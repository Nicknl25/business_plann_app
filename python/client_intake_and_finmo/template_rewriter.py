from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from fact_templates import sanitize_fact_template  # type: ignore

ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
_RETRYABLE_STATUS = {429, 502, 503, 504}


def _load_root_env() -> None:
  try:
    from dotenv import load_dotenv  # type: ignore
  except Exception:
    return
  try:
    load_dotenv(str(ROOT_ENV_PATH))
  except Exception:
    pass


def _require_openai_key() -> str:
  _load_root_env()
  key = (os.getenv("OPENAI_API_KEY") or "").strip()
  if not key:
    raise RuntimeError("OPENAI_API_KEY is not configured.")
  return key


def _openai_model() -> str:
  _load_root_env()
  return (os.getenv("OPENAI_MODEL") or "gpt-5.1").strip() or "gpt-5.1"


def _openai_timeout_seconds() -> Optional[int]:
  _load_root_env()
  return None


def _format_openai_error(resp: requests.Response) -> str:
  if resp.status_code in _RETRYABLE_STATUS:
    return "We're having trouble reaching our AI service right now. Please try again in a minute."
  return f"OpenAI API error {resp.status_code}: {resp.text[:500]}"


def _post_openai(*, url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> requests.Response:
  timeout = _openai_timeout_seconds()
  last_exc: Optional[Exception] = None
  for attempt in range(3):
    try:
      resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
      if resp.status_code in _RETRYABLE_STATUS and attempt < 2:
        time.sleep(0.75 * (2**attempt))
        continue
      return resp
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as exc:
      last_exc = exc
      if attempt >= 2:
        raise
      time.sleep(0.75 * (2**attempt))
    except requests.exceptions.ConnectionError as exc:
      last_exc = exc
      if attempt >= 2:
        raise
      time.sleep(0.75 * (2**attempt))
  if last_exc:
    raise last_exc
  raise RuntimeError("OpenAI request failed unexpectedly.")


def _parse_responses_text(data: Dict[str, Any]) -> str:
  output = data.get("output") or []
  chunks: list[str] = []
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_text" and part.get("text"):
        chunks.append(str(part["text"]))
  if not chunks:
    raise RuntimeError("OpenAI response contained no output_text.")
  return "\n".join(chunks).strip()


def rewrite_summary_as_fact_template(
  *,
  text: str,
  shared_context: Dict[str, Any],
  business_facts: Dict[str, Any],
  required_fact_keys: List[str],
  allowed_fact_keys: List[str],
) -> str:
  """
  Convert an existing literal summary paragraph into a fact-bearing template using
  {{fact:<group>.<field>}} placeholders.

  This is ONLY used as a one-time upgrade path for older drafts or model slips
  where literal values leaked into a summary that must stay correct as facts evolve.
  """
  raw = str(text or "").strip()
  if not raw:
    return ""

  api_key = _require_openai_key()
  model = _openai_model()

  required_list = ", ".join(required_fact_keys)
  allowed_list = ", ".join(allowed_fact_keys)

  system = f"""
You rewrite an existing intake summary into a fact-bearing template.

Rules:
- Keep the meaning and structure as close as possible.
- Do NOT add new facts or new claims.
- Replace any known facts with placeholders of the form {{fact:<group>.<field>}}.
- You may ONLY use these allowed fact keys: {allowed_list}
- The output MUST include these required placeholders at least once: {required_list}
- Output ONLY the rewritten text. No JSON. No commentary.
""".strip()

  context = {
    "business": business_facts,
    "shared_context": shared_context,
    "required_fact_keys": required_fact_keys,
    "allowed_fact_keys": allowed_fact_keys,
    "text_to_rewrite": raw,
  }
  context_blob = json.dumps(context, ensure_ascii=False)

  url = "https://api.openai.com/v1/responses"
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  payload = {
    "model": model,
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": context_blob},
    ],
  }

  resp = _post_openai(url=url, headers=headers, payload=payload)
  if resp.status_code >= 400:
    raise RuntimeError(_format_openai_error(resp))

  rewritten = _parse_responses_text(resp.json())
  rewritten = sanitize_fact_template(rewritten)

  # Best-effort: ensure required placeholders survived sanitization.
  for key in required_fact_keys:
    ph = f"{{{{fact:{key}}}}}"
    if ph not in rewritten:
      raise RuntimeError(f"Rewriter did not include required placeholder: {key}")

  return rewritten.strip()

