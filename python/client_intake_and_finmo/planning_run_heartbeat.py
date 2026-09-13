"""A LONG STAGE IS NOT A DEAD RUN - and the heartbeat has to say so.

Wren & Calloway 07a5b10f (2026-09-12): the grid-application stage ran ten
minutes of real work (the model recalculating every few seconds, the cash
and surplus passes) while planning_runs.last_heartbeat_at sat frozen at
the stage transition, because the heartbeat only moved when the execution
state was persisted. The watcher called it a stall, Cowork filed a blocker,
and a client would have seen a run that was neither running nor failed.

The most universal sign of life inside a run is a model rebuild, so the
finmo bridge touches the heartbeat on every rebuild, throttled. The touch
resolves the run from the trace context (deep call sites carry no run id),
opens its own short connection, and never raises: a heartbeat must never be
the thing that kills a build.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_LAST_TOUCH: Dict[str, float] = {}
_LOCK = threading.Lock()
DEFAULT_MIN_INTERVAL_S = 15.0


def _resolve_run_id(planning_run_id: Optional[str]) -> str:
  pid = str(planning_run_id or "").strip()
  if pid:
    return pid
  try:
    from client_intake_and_finmo.post_intake_handler_traces import current_planning_run_id
    return str(current_planning_run_id() or "").strip()
  except Exception:
    return ""


def _write(pid: str) -> bool:
  from client_intake_and_finmo.intake_consult_draft import current_app_timestamp_str
  from intake_submission import get_mysql_connection
  now = current_app_timestamp_str()
  conn = get_mysql_connection()
  try:
    cur = conn.cursor()
    try:
      cur.execute(
        "UPDATE planning_runs SET last_heartbeat_at = %s, updated_at = %s WHERE planning_run_id = %s",
        (now, now, pid),
      )
      conn.commit()
      return True
    finally:
      cur.close()
  finally:
    try:
      conn.close()
    except Exception:
      pass


def touch_planning_run_heartbeat(
  planning_run_id: Optional[str] = None,
  *,
  min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
  _writer=None,
) -> bool:
  """Move the run's heartbeat if at least ``min_interval_s`` have passed
  since the last touch for this run. Returns True when a write happened.
  No run in context, no write. Never raises."""
  try:
    pid = _resolve_run_id(planning_run_id)
    if not pid:
      return False
    now = time.monotonic()
    with _LOCK:
      last = _LAST_TOUCH.get(pid)
      if last is not None and (now - last) < float(min_interval_s):
        return False
      _LAST_TOUCH[pid] = now
    writer = _writer or _write
    return bool(writer(pid))
  except Exception as exc:  # noqa: BLE001 - a heartbeat never kills a build
    logger.debug("planning_run_heartbeat_touch_failed: %s: %s", type(exc).__name__, str(exc)[:160])
    return False


def _reset_for_tests() -> None:
  with _LOCK:
    _LAST_TOUCH.clear()


__all__ = ["touch_planning_run_heartbeat", "DEFAULT_MIN_INTERVAL_S"]
