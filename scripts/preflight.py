"""PREFLIGHT - every submit-path door that can be checked in seconds, checked
at stack start and on every push that touches post-intake (Nick 2026-09-11:
"It caught a field name in 0.6 seconds; whatever else can be checked that
cheaply at stack start should be. That's the class of mistake I'm tired of
paying 35 minutes for.")

Stages, cheapest first. Every stage runs even after one fails, so one report
names everything:
  1. SOURCE   - no control characters in tracked Python/JS (the heredoc class:
                a backspace where \\b belonged compiles and matches nothing);
                every writing renderer .js parses (node --check); every
                post-intake module and the intake handler import, in the
                server's own import order.
  2. PINS     - the payroll / router / boundary / replay-gate unit modules.
  3. BOUNDARY - for the most recent drafts that reached post-intake, the run's
                entry exactly as a run does it: the entry recalc's pure half
                (_entry_recalc_changes) -> the INTAKE->POST_INTAKE contract on
                the payload the run builds (intake_draft_gate_payload). Both
                are the functions the run itself calls. A draft whose original
                run got past the boundary must still get past it.
  4. PAYROLL  - the payroll payload door on the same drafts: anchor ->
                reconciliation -> the REAL validator, then the anchor-authored
                path on each draft's own key people. A draft counts as BROKEN
                only when its payload validated as stored and fails after the
                replay. The reconciliation STOPPING an out-of-band draft is the
                gate doing its job: listed, not a failure.

Read-only: no DB writes, no GPT calls. Exit 0 = doors sound, 1 = broken.
The ten-draft full replay (scripts/replay_post_intake.py, ~10 min) is a
deliberate command, not part of this.
Usage: python scripts/preflight.py [--drafts N] [--no-pins]
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "python")

#: QUARANTINED BY THE 2026-09-25 REVERT (Nick's ruling). The four intake files
#: were reverted to 7943c191, 12 September - the last state with repeated
#: evidence of completing runs end to end (16 completed runs and 7 delivered
#: plans between 10 and 15 September; ZERO in the ten days after). The pins
#: below test code that no longer exists, so they are commented out IN PLACE
#: rather than deleted: the file they pin is one `git checkout` away, and when
#: any of this behaviour is rebuilt its pin is already written.
#:
#: TWENTY are the capacity work that was reverted on purpose. TWELVE are
#: collateral - they pinned NON-capacity behaviour that happened to live in the
#: same four files: a lever never moving her revenue, a client never hearing a
#: field name, the current-revenue protections, the one-reader recording, and
#: the run-failure/artifact recording. Those are real losses, named here so
#: nobody has to rediscover them.
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
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_router_unresolved_and_inner_shape",
    "tests.test_qa_payroll_launch_band",
    "tests.test_p3_40_contract_5_intake_draft",
    "tests.test_open_hold_keeps_intake_open",
    "tests.test_restructure_stays_the_clients_business",
    "tests.test_a_stated_interest_rate_runs",
    "tests.test_payroll_column_matches_the_model_that_ships",
    "tests.test_prepush_gate",
    "tests.test_people_stage_merge_and_hold_retire",
    "tests.test_preflight_doors",
    "tests.test_gpt_lock_strict_replay",
    "tests.test_post_intake_replay_gate",
    "tests.test_intake_persona_gate",
    "tests.test_conversation_defects_20260911",
    # A PIN THAT IS NOT IN THIS LIST DOES NOT RUN (2026-09-13). Eight pin
    # files written across one day - 92 tests - were never registered here,
    # so preflight said PASS without executing one of them. The same shape as
    # the filter that was written and never called, one level up.
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_the_ask_is_wired_not_just_written",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_concurrent_capacity_reaches_the_model",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_a_driver_names_its_line",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_a_restatement_cannot_erase_a_capacity",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_a_restatement_keeps_every_key_the_row_held",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_a_stated_annual_count_survives_a_restatement",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_every_row_of_a_line_has_one_shape",
    "tests.test_a_derived_figure_is_not_its_own_explanation",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_a_derived_figure_is_never_read_back",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_the_router_keeps_her_words_and_reads_its_numbers",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_every_interpretation_is_recorded",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_the_shadow_reads_every_turn_and_changes_nothing",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_every_reader_of_her_words_is_counted",
    "tests.test_the_one_reader_report_counts_three_states",
    "tests.test_a_stored_figure_is_never_doubled",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_current_revenue_holds_only_what_she_said",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_a_lever_never_moves_her_revenue",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_a_reader_that_is_not_sure_does_not_write",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_an_expectation_is_not_current_revenue",
    "tests.test_two_copies_of_one_fact_agree",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_a_period_count_follows_its_cadence",
    "tests.test_a_receipt_says_what_the_store_kept",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_a_readback_offers_the_field_it_asked_about",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_the_app_says_what_it_asked",
    "tests.test_a_census_payroll_is_carried_in_dollars",
    "tests.test_a_client_never_reads_an_identifier",
    "tests.test_a_skip_is_not_a_pass",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_a_stage_owns_its_fields_and_her_weeks",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_her_working_year_is_not_her_turns",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_a_figure_that_cannot_mean_that_is_asked_about",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_the_same_door_gives_one_answer",
    "tests.test_the_bridge_loses_nothing_and_doubles_nothing",
    "tests.test_an_issue_with_an_unknown_field_is_refused",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_a_volunteered_figure_is_never_dropped",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_capacity_fixes_hold_for_any_business",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_a_guard_revert_never_erases_a_row_key",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_the_contract_ask_says_what_it_means",
    "tests.test_a_receipt_names_only_what_the_client_said",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_the_annual_pair_has_a_home",
    "tests.test_a_receipt_says_something_new_before_the_question",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_a_client_never_hears_a_field_name",
    "tests.test_capacity_pair_is_arithmetic",
    "tests.test_gate_reports_stale_recordings",
    "tests.test_artifact_endpoints",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_delivered_artifacts",
    # QUARANTINED BY THE 12-SEPT REVERT: "tests.test_system_run_failure_is_recorded",
    "tests.test_revenue_drivers_survive_the_real_writer",
]
GATE_STOP = "payroll_authored_off_stated_payroll"
SYNTHETIC_POOL = 250000.0
SOURCE_DIRS = ("python", "scripts", "tests", "replay_gate", "client_statements_output_excel")
RENDER_DIR = "python/writing_phase_v2/render/"
_CTRL = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")
IMPORT_CORE = ("finmo_bridge", "quarter_grid", "model_inputs", "openai_http")
# First-submit state at the boundary: planning_context_summary_json is a
# post-intake output, empty when a draft is first submitted (the replay gate
# resets it the same way).
BOUNDARY_RESET = ("planning_context_summary_json",)
DRAFT_COLUMNS = ("draft_id", "business_name", "payroll_headcount", "people_json",
                 "financials_json", "financials_year1_json", "operating_model_json",
                 "target_market_json", "marketing_model_json", "fulfillment_json",
                 "planning_context_summary_json")


def _server_path():
    """The server's import order (python/api.py): python/ first, then
    python/client_intake_and_finmo APPENDED; the repo root carries
    client_statements_output_excel."""
    for p in (ROOT, PY):
        if p not in sys.path:
            sys.path.insert(0, p)
    extra = os.path.join(PY, "client_intake_and_finmo")
    if extra not in sys.path:
        sys.path.append(extra)


def _jl(v):
    if isinstance(v, dict):
        return v
    try:
        return json.loads(v) if v else {}
    except Exception:
        return None


# --------------------------------------------------------------------------
# 1. SOURCE
# --------------------------------------------------------------------------
def import_smoke() -> int:
    """Runs in its own process (--import-smoke) so nothing this script already
    imported can hide a broken import."""
    _server_path()
    import importlib
    import pkgutil

    failures = []
    names = ["api_handlers.intake_consult"]
    import client_intake_and_finmo as pkg
    for m in pkgutil.walk_packages(pkg.__path__, "client_intake_and_finmo.",
                                   onerror=lambda n: failures.append("discovery failed: %s" % n)):
        if ".post_intake" in m.name or m.name.rsplit(".", 1)[-1] in IMPORT_CORE:
            names.append(m.name)
    for name in names:
        try:
            importlib.import_module(name)
        except Exception as exc:
            failures.append("import %s: %s: %s" % (name, type(exc).__name__, str(exc)[:160]))
    for f in failures:
        print(f)
    print("imported %d post-intake modules, %d failed" % (len(names), len(failures)))
    return 1 if failures else 0


def run_source() -> bool:
    t0 = time.time()
    problems = []
    listed = subprocess.check_output(["git", "-C", ROOT, "ls-files", "--"] + list(SOURCE_DIRS),
                                     text=True).splitlines()
    code_files = [f for f in listed if f.endswith((".py", ".js"))]
    for f in code_files:
        try:
            with open(os.path.join(ROOT, f), "rb") as fh:
                m = _CTRL.search(fh.read())
        except OSError:
            continue
        if m:
            problems.append("control character 0x%02x in %s" % (m.group(0)[0], f))
    node = shutil.which("node")
    js = [f for f in code_files if f.startswith(RENDER_DIR) and f.endswith(".js")]
    if node:
        for f in js:
            r = subprocess.run([node, "--check", os.path.join(ROOT, f)], capture_output=True, text=True)
            if r.returncode != 0:
                problems.append("%s does not parse: %s"
                                % (f, ((r.stderr or "").strip().splitlines() or ["?"])[-1][:160]))
    else:
        print("[source] node not found - renderer JS not checked")
    r = subprocess.run([sys.executable, "-X", "utf8", os.path.abspath(__file__), "--import-smoke"],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    smoke = (r.stdout or "").strip().splitlines()
    if r.returncode != 0:
        problems.extend([l for l in smoke if not l.startswith("imported ")][:8]
                        or [(r.stderr or "import smoke crashed").strip()[-300:]])
    summary = next((l for l in smoke if l.startswith("imported ")), "import smoke gave no summary")
    ok = not problems
    print("[source] %s in %.1fs - %d files free of control characters, %d renderer JS parsed, %s"
          % ("OK" if ok else "FAILED", time.time() - t0, len(code_files),
             len(js) if node else 0, summary))
    for p in problems:
        print("  BROKEN  " + p)
    return ok


# --------------------------------------------------------------------------
# 2. PINS
# --------------------------------------------------------------------------
def run_pins() -> bool:
    t0 = time.time()
    r = subprocess.run([sys.executable, "-X", "utf8", "-m", "unittest"] + PIN_MODULES,
                       cwd=ROOT, capture_output=True, text=True)
    tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
    ok = r.returncode == 0
    print("[pins] %s in %.1fs - %s" % ("OK" if ok else "FAILED", time.time() - t0, " | ".join(tail)))
    if not ok:
        print((r.stdout + r.stderr)[-3000:])
    return ok


# --------------------------------------------------------------------------
# The drafts both door stages read: the N most recent that reached post-intake.
# --------------------------------------------------------------------------
def load_drafts(n: int):
    import mysql.connector
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    conn = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"))
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT " + ", ".join("d.%s" % c for c in DRAFT_COLUMNS) + ", r.run_status, r.failure_reason "
        "FROM intake_consult_drafts d "
        "JOIN (SELECT draft_id, MAX(COALESCE(started_at, created_at)) last_run "
        "      FROM planning_runs GROUP BY draft_id) p ON p.draft_id = d.draft_id "
        "LEFT JOIN planning_runs r ON r.draft_id = d.draft_id "
        "     AND COALESCE(r.started_at, r.created_at) = p.last_run "
        "WHERE d.client_id NOT LIKE 'rpgate%%' AND d.client_id NOT LIKE 'rgate%%' "
        "ORDER BY p.last_run DESC LIMIT %s", (int(n),))
    seen, drafts = set(), []
    for row in cur.fetchall():
        if row["draft_id"] not in seen:
            seen.add(row["draft_id"])
            drafts.append(row)
    conn.close()
    return drafts


def _tag(d):
    return "%s %s" % (d["draft_id"][:8], str(d.get("business_name") or "")[:28])


# --------------------------------------------------------------------------
# 3. BOUNDARY
# --------------------------------------------------------------------------
def check_boundary(drafts) -> bool:
    _server_path()
    import api_handlers.intake_consult as ic
    from client_intake_and_finmo.post_intake_contracts.enforcement import (
        SIDE_CONSUMER, validate_intake_draft_at_boundary)
    from client_intake_and_finmo.post_intake_initial_grid.runner import intake_draft_gate_payload

    t0 = time.time()
    tally = {"passed": 0, "fixed": 0, "known": 0, "recalc_changed": 0}
    broken = []
    for d in drafts:
        was_stopped_here = str(d.get("failure_reason") or "").startswith("INTAKE->POST_INTAKE")
        row = dict(d)
        for col in BOUNDARY_RESET:
            row[col] = None
        try:
            changes = ic._entry_recalc_changes(row)
        except Exception as exc:
            broken.append((_tag(d), "entry recalc", "%s: %s" % (type(exc).__name__, str(exc)[:200])))
            continue
        if changes:  # the run persists these and re-reads the draft
            tally["recalc_changed"] += 1
            row.update({k: json.dumps(v) for k, v in changes.items()})
        try:
            validate_intake_draft_at_boundary(
                intake_draft_gate_payload(row, parse_json_dict=ic._parse_json_dict),
                side=SIDE_CONSUMER)
        except Exception as exc:
            if was_stopped_here:
                tally["known"] += 1
            else:
                broken.append((_tag(d), "INTAKE->POST_INTAKE",
                               "%s: %s" % (type(exc).__name__, str(exc)[:200])))
            continue
        tally["fixed" if was_stopped_here else "passed"] += 1
    ok = not broken
    print("[boundary] %s - %d drafts in %.1fs: %d pass (%d recomputed at entry), %d that failed "
          "here before now pass, %d still fail as before"
          % ("OK" if ok else "FAILED", len(drafts), time.time() - t0, tally["passed"] + tally["fixed"],
             tally["recalc_changed"], tally["fixed"], tally["known"]))
    for tag, where, err in broken:
        print("  BROKEN  %-38s %-20s %s" % (tag, where, err))
    return ok


# --------------------------------------------------------------------------
# 4. PAYROLL
# --------------------------------------------------------------------------
def _reconcile(S, payload, anchor, fin):
    """'reconciled' | 'gate_stopped' | 'no_stated'; raises on any other exception."""
    try:
        S._stamp_stated_payroll_reconciliation(payload, anchor, financials_json=fin)
    except Exception as exc:  # the fail-fast raises after stamping
        if GATE_STOP in str(exc):
            return "gate_stopped"
        raise
    return "reconciled" if "stated_payroll_reconciliation" in payload else "no_stated"


def check_payroll(drafts) -> bool:
    _server_path()
    from client_intake_and_finmo.post_intake_headcount import schedule as S
    from client_intake_and_finmo.post_intake_headcount.lookup import (
        validate_payroll_headcount_payload as V)

    t0 = time.time()
    tally = {"replayed": 0, "no_payload": 0, "skipped_legacy": 0, "reconciled": 0,
             "gate_stopped": 0, "no_stated": 0, "authored_ok": 0}
    broken, stopped = [], []
    for d in drafts:
        tag = _tag(d)
        stored = _jl(d["payroll_headcount"])
        people = _jl(d["people_json"]) or {}
        fin = _jl(d["financials_json"]) or {}
        if not isinstance(stored, dict) or not stored.get("rows"):
            tally["no_payload"] += 1
            continue
        base = copy.deepcopy(stored)
        for k in ("stated_payroll_reconciliation", "rest_of_team_anchor"):
            base.pop(k, None)
        if V(copy.deepcopy(base)):
            tally["skipped_legacy"] += 1      # predates the current schema rules
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
                copy.deepcopy(sup), people_json=people, key_people_rows=keys, horizon=horizon)
            p["rows"] = keys + new_sup
            if anchor is not None:
                p["rest_of_team_anchor"] = anchor
            outcome = _reconcile(S, p, anchor, fin)
            tally[outcome] += 1
            if outcome == "gate_stopped":
                rec = p.get("stated_payroll_reconciliation") or {}
                stopped.append((tag, rec.get("ratio"), rec.get("stated_total_payroll"),
                                rec.get("authored_q1_annualized")))
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

    ok = not broken
    print("[payroll] %s - %d drafts in %.1fs: replayed %d (%d without a payload, %d from before "
          "the current schema), live door %d reconciled / %d stopped by the reconciliation / "
          "%d no stated payroll; authored path valid on %d"
          % ("OK" if ok else "FAILED", len(drafts), time.time() - t0, tally["replayed"],
             tally["no_payload"], tally["skipped_legacy"], tally["reconciled"],
             tally["gate_stopped"], tally["no_stated"], tally["authored_ok"]))
    for tag, ratio, stated, authored in stopped:
        print("  stopped %-38s ratio %s  stated %s  authored %s" % (tag, ratio, stated, authored))
    for tag, where, errs in broken:
        print("  BROKEN  %-38s %-15s %s" % (tag, where, "; ".join(str(e) for e in errs)))
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drafts", type=int, default=40)
    ap.add_argument("--no-pins", action="store_true")
    ap.add_argument("--import-smoke", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.import_smoke:
        return import_smoke()
    t0 = time.time()
    results = [run_source()]
    if not a.no_pins:
        results.append(run_pins())
    drafts = load_drafts(a.drafts)
    results.append(check_boundary(drafts))
    results.append(check_payroll(drafts))
    ok = all(results)
    verdict = "PREFLIGHT: %s in %.1fs" % (
        "PASS - doors sound" if ok else "FAIL - do not start a paid run",
        time.time() - t0)
    # A FAILURE THAT LEAVES NO TRACE CANNOT BE DIAGNOSED (2026-09-13). A
    # pre-push preflight failed once, passed on the retry, and the reason was
    # gone - the output had scrolled past and nothing was written down. A
    # preflight that fails intermittently and keeps no record teaches you to
    # retry instead of look, which is the opposite of what a door is for.
    # Same ruling as a failed build being recorded and surfaced.
    try:
        runtime = os.path.join(ROOT, "_runtime")
        os.makedirs(runtime, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        line = "%s  %s  (source=%s pins=%s boundary=%s payroll=%s)\n" % (
            stamp, "PASS" if ok else "FAIL",
            *(("ok" if r else "FAIL") for r in (
                results + [True, True, True, True])[:4]))
        with open(os.path.join(runtime, "preflight_history.txt"), "a",
                  encoding="utf-8") as fh:
            fh.write(line)
        if not ok:
            with open(os.path.join(runtime, "preflight_last_failure.txt"), "w",
                      encoding="utf-8") as fh:
                fh.write(line)
    except Exception:
        pass          # a door that cannot write its log still reports its verdict
    print(verdict)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
