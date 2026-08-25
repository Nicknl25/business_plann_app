"""Keep the VS<->mini handoff watcher ALIVE without Nick.

The watcher (scripts/handoff_watch.py) is the doorbell: it reads the STATUS
line of replay_gate/HANDOFF.md, seeds tasks from the plain-English inbox, and
launches exactly one headless agent turn at a time. It works. What it never
had is anything that STARTS it.

It ran until 2026-08-17 21:41:59, stopped with the nightly shutdown, and then
nobody noticed - the loop looked "broken" when in fact nothing was running it,
and every handoff since has been shuttled by hand, which is the exact thing the
watcher exists to prevent. The SessionStart hook Nick remembers arms the
PERSONA run watcher (scripts/persona_session_watch.py), a different script for
a different job; the handoff watcher had no auto-arm at all.

This is that auto-arm, and it deliberately lives OUTSIDE any Claude session: a
scheduled task runs it every few minutes and starts the watcher if the watcher
is not alive. Session ends, machine reboots, watcher crashes - the next tick
brings it back.

What it will NOT do, because these are the brakes Nick approved:
  * start anything while replay_gate/HANDOFF_PAUSE exists - the PAUSE brake
    means stopped, and a supervisor that overrides the brake is a runaway;
  * start a second watcher - the watcher is a hard singleton on its own pid
    file, and this checks first anyway;
  * touch STATUS, the inbox, or any agent turn. It starts a process. That is
    the whole job.

Install (once, no elevation needed):
    python scripts/handoff_supervisor.py --install
Check:
    python scripts/handoff_supervisor.py --status
Remove:
    python scripts/handoff_supervisor.py --uninstall
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WATCHER = REPO / "scripts" / "handoff_watch.py"
PAUSE_SENTINEL = REPO / "replay_gate" / "HANDOFF_PAUSE"
STATE_DIR = REPO / "_handoff"
LOG_DIR = STATE_DIR / "logs"
WATCHER_PID = STATE_DIR / "watcher.pid"
SUPERVISOR_LOG = LOG_DIR / "supervisor.log"
WATCHER_STDOUT = LOG_DIR / "watcher_stdout.log"
TASK_NAME = "BPA_HandoffWatcher"
#: Every 5 minutes: fast enough that a crash costs one poll, cheap enough that
#: the check itself is free. The watcher's own poll is 5s once it is up.
INTERVAL_MINUTES = 5


#: Shell-outs never get a console window (the supervisor may itself run under
#: pythonw, where every child console would flash on the desktop).
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if os.name == "nt" else 0


def python_exe() -> str:
    """pythonw so the scheduled task never flashes a console at Nick."""
    venv = REPO / ".venv" / "Scripts" / "pythonw.exe"
    return str(venv) if venv.exists() else sys.executable


def log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with open(SUPERVISOR_LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def watcher_alive() -> bool:
    """FAIL CLOSED, the same rule the watcher uses on its own pid file: if we
    cannot tell, assume it is alive rather than race a second one into life."""
    if not WATCHER_PID.exists():
        return False
    try:
        pid = int(WATCHER_PID.read_text().strip())
    except Exception:
        return True
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                             capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW).stdout
    except Exception:
        return True
    return str(pid) in out


def start_watcher() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # DETACHED. The supervisor is a scheduled task that exits in a second; the
    # watcher must outlive it, so it gets its own process group and no console.
    flags = 0
    if os.name == "nt":
        flags = (subprocess.CREATE_NEW_PROCESS_GROUP
                 | getattr(subprocess, "DETACHED_PROCESS", 0x00000008))
    with open(WATCHER_STDOUT, "a", encoding="utf-8") as out:
        child = subprocess.Popen(
            [python_exe(), "-u", str(WATCHER)],
            cwd=str(REPO), stdout=out, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, creationflags=flags)
    log(f"watcher STARTED pid={child.pid} (log: {WATCHER_STDOUT})")
    return child.pid


def tick() -> int:
    if PAUSE_SENTINEL.exists():
        log("PAUSE sentinel present - standing down (the brake means stopped)")
        return 0
    if watcher_alive():
        return 0
    log("watcher not running - starting it")
    start_watcher()
    return 0


def install() -> int:
    cmd = f'"{python_exe()}" "{Path(__file__).resolve()}" --tick'
    # /F overwrites, so --install is idempotent and safe to re-run.
    create = subprocess.run(
        ["schtasks", "/Create", "/TN", TASK_NAME, "/TR", cmd, "/SC", "MINUTE",
         "/MO", str(INTERVAL_MINUTES), "/F"],
        capture_output=True, text=True, creationflags=NO_WINDOW)
    print((create.stdout or create.stderr).strip())
    if create.returncode != 0:
        return create.returncode
    subprocess.run(["schtasks", "/Run", "/TN", TASK_NAME],
                   capture_output=True, text=True, creationflags=NO_WINDOW)
    log(f"scheduled task {TASK_NAME} installed, every {INTERVAL_MINUTES} min")
    return 0


def uninstall() -> int:
    r = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    print((r.stdout or r.stderr).strip())
    return r.returncode


def status() -> int:
    r = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    print((r.stdout or r.stderr).strip())
    brake = "PRESENT - watcher will not start" if PAUSE_SENTINEL.exists() else "absent"
    print(f"\nPAUSE sentinel : {brake}")
    print(f"watcher alive  : {watcher_alive()}")
    if WATCHER_PID.exists():
        print(f"watcher pid    : {WATCHER_PID.read_text().strip()}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--tick", action="store_true", help="one check (what the task runs)")
    args = ap.parse_args()
    if args.install:
        return install()
    if args.uninstall:
        return uninstall()
    if args.status:
        return status()
    return tick()


if __name__ == "__main__":
    raise SystemExit(main())
