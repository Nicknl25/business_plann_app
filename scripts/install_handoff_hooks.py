"""Install a pre-commit hook that REFUSES commits while a handoff agent turn
is in flight.

Why: during supervised cycle 1 the interactive VS session committed while the
headless mini turn had files staged, so mini's gate work landed inside an
unrelated commit ("history conflated", mini's words). Two agents writing one
git index is a live hazard for this loop, and the watcher's own hands-off rule
cannot bind a human-driven session — a hook can.

The hook blocks ONLY while _handoff/agent.pid names a live process, and it
tells the caller what to wait for. Emergency override: HANDOFF_ALLOW_COMMIT=1.
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / ".git" / "hooks" / "pre-commit"

BODY = r'''#!/bin/sh
# handoff-loop guard (scripts/install_handoff_hooks.py) — refuse to write the
# index while a headless agent turn owns the tree.
if [ "$HANDOFF_ALLOW_COMMIT" = "1" ]; then exit 0; fi
PIDFILE="$(git rev-parse --show-toplevel)/_handoff/agent.pid"
[ -f "$PIDFILE" ] || exit 0
PID="$(tr -d '[:space:]' < "$PIDFILE")"
[ -n "$PID" ] || exit 0
if tasklist //FI "PID eq $PID" 2>/dev/null | grep -q "$PID"; then
  echo "COMMIT BLOCKED: handoff agent turn in flight (pid $PID)." >&2
  echo "  Two sessions writing one index conflates history - wait for the" >&2
  echo "  turn to finish (watch _handoff/logs/watcher.log), or set" >&2
  echo "  HANDOFF_ALLOW_COMMIT=1 if you are certain." >&2
  exit 1
fi
exit 0
'''


def main() -> int:
    HOOK.parent.mkdir(parents=True, exist_ok=True)
    HOOK.write_text(BODY, encoding="utf-8", newline="\n")
    HOOK.chmod(HOOK.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f"installed: {HOOK}")
    probe = subprocess.run(["sh", str(HOOK)], cwd=str(REPO), capture_output=True, text=True)
    print(f"hook self-test exit={probe.returncode} (0 = no agent in flight)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
