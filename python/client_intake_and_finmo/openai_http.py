from __future__ import annotations

import os
import time
from typing import Any, Dict, Iterable, Optional

import requests


_TRANSIENT_EDGE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


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


def _looks_like_transient_openai_edge_response(resp: requests.Response) -> bool:
  status_code = int(getattr(resp, "status_code", 0) or 0)
  if status_code in _TRANSIENT_EDGE_STATUS:
    return True
  content_type = str((getattr(resp, "headers", {}) or {}).get("content-type") or "").lower()
  body = str(getattr(resp, "text", "") or "")[:4000].lower()
  if "text/html" not in content_type and "<html" not in body:
    return False
  transient_markers = (
    "temporarily unavailable",
    "cloudflare",
    "bad gateway",
    "gateway timeout",
    "service unavailable",
    "cf-error",
  )
  return any(marker in body for marker in transient_markers)


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
  retryable.update(_TRANSIENT_EDGE_STATUS)
  resolved_timeout_seconds = _resolve_timeout_seconds(timeout_seconds)
  last_exc: Optional[Exception] = None
  for attempt in range(max(1, int(max_attempts or 1))):
    try:
      with _openai_session() as session:
        resp = session.post(url, headers=headers, json=payload, timeout=resolved_timeout_seconds)
      if (
        (resp.status_code in retryable or _looks_like_transient_openai_edge_response(resp))
        and attempt < max_attempts - 1
      ):
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
