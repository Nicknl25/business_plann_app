"""Shared GPT critic IO for the Phase 3 consultants.

Each Phase 3 consultant (band shaping, target shaping, conflict adjudication)
calls a deterministic Python proposer first, then optionally calls GPT to
critique or adjudicate. All three follow the same wire pattern:

  1. Check OPENAI_API_KEY availability. When absent, return immediately with
     decision_source=`python_proposer_only_no_api_key`. The orchestrator
     never blocks on GPT availability — Python defaults stand.
  2. Build an OpenAI Responses-API payload with the supplied system prompt,
     a user JSON-encoded context, and the supplied strict JSON schema.
  3. Call OpenAI via post_openai_with_retries. Catch every exception class
     and translate to a structured fallback (timeout, http_error,
     invalid_json, unexpected_error). Never raise.
  4. Return {parsed, raw_openai_response, decision_source, detail} so the
     consultant can apply corrections (or fall back to its proposal).

This module is intentionally tiny and dependency-light — the heavy lifting
(schema construction, prompt building, correction application) is each
consultant's responsibility.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


_DEFAULT_OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
_DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
_DEFAULT_TIMEOUT_SECONDS = 45.0
# Phase 6 Step 2 — reproducible-output seed. temperature=0 minimizes but does
# not eliminate OpenAI's sampling variance; the seed parameter (combined with
# temperature=0) gives reproducible outputs across calls. Phase 3 consultants
# run per-scope (per-lever / per-metric / per-conflict) and the diagnostic
# value of "same scope key → same GPT amendment across runs" is high.
_PHASE_3_CONSULTANT_SEED = 1729


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
  api_key = _resolve_api_key()
  if not api_key:
    return {
      "parsed": None,
      "raw_openai_response": {},
      "decision_source": "python_proposer_only_no_api_key",
      "detail": "OPENAI_API_KEY environment variable is not set.",
      "model_used": "",
    }
  model = _resolve_model()
  payload = {
    "model": model,
    "temperature": 0.0,
    "seed": _PHASE_3_CONSULTANT_SEED,
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
    return {
      "parsed": None,
      "raw_openai_response": {},
      "decision_source": "python_proposer_only_critic_timeout",
      "detail": f"timeout_after_{timeout_seconds:.1f}s",
      "model_used": model,
    }
  except Exception as exc:
    logger.warning("post_intake_solver:%s_critic_unexpected_error: %s", consultant_name, exc)
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
    return {
      "parsed": None,
      "raw_openai_response": copy.deepcopy(raw),
      "decision_source": "python_proposer_only_critic_invalid_json",
      "detail": "no_parseable_json_in_response",
      "model_used": model,
    }
  return {
    "parsed": parsed,
    "raw_openai_response": copy.deepcopy(raw),
    "decision_source": "python_proposer_plus_gpt_critic",
    "detail": "",
    "model_used": model,
  }
