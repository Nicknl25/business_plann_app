"""Install .git/hooks/pre-push -> scripts/prepush_preflight.py (Nick 2026-09-11).

Git hooks are not versioned, so the hook is a two-line shim and the logic
lives in the tracked script. Re-run this after a fresh clone.
"""
from __future__ import annotations

import stat
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / ".git" / "hooks" / "pre-push"
BODY = """#!/bin/sh
# preflight on every push touching post-intake (scripts/install_preflight_hook.py)
exec "$(git rev-parse --show-toplevel)/.venv/Scripts/python.exe" -X utf8 \\
  "$(git rev-parse --show-toplevel)/scripts/prepush_preflight.py" "$@"
"""


def main() -> int:
    HOOK.parent.mkdir(parents=True, exist_ok=True)
    HOOK.write_text(BODY, encoding="utf-8", newline="\n")
    HOOK.chmod(HOOK.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f"installed: {HOOK}")
    # Probe: an empty ref list must pass straight through.
    probe = subprocess.run(["sh", str(HOOK)], cwd=str(REPO), input="", capture_output=True, text=True)
    print(f"probe (no refs): exit {probe.returncode}")
    return probe.returncode


if __name__ == "__main__":
    raise SystemExit(main())
