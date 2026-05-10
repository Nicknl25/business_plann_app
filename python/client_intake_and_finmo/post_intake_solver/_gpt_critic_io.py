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
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


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


def _record_gpt_call(consultant_name: str, decision_source: str) -> None:
  global _gpt_call_count, _gpt_call_log
  with _gpt_call_state_lock:
    _gpt_call_count += 1
    _gpt_call_log.append({
      "consultant_name": str(consultant_name or ""),
      "call_index": _gpt_call_count,
      "decision_source": str(decision_source or ""),
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
    - "python_proposer_only_critic_timeout"
    - "python_proposer_only_critic_http_error"
    - "python_proposer_only_critic_invalid_json"
    - "python_proposer_only_critic_unexpected_error"

  Never raises. The orchestrator treats anything other than
  python_proposer_plus_gpt_critic as "Python proposal stands as the
  safety floor" and tags affected entries with calibration_source=
  uncalibrated_due_to_gpt_failure.
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
  try:
    from client_intake_and_finmo.openai_http import post_openai_with_retries  # type: ignore
    resp = post_openai_with_retries(
      url=_DEFAULT_OPENAI_RESPONSES_URL,
      headers=headers,
      payload=payload,
      timeout_seconds=float(timeout_seconds),
      retryable_status=(429, 500, 502, 503, 504),
      max_attempts=3,
    )
  except TimeoutError as exc:
    logger.warning("post_intake_solver:%s_critic_timeout: %s", consultant_name, exc)
    _record_gpt_call(consultant_name, "python_proposer_only_critic_timeout")
    return {
      "parsed": None,
      "raw_openai_response": {},
      "decision_source": "python_proposer_only_critic_timeout",
      "detail": f"timeout_after_{timeout_seconds:.1f}s",
      "model_used": model,
    }
  except Exception as exc:
    logger.warning("post_intake_solver:%s_critic_unexpected_error: %s", consultant_name, exc)
    _record_gpt_call(consultant_name, "python_proposer_only_critic_unexpected_error")
    return {
      "parsed": None,
      "raw_openai_response": {},
      "decision_source": "python_proposer_only_critic_unexpected_error",
      "detail": str(exc)[:200],
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
