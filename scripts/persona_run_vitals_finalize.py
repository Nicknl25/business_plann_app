"""Finalize run-vitals for one watched persona run.

Invoked by scripts/persona_session_watch.py after each watch-only monitor
exits. Reads the monitor's --result-path JSON, aggregates the per-turn /
per-GPT-call vitals rows the app wrote live, resolves the final verdict
(draft status, planning stage, coherence status, run status), best-effort
links the OneDrive transcript file, then INSERTs one run_vitals_runs summary
row plus watcher-sourced run_vitals_events rows (stall / terminal / recycle).

Standalone + idempotent-enough: INSERT-only, so re-finalizing a run adds a
newer summary row (latest created_at wins). Exit code 0 even when data is
missing — finalization is observability, never a gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRANSCRIPT_DIR = (
  r"C:\Users\IgnatiusHenry\OneDrive - Tithe Financial Wealth Management"
  r"\Apps\Test Runs"
)


def _bootstrap():
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))


def _parse_json(raw: Any) -> Any:
  if raw is None:
    return None
  if isinstance(raw, (dict, list)):
    return raw
  try:
    return json.loads(raw)
  except Exception:
    return None


def _one_row(conn, sql: str, params: tuple) -> Optional[Dict[str, Any]]:
  cur = conn.cursor()
  try:
    cur.execute(sql, params)
    row = cur.fetchone()
    if row is None:
      return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))
  finally:
    cur.close()


def _turn_aggregates(conn, draft_id: str) -> Dict[str, Any]:
  row = _one_row(
    conn,
    """
    SELECT COUNT(*) AS turns,
           COALESCE(SUM(latency_ms), 0) AS total_turn_ms,
           COALESCE(SUM(gpt_calls), 0) AS gpt_calls,
           COALESCE(SUM(gpt_elapsed_ms), 0) AS gpt_elapsed_ms,
           COALESCE(SUM(gpt_tokens_in), 0) AS gpt_tokens_in,
           COALESCE(SUM(gpt_tokens_out), 0) AS gpt_tokens_out,
           COALESCE(SUM(gpt_lock_replays), 0) AS gpt_lock_replays,
           COALESCE(SUM(hold), 0) AS holds,
           SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS errors,
           MIN(created_at) AS intake_first_turn_at,
           MAX(created_at) AS intake_last_turn_at
    FROM run_vitals_turns WHERE draft_id = %s
    """,
    (draft_id,),
  )
  return row or {}


def _post_intake_gpt_aggregates(conn, draft_id: str) -> Dict[str, Any]:
  row = _one_row(
    conn,
    """
    SELECT COUNT(*) AS gpt_calls,
           COALESCE(SUM(elapsed_ms), 0) AS gpt_elapsed_ms,
           COALESCE(SUM(tokens_in), 0) AS gpt_tokens_in,
           COALESCE(SUM(tokens_out), 0) AS gpt_tokens_out,
           COALESCE(SUM(lock_replay), 0) AS gpt_lock_replays,
           SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS errors
    FROM run_vitals_gpt_calls WHERE draft_id = %s AND phase = 'post_intake'
    """,
    (draft_id,),
  )
  return row or {}


def _draft_row(conn, draft_id: str) -> Dict[str, Any]:
  row = _one_row(
    conn,
    """
    SELECT client_id, business_name, status, planning_stage,
           planning_run_id, financials_json
    FROM intake_consult_drafts WHERE draft_id = %s
    """,
    (draft_id,),
  )
  return row or {}


def _planning_run_row(conn, planning_run_id: str) -> Dict[str, Any]:
  if not planning_run_id:
    return {}
  row = _one_row(
    conn,
    """
    SELECT run_status, started_at, completed_at, stopped_at
    FROM planning_runs WHERE planning_run_id = %s
    """,
    (planning_run_id,),
  )
  return row or {}


def _coherence_status(financials_json_raw: Any) -> str:
  fin = _parse_json(financials_json_raw)
  if not isinstance(fin, dict):
    return ""
  coh = fin.get("_coherence")
  if isinstance(coh, dict):
    return str(coh.get("status") or "")
  return ""


def _find_transcript(
  transcript_dir: str, first_turn_at: Optional[datetime]
) -> Optional[str]:
  """Newest file in the Test Runs dir modified since shortly before the
  run's first turn — best-effort link, adjudicated by a human later."""
  try:
    base = Path(transcript_dir)
    if not base.is_dir():
      return None
    cutoff = (
      (first_turn_at - timedelta(minutes=10)).timestamp()
      if first_turn_at is not None
      else 0.0
    )
    candidates = [
      p for p in base.rglob("*")
      if p.is_file() and p.stat().st_mtime >= cutoff
    ]
    if not candidates:
      return None
    return str(max(candidates, key=lambda p: p.stat().st_mtime))
  except Exception:
    return None


def main(argv) -> int:
  parser = argparse.ArgumentParser(description="Finalize run-vitals for one persona run.")
  parser.add_argument("--result-path", default=str(REPO_ROOT / "tmp_persona_watch_result.json"))
  parser.add_argument("--transcript-dir", default=DEFAULT_TRANSCRIPT_DIR)
  parser.add_argument("--stalls", type=int, default=0,
                      help="Stall events the watcher observed during this watch.")
  args = parser.parse_args(argv)

  _bootstrap()
  from intake_submission import get_mysql_connection  # type: ignore
  from client_intake_and_finmo import run_vitals  # type: ignore

  try:
    result = json.loads(Path(args.result_path).read_text(encoding="utf-8"))
  except Exception as exc:
    print(f"vitals-finalize: no result payload ({type(exc).__name__}); nothing to record", flush=True)
    return 0

  draft_id = str(result.get("draft_id") or "").strip()
  if not draft_id:
    print("vitals-finalize: watch ended with no draft; nothing to record", flush=True)
    return 0
  planning_run_id = str(result.get("planning_run_id") or "").strip()
  exit_reason = str(result.get("exit_reason") or "").strip()
  terminal_run_status = str(result.get("terminal_run_status") or "").strip()

  conn = get_mysql_connection()
  try:
    turns = _turn_aggregates(conn, draft_id)
    post_gpt = _post_intake_gpt_aggregates(conn, draft_id)
    draft = _draft_row(conn, draft_id)
    if not planning_run_id:
      planning_run_id = str(draft.get("planning_run_id") or "").strip()
    run_row = _planning_run_row(conn, planning_run_id)
  finally:
    try:
      conn.close()
    except Exception:
      pass

  started_at = run_row.get("started_at")
  completed_at = run_row.get("completed_at") or run_row.get("stopped_at")
  run_seconds = None
  if isinstance(started_at, datetime) and isinstance(completed_at, datetime):
    run_seconds = int((completed_at - started_at).total_seconds())

  first_turn_at = turns.get("intake_first_turn_at")
  if isinstance(first_turn_at, datetime) and first_turn_at.tzinfo is None:
    # DB DATETIMEs are naive local time; transcript mtimes are epoch — treat
    # the naive stamp as local for the mtime cutoff.
    first_turn_local = first_turn_at
  else:
    first_turn_local = first_turn_at if isinstance(first_turn_at, datetime) else None
  transcript_path = _find_transcript(args.transcript_dir, first_turn_local)

  # Watcher-sourced events for the run's event stream.
  run_vitals.record_event(
    draft_id=draft_id,
    planning_run_id=planning_run_id,
    source="watcher",
    event_type=f"watch_end_{exit_reason or 'unknown'}",
    detail={
      "terminal_run_status": terminal_run_status,
      "stalls_observed": int(args.stalls or 0),
      "transcript_path": transcript_path,
    },
  )

  summary = {
    "draft_id": draft_id,
    "client_id": str(draft.get("client_id") or ""),
    "business_name": draft.get("business_name"),
    "planning_run_id": planning_run_id,
    "exit_reason": exit_reason,
    "draft_status": str(draft.get("status") or ""),
    "run_status": terminal_run_status or str(run_row.get("run_status") or ""),
    "planning_stage": str(draft.get("planning_stage") or ""),
    "coherence_status": _coherence_status(draft.get("financials_json")),
    "turns": int(turns.get("turns") or 0),
    "intake_first_turn_at": turns.get("intake_first_turn_at"),
    "intake_last_turn_at": turns.get("intake_last_turn_at"),
    "total_turn_ms": int(turns.get("total_turn_ms") or 0),
    "gpt_calls": int(turns.get("gpt_calls") or 0) + int(post_gpt.get("gpt_calls") or 0),
    "gpt_elapsed_ms": int(turns.get("gpt_elapsed_ms") or 0) + int(post_gpt.get("gpt_elapsed_ms") or 0),
    "gpt_tokens_in": int(turns.get("gpt_tokens_in") or 0) + int(post_gpt.get("gpt_tokens_in") or 0),
    "gpt_tokens_out": int(turns.get("gpt_tokens_out") or 0) + int(post_gpt.get("gpt_tokens_out") or 0),
    "gpt_lock_replays": int(turns.get("gpt_lock_replays") or 0) + int(post_gpt.get("gpt_lock_replays") or 0),
    "holds": int(turns.get("holds") or 0),
    "errors": int(turns.get("errors") or 0) + int(post_gpt.get("errors") or 0),
    "stalls": int(args.stalls or 0),
    "run_started_at": started_at,
    "run_completed_at": completed_at,
    "run_seconds": run_seconds,
    "transcript_path": transcript_path,
  }
  run_vitals.insert_run_summary(summary)

  # Resolution-sensing pass over the shared issue database: every
  # open/recurring issue is evaluated against this run (recur / exercised
  # clean / not exercised). Best-effort — a checker failure must not lose
  # the vitals summary above.
  try:
    from client_intake_and_finmo import issue_registry  # type: ignore
    conn2 = get_mysql_connection()
    try:
      check = issue_registry.evaluate_run_for_resolution(conn2, draft_id=draft_id)
    finally:
      try:
        conn2.close()
      except Exception:
        pass
    print(
      "ISSUE CHECK: evaluated={ev} recurred={rc} exercised_clean={ec} "
      "not_exercised={ne} resolved_confirmed={cf} resolved_observational={ob}".format(
        ev=check["evaluated"], rc=check["recurred"],
        ec=check["exercised_clean"], ne=check["not_exercised"],
        cf=check["resolved_confirmed"] or "-",
        ob=check["resolved_observational"] or "-",
      ),
      flush=True,
    )
  except Exception as exc:
    print(f"ISSUE CHECK failed (continuing): {type(exc).__name__}: {exc}", flush=True)

  print(
    "RUN VITALS: draft={d} biz={b!r} exit={e} run_status={rs} stage={st} "
    "coherence={c} turns={t} turn_ms={tm} gpt_calls={g} gpt_ms={gm} "
    "tokens={ti}/{to} replays={lr} holds={h} errors={er} stalls={sl} "
    "run_s={rsec} transcript={tp}".format(
      d=draft_id[:8],
      b=str(summary["business_name"] or "?")[:40],
      e=exit_reason or "?",
      rs=summary["run_status"] or "?",
      st=summary["planning_stage"] or "?",
      c=summary["coherence_status"] or "?",
      t=summary["turns"],
      tm=summary["total_turn_ms"],
      g=summary["gpt_calls"],
      gm=summary["gpt_elapsed_ms"],
      ti=summary["gpt_tokens_in"],
      to=summary["gpt_tokens_out"],
      lr=summary["gpt_lock_replays"],
      h=summary["holds"],
      er=summary["errors"],
      sl=summary["stalls"],
      rsec=summary["run_seconds"],
      tp=transcript_path or "not-found",
    ),
    flush=True,
  )
  return 0


if __name__ == "__main__":
  raise SystemExit(main(sys.argv[1:]))
