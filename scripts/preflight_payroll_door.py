"""PREFLIGHT - the payroll payload door, checked in seconds before any paid
run (Nick 2026-09-11: "im tired of spending money on long runs only to find
that something dumb is broken at the end").

Two live system runs were lost today at submit to defects a free, offline
check catches instantly:
  - the reconciliation stamp carried an unapproved text label
    (stated_source) - Ferriday & Blythe d44f717c failed at payload build;
  - the anchor-AUTHORED block (the ruling-1 path) had never run live and
    could not pass the validator at all.
Both were invisible to pins that called the stamping functions directly and
never ran the real validator on a payload carrying the result.

Checks, in order:
  1. PINS   - the payroll / router / writing-door unit modules.
  2. REPLAY - for the most recent stored drafts carrying a payroll payload,
              the post-author door exactly as the live builder runs it:
              rest-of-team anchor -> stated-payroll reconciliation -> the
              REAL payload validator; then the anchor-authored path on each
              draft's own key people (a stated pool, no supporting roster).

A draft counts as BROKEN only when its payload validated as stored and fails
after the replay - so payloads from before today's rules never raise false
alarms. The reconciliation STOPPING an out-of-band draft is the gate doing its
job: reported, not a failure. Any unexpected exception is a failure.

Read-only: no DB writes, no GPT calls. Exit 0 = door sound, 1 = broken.
Usage: python scripts/preflight_payroll_door.py [--drafts N] [--no-pins]
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "python")):
    if p not in sys.path:
        sys.path.insert(0, p)

PIN_MODULES = [
    "tests.test_payroll_stamps_pass_the_real_validator",
    "tests.test_anchor_authors_and_reconciles",
    "tests.test_reconciliation_reads_the_client",
    "tests.test_rest_of_team_anchor",
    "tests.test_rest_of_team_is_not_a_plug",
    "tests.test_headcount_is_stated_not_counted",
    "tests.test_payroll_commit_path_fact_band",
    "tests.test_wage_floor_honors_stated",
    "tests.test_group_rows_count_per_person",
    "tests.test_key_person_occupation_matcher",
    "tests.test_concurrent_run_isolation",
    "tests.test_intake_rest_of_team_and_ops_guard",
    "tests.test_router_unresolved_and_inner_shape",
    "tests.test_qa_payroll_launch_band",
]
GATE_STOP = "payroll_authored_off_stated_payroll"
SYNTHETIC_POOL = 250000.0


def _jl(v):
    if isinstance(v, dict):
        return v
    try:
        return json.loads(v) if v else {}
    except Exception:
        return None


def run_pins() -> bool:
    t0 = time.time()
    r = subprocess.run([sys.executable, "-X", "utf8", "-m", "unittest"] + PIN_MODULES,
                       cwd=ROOT, capture_output=True, text=True)
    tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
    ok = r.returncode == 0
    print("[pins] %s in %.1fs - %s" % ("OK" if ok else "FAILED", time.time() - t0,
                                       " | ".join(tail)))
    if not ok:
        print((r.stdout + r.stderr)[-3000:])
    return ok


def _reconcile(S, payload, anchor, fin):
    """Returns 'reconciled' | 'gate_stopped' | 'no_stated' ; raises on any
    other exception."""
    try:
        S._stamp_stated_payroll_reconciliation(payload, anchor, financials_json=fin)
    except Exception as exc:  # the fail-fast raises after stamping
        if GATE_STOP in str(exc):
            return "gate_stopped"
        raise
    return "reconciled" if "stated_payroll_reconciliation" in payload else "no_stated"


def replay(n: int) -> bool:
    import mysql.connector
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    from client_intake_and_finmo.post_intake_headcount import schedule as S
    from client_intake_and_finmo.post_intake_headcount.lookup import (
        validate_payroll_headcount_payload as V)

    conn = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"))
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT draft_id, business_name, payroll_headcount, people_json, "
        "financials_json FROM intake_consult_drafts WHERE payroll_headcount "
        "IS NOT NULL AND payroll_headcount <> '' AND payroll_headcount <> '{}' "
        "ORDER BY updated_at DESC LIMIT %s", (int(n),))
    drafts = cur.fetchall()
    conn.close()

    t0 = time.time()
    tally = {"replayed": 0, "skipped_legacy": 0, "reconciled": 0,
             "gate_stopped": 0, "no_stated": 0, "authored_ok": 0}
    broken = []
    stopped = []
    for d in drafts:
        tag = "%s %s" % (d["draft_id"][:8], str(d["business_name"] or "")[:28])
        stored = _jl(d["payroll_headcount"])
        people = _jl(d["people_json"]) or {}
        fin = _jl(d["financials_json"]) or {}
        if not isinstance(stored, dict) or not stored.get("rows"):
            tally["skipped_legacy"] += 1
            continue
        base = copy.deepcopy(stored)
        for k in ("stated_payroll_reconciliation", "rest_of_team_anchor"):
            base.pop(k, None)
        if V(copy.deepcopy(base)):
            tally["skipped_legacy"] += 1      # predates today's schema rules
            continue
        tally["replayed"] += 1
        rows = base["rows"]
        keys = [r for r in rows if r.get("staffing_class") == "key_person"]
        sup = [r for r in rows if r.get("staffing_class") != "key_person"]
        horizon = max(int(r.get("quarter_index") or 0) for r in rows)
        try:
            # (a) the live door on this draft's own numbers
            p = copy.deepcopy(base)
            new_sup, anchor = S._anchor_supporting_rows_to_stated_pool(
                copy.deepcopy(sup), people_json=people, key_people_rows=keys,
                horizon=horizon)
            p["rows"] = keys + new_sup
            if anchor is not None:
                p["rest_of_team_anchor"] = anchor
            outcome = _reconcile(S, p, anchor, fin)
            tally[outcome] += 1
            if outcome == "gate_stopped":
                rec = p.get("stated_payroll_reconciliation") or {}
                stopped.append((tag, rec.get("ratio"), rec.get("stated_total_payroll"),
                                rec.get("authored_q1_annualized"),
                                (anchor or {}).get("anchor_disposition")))
            errs = V(p)
            if errs:
                broken.append((tag, "live door", errs[:3]))
                continue
            # (b) the anchor-authored path on this draft's own key people
            q = copy.deepcopy(base)
            auth, anchor2 = S._anchor_supporting_rows_to_stated_pool(
                [], people_json={"rest_of_team_payroll_year1": SYNTHETIC_POOL},
                key_people_rows=keys, horizon=horizon)
            q["rows"] = keys + auth
            if anchor2 is not None:
                q["rest_of_team_anchor"] = anchor2
            named = sum(float(r.get("ending_fte") or 0) * float(r.get("annual_wage") or 0)
                        for r in keys if int(r.get("quarter_index") or 0) == 1)
            _reconcile(S, q, anchor2, {"current_payroll": named + SYNTHETIC_POOL})
            errs = V(q)
            if errs:
                broken.append((tag, "authored block", errs[:3]))
                continue
            tally["authored_ok"] += 1
        except Exception as exc:
            broken.append((tag, "exception", ["%s: %s" % (type(exc).__name__, str(exc)[:160])]))

    print("[replay] %d drafts in %.1fs - replayed %d (skipped %d from before today's "
          "schema), live door: %d reconciled / %d gate-stopped / %d no stated payroll; "
          "authored path valid on %d"
          % (len(drafts), time.time() - t0, tally["replayed"], tally["skipped_legacy"],
             tally["reconciled"], tally["gate_stopped"], tally["no_stated"],
             tally["authored_ok"]))
    for tag, ratio, stated, authored, disp in stopped:
        print("  STOPPED %-38s ratio %s  stated %s  authored %s  (%s)"
              % (tag, ratio, stated, authored, disp))
    for tag, where, errs in broken:
        print("  BROKEN  %-38s %-15s %s" % (tag, where, "; ".join(str(e) for e in errs)))
    return not broken


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drafts", type=int, default=40)
    ap.add_argument("--no-pins", action="store_true")
    a = ap.parse_args()
    ok = True
    if not a.no_pins:
        ok = run_pins() and ok
    ok = replay(a.drafts) and ok
    print("PREFLIGHT: %s" % ("PASS - payroll door sound" if ok
                             else "FAIL - do not start a paid run"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
