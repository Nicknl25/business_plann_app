"""Shared GPT wire for solver-side Responses-API turns.

Phase 4 dead-layer deletion (fallback-class fix): the Phase-3 schema
chokepoint `call_gpt_with_schema_or_fallback` had ZERO live callers (the
three Phase 3 consultants were retired in P3.5; the GPT exhaustion
handler is a no-GPT stub) and was deleted, along with the dormant
per-run GPT call budget it enforced. The ONE live caller of this module
is the funding handler's tool-calling session
(post_intake_funding_handler/tool_calling_session.py), which uses
`call_gpt_responses_api_turn` and bounds itself with its own
HARD_CAP_TOOL_CALLS.

Failure semantics: network faults are retried by
_network_retry.call_with_retries; exhaustion/HTTP/JSON failures return a
structured fallback decision_source. Under the fail-loud doctrine the
CALLER decides what a fallback means — the funding session raises
PostIntakePreconditionFailed on any non-success decision_source
(convergence_test_mode_enabled defaults ON), so a fallback fails the
run loudly and the supervisor reruns it.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


def _emit_gpt_io_trace(**kwargs: Any) -> None:
  """Best-effort bridge to the L-4 handler-trace sink. Captures OpenAI
  turn telemetry (latency, token usage, error context) per call so a
  mid-run crash still leaves the per-call trace durable. Never raises —
  instrumentation must not break the GPT chokepoint."""
  try:
    from client_intake_and_finmo.post_intake_handler_traces import (  # type: ignore
      record_gpt_io,
    )
    record_gpt_io(**kwargs)
  except Exception:
    pass


_DEFAULT_OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
_DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
_DEFAULT_TIMEOUT_SECONDS = 45.0



_gpt_call_state_lock = threading.Lock()
_gpt_call_log: List[Dict[str, Any]] = []


def reset_gpt_call_log() -> None:
  """Reset the per-run GPT call log. Called at the start of each
  planning run by the orchestrator."""
  global _gpt_call_log
  with _gpt_call_state_lock:
    _gpt_call_log = []


def get_gpt_call_log() -> List[Dict[str, Any]]:
  with _gpt_call_state_lock:
    return [dict(entry) for entry in _gpt_call_log]


def _record_gpt_call(
  consultant_name: str,
  decision_source: str,
  *,
  counted_against_run_budget: bool = True,
) -> None:
  """Log a GPT call (telemetry only — the run-wide budget is retired;
  the flag is kept in the log for continuity of the historical shape)."""
  global _gpt_call_log
  with _gpt_call_state_lock:
    _gpt_call_log.append({
      "consultant_name": str(consultant_name or ""),
      "call_index": None,
      "decision_source": str(decision_source or ""),
      "counted_against_run_budget": bool(counted_against_run_budget),
    })


def _resolve_api_key() -> Optional[str]:
  raw = os.getenv("OPENAI_API_KEY") or ""
  raw = raw.strip()
  return raw or None


def _resolve_model() -> str:
  raw = (os.getenv("OPENAI_MODEL_FOR_SOLVER_CONSULTANTS") or "").strip()
  if raw:
    return raw
  raw = (os.getenv("OPENAI_MODEL") or "").strip()
  return raw or _DEFAULT_OPENAI_MODEL


def _parse_responses_json_dict(raw: Dict[str, Any]) -> Dict[str, Any]:
  """Extract the first JSON object from an OpenAI Responses API payload."""
  if not isinstance(raw, dict):
    return {}
  output = raw.get("output")
  if isinstance(output, list):
    for item in output:
      if not isinstance(item, dict):
        continue
      content = item.get("content")
      if not isinstance(content, list):
        continue
      for block in content:
        if not isinstance(block, dict):
          continue
        text = block.get("text")
        if not isinstance(text, str) or not text.strip():
          continue
        try:
          parsed = json.loads(text)
          if isinstance(parsed, dict):
            return parsed
        except Exception:
          continue
  text = raw.get("output_text")
  if isinstance(text, str) and text.strip():
    try:
      parsed = json.loads(text)
      if isinstance(parsed, dict):
        return parsed
    except Exception:
      return {}
  return {}


# ----------------------------------------------------------------------------
# Phase 9 P3.5 — Responses API tool-calling variant.
#
# call_gpt_responses_api_turn issues one Responses-API turn against an
# already-built input array. The caller (the GPT exhaustion handler's
# tool-calling session) owns the conversation: it appends function_call
# items returned by the model, runs the tool locally, appends
# function_call_output items, and re-invokes this function for the next
# turn. Each invocation is logged via _record_gpt_call (telemetry only;
# the session bounds itself with HARD_CAP_TOOL_CALLS).
#
# When tools=None is passed, this acts as a final-commit forcer: the
# model has no tool to call so its only option is to emit a strict
# json_schema-conformant assistant message.
# ----------------------------------------------------------------------------


def call_gpt_responses_api_turn(
  *,
  consultant_name: str,
  input_items: List[Dict[str, Any]],
  tools: Optional[List[Dict[str, Any]]],
  response_schema: Optional[Dict[str, Any]],
  schema_name: Optional[str],
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
  counts_against_run_budget: bool = True,
) -> Dict[str, Any]:
  """Issue one OpenAI Responses API turn.

  Parameters
  ----------
  consultant_name
    Logged for budget tracking; conventionally the session label (e.g.,
    "post_intake_gpt_exhaustion_handler_tool_call_turn_3").
  input_items
    Full conversation history to send. Items may be:
      - {"role": "system"|"user"|"assistant", "content": [{"type": "input_text", "text": ...}]}
      - assistant_message items returned previously
      - function_call items returned previously
      - {"type": "function_call_output", "call_id": ..., "output": ...}
    The caller is responsible for assembling this list.
  tools
    Optional list of tool definitions in Responses API format
    ({type: function, name, description, parameters, strict}). Pass
    None to force a final assistant-message answer.
  response_schema
    Optional strict JSON schema constraining the assistant text output
    when the model emits one. None = no schema constraint.
  schema_name
    Schema name shown in the json_schema format declaration.

  Returns
  -------
  Dict with keys:
    - "tool_calls": List[Dict[str, Any]] — function_call items the model
        emitted this turn. Each carries {"id", "call_id", "name",
        "arguments"} with arguments still as a JSON string.
    - "assistant_message_text": Optional[str] — final text content if
        the model emitted an assistant message instead of tool calls.
    - "parsed_assistant_json": Optional[Dict[str, Any]] — assistant_
        message_text parsed as JSON when present and valid.
    - "raw_assistant_items": List[Dict[str, Any]] — the raw output
        items so the caller can append them verbatim to the next turn's
        input (Responses API requires assistant turns to round-trip
        unchanged).
    - "raw_openai_response", "decision_source", "detail", "model_used"
        — decision_source is python_proposer_plus_gpt_critic on
        success, else a python_proposer_only_critic_* fallback tag.
  """
  api_key = _resolve_api_key()
  if not api_key:
    _record_gpt_call(
      consultant_name,
      "python_proposer_only_no_api_key",
      counted_against_run_budget=counts_against_run_budget,
    )
    return {
      "tool_calls": [],
      "assistant_message_text": None,
      "parsed_assistant_json": None,
      "raw_assistant_items": [],
      "raw_openai_response": {},
      "decision_source": "python_proposer_only_no_api_key",
      "detail": "OPENAI_API_KEY environment variable is not set.",
      "model_used": "",
    }
  model = _resolve_model()
  payload: Dict[str, Any] = {
    "model": model,
    "temperature": 0.0,
    "input": list(input_items or []),
  }
  if tools:
    payload["tools"] = list(tools)
  if isinstance(response_schema, dict) and response_schema:
    payload["text"] = {
      "format": {
        "type": "json_schema",
        "name": str(schema_name or consultant_name),
        "strict": True,
        "schema": response_schema,
      }
    }
  headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
  }
  # Phase 9 P3.10 Commit 1 — route the tool-calling chokepoint through
  # the same retry primitive. On retry exhaustion this raises a
  # structured NetworkRetryExhausted; for Commit 1 the chokepoint
  # surfaces it as a decision_source dict (preserving Phase-3 critic
  # semantics where Python-floor fallback exists). Commit 2 converts
  # the receiving end (the tool-calling session loop) to a hard-fail
  # because no Python floor exists for the exhaustion handler.
  #
  # Q2: failed network calls (NetworkRetryExhausted) do NOT consume the
  # GPT call budget — _record_gpt_call is intentionally NOT invoked on
  # that branch. Only successful HTTP responses count.
  from client_intake_and_finmo.post_intake_solver._network_retry import (  # type: ignore
    NetworkRetryExhausted,
    NonRetriableHTTPError,
    call_with_retries,
  )

  def _do_request():
    # DETERMINISM — route through post_openai_with_retries so this call
    # rides the GPT RESPONSE LOCK (run-once-and-lock). This IO layer
    # previously posted directly via session.post, BYPASSING the lock —
    # every handler/critic built on it (funding handler tool sessions,
    # exhaustion-handler critics) made a fresh live GPT call on every
    # run. Invisible for years because these paths only engage when a
    # validator pops, and healthy businesses never popped; Cedar's
    # judged capital structure engaged the funding handler and produced
    # three different outcomes from three byte-identical runs.
    # max_attempts=1: the outer call_with_retries owns retry semantics;
    # the inner call contributes only lock lookup/replay/save.
    from client_intake_and_finmo.openai_http import (  # type: ignore
      post_openai_with_retries as _locked_post,
    )
    return _locked_post(
      url=_DEFAULT_OPENAI_RESPONSES_URL,
      headers=headers,
      payload=payload,
      timeout_seconds=float(timeout_seconds),
      retryable_status=(),
      max_attempts=1,
    )

  _io_t0 = time.monotonic()
  _io_request_summary = {
    "input_item_count": len(input_items or []),
    "input_chars": sum(
      len(json.dumps(it, default=str)) for it in (input_items or [])
    ),
    "tool_count": len(tools or []),
    "tool_names": [
      str((t or {}).get("name") or "") for t in (tools or [])
    ],
  }
  try:
    resp = call_with_retries(
      _do_request,
      endpoint=_DEFAULT_OPENAI_RESPONSES_URL,
    )
  except NetworkRetryExhausted as exc:
    logger.error(
      "post_intake_solver:%s_critic_network_retry_exhausted: %s",
      consultant_name, exc,
    )
    _emit_gpt_io_trace(
      consultant_name=consultant_name,
      decision_source="python_proposer_only_critic_network_retry_exhausted",
      model=model,
      elapsed_ms=int((time.monotonic() - _io_t0) * 1000.0),
      error=exc.to_dict() if hasattr(exc, "to_dict") else {"detail": str(exc)[:500]},
      request_summary=_io_request_summary,
      raw_request=payload,
    )
    return {
      "tool_calls": [],
      "assistant_message_text": None,
      "parsed_assistant_json": None,
      "raw_assistant_items": [],
      "raw_openai_response": {"network_retry_exhausted": exc.to_dict()},
      "decision_source": "python_proposer_only_critic_network_retry_exhausted",
      "detail": str(exc)[:500],
      "model_used": model,
      "network_retry_exhausted": exc.to_dict(),
    }
  except NonRetriableHTTPError as exc:
    logger.warning(
      "post_intake_solver:%s_critic_http_error: status=%s body=%s",
      consultant_name, exc.status_code, exc.body_text[:200],
    )
    _record_gpt_call(
      consultant_name,
      "python_proposer_only_critic_http_error",
      counted_against_run_budget=counts_against_run_budget,
    )
    return {
      "tool_calls": [],
      "assistant_message_text": None,
      "parsed_assistant_json": None,
      "raw_assistant_items": [],
      "raw_openai_response": {"status": exc.status_code, "body": exc.body_text},
      "decision_source": "python_proposer_only_critic_http_error",
      "detail": f"http_status_{exc.status_code}",
      "model_used": model,
    }
  status = int(getattr(resp, "status_code", 0) or 0)
  body_text = str(getattr(resp, "text", "") or "")[:4000]
  if status >= 400:
    logger.warning(
      "post_intake_solver:%s_critic_http_error: status=%s body=%s",
      consultant_name, status, body_text[:200],
    )
    _record_gpt_call(
      consultant_name,
      "python_proposer_only_critic_http_error",
      counted_against_run_budget=counts_against_run_budget,
    )
    return {
      "tool_calls": [],
      "assistant_message_text": None,
      "parsed_assistant_json": None,
      "raw_assistant_items": [],
      "raw_openai_response": {"status": status, "body": body_text},
      "decision_source": "python_proposer_only_critic_http_error",
      "detail": f"http_status_{status}",
      "model_used": model,
    }
  try:
    raw = resp.json() if isinstance(resp.json(), dict) else {"response": body_text}
  except Exception as exc:
    logger.warning("post_intake_solver:%s_critic_invalid_json: %s", consultant_name, exc)
    _record_gpt_call(
      consultant_name,
      "python_proposer_only_critic_invalid_json",
      counted_against_run_budget=counts_against_run_budget,
    )
    return {
      "tool_calls": [],
      "assistant_message_text": None,
      "parsed_assistant_json": None,
      "raw_assistant_items": [],
      "raw_openai_response": {"response": body_text},
      "decision_source": "python_proposer_only_critic_invalid_json",
      "detail": "response_body_not_json",
      "model_used": model,
    }

  tool_calls: List[Dict[str, Any]] = []
  assistant_text: Optional[str] = None
  raw_assistant_items: List[Dict[str, Any]] = []
  output = raw.get("output") if isinstance(raw, dict) else None
  if isinstance(output, list):
    for item in output:
      if not isinstance(item, dict):
        continue
      raw_assistant_items.append(copy.deepcopy(item))
      itype = str(item.get("type") or "").strip()
      if itype == "function_call":
        tool_calls.append({
          "id": str(item.get("id") or "").strip(),
          "call_id": str(item.get("call_id") or "").strip(),
          "name": str(item.get("name") or "").strip(),
          "arguments": item.get("arguments") or "",
        })
        continue
      content = item.get("content")
      if isinstance(content, list):
        for block in content:
          if not isinstance(block, dict):
            continue
          text = block.get("text")
          if isinstance(text, str) and text.strip():
            assistant_text = (assistant_text or "") + text
  if assistant_text is None:
    text_from_top = raw.get("output_text") if isinstance(raw, dict) else None
    if isinstance(text_from_top, str) and text_from_top.strip():
      assistant_text = text_from_top

  parsed_assistant_json: Optional[Dict[str, Any]] = None
  if isinstance(assistant_text, str) and assistant_text.strip():
    try:
      candidate = json.loads(assistant_text)
      if isinstance(candidate, dict):
        parsed_assistant_json = candidate
    except Exception:
      parsed_assistant_json = None

  _record_gpt_call(
    consultant_name,
    "python_proposer_plus_gpt_critic",
    counted_against_run_budget=counts_against_run_budget,
  )
  _emit_gpt_io_trace(
    consultant_name=consultant_name,
    decision_source="python_proposer_plus_gpt_critic",
    model=model,
    elapsed_ms=int((time.monotonic() - _io_t0) * 1000.0),
    usage=(raw.get("usage") if isinstance(raw, dict) else None) or {},
    tool_call_names=[str(tc.get("name") or "") for tc in tool_calls],
    request_summary=_io_request_summary,
    raw_request=payload,
    raw_response=raw,
  )
  return {
    "tool_calls": tool_calls,
    "assistant_message_text": assistant_text,
    "parsed_assistant_json": parsed_assistant_json,
    "raw_assistant_items": raw_assistant_items,
    "raw_openai_response": copy.deepcopy(raw),
    "decision_source": "python_proposer_plus_gpt_critic",
    "detail": "",
    "model_used": model,
  }
