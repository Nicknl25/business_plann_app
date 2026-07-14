from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any, Dict, Iterable, Optional

import requests


_TRANSIENT_EDGE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


# ----------------------------------------------------------------------------
# GPT RESPONSE LOCK — full-pipeline determinism (run-once-and-lock).
#
# gpt-5.1 is a reasoning model that does not honor `seed`, so every live call
# re-rolls: identical business inputs produced cost sides differing 50-62%
# run-to-run (Luna EBITDA, Ironwood net income) while revenue was already
# deterministic. Same disease we killed on revenue, so the same cure, applied
# ONCE at the shared HTTP layer every GPT call flows through: the first run's
# response for a given request is persisted keyed by a content hash of the
# request; identical requests on later runs replay it byte-for-byte. By
# induction the entire pipeline becomes reproducible: deterministic inputs ->
# identical first request -> locked response -> identical downstream state ->
# identical next request -> ...
#
# This locks the DECISION, not the decider: the executive's per-business
# judgments (labor-bound vs leverage, band trajectories, cascade lever moves)
# are made live on the first run with full context and replayed verbatim after
# -- never flattened into something generic.
#
# Hash hygiene (the revenue-critique lesson): run-minted tokens must not leak
# into the key or it re-rolls every run. The canonical request string is
# normalized before hashing: 32-hex ids / dashed UUIDs (draft_id,
# planning_run_id) and date-WITH-TIME stamps become placeholders. Bare dates
# are kept -- they are business content (start dates), not run artifacts.
#
# Best-effort by design: any store failure (no DB, bad table) -> live call,
# exactly as before. Kill switch: GPT_RESPONSE_LOCK=0.
# ----------------------------------------------------------------------------

GPT_RESPONSE_LOCK_TABLE = "post_intake_gpt_response_store"

_VOLATILE_TOKEN_RE = re.compile(
  r"[0-9a-f]{32}"                                                # 32-hex ids
  r"|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"  # dashed UUIDs
  r"|\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?"      # datetimes (not bare dates)
)

_lock_table_ready = False


def _gpt_lock_enabled() -> bool:
  return (os.getenv("GPT_RESPONSE_LOCK") or "1").strip().lower() not in ("0", "false", "off")


def gpt_request_lock_key(url: str, payload: Dict[str, Any]) -> str:
  canonical = json.dumps(
    {"url": str(url), "payload": payload},
    sort_keys=True, ensure_ascii=False, default=str,
  )
  normalized = _VOLATILE_TOKEN_RE.sub("<VOLATILE>", canonical)
  return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class _LockedResponse:
  """Minimal stand-in for requests.Response replaying a locked body. Callers
  in this codebase use .status_code / .json() / .text / .headers only."""

  status_code = 200

  def __init__(self, body_text: str) -> None:
    self.text = body_text
    self.headers: Dict[str, str] = {"content-type": "application/json", "x-gpt-response-lock": "replay"}

  def json(self) -> Any:
    return json.loads(self.text)


def _lock_connection():
  import mysql.connector  # type: ignore
  return mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
  )


def _lock_ensure_table(conn) -> None:
  global _lock_table_ready
  if _lock_table_ready:
    return
  cur = conn.cursor()
  try:
    cur.execute(
      f"""
      CREATE TABLE IF NOT EXISTS {GPT_RESPONSE_LOCK_TABLE} (
        input_hash VARCHAR(64) NOT NULL PRIMARY KEY,
        response_text LONGTEXT NOT NULL,
        url VARCHAR(255),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
      """
    )
    conn.commit()
    _lock_table_ready = True
  finally:
    try:
      cur.close()
    except Exception:
      pass


def _lock_lookup(key: str) -> Optional[str]:
  # DETERMINISM — a lock lookup that silently swallows a DB hiccup falls
  # back to an UNLOCKED live call, reintroducing nondeterminism anywhere
  # in the app (any run where the hiccup lands rolls fresh). Retry the DB
  # op; if it still fails, RAISE — the caller must never proceed unlocked
  # while the lock is enabled. Same discipline for _lock_save: a swallowed
  # save failure means the NEXT run re-rolls a call this run made live.
  _last_exc: Optional[Exception] = None
  for _attempt in range(3):
    try:
      conn = _lock_connection()
      try:
        _lock_ensure_table(conn)
        cur = conn.cursor()
        try:
          cur.execute(
            f"SELECT response_text FROM {GPT_RESPONSE_LOCK_TABLE} WHERE input_hash = %s",
            (key,),
          )
          row = cur.fetchone()
        finally:
          cur.close()
      finally:
        conn.close()
      return row[0] if row and row[0] else None
    except Exception as exc:
      _last_exc = exc
      time.sleep(0.25 * (_attempt + 1))
  raise RuntimeError(
    f"gpt_response_lock_lookup_failed: the response-lock store is unreachable "
    f"after 3 attempts; refusing to fall back to an unlocked live call. "
    f"cause={type(_last_exc).__name__}: {str(_last_exc)[:200]}"
  )


def _lock_save(key: str, url: str, body_text: str) -> None:
  _last_exc: Optional[Exception] = None
  for _attempt in range(3):
    try:
      conn = _lock_connection()
      try:
        _lock_ensure_table(conn)
        cur = conn.cursor()
        try:
          cur.execute(
            f"INSERT IGNORE INTO {GPT_RESPONSE_LOCK_TABLE} (input_hash, response_text, url) VALUES (%s, %s, %s)",
            (key, body_text, str(url)[:255]),
          )
          conn.commit()
        finally:
          cur.close()
      finally:
        conn.close()
      return
    except Exception as exc:
      _last_exc = exc
      time.sleep(0.25 * (_attempt + 1))
  raise RuntimeError(
    f"gpt_response_lock_save_failed: could not persist a live GPT response "
    f"after 3 attempts; the next identical run would re-roll it. "
    f"cause={type(_last_exc).__name__}: {str(_last_exc)[:200]}"
  )


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
  # GPT response lock: replay the locked response for an identical request
  # (see module comment). Miss -> live call (then saved). A store FAILURE
  # is fatal by design — _lock_lookup retries and raises; silently falling
  # back to an unlocked live call here was a system-wide determinism hole.
  lock_key: Optional[str] = None
  if _gpt_lock_enabled():
    lock_key = gpt_request_lock_key(url, payload)
    locked_body = _lock_lookup(lock_key)
    if locked_body is not None:
      return _LockedResponse(locked_body)  # type: ignore[return-value]

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
      # Lock only clean, parseable successes -- a cached failure would
      # freeze an outage into determinism. The parse check stays
      # non-fatal (an unparseable 200 is returned to the caller to
      # handle); a SAVE failure raises (see _lock_save) — proceeding
      # with an unsaved live response means the next identical run
      # re-rolls it.
      if lock_key is not None and int(getattr(resp, "status_code", 0) or 0) == 200:
        _parse_ok = True
        try:
          resp.json()
        except Exception:
          _parse_ok = False
        if _parse_ok:
          _lock_save(lock_key, url, resp.text)
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
