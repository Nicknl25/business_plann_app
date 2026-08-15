"""mini TRIAGE TURN (2026-08-14): close the WONT-FIX bucket in the registry.

Nick's deal-breaker law: a finding becomes a fix turn only if it puts a
WRONG NUMBER or FALSE CLAIM into a real client's DELIVERED PLAN on the
GUIDED PATH. Everything else closes WONT-FIX with its reason, in the same
audit. Closing is safe by design: resolved is not terminal — a failing
probe re-files as a recurrence.

Mechanism: the registry's human-override door (resolve_manually), reason
in the note. Dry run by default; --apply to write.
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env", override=False)
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))

from client_intake_and_finmo import issue_registry  # noqa: E402
from intake_submission import get_mysql_connection  # noqa: E402

APPLY = "--apply" in sys.argv

PREFIX = ("TRIAGE 2026-08-14 (deal-breaker law): WONT-FIX - no wrong number "
          "or false claim reaches a delivered plan on the guided path. ")
SUFFIX = " Recurrence re-opens (resolved is not terminal)."

# signature -> one-line reason (the triage file _mini_triage_20260814.txt
# carries the full buckets; these notes must stand alone in the registry).
CLOSE: dict[str, str] = {
    "experience:financials:receipt_header_names_one_line_and_prints_another_lines_price":
        "Unreproducible from the filing; final stored state was correct and the "
        "capture_receipt naming path reads correct on inspection (VS_NOTES CW-032 "
        "tier 4). Cosmetic receipt header.",
    "hard_break:post_intake:capital_lease_schedule_validation_kills_plan_run":
        "A killed run delivers no plan; the recovery design (hold-not-verdict, "
        "supervisor ladder, dead-letter) owns failed runs, and the derived-lease "
        "tolerance shipped in CW-016 addressed the trigger.",
    "hard_break:post_intake:percent_of_revenue_out_of_range_kills_plan_run":
        "A killed run delivers no plan; supervisor escalation owns strands, and "
        "the source class is dead (blend doors refuse non-fraction rates, "
        "CW-031 round 8; census found 7 stored instances, all one April business).",
    "experience:post_intake:failed_plan_run_still_shows_building_your_plan":
        "Screen-state honesty on a run that delivers no plan. Superseded into the "
        "feature decision 'client-facing run-status honesty' for Nick.",
    "experience:submit:build_strip_rendered_before_run_exists":
        "UI render timing; nothing stored, nothing claimed about stored state.",
    "experience:target_market:positioning_product_list_join_glitch":
        "Copy join glitch; no stored number.",
    "experience:submit:reference_code_prefix_malformed":
        "Reference-code cosmetics; no stored number.",
    "experience:submit:reference_code_symbol_prefix":
        "Reference-code cosmetics; no stored number.",
    "experience:submit:post_submit_status_reads_in_progress":
        "Status-display sync; superseded into the feature decision "
        "'client-facing run-status honesty' for Nick.",
    "flow:submit:draft_status_in_progress_after_successful_submit":
        "Status-display sync; submit itself proven live (cc7e810). Superseded "
        "into the feature decision 'client-facing run-status honesty'.",
    "experience:submit_confirmation:terminal_state_not_reflected":
        "Status-display sync; superseded into the feature decision "
        "'client-facing run-status honesty'.",
    "experience:chat:currency_formatter_applied_to_non_monetary_values":
        "Display formatting; stored values untouched.",
    "experience:coherence:ack_reports_rounded_value_that_differs_from_stored":
        "Truthful rounding in display; the stored value is correct and is what "
        "the plan consumes.",
    "experience:coherence:parameter_narration_reports_rounded_value_not_stored_value":
        "Truthful rounding in display; stored value correct.",
    "experience:coherence:believable_band_shifts_with_client_inputs":
        "The band deriving from client inputs is the design (band identity "
        "excludes knobs since CW-017); not a defect.",
    "experience:human_resources:wage_defaults_implausible":
        "Defaults are anchors shown in the people stage and client-correctable; "
        "anchor-vs-actual correction is the design working; judged floors bound "
        "outcomes.",
    "experience:human_resources:wage_defaults_identical_across_roles":
        "Same class: client-reviewed anchors, judged floors bound outcomes.",
    "experience:human_resources:wage_defaults_invert_role_seniority":
        "Same class: client-reviewed anchors, judged floors bound outcomes.",
    "experience:human_resources:business_name_substituted_with_generic_label":
        "Copy substitution; no stored number.",
    "flow:intake_review:offered_modelling_thread_dropped":
        "A dropped courtesy thread corrupts no number and fakes no receipt; "
        "thread-keeping is listed as a feature decision if Nick wants it.",
}

conn = get_mysql_connection()
cur = conn.cursor(dictionary=True)
fmt = ",".join(["%s"] * len(CLOSE))
cur.execute(
    f"SELECT signature, status, severity FROM issues WHERE signature IN ({fmt})",
    tuple(CLOSE))
rows = {r["signature"]: r for r in cur.fetchall()}
cur.close()

missing = [s for s in CLOSE if s not in rows]
print(f"targets: {len(CLOSE)}  found: {len(rows)}  missing: {missing or 'none'}")
for sig, r in rows.items():
    print(f"  [{r['status']}/{r['severity']}] {sig}")

if not APPLY:
    print("\nDRY RUN - rerun with --apply to close")
    conn.close()
    sys.exit(0)

closed = 0
for sig, reason in CLOSE.items():
    r = rows.get(sig)
    if r is None:
        continue
    if str(r["status"]) not in ("open", "recurring"):
        print(f"skip {sig}: status={r['status']}")
        continue
    out = issue_registry.resolve_manually(conn, signature=sig, note=PREFIX + reason + SUFFIX)
    closed += 1
    print(f"closed {sig}: status={out.get('status')} basis={out.get('resolution_basis')}")

print(f"\nCLOSED: {closed}")

cur = conn.cursor(dictionary=True)
cur.execute(
    f"SELECT signature, status, resolution_basis FROM issues WHERE signature IN ({fmt})",
    tuple(CLOSE))
for r in cur.fetchall():
    print("VERIFY:", r["signature"], "->", r["status"], "/", r["resolution_basis"])
cur.close()
conn.close()
