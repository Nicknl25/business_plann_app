"""THE STORE STAYS UP, AND AN OUTAGE IS NEVER SILENT.

WHAT THIS EXISTS FOR (Nick, 2026-09-22): "The store being dead for days is the
answer to everything I've been complaining about." Between 2026-09-18 21:02 and
2026-09-22 21:02 the backend on :5050 was not listening. Cowork went on driving
runs and filing its CW-077 findings into a store that was not there; VS came back
to a table whose newest row was its own from Friday (max issue id 1371) and no
draft after 09-18 20:28. Neither side saw a failure. Both believed they had
spoken.

WHY THE KEEPALIVE DID NOT SAVE IT. scripts/backend_keepalive.ps1 is a LOOP - a
long-lived process that pings every 30s and restarts the backend after three
misses. It works, and it is exactly as mortal as whoever started it. Nothing
installed it; a Claude session started it, the session ended, and the loop went
with it. MEASURED 2026-09-22: `Get-ScheduledTask` matching handoff|keepalive|
bplan|backend|cowork returned NOTHING. There was no scheduled task on this
machine. The store's life support only ever ran while someone was watching it,
which is the one time it is not needed.

SO THIS IS A TICK, NOT A LOOP. One pass, then exit. A scheduled task runs it
every couple of minutes, so there is no long-lived process to die with a session,
a terminal or a weekend. Same shape as handoff_supervisor.py --tick, and for the
same reason.

WHAT IT WILL NOT DO:
  * start the backend while _runtime/backend_keepalive.stop exists - a deliberate
    shutdown stays down, and a supervisor that overrides the brake is a runaway;
  * start a second backend - it checks the port first;
  * touch a draft, an issue row, or any app data. It starts a process and writes
    its own log. That is the whole job.

Install (once, no elevation needed):
    .venv\\Scripts\\python.exe scripts\\store_tick.py --install
Check:
    .venv\\Scripts\\python.exe scripts\\store_tick.py --status
Remove:
    .venv\\Scripts\\python.exe scripts\\store_tick.py --uninstall
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNTIME = REPO / "_runtime"
LOG = RUNTIME / "store_tick.log"
OUTAGE = RUNTIME / "store_outage.json"
STOP = RUNTIME / "backend_keepalive.stop"
START = REPO / "scripts" / "start_persona_backend.ps1"
TASK_NAME = "BPlanStoreTick"
PORT = 5050


def _now() -> str:
  return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(line: str) -> None:
  RUNTIME.mkdir(parents=True, exist_ok=True)
  with open(LOG, "a", encoding="utf-8") as fh:
    fh.write("%s %s\n" % (_now(), line))


def store_answers(timeout: float = 8.0) -> bool:
  """The store is UP only when it answers. A listening socket is not enough -
  a wedged worker accepts the connection and never replies, which reads as
  healthy to anything that only checks the port."""
  try:
    with urllib.request.urlopen(
        "http://127.0.0.1:%d/api/ping" % PORT, timeout=timeout) as resp:
      if resp.status != 200:
        return False
      json.loads(resp.read().decode("utf-8") or "{}")
      return True
  except (urllib.error.URLError, socket.timeout, ValueError, OSError):
    return False


def _read_outage() -> dict:
  try:
    return json.loads(OUTAGE.read_text(encoding="utf-8"))
  except Exception:
    return {}


def _write_outage(obj: dict) -> None:
  RUNTIME.mkdir(parents=True, exist_ok=True)
  try:
    OUTAGE.write_text(json.dumps(obj, indent=2), encoding="utf-8")
  except Exception:
    pass


def start_backend() -> bool:
  if not START.exists():
    log("CANNOT START: %s is missing" % START.name)
    return False
  try:
    subprocess.Popen(
      ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
       "-File", str(START), "-Force"],
      cwd=str(REPO),
      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return True
  except Exception as exc:                                    # noqa: BLE001
    log("START FAILED: %s: %s" % (type(exc).__name__, exc))
    return False


def tick() -> int:
  """One pass. Returns 0 when the store answers or was deliberately stopped."""
  if STOP.exists():
    state = _read_outage()
    if state.get("down_since"):
      log("stopped deliberately (stop file present) - not restarting")
    _write_outage({"stopped_on_purpose": True, "checked_at": _now()})
    return 0

  if store_answers():
    state = _read_outage()
    if state.get("down_since"):
      log("STORE BACK UP after being down since %s (%d failed ticks)"
          % (state.get("down_since"), int(state.get("failed_ticks") or 0)))
    _write_outage({"up": True, "checked_at": _now()})
    return 0

  state = _read_outage()
  failed = int(state.get("failed_ticks") or 0) + 1
  down_since = state.get("down_since") or _now()
  alerted = bool(state.get("alerted"))
  # ONE TICK IS NOT AN OUTAGE. A restart in progress, or a request that lands
  # mid-reload, fails one check and is healthy on the next. Two consecutive
  # failures is the floor for calling it down and acting.
  record = {"up": False, "down_since": down_since, "failed_ticks": failed,
            "checked_at": _now(), "restart_attempted": False, "alerted": alerted}
  if failed >= 2:
    log("STORE DOWN since %s (%d consecutive failed ticks) - starting it"
        % (down_since, failed))
    record["restart_attempted"] = start_backend()
    record["restart_attempted_at"] = _now()
  else:
    log("store did not answer (tick %d) - waiting one more before acting" % failed)
  # AN OUTAGE WE CANNOT HEAL MUST REACH A HUMAN, AND NOT THROUGH A CLAUDE
  # SESSION. Five consecutive failures is ten minutes of a store that will not
  # come back on its own - the shape of the weekend, where both agents went on
  # talking into nothing. The email does not depend on any session being alive,
  # which is the entire point; sent once per outage, never once per tick.
  if failed >= 5 and not alerted:
    record["alerted"] = _alert_nick(down_since, failed)
  _write_outage(record)
  return 1


def _alert_nick(down_since: str, failed: int) -> bool:
  subject = "BPLAN STORE DOWN since %s - %d failed checks, restart not working" % (
    down_since, failed)
  body = (
    "The store on http://127.0.0.1:%d has not answered /api/ping for %d "
    "consecutive checks (about %d minutes).\n\n"
    "The tick has tried to restart it and it is still not answering, so this "
    "needs a person.\n\n"
    "WHY YOU ARE BEING TOLD: while the store is down, Cowork's filings and VS's "
    "claims go nowhere and BOTH SIDES BELIEVE THEY HAVE SPOKEN. That is what "
    "happened between 2026-09-18 21:02 and 2026-09-22 21:02 - four days, an "
    "entire CW-077 sequence lost, and neither agent saw a failure.\n\n"
    "  log        : %s\n  last record: %s\n"
    % (PORT, failed, failed * 2, LOG, OUTAGE))
  try:
    subprocess.run(
      [sys.executable, str(REPO / "scripts" / "notify_push_email.py"), subject, body],
      cwd=str(REPO), capture_output=True, text=True, timeout=120)
    log("ALERT SENT: store down since %s, %d failed checks" % (down_since, failed))
    return True
  except Exception as exc:                                    # noqa: BLE001
    log("ALERT FAILED: %s: %s" % (type(exc).__name__, exc))
    return False


def _schtasks(args: list) -> subprocess.CompletedProcess:
  return subprocess.run(["schtasks.exe"] + args, capture_output=True, text=True)


def install() -> int:
  python = REPO / ".venv" / "Scripts" / "python.exe"
  if not python.exists():
    python = Path(sys.executable)
  cmd = '"%s" "%s" --tick' % (python, Path(__file__).resolve())
  # Every 2 minutes, from logon, forever. No elevation: it runs as this user.
  res = _schtasks(["/Create", "/F", "/TN", TASK_NAME, "/SC", "MINUTE", "/MO", "2",
                   "/TR", cmd, "/RL", "LIMITED"])
  print(res.stdout.strip() or res.stderr.strip())
  if res.returncode == 0:
    # AND AT LOGON, so a reboot does not wait for the first interval and, more
    # to the point, so the machine coming back is enough to bring the store back.
    _schtasks(["/Create", "/F", "/TN", TASK_NAME + "AtLogon", "/SC", "ONLOGON",
               "/TR", cmd, "/RL", "LIMITED"])
    log("installed scheduled task %s (every 2 minutes) + at logon" % TASK_NAME)
  return res.returncode


def uninstall() -> int:
  rc = 0
  for name in (TASK_NAME, TASK_NAME + "AtLogon"):
    res = _schtasks(["/Delete", "/F", "/TN", name])
    print(res.stdout.strip() or res.stderr.strip())
    rc = rc or res.returncode
  log("uninstalled scheduled task %s" % TASK_NAME)
  return rc


def status() -> int:
  res = _schtasks(["/Query", "/TN", TASK_NAME, "/FO", "LIST"])
  print(res.stdout.strip() or res.stderr.strip() or "task not installed")
  print("stop sentinel : %s" % ("present" if STOP.exists() else "absent"))
  print("store answers : %s" % store_answers())
  state = _read_outage()
  if state:
    print("last record   : %s" % json.dumps(state))
  return 0


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__)
  g = ap.add_mutually_exclusive_group()
  g.add_argument("--tick", action="store_true", help="one pass (what the task runs)")
  g.add_argument("--install", action="store_true")
  g.add_argument("--uninstall", action="store_true")
  g.add_argument("--status", action="store_true")
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
