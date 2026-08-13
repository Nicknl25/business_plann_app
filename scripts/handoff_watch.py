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
INBOX = REPO / "replay_gate" / "HANDOFF_INBOX.md"
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
# DATA, NOT PROSE. The first cut scanned for the word "drift" and exempted
# zero-counts — which fired URGENT on mini's own sentences ("would have fired
# a FALSE DRIFT", "surfaces as a named DRIFT") and cried wolf over a clean
# table. False urgency erodes the one alarm that must never be ignored, so the
# backstop now matches only DRIFT in a COUNTED or ROW shape.
_DRIFT_REAL = (
    re.compile(r"(?<!\d)[1-9]\d*\s+drift\b", re.I),            # "1 DRIFT"
    re.compile(r"\bdrift\b\s*[:=]\s*[1-9]\d*", re.I),          # "DRIFT: 2"
    re.compile(r"^.*\b[RI]\d{1,3}\b.*\bdrift\b.*$", re.I | re.M),  # a leg row
)


def result_mentions_drift(block: str) -> bool:
    """F2 backstop (mini's audit): a DRIFT ROW or NONZERO DRIFT COUNT in the
    RESULT outranks the VERDICT line — defense in depth against a
    self-mislabelled table (DRIFT rows carrying VERDICT: progress).

    Narrative prose about drift is NOT a trigger. A mislabelled table always
    carries the count or the leg row; an agent describing the concept does
    not. The VERDICT field remains the primary channel — this is the belt."""
    return any(pattern.search(block) for pattern in _DRIFT_REAL)


def parse_handoff() -> dict:
    """Strict parse; raises ValueError on malformed (watcher never guesses).

    FAILS CLOSED on an unknown VERDICT (F1, mini's blocker): a typo'd
    'gren'/'drifted' used to fall past every stop branch and behave like
    progress — a one-character slip would run unattended past a clean table.
    An unrecognized verdict is now a stopped-fault, never a continue."""
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
    verdict = _field("VERDICT").strip().lower()
    if verdict and verdict not in VALID_VERDICTS:
        # F1 FAIL CLOSED: an unrecognized verdict is a fault, never a
        # continue. 'gren' must not behave like progress.
        raise ValueError(
            f"unknown VERDICT {verdict!r} (valid: {sorted(VALID_VERDICTS)}) — "
            "failing closed rather than continuing"
        )
    effective = verdict
    if verdict != "drift" and result_mentions_drift(result_block(text)):
        effective = "drift"  # F2 backstop: the table outranks the label
    return {
        "status": status,
        "turn": turn,
        "cap": cap,
        "agent": _field("AGENT"),
        "verdict": effective,
        "declared_verdict": verdict,
        "signature": _field("ERROR-SIGNATURE"),
        "turn_timeout_minutes": int(timeout_line) if timeout_line.isdigit() else None,
        "raw": text,
    }


INBOX_TEMPLATE = """# HANDOFF INBOX — plain English only.
# Nick writes what he wants in normal words (e.g. "go", "run the R32 cycle",
# "re-run the prove and have mini audit it"). The WATCHER seeds the task and
# flips STATUS itself. Nick never edits HANDOFF.md, STATUS, config, or code.
# Prefix a line with "mini:" to address mini instead of VS.
"""


def read_inbox() -> str:
    """Nick's plain-English instruction, if any. Comments and blanks ignored."""
    if not INBOX.exists():
        return ""
    body = [
        line for line in INBOX.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return "\n".join(body).strip()


def consume_inbox(text: str, branch: str) -> None:
    """THE RE-ARM PATH THAT NEVER TOUCHES NICK: an English line becomes the
    TASK block, the TURN counter resets, PAUSE lifts, STATUS flips — all
    watcher-side. Consumed exactly once (the inbox is cleared in the same
    commit), so a stale line can never silently resume a paused loop later."""
    target = "awaiting-mini" if text.lower().startswith("mini:") else "awaiting-VS"
    task = text.split(":", 1)[1].strip() if text.lower().startswith("mini:") else text
    raw = HANDOFF.read_text(encoding="utf-8")
    seeded = re.sub(
        r"(?ms)^TASK:\n.*?(?=^RESULT:)",
        "TASK:\n" + "\n".join(f"  {ln}" for ln in task.splitlines()) + "\n",
        raw, count=1,
    )
    lines = seeded.splitlines()
    lines[0] = f"STATUS: {target}"
    seeded = re.sub(r"^TURN:\s*\d+\s*/", "TURN: 0/", "\n".join(lines), count=1, flags=re.M) + "\n"
    HANDOFF.write_text(seeded, encoding="utf-8")
    INBOX.write_text(INBOX_TEMPLATE, encoding="utf-8")
    pause_lifted = False
    if PAUSE_SENTINEL.exists():
        PAUSE_SENTINEL.unlink()
        pause_lifted = True
        log("PAUSE lifted by an inbox instruction (Nick's words are the un-pause)")
    # `git add -A -- <path>` FATALS on a pathspec that matches nothing, so the
    # sentinel is staged only when it actually existed (and never fatally).
    git("add", "-A", "--", str(HANDOFF.relative_to(REPO)), str(INBOX.relative_to(REPO)))
    if pause_lifted:
        git("add", "-A", "--", str(PAUSE_SENTINEL.relative_to(REPO)), check=False)
    got = git("commit", "-m", f"[handoff-watcher] seed from inbox -> {target}", check=False)
    if got.returncode != 0 and "nothing to commit" not in (got.stdout + got.stderr):
        raise RuntimeError(f"inbox seed commit failed: {got.stderr[:300]}")
    fault = push_with_retries(branch)
    if fault:
        raise RuntimeError(f"inbox seed push failed: {fault}")
    log(f"inbox consumed -> {target}: {task[:120]}")


def resolve_agent_binary(cfg: dict) -> str:
    """Find the claude CLI without Nick ever configuring anything: explicit
    config path -> PATH -> the VS Code extension's native binary (newest
    version dir, so an extension update cannot break the loop)."""
    explicit = str(cfg.get("agent_binary") or "").strip()
    if explicit and explicit.lower() != "auto" and Path(explicit).exists():
        return explicit
    from shutil import which
    found = which("claude")
    if found:
        return found
    ext_root = Path(os.environ.get("USERPROFILE", "")) / ".vscode" / "extensions"
    cands = sorted(ext_root.glob("anthropic.claude-code-*/resources/native-binary/claude.exe"))
    if cands:
        return str(cands[-1])
    raise RuntimeError(
        "cannot resolve the claude CLI — set agent_binary in replay_gate/handoff_config.json"
    )


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
    # Nick's interface is English in / ping out — so the ping itself says how
    # to continue, and it is never "edit this file".
    body = body.rstrip() + (
        "\n\n---\nTo continue: just say what you want in plain English "
        "('go', 're-run it', 'have mini audit that'). VS or the watcher does "
        "every mechanical step — you never edit HANDOFF.md, STATUS, config, "
        "or code."
    )
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
    """FAIL CLOSED (mini's latent finding): if we cannot tell whether the
    process is alive, assume it IS. An unknown-state agent must never be
    raced by a second launch, and an unknown-state watcher must never be
    duplicated. The old catch-all returned False, so a broken process table
    would have opened BOTH guards at once."""
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
    except Exception as exc:
        log(f"pid file {pid_file.name} unreadable ({exc}) — assuming ALIVE "
            "(fail closed); delete it if you know the process is gone")
        return True
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True, text=True, timeout=30,
        ).stdout
        return str(pid) in out
    except Exception as exc:
        log(f"cannot query the process table ({type(exc).__name__}: {exc}) — "
            f"assuming pid {pid} ALIVE (fail closed)")
        return True


def launch_agent(agent: str, cfg: dict, timeout_minutes: int) -> tuple[int, Path]:
    """Run one headless agent turn to completion. Returns (returncode, logfile)."""
    prompt_path = REPO / "replay_gate" / f"HANDOFF_PROMPT_{agent.upper()}.md"
    prompt = prompt_path.read_text(encoding="utf-8")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logfile = LOG_DIR / f"{stamp}-{agent}.txt"
    template = cfg.get("agent_command", ["{binary}", "-p", "{prompt}", "--dangerously-skip-permissions"])
    binary = resolve_agent_binary(cfg) if any("{binary}" in part for part in template) else ""
    cmd = [part.replace("{binary}", binary).replace("{prompt}", prompt) for part in template]
    beat = int(cfg.get("heartbeat_seconds", 30))
    log(f"LAUNCH {agent} (timeout {timeout_minutes}m) -> {logfile.name}")
    log(f"    tail the agent: Get-Content -Wait '{logfile}'")
    with open(logfile, "w", encoding="utf-8") as out:
        child = subprocess.Popen(cmd, cwd=str(REPO), stdout=out, stderr=subprocess.STDOUT, shell=False)
        AGENT_PID.write_text(str(child.pid), encoding="utf-8")
        started = time.time()
        deadline = started + timeout_minutes * 60
        last_beat = started
        # HEARTBEAT WHILE WORKING: the old child.wait() blocked silently for
        # the whole turn, so a healthy 10-minute turn and a dead watcher
        # looked identical. Never block without a pulse.
        while True:
            code = child.poll()
            if code is not None:
                break
            now = time.time()
            if now >= deadline:
                child.kill()
                code = -9
                break
            if now - last_beat >= beat:
                last_beat = now
                elapsed = int(now - started)
                size = logfile.stat().st_size if logfile.exists() else 0
                log(f"... working: {agent} pid={child.pid} "
                    f"{elapsed // 60}m{elapsed % 60:02d}s elapsed, "
                    f"agent log {size:,}B, timeout in {int((deadline - now) / 60)}m")
            time.sleep(2)
    AGENT_PID.unlink(missing_ok=True)
    elapsed = int(time.time() - started)
    log(f"    {agent} exited code={code} after {elapsed // 60}m{elapsed % 60:02d}s")
    return code, logfile


def idle_sleep(cfg: dict, seconds: int) -> None:
    """HEARTBEAT WHILE IDLE: a pulse every heartbeat_seconds so silence in
    the log always means something is genuinely wrong."""
    beat = max(5, int(cfg.get("heartbeat_seconds", 30)))
    end = time.time() + seconds
    while time.time() < end:
        time.sleep(min(beat, max(1.0, end - time.time())))
        try:
            status = parse_handoff()["status"]
        except Exception as exc:
            status = f"UNPARSEABLE ({type(exc).__name__})"
        waiting_for = {
            "awaiting-Nick": " — waiting on your word (say it in plain English)",
            "paused": " — PAUSED",
        }.get(status, "")
        remaining = max(0, int(end - time.time()))
        log(f"... idle: STATUS={status}, no child, next poll in {remaining}s{waiting_for}")


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
    inbox = read_inbox()
    # F3 (mini's audit): the PAUSE brake is checked BEFORE any git action. A
    # paused watcher with a diverged HEAD used to still commit and push a
    # stopped-fault — pause must halt everything, not just launches. An
    # inbox instruction outranks pause: Nick's words ARE the un-pause.
    if PAUSE_SENTINEL.exists() and not inbox:
        log("PAUSED (sentinel present) — idling at turn boundary, no git action")
        return False
    if inbox:
        consume_inbox(inbox, branch)
        return True
    # HANDS OFF WHILE AN AGENT OWNS THE TREE: if a child is alive (this
    # watcher's or one inherited from a previous watcher process), do NO git
    # work at all. The blocking child.wait() used to guarantee this
    # implicitly; the polling loop must guarantee it explicitly.
    if pid_alive(AGENT_PID):
        try:
            pid_txt = AGENT_PID.read_text(encoding="utf-8").strip()
        except Exception:
            pid_txt = "?"
        log(f"... agent turn in flight (pid {pid_txt}) — watcher hands off the tree")
        return False
    fault = git_sync(branch)
    if fault:
        h = parse_handoff()
        stop("stopped-fault", f"git fault: {fault}",
             f"git fault ({fault})", f"git_sync fault: {fault}\n\n{result_block(h['raw'])}", cfg, state)
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
            idle_sleep(cfg, int(cfg["poll_seconds"]))
            cfg = load_config()  # config is live-tunable (SS9 ruling 2)
    finally:
        WATCHER_PID.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
