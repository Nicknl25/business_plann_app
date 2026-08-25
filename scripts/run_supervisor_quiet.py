"""Run the post-intake supervisor WITHOUT a console window.

The scheduled task `BusinessPlanApp-Supervisor` fires every five minutes. It
was registered against `python.exe`, and a console python launched by Task
Scheduler flashes a terminal on the desktop every single tick - the "screen
that keeps flashing" Nick saw on 2026-08-25. `pythonw.exe` has no console,
but `run_supervisor.py` reports what it did (reaped / rerun_done /
dead_letter ...) on stdout, which pythonw discards.

So: this launcher is what the task runs under pythonw. It sends stdout and
stderr to `_logs/supervisor.log` (append, one timestamped line per event) and
hands off to `run_supervisor.main` unchanged. The supervisor's own record
in the `supervisor_actions` table is unaffected; this only keeps the console
output that would otherwise be lost, and keeps the desktop quiet.
"""
from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG_DIR = REPO / "_logs"
LOG_FILE = LOG_DIR / "supervisor.log"


class _Stamped(io.TextIOBase):
  """Line-buffered file sink that prefixes each line with a timestamp."""

  def __init__(self, fh):
    self._fh = fh
    self._at_line_start = True

  def write(self, s):  # noqa: D401 - io protocol
    for chunk in s.splitlines(True):
      if self._at_line_start and chunk.strip():
        self._fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + chunk)
      else:
        self._fh.write(chunk)
      self._at_line_start = chunk.endswith("\n")
    self._fh.flush()
    return len(s)

  def flush(self):
    self._fh.flush()


def main() -> int:
  LOG_DIR.mkdir(parents=True, exist_ok=True)
  fh = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
  sink = _Stamped(fh)
  sys.stdout = sink
  sys.stderr = sink
  os.chdir(REPO)
  # One line per tick, BEFORE anything can fail, so the log proves the task
  # ran even when the supervisor finds nothing to reap (it prints only on
  # events).
  print("supervisor_quiet tick exe=" + sys.executable + " argv=" + " ".join(sys.argv[1:]), flush=True)
  sys.path.insert(0, str(REPO / "scripts"))
  import run_supervisor  # noqa: E402

  try:
    return int(run_supervisor.main(sys.argv[1:]) or 0)
  except SystemExit as exc:  # run_supervisor may raise its own exit
    return int(exc.code or 0)
  except Exception as exc:  # never a dialog, never a window - log and exit
    print(f"supervisor_quiet_unhandled: {type(exc).__name__}: {exc}", flush=True)
    return 1
  finally:
    # Hand the interpreter its real streams back BEFORE closing the log, or
    # Python's exit-time flush hits a closed file and reports exit 120.
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
    fh.flush()
    fh.close()


if __name__ == "__main__":
  raise SystemExit(main())
