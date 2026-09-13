"""A FAILED BUILD IS RECORDED, EVEN WHEN IT DIED BEFORE THE RUN EXISTED.

Sorrel & Dunne 691a4763 (2026-09-12 23:23:58) is why this is here. The system
run threw inside `prepare_initial_grid_for_draft` - BEFORE `begin_planning_run`
created the planning_runs row - and two things followed:

  * `clear_planning_run_action` is the only writer of the draft's
    planning_status / planning_run_status / planning_failure_reason columns,
    and it needs an active run row to write to. There wasn't one, so those
    columns kept saying "pending" over a build that was already dead.
  * `_persist_failed_system_run_snapshot` did set the draft's `status` to
    "failed" - and then the client carried on talking, re-completed the
    intake two minutes later, and the next persist wrote "completed" straight
    back over it. The only trace left was a line in a log file.

So the client was told "the intake is already finished and marked as submitted
on my side, so there's nothing more for me to run here", and the row agreed.

A draft column is a mutable view of where a draft is now. It is the wrong
place to keep the fact that something failed, because the next turn can
legitimately overwrite it. This table is append-only and nothing overwrites
it: one row per failed system run, with or without a planning run id.

    draft_id, planning_run_id, stage, detail, run_existed, occurred_at

`run_existed` is the distinction that was invisible: a failure the run row
knew about, versus one that happened before there was a run row to tell.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TABLE = "system_run_failures"

_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  draft_id VARCHAR(64) NOT NULL,
  planning_run_id VARCHAR(64) NULL,
  stage VARCHAR(128) NULL,
  detail MEDIUMTEXT NULL,
  run_existed TINYINT(1) NOT NULL DEFAULT 0,
  occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  KEY ix_draft (draft_id, occurred_at),
  KEY ix_run (planning_run_id)
)
"""

_ensured = False
_lock = threading.Lock()

#: A contract violation's detail carries every violating quarter; keep it all,
#: but not without a bound.
_MAX_DETAIL = 60000


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


def record(conn, *, draft_id: str, detail: str, planning_run_id: str = "",
           stage: str = "", run_existed: bool = False) -> Optional[int]:
  """One failed system run. Never raises - the request is already failing and
  its error belongs to the caller, not to this table - but never silent."""
  try:
    if not str(draft_id or "").strip():
      logger.error("SYSTEM_RUN_FAILURE_NO_DRAFT detail=%r", str(detail)[:200])
      return None
    _ensure(conn)
    cur = conn.cursor()
    try:
      cur.execute(
        f"INSERT INTO {TABLE} (draft_id, planning_run_id, stage, detail, run_existed) "
        "VALUES (%s,%s,%s,%s,%s)",
        (str(draft_id), str(planning_run_id or "") or None,
         (str(stage or "") or None), str(detail or "")[:_MAX_DETAIL],
         1 if run_existed else 0),
      )
      row_id = cur.lastrowid
      try:
        conn.commit()
      except Exception:
        pass
    finally:
      cur.close()
    logger.error(
      "SYSTEM_RUN_FAILURE_RECORDED draft=%s run=%s stage=%s run_existed=%s: %s",
      draft_id, planning_run_id or "-", stage or "-", run_existed, str(detail)[:300])
    return row_id
  except Exception as exc:  # noqa: BLE001
    logger.error("SYSTEM_RUN_FAILURE_WRITE_FAILED draft=%s: %s", draft_id, exc)
    return None


def for_draft(conn, draft_id: str) -> List[Dict[str, Any]]:
  """Every failed run for this draft, newest first. Append-only, so this is
  the whole history - including failures a later turn overwrote in the draft's
  own columns."""
  _ensure(conn)
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      f"SELECT draft_id, planning_run_id, stage, detail, run_existed, occurred_at "
      f"FROM {TABLE} WHERE draft_id=%s ORDER BY occurred_at DESC, id DESC",
      (str(draft_id),))
    return [dict(r) for r in cur.fetchall()]
  finally:
    cur.close()


def latest(conn, draft_id: str) -> Optional[Dict[str, Any]]:
  rows = for_draft(conn, draft_id)
  return rows[0] if rows else None


def unresolved_for_draft(conn, draft_id: str) -> Optional[Dict[str, Any]]:
  """The most recent failure with no successful run after it - i.e. the one
  the client is still sitting behind. This is what the front end needs in
  order to say "the build failed, here is why, try again" instead of leaving
  a Submitted button over a dead run."""
  from client_intake_and_finmo.intake_consult_draft import get_draft  # type: ignore

  last = latest(conn, draft_id)
  if not last:
    return None
  try:
    draft = get_draft(conn, draft_id=str(draft_id).strip()) or {}
  except Exception:
    return last
  completed_at = draft.get("planning_run_completed_at")
  if completed_at and last.get("occurred_at") and completed_at > last["occurred_at"]:
    return None   # a run finished after this failure; the client is past it
  return last
