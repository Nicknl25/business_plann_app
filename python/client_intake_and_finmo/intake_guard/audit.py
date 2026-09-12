"""THE AUDIT TRAIL - every action the guard takes, with the patch, the
receipt and the why. In the draft's financials state (`_guard`) and in
its own table, so what the guard did is always readable."""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TABLE = "intake_guard_actions"
_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  draft_id VARCHAR(64) NOT NULL,
  turn INT NOT NULL,
  door VARCHAR(8) NOT NULL,
  action VARCHAR(32) NOT NULL,
  field VARCHAR(255) NULL,
  from_value TEXT NULL,
  to_value TEXT NULL,
  client_words TEXT NULL,
  receipt TEXT NULL,
  why TEXT NULL,
  elapsed_ms INT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  KEY ix_draft (draft_id, turn)
)
"""
_ensured = False
_lock = threading.Lock()
MAX_STATE_ACTIONS = 60


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


def record(conn, *, draft_id: str, turn: int, door: str, action: str, field: Optional[str] = None,
           from_value: Any = None, to_value: Any = None, client_words: str = "", receipt: str = "",
           why: str = "", elapsed_ms: Optional[int] = None) -> None:
  """One row per action. Never raises (the audit must not break a turn)
  but never silent: a failed write is logged at ERROR."""
  try:
    _ensure(conn)
    cur = conn.cursor()
    try:
      cur.execute(
        f"INSERT INTO {TABLE} (draft_id, turn, door, action, field, from_value, to_value, client_words, receipt, why, elapsed_ms) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (str(draft_id), int(turn), door, action, field,
         json.dumps(from_value, default=str) if from_value is not None else None,
         json.dumps(to_value, default=str) if to_value is not None else None,
         client_words or None, receipt or None, why or None, elapsed_ms))
      try:
        conn.commit()
      except Exception:
        pass
    finally:
      cur.close()
  except Exception as exc:  # noqa: BLE001
    logger.error("INTAKE_GUARD_AUDIT_WRITE_FAILED draft=%s turn=%s door=%s action=%s: %s", draft_id, turn, door, action, exc)


def stamp(financials_json: Dict[str, Any], entry: Dict[str, Any]) -> Dict[str, Any]:
  """The same action in the draft state, bounded."""
  fin = dict(financials_json or {})
  g = dict(fin.get("_guard") or {})
  actions = list(g.get("actions") or [])
  actions.append({**entry, "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
  g["actions"] = actions[-MAX_STATE_ACTIONS:]
  fin["_guard"] = g
  return fin


def set_hold(financials_json: Dict[str, Any], hold: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  fin = dict(financials_json or {})
  g = dict(fin.get("_guard") or {})
  if hold:
    g["hold"] = hold
  else:
    g.pop("hold", None)
  fin["_guard"] = g
  return fin


def get_hold(financials_json: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
  g = (financials_json or {}).get("_guard") or {}
  h = g.get("hold")
  return h if isinstance(h, dict) and h else None


def actions_for(conn, draft_id: str) -> List[Dict[str, Any]]:
  _ensure(conn)
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(f"SELECT turn, door, action, field, from_value, to_value, client_words, receipt, why, elapsed_ms, created_at "
                f"FROM {TABLE} WHERE draft_id=%s ORDER BY id", (str(draft_id),))
    return [dict(r) for r in cur.fetchall()]
  finally:
    cur.close()
