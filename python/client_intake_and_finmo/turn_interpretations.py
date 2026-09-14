"""WHAT THE APP UNDERSTOOD - one row per interpretation of a client turn.

One-reader build, STEP 0 (Nick ruled 2026-09-14). The intent router is the one
thing built to interpret a client's sentence, and until today what it
understood was stored nowhere readable: only a raw API body in the response
cache, and a TURN_INTENT log line without the unresolved figures. So nobody -
not a door, not Cowork, not a claim - could read what the app took a sentence
to mean beside what it then wrote.

This records every router result as it is returned to its caller: the action,
the patch, the unresolved figures with the client's words, the reply text, which
call site asked, how long it took, and whether the sentence it was given IS the
client's message this turn. That last flag makes a hidden reader visible: the
proposal extractor hands the router the app's own previous reply as if the
client had said it.

Nothing downstream reads this table yet - no behaviour changes. It is written
only inside a live request (never from a unit test or preflight, which are
read-only), and a failed write never breaks a turn: it is logged at ERROR.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TABLE = "intake_turn_interpretations"
_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  draft_id VARCHAR(64) NOT NULL,
  turn INT NULL,
  call_site VARCHAR(160) NOT NULL DEFAULT '',
  consult_type VARCHAR(32) NOT NULL DEFAULT '',
  active_focus VARCHAR(32) NOT NULL DEFAULT '',
  is_client_message TINYINT(1) NOT NULL DEFAULT 0,
  message_sha256 CHAR(64) NULL,
  message_chars INT NULL,
  status VARCHAR(16) NOT NULL,
  action VARCHAR(32) NULL,
  patch_json LONGTEXT NULL,
  unresolved_json LONGTEXT NULL,
  assistant_message TEXT NULL,
  error TEXT NULL,
  elapsed_ms INT NULL,
  created_at TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP(6),
  KEY ix_draft_turn (draft_id, turn)
)
"""
_ensured = False
_lock = threading.Lock()


def _connect():
  """Patchable in pins. The same connection factory every intake writer uses."""
  from client_intake_and_finmo.intake_submission import get_mysql_connection  # type: ignore
  return get_mysql_connection()


def _ensure(conn) -> None:
  global _ensured
  if _ensured:
    return
  with _lock:
    if _ensured:
      return
    cur = conn.cursor()
    try:
      cur.execute(_DDL)
      try:
        conn.commit()
      except Exception:
        pass
    finally:
      cur.close()
    _ensured = True


def _sha(text: str) -> str:
  return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _turn_context() -> Optional[Dict[str, Any]]:
  """The live request's draft, turn and client message - or None outside a
  request, which is what keeps unit tests and preflight read-only."""
  try:
    from flask import g, has_request_context  # type: ignore
  except Exception:
    return None
  if not has_request_context():
    return None
  try:
    from client_intake_and_finmo.openai_http import get_gpt_run_identity  # type: ignore
    draft_id = str((get_gpt_run_identity() or {}).get("draft_id") or "").strip()
  except Exception:
    draft_id = ""
  if not draft_id:
    return None
  turn = getattr(g, "_turn_index", None)
  return {
    "draft_id": draft_id,
    "turn": int(turn) if isinstance(turn, int) else None,
    "client_text": getattr(g, "_turn_user_text", None),
  }


def record(*, kwargs: Dict[str, Any], result: Optional[Dict[str, Any]], elapsed_ms: int,
           call_site: str, error: Optional[BaseException] = None) -> None:
  """One row per router result. Never raises; never silent."""
  ctx = _turn_context()
  if ctx is None:
    return
  message = str(kwargs.get("user_message") or "")
  client_text = ctx.get("client_text")
  is_client = client_text is not None and message.strip() == str(client_text).strip() and bool(message.strip())
  res = result if isinstance(result, dict) else {}
  try:
    conn = _connect()
    try:
      _ensure(conn)
      cur = conn.cursor()
      try:
        cur.execute(
          f"INSERT INTO {TABLE} (draft_id, turn, call_site, consult_type, active_focus, is_client_message, "
          "message_sha256, message_chars, status, action, patch_json, unresolved_json, assistant_message, error, "
          "elapsed_ms) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
          (ctx["draft_id"], ctx["turn"], str(call_site or "")[:160], str(kwargs.get("consult_type") or "")[:32],
           str(kwargs.get("active_focus") or "")[:32], 1 if is_client else 0, _sha(message), len(message),
           "error" if error is not None else "ok",
           (str(res.get("action")) if res.get("action") is not None else None),
           json.dumps(res.get("patch"), ensure_ascii=False, default=str) if res.get("patch") is not None else None,
           json.dumps(res.get("unresolved_figures") or [], ensure_ascii=False, default=str),
           (str(res.get("assistant_message")) if res.get("assistant_message") is not None else None),
           ("%s: %s" % (type(error).__name__, error))[:2000] if error is not None else None,
           int(elapsed_ms)))
        try:
          conn.commit()
        except Exception:
          pass
      finally:
        cur.close()
    finally:
      try:
        conn.close()
      except Exception:
        pass
  except Exception as exc:  # noqa: BLE001
    logger.error("TURN_INTERPRETATION_WRITE_FAILED draft=%s turn=%s site=%s: %s",
                 ctx.get("draft_id"), ctx.get("turn"), call_site, exc)


def for_draft(conn, draft_id: str) -> List[Dict[str, Any]]:
  """Every recorded interpretation on a draft, oldest first, JSON columns parsed."""
  _ensure(conn)
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(f"SELECT id, turn, call_site, consult_type, active_focus, is_client_message, message_chars, status, "
                f"action, patch_json, unresolved_json, assistant_message, error, elapsed_ms, created_at "
                f"FROM {TABLE} WHERE draft_id=%s ORDER BY id", (str(draft_id),))
    rows = []
    for r in cur.fetchall():
      row = dict(r)
      for src, dst in (("patch_json", "patch"), ("unresolved_json", "unresolved_figures")):
        raw = row.pop(src, None)
        try:
          row[dst] = json.loads(raw) if raw else None
        except Exception:
          row[dst] = raw
      row["is_client_message"] = bool(row.get("is_client_message"))
      rows.append(row)
    return rows
  finally:
    cur.close()
