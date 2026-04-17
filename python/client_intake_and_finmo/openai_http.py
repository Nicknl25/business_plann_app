from __future__ import annotations

import os
import time
from typing import Any, Dict, Iterable, Optional

import requests


def _openai_session() -> requests.Session:
  session = requests.Session()
  session.trust_env = False
  session.proxies = {"http": None, "https": None}
  return session


def _resolve_timeout_seconds(timeout_seconds: Optional[float]) -> float:
  if isinstance(timeout_seconds, (int, float)) and float(timeout_seconds) > 0:
    return float(timeout_seconds)
  raw = (os.getenv("OPENAI_TIMEOUT_SECONDS") or "").strip()
  try:
    parsed = float(raw)
  except Exception:
    parsed = 45.0
  return max(15.0, parsed)


def post_openai_with_retries(
  *,
  url: str,
  headers: Dict[str, str],
  payload: Dict[str, Any],
  timeout_seconds: float,
  retryable_status: Iterable[int],
  max_attempts: int = 3,
) -> requests.Response:
  retryable = {int(item) for item in retryable_status}
  resolved_timeout_seconds = _resolve_timeout_seconds(timeout_seconds)
  last_exc: Optional[Exception] = None
  for attempt in range(max(1, int(max_attempts or 1))):
    try:
      with _openai_session() as session:
        resp = session.post(url, headers=headers, json=payload, timeout=resolved_timeout_seconds)
      if resp.status_code in retryable and attempt < max_attempts - 1:
        time.sleep(0.75 * (2**attempt))
        continue
      return resp
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as exc:
      last_exc = exc
      if attempt >= max_attempts - 1:
        raise
      time.sleep(0.75 * (2**attempt))
    except requests.exceptions.ConnectionError as exc:
      last_exc = exc
      if attempt >= max_attempts - 1:
        raise
      time.sleep(0.75 * (2**attempt))
  if last_exc:
    raise last_exc
  raise RuntimeError("OpenAI request failed unexpectedly.")
