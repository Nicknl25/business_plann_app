"""Post-intake run supervisor: the unattended half of the recovery design.

One pass (default) does three things, in order:

  1. REAP — a planning run stuck at run_status='running' whose freshest
     heartbeat is older than --stall-seconds is a dead run (process died
     mid-run; nothing else ever transitions it). Mark it failed
     (failure_reason=heartbeat_stale) so the draft is un-wedged and the
     rerun ladder can pick it up. Email the alerts inbox.

  2. RERUN LADDER — for each draft whose LATEST run is failed and not
     superseded, count supervisor rerun attempts since the draft's last
     completed run and schedule the next clean rerun on the ladder
     (default 10m / 1h / 6h / 24h after the failure). A rerun is a full
     restart (lifecycle_mode="rerun"): provenance-linked, superseding,
     clean rebuild — previously-successful GPT calls replay from the
     response-lock store, so the retry pays only for the calls that
     failed. Fail-loud runs and dead runs ride the same ladder (an
     OpenAI outage looks the same either way; immediate rerun would
     just re-fail). At most one rerun is executed per pass (serial —
     one server process, one run at a time).

  3. DEAD-LETTER — ladder exhausted: send the GUARANTEED internal
     escalation (once per failure chain). Delivery is human-mediated
     ("we'll follow up in 5-7 business days"), so there is NO
     client-facing email — the escalation exists so a human follows up
     inside the promised window.

Every action lands in supervisor_actions (queryable — feeds the admin
view). Designed to run from a scheduled task every ~5 minutes:

  .venv\\Scripts\\python.exe scripts\\run_supervisor.py
"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LADDER_SECONDS = (600, 3600, 21600, 86400)

_ACTIONS_DDL = """
CREATE TABLE IF NOT EXISTS supervisor_actions (
  action_id BIGINT AUTO_INCREMENT PRIMARY KEY,
  draft_id VARCHAR(64) NOT NULL,
  planning_run_id VARCHAR(64) NULL,
  action VARCHAR(32) NOT NULL,
  attempt_number INT NULL,
  outcome VARCHAR(64) NOT NULL,
  detail TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY ix_draft (draft_id),
  KEY ix_run (planning_run_id),
  KEY ix_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def _connect():
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore

  return get_mysql_connection()


def _send_email(subject: str, body: str) -> Dict[str, Any]:
  """Internal alerts email (EMAIL_* env). Never raises — an email failure
  must not stop the supervisor from acting; the failure is recorded in
  supervisor_actions.detail instead."""
  try:
    host = os.environ["EMAIL_HOST"]
    port = int(os.environ.get("EMAIL_PORT", "587"))
    user = os.environ["EMAIL_USER"]
    password = os.environ["EMAIL_PASSWORD"]
    to = os.environ["EMAIL_ALERTS_ADDRESS"]
  except KeyError as exc:
    return {"sent": False, "reason": f"missing_env:{exc}"}
  try:
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    with smtplib.SMTP(host, port, timeout=30) as server:
      server.starttls()
      server.login(user, password)
      server.sendmail(user, [to], msg.as_string())
    return {"sent": True, "recipient": to}
  except Exception as exc:  # noqa: BLE001 — declared: email is best-effort
    return {"sent": False, "reason": f"{type(exc).__name__}: {exc}"}


def _record(conn, *, draft_id: str, run_id: Optional[str], action: str,
            attempt: Optional[int], outcome: str, detail: Any) -> None:
  cur = conn.cursor()
  try:
    cur.execute(
      "INSERT INTO supervisor_actions (draft_id, planning_run_id, action, "
      "attempt_number, outcome, detail) VALUES (%s, %s, %s, %s, %s, %s)",
      (
        draft_id, run_id, action, attempt, outcome,
        json.dumps(detail, default=str)[:4000] if not isinstance(detail, str) else detail[:4000],
      ),
    )
    conn.commit()
  finally:
    cur.close()


def _business_name(conn, draft_id: str) -> str:
  cur = conn.cursor()
  try:
    cur.execute(
      "SELECT business_name FROM intake_consult_drafts WHERE draft_id = %s",
      (draft_id,),
    )
    row = cur.fetchone()
    return str(row[0]) if row and row[0] else draft_id
  finally:
    cur.close()


def reap_dead_runs(conn, *, stall_seconds: float) -> List[Dict[str, Any]]:
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      """
      SELECT planning_run_id, draft_id, current_stage, last_heartbeat_at, updated_at
      FROM planning_runs
      WHERE run_status = 'running'
        AND COALESCE(last_heartbeat_at, updated_at, started_at)
              < NOW() - INTERVAL %s SECOND
      """,
      (int(stall_seconds),),
    )
    dead = [dict(r) for r in (cur.fetchall() or [])]
  finally:
    cur.close()
  reaped = []
  for run in dead:
    run_id = str(run["planning_run_id"])
    draft_id = str(run["draft_id"])
    cur = conn.cursor()
    try:
      # completed_at = the LAST HEARTBEAT, not the moment the reaper
      # noticed: the run died back then. This also keeps freshly-reaped
      # historical zombies outside the ladder's --since-hours window —
      # stamping NOW() on first activation put 54 archive drafts on the
      # ladder and reran one (it 500'd; archives are not rerunnable).
      cur.execute(
        """
        UPDATE planning_runs
        SET run_status = 'failed', current_stage_status = 'failed',
            failure_reason = %s,
            completed_at = COALESCE(last_heartbeat_at, updated_at, NOW()),
            updated_at = NOW()
        WHERE planning_run_id = %s AND run_status = 'running'
        """,
        (
          f"heartbeat_stale: no heartbeat for >{int(stall_seconds)}s "
          f"at stage {run.get('current_stage')}",
          run_id,
        ),
      )
      conn.commit()
    finally:
      cur.close()
    _record(conn, draft_id=draft_id, run_id=run_id, action="reap", attempt=None,
            outcome="marked_failed", detail={"stage": run.get("current_stage")})
    reaped.append(run)
    print(json.dumps({"event": "reaped", "planning_run_id": run_id, "draft_id": draft_id}), flush=True)
  if reaped:
    # ONE summary email per pass — first activation reaps a backlog of
    # historical zombies and must not flood the inbox.
    lines = [
      f"  {r['planning_run_id']}  draft={r['draft_id']}  stage={r.get('current_stage')}"
      for r in reaped[:40]
    ]
    if len(reaped) > 40:
      lines.append(f"  ... and {len(reaped) - 40} more")
    _send_email(
      f"SUPERVISOR: reaped {len(reaped)} dead run(s)",
      f"{len(reaped)} planning run(s) had no heartbeat for >{int(stall_seconds)}s "
      f"and were marked failed (server process died mid-run). Recent failures "
      f"enter the rerun ladder; historical ones are outside --since-hours and "
      f"stay failed.\n\n" + "\n".join(lines),
    )
  return reaped


def _rerun_candidates(conn, *, since_hours: float) -> List[Dict[str, Any]]:
  """Drafts whose LATEST run is failed, not superseded, and RECENT.

  The recency bound exists so first activation does not ladder months of
  historical test failures (including deliberately-doomed scenarios) —
  the supervisor owns failures from its own watch, not the archive."""
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      """
      SELECT pr.planning_run_id, pr.draft_id, pr.failure_reason,
             COALESCE(pr.completed_at, pr.updated_at) AS failed_at
      FROM planning_runs pr
      JOIN (
        SELECT draft_id, MAX(started_at) AS max_started
        FROM planning_runs GROUP BY draft_id
      ) latest ON latest.draft_id = pr.draft_id AND latest.max_started = pr.started_at
      WHERE pr.run_status = 'failed'
        AND pr.superseded_by_planning_run_id IS NULL
        AND COALESCE(pr.completed_at, pr.updated_at) > NOW() - INTERVAL %s HOUR
      """,
      (int(since_hours),),
    )
    return [dict(r) for r in (cur.fetchall() or [])]
  finally:
    cur.close()


def _attempts_since_last_success(conn, draft_id: str) -> int:
  cur = conn.cursor()
  try:
    cur.execute(
      """
      SELECT COUNT(*) FROM supervisor_actions
      WHERE draft_id = %s AND action = 'rerun'
        AND created_at > COALESCE(
          (SELECT MAX(completed_at) FROM planning_runs
           WHERE draft_id = %s AND run_status = 'completed'),
          '1970-01-01')
      """,
      (draft_id, draft_id),
    )
    return int(cur.fetchone()[0] or 0)
  finally:
    cur.close()


def _dead_letter_already_sent(conn, draft_id: str) -> bool:
  cur = conn.cursor()
  try:
    cur.execute(
      """
      SELECT COUNT(*) FROM supervisor_actions
      WHERE draft_id = %s AND action = 'dead_letter'
        AND created_at > COALESCE(
          (SELECT MAX(completed_at) FROM planning_runs
           WHERE draft_id = %s AND run_status = 'completed'),
          '1970-01-01')
      """,
      (draft_id, draft_id),
    )
    return int(cur.fetchone()[0] or 0) > 0
  finally:
    cur.close()


def run_ladder(conn, *, base_url: str, ladder: tuple, run_timeout: float,
               since_hours: float, dry_run: bool) -> None:
  now = datetime.now(timezone.utc)
  for cand in _rerun_candidates(conn, since_hours=since_hours):
    draft_id = str(cand["draft_id"])
    run_id = str(cand["planning_run_id"])
    attempts = _attempts_since_last_success(conn, draft_id)
    if dry_run:
      print(json.dumps({
        "event": "dry_run_candidate", "draft_id": draft_id, "run_id": run_id,
        "attempts": attempts, "failure": str(cand.get("failure_reason") or "")[:160],
      }), flush=True)
      continue
    if attempts >= len(ladder):
      if not _dead_letter_already_sent(conn, draft_id):
        name = _business_name(conn, draft_id)
        email = _send_email(
          f"SUPERVISOR DEAD-LETTER: {name} — no plan after {attempts} reruns",
          f"Draft {draft_id} ({name}) still fails after {attempts} supervised "
          f"reruns over the full ladder.\n"
          f"Latest run: {run_id}\nFailure: {cand.get('failure_reason')}\n\n"
          f"NO PLAN WILL ARRIVE WITHOUT HUMAN ACTION. The client was promised "
          f"follow-up within 5-7 business days — this needs a human inside "
          f"that window.",
        )
        _record(conn, draft_id=draft_id, run_id=run_id, action="dead_letter",
                attempt=attempts, outcome="escalated", detail={"email": email})
        print(json.dumps({"event": "dead_letter", "draft_id": draft_id}), flush=True)
      continue

    failed_at = cand.get("failed_at")
    if isinstance(failed_at, datetime):
      failed_at_utc = failed_at.replace(tzinfo=timezone.utc) if failed_at.tzinfo is None else failed_at
    else:
      failed_at_utc = now
    due = failed_at_utc + timedelta(seconds=ladder[attempts])
    if now < due:
      continue

    attempt_number = attempts + 1
    print(json.dumps({
      "event": "rerun_start", "draft_id": draft_id, "source_run": run_id,
      "attempt": attempt_number,
    }), flush=True)
    try:
      # NOTE: no planning_run_id in the body — in rerun mode that field
      # names the NEW run's id (begin_planning_run: requested_run_id or
      # uuid4), not the source; passing the failed run's id collides with
      # the primary key. The source is the draft's latest run implicitly.
      resp = requests.post(
        f"{base_url}/api/intake-consult/system-run",
        json={"draft_id": draft_id, "lifecycle_mode": "rerun"},
        timeout=run_timeout,
      )
      outcome = "rerun_completed" if resp.status_code == 200 else f"rerun_failed_http_{resp.status_code}"
      detail: Any = {"status": resp.status_code, "body": str(resp.text)[:1500]}
    except Exception as exc:  # noqa: BLE001 — declared: outcome recorded, ladder continues
      outcome = "rerun_request_error"
      detail = f"{type(exc).__name__}: {exc}"
    _record(conn, draft_id=draft_id, run_id=run_id, action="rerun",
            attempt=attempt_number, outcome=outcome, detail=detail)
    print(json.dumps({"event": "rerun_done", "draft_id": draft_id, "outcome": outcome}), flush=True)
    break  # serial: at most one rerun per supervisor pass


def main(argv: List[str]) -> int:
  parser = argparse.ArgumentParser(description="Reap dead runs, ladder reruns, dead-letter escalation.")
  parser.add_argument("--base-url", default="http://127.0.0.1:5050")
  parser.add_argument("--stall-seconds", type=float, default=900.0)
  parser.add_argument("--ladder", default=",".join(str(s) for s in DEFAULT_LADDER_SECONDS),
                      help="Comma-separated rerun delays in seconds after each failure.")
  parser.add_argument("--run-timeout", type=float, default=1800.0,
                      help="HTTP timeout for a synchronous rerun POST.")
  parser.add_argument("--since-hours", type=float, default=24.0,
                      help="Only failures newer than this are ladder candidates.")
  parser.add_argument("--dry-run", action="store_true",
                      help="Report reap/ladder decisions without acting.")
  args = parser.parse_args(argv)
  ladder = tuple(int(s) for s in str(args.ladder).split(",") if s.strip())

  conn = _connect()
  try:
    cur = conn.cursor()
    cur.execute(_ACTIONS_DDL)
    conn.commit()
    cur.close()
    if args.dry_run:
      cur = conn.cursor(dictionary=True)
      cur.execute(
        "SELECT planning_run_id, draft_id, current_stage FROM planning_runs "
        "WHERE run_status = 'running' AND COALESCE(last_heartbeat_at, updated_at, started_at)"
        " < NOW() - INTERVAL %s SECOND",
        (int(args.stall_seconds),),
      )
      for run in cur.fetchall() or []:
        print(json.dumps({"event": "dry_run_would_reap", **{k: str(v) for k, v in run.items()}}), flush=True)
      cur.close()
    else:
      reap_dead_runs(conn, stall_seconds=args.stall_seconds)
    run_ladder(
      conn, base_url=args.base_url, ladder=ladder, run_timeout=args.run_timeout,
      since_hours=args.since_hours, dry_run=args.dry_run,
    )
  finally:
    conn.close()
  return 0


if __name__ == "__main__":
  raise SystemExit(main(sys.argv[1:]))
