from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

import requests


_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
def require_openai_key() -> str:
  key = (os.getenv("OPENAI_API_KEY") or "").strip()
  if not key:
    raise RuntimeError("OPENAI_API_KEY is not configured.")
  return key


def model_for_agent(agent_name: str) -> str:
  specific = {
    "realism_agent": "REALISM_AGENT_MODEL",
    "operations_agent": "OPERATIONS_AGENT_MODEL",
    "capital_agent": "CAPITAL_AGENT_MODEL",
    "grid_agent": "GRID_AGENT_MODEL",
  }.get(str(agent_name or "").strip())
  if specific:
    value = (os.getenv(specific) or "").strip()
    if value:
      return value
  return (os.getenv("APP_AGENTS_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5.1").strip() or "gpt-5.1"


def _post_openai(
  *,
  headers: Dict[str, str],
  payload: Dict[str, Any],
  max_attempts: int = 2,
) -> requests.Response:
  last_exc: Optional[Exception] = None
  attempts = max(1, int(max_attempts or 1))
  for attempt in range(attempts):
    try:
      response = requests.post(
        "https://api.openai.com/v1/responses",
        headers=headers,
        json=payload,
      )
      if response.status_code in _RETRYABLE_STATUS and attempt < attempts - 1:
        time.sleep(1.5 * (2 ** attempt))
        continue
      return response
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as exc:
      last_exc = exc
      if attempt >= attempts - 1:
        raise
      time.sleep(1.5 * (2 ** attempt))
  if last_exc:
    raise last_exc
  raise RuntimeError("OpenAI request failed unexpectedly.")


def parse_json_response(data: Dict[str, Any]) -> Dict[str, Any]:
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
        maybe = json.loads(raw)
      except Exception:
        continue
      if isinstance(maybe, dict):
        return maybe
  return {}


def call_agent_with_schema(
  *,
  agent_name: str,
  system_prompt: str,
  user_prompt: str,
  schema_name: str,
  schema: Dict[str, Any],
) -> Dict[str, Any]:
  api_key = require_openai_key()
  headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
  }
  payload = {
    "model": model_for_agent(agent_name),
    "input": [
      {
        "role": "system",
        "content": [{"type": "input_text", "text": str(system_prompt or "").strip()}],
      },
      {
        "role": "user",
        "content": [{"type": "input_text", "text": str(user_prompt or "").strip()}],
      },
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": str(schema_name or agent_name).strip() or agent_name,
        "schema": schema,
        "strict": True,
      }
    },
  }
  response = _post_openai(
    headers=headers,
    payload=payload,
    max_attempts=3,
  )
  if response.status_code >= 400:
    raise RuntimeError(f"OpenAI API error {response.status_code}: {response.text[:1200]}")
  return parse_json_response(response.json())
