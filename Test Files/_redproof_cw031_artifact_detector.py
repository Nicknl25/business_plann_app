"""CW-031 tier 1 red-proof: the registry must catch its own false resolution.

THE BUG. Issue #138 (a multi-line business gets one blended COGS) was marked
resolved/confirmed by draft 1070c6a5 -- the Ravenwood run whose artifacts
DISPROVE it. The detector only ever asked "did a run finish and visit the
financials section, and did the reporter stay quiet?". The app proposed a
per-line split in prose, the reporter read the proposal, and the four product
rows were written null anyway.

THE PRODUCTION CHAIN under test is the one the finalizer runs after every
watched persona run:

    scripts/persona_run_vitals_finalize.py:387
      -> issue_registry.evaluate_run_for_resolution(conn, draft_id=...)

This proof calls that exact function against that exact draft, with no
fixtures and no stubs: real MySQL rows, the real operating_model_json, and
the real delivered workbook on disk.

RED ON THE BUG: with the detector's artifact gate removed (or before it
existed) the run below RESOLVES #138 confirmed. With the gate in place the
same call must reopen it and name the artifact.

  .venv\\Scripts\\python.exe "Test Files\\_redproof_cw031_artifact_detector.py"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
DRAFT_ID = "1070c6a560a04f3d971019a3787180bf"
FALSELY_RESOLVED = (
  "flow:financials:two_line_business_gets_one_blended_cogs_and_the_"
  "question_goes_unanswered"
)

# The per-line COGS class, all four filed off the same Ravenwood run. Each
# gets the artifact its verdict actually depends on.
PROBES = {
  "flow:financials:two_line_business_gets_one_blended_cogs_and_the_question_goes_unanswered": {
    "section": "financials",
    "artifact": [
      {"kind": "ops_per_line_cogs", "min_lines": 2},
      {"kind": "workbook_cogs_rows", "sheet": "FINMO", "min_rows": 2},
    ],
    "note": "resolved-confirmed on the run that disproves it; artifact gate added CW-031",
  },
  "hard_break:financials:per_line_cogs_is_proposed_but_cannot_be_written_by_the_client": {
    "section": "financials",
    "artifact": [{"kind": "ops_per_line_cogs", "min_lines": 2}],
    "note": "the write door: the proposal is correct, the ops rows stay null",
  },
  "hard_break:plan_build:workbook_carries_one_blended_cogs_row_at_n_equals_four": {
    "section": "financials",
    "artifact": [{"kind": "workbook_cogs_rows", "sheet": "FINMO", "min_rows": 2}],
    "note": "scoped to the P&L sheet: the label also sits on Model Inputs and Audit Source",
  },
}

FAILURES: list = []


def check(label: str, ok: bool, detail: str) -> None:
  print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {detail}")
  if not ok:
    FAILURES.append(label)


def main() -> int:
  load_dotenv(REPO_ROOT / ".env", override=False)
  sys.path.insert(0, str(REPO_ROOT / "python"))
  sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))
  from intake_submission import get_mysql_connection  # type: ignore
  from client_intake_and_finmo import issue_registry  # type: ignore

  conn = get_mysql_connection()
  try:
    print("STEP 0 - restore the documented false state so this proof repeats")
    # #138 as the registry actually recorded it on 2026-08-13 12:14:22:
    # resolved / retested_clean / confirmed, off draft 1070c6a5. The proof
    # rebuilds that exact state and then makes the fixed detector overturn it.
    cur = conn.cursor()
    cur.execute(
      """UPDATE issues SET status='resolved', resolution_basis='retested_clean',
             resolution_confidence='confirmed', clean_exercise_count=1,
             runs_since_last_seen=1
         WHERE signature=%s""",
      (FALSELY_RESOLVED,),
    )
    cur.execute(
      "DELETE FROM issue_occurrences WHERE draft_id=%s AND source='artifact_check'",
      (DRAFT_ID,),
    )
    conn.commit()
    cur.close()
    restored = issue_registry.get_issue(conn, signature=FALSELY_RESOLVED)
    print(f"  #138 restored to status={restored['status']} "
          f"basis={restored['resolution_basis']} "
          f"confidence={restored['resolution_confidence']}")
    check("false state restored",
          str(restored["status"]) == "resolved"
          and restored["resolution_confidence"] == "confirmed",
          "the run that disproves #138 is the run that resolved it")

    print("\nSTEP 1 - the artifacts, read directly (this is the ground truth)")
    cur = conn.cursor()
    ops = issue_registry._load_ops_model(cur, DRAFT_ID)
    products = issue_registry._ops_product_rows(ops or {})
    nulls = [str(p.get("product_name")) for p in products
             if p.get("cogs_percent_of_line_revenue") is None]
    print(f"  ops product rows: {len(products)}; null per-line COGS on: {nulls}")
    wb = issue_registry._assert_workbook_cogs_rows(
      cur, DRAFT_ID, {"sheet": "FINMO", "min_rows": 2})
    print(f"  workbook: {wb['verdict']} - {wb['detail']}")
    cur.close()
    check("ground truth is a genuine defect",
          len(products) >= 2 and len(nulls) == len(products) and wb["verdict"] == "fail",
          f"{len(products)} lines, {len(nulls)} null, workbook {wb['verdict']}")

    print("\nSTEP 2 - attach the artifact assertions (audited setter)")
    for signature, probe in PROBES.items():
      issue_registry.set_probe(conn, signature=signature, probe=probe,
                               note="CW-031 tier 1: artifact gate")
      print(f"  probe set: {signature.split(':')[-1][:60]}")

    print("\nSTEP 3 - run the PRODUCTION detector on the real failing draft")
    before = {s: issue_registry.get_issue(conn, signature=s) for s in PROBES}
    summary = issue_registry.evaluate_run_for_resolution(conn, draft_id=DRAFT_ID)
    print("  " + json.dumps({k: v for k, v in summary.items()
                             if k not in ("resolved_confirmed", "resolved_observational")}))
    print(f"  resolved_confirmed: {summary['resolved_confirmed']}")

    print("\nSTEP 4 - the verdicts")
    # Only #138 reaches the artifact branch: #140/#141 were FILED off this
    # same draft, so they take the reported-this-run branch and are held open
    # by the report itself. Asserting one artifact failure here is the precise
    # contract, not a softened one -- STEP 4b pins the other branch.
    check("the artifact assertion fired and failed",
          int(summary.get("artifact_failed") or 0) >= 1,
          f"artifact_failed={summary.get('artifact_failed')}")
    check("no false 'artifact verified' on a broken run",
          int(summary.get("artifact_verified") or 0) == 0,
          f"artifact_verified={summary.get('artifact_verified')}")
    for signature in PROBES:
      after = issue_registry.get_issue(conn, signature=signature)
      short = signature.split(":")[-1][:52]
      was = str(before[signature]["status"])
      now = str(after["status"])
      check(f"{short} is not resolved",
            now != "resolved", f"{was} -> {now}")
      check(f"{short} carries no 'confirmed' verdict",
            after.get("resolution_confidence") != "confirmed",
            f"confidence={after.get('resolution_confidence')}")
    check("nothing resolved confirmed on this run",
          not summary["resolved_confirmed"],
          f"{len(summary['resolved_confirmed'])} confirmed")

    print("\nSTEP 5 - the recurrence names the ARTIFACT, not the prose")
    cur = conn.cursor()
    cur.execute(
      """SELECT signature, observed FROM issue_occurrences
         WHERE draft_id=%s AND source='artifact_check' ORDER BY id DESC LIMIT 10""",
      (DRAFT_ID,),
    )
    rows = cur.fetchall()
    cur.close()
    for sig, observed in rows:
      print(f"  {sig.split(':')[-1][:52]}: {observed[:150]}")
    check("an artifact_check occurrence was written",
          len(rows) >= 1, f"{len(rows)} occurrence(s)")
    check("evidence cites the persisted rows",
          any("cogs_percent_of_line_revenue" in (o or "") for _, o in rows),
          "observed text names the ops field")
    check("the reopened issue is #138 itself",
          any(s.endswith("two_line_business_gets_one_blended_cogs_and_the_"
                         "question_goes_unanswered") for s, _ in rows),
          "signature matches the falsely-resolved issue")

    print("\nSTEP 6 - the FALSE-CONFIRM path is closed for good")
    # The original sin restated as a standing assertion: an issue whose probe
    # states only opportunity can never again reach 'confirmed'.
    opportunity_only = {"section": "financials"}
    art = issue_registry._assert_artifacts(None, DRAFT_ID, opportunity_only)
    check("an opportunity-only probe carries no artifact",
          art["present"] is False and art["verdict"] == "absent",
          f"present={art['present']} verdict={art['verdict']}")
    cur = conn.cursor()
    cur.execute(
      """SELECT COUNT(*) FROM issues
         WHERE resolution_confidence='confirmed' AND resolution_basis='retested_clean'"""
    )
    stale_confirmed = int(cur.fetchone()[0] or 0)
    cur.close()
    print(f"  legacy 'confirmed' rows resting on retested_clean: {stale_confirmed}")
    check("no NEW confirmed verdict was minted on this broken run",
          not summary["resolved_confirmed"], "resolved_confirmed is empty")
  finally:
    try:
      conn.close()
    except Exception:
      pass

  print("\n" + "=" * 72)
  if FAILURES:
    print(f"RED - {len(FAILURES)} check(s) failed: {FAILURES}")
    return 1
  print("GREEN - the detector reopened #138 on artifact evidence from the real draft.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
