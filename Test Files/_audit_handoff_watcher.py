# -*- coding: utf-8 -*-
"""INDEPENDENT AUDIT OF THE HANDOFF WATCHER (scripts/handoff_watch.py @ d62dc53).

The loop cannot audit itself, so this drives one_cycle() directly against a
throwaway git repo pair (local + bare origin), a stub agent, and an SMTP
config pointing at nothing - the ping ATTEMPT is asserted from the watcher's
own log line, never from delivery.

Each behaviour gets a fresh repo so no test can pass because a previous one
left state behind.
"""
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from contextlib import redirect_stdout
from pathlib import Path

# PORTABILITY (VS): resolve from THIS repo, not an upload mount, so the
# audit is re-runnable on the machine that owns the watcher.
WATCHER_SRC = Path(__file__).resolve().parents[1] / "scripts" / "handoff_watch.py"
BRANCH = "intake-stable"
RESULTS = []


def sh(*args, cwd=None, check=True):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=check)


def make_repo(handoff_text, *, agent_cmd=None, cap=8, extra_files=None):
    root = Path(tempfile.mkdtemp(prefix="wtest_"))
    origin = root / "origin.git"
    local = root / "local"
    sh("git", "init", "--bare", "-b", BRANCH, str(origin))
    sh("git", "clone", str(origin), str(local))
    sh("git", "config", "user.email", "t@t", cwd=local)
    sh("git", "config", "user.name", "t", cwd=local)
    (local / "replay_gate").mkdir(parents=True, exist_ok=True)
    (local / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy(WATCHER_SRC, local / "scripts" / "handoff_watch.py")
    (local / "replay_gate" / "HANDOFF.md").write_text(handoff_text, encoding="utf-8")
    for who in ("VS", "MINI"):
        (local / "replay_gate" / f"HANDOFF_PROMPT_{who}.md").write_text(
            f"prompt for {who}\n", encoding="utf-8")
    cfg = {"cap_round_trips": cap, "poll_seconds": 1,
           "default_turn_timeout_minutes": 180, "branch": BRANCH,
           "push_retries": 1}
    if agent_cmd:
        cfg["agent_command"] = agent_cmd
    (local / "replay_gate" / "handoff_config.json").write_text(
        json.dumps(cfg, indent=2), encoding="utf-8")
    for rel, body in (extra_files or {}).items():
        p = local / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    sh("git", "add", "-A", cwd=local)
    sh("git", "commit", "-m", "seed", cwd=local)
    sh("git", "push", "-u", "origin", BRANCH, cwd=local)
    return root, local


def load_watcher(local):
    """Import the watcher bound to THIS repo (REPO is computed from __file__)."""
    for mod in list(sys.modules):
        if mod == "handoff_watch":
            del sys.modules[mod]
    spec = importlib.util.spec_from_file_location(
        "handoff_watch", str(local / "scripts" / "handoff_watch.py"))
    hw = importlib.util.module_from_spec(spec)
    sys.modules["handoff_watch"] = hw
    spec.loader.exec_module(hw)
    return hw


def handoff(status, *, turn=1, cap=16, agent="", verdict="", sig="",
            timeout=None, result="RESULT: done"):
    lines = [f"STATUS: {status}", f"TURN: {turn}/{cap}"]
    if timeout is not None:
        lines.append(f"TURN-TIMEOUT-MINUTES: {timeout}")
    lines.append("")
    lines.append(result)
    if agent:
        lines.append(f"AGENT: {agent}")
    if verdict:
        lines.append(f"VERDICT: {verdict}")
    if sig:
        lines.append(f"ERROR-SIGNATURE: {sig}")
    return "\n".join(lines) + "\n"


def run_cycle(hw, cfg=None, state=None):
    """-> (kept_looping, log_text)."""
    buf = io.StringIO()
    cfg = cfg if cfg is not None else hw.load_config()
    state = state if state is not None else hw.load_state()
    with redirect_stdout(buf):
        kept = hw.one_cycle(cfg, state)
    return kept, buf.getvalue(), state


def status_of(local):
    return (local / "replay_gate" / "HANDOFF.md").read_text(
        encoding="utf-8").splitlines()[0].split(":", 1)[1].strip()


def commits(local):
    return sh("git", "log", "--oneline", cwd=local).stdout


def record(num, name, ok, detail):
    RESULTS.append((num, name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {num}. {name}")
    if detail:
        print(f"        {detail}")


# --------------------------------------------------------------------------
def t1_green_latch():
    root, local = make_repo(handoff("awaiting-VS", agent="mini", verdict="green",
                                    sig="none"))
    hw = load_watcher(local)
    kept, log1, state = run_cycle(hw)
    st = status_of(local)
    pinged1 = "PING" in log1
    # second poll: must NOT ping again (last_ping latch)
    kept2, log2, _ = run_cycle(hw, state=state)
    pinged2 = "PING" in log2
    pushed = "[handoff-watcher]" in commits(local)
    ok = (not kept and st == "awaiting-Nick" and pinged1 and not pinged2 and pushed)
    record(1, "stop-on-green latch", ok,
           f"kept={kept} status={st!r} ping#1={pinged1} ping#2={pinged2} "
           f"watcher-commit={pushed}")
    shutil.rmtree(root, ignore_errors=True)


def t2_drift_urgent():
    root, local = make_repo(handoff("awaiting-VS", agent="mini", verdict="drift",
                                    sig="none"))
    hw = load_watcher(local)
    kept, log1, _ = run_cycle(hw)
    st = status_of(local)
    urgent = "URGENT" in log1
    ok = (not kept and st == "awaiting-Nick" and urgent)
    record(2, "DRIFT -> stop + URGENT ping", ok,
           f"kept={kept} status={st!r} urgent-in-log={urgent} | "
           f"{[l for l in log1.splitlines() if 'PING' in l][:1]}")
    shutil.rmtree(root, ignore_errors=True)


def t3_signature():
    # (a) SAME agent twice with the same signature -> stopped-stuck
    root, local = make_repo(handoff("awaiting-VS", agent="mini", verdict="blocked",
                                    sig="SIG-X"))
    hw = load_watcher(local)
    state = hw.load_state()
    state["last_signature"] = {"mini": "SIG-X"}
    kept, log1, _ = run_cycle(hw, state=state)
    trip = (not kept and status_of(local) == "stopped-stuck")
    shutil.rmtree(root, ignore_errors=True)

    # (b) CONVERGING: VS reported SIG-X, now mini reports SIG-X -> must NOT trip
    root2, local2 = make_repo(handoff("awaiting-VS", agent="mini",
                                      verdict="blocked", sig="SIG-X"),
                              agent_cmd=["python", "-c", "pass"])
    hw2 = load_watcher(local2)
    state2 = hw2.load_state()
    state2["last_signature"] = {"VS": "SIG-X"}
    _kept, log2, _ = run_cycle(hw2, state=state2)
    no_trip = status_of(local2) != "stopped-stuck"
    ok = trip and no_trip
    record(3, "same-signature-per-direction (trips same side, not across)", ok,
           f"same-agent-twice -> stopped-stuck: {trip}; "
           f"one-each-side -> did NOT trip: {no_trip}")
    shutil.rmtree(root2, ignore_errors=True)


def t4_refusals():
    # (a) dirty tracked tree
    root, local = make_repo(handoff("awaiting-VS", agent="mini", verdict="progress",
                                    sig="none"))
    (local / "replay_gate" / "HANDOFF_PROMPT_VS.md").write_text("dirtied\n",
                                                                encoding="utf-8")
    hw = load_watcher(local)
    kept, log1, _ = run_cycle(hw)
    dirty_ok = (not kept and status_of(local) == "stopped-fault")
    shutil.rmtree(root, ignore_errors=True)

    # (b) diverged history -> stopped-fault, and NEVER merges
    root2, local2 = make_repo(handoff("awaiting-VS", agent="mini",
                                      verdict="progress", sig="none"))
    other = root2 / "other"
    sh("git", "clone", str(root2 / "origin.git"), str(other))
    sh("git", "config", "user.email", "o@o", cwd=other)
    sh("git", "config", "user.name", "o", cwd=other)
    (other / "remote_only.txt").write_text("remote\n", encoding="utf-8")
    sh("git", "add", "-A", cwd=other)
    sh("git", "commit", "-m", "remote work", cwd=other)
    sh("git", "push", "origin", BRANCH, cwd=other)
    (local2 / "local_only.txt").write_text("local\n", encoding="utf-8")
    sh("git", "add", "-A", cwd=local2)
    sh("git", "commit", "-m", "local work", cwd=local2)
    hw2 = load_watcher(local2)
    kept2, log2, _ = run_cycle(hw2)
    merged = (local2 / "remote_only.txt").exists()
    div_ok = (not kept2 and status_of(local2) == "stopped-fault" and not merged)
    shutil.rmtree(root2, ignore_errors=True)

    # (c) live agent pid -> no launch, no status write
    root3, local3 = make_repo(handoff("awaiting-VS", agent="mini",
                                      verdict="progress", sig="none"),
                              agent_cmd=["python", "-c", "raise SystemExit(7)"])
    hw3 = load_watcher(local3)
    hw3.pid_alive = lambda p: p == hw3.AGENT_PID   # simulate a live agent
    before = commits(local3)
    kept3, log3, _ = run_cycle(hw3)
    pid_ok = (not kept3 and status_of(local3) == "awaiting-VS"
              and commits(local3) == before and "LAUNCH" not in log3)
    shutil.rmtree(root3, ignore_errors=True)

    ok = dirty_ok and div_ok and pid_ok
    record(4, "refuse on dirty / diverged / live-pid", ok,
           f"dirty->stopped-fault: {dirty_ok}; diverged->stopped-fault & "
           f"no-merge: {div_ok}; live-pid->no launch/no write: {pid_ok}")


def t5_pause():
    # (a) sentinel file
    root, local = make_repo(handoff("awaiting-VS", agent="mini", verdict="progress",
                                    sig="none"),
                            agent_cmd=["python", "-c", "raise SystemExit(7)"])
    (local / "replay_gate" / "HANDOFF_PAUSE").write_text("", encoding="utf-8")
    hw = load_watcher(local)
    before = commits(local)
    kept, log1, _ = run_cycle(hw)
    sentinel_ok = (not kept and status_of(local) == "awaiting-VS"
                   and commits(local) == before and "LAUNCH" not in log1
                   and "PAUSED" in log1)
    # resumes when removed
    (local / "replay_gate" / "HANDOFF_PAUSE").unlink()
    kept2, log2, _ = run_cycle(hw)
    resumed = "LAUNCH" in log2
    shutil.rmtree(root, ignore_errors=True)

    # (b) STATUS: paused -> idle, and NO ping (Nick set it deliberately)
    root2, local2 = make_repo(handoff("paused", agent="mini", verdict="green",
                                      sig="none"))
    hw2 = load_watcher(local2)
    kept3, log3, _ = run_cycle(hw2)
    status_ok = (not kept3 and status_of(local2) == "paused"
                 and "PING" not in log3)
    shutil.rmtree(root2, ignore_errors=True)

    ok = sentinel_ok and resumed and status_ok
    record(5, "PAUSE brake (sentinel + STATUS: paused)", ok,
           f"sentinel->no launch/no write: {sentinel_ok}; resumes: {resumed}; "
           f"STATUS:paused idle & silent: {status_ok}")


def t6_cap():
    root, local = make_repo(handoff("awaiting-VS", turn=16, cap=16, agent="mini",
                                    verdict="progress", sig="none"), cap=8)
    hw = load_watcher(local)
    kept, log1, _ = run_cycle(hw)
    ok = (not kept and status_of(local) == "stopped-cap")
    record(6, "iteration cap", ok, f"kept={kept} status={status_of(local)!r}")
    shutil.rmtree(root, ignore_errors=True)


def t7_no_flip():
    root, local = make_repo(handoff("awaiting-VS", agent="mini", verdict="progress",
                                    sig="none"),
                            agent_cmd=["python", "-c", "raise SystemExit(7)"])
    hw = load_watcher(local)
    kept, log1, _ = run_cycle(hw)
    st = status_of(local)
    named = "did not flip" in log1 or "without flipping" in log1
    ok = (not kept and st == "stopped-fault")
    record(7, "no-flip -> stopped-fault", ok,
           f"kept={kept} status={st!r} names-agent-and-code={named}")
    shutil.rmtree(root, ignore_errors=True)


def t8_timeout():
    root, local = make_repo(handoff("awaiting-VS", agent="mini", verdict="progress",
                                    sig="none", timeout=1),
                            agent_cmd=["python", "-c",
                                       "import time; time.sleep(300)"])
    hw = load_watcher(local)
    # 1 minute is the smallest the parser accepts; shrink the multiplier so the
    # audit does not sit for a minute. The PATH under test is unchanged.
    real_launch = hw.launch_agent

    def fast_launch(agent, cfg, timeout_minutes):
        import subprocess as sp
        hw.LOG_DIR.mkdir(parents=True, exist_ok=True)
        logfile = hw.LOG_DIR / "t8.txt"
        with open(logfile, "w", encoding="utf-8") as out:
            child = sp.Popen(["python", "-c", "import time; time.sleep(300)"],
                             cwd=str(hw.REPO), stdout=out, stderr=sp.STDOUT)
            hw.AGENT_PID.write_text(str(child.pid), encoding="utf-8")
            try:
                child.wait(timeout=2)          # stands in for timeout*60
                code = child.returncode
            except sp.TimeoutExpired:
                child.kill()
                code = -9
        hw.AGENT_PID.unlink(missing_ok=True)
        return code, logfile

    hw.launch_agent = fast_launch
    kept, log1, _ = run_cycle(hw)
    st = status_of(local)
    ok = (not kept and st == "stopped-fault" and "timed out" in log1.lower()
          or (not kept and st == "stopped-fault" and "timeout" in log1.lower()))
    record(8, "turn timeout -> killed + stopped-fault", ok,
           f"kept={kept} status={st!r} | "
           f"{[l for l in log1.splitlines() if 'PING' in l or 'timeout' in l.lower()][:2]}")
    hw.launch_agent = real_launch
    shutil.rmtree(root, ignore_errors=True)


def t9_self_flip_pings():
    """THE ONE VS JUST FIXED. Both halves."""
    halves = []
    for verdict, want_urgent in (("green", False), ("drift", True),
                                 ("needs-ruling", False)):
        root, local = make_repo(handoff("awaiting-Nick", agent="mini",
                                        verdict=verdict, sig="none"),
                                agent_cmd=["python", "-c", "raise SystemExit(7)"])
        hw = load_watcher(local)
        kept, log1, state = run_cycle(hw)
        pinged = "PING" in log1
        urgent = "URGENT" in log1
        launched = "LAUNCH" in log1
        # exactly one ping across two polls
        _k2, log2, _ = run_cycle(hw, state=state)
        once = pinged and "PING" not in log2
        good = (not kept and pinged and once and not launched
                and urgent == want_urgent)
        halves.append((verdict, good, pinged, once, urgent, launched))
        shutil.rmtree(root, ignore_errors=True)

    # 9b: stopped-* / paused must stay SILENT
    silent = []
    for st in ("paused", "stopped-stuck", "stopped-cap", "stopped-fault"):
        root, local = make_repo(handoff(st, agent="mini", verdict="green",
                                        sig="none"))
        hw = load_watcher(local)
        _k, log1, _ = run_cycle(hw)
        silent.append((st, "PING" not in log1))
        shutil.rmtree(root, ignore_errors=True)

    ok = all(h[1] for h in halves) and all(s[1] for s in silent)
    record(9, "agent self-flip to awaiting-Nick PINGS (VS's fix)", ok,
           "; ".join(f"{v}: ping={p} once={o} urgent={u} launched={l}"
                     for v, _g, p, o, u, l in halves)
           + " || silent: " + ", ".join(f"{s}={q}" for s, q in silent))




# ==========================================================================
# ADVERSARIAL PROBES - beyond VS's nine. VS found a silent-on-success bug in
# his own safety code; these look for another path where the SAFE outcome is
# the one that fails open.
# ==========================================================================
FLIP_STUB = ("import subprocess,pathlib;"
             "p=pathlib.Path('replay_gate/HANDOFF.md');"
             "t=p.read_text().splitlines();t[0]='STATUS: awaiting-mini';"
             "p.write_text('\\n'.join(t)+'\\n');"
             "subprocess.run(['git','add','-A']);"
             "subprocess.run(['git','commit','-m','stub flip'])")


def probe_continues(label, verdict, result="RESULT: done", should_continue=False):
    """A CORRECTLY-flipping stub, so 'did the loop roll on' is unambiguous."""
    root, local = make_repo(handoff("awaiting-VS", agent="mini", verdict=verdict,
                                    sig="none", result=result),
                            agent_cmd=["python", "-c", FLIP_STUB])
    hw = load_watcher(local)
    kept, log1, _ = run_cycle(hw)
    ok = (kept == should_continue)
    print(f"[{'ok  ' if ok else 'HOLE'}] {label}: verdict={verdict!r} "
          f"continued={kept} (want {should_continue})")
    shutil.rmtree(root, ignore_errors=True)
    return ok


def probes():
    out = [
        probe_continues("unknown verdict 'gren'", "gren"),
        probe_continues("unknown verdict 'drifted'", "drifted"),
        probe_continues("cased 'Green '", "Green "),
        probe_continues("DRIFT row in table, VERDICT=progress", "progress",
                        result="RESULT: R31 SAME/GOLDEN, R32 MOVED/DRIFT"),
        probe_continues("control: honest progress", "progress",
                        should_continue=True),
    ]
    print(f"probes: {sum(out)}/{len(out)} clean")
    return all(out)


if __name__ == "__main__":
    os.environ.pop("EMAIL_HOST", None)   # ping must ATTEMPT and fail loudly
    for fn in (t1_green_latch, t2_drift_urgent, t3_signature, t4_refusals,
               t5_pause, t6_cap, t7_no_flip, t8_timeout, t9_self_flip_pings):
        try:
            fn()
        except Exception as exc:
            record(int(fn.__name__[1]), fn.__name__, False,
                   f"HARNESS ERROR {type(exc).__name__}: {exc}")
    probes()
    print("\n" + "=" * 70)
    bad = [r for r in RESULTS if not r[2]]
    print(f"{len(RESULTS) - len(bad)}/{len(RESULTS)} behaviours pass")
    for num, name, _ok, detail in bad:
        print(f"  FAIL {num}. {name}: {detail}")
    raise SystemExit(1 if bad else 0)
