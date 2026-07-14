"""Shared GPT chokepoint for solver-side GPT calls.

Phase 9 P3.5 — the three Phase 3 consultants (band shaping, target
shaping, conflict adjudication) that originally called this chokepoint
have been retired. Their per-scope GPT amendments to `envelope_payload`
and `targets_payload` placed GPT inside the deterministic solver loop,
which the Phase 9 P3 architecture explicitly rules out. This module
remains in place because the GPT exhaustion handler
(``post_intake_gpt_exhaustion_handler``) routes its Call 1 / Call 2 /
iteration GPT calls through the same wire pattern.

Wire pattern (every caller):

  1. Check OPENAI_API_KEY availability. When absent, return immediately
     with decision_source=`python_proposer_only_no_api_key`.
  2. Build an OpenAI Responses-API payload with the supplied system
     prompt, a user JSON-encoded context, and the supplied strict JSON
     schema.
  3. Call OpenAI via post_openai_with_retries. Catch every exception
     class and translate to a structured fallback (timeout, http_error,
     invalid_json, unexpected_error). Never raise.
  4. Return {parsed, raw_openai_response, decision_source, detail} so
     the caller can apply corrections (or fall back to its proposal).

This module is intentionally tiny and dependency-light — the heavy
lifting (schema construction, prompt building, correction application)
is each caller's responsibility.
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
# Phase 6 Step 2 — reproducible-output seed. temperature=0 minimizes but does
# not eliminate OpenAI's sampling variance; the seed parameter (combined with
# temperature=0) gives reproducible outputs across calls.
#
# Phase 9 P3.5 — NOT USED by the current Responses-API caller path. The
# OpenAI Responses API rejects the `seed` parameter with HTTP 400
# (`unknown_parameter`); see the payload assembly below. Constant
# preserved at module scope only for any future Chat-Completions-API
# caller that does support seed. The current chokepoint omits it.
_PHASE_3_CONSULTANT_SEED = 1729


# ----------------------------------------------------------------------------
# Phase 9 Phase H — GPT call budget per planning run.
#
# Doctrine Q4: maximum 4 GPT calls per planning run, hard runtime cap.
# Allocation: 1 band shaping batch, 1 target shaping batch, 1 conflict
# adjudication batch, 1 final realism critique on assembled plan.
#
# The cap is enforced at this single chokepoint (call_gpt_with_schema_or_fallback)
# rather than scattered across consultants — every Phase 3 GPT call routes
# through here. When the budget is exhausted, the call returns the standard
# "python_proposer_only" fallback so the consultant's existing fallback path
# applies its Python-only proposal. No exceptions, no broken runs.
# ----------------------------------------------------------------------------

# Phase 9 P3.5 — budget raised from 4 to 8 to accommodate the GPT
# exhaustion handler. Allocation under P3.5:
#   - 1 band shaping batch, 1 target shaping batch, 1 conflict
#     adjudication batch, 1 final realism critique on assembled plan
#     (the original 4 Phase H slots).
#   - Up to 3 GPT exhaustion handler calls: 1 EBITDA-anchor call,
#     1 driver-anchor call, and up to 3 iteration calls (sharing a
#     budget within this handler — capped to 5 total handler-side
#     calls in practice, gated by the handler's own MAX_ITERATIONS).
#   - Cash strategy GPT review continues to draw from this pool when
#     it fires.
# Worst-case ceiling: 4 (Phase H) + 5 (P3.5 handler) = 9; in practice
# the handler stops at LANDED earlier, and the 8-call budget covers the
# realistic envelope. Calls beyond 8 fall back to Python deterministic
# proposers, which is the safe degradation path.
_GPT_CALL_BUDGET_PER_RUN = 8
_gpt_call_state_lock = threading.Lock()
_gpt_call_count: int = 0
_gpt_call_log: List[Dict[str, Any]] = []


def reset_gpt_call_budget() -> None:
  """Reset the per-run GPT call counter. Called at the start of each
  planning run by the orchestrator (run_target_seeking_orchestrated_system_run)."""
  global _gpt_call_count, _gpt_call_log
  with _gpt_call_state_lock:
    _gpt_call_count = 0
    _gpt_call_log = []


def get_gpt_call_count() -> int:
  with _gpt_call_state_lock:
    return int(_gpt_call_count)


def get_gpt_call_log() -> List[Dict[str, Any]]:
  with _gpt_call_state_lock:
    return [dict(entry) for entry in _gpt_call_log]


def _record_gpt_call(
  consultant_name: str,
  decision_source: str,
  *,
  counted_against_run_budget: bool = True,
) -> None:
  """Record a GPT call. Always logs; only increments the run-wide
  counter when counted_against_run_budget=True.

  Phase 9 P3.10 iter 17 (Batch A) — the GPT-exhaustion handler's
  tool-calling session passes counted_against_run_budget=False so its
  internal tool rounds (constrained by the handler's own
  HARD_CAP_TOOL_CALLS=10 budget) do not consume the run-wide
  _GPT_CALL_BUDGET_PER_RUN=8 budget reserved for regular critique
  calls. Visibility into actual handler usage is preserved via the
  log entry's counted_against_run_budget flag.
  """
  global _gpt_call_count, _gpt_call_log
  with _gpt_call_state_lock:
    if counted_against_run_budget:
      _gpt_call_count += 1
      call_index = _gpt_call_count
    else:
      call_index = None
    _gpt_call_log.append({
      "consultant_name": str(consultant_name or ""),
      "call_index": call_index,
      "decision_source": str(decision_source or ""),
      "counted_against_run_budget": bool(counted_against_run_budget),
    })


def _budget_exhausted() -> bool:
  with _gpt_call_state_lock:
    return _gpt_call_count >= _GPT_CALL_BUDGET_PER_RUN


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


def call_gpt_with_schema_or_fallback(
  *,
  consultant_name: str,
  system_prompt: str,
  user_context: Dict[str, Any],
  response_schema: Dict[str, Any],
  schema_name: str,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
  """Invoke OpenAI Responses API with a strict-JSON-schema constraint.

  Returns:
    {
      "parsed": Optional[Dict[str, Any]],   # parsed JSON when call succeeded
      "raw_openai_response": Dict[str, Any],
      "decision_source": str,               # see below
      "detail": str,
      "model_used": str,
    }

  decision_source values:
    - "python_proposer_only_no_api_key"
    - "python_proposer_plus_gpt_critic"
    - "python_proposer_only_critic_http_error"
    - "python_proposer_only_critic_invalid_json"
    - "python_proposer_only_critic_network_retry_exhausted"  (Phase 9 P3.10)

  Never raises (Commit 1 of Phase 9 P3.10 — the chokepoint preserves
  the Phase-3 critic contract for sites with a valid Python floor; the
  exhaustion-handler call site (which has no floor) gets its own
  hard-fail conversion in Commits 2-5).

  Phase 9 P3.10 — network failures (DNS, timeout, connection, HTTP
  429/5xx) now retry up to 2 times via the _network_retry primitive
  with exponential backoff (1s, 2s). HTTP 429 honors Retry-After when
  present. On retry exhaustion the call returns decision_source=
  "python_proposer_only_critic_network_retry_exhausted" with the full
  attempt log in raw_openai_response and detail. Per Q2: retry-exhausted
  calls do NOT consume the GPT call budget; only successful HTTP
  responses do.
  """
  # Phase 9 Phase H — enforce 4-call budget per planning run.
  if _budget_exhausted():
    _record_gpt_call(consultant_name, "python_proposer_only_budget_exhausted")
    return {
      "parsed": None,
      "raw_openai_response": {},
      "decision_source": "python_proposer_only_budget_exhausted",
      "detail": (
        f"gpt_call_budget_exhausted: {_GPT_CALL_BUDGET_PER_RUN} "
        f"calls already issued in this planning run; subsequent "
        f"consultants fall back to Python proposal."
      ),
      "model_used": "",
    }
  api_key = _resolve_api_key()
  if not api_key:
    _record_gpt_call(consultant_name, "python_proposer_only_no_api_key")
    return {
      "parsed": None,
      "raw_openai_response": {},
      "decision_source": "python_proposer_only_no_api_key",
      "detail": "OPENAI_API_KEY environment variable is not set.",
      "model_used": "",
    }
  model = _resolve_model()
  # NOTE: the OpenAI Responses API does not accept the `seed` parameter
  # (only Chat Completions does). Phase 9 P3.5 surfaced this as the
  # cause of every consultant falling back to "python_proposer_only_
  # critic_http_error" with status=400 unknown parameter 'seed'. The
  # _PHASE_3_CONSULTANT_SEED constant is preserved at module scope for
  # any future Chat-Completions-API caller; the Responses payload
  # simply omits it. temperature=0 still suppresses most of the
  # variance.
  payload = {
    "model": model,
    "temperature": 0.0,
    "input": [
      {
        "role": "system",
        "content": [{"type": "input_text", "text": str(system_prompt or "").strip()}],
      },
      {
        "role": "user",
        "content": [
          {"type": "input_text", "text": json.dumps(user_context or {}, ensure_ascii=False)}
        ],
      },
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": str(schema_name or consultant_name),
        "strict": True,
        "schema": response_schema,
      }
    },
  }
  headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
  }
  # Phase 9 P3.10 Commit 1 — route every OpenAI call through the
  # network retry primitive. Transient failures (DNS, timeout, 429,
  # 5xx) retry up to 2 times with exponential backoff (1s, 2s); HTTP
  # 429 honors Retry-After when present. Non-retriable HTTP statuses
  # (400/401/403/404) and retry exhaustion raise structured exceptions
  # that the caller surfaces as the existing decision_source dict (this
  # commit) — Commit 2+ converts those to hard-fails at sites without a
  # Python floor. Per Q2: network-retry-exhausted calls do NOT consume
  # the GPT call budget; only successful HTTP responses do.
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
    return {
      "parsed": None,
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
    _record_gpt_call(consultant_name, "python_proposer_only_critic_http_error")
    return {
      "parsed": None,
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
    _record_gpt_call(consultant_name, "python_proposer_only_critic_http_error")
    return {
      "parsed": None,
      "raw_openai_response": {"status": status, "body": body_text},
      "decision_source": "python_proposer_only_critic_http_error",
      "detail": f"http_status_{status}",
      "model_used": model,
    }
  try:
    raw = resp.json() if isinstance(resp.json(), dict) else {"response": body_text}
  except Exception as exc:
    logger.warning("post_intake_solver:%s_critic_invalid_json: %s", consultant_name, exc)
    _record_gpt_call(consultant_name, "python_proposer_only_critic_invalid_json")
    return {
      "parsed": None,
      "raw_openai_response": {"response": body_text},
      "decision_source": "python_proposer_only_critic_invalid_json",
      "detail": "response_body_not_json",
      "model_used": model,
    }
  parsed = _parse_responses_json_dict(raw)
  if not parsed:
    logger.warning("post_intake_solver:%s_critic_invalid_json: no parseable json in response", consultant_name)
    _record_gpt_call(consultant_name, "python_proposer_only_critic_invalid_json")
    return {
      "parsed": None,
      "raw_openai_response": copy.deepcopy(raw),
      "decision_source": "python_proposer_only_critic_invalid_json",
      "detail": "no_parseable_json_in_response",
      "model_used": model,
    }
  _record_gpt_call(consultant_name, "python_proposer_plus_gpt_critic")
  return {
    "parsed": parsed,
    "raw_openai_response": copy.deepcopy(raw),
    "decision_source": "python_proposer_plus_gpt_critic",
    "detail": "",
    "model_used": model,
  }


# ----------------------------------------------------------------------------
# Phase 9 P3.5 — Responses API tool-calling variant.
#
# call_gpt_responses_api_turn issues one Responses-API turn against an
# already-built input array. The caller (the GPT exhaustion handler's
# tool-calling session) owns the conversation: it appends function_call
# items returned by the model, runs the tool locally, appends
# function_call_output items, and re-invokes this function for the next
# turn. Each invocation counts as ONE GPT call against the per-run
# budget enforced by _budget_exhausted / _record_gpt_call.
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
        as in call_gpt_with_schema_or_fallback.
  """
  # Phase 9 P3.10 iter 17 (Batch A) — when counts_against_run_budget
  # is False, the run-wide _GPT_CALL_BUDGET_PER_RUN cap is bypassed.
  # The handler's tool-calling session passes False because its rounds
  # are bounded by HARD_CAP_TOOL_CALLS=10 inside the session itself —
  # the run-wide 8-call budget covers regular critique calls only.
  if counts_against_run_budget and _budget_exhausted():
    _record_gpt_call(
      consultant_name,
      "python_proposer_only_budget_exhausted",
      counted_against_run_budget=True,
    )
    return {
      "tool_calls": [],
      "assistant_message_text": None,
      "parsed_assistant_json": None,
      "raw_assistant_items": [],
      "raw_openai_response": {},
      "decision_source": "python_proposer_only_budget_exhausted",
      "detail": (
        f"gpt_call_budget_exhausted: {_GPT_CALL_BUDGET_PER_RUN} "
        f"calls already issued in this planning run."
      ),
      "model_used": "",
    }
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
