"""Emit a TURN PLAN — Nick's standing rule (2026-08-14): every turn
DECLARES its plan up front, visibly, then PROCEEDS. Nobody waits.

Usage (the agent's FIRST action of every turn):
  python scripts/handoff_turn_plan.py <agent> <plan-file-or-text>

The plan is the required four-line shape (composed by the agent):
  TASK: ...
  BLAST-RADIUS: localized | system-touching (+ why)
  LOADING: <exact files/sections being read>
  VERIFY: canary skip|run | legs <which+count> | full prove y/n

Delivery (same channels as the flip pings): watcher log + email +
desktop alert. This is a NOTIFICATION, not a gate — the script always
exits 0 so a delivery failure can never stall the turn; failures are
printed as warnings only. The end-of-turn RESULT confirms
declared-vs-actual, and mini audits the match.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG_DIR = REPO / "_handoff" / "logs"


def _log(agent: str, plan: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    block = "\n".join(f"{stamp} TURN PLAN [{agent}] {ln}" for ln in plan.splitlines() if ln.strip())
    with open(LOG_DIR / "watcher.log", "a", encoding="utf-8") as fh:
        fh.write(block + "\n")


def _email(agent: str, plan: str) -> None:
    sys.path.insert(0, str(REPO / "scripts"))
    import notify_push_email
    stamp = time.strftime("%Y-%m-%d %H:%M")
    body = (f"TURN PLAN — {agent} — {stamp}\n{plan}\n\n"
            "Declared, not asked: the turn is already running. Reply in "
            "plain English only if you want to intervene.")
    rc = notify_push_email.main(["notify_push_email.py", f"TURN PLAN [{agent}]", body])
    if rc != 0:
        print("warning: turn-plan email failed (turn continues)", file=sys.stderr)


def _desktop(agent: str, plan: str) -> None:
    # Fire and forget, mirrors handoff_watch.desktop_alert.
    first = next((ln for ln in plan.splitlines() if ln.strip()), "")
    text = f"TURN PLAN [{agent}] {first}"[:180].replace('"', "'")
    try:
        subprocess.Popen(["msg", "*", "/TIME:0", text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: handoff_turn_plan.py <agent> <plan-file-or-text>", file=sys.stderr)
        return 0  # never block a turn, even on misuse — the RESULT audit catches it
    agent = argv[1]
    raw = argv[2]
    p = Path(raw)
    plan = p.read_text(encoding="utf-8") if p.is_file() else raw
    for step in (_log, _email, _desktop):
        try:
            step(agent, plan)
        except Exception as exc:
            print(f"warning: {step.__name__} failed ({type(exc).__name__}: {exc}) — turn continues",
                  file=sys.stderr)
    print("turn plan emitted")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
