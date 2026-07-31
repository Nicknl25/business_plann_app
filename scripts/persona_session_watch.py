"""Persona-session auto-watcher: sense the stack, observe runs, no prompts.

Loops forever (designed to be armed as a persistent background monitor):

  1. STACK SENSE -- poll until backend (:5050) and frontend (:5173) both
     accept TCP connections. Emit one line on up/down transitions.
  2. OBSERVE -- while the stack is up, run run_live_e2e_monitor.py
     --watch-only (newest draft created after watch start; per-turn DB
     state, stage transitions, stall detection) and compact its JSON
     events to one-line summaries on stdout. When a watch ends
     (terminal / stall / max-wait), loop and watch the next draft.
  3. SERVER LOG TAIL -- follow the newest _logs_persona_*.txt for the
     high-signal markers (TURN_BEGIN, TURN_HOLD, tracebacks) so
     intake-turn rhythm and holds surface live alongside DB state.

Each stdout line is an event for the observing Claude session. Serial
persona runs by design -- one draft watched at a time; an abandoned
intake recycles after --recycle-seconds so a later draft is picked up.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
MONITOR = REPO_ROOT / "scripts" / "run_live_e2e_monitor.py"
FINALIZER = REPO_ROOT / "scripts" / "persona_run_vitals_finalize.py"
PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
RESULT_PATH = REPO_ROOT / "tmp_persona_watch_result.json"

_LOG_MARKERS = ("TURN_BEGIN", "TURN_HOLD", "Traceback", "Failed intake consult")


def _emit(line: str) -> None:
  print(line, flush=True)


def _port_open(port: int, host: str = "localhost", timeout: float = 1.5) -> bool:
  # "localhost" not "127.0.0.1": create_connection tries every resolved
  # family, and vite binds ::1 (IPv6) only on this machine.
  try:
    with socket.create_connection((host, port), timeout=timeout):
      return True
  except OSError:
    return False


def _stack_up(backend_port: int, frontend_port: int) -> bool:
  return _port_open(backend_port) and _port_open(frontend_port)


def _compact(raw_line: str) -> Optional[str]:
  """One-line summary per monitor event; None drops the line."""
  try:
    evt: Dict[str, Any] = json.loads(raw_line)
  except (ValueError, TypeError):
    return None
  kind = evt.get("event")
  if kind == "watch_start":
    return None  # our own loop announces observation
  if kind == "draft_detected":
    return f"DRAFT {str(evt.get('draft_id'))[:8]} detected -- intake in progress"
  if kind == "planning_run_detected":
    return f"RUN {str(evt.get('planning_run_id'))[:8]} started -- system run active"
  if kind == "state_change":
    s = evt.get("state") or {}
    return (
      f"draft {str(s.get('draft_id'))[:8]}: status={s.get('status')} "
      f"focus={s.get('active_focus')} stage={s.get('planning_stage')}/{s.get('planning_status')}"
    )
  if kind == "planning_run_change":
    r = evt.get("planning_run") or {}
    return (
      f"run {str(r.get('planning_run_id'))[:8]}: {r.get('current_stage')} "
      f"{r.get('current_stage_status')} iter={r.get('current_iteration')} "
      f"cycle={r.get('current_cycle')} issues={r.get('latest_remaining_issue_count')}"
    )
  if kind == "stall_detected":
    return (
      f"STALL: run {str(evt.get('planning_run_id'))[:8]} silent "
      f"{round(float(evt.get('age_seconds') or 0))}s (threshold {evt.get('stall_seconds')})"
    )
  if kind == "run_terminal":
    return f"RUN TERMINAL: {evt.get('run_status')}"
  if kind == "max_wait_exceeded":
    return "watch recycled (no activity within recycle window)"
  if kind == "final_row":
    return (
      f"watch ended: draft={str(evt.get('draft_id') or '')[:8]} "
      f"reason={evt.get('exit_reason')} run_status={evt.get('terminal_run_status')}"
    )
  return None


def _tail_persona_log(stop: threading.Event) -> None:
  """Follow the newest _logs_persona_*.txt; emit high-signal lines."""
  current_path: Optional[str] = None
  handle = None
  while not stop.is_set():
    try:
      candidates = sorted(
        glob.glob(str(REPO_ROOT / "_logs_persona_*.txt")),
        key=os.path.getmtime,
        reverse=True,
      )
      newest = candidates[0] if candidates else None
      if newest != current_path:
        if handle:
          handle.close()
        current_path = newest
        handle = open(newest, "r", encoding="utf-8", errors="replace") if newest else None
        if handle:
          handle.seek(0, os.SEEK_END)
          _emit(f"log: following {os.path.basename(newest)}")
      if handle:
        for line in iter(handle.readline, ""):
          text = line.rstrip()
          if any(marker in text for marker in _LOG_MARKERS):
            _emit(f"log: {text[:240]}")
    except Exception as exc:  # noqa: BLE001 -- the tail must never kill the watcher
      _emit(f"log-tail error (continuing): {type(exc).__name__}: {exc}")
      time.sleep(10)
    stop.wait(3.0)
  if handle:
    handle.close()


def _active_recent_draft() -> str:
  """The draft to RE-ATTACH to: an in_progress draft touched within the
  last 10 minutes. Without this, a watch recycled mid-active-run (the
  monitor's max-wait is absolute, not activity-based — CW-003 lost
  observation 24 minutes in) spawns a successor that only watches drafts
  created after its own start and never re-finds the live one."""
  try:
    import sys as _sys
    _sys.path.insert(0, str(REPO_ROOT / "python"))
    _sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(REPO_ROOT / ".env", override=False)
    from intake_submission import get_mysql_connection  # type: ignore
    conn = get_mysql_connection()
    try:
      cur = conn.cursor()
      try:
        cur.execute(
          """
          SELECT draft_id FROM intake_consult_drafts
          WHERE status = 'in_progress'
            AND updated_at > NOW() - INTERVAL 10 MINUTE
          ORDER BY updated_at DESC LIMIT 1
          """
        )
        row = cur.fetchone()
        return str(row[0]) if row and row[0] else ""
      finally:
        cur.close()
    finally:
      conn.close()
  except Exception:
    return ""


def _finalize_vitals(stall_count: int) -> None:
  """Record the watched run's vitals summary (run_vitals_runs + events) and
  surface the one-line RUN VITALS summary. Best-effort: a finalizer failure
  must never stop the watch loop."""
  if not RESULT_PATH.exists():
    return  # watch ended before any draft appeared; nothing to record
  try:
    out = subprocess.run(
      [str(PYTHON), "-u", str(FINALIZER),
       "--result-path", str(RESULT_PATH),
       "--stalls", str(stall_count)],
      cwd=str(REPO_ROOT),
      capture_output=True,
      text=True,
      encoding="utf-8",
      errors="replace",
      timeout=120,
    )
    for line in (out.stdout or "").splitlines():
      if line.strip():
        _emit(line.strip())
    if out.returncode != 0:
      tail = (out.stderr or "").strip().splitlines()
      _emit(f"vitals-finalize failed rc={out.returncode}: {tail[-1] if tail else '?'}")
  except Exception as exc:  # noqa: BLE001 -- the watch loop must survive
    _emit(f"vitals-finalize error (continuing): {type(exc).__name__}: {exc}")


def main(argv) -> int:
  parser = argparse.ArgumentParser(description="Auto-sense the persona stack and observe runs.")
  parser.add_argument("--backend-port", type=int, default=5050)
  parser.add_argument("--frontend-port", type=int, default=5173)
  parser.add_argument("--stall-seconds", type=float, default=300.0)
  parser.add_argument("--poll-seconds", type=float, default=5.0)
  parser.add_argument(
    "--recycle-seconds", type=float, default=3600.0,
    help="Recycle an idle watch after this long so an abandoned intake does not hold the watcher.",
  )
  args = parser.parse_args(argv)

  _emit(
    f"persona watcher armed: waiting for backend :{args.backend_port} "
    f"+ frontend :{args.frontend_port}"
  )
  # Transcript catch-up for runs that ended while nothing was watching
  # (watcher down, machine died): capture is unconditional and DB-driven,
  # so anything the finalizer missed is written now.
  try:
    _bf = subprocess.run(
      [str(PYTHON), "-u", str(FINALIZER), "--backfill-hours", "48"],
      cwd=str(REPO_ROOT), capture_output=True, text=True,
      encoding="utf-8", errors="replace", timeout=180,
    )
    for _line in (_bf.stdout or "").splitlines():
      if _line.strip():
        _emit(_line.strip())
  except Exception as exc:  # noqa: BLE001
    _emit(f"transcript backfill error (continuing): {type(exc).__name__}: {exc}")
  stack_was_up = False
  tail_stop = threading.Event()
  tail_thread = threading.Thread(target=_tail_persona_log, args=(tail_stop,), daemon=True)
  tail_thread.start()

  try:
    while True:
      up = _stack_up(args.backend_port, args.frontend_port)
      if up and not stack_was_up:
        _emit("STACK UP -- backend + frontend both serving; observing for new drafts")
      if not up and stack_was_up:
        _emit("STACK DOWN -- pausing observation until both ports return")
      stack_was_up = up
      if not up:
        time.sleep(5.0)
        continue

      try:
        RESULT_PATH.unlink()  # stale result must not be re-finalized
      except OSError:
        pass
      stall_count = 0
      reattach = _active_recent_draft()
      if reattach:
        _emit(f"re-attaching to active draft {reattach[:8]}")
      proc = subprocess.Popen(
        [
          str(PYTHON), "-u", str(MONITOR),
          "--watch-only",
          *(["--draft-id", reattach] if reattach else []),
          "--stall-seconds", str(args.stall_seconds),
          "--poll-seconds", str(args.poll_seconds),
          "--max-wait-seconds", str(args.recycle_seconds),
          "--result-path", str(RESULT_PATH),
        ],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
      )
      for raw in iter(proc.stdout.readline, ""):
        stripped = raw.strip()
        if '"stall_detected"' in stripped:
          stall_count += 1
        compacted = _compact(stripped)
        if compacted:
          _emit(compacted)
        if not _stack_up(args.backend_port, args.frontend_port):
          proc.terminate()
          break
      proc.wait(timeout=30)
      _finalize_vitals(stall_count)
      time.sleep(2.0)
  finally:
    tail_stop.set()
  return 0


if __name__ == "__main__":
  raise SystemExit(main(sys.argv[1:]))
