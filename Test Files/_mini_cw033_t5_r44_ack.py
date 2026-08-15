"""mini CW-033 turn-5 audit, item 2: the R44-found empty-state scalar ack.

VS's claim: "the empty-state scalar ack now claims nothing for ANY scalar
stage". Checks, none trusting the claim:
  A. Every generic scalar stage with the value ABSENT (missing / None / "")
     acks bare "Got it." - no invented figure.
  B. A stage whose landed value IS a genuine 0 still speaks $0.
  C. Benign router prose ships again on empty-state turns across stages
     (the _first builder: bare code ack -> prose wins; write-claim prose
     still dies).
  D. The NAMED scalar branches ABOVE the generic one (current_payroll,
     marketing, current_num_employees) with the value absent - do they
     claim a figure? (The latent class the R44 fix closed for the generic
     branch; these have their own hardcoded branches.)

  .venv\\Scripts\\python.exe "Test Files\\_mini_cw033_t5_r44_ack.py"
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "python" / "client_intake_and_finmo"))

NUM_RE = re.compile(r"[\$\d]")

results = []


def check(tag, ok, detail=""):
    results.append((tag, bool(ok)))
    print(f"[{'PASS' if ok else 'FAIL'}] {tag}" + (f" -- {detail}" if detail else ""))


def main() -> int:
    import api_handlers.intake_consult as ic  # type: ignore

    ack_of = lambda stage, fin: ic._build_financials_stage_acknowledgement(
        stage_name=stage, financials_json=fin)

    # --- A: generic scalar stages, value absent in three shapes ---
    generic = sorted(ic._GENERIC_FINANCIALS_FIELD_LABELS)
    for stage in generic:
        if stage == "future_rent_expected":
            continue  # boolean stage, its ack is a sentence, no figure
        for shape_name, fin in (("missing", {}), ("None", {stage: None}),
                                ("empty-str", {stage: ""})):
            a = ack_of(stage, fin)
            check(f"A {stage} value {shape_name} -> bare ack, no figure",
                  a == "Got it.", repr(a))

    # --- B: a genuine stored 0 still speaks $0 ---
    a0 = ack_of("monthly_rent_expense", {"monthly_rent_expense": 0})
    check("B stored 0 rent still speaks $0",
          "$0" in a0 and "monthly rent" in a0, repr(a0))
    a0b = ack_of("cash_on_hand", {"cash_on_hand": 0.0})
    check("B stored 0.0 cash on hand still speaks $0",
          "$0" in a0b, repr(a0b))

    # --- C: the _first builder lets benign prose ship on empty-state ---
    benign = "Happy to walk through how that part of the model works."
    for stage in ("monthly_rent_expense", "cash_on_hand",
                  "other_operating_expense", "current_capex"):
        out = ic._build_financials_stage_acknowledgement_first(
            benign, stage_name=stage, financials_json={},
            user_message="how does rent factor in?")
        check(f"C benign prose ships on empty-state {stage}",
              out == benign, repr(out))
    claimy = "Got it - I'll update your rent to $3,000."
    out2 = ic._build_financials_stage_acknowledgement_first(
        claimy, stage_name="monthly_rent_expense", financials_json={},
        user_message="rent is 3,000")
    check("C write-claim prose still dies on empty-state (bare ack ships)",
          out2 == "Got it.", repr(out2))
    # landed value present -> the write-derived ack outranks prose
    out3 = ic._build_financials_stage_acknowledgement_first(
        benign, stage_name="monthly_rent_expense",
        financials_json={"monthly_rent_expense": 2400.0},
        user_message="rent is 2,400")
    check("C a landed value still outranks benign prose (named ack)",
          "2,400" in out3 and "monthly rent" in out3, repr(out3))

    # --- D: the named branches above the generic one, value absent ---
    for stage, fin, label in (
        ("current_payroll", {}, "payroll"),
        ("marketing", {}, "marketing"),
        ("current_num_employees", {}, "employee count"),
    ):
        a = ack_of(stage, fin)
        claims_fig = bool(re.search(r"\$\d|\b\d", a))
        check(f"D {stage} value absent -> does the ack claim a figure? "
              f"(claims={claims_fig})", True, repr(a))

    failing = [t for t, ok in results if not ok]
    print()
    if failing:
        print(f"RESULT: RED - {len(failing)} failing:")
        for f in failing:
            print("  -", f)
        return 1
    print(f"RESULT: GREEN - all {len(results)} checks passed "
          "(D lines are observations, read them)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
