from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from validate_numeric_cutover import validate_loaded_document


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNNER_PATH = REPO_ROOT / "Test Files" / "run_live_args_intake.py"


def _utc_now_sql() -> str:
  return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse_dt(raw: Any) -> Optional[datetime]:
  if raw is None:
    return None
  text = str(raw).strip()
  if not text or text.lower() == "none":
    return None
  normalized = text.replace("Z", "+00:00")
  for candidate in (normalized, normalized.replace(" ", "T")):
    try:
      dt = datetime.fromisoformat(candidate)
      if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
      return dt.astimezone(timezone.utc)
    except Exception:
      continue
  return None


def _seconds_between(later: Optional[datetime], earlier: Optional[datetime]) -> Optional[float]:
  if later is None or earlier is None:
    return None
  return round((later - earlier).total_seconds(), 3)


def _load_db():
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore

  return get_mysql_connection


def _latest_draft_after(*, get_mysql_connection, after_ts: str) -> Optional[Dict[str, Any]]:
  conn = get_mysql_connection()
  try:
    cur = conn.cursor(dictionary=True)
    cur.execute(
      """
      SELECT draft_id, created_at, updated_at, status, active_focus,
             planning_run_id,
             planning_stage, planning_status,
             planning_last_review_iteration,
             planning_current_retry_count,
             planning_current_cycle,
             planning_detected_issue_count,
             planning_remaining_issue_count,
             planning_resolved_issue_count,
             planning_tolerated_issue_count,
             planning_iteration_pending_issue_count,
             planning_latest_checkpoint_id,
             planning_last_heartbeat_at,
             planning_run_json,
             convergence_state_json,
             numeric_solver_feedback_json
      FROM intake_consult_drafts
      WHERE created_at >= %s
      ORDER BY created_at DESC
      LIMIT 1
      """,
      (after_ts,),
    )
    return cur.fetchone()
  finally:
    try:
      cur.close()
    except Exception:
      pass
    conn.close()


def _draft_by_id(*, get_mysql_connection, draft_id: str) -> Optional[Dict[str, Any]]:
  conn = get_mysql_connection()
  try:
    cur = conn.cursor(dictionary=True)
    cur.execute(
      """
      SELECT draft_id, created_at, updated_at, status, active_focus,
             planning_run_id,
             planning_stage, planning_status,
             planning_last_review_iteration,
             planning_current_retry_count,
             planning_current_cycle,
             planning_detected_issue_count,
             planning_remaining_issue_count,
             planning_resolved_issue_count,
             planning_tolerated_issue_count,
             planning_iteration_pending_issue_count,
             planning_latest_checkpoint_id,
             planning_last_heartbeat_at,
             planning_run_json,
             convergence_state_json,
             numeric_solver_feedback_json
      FROM intake_consult_drafts
      WHERE draft_id = %s
      LIMIT 1
      """,
      (draft_id,),
    )
    return cur.fetchone()
  finally:
    try:
      cur.close()
    except Exception:
      pass
    conn.close()


def _parse_json(raw: Any) -> Any:
  if raw is None:
    return None
  if isinstance(raw, (dict, list)):
    return raw
  try:
    return json.loads(str(raw))
  except Exception:
    return None


def _snapshot(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  if not isinstance(row, dict):
    return {}
  return {
    "draft_id": row.get("draft_id"),
    "status": row.get("status"),
    "active_focus": row.get("active_focus"),
    "planning_run_id": row.get("planning_run_id"),
    "planning_stage": row.get("planning_stage"),
    "planning_status": row.get("planning_status"),
    "planning_last_review_iteration": row.get("planning_last_review_iteration"),
    "planning_current_retry_count": row.get("planning_current_retry_count"),
    "planning_current_cycle": row.get("planning_current_cycle"),
    "planning_detected_issue_count": row.get("planning_detected_issue_count"),
    "planning_remaining_issue_count": row.get("planning_remaining_issue_count"),
    "planning_resolved_issue_count": row.get("planning_resolved_issue_count"),
    "planning_tolerated_issue_count": row.get("planning_tolerated_issue_count"),
    "planning_iteration_pending_issue_count": row.get("planning_iteration_pending_issue_count"),
    "planning_latest_checkpoint_id": row.get("planning_latest_checkpoint_id"),
    "planning_last_heartbeat_at": str(row.get("planning_last_heartbeat_at")),
    "updated_at": str(row.get("updated_at")),
  }


def _planning_run_by_id(*, get_mysql_connection, planning_run_id: str) -> Optional[Dict[str, Any]]:
  conn = get_mysql_connection()
  try:
    cur = conn.cursor(dictionary=True)
    cur.execute(
      """
      SELECT planning_run_id, draft_id, client_id, run_status,
             current_stage, current_stage_status,
             current_iteration, current_retry_count, current_cycle,
             latest_detected_issue_count, latest_remaining_issue_count, latest_resolved_issue_count,
             latest_checkpoint_id, resume_from_checkpoint_id, source_planning_run_id,
             superseded_by_planning_run_id, requested_action, requested_action_at,
             latest_controller_status, failure_reason, trigger_type, resume_count,
             created_at, updated_at, started_at, last_heartbeat_at, paused_at, stopped_at, completed_at
      FROM planning_runs
      WHERE planning_run_id = %s
      LIMIT 1
      """,
      (planning_run_id,),
    )
    return cur.fetchone()
  finally:
    try:
      cur.close()
    except Exception:
      pass
    conn.close()


def _latest_checkpoint_for_run(*, get_mysql_connection, planning_run_id: str) -> Optional[Dict[str, Any]]:
  conn = get_mysql_connection()
  try:
    cur = conn.cursor(dictionary=True)
    cur.execute(
      """
      SELECT checkpoint_id, planning_run_id, draft_id, client_id,
             stage, stage_status, iteration, retry_count, cycle,
             checkpoint_kind, created_at, updated_at
      FROM planning_run_checkpoints
      WHERE planning_run_id = %s
      ORDER BY created_at DESC
      LIMIT 1
      """,
      (planning_run_id,),
    )
    return cur.fetchone()
  finally:
    try:
      cur.close()
    except Exception:
      pass
    conn.close()


def _recent_stage_events_for_run(
  *,
  get_mysql_connection,
  planning_run_id: str,
  limit: int,
) -> list[Dict[str, Any]]:
  conn = get_mysql_connection()
  try:
    cur = conn.cursor(dictionary=True)
    cur.execute(
      """
      SELECT event_id, planning_run_id, draft_id, client_id,
             stage, stage_status, iteration, retry_count, cycle,
             event_type, event_summary, created_at
      FROM planning_stage_events
      WHERE planning_run_id = %s
      ORDER BY created_at DESC
      LIMIT %s
      """,
      (planning_run_id, max(1, int(limit))),
    )
    rows = cur.fetchall() or []
    return [row for row in rows if isinstance(row, dict)]
  finally:
    try:
      cur.close()
    except Exception:
      pass
    conn.close()


def _planning_run_snapshot(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  if not isinstance(row, dict):
    return {}
  return {
    "planning_run_id": row.get("planning_run_id"),
    "draft_id": row.get("draft_id"),
    "run_status": row.get("run_status"),
    "current_stage": row.get("current_stage"),
    "current_stage_status": row.get("current_stage_status"),
    "current_iteration": row.get("current_iteration"),
    "current_retry_count": row.get("current_retry_count"),
    "current_cycle": row.get("current_cycle"),
    "latest_detected_issue_count": row.get("latest_detected_issue_count"),
    "latest_remaining_issue_count": row.get("latest_remaining_issue_count"),
    "latest_resolved_issue_count": row.get("latest_resolved_issue_count"),
    "latest_checkpoint_id": row.get("latest_checkpoint_id"),
    "latest_controller_status": row.get("latest_controller_status"),
    "failure_reason": row.get("failure_reason"),
    "resume_count": row.get("resume_count"),
    "started_at": str(row.get("started_at")),
    "updated_at": str(row.get("updated_at")),
    "last_heartbeat_at": str(row.get("last_heartbeat_at")),
    "completed_at": str(row.get("completed_at")),
  }


def _checkpoint_snapshot(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  if not isinstance(row, dict):
    return {}
  return {
    "checkpoint_id": row.get("checkpoint_id"),
    "planning_run_id": row.get("planning_run_id"),
    "stage": row.get("stage"),
    "stage_status": row.get("stage_status"),
    "iteration": row.get("iteration"),
    "retry_count": row.get("retry_count"),
    "cycle": row.get("cycle"),
    "checkpoint_kind": row.get("checkpoint_kind"),
    "created_at": str(row.get("created_at")),
    "updated_at": str(row.get("updated_at")),
  }


def _monitor_health_summary(
  *,
  proc_returncode: Optional[int],
  seen_states: list[Dict[str, Any]],
  seen_run_states: list[Dict[str, Any]],
  final_snapshot: Dict[str, Any],
  final_run_row: Dict[str, Any],
  final_checkpoint: Dict[str, Any],
  final_events: list[Dict[str, Any]],
) -> Dict[str, Any]:
  completed_at = _parse_dt(final_run_row.get("completed_at")) or _parse_dt(final_snapshot.get("updated_at")) or datetime.now(timezone.utc)
  last_heartbeat_at = _parse_dt(final_run_row.get("last_heartbeat_at")) or _parse_dt(final_snapshot.get("planning_last_heartbeat_at"))
  checkpoint_created_at = _parse_dt(final_checkpoint.get("created_at"))
  latest_event_created_at = None
  if final_events:
    latest_event_created_at = _parse_dt(final_events[0].get("created_at"))

  run_completed_event_seen = any(str(item.get("event_type") or "").strip() == "run_completed" for item in final_events)
  state_stages = [
    str(item.get("planning_stage") or "").strip()
    for item in seen_states
    if str(item.get("planning_stage") or "").strip()
  ]
  run_stages = [
    str(item.get("current_stage") or "").strip()
    for item in seen_run_states
    if str(item.get("current_stage") or "").strip()
  ]
  unique_state_stages = sorted({item for item in state_stages if item})
  unique_run_stages = sorted({item for item in run_stages if item})
  heartbeat_age_seconds = _seconds_between(completed_at, last_heartbeat_at)
  checkpoint_age_seconds = _seconds_between(completed_at, checkpoint_created_at)
  last_event_age_seconds = _seconds_between(completed_at, latest_event_created_at)
  completed_cleanly = bool(
    proc_returncode == 0
    and str(final_snapshot.get("status") or "").strip().lower() == "completed"
    and str(final_snapshot.get("planning_stage") or "").strip() == "convergence_completed"
    and str(final_run_row.get("run_status") or "").strip().lower() == "completed"
    and str(final_run_row.get("current_stage") or "").strip() == "convergence_completed"
    and run_completed_event_seen
  )
  return {
    "contract_version": "monitor_health_summary_v1",
    "runner_returncode": proc_returncode,
    "draft_state_change_count": len(seen_states),
    "planning_run_state_change_count": len(seen_run_states),
    "saw_draft_progress": len(seen_states) > 1,
    "saw_planning_run_progress": len(seen_run_states) > 1,
    "unique_draft_stages": unique_state_stages,
    "unique_planning_run_stages": unique_run_stages,
    "latest_draft_stage": str(final_snapshot.get("planning_stage") or "").strip() or None,
    "latest_run_stage": str(final_run_row.get("current_stage") or "").strip() or None,
    "latest_run_status": str(final_run_row.get("run_status") or "").strip() or None,
    "latest_checkpoint_kind": str(final_checkpoint.get("checkpoint_kind") or "").strip() or None,
    "recent_stage_event_count": len(final_events),
    "run_completed_event_seen": run_completed_event_seen,
    "last_heartbeat_age_seconds": heartbeat_age_seconds,
    "last_checkpoint_age_seconds": checkpoint_age_seconds,
    "last_event_age_seconds": last_event_age_seconds,
    "heartbeat_present": last_heartbeat_at is not None,
    "checkpoint_present": bool(final_checkpoint),
    "recent_events_present": bool(final_events),
    "completed_cleanly": completed_cleanly,
  }


def _proxy_clean_env() -> Dict[str, str]:
  env = dict(os.environ)
  for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    env.pop(key, None)
  env["NO_PROXY"] = "127.0.0.1,localhost"
  env["no_proxy"] = "127.0.0.1,localhost"
  return env


def main(argv: list[str]) -> int:
  parser = argparse.ArgumentParser(description="Run a live E2E intake/system-run and poll persisted SQL state.")
  parser.add_argument("prompt", help="Business prompt to send to the live runner.")
  parser.add_argument("--base-url", default="http://127.0.0.1:5050", help="Local API base URL.")
  parser.add_argument("--poll-seconds", type=float, default=10.0, help="SQL polling cadence while the run is active.")
  parser.add_argument("--runner", default=str(DEFAULT_RUNNER_PATH), help="Runner script path to execute.")
  parser.add_argument("--stdout-path", default="", help="Optional stdout capture file.")
  parser.add_argument("--stderr-path", default="", help="Optional stderr capture file.")
  parser.add_argument("--result-path", default="", help="Optional path to persist the final monitor payload as JSON.")
  parser.add_argument("--event-limit", type=int, default=12, help="Number of most-recent planning stage events to include in the final artifact.")
  parser.add_argument(
    "--validate-cutover",
    action="store_true",
    help="Run cutover validation against the final monitor payload and fail if acceptance checks do not pass.",
  )
  args = parser.parse_args(argv)

  get_mysql_connection = _load_db()

  runner_path = Path(args.runner)
  if not runner_path.is_absolute():
    runner_path = (REPO_ROOT / runner_path).resolve()

  start_ts = _utc_now_sql()
  stdout_path = Path(args.stdout_path or f"tmp_{int(time.time())}_live_e2e_stdout.txt")
  stderr_path = Path(args.stderr_path or f"tmp_{int(time.time())}_live_e2e_stderr.txt")

  cmd = [
    str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"),
    "-u",
    str(runner_path),
    args.prompt,
    "--base-url",
    args.base_url,
  ]
  print(json.dumps({"event": "runner_start", "prompt": args.prompt, "start_utc": start_ts, "cmd": cmd}), flush=True)

  stdout_file = stdout_path.open("w", encoding="utf-8")
  stderr_file = stderr_path.open("w", encoding="utf-8")
  proc = subprocess.Popen(
    cmd,
    cwd=str(REPO_ROOT),
    env=_proxy_clean_env(),
    stdout=stdout_file,
    stderr=stderr_file,
    shell=False,
  )

  draft_id: Optional[str] = None
  planning_run_id: Optional[str] = None
  last_snapshot: Dict[str, Any] = {}
  last_run_snapshot: Dict[str, Any] = {}
  seen_states: list[Dict[str, Any]] = []
  seen_run_states: list[Dict[str, Any]] = []

  try:
    while True:
      row = (
        _draft_by_id(get_mysql_connection=get_mysql_connection, draft_id=draft_id)
        if draft_id
        else _latest_draft_after(get_mysql_connection=get_mysql_connection, after_ts=start_ts)
      )
      if isinstance(row, dict):
        if draft_id is None and row.get("draft_id"):
          draft_id = str(row.get("draft_id"))
          print(json.dumps({"event": "draft_detected", "draft_id": draft_id}), flush=True)
        if row.get("planning_run_id"):
          next_run_id = str(row.get("planning_run_id"))
          if planning_run_id != next_run_id:
            planning_run_id = next_run_id
            print(json.dumps({"event": "planning_run_detected", "planning_run_id": planning_run_id}), flush=True)
        snap = _snapshot(row)
        if snap and snap != last_snapshot:
          seen_states.append(snap)
          print(json.dumps({"event": "state_change", "state": snap}), flush=True)
          last_snapshot = snap
      if planning_run_id:
        run_row = _planning_run_by_id(get_mysql_connection=get_mysql_connection, planning_run_id=planning_run_id)
        run_snap = _planning_run_snapshot(run_row)
        if run_snap and run_snap != last_run_snapshot:
          seen_run_states.append(run_snap)
          print(json.dumps({"event": "planning_run_change", "planning_run": run_snap}), flush=True)
          last_run_snapshot = run_snap
      rc = proc.poll()
      if rc is not None:
        print(json.dumps({"event": "runner_exit", "returncode": rc}), flush=True)
        break
      time.sleep(max(args.poll_seconds, 1.0))
  finally:
    stdout_file.close()
    stderr_file.close()

  final_row = _draft_by_id(get_mysql_connection=get_mysql_connection, draft_id=draft_id) if draft_id else None
  if not planning_run_id and isinstance(final_row, dict) and final_row.get("planning_run_id"):
    planning_run_id = str(final_row.get("planning_run_id"))
  final_run_row = (
    _planning_run_by_id(get_mysql_connection=get_mysql_connection, planning_run_id=planning_run_id)
    if planning_run_id
    else None
  )
  final_checkpoint = (
    _latest_checkpoint_for_run(get_mysql_connection=get_mysql_connection, planning_run_id=planning_run_id)
    if planning_run_id
    else None
  )
  final_events = (
    _recent_stage_events_for_run(
      get_mysql_connection=get_mysql_connection,
      planning_run_id=planning_run_id,
      limit=args.event_limit,
    )
    if planning_run_id
    else []
  )
  final_snapshot = _snapshot(final_row)
  final_planning_run_row = _planning_run_snapshot(final_run_row)
  final_latest_checkpoint = _checkpoint_snapshot(final_checkpoint)
  final_recent_stage_events = [
    {
      **event,
      "created_at": str(event.get("created_at")),
    }
    for event in final_events
  ]
  final_monitor_health_summary = _monitor_health_summary(
    proc_returncode=proc.returncode,
    seen_states=seen_states,
    seen_run_states=seen_run_states,
    final_snapshot=final_snapshot,
    final_run_row=final_planning_run_row,
    final_checkpoint=final_latest_checkpoint,
    final_events=final_recent_stage_events,
  )
  final_payload = {
    "event": "final_row",
    "draft_id": draft_id,
    "planning_run_id": planning_run_id,
    "stdout_path": str(stdout_path),
    "stderr_path": str(stderr_path),
    "seen_state_count": len(seen_states),
    "seen_states": seen_states,
    "seen_planning_run_state_count": len(seen_run_states),
    "seen_planning_run_states": seen_run_states,
    "final_snapshot": final_snapshot,
    "final_planning_run_row": final_planning_run_row,
    "final_latest_checkpoint": final_latest_checkpoint,
    "final_recent_stage_events": final_recent_stage_events,
    "final_monitor_health_summary": final_monitor_health_summary,
    "final_planning_run": _parse_json(final_row.get("planning_run_json")) if isinstance(final_row, dict) else None,
    "final_convergence_state": _parse_json(final_row.get("convergence_state_json")) if isinstance(final_row, dict) else None,
    "final_numeric_solver_feedback": _parse_json(final_row.get("numeric_solver_feedback_json")) if isinstance(final_row, dict) else None,
  }
  result_path = Path(args.result_path).resolve() if str(args.result_path or "").strip() else (REPO_ROOT / "tmp_live_e2e_monitor_result.json")
  result_path.write_text(json.dumps(final_payload, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
  print(json.dumps(final_payload, default=str), flush=True)

  if args.validate_cutover:
    validation_errors = validate_loaded_document(final_payload)
    validation_event = {
      "event": "cutover_validation",
      "result_path": str(result_path),
      "passed": not validation_errors,
      "errors": validation_errors,
    }
    print(json.dumps(validation_event, default=str), flush=True)
    if validation_errors:
      return 5

  if proc.returncode != 0:
    return int(proc.returncode or 1)
  if not isinstance(final_row, dict):
    print("No persisted draft row found for live run.", file=sys.stderr)
    return 2
  if str(final_row.get("status") or "").strip().lower() != "completed":
    print("Final draft row did not complete.", file=sys.stderr)
    return 3
  if str(final_row.get("planning_stage") or "").strip() != "convergence_completed":
    print("Final planning stage did not reach convergence_completed.", file=sys.stderr)
    return 4
  return 0


if __name__ == "__main__":
  raise SystemExit(main(sys.argv[1:]))
