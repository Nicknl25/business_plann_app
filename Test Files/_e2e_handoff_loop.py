"""END-TO-END LOOP HARNESS — drive the WHOLE handoff cycle in a throwaway
repo with stub agents, so loop bugs are found here instead of in front of
Nick one at a time.

Mini's _audit_handoff_watcher.py proves the SAFETY properties in isolation
(stop-on-green, DRIFT, cap, pause, refusals). This proves the loop actually
RUNS: seed -> launch -> flip -> launch -> green -> stop -> re-seed -> launch.
Three production bugs got past the isolated tests because nothing exercised
the sequence:
  1. consume_inbox fataled on `git add` of an absent PAUSE sentinel
  2. a seeded task inherited the previous turn's VERDICT: green and was
     force-stopped instantly — re-arm after the most common stop was
     structurally impossible
  3. a long-lived watcher kept running code that had been fixed on disk

Run: python "Test Files/_e2e_handoff_loop.py"
"""
from __future__ import annotations

import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parents[1]
WATCHER_SRC = HERE / "scripts" / "handoff_watch.py"
BRANCH = "intake-stable"
STEPS: list[tuple[str, bool, str]] = []


def sh(*args, cwd=None, check=True):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=check)


def step(name: str, ok: bool, detail: str = "") -> bool:
    STEPS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"        {detail}")
    return ok


# A stub agent: flips STATUS to the given target with the given verdict and
# commits — i.e. it honours the turn contract without needing a real model.
def flip_stub(target: str, verdict: str, sig: str = "none", summary: str = "stub") -> str:
    return (
        "import pathlib,subprocess,re;"
        "p=pathlib.Path('replay_gate/HANDOFF.md');"
        "t=p.read_text(encoding='utf-8');"
        "lines=t.splitlines();"
        f"lines[0]='STATUS: {target}';"
        "t='\\n'.join(lines);"
        "i=t.rfind('RESULT:');"
        f"t=(t[:i] if i>=0 else t)+'RESULT:\\n  AGENT: stub\\n  VERDICT: {verdict}\\n"
        f"  ERROR-SIGNATURE: {sig}\\n  EVIDENCE: none\\n  SUMMARY: {summary}\\n';"
        "p.write_text(t,encoding='utf-8');"
        "subprocess.run(['git','add','-A']);"
        "subprocess.run(['git','commit','-m','stub turn'])"
    )


def make_repo(handoff_text: str, agent_cmd) -> tuple[Path, Path]:
    root = Path(tempfile.mkdtemp(prefix="e2e_"))
    origin, local = root / "origin.git", root / "local"
    sh("git", "init", "--bare", "-b", BRANCH, str(origin))
    sh("git", "clone", str(origin), str(local))
    sh("git", "config", "user.email", "t@t", cwd=local)
    sh("git", "config", "user.name", "t", cwd=local)
    (local / "replay_gate").mkdir(parents=True, exist_ok=True)
    (local / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy(WATCHER_SRC, local / "scripts" / "handoff_watch.py")
    (local / "replay_gate" / "HANDOFF.md").write_text(handoff_text, encoding="utf-8")
    for who in ("VS", "MINI"):
        (local / "replay_gate" / f"HANDOFF_PROMPT_{who}.md").write_text(f"{who}\n", encoding="utf-8")
    (local / "replay_gate" / "handoff_config.json").write_text(json.dumps({
        "cap_round_trips": 8, "poll_seconds": 1, "default_turn_timeout_minutes": 180,
        "branch": BRANCH, "push_retries": 1, "heartbeat_seconds": 5,
        "agent_command": agent_cmd,
    }, indent=2), encoding="utf-8")
    sh("git", "add", "-A", cwd=local)
    sh("git", "commit", "-m", "seed", cwd=local)
    sh("git", "push", "-u", "origin", BRANCH, cwd=local)
    return root, local


def load_watcher(local: Path):
    sys.modules.pop("handoff_watch", None)
    spec = importlib.util.spec_from_file_location(
        "handoff_watch", str(local / "scripts" / "handoff_watch.py"))
    hw = importlib.util.module_from_spec(spec)
    sys.modules["handoff_watch"] = hw
    spec.loader.exec_module(hw)
    return hw


def cycle(hw, state):
    buf = io.StringIO()
    with redirect_stdout(buf):
        kept = hw.one_cycle(hw.load_config(), state)
    return kept, buf.getvalue()


def status_of(local: Path) -> str:
    return (local / "replay_gate" / "HANDOFF.md").read_text(
        encoding="utf-8").splitlines()[0].split(":", 1)[1].strip()


def main() -> int:
    # The realistic starting point: the loop is parked after a GREEN stop,
    # exactly where cycle 1 left it in production.
    start = (
        "STATUS: awaiting-Nick\nTURN: 4/16\nTASK:\n  (previous task)\n"
        "RESULT:\n  AGENT: mini\n  VERDICT: green\n  ERROR-SIGNATURE: none\n"
        "  EVIDENCE: prove7\n  SUMMARY: CLEAN TABLE 50/50, 0 DRIFT\n"
    )
    root, local = make_repo(start, ["python", "-c", flip_stub("awaiting-mini", "progress", "SIG-A")])
    hw = load_watcher(local)
    state = {"last_signature": {}, "last_ping": ""}
    hw.ping = lambda subject, body, st: st.__setitem__("last_ping", subject)

    kept, out = cycle(hw, state)
    step("parked at green: no launch, stays stopped",
         not kept and status_of(local) == "awaiting-Nick" and "LAUNCH" not in out,
         f"status={status_of(local)}")

    # Nick's plain-English instruction arrives.
    (local / "replay_gate" / "HANDOFF_INBOX.md").write_text(
        hw.INBOX_TEMPLATE + "freeze the golden input as a committed constant\n", encoding="utf-8")
    sh("git", "add", "-A", cwd=local)
    sh("git", "commit", "-m", "nick instruction", cwd=local)

    kept, out = cycle(hw, state)          # consume inbox (bug 1 lived here)
    seeded = (local / "replay_gate" / "HANDOFF.md").read_text(encoding="utf-8")
    step("inbox consumed: task seeded, status flipped, prior green superseded",
         status_of(local) == "awaiting-VS"
         and "freeze the golden input" in seeded
         and "VERDICT: progress" in seeded.split("RESULT:")[-1],
         f"status={status_of(local)}")

    kept, out = cycle(hw, state)          # launch VS (bug 2 blocked this)
    step("VS turn launched and flipped to mini",
         "LAUNCH VS" in out and status_of(local) == "awaiting-mini",
         f"status={status_of(local)}")

    # mini's turn returns progress with a DIFFERENT signature (converging).
    (local / "replay_gate" / "handoff_config.json").write_text(json.dumps({
        "cap_round_trips": 8, "poll_seconds": 1, "default_turn_timeout_minutes": 180,
        "branch": BRANCH, "push_retries": 1, "heartbeat_seconds": 5,
        "agent_command": ["python", "-c", flip_stub("awaiting-VS", "progress", "SIG-B")],
    }, indent=2), encoding="utf-8")
    sh("git", "add", "-A", cwd=local); sh("git", "commit", "-m", "cfg", cwd=local)
    kept, out = cycle(hw, state)
    step("mini turn launched and handed back to VS",
         "LAUNCH mini" in out and status_of(local) == "awaiting-VS",
         f"status={status_of(local)}")

    # VS finishes GREEN -> the loop must stop and ping, and never launch again.
    (local / "replay_gate" / "handoff_config.json").write_text(json.dumps({
        "cap_round_trips": 8, "poll_seconds": 1, "default_turn_timeout_minutes": 180,
        "branch": BRANCH, "push_retries": 1, "heartbeat_seconds": 5,
        "agent_command": ["python", "-c", flip_stub("awaiting-mini", "green", "none",
                                                    "clean table 50/50 - 0 DRIFT")],
    }, indent=2), encoding="utf-8")
    sh("git", "add", "-A", cwd=local); sh("git", "commit", "-m", "cfg", cwd=local)
    kept, out = cycle(hw, state)
    kept2, out2 = cycle(hw, state)
    step("green forces the stop even though the agent pointed at mini",
         status_of(local) == "awaiting-Nick" and not kept2 and "LAUNCH" not in out2,
         f"status={status_of(local)} ping={state.get('last_ping')!r}")
    step("green ping is 'confirm', never URGENT drift (prose must not alarm)",
         "green" in str(state.get("last_ping", "")).lower()
         and "URGENT" not in str(state.get("last_ping", "")),
         f"ping={state.get('last_ping')!r}")

    # RE-ARM after green — the bug that made the loop unusable in production.
    (local / "replay_gate" / "HANDOFF_INBOX.md").write_text(
        hw.INBOX_TEMPLATE + "go again\n", encoding="utf-8")
    sh("git", "add", "-A", cwd=local); sh("git", "commit", "-m", "nick again", cwd=local)
    cycle(hw, state)                       # consume
    kept, out = cycle(hw, state)           # must LAUNCH, not re-stop
    step("RE-ARM AFTER GREEN: seeded and launched again",
         "LAUNCH" in out, f"status={status_of(local)} out={out.strip().splitlines()[-1] if out.strip() else ''}")

    # Everything the watcher wrote must be on origin (offsite per turn).
    local_head = sh("git", "rev-parse", "HEAD", cwd=local).stdout.strip()
    origin_head = sh("git", "rev-parse", f"origin/{BRANCH}", cwd=local).stdout.strip()
    step("every watcher write reached origin", local_head == origin_head,
         f"local={local_head[:8]} origin={origin_head[:8]}")

    shutil.rmtree(root, ignore_errors=True)
    bad = [s for s in STEPS if not s[1]]
    print("\n" + "=" * 66)
    print(f"{len(STEPS) - len(bad)}/{len(STEPS)} loop steps pass")
    for name, _ok, detail in bad:
        print(f"  FAIL {name}: {detail}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
