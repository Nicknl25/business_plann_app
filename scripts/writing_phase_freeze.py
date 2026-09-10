"""Flip or read the writing-phase trigger switch - one line out.

Usage:
  python scripts/writing_phase_freeze.py status
  python scripts/writing_phase_freeze.py off  [--note "why"]   # FREEZE: no plan is written
  python scripts/writing_phase_freeze.py on   [--note "why"]   # lift the freeze

The switch is read by the system-run success tail at trigger time, so a
flip takes effect on the next run without a :5050 restart. Exit code:
0 = trigger ON, 3 = FROZEN (so a caller can branch on the state).
"""
from __future__ import annotations

import argparse
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO, os.path.join(REPO, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from writing_phase_v2 import trigger_switch as TS  # noqa: E402


def main(argv=None) -> int:
  ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  ap.add_argument("action", choices=("on", "off", "status"))
  ap.add_argument("--note", default="", help="why (recorded in the flag file)")
  ap.add_argument("--by", default="", help="who (default: the OS user)")
  ap.add_argument("--path", default="", help="flag file override (tests only)")
  args = ap.parse_args(argv)
  path = args.path or None
  if args.action == "status":
    state = TS.read_state(path)
  else:
    state = TS.set_state(args.action == "on", by=args.by, note=args.note, path=path)
  print(TS.one_line(state))
  return 3 if state["frozen"] else 0


if __name__ == "__main__":
  sys.exit(main())
