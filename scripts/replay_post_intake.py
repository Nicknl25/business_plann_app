"""POST-INTAKE REPLAY GATE (Nick 2026-09-11).

"Take the stored payloads from the last ten drafts, push them straight
through post-intake, get verdicts ... No conversation, no GPT, no waiting.
... no post-intake change ships until the replay passes on all ten."

For each of the N drafts that most recently reached post-intake:
  1. CLONE the draft's intake state into a scratch draft (new draft_id, client_id
     'rpgate...'). Every post-intake OUTPUT column is reset, so the pipeline sees
     exactly what a first submit sees; planning_run_json = intake_complete/pending.
     The source draft is only read, never written.
  2. RUN the real pipeline in its own process: _run_planning_system_for_draft (the
     function the /system-run handler calls), then the handler's own consumer-side
     contract gate. The handler's delivery tail (workbook export, email, OneDrive
     copy, writing trigger) is never called - a replay delivers nothing and mails
     no one, and EMAIL_* / FINMO_MODEL_DELIVERY_DIR are blanked in the worker too.
  3. NO LIVE GPT: GPT_RESPONSE_LOCK_STRICT=1. Every judgment replays from the
     response store. A question the store never recorded is a GPT_MISS verdict that
     names the prompt, never a paid call. The lock key masks ids and datetimes, so
     a copy of an unchanged draft asks byte-identical questions.
  4. JUDGE against the source draft's own last real run:
       PASS         replay completed and passed the contract gate
       FIXED        replay completed; the source run had failed
       KNOWN        replay failed with the SAME signature the source run did
       POSTDATES    replay failed a check whose code first appeared in git AFTER the
                    source's run - an old draft meeting a new rule (Nick 2026-09-11)
       BLESSED      outcome change accepted in replay_gate/post_intake_replay_blessed.json
       REGRESSION   source completed, replay failed         -> do not ship
       ACCEPTANCE_DROP  the source's plan passed acceptance, the replay's does not
                                                            -> do not ship
       NEW_FAILURE  both failed, with different signatures  -> do not ship
       GPT_MISS     a judgment was not in the store         -> do not ship
       ERROR        the harness itself broke                -> do not ship
  5. SWEEP every scratch row: all draft- and run-keyed tables, both keys, and only
     rows whose draft carries the scratch client_id. The response store is never
     swept - it is the cache the replay reads.

Exit 0 = safe to ship, 1 = do not ship, 2 = setup failure.
Usage:
  python scripts/replay_post_intake.py                  # last 10 drafts, 10 in parallel
  python scripts/replay_post_intake.py --drafts 3 --jobs 3
  python scripts/replay_post_intake.py --source 21260361 --source 2f71e20d
  python scripts/replay_post_intake.py --keep           # leave the scratch rows
  python scripts/replay_post_intake.py --sweep-orphans  # remove leftovers of a killed run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "python")
SCRATCH_PREFIX = "rpgate"
BLESSED_PATH = os.path.join(ROOT, "replay_gate", "post_intake_replay_blessed.json")
REPORT_PATH = os.path.join(ROOT, "_runtime", "post_intake_replay_last.json")
LOG_DIR = os.path.join(ROOT, "_runtime", "replay_logs")
EMAIL_KEYS = ("EMAIL_USER", "EMAIL_PASSWORD", "EMAIL_HOST", "EMAIL_PORT",
              "EMAIL_ALERTS_ADDRESS", "FINMO_MODEL_DELIVERY_DIR")

# Post-intake OUTPUT columns, reset on the clone. Measured 2026-09-11: present
# on all 74 drafts that ran post-intake in the last 30 days, absent on the 441
# completed drafts that never did. Every planning_* column is reset as well.
RESET_COLUMNS = frozenset((
    "model_input_json", "finmo_json", "payroll_headcount", "debt_schedule",
    "marketing_schedule_json", "numeric_solver_feedback_json",
    "planning_context_summary_json", "planning_runtime_json",
    "planning_convergence_json", "repair_guidance_json",
    "convergence_state_json", "financial_story",
    "submitted_at", "intake_submission_id",
))
INTAKE_COMPLETE = {
    "contract_version": "planning_run_v1",
    "stage": "intake_complete",
    "status": "pending",
    "gpt_narrative": "Intake complete (post-intake replay gate).",
}
NEVER_SWEEP = frozenset(("post_intake_gpt_response_store",))
BLOCKING = ("REGRESSION", "NEW_FAILURE", "GPT_MISS", "ERROR", "ACCEPTANCE_DROP")

# A failure's signature is its INNERMOST error code - the last snake_case token
# (two or more underscores) followed by a single colon - plus the dotted field
# path after it, when there is one. The wrappers (post_intake_fail_fast::,
# fail_round1_set_tool_rejected:) are the same for every payroll failure, so a
# signature built from them would call any new payroll failure KNOWN.
#   Codes come as `code:` or `code@location:` (POST_INTAKE:payroll_authored_
#   off_stated_payroll@payroll_headcount_payload_build: ...) - the code is the
#   token before the @, never the location after it.
_CODE_RE = re.compile(
    r"([A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+){2,})(?:@[\w.]+)?:(?!:)\s*([A-Za-z_][\w.]*\.[\w.]+)?")
_SIG_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+){2,}")


def signature(detail) -> str:
    text = str(detail or "")
    codes = list(_CODE_RE.finditer(text))
    if codes:
        m = codes[-1]
        return m.group(1) + (":" + m.group(2) if m.group(2) else "")
    m = _SIG_RE.search(text)
    return m.group(0) if m else (text[:60] or "unknown")


_INTRODUCED_CACHE: dict = {}


def check_introduced(code):
    """When the check that raised `code` first existed: the commit time of the
    first commit whose diff added that token under python/ (git pickaxe, ~1s,
    cached), as naive local time like planning_runs. None when the token is not
    an error code or git cannot say - and None never excuses a failure."""
    if not code or not _SIG_RE.fullmatch(code):
        return None
    if code not in _INTRODUCED_CACHE:
        when = None
        try:
            out = subprocess.check_output(
                ["git", "-C", ROOT, "log", "-S" + code, "--reverse", "--format=%cI", "--", "python"],
                text=True, stderr=subprocess.DEVNULL).split()
            if out:
                import datetime as _dt
                when = _dt.datetime.fromisoformat(out[0]).astimezone().replace(tzinfo=None)
        except Exception:
            when = None
        _INTRODUCED_CACHE[code] = when
    return _INTRODUCED_CACHE[code]


def _load_env():
    # .env is gitignored, so a worktree at another commit has none: credentials
    # come from REPLAY_GATE_HOME (the replay_gate convention), else this repo.
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.environ.get("REPLAY_GATE_HOME") or ROOT, ".env"))


def _conn():
    import mysql.connector
    c = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
        port=int(os.getenv("MYSQL_PORT") or 3306))
    c.autocommit = True
    return c


# --------------------------------------------------------------------------
# The worker: one scratch draft through the real pipeline, in its own process.
# --------------------------------------------------------------------------
def worker(scratch: str) -> int:
    # The server's import order: python/ first, then python/client_intake_and_finmo
    # APPENDED (python/api.py:69) - so bare and package module names resolve as
    # they do in production. The repo root carries client_statements_output_excel.
    sys.path.insert(0, ROOT)
    sys.path.insert(0, PY)
    sys.path.append(os.path.join(PY, "client_intake_and_finmo"))
    _load_env()
    os.environ["GPT_RESPONSE_LOCK"] = "1"
    # Fail-safe: strict unless the driver EXPLICITLY asked to record.
    os.environ["GPT_RESPONSE_LOCK_STRICT"] = "" if os.environ.get("REPLAY_RECORD") == "1" else "1"
    import api_handlers.intake_consult as ic
    for k in EMAIL_KEYS:
        os.environ[k] = ""
    from intake_submission import get_mysql_connection  # the handler's own import

    out = {"scratch": scratch}
    conn = get_mysql_connection()
    t0 = time.time()
    try:
        ic._set_active_openai_deadline(None)
        result = ic._run_planning_system_for_draft(
            conn=conn, draft_id=scratch, lifecycle_mode="start", planning_run_id=None)
        from client_intake_and_finmo.post_intake_contracts.enforcement import (
            SIDE_CONSUMER, validate_solver_output_at_boundary)
        validate_solver_output_at_boundary(result, side=SIDE_CONSUMER)
        # The handler's acceptance gate - the REAL one; it writes only the
        # scratch run's acceptance_verdict_json. (The restructure stage the
        # handler fires on a non-viable verdict is NOT replayed.)
        from client_intake_and_finmo.post_intake_acceptance import verify_run_acceptance
        prj = result.get("planning_run_json") if isinstance(result, dict) else None
        acc_run = str(prj.get("planning_run_id") or "").strip() if isinstance(prj, dict) else ""
        acc = verify_run_acceptance(
            conn, draft_id=str((result or {}).get("draft_id") or scratch),
            planning_run_id=acc_run or None) or {}
        out["acceptance_passed"] = bool(acc.get("passed"))
        out["acceptance_failed_checks"] = [
            str((c.get("name") or c.get("check") or c.get("id")) if isinstance(c, dict) else c)
            for c in (acc.get("failed_checks") or [])][:10]
        out.update(outcome="completed", detail="")
    except BaseException as exc:  # the verdict IS the exception
        # detail is str(exc) alone - the same text a real run stores as
        # planning_runs.failure_reason - so the two sign alike.
        out.update(outcome="failed", error_type=type(exc).__name__, detail=str(exc)[:600])
    out["pipeline_seconds"] = round(time.time() - t0, 1)

    misses = []
    for name in ("openai_http", "client_intake_and_finmo.openai_http"):
        mod = sys.modules.get(name)
        misses.extend(list(getattr(mod, "_STRICT_MISSES", None) or []))
    out["gpt_miss_count"] = len(misses)
    out["gpt_misses"] = misses[:5]

    try:  # fresh connection: a REPEATABLE-READ snapshot opened earlier reads nothing new
        rc = get_mysql_connection()
        cur = rc.cursor(dictionary=True)
        cur.execute(
            "SELECT planning_run_id, run_status, failure_reason, acceptance_verdict_json "
            "FROM planning_runs WHERE draft_id=%s ORDER BY created_at DESC LIMIT 1", (scratch,))
        row = cur.fetchone() or {}
        out["planning_run_id"] = row.get("planning_run_id")
        out["run_status"] = row.get("run_status")
        # The usage ledger records every use, replay or live, keyed by draft
        # (run_vitals misses calls made through the bare openai_http module).
        cur.execute("SELECT COUNT(*) n FROM post_intake_gpt_response_usage WHERE draft_id=%s",
                    (scratch,))
        out["gpt_uses"] = int((cur.fetchone() or {}).get("n") or 0)
        # A LIVE answer is saved stamped with the draft that asked it first.
        cur.execute("SELECT COUNT(*) n FROM post_intake_gpt_response_store WHERE draft_id=%s",
                    (scratch,))
        out["gpt_live"] = int((cur.fetchone() or {}).get("n") or 0)
        rc.close()
    except Exception as exc:
        out["readback_error"] = str(exc)[:200]
    print("REPLAY_RESULT " + json.dumps(out, default=str))
    sys.stdout.flush()
    return 0


# --------------------------------------------------------------------------
# The driver.
# --------------------------------------------------------------------------
def _acceptance_passed(raw):
    """True / False from a stored acceptance verdict; None when there is none."""
    try:
        acc = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None
    if not isinstance(acc, dict) or "passed" not in acc:
        return None
    return bool(acc.get("passed"))


def select_sources(conn, n, only):
    cur = conn.cursor(dictionary=True)
    if only:
        rows = []
        for prefix in only:
            cur.execute("SELECT draft_id FROM intake_consult_drafts WHERE draft_id LIKE %s",
                        (prefix.strip() + "%",))
            hit = cur.fetchall()
            if len(hit) != 1:
                raise SystemExit("SETUP FAILED: --source %s matched %d drafts" % (prefix, len(hit)))
            rows.append(hit[0]["draft_id"])
        ids = rows
    else:
        cur.execute(
            "SELECT p.draft_id, MAX(COALESCE(p.started_at, p.created_at)) last_run "
            "FROM planning_runs p JOIN intake_consult_drafts d ON d.draft_id = p.draft_id "
            "WHERE d.client_id NOT LIKE %s AND d.client_id NOT LIKE %s "
            "GROUP BY p.draft_id ORDER BY last_run DESC LIMIT %s",
            (SCRATCH_PREFIX + "%", "rgate%", int(n)))
        ids = [r["draft_id"] for r in cur.fetchall()]
    sources = []
    for d in ids:
        cur.execute("SELECT business_name FROM intake_consult_drafts WHERE draft_id=%s", (d,))
        name = (cur.fetchone() or {}).get("business_name") or ""
        cur.execute(
            "SELECT run_status, failure_reason, COALESCE(started_at, created_at) run_started, "
            "acceptance_verdict_json FROM planning_runs WHERE draft_id=%s "
            "ORDER BY COALESCE(started_at, created_at) DESC LIMIT 1", (d,))
        run = cur.fetchone() or {}
        ok = str(run.get("run_status") or "") == "completed"
        detail = run.get("failure_reason") or ("" if ok else "unfinished:%s" % run.get("run_status"))
        sources.append({"draft_id": d, "name": str(name), "status": "completed" if ok else "failed",
                        "detail": str(detail or ""), "signature": None if ok else signature(detail),
                        "run_started": run.get("run_started"),
                        "acceptance_passed": _acceptance_passed(run.get("acceptance_verdict_json"))})
    return sources


def clone(conn, source_id: str) -> str:
    cur = conn.cursor()
    cur.execute(
        "SELECT column_name, is_nullable, column_default FROM information_schema.columns "
        "WHERE table_schema=DATABASE() AND table_name='intake_consult_drafts' "
        "ORDER BY ordinal_position")
    cols = [(str(a), str(b), c) for a, b, c in cur.fetchall()]
    new_id = uuid.uuid4().hex
    client_id = (SCRATCH_PREFIX + uuid.uuid4().hex)[:20]
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    exprs, params = [], []
    for name, nullable, default in cols:
        if name == "draft_id":
            exprs.append("%s"); params.append(new_id)
        elif name == "client_id":
            exprs.append("%s"); params.append(client_id)
        elif name == "planning_run_json":
            exprs.append("%s"); params.append(json.dumps(INTAKE_COMPLETE))
        elif name == "status":
            exprs.append("'completed'")
        elif name == "active_focus":
            exprs.append("'done'")
        elif name in ("created_at", "updated_at", "completed_at"):
            exprs.append("%s"); params.append(now)
        elif name in RESET_COLUMNS or name.startswith("planning_"):
            if nullable == "YES":
                exprs.append("NULL")
            elif default is not None:
                exprs.append("DEFAULT(`%s`)" % name)
            else:
                exprs.append("`%s`" % name)
        else:
            exprs.append("`%s`" % name)
    sql = ("INSERT INTO intake_consult_drafts (%s) SELECT %s FROM intake_consult_drafts "
           "WHERE draft_id = %%s" % (", ".join("`%s`" % c[0] for c in cols), ", ".join(exprs)))
    cur.execute(sql, params + [source_id])
    if cur.rowcount != 1:
        raise SystemExit("SETUP FAILED: clone of %s inserted %s rows" % (source_id, cur.rowcount))
    return new_id


def sweep(conn, scratch_ids) -> int:
    cur = conn.cursor()
    cur.execute(
        "SELECT table_name, GROUP_CONCAT(column_name) FROM information_schema.columns "
        "WHERE table_schema=DATABASE() AND column_name IN ('draft_id','planning_run_id') "
        "GROUP BY table_name")
    tables = {str(t): set(str(c).split(",")) for t, c in cur.fetchall()}
    removed = 0
    for d in scratch_ids:
        cur.execute("SELECT client_id FROM intake_consult_drafts WHERE draft_id=%s", (d,))
        row = cur.fetchone()
        if row is None or not str(row[0] or "").startswith(SCRATCH_PREFIX):
            continue  # never touch a draft that is not ours
        cur.execute("SELECT planning_run_id FROM planning_runs WHERE draft_id=%s", (d,))
        runs = [r[0] for r in cur.fetchall()]
        for t, cols in sorted(tables.items()):
            if t in NEVER_SWEEP or t == "intake_consult_drafts":
                continue
            if "draft_id" in cols:
                cur.execute("DELETE FROM `%s` WHERE draft_id = %%s" % t, (d,))
                removed += cur.rowcount
            if "planning_run_id" in cols and runs:
                cur.execute("DELETE FROM `%s` WHERE planning_run_id IN (%s)"
                            % (t, ",".join(["%s"] * len(runs))), runs)
                removed += cur.rowcount
        cur.execute("DELETE FROM intake_consult_drafts WHERE draft_id=%s AND client_id LIKE %s",
                    (d, SCRATCH_PREFIX + "%"))
        removed += cur.rowcount
    return removed


def run_worker(scratch: str, timeout: int, record: bool = False) -> dict:
    env = dict(os.environ)
    env.update({"GPT_RESPONSE_LOCK": "1", "PYTHONUTF8": "1",
                "GPT_RESPONSE_LOCK_STRICT": "" if record else "1",
                "REPLAY_RECORD": "1" if record else "0",
                "GPT_RESPONSE_LOCK_MISS_DIR": os.path.join(ROOT, "_runtime", "replay_misses",
                                                           scratch[:8])})
    for k in EMAIL_KEYS:
        env[k] = ""
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, "%s.log" % scratch[:8])
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable, "-X", "utf8", os.path.abspath(__file__),
                            "--worker", scratch], cwd=ROOT, env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"verdict_raw": "ERROR", "outcome": "failed", "log": log_path,
                "detail": "worker timeout after %ss" % timeout, "elapsed": round(time.time() - t0, 1)}
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(r.stdout + "\n--- stderr ---\n" + r.stderr)
    line = next((l for l in reversed(r.stdout.splitlines()) if l.startswith("REPLAY_RESULT ")), None)
    if line is None:
        return {"verdict_raw": "ERROR", "outcome": "failed", "log": log_path,
                "detail": "worker exit %s, no result; tail: %s" % (
                    r.returncode, (r.stdout + r.stderr)[-500:]),
                "elapsed": round(time.time() - t0, 1)}
    out = json.loads(line[len("REPLAY_RESULT "):])
    out["elapsed"] = round(time.time() - t0, 1)
    out["log"] = log_path
    return out


def judge(src: dict, rep: dict, blessed: dict, introduced=None) -> str:
    if rep.get("verdict_raw") == "ERROR":
        return "ERROR"
    if rep.get("gpt_miss_count"):
        return "GPT_MISS"
    if rep.get("outcome") == "completed":
        if src.get("acceptance_passed") is True and rep.get("acceptance_passed") is False:
            # The run completes, but the plan it makes no longer passes the
            # acceptance gate its source passed: the draft got worse - unless
            # every check it now fails is newer than the source run.
            checks = rep.get("acceptance_failed_checks") or []
            started = src.get("run_started")
            whens = [introduced(c) if introduced else None for c in checks]
            if checks and started is not None and all(w is not None and w > started for w in whens):
                return "POSTDATES"
            # A drop explained by a LATER ruling (not a newer check) is
            # baselined by hand, with its evidence, on the exact check set.
            b = blessed.get(src["draft_id"]) or {}
            if checks and sorted(b.get("acceptance_failed_checks") or []) == sorted(checks):
                return "BLESSED"
            return "ACCEPTANCE_DROP"
        return "PASS" if src["status"] == "completed" else "FIXED"
    rsig = signature(rep.get("detail"))
    b = blessed.get(src["draft_id"]) or {}
    if b.get("signature") == rsig:
        return "BLESSED"
    if src["status"] != "completed" and src["signature"] == rsig:
        return "KNOWN"
    # Nick 2026-09-11: a draft failing a check that did not exist when its
    # original run ran is an old draft meeting a new rule, not a regression.
    # Only a draft that gets worse blocks a push.
    when = introduced(rsig.split(":", 1)[0]) if introduced else None
    started = src.get("run_started")
    if when is not None and started is not None and when > started:
        return "POSTDATES"
    return "REGRESSION" if src["status"] == "completed" else "NEW_FAILURE"


def _git(*args) -> str:
    try:
        return subprocess.check_output(["git", "-C", ROOT] + list(args), text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "?"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drafts", type=int, default=10)
    ap.add_argument("--jobs", type=int, default=0, help="parallel workers (default: one per draft)")
    ap.add_argument("--source", action="append", default=[], help="replay this draft (id prefix)")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--record", action="store_true",
                    help="ALLOW LIVE GPT on a miss and save the answer - costs money, ask first")
    ap.add_argument("--sweep-orphans", action="store_true")
    ap.add_argument("--worker", default="")
    a = ap.parse_args()
    if a.worker:
        return worker(a.worker)

    _load_env()
    conn = _conn()
    if a.sweep_orphans:
        cur = conn.cursor()
        cur.execute("SELECT draft_id FROM intake_consult_drafts WHERE client_id LIKE %s",
                    (SCRATCH_PREFIX + "%",))
        ids = [r[0] for r in cur.fetchall()]
        print("swept %d rows across %d orphan scratch drafts" % (sweep(conn, ids), len(ids)))
        return 0

    sources = select_sources(conn, a.drafts, a.source)
    if not sources:
        print("SETUP FAILED: no drafts to replay")
        return 2
    try:
        with open(BLESSED_PATH, encoding="utf-8") as fh:
            blessed = json.load(fh)
    except FileNotFoundError:
        blessed = {}
    dirty = [l for l in _git("status", "--porcelain", "--", "python", "client_statements_output_excel").splitlines() if l.strip()]
    print("POST-INTAKE REPLAY  build %s%s  drafts %d  %s"
          % (_git("rev-parse", "--short", "HEAD"), " +%d uncommitted" % len(dirty) if dirty else "",
             len(sources), "RECORD MODE - live GPT allowed on a miss" if a.record else "strict GPT lock"))

    pairs, results = [], []
    t0 = time.time()
    try:
        for s in sources:
            pairs.append((s, clone(conn, s["draft_id"])))
        jobs = a.jobs or len(pairs)
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
            futs = {ex.submit(run_worker, scratch, a.timeout, a.record): (s, scratch)
                    for s, scratch in pairs}
            for f in as_completed(futs):
                s, scratch = futs[f]
                try:
                    rep = f.result()
                except Exception as exc:
                    rep = {"verdict_raw": "ERROR", "outcome": "failed", "detail": repr(exc)[:300]}
                verdict = judge(s, rep, blessed, check_introduced)
                results.append((s, rep, verdict))
                print("  %-12s %-9s %6.0fs  %s %-26s  source %-9s  %s"
                      % (verdict, rep.get("outcome"), rep.get("elapsed") or 0, s["draft_id"][:8],
                         s["name"][:26], s["status"],
                         (rep.get("detail") or "")[:110] if rep.get("outcome") != "completed"
                         else "gpt %s uses (%s live), acceptance %s" % (
                             rep.get("gpt_uses"), rep.get("gpt_live"), rep.get("acceptance_passed"))))
                sys.stdout.flush()
    finally:
        if not a.keep and pairs:
            print("  swept %d scratch rows" % sweep(conn, [p[1] for p in pairs]))
    wall = time.time() - t0

    blocking = [r for r in results if r[2] in BLOCKING]
    for s, rep, verdict in results:
        if verdict in ("GPT_MISS",):
            for m in rep.get("gpt_misses") or []:
                print("  GPT_MISS %s: %s" % (s["draft_id"][:8], m[:200]))
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        json.dump({"build": _git("rev-parse", "HEAD"), "uncommitted": dirty, "wall_seconds": round(wall, 1),
                   "results": [{"source": s, "replay": rep, "verdict": v} for s, rep, v in results]},
                  fh, indent=1, default=str)
    counts = {}
    for _, _, v in results:
        counts[v] = counts.get(v, 0) + 1
    print("REPLAY: %s in %.0fs - %s" % (
        "DO NOT SHIP" if blocking else "SAFE TO SHIP", wall,
        ", ".join("%d %s" % (n, v) for v, n in sorted(counts.items()))))
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
