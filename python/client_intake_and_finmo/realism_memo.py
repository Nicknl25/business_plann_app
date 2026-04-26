from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

import requests
try:
  from openai_http import post_openai_with_retries  # type: ignore
except Exception:
  from client_intake_and_finmo.openai_http import post_openai_with_retries  # type: ignore


PROMPTS_DIR = Path(__file__).resolve().parent / "prompts" / "realism_memo"
REALISM_MEMO_REVIEWER_PROMPT_PATH = PROMPTS_DIR / "reviewer.md"
REALISM_MEMO_GRID_ADVISORY_PROMPT_PATH = PROMPTS_DIR / "grid_advisory.md"
_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
_REALISM_ISSUE_CODES = [
  "capacity_revenue_mismatch",
  "cost_structure_mismatch",
  "working_capital_payment_model_mismatch",
]


def empty_realism_memo_payload() -> Dict[str, Any]:
  return {
    "status": "not_generated",
    "issues": [],
  }


def failed_realism_memo_payload() -> Dict[str, Any]:
  return {
    "status": "failed",
    "issues": [],
  }


def _normalize_issue_text(value: Any) -> str:
  return str(value or "").strip()


def _normalize_issue_code(value: Any) -> str:
  code = str(value or "").strip().lower()
  return code if code in _REALISM_ISSUE_CODES else ""


def is_valid_realism_memo_payload(payload: Any) -> bool:
  if not isinstance(payload, dict):
    return False
  issues = payload.get("issues")
  if not isinstance(issues, list):
    return False
  if len(issues) > 4:
    return False
  for item in issues:
    if not isinstance(item, dict):
      return False
    issue_code = _normalize_issue_code(item.get("issue_code"))
    issue = _normalize_issue_text(item.get("issue"))
    detail = _normalize_issue_text(item.get("detail"))
    if not issue_code or not issue or not detail:
      return False
  return True


def normalize_realism_memo_payload(payload: Any) -> Dict[str, Any]:
  if not isinstance(payload, dict):
    return empty_realism_memo_payload()
  status = str(payload.get("status") or "").strip() or "ready"
  raw_issues = payload.get("issues")
  issues_out: List[Dict[str, str]] = []
  if isinstance(raw_issues, list):
    for item in raw_issues:
      if not isinstance(item, dict):
        continue
      issue_code = _normalize_issue_code(item.get("issue_code"))
      issue = _normalize_issue_text(item.get("issue"))
      detail = _normalize_issue_text(item.get("detail"))
      if not issue_code or not issue or not detail:
        continue
      issues_out.append({"issue_code": issue_code, "issue": issue, "detail": detail})
      if len(issues_out) >= 4:
        break
  return {
    "status": status,
    "issues": issues_out,
  }


def load_realism_memo_reviewer_prompt() -> str:
  return REALISM_MEMO_REVIEWER_PROMPT_PATH.read_text(encoding="utf-8").strip()


def load_realism_memo_grid_advisory_prompt() -> str:
  return REALISM_MEMO_GRID_ADVISORY_PROMPT_PATH.read_text(encoding="utf-8").strip()


def _require_openai_key() -> str:
  key = (os.getenv("OPENAI_API_KEY") or "").strip()
  if not key:
    raise RuntimeError("OPENAI_API_KEY is not configured.")
  return key


def _realism_memo_model() -> str:
  return (
    os.getenv("REALISM_MEMO_MODEL")
    or os.getenv("OPENAI_MODEL")
    or "gpt-5.1"
  ).strip() or "gpt-5.1"


def _timeout_seconds() -> None:
  return None


def _post_openai(*, url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> requests.Response:
  timeout = _timeout_seconds()
  return post_openai_with_retries(
    url=url,
    headers=headers,
    payload=payload,
    timeout_seconds=timeout,
    retryable_status=_RETRYABLE_STATUS,
    max_attempts=2,
  )


def _parse_json_response(data: Dict[str, Any]) -> Dict[str, Any]:
  for item in data.get("output") or []:
    if not isinstance(item, dict):
      continue
    for part in item.get("content") or []:
      if not isinstance(part, dict):
        continue
      parsed = part.get("parsed")
      if isinstance(parsed, dict):
        return parsed
      raw = str(part.get("text") or "").strip()
      if not raw:
        continue
      try:
        parsed = json.loads(raw)
      except Exception:
        continue
      if isinstance(parsed, dict):
        return parsed
  return {}


def realism_memo_schema() -> Dict[str, Any]:
  return {
    "name": "realism_memo",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "status": {
          "type": "string",
          "enum": ["ready"],
        },
        "issues": {
          "type": "array",
          "maxItems": 4,
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "issue": {"type": "string"},
              "issue_code": {"type": "string", "enum": _REALISM_ISSUE_CODES},
              "detail": {"type": "string"},
            },
            "required": ["issue_code", "issue", "detail"],
          },
        },
      },
      "required": ["status", "issues"],
    },
    "strict": True,
  }


def build_realism_memo_input(
  *,
  ops_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  solved_model_input_json: Dict[str, Any] | None = None,
  solved_finmo_json: Dict[str, Any] | None = None,
) -> str:
  return (
    "Business operating context (ops_json):\n"
    + json.dumps(ops_json if isinstance(ops_json, dict) else {}, ensure_ascii=False)
    + "\n\nBusiness financial context (financials_json):\n"
    + json.dumps(financials_json if isinstance(financials_json, dict) else {}, ensure_ascii=False)
    + "\n\nSolved model input context (solved_model_input_json):\n"
    + json.dumps(solved_model_input_json if isinstance(solved_model_input_json, dict) else {}, ensure_ascii=False)
    + "\n\nSolved finmo context (solved_finmo_json):\n"
    + json.dumps(solved_finmo_json if isinstance(solved_finmo_json, dict) else {}, ensure_ascii=False)
  )


def generate_realism_memo_payload(
  *,
  ops_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  solved_model_input_json: Dict[str, Any] | None = None,
  solved_finmo_json: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
  api_key = _require_openai_key()
  headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
  }
  payload = {
    "model": _realism_memo_model(),
    "input": [
      {
        "role": "system",
        "content": [{"type": "input_text", "text": load_realism_memo_reviewer_prompt()}],
      },
      {
        "role": "user",
        "content": [
          {
            "type": "input_text",
            "text": build_realism_memo_input(
              ops_json=ops_json,
              financials_json=financials_json,
              solved_model_input_json=solved_model_input_json,
              solved_finmo_json=solved_finmo_json,
            ),
          }
        ],
      },
    ],
    "text": {
      "format": {
        "type": "json_schema",
        **realism_memo_schema(),
      }
    },
  }
  response = _post_openai(
    url="https://api.openai.com/v1/responses",
    headers=headers,
    payload=payload,
  )
  if response.status_code >= 400:
    raise RuntimeError(f"OpenAI API error {response.status_code}: {response.text[:1200]}")
  return normalize_realism_memo_payload(_parse_json_response(response.json()))


def generate_realism_memo_payload_safe(
  *,
  ops_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  solved_model_input_json: Dict[str, Any] | None = None,
  solved_finmo_json: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
  try:
    payload = generate_realism_memo_payload(
      ops_json=ops_json,
      financials_json=financials_json,
      solved_model_input_json=solved_model_input_json,
      solved_finmo_json=solved_finmo_json,
    )
  except Exception:
    return failed_realism_memo_payload()
  if not is_valid_realism_memo_payload(payload):
    return failed_realism_memo_payload()
  return payload
