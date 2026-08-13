"""VS<->mini HANDOFF WATCHER — the doorbell (spec:
docs/architecture/vs_mini_handoff_watcher_spec.md, approved by Nick
2026-08-12 with the SS9 rulings + PAUSE brake).

A clock and a router, never a merger: reads the STATUS line of
replay_gate/HANDOFF.md, launches exactly one headless agent at a
time, watches for the flip, and STOPS for Nick on: awaiting-Nick /
needs-ruling, GREEN (always — force-override even if the agent
flipped elsewhere), DRIFT (harder than green: URGENT ping),
same ERROR-SIGNATURE twice per direction, the iteration cap, any
process fault, and the manual PAUSE brake.

Run:  python scripts/handoff_watch.py            (foreground loop)
Stop: create replay_gate/HANDOFF_PAUSE (clean stop at turn boundary)
      or Ctrl+C (never kills a live agent turn on its own).
"""
from __future__ import annotations

import json
import os
import re
import smtplib
import subprocess
import sys
import time
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HANDOFF = REPO / "replay_gate" / "HANDOFF.md"
PAUSE_SENTINEL = REPO / "replay_gate" / "HANDOFF_PAUSE"
CONFIG_PATH = REPO / "replay_gate" / "handoff_config.json"
STATE_DIR = REPO / "_handoff"
LOG_DIR = STATE_DIR / "logs"
WATCHER_PID = STATE_DIR / "watcher.pid"
AGENT_PID = STATE_DIR / "agent.pid"
STATE_PATH = STATE_DIR / "state.json"

AGENT_STATUSES = {"awaiting-VS": "VS", "awaiting-mini": "mini"}
STOP_STATUSES = {"awaiting-Nick", "stopped-stuck", "stopped-cap", "stopped-fault", "paused"}
VALID_VERDICTS = {"progress", "green", "blocked", "needs-ruling", "drift"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    line = f"{_now()} {msg}"
    print(line, flush=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / "watcher.log", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def load_config() -> dict:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg.setdefault("cap_round_trips", 8)
    cfg.setdefault("poll_seconds", 60)
    cfg.setdefault("default_turn_timeout_minutes", 180)
    cfg.setdefault("branch", "intake-stable")
    cfg.setdefault("push_retries", 3)
    return cfg


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_signature": {}, "last_ping": ""}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- git
def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(REPO), capture_output=True, text=True, check=check,
    )


def git_clean_tracked() -> bool:
    out = git("status", "--porcelain").stdout
    return not any(line and not line.startswith("??") for line in out.splitlines())


def git_sync(branch: str) -> str:
    """fetch; ff-only reconcile. Returns '' if ok else a fault reason."""
    git("fetch", "origin", branch)
    local = git("rev-parse", "HEAD").stdout.strip()
    remote = git("rev-parse", f"origin/{branch}").stdout.strip()
    if local == remote:
        return ""
    base = git("merge-base", "HEAD", f"origin/{branch}").stdout.strip()
    if base == local:  # remote strictly ahead -> ff pull
        if not git_clean_tracked():
            return "remote-ahead-but-tree-dirty"
        got = git("merge", "--ff-only", f"origin/{branch}", check=False)
        return "" if got.returncode == 0 else f"ff-only-failed: {got.stderr[:200]}"
    if base == remote:  # local ahead -> push (SS9 ruling 4: immediate)
        return push_with_retries(branch)
    return "history-diverged"


def push_with_retries(branch: str, retries: int = 3) -> str:
    for attempt in range(1, retries + 1):
        got = git("push", "origin", branch, check=False)
        if got.returncode == 0:
            return ""
        log(f"push attempt {attempt}/{retries} failed: {got.stderr.strip()[:200]}")
        time.sleep(10)
    return "push-failed-after-retries"


# ----------------------------------------------------------- handoff
def parse_handoff() -> dict:
    """Strict parse; raises ValueError on malformed (watcher never guesses)."""
    text = HANDOFF.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or not lines[0].startswith("STATUS:"):
        raise ValueError("line 1 is not 'STATUS: <value>'")
    status = lines[0].split(":", 1)[1].strip()
    known = set(AGENT_STATUSES) | STOP_STATUSES
    if status not in known:
        raise ValueError(f"unknown STATUS {status!r}")
    turn_match = re.search(r"^TURN:\s*(\d+)\s*/\s*(\d+)\s*$", text, re.M)
    turn = int(turn_match.group(1)) if turn_match else 0
    cap = int(turn_match.group(2)) if turn_match else 0

    def _field(name: str) -> str:
        matches = re.findall(rf"^\s*{name}:\s*(.+?)\s*$", text, re.M)
        return matches[-1].strip() if matches else ""

    timeout_line = _field("TURN-TIMEOUT-MINUTES")
    return {
        "status": status,
        "turn": turn,
        "cap": cap,
        "agent": _field("AGENT"),
        "verdict": _field("VERDICT").lower(),
        "signature": _field("ERROR-SIGNATURE"),
        "turn_timeout_minutes": int(timeout_line) if timeout_line.isdigit() else None,
        "raw": text,
    }


def write_status(new_status: str, *, reason: str, branch: str, bump_turn: int | None = None) -> None:
    """Watcher-owned writes: STATUS line, optional TURN bump. Commit+push immediately."""
    text = HANDOFF.read_text(encoding="utf-8")
    lines = text.splitlines()
    lines[0] = f"STATUS: {new_status}"
    text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    if bump_turn is not None:
        text = re.sub(r"^TURN:\s*\d+\s*/", f"TURN: {bump_turn}/", text, count=1, flags=re.M)
    HANDOFF.write_text(text, encoding="utf-8")
    git("add", str(HANDOFF.relative_to(REPO)))
    got = git("commit", "-m", f"[handoff-watcher] {reason}", check=False)
    if got.returncode != 0 and "nothing to commit" not in (got.stdout + got.stderr):
        raise RuntimeError(f"watcher commit failed: {got.stderr[:300]}")
    fault = push_with_retries(branch)
    if fault:
        raise RuntimeError(f"watcher push failed: {fault}")


# -------------------------------------------------------------- ping
def ping(subject: str, body: str, state: dict) -> None:
    key = f"{subject}|{git('rev-parse', 'HEAD').stdout.strip()}"
    if state.get("last_ping") == key:
        return  # one ping per stop per ref — never loop-ping
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO / ".env")
        host = os.environ["EMAIL_HOST"]
        port = int(os.environ.get("EMAIL_PORT", "587"))
        user = os.environ["EMAIL_USER"]
        pw = os.environ["EMAIL_PASSWORD"]
        to = os.environ["EMAIL_ALERTS_ADDRESS"]
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = user
        msg["To"] = to
        with smtplib.SMTP(host, port) as s:
            s.starttls()
            s.login(user, pw)
            s.sendmail(user, [to], msg.as_string())
        log(f"PING sent: {subject}")
    except Exception as exc:  # ping failure is loud in the log but not fatal
        log(f"PING FAILED ({subject}): {type(exc).__name__}: {exc}")
    state["last_ping"] = key
    save_state(state)


def result_block(raw: str) -> str:
    idx = raw.rfind("RESULT:")
    return raw[idx:][:1500] if idx >= 0 else "(no RESULT block)"


# ------------------------------------------------------------- agent
def pid_alive(pid_file: Path) -> bool:
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
    except Exception:
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True,
        ).stdout
        return str(pid) in out
    except Exception:
        return False


def launch_agent(agent: str, cfg: dict, timeout_minutes: int) -> tuple[int, Path]:
    """Run one headless agent turn to completion. Returns (returncode, logfile)."""
    prompt_path = REPO / "replay_gate" / f"HANDOFF_PROMPT_{agent.upper()}.md"
    prompt = prompt_path.read_text(encoding="utf-8")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logfile = LOG_DIR / f"{stamp}-{agent}.txt"
    template = cfg.get("agent_command", ["claude", "-p", "{prompt}", "--dangerously-skip-permissions"])
    cmd = [part.replace("{prompt}", prompt) for part in template]
    log(f"LAUNCH {agent} (timeout {timeout_minutes}m) -> {logfile.name}")
    with open(logfile, "w", encoding="utf-8") as out:
        child = subprocess.Popen(cmd, cwd=str(REPO), stdout=out, stderr=subprocess.STDOUT, shell=False)
        AGENT_PID.write_text(str(child.pid), encoding="utf-8")
        try:
            child.wait(timeout=timeout_minutes * 60)
            code = child.returncode
        except subprocess.TimeoutExpired:
            child.kill()
            code = -9
    AGENT_PID.unlink(missing_ok=True)
    return code, logfile


# -------------------------------------------------------------- loop
def stop(new_status: str, reason: str, subject: str, body: str, cfg: dict, state: dict, urgent: bool = False) -> None:
    prefix = "URGENT HANDOFF STOPPED" if urgent else "HANDOFF STOPPED"
    try:
        write_status(new_status, reason=reason, branch=cfg["branch"])
    except Exception as exc:
        log(f"STATUS write failed during stop: {exc}")
    ping(f"{prefix}: {subject}", body, state)


def one_cycle(cfg: dict, state: dict) -> bool:
    """Returns True to keep looping, False when idling on a stop state."""
    branch = cfg["branch"]
    fault = git_sync(branch)
    if fault:
        h = parse_handoff()
        stop("stopped-fault", f"git fault: {fault}",
             f"git fault ({fault})", f"git_sync fault: {fault}\n\n{result_block(h['raw'])}", cfg, state)
        return False
    # PAUSE brake — Nick's manual emergency brake, checked before EVERY launch.
    if PAUSE_SENTINEL.exists():
        log("PAUSED (sentinel present) — idling at turn boundary")
        return False
    try:
        h = parse_handoff()
    except Exception as exc:
        stop("stopped-fault", f"malformed HANDOFF.md: {exc}",
             "malformed HANDOFF.md", f"parse error: {exc}", cfg, state)
        return False
    status = h["status"]
    if status in STOP_STATUSES:
        # An AGENT that follows its contract flips to awaiting-Nick ITSELF on
        # green / drift / needs-ruling. The watcher still owes Nick the ping -
        # otherwise the CORRECT agent behavior is the one path that stays
        # silent. The last_ping latch keeps it to one per stop.
        if status == "awaiting-Nick":
            verdict = h["verdict"]
            body = result_block(h["raw"])
            if verdict == "drift":
                ping("URGENT HANDOFF STOPPED: DRIFT — look now",
                     f"A negative control MOVED. Never auto-continue past this.\n\n{body}", state)
            elif verdict == "green":
                ping("HANDOFF STOPPED: green — confirm",
                     f"A clean/green result is waiting for your look.\n\n{body}", state)
            else:
                ping("HANDOFF STOPPED: ruling needed", body, state)
        return False  # idle; only Nick re-arms

    # GREEN / DRIFT force-override: even if the agent flipped to the other
    # agent, a green or drift verdict NEVER self-continues.
    if h["verdict"] == "green":
        stop("awaiting-Nick", "force-stop: VERDICT=green", "green — confirm",
             f"A clean/green result is waiting for your look.\n\n{result_block(h['raw'])}", cfg, state)
        return False
    if h["verdict"] == "drift":
        stop("awaiting-Nick", "force-stop: VERDICT=drift", "DRIFT — look now",
             f"A negative control MOVED. Never auto-continue past this.\n\n{result_block(h['raw'])}",
             cfg, state, urgent=True)
        return False
    if h["verdict"] == "needs-ruling":
        stop("awaiting-Nick", "needs-ruling", "ruling needed",
             result_block(h["raw"]), cfg, state)
        return False

    agent = AGENT_STATUSES[status]
    # SAME ERROR TWICE, per direction: the previous RESULT was written by the
    # OTHER agent; compare the incoming task's signature against what THIS
    # agent last reported. Convergence = a new signature every rung.
    sig = h["signature"]
    if sig and sig.lower() != "none":
        prev = state["last_signature"].get(h["agent"] or "?", "")
        if prev and prev == sig:
            stop("stopped-stuck", f"same ERROR-SIGNATURE twice: {sig}",
                 f"stuck on {sig}",
                 f"The loop is not converging: {sig} repeated for {h['agent']}.\n\n{result_block(h['raw'])}",
                 cfg, state)
            return False
        if h["agent"]:
            state["last_signature"][h["agent"]] = sig
            save_state(state)
    elif h["verdict"] and h["verdict"] not in ("green",):
        log(f"note: RESULT verdict={h['verdict']!r} with no ERROR-SIGNATURE (spec wants one)")

    # ITERATION CAP (watcher-owned counter)
    cap = cfg["cap_round_trips"]
    next_turn = h["turn"] + 1
    if next_turn > cap * 2:  # cap counts ROUND-TRIPS; TURN counts agent turns
        stop("stopped-cap", f"iteration cap {cap} round-trips",
             "iteration cap reached",
             f"TURN {h['turn']} hit the {cap}-round-trip ceiling.\n\n{result_block(h['raw'])}", cfg, state)
        return False

    # Launch preconditions (spec SS3.3): no live agent, clean tree, synced.
    if pid_alive(AGENT_PID):
        log("agent pid alive — waiting")
        return False
    if not git_clean_tracked():
        stop("stopped-fault", "dirty tracked tree at launch boundary",
             "dirty tree", git("status", "--porcelain").stdout[:1200], cfg, state)
        return False

    write_status(status, reason=f"turn {next_turn}: launch {agent}", branch=branch, bump_turn=next_turn)
    timeout = h["turn_timeout_minutes"] or cfg["default_turn_timeout_minutes"]
    code, logfile = launch_agent(agent, cfg, timeout)
    if code == -9:
        stop("stopped-fault", f"{agent} turn timeout after {timeout}m",
             f"{agent} timed out",
             f"Killed after {timeout} minutes (timeouts catch HANGS; if this was a "
             f"valid long run, raise TURN-TIMEOUT-MINUTES in the TASK block).\n"
             f"log tail:\n{logfile.read_text(encoding='utf-8', errors='replace')[-1500:]}",
             cfg, state)
        return False
    # Did the agent flip? (Its final commit carries the flip.)
    try:
        after = parse_handoff()
    except Exception as exc:
        stop("stopped-fault", f"post-turn HANDOFF malformed: {exc}",
             "malformed HANDOFF.md after turn", str(exc), cfg, state)
        return False
    if after["status"] == status:
        stop("stopped-fault", f"{agent} exited (code {code}) without flipping STATUS",
             f"{agent} did not flip",
             f"exit code {code}; log tail:\n{logfile.read_text(encoding='utf-8', errors='replace')[-1500:]}",
             cfg, state)
        return False
    fault = git_sync(branch)  # push the agent's work if it could not (SS3.4)
    if fault:
        stop("stopped-fault", f"post-turn git fault: {fault}", f"git fault ({fault})",
             fault, cfg, state)
        return False
    log(f"turn complete: {status} -> {after['status']} (verdict={after['verdict'] or '-'})")
    return True


def main() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if pid_alive(WATCHER_PID):
        print("another watcher is alive — exiting", file=sys.stderr)
        return 2
    WATCHER_PID.write_text(str(os.getpid()), encoding="utf-8")
    cfg = load_config()
    state = load_state()
    log(f"watcher up (cap={cfg['cap_round_trips']} rt, poll={cfg['poll_seconds']}s, "
        f"timeout={cfg['default_turn_timeout_minutes']}m, branch={cfg['branch']})")
    try:
        while True:
            try:
                one_cycle(cfg, state)
            except Exception as exc:
                log(f"cycle error: {type(exc).__name__}: {exc}")
                try:
                    stop("stopped-fault", f"watcher exception: {type(exc).__name__}",
                         "watcher exception", f"{type(exc).__name__}: {exc}", cfg, state)
                except Exception:
                    pass
                return 1
            time.sleep(cfg["poll_seconds"])
            cfg = load_config()  # config is live-tunable (SS9 ruling 2)
    finally:
        WATCHER_PID.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
