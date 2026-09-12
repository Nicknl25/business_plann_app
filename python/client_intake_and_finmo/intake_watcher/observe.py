"""Orchestration: after every persisted turn, build the Turn from the draft
and the previous snapshot, run the checks and the model read, write the
observations, keep the snapshot. Read-only toward the draft; its own two
tables are the only thing it writes.

Placement: per turn. append_messages (the one persistence door for a turn)
calls notify_turn_persisted(draft_id); by default that runs in a daemon
thread so the client's reply is never delayed. INTAKE_WATCHER_SYNC=1 runs it
inline (the persona gate sets this so the model read is recorded and
replayed inside the turn). INTAKE_WATCHER_ENABLED=0 disables it.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional

from client_intake_and_finmo.intake_watcher.checks import Turn, numeric_leaves, run_checks
from client_intake_and_finmo.intake_watcher import judgment as _judgment

logger = logging.getLogger("intake_watcher")

SNAPSHOT_TABLE = "intake_watch_snapshots"
OBSERVATION_TABLE = "intake_watch_observations"

_DDL = (
  f"""CREATE TABLE IF NOT EXISTS {SNAPSHOT_TABLE} (
    draft_id VARCHAR(64) NOT NULL PRIMARY KEY,
    turn INT NOT NULL,
    snapshot_json LONGTEXT NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
  )""",
  f"""CREATE TABLE IF NOT EXISTS {OBSERVATION_TABLE} (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    draft_id VARCHAR(64) NOT NULL,
    turn INT NOT NULL,
    kind VARCHAR(64) NOT NULL,
    severity VARCHAR(16) NOT NULL,
    detector VARCHAR(16) NOT NULL,
    field VARCHAR(255) NOT NULL DEFAULT '',
    client_words TEXT,
    stored_value TEXT,
    expected TEXT,
    why TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_draft (draft_id, turn)
  )""",
)


def enabled() -> bool:
  return (os.getenv("INTAKE_WATCHER_ENABLED") or "1").strip().lower() not in ("0", "false", "no", "off")


def sync_mode() -> bool:
  return (os.getenv("INTAKE_WATCHER_SYNC") or "").strip().lower() in ("1", "true", "yes")


# ------------------------------------------------------------------ store

class MySQLStore:
  """The watcher's own two tables. Never touches the draft."""

  def __init__(self, conn) -> None:
    self.conn = conn
    self._ensured = False

  def ensure(self) -> None:
    if self._ensured:
      return
    cur = self.conn.cursor()
    try:
      for ddl in _DDL:
        cur.execute(ddl)
      self.conn.commit()
    finally:
      cur.close()
    self._ensured = True

  def load_snapshot(self, draft_id: str) -> Optional[Dict[str, Any]]:
    self.ensure()
    cur = self.conn.cursor()
    try:
      cur.execute(f"SELECT turn, snapshot_json FROM {SNAPSHOT_TABLE} WHERE draft_id=%s", (draft_id,))
      row = cur.fetchone()
    finally:
      cur.close()
    if not row:
      return None
    try:
      snap = json.loads(row[1])
    except Exception:
      return None
    snap["_turn"] = int(row[0])
    return snap

  def save_snapshot(self, draft_id: str, turn: int, snapshot: Dict[str, Any]) -> None:
    self.ensure()
    cur = self.conn.cursor()
    try:
      cur.execute(
        f"INSERT INTO {SNAPSHOT_TABLE} (draft_id, turn, snapshot_json) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE turn=VALUES(turn), snapshot_json=VALUES(snapshot_json)",
        (draft_id, int(turn), json.dumps(snapshot, ensure_ascii=False, default=str)),
      )
      self.conn.commit()
    finally:
      cur.close()

  def write_observations(self, obs: List[Dict[str, Any]]) -> None:
    if not obs:
      return
    self.ensure()
    cur = self.conn.cursor()
    try:
      for o in obs:
        cur.execute(
          f"INSERT INTO {OBSERVATION_TABLE} (draft_id, turn, kind, severity, detector, field, client_words, stored_value, expected, why) "
          "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
          (o.get("draft_id"), int(o.get("turn") or 0), o.get("kind"), o.get("severity"), o.get("detector"),
           str(o.get("field") or "")[:255], str(o.get("client_words") or ""),
           json.dumps(o.get("stored_value"), default=str), json.dumps(o.get("expected"), default=str),
           str(o.get("why") or "")),
        )
      self.conn.commit()
    finally:
      cur.close()

  def list_observations(self, draft_id: str) -> List[Dict[str, Any]]:
    self.ensure()
    cur = self.conn.cursor()
    try:
      cur.execute(
        f"SELECT id, turn, kind, severity, detector, field, client_words, stored_value, expected, why, created_at "
        f"FROM {OBSERVATION_TABLE} WHERE draft_id=%s ORDER BY turn, id", (draft_id,))
      rows = cur.fetchall()
    finally:
      cur.close()
    out = []
    for r in rows:
      def _j(v):
        try:
          return json.loads(v) if isinstance(v, str) else v
        except Exception:
          return v
      out.append({"id": r[0], "turn": r[1], "kind": r[2], "severity": r[3], "detector": r[4], "field": r[5],
                  "client_words": r[6], "stored_value": _j(r[7]), "expected": _j(r[8]), "why": r[9],
                  "created_at": str(r[10])})
    return out


class MemoryStore:
  """For tests and replays."""

  def __init__(self) -> None:
    self.snapshots: Dict[str, Dict[str, Any]] = {}
    self.observations: List[Dict[str, Any]] = []

  def load_snapshot(self, draft_id):
    return self.snapshots.get(draft_id)

  def save_snapshot(self, draft_id, turn, snapshot):
    s = dict(snapshot); s["_turn"] = turn
    self.snapshots[draft_id] = s

  def write_observations(self, obs):
    self.observations.extend(obs)

  def list_observations(self, draft_id):
    return [o for o in self.observations if o.get("draft_id") == draft_id]


# --------------------------------------------------------------- snapshot

def _load_json(raw: Any) -> Dict[str, Any]:
  if isinstance(raw, dict):
    return raw
  if isinstance(raw, str) and raw.strip():
    try:
      v = json.loads(raw)
      return v if isinstance(v, dict) else {}
    except Exception:
      return {}
  return {}


def snapshot_from_draft(draft: Dict[str, Any]) -> Dict[str, Any]:
  """The watcher's view of the draft: the three sections it reasons about,
  status, focus, and the pending question. Nothing else."""
  return {
    "ops": _load_json(draft.get("operating_model_json")),
    "people": _load_json(draft.get("people_json")),
    "financials": _load_json(draft.get("financials_json")),
    "status": draft.get("status"),
    "active_focus": draft.get("active_focus"),
    "pending_question_key": draft.get("pending_question_key"),
  }


def diff_of(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
  b = numeric_leaves({k: before.get(k) for k in ("financials", "ops", "people")})
  a = numeric_leaves({k: after.get(k) for k in ("financials", "ops", "people")})
  out: Dict[str, Any] = {}
  for path in sorted(set(a) | set(b)):
    if a.get(path) != b.get(path):
      out[path] = {"before": b.get(path), "after": a.get(path)}
  if before.get("status") != after.get("status"):
    out["status"] = {"before": before.get("status"), "after": after.get("status")}
  if before.get("active_focus") != after.get("active_focus"):
    out["active_focus"] = {"before": before.get("active_focus"), "after": after.get("active_focus")}
  return out


# ------------------------------------------------------------------ core

def observe_draft_turn(*, draft: Dict[str, Any], store, post=None, run_model: bool = True) -> List[Dict[str, Any]]:
  """Build the Turn from the draft and the previous snapshot, run everything,
  persist, return the observations. Pure with respect to the draft."""
  draft_id = str(draft.get("draft_id") or "").strip()
  msgs = draft.get("messages_json") or draft.get("messages") or []
  if isinstance(msgs, str):
    try:
      msgs = json.loads(msgs)
    except Exception:
      msgs = []
  msgs = [m for m in msgs if isinstance(m, dict)]
  turn = len(msgs)
  after = snapshot_from_draft(draft)
  prev = store.load_snapshot(draft_id) or {}
  before = {k: prev.get(k) for k in ("ops", "people", "financials", "status", "active_focus", "pending_question_key")} if prev else \
           {"ops": {}, "people": {}, "financials": {}, "status": None, "active_focus": None, "pending_question_key": None}
  # the latest exchange = the last user message and the assistant reply after it
  user_text, assistant_text = "", ""
  for m in reversed(msgs):
    if not assistant_text and m.get("role") == "assistant":
      assistant_text = str(m.get("content") or "")
    elif m.get("role") == "user":
      user_text = str(m.get("content") or "")
      break
  prior_user = [str(m.get("content") or "") for m in msgs[:-2] if m.get("role") == "user"]
  prior_assistant = [str(m.get("content") or "") for m in msgs[:-1] if m.get("role") == "assistant"]
  t = Turn(draft_id=draft_id, turn=turn, user_text=user_text, assistant_text=assistant_text,
           before=before, after=after, prior_user_texts=prior_user, prior_assistant_texts=prior_assistant)
  obs = run_checks(t)
  if run_model:
    state = (after.get("financials") or {}).get("_coherence") or {}
    rnd = state.get("round") if isinstance(state.get("round"), dict) else {}
    obs.extend(_judgment.judge_turn(
      draft_id=draft_id, turn=turn,
      transcript=[{"role": m.get("role"), "content": m.get("content")} for m in msgs],
      user_text=user_text, assistant_text=assistant_text,
      diff=diff_of(before, after), floors=dict(state.get("client_floors") or {}),
      options=list(rnd.get("options") or []), post=post,
    ))
  store.write_observations(obs)
  store.save_snapshot(draft_id, turn, after)
  kinds = [o.get("kind") for o in obs]
  logger.info("WATCH_OBSERVED draft=%s turn=%s kinds=%s", draft_id[:12], turn, kinds)
  return obs


def _observe_by_id(draft_id: str) -> None:
  from client_intake_and_finmo.intake_submission import get_mysql_connection  # type: ignore
  from client_intake_and_finmo.intake_consult_draft import get_draft  # type: ignore
  conn = get_mysql_connection()
  try:
    draft = get_draft(conn, draft_id=draft_id) or {}
    if not draft:
      return
    observe_draft_turn(draft=draft, store=MySQLStore(conn))
  finally:
    try:
      conn.close()
    except Exception:
      pass


def notify_turn_persisted(draft_id: str) -> None:
  """Called by append_messages after a turn is persisted. Never raises."""
  if not enabled():
    return
  did = str(draft_id or "").strip()
  if not did:
    return
  try:
    if sync_mode():
      _observe_by_id(did)
    else:
      th = threading.Thread(target=_safe_observe, args=(did,), name=f"intake-watch-{did[:8]}", daemon=True)
      th.start()
  except Exception:
    logger.exception("WATCH_FAILED draft=%s", did[:12])


def _safe_observe(draft_id: str) -> None:
  try:
    _observe_by_id(draft_id)
  except Exception:
    logger.exception("WATCH_FAILED draft=%s", draft_id[:12])
