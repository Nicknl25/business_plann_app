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


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNNER_PATH = REPO_ROOT / "Test Files" / "run_live_args_intake.py"


def _utc_now_sql() -> str:
  return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


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
             planning_stage, planning_status,
             planning_last_review_iteration,
             planning_detected_issue_count,
             planning_remaining_issue_count,
             planning_resolved_issue_count,
             planning_tolerated_issue_count,
             planning_iteration_pending_issue_count,
             planning_run_json,
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
             planning_stage, planning_status,
             planning_last_review_iteration,
             planning_detected_issue_count,
             planning_remaining_issue_count,
             planning_resolved_issue_count,
             planning_tolerated_issue_count,
             planning_iteration_pending_issue_count,
             planning_run_json,
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
    "planning_stage": row.get("planning_stage"),
    "planning_status": row.get("planning_status"),
    "planning_last_review_iteration": row.get("planning_last_review_iteration"),
    "planning_detected_issue_count": row.get("planning_detected_issue_count"),
    "planning_remaining_issue_count": row.get("planning_remaining_issue_count"),
    "planning_resolved_issue_count": row.get("planning_resolved_issue_count"),
    "planning_tolerated_issue_count": row.get("planning_tolerated_issue_count"),
    "planning_iteration_pending_issue_count": row.get("planning_iteration_pending_issue_count"),
    "updated_at": str(row.get("updated_at")),
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
  last_snapshot: Dict[str, Any] = {}
  seen_states: list[Dict[str, Any]] = []

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
        snap = _snapshot(row)
        if snap and snap != last_snapshot:
          seen_states.append(snap)
          print(json.dumps({"event": "state_change", "state": snap}), flush=True)
          last_snapshot = snap
      rc = proc.poll()
      if rc is not None:
        print(json.dumps({"event": "runner_exit", "returncode": rc}), flush=True)
        break
      time.sleep(max(args.poll_seconds, 1.0))
  finally:
    stdout_file.close()
    stderr_file.close()

  final_row = _draft_by_id(get_mysql_connection=get_mysql_connection, draft_id=draft_id) if draft_id else None
  final_payload = {
    "event": "final_row",
    "draft_id": draft_id,
    "stdout_path": str(stdout_path),
    "stderr_path": str(stderr_path),
    "seen_state_count": len(seen_states),
    "seen_states": seen_states,
    "final_snapshot": _snapshot(final_row),
    "final_planning_run": _parse_json(final_row.get("planning_run_json")) if isinstance(final_row, dict) else None,
    "final_numeric_solver_feedback": _parse_json(final_row.get("numeric_solver_feedback_json")) if isinstance(final_row, dict) else None,
  }
  print(json.dumps(final_payload, default=str), flush=True)

  if proc.returncode != 0:
    return int(proc.returncode or 1)
  if not isinstance(final_row, dict):
    print("No persisted draft row found for live run.", file=sys.stderr)
    return 2
  if str(final_row.get("status") or "").strip().lower() != "completed":
    print("Final draft row did not complete.", file=sys.stderr)
    return 3
  if str(final_row.get("planning_stage") or "").strip() != "final_viability_guaranteed":
    print("Final planning stage did not reach final_viability_guaranteed.", file=sys.stderr)
    return 4
  return 0


if __name__ == "__main__":
  raise SystemExit(main(sys.argv[1:]))
