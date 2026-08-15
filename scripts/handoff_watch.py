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
STOP_REQUEST = STATE_DIR / "watcher.stop_request"

AGENT_STATUSES = {"awaiting-VS": "VS", "awaiting-mini": "mini"}
STOP_STATUSES = {"awaiting-Nick", "stopped-stuck", "stopped-cap", "stopped-fault", "paused"}
VALID_VERDICTS = {"progress", "green", "blocked", "needs-ruling", "drift"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_state_dir() -> None:
    """The watcher's own scratch (pids, logs, state) must be INVISIBLE to git.
    If it is ever tracked — a fresh clone, or an agent's `git add -A` sweeping
    it in — the watcher's next log write dirties the tree and the loop dies on
    a confusing 'dirty tree' fault. A self-ignoring state dir makes that
    unrepresentable."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    marker = STATE_DIR / ".gitignore"
    if not marker.exists():
        marker.write_text("*\n", encoding="utf-8")


def log(msg: str) -> None:
    line = f"{_now()} {msg}"
    print(line, flush=True)
    ensure_state_dir()
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
    ensure_state_dir()
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- git
def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(REPO), capture_output=True, text=True, check=check,
    )


def git_clean_tracked() -> bool:
    out = git("status", "--porcelain").stdout
    return not any(line and not line.startswith("??") for line in out.splitlines())


def git_fetch_with_retries(branch: str, attempts: int = 3) -> bool:
    """A TRANSIENT fetch failure must not burn a stop. One blip (a network
    hiccup, or a collision with a concurrent push) used to raise straight out
    of one_cycle into stopped-fault + ping — observed live at 10:39:56, where
    the very next manual fetch succeeded. Only a PERSISTENT failure is a
    fault."""
    for attempt in range(1, attempts + 1):
        got = git("fetch", "origin", branch, check=False)
        if got.returncode == 0:
            return True
        log(f"fetch attempt {attempt}/{attempts} failed (rc={got.returncode}): "
            f"{got.stderr.strip()[:150]}")
        time.sleep(5)
    return False


_LAST_FETCH_TS = 0.0


def git_sync(branch: str, *, fetch_interval: float = 0.0) -> str:
    """fetch; ff-only reconcile. Returns '' if ok else a fault reason.

    POLL-GAP RULE (Nick): the only idle is an agent genuinely working.
    The poll now runs every ~10s, but fetching origin that often is
    pointless — agents commit LOCALLY on this machine, and `git push`
    updates the remote-tracking ref, so HEAD==origin/branch is correct
    without a fetch for the whole local flow. The fetch exists to see
    REMOTE changes (a pause pushed from Nick's phone), and 60s is fine
    for that. fetch_interval > 0 skips the fetch when the last one is
    fresh."""
    global _LAST_FETCH_TS
    if fetch_interval <= 0 or (time.time() - _LAST_FETCH_TS) >= fetch_interval:
        if not git_fetch_with_retries(branch):
            return "fetch-failed-after-retries"
        _LAST_FETCH_TS = time.time()
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
    not. The VERDICT field remains the primary channel — this is the belt.

    ZERO-COUNTS ARE STRIPPED FIRST, for ALL patterns: the leg-row pattern
    used to fire on the evidence line '58 legs, R40 PROVEN, 0 DRIFT,
    0 UNEARNED' — a leg id and the word drift on one line, with the count
    explicitly ZERO — sending Nick an URGENT for a clean table (2026-08-13
    turn 13). False urgency erodes the one alarm that must never be
    ignored; a stated zero can never be evidence of movement."""
    scrubbed = re.sub(r"(?<![1-9])0\s+drift\b", " ", block, flags=re.I)
    scrubbed = re.sub(r"\bdrift\b\s*[:=]\s*0(?!\d)", " ", scrubbed, flags=re.I)
    return any(pattern.search(scrubbed) for pattern in _DRIFT_REAL)


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
    _task_block = "TASK:\n" + "\n".join(f"  {ln}" for ln in task.splitlines()) + "\n"
    # Lambda replacement: the seed is Nick's prose and may carry a
    # backslash; a raw replacement string is parsed for escapes and
    # 'bad escape \S' killed a whole cycle on 2026-08-15.
    seeded = re.sub(
        r"(?ms)^TASK:\n.*?(?=^RESULT:)",
        lambda _m: _task_block,
        raw, count=1,
    )
    lines = seeded.splitlines()
    lines[0] = f"STATUS: {target}"
    seeded = re.sub(r"^TURN:\s*\d+\s*/", "TURN: 0/", "\n".join(lines), count=1, flags=re.M) + "\n"
    # THE PRIOR RESULT MUST NOT OUTLIVE ITS TASK. Without this, a new
    # instruction seeded after a GREEN stop was force-stopped again on the
    # stale VERDICT: green the moment it flipped — re-arming after the most
    # common stop could never work. The old RESULT stays in git history.
    # A SEED TRUNCATES HISTORY TO THE HEAD (2026-08-15 fix): the file used
    # to keep every prior TASK/RESULT block below the seed, and _field()
    # reads the LAST match - so a seed's TURN-TIMEOUT-MINUTES at the top
    # was shadowed by whatever stale agent-written TASK sat lowest (turn A
    # ran on 240 not 120; a build turn launched with 45). History is in
    # git by doctrine; after a seed the file is exactly STATUS / TURN /
    # the seeded TASK / one neutral RESULT, so first-match, last-match and
    # "the TASK block" all mean the same thing.
    _mt = re.search(r"(?ms)^TASK:\n.*?(?=^RESULT:)", seeded)
    seeded = (seeded[: _mt.end()] if _mt else seeded) + (
            "RESULT:\n"
            "  AGENT: none\n"
            "  VERDICT: progress\n"
            "  ERROR-SIGNATURE: none\n"
            "  EVIDENCE: (superseded — new instruction seeded)\n"
            "  SUMMARY: The previous turn's RESULT was superseded by a new\n"
            "  instruction; it remains in git history.\n"
        )
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
STAGES = REPO / "replay_gate" / "STAGES.md"
_STAGE_ITEM = re.compile(r"^##\s+([A-Za-z0-9][A-Za-z0-9\-]*)")
_STAGE_FIELD = re.compile(r"^\s*(GATE|LIVE|COWORK):\s*([a-z][a-z/\-]*)", re.I)


def stage_items() -> list[dict]:
    """Parse replay_gate/STAGES.md — the ONE place that answers 'is it done?'
    per work item, in stages, because a bare green/red made Nick adjudicate
    two agents' different meanings of 'done'."""
    if not STAGES.exists():
        return []
    items: list[dict] = []
    current: dict | None = None
    for line in STAGES.read_text(encoding="utf-8").splitlines():
        head = _STAGE_ITEM.match(line)
        if head:
            current = {"name": head.group(1), "GATE": "?", "LIVE": "?", "COWORK": "?"}
            items.append(current)
            continue
        if current:
            field = _STAGE_FIELD.match(line)
            if field and current[field.group(1).upper()] == "?":
                current[field.group(1).upper()] = field.group(2).lower()
    return items


def stage_summary(*, only_open: bool = True) -> str:
    """One line per work item. `only_open` keeps the heartbeat short by
    showing just the items that still need something."""
    rows = []
    for item in stage_items():
        open_item = item["LIVE"] in {"pending", "failing"} or item["COWORK"] == "blocked"
        if only_open and not open_item:
            continue
        rows.append(
            f"{item['name']}: GATE={item['GATE']} LIVE={item['LIVE']} COWORK={item['COWORK']}"
        )
    return " | ".join(rows)


def desktop_alert(subject: str) -> None:
    """SECOND CHANNEL. Email can sit unread in a tab nobody is looking at —
    which is exactly what happened: eight pings sent, none seen. A desktop
    alert lands on the machine the loop is running on. Fire and forget; a
    failure here must never stall the watcher."""
    text = subject[:180].replace('"', "'")
    try:
        subprocess.Popen(["msg", "*", "/TIME:0", text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    except Exception:
        pass
    try:  # fallback: non-blocking balloon, never a modal that could hang us
        script = (
            "[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms');"
            "$n=New-Object System.Windows.Forms.NotifyIcon;"
            "$n.Icon=[System.Drawing.SystemIcons]::Warning;$n.Visible=$true;"
            f"$n.ShowBalloonTip(20000,'HANDOFF WATCHER',\"{text}\",'Warning');"
            "Start-Sleep -Seconds 20"
        )
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        log(f"desktop alert failed ({type(exc).__name__}) — email is the only channel")


def ping(subject: str, body: str, state: dict) -> None:
    # Nick's interface is English in / ping out — so the ping itself says how
    # to continue, and it is never "edit this file".
    stages = stage_summary(only_open=False)
    if stages:
        # Every ping answers "where is everything?" without Nick asking.
        body = body.rstrip() + "\n\n--- WORK ITEM STAGES ---\n" + stages.replace(" | ", "\n")
    body = body.rstrip() + (
        "\n\n---\nTo continue: just say what you want in plain English "
        "('go', 're-run it', 'have mini audit that'). VS or the watcher does "
        "every mechanical step — you never edit HANDOFF.md, STATUS, config, "
        "or code."
    )
    # PING DEDUPE (Nick, after the popup storm): a ping fires ONCE per
    # distinct state (subject == STATUS + reason) and stays quiet until the
    # state actually CHANGES. The old key included HEAD, so a confused
    # watcher cycling states re-fired the same alarms as commits moved.
    # Belt: a global minimum interval between ANY two pings — even a
    # confused watcher says its piece once and waits.
    if state.get("last_ping_subject") == subject:
        return
    if time.time() - float(state.get("last_ping_ts", 0)) < 60:
        log(f"ping rate-limited (<60s since last): {subject}")
        return
    desktop_alert(subject)
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
    state["last_ping_subject"] = subject
    state["last_ping_ts"] = time.time()
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
    # THE AGENT IS THE SANCTIONED WRITER. The pre-commit guard refuses a
    # commit while an agent turn is in flight, because two sessions writing
    # one index conflates history - but the agent itself is the one session
    # that MUST commit: the turn contract ends with the STATUS flip riding
    # its last commit. Without this the guard blocks the very turn it exists
    # to protect, every cycle reads as stopped-fault NO-FLIP, and the loop
    # cannot advance. Only the child gets the exemption; a human shell in
    # another window still hits the guard.
    child_env = dict(os.environ, HANDOFF_ALLOW_COMMIT="1")
    with open(logfile, "w", encoding="utf-8") as out:
        child = subprocess.Popen(cmd, cwd=str(REPO), stdout=out, stderr=subprocess.STDOUT,
                                 shell=False, env=child_env)
        AGENT_PID.write_text(str(child.pid), encoding="utf-8")
        started = time.time()
        deadline = started + timeout_minutes * 60
        last_beat = started
        # SELF-WATCHDOG (Nick's ruling 3): alive-but-dead-inside is a fault
        # to act on, not a state to rest in. The agent LOG is no signal
        # (buffered until exit), so 'genuinely executing' is measured by CPU
        # accumulation: less than hung_agent_cpu_seconds of CPU across a
        # watchdog_minutes window means hung -> kill, code -8, and one_cycle
        # runs the known-fault recovery on it.
        wd_window = float(cfg.get("watchdog_minutes", 12)) * 60
        wd_min_cpu = float(cfg.get("hung_agent_cpu_seconds", 5.0))
        wd_mark_ts = started
        wd_mark_cpu = _cpu_seconds(child.pid) or 0.0
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
            if now - wd_mark_ts >= wd_window:
                cpu_now = _cpu_seconds(child.pid)
                if cpu_now is not None and (cpu_now - wd_mark_cpu) < wd_min_cpu:
                    log(f"WATCHDOG: {agent} pid={child.pid} accumulated "
                        f"{cpu_now - wd_mark_cpu:.1f}s CPU in {wd_window / 60:.0f}m — hung, killing")
                    child.kill()
                    code = -8
                    break
                wd_mark_ts = now
                wd_mark_cpu = cpu_now if cpu_now is not None else wd_mark_cpu
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
    ensure_state_dir()
    # A LIVE TURN OUTRANKS EVERYTHING - including Nick's inbox. The inbox
    # used to be consumed FIRST, so a plain-English line dropped mid-turn
    # would flip STATUS and reset TURN underneath a live agent, whose own
    # final flip would then collide. Nick's words must never interrupt a
    # live turn; they are consumed at the next boundary, seconds later.
    # (Also: no git work at all while a child owns the tree - the blocking
    # child.wait() used to guarantee that implicitly.)
    if pid_alive(AGENT_PID):
        try:
            pid_txt = AGENT_PID.read_text(encoding="utf-8").strip()
        except Exception:
            pid_txt = "?"
        if read_inbox():
            log(f"... agent turn in flight (pid {pid_txt}) — inbox instruction "
                "waits for the boundary (a live turn outranks the inbox)")
        else:
            log(f"... agent turn in flight (pid {pid_txt}) — watcher hands off the tree")
        return False
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
    fault = git_sync(branch, fetch_interval=float(cfg.get("fetch_interval_seconds", 60)))
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
    if code == -8:
        # WATCHDOG KILL: alive-but-idle agent. Known-fault registry first —
        # a hung turn re-seeds and relaunches (cap-limited); only a failed
        # or repeat recovery pings.
        if auto_recover_dead_turn(agent, cfg, state, logfile, reason="hung (watchdog)"):
            return True
        stop("stopped-fault", f"{agent} hung (watchdog kill) and recovery declined",
             f"{agent} hung",
             f"Watchdog killed an alive-but-idle agent; auto-recovery declined "
             f"(cap or unknown residue).\nlog tail:\n"
             f"{logfile.read_text(encoding='utf-8', errors='replace')[-1500:]}",
             cfg, state)
        return False
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
        # KNOWN-FAULT SELF-HEAL (Nick's ruling): a fault whose recovery is
        # mechanical must not park the loop until Nick notices — the 0-byte-
        # prove death cost an hour of idle for 30 seconds of recovery, twice.
        # Known class: clean exit, no flip, a 0-byte _prove_* artifact (the
        # agent backgrounded its prove and the child died with the session).
        # Recovery = the manual playbook: delete the dead artifact, commit
        # orphaned work (compile-gated), re-seed the SAME turn foreground.
        # Unknown faults and repeat offenders still stop + ping.
        if code == 0 and auto_recover_backgrounded_prove(agent, cfg, state, logfile):
            return True
        stop("stopped-fault", f"{agent} exited (code {code}) without flipping STATUS",
             f"{agent} did not flip",
             f"exit code {code}; log tail:\n{logfile.read_text(encoding='utf-8', errors='replace')[-1500:]}",
             cfg, state)
        return False
    fault = git_sync(branch, fetch_interval=0)  # post-turn: always fetch-fresh (SS3.4)
    if fault:
        stop("stopped-fault", f"post-turn git fault: {fault}", f"git fault ({fault})",
             fault, cfg, state)
        return False
    log(f"turn complete: {status} -> {after['status']} (verdict={after['verdict'] or '-'})")
    return True


# ---------------------------------------------------- known-fault registry
# Nick's ruling: a fault whose recovery is mechanical must not park the loop
# until a human notices. Each entry: detect(agent, code, cfg) -> bool, and
# recover(agent, cfg, state, logfile) -> bool (True = healed, no ping).
# UNKNOWN faults, cap-hit repeats, and failed recoveries still stop + ping —
# self-healing never silently half-happens. Add the NEXT recurring fault
# class here instead of hand-recovering it twice.

def _cpu_seconds(pid: int) -> float | None:
    """Total CPU seconds for a pid, or None if unknowable. Used by the
    watchdog to tell 'genuinely executing' from 'alive but dead inside' —
    the agent LOG is no signal (headless output buffers until exit)."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-Process -Id {pid} -ErrorAction Stop).CPU"],
            capture_output=True, text=True, timeout=20,
        ).stdout.strip()
        return float(out) if out else None
    except Exception:
        return None


def auto_recover_backgrounded_prove(agent: str, cfg: dict, state: dict, logfile: Path) -> bool:
    """Known fault #1 (seen twice, identical): agent exits 0 without
    flipping, leaving a 0-byte _prove_*.txt — it backgrounded the prove and
    the child died with the session. Detector: the 0-byte artifact must
    exist; otherwise this is NOT the known class and the normal fault path
    pings."""
    dead_proves = [
        p for p in REPO.glob("_prove_*.txt")
        if p.stat().st_size == 0 and (time.time() - p.stat().st_mtime) < 6 * 3600
    ]
    if not dead_proves:
        return False
    return _recover_dead_turn(agent, cfg, state, dead_proves=dead_proves,
                              reason="session exited with the prove backgrounded")


def auto_recover_dead_turn(agent: str, cfg: dict, state: dict, logfile: Path, *, reason: str) -> bool:
    """Known fault #2: watchdog-killed hung agent. Same recovery spine —
    clear dead artifacts if any, commit orphaned work (compile-gated),
    re-seed the SAME turn."""
    dead_proves = [
        p for p in REPO.glob("_prove_*.txt")
        if p.stat().st_size == 0 and (time.time() - p.stat().st_mtime) < 6 * 3600
    ]
    return _recover_dead_turn(agent, cfg, state, dead_proves=dead_proves, reason=reason)


def _recover_dead_turn(agent: str, cfg: dict, state: dict, *, dead_proves: list, reason: str) -> bool:
    """The shared recovery spine. True = healed silently; False = decline
    (cap hit or a step failed) and the caller's fault path pings — recovery
    never half-happens silently."""
    turn = parse_handoff().get("turn", 0)
    key = f"turn{turn}-{agent}"
    recoveries = state.setdefault("auto_recoveries", {})
    if recoveries.get(key, 0) >= int(cfg.get("max_auto_recoveries_per_turn", 2)):
        log(f"auto-recovery cap hit for {key} — escalating to Nick")
        return False  # persistent crasher: a human should look

    try:
        # 1. The dead artifacts go away.
        for p in dead_proves:
            p.unlink()
            log(f"auto-recover: deleted 0-byte {p.name}")
        # 2. Orphaned tracked work gets committed AS the agent's — but only
        #    if any changed python still compiles; half-edited code is an
        #    unknown fault, not a known one.
        dirty = [
            line[3:].strip().strip('"')
            for line in git("status", "--porcelain").stdout.splitlines()
            if line and not line.startswith("??")
        ]
        import py_compile
        for f in dirty:
            if f.endswith(".py"):
                py_compile.compile(str(REPO / f), doraise=True)  # raises -> unknown
        if dirty:
            git("add", "-A", "--", *dirty)
            got = git("commit", "-m",
                      f"[handoff-watcher] auto-recover: {agent} turn {turn} orphaned work "
                      f"({reason})", check=False)
            if got.returncode != 0 and "nothing to commit" not in (got.stdout + got.stderr):
                raise RuntimeError(f"orphan commit failed: {got.stderr[:200]}")
        # 3. Re-seed the SAME turn with the corrective task, foreground-prove.
        raw = HANDOFF.read_text(encoding="utf-8")
        corrective = (
            "TASK:\n"
            f"  TURN-TIMEOUT-MINUTES: 240\n"
            f"  AUTO-RECOVERY of your previous session (it exited with the prove\n"
            f"  running in the background; under claude -p there is NO re-invocation\n"
            f"  and children die at exit - the prove died as a 0-byte file, now\n"
            f"  deleted; your orphaned work is committed). Remaining steps ONLY:\n"
            f"  re-run the full prove IN THE FOREGROUND (blocking), read the verdict\n"
            f"  in this same turn, write the RESULT on the prove's actual outcome,\n"
            f"  and flip as your final commit. Everything else from your previous\n"
            f"  task is already done and recorded.\n"
        )
        seeded = re.sub(r"(?ms)^TASK:\n.*?(?=^RESULT:)", corrective, raw, count=1)
        HANDOFF.write_text(seeded, encoding="utf-8")
        git("add", str(HANDOFF.relative_to(REPO)))
        got = git("commit", "-m",
                  f"[handoff-watcher] auto-recover: re-seed {agent} turn {turn} (foreground prove)",
                  check=False)
        if got.returncode != 0 and "nothing to commit" not in (got.stdout + got.stderr):
            raise RuntimeError(f"re-seed commit failed: {got.stderr[:200]}")
        fault = push_with_retries(cfg["branch"])
        if fault:
            raise RuntimeError(fault)
    except Exception as exc:
        log(f"auto-recovery FAILED ({type(exc).__name__}: {exc}) — falling through to the fault path")
        return False

    recoveries[key] = recoveries.get(key, 0) + 1
    save_state(state)
    log(f"AUTO-RECOVERED {key} (attempt {recoveries[key]}) — no ping, relaunching next poll")
    return True


def source_fingerprint() -> str:
    try:
        import hashlib
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
    except Exception:
        return "?"


def main() -> int:
    """Nick's four rules after the popup storm: at most ONE watcher, always
    on CURRENT code, each ping fires once. A stale or duplicate watcher is
    structurally impossible, not detected-and-narrated."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    # HARD SINGLETON: refuse to be the second watcher. If one is alive it is
    # either current (we have no business existing) or stale (rule 1 makes
    # it self-exit within one poll) — either way we ask it to stop and WAIT
    # for it to actually be dead before taking over; if it will not die
    # (mid-turn), we refuse rather than coexist. pid_alive fails CLOSED.
    if pid_alive(WATCHER_PID):
        STOP_REQUEST.write_text(str(os.getpid()), encoding="utf-8")
        print("watcher already alive — stop requested, waiting up to 30s for a clean handoff...")
        for _ in range(30):
            time.sleep(1)
            if not pid_alive(WATCHER_PID):
                break
        else:
            STOP_REQUEST.unlink(missing_ok=True)
            print("existing watcher did not exit (likely mid-turn) — REFUSING to "
                  "coexist; retry at the turn boundary", file=sys.stderr)
            return 2
    STOP_REQUEST.unlink(missing_ok=True)
    WATCHER_PID.write_text(str(os.getpid()), encoding="utf-8")
    cfg = load_config()
    state = load_state()
    booted_src = source_fingerprint()
    booted_head = git("rev-parse", "--short", "HEAD", check=False).stdout.strip()
    log(f"watcher up (cap={cfg['cap_round_trips']} rt, poll={cfg['poll_seconds']}s, "
        f"timeout={cfg['default_turn_timeout_minutes']}m, branch={cfg['branch']}, "
        f"code={booted_src} @ {booted_head})")
    try:
        while True:
            # SELF-TERMINATE ON STALE SOURCE (rule 1): a stale watcher gets
            # out of the way at the next safe boundary — it does not narrate
            # its staleness forever. This check sits BEFORE one_cycle, so a
            # stale process never launches a turn; a turn already in flight
            # finishes inside one_cycle and the exit happens right after.
            if source_fingerprint() != booted_src:
                log("SOURCE CHANGED on disk — self-terminating cleanly at this "
                    "boundary so a fresh watcher can take over (rule: enforce, "
                    "never narrate)")
                return 0
            # CLEAN HANDOFF (rule 2/4): a newer instance asked us to stop.
            if STOP_REQUEST.exists() and not pid_alive(AGENT_PID):
                log("stop requested by a newer watcher — exiting cleanly")
                return 0
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
