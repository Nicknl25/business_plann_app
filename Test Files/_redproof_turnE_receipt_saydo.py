"""TURN E redproof (CW-033, 2026-08-15) - offline, both builders, the W3 t2
shape (Sumac Property contract: 12-period row, price 520, util 0.82; client
says "Sorry - mowing capacity is 40 a week." -> period 173.3333, wk 40).

  E1 capture_receipt.receipt_summary: the week twin renders "weekly capacity
     -> 40" and the period cell "monthly capacity -> 173"; NEVER "monthly
     capacity -> 40".
  E2 intake_consult._reconcile_driver_correction: with the converted stated
     figure declared (converted_stated=[40]) the say-do tail must NOT claim
     "didn't end up using 40". The undeclared call is also run to show the
     pre-fix behaviour (tail present) - on PREFIX code the declared call is a
     TypeError (structural red) and the undeclared call shows the tail
     (behavioural red).

  .venv\Scripts\python.exe "Test Files\_redproof_turnE_receipt_saydo.py"
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))
sys.path.insert(0, str(REPO / "python" / "client_intake_and_finmo"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FAILS: list = []


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))
    if not ok:
        FAILS.append(label)


def main() -> int:
    from capture_receipt import receipt_summary  # type: ignore
    from api_handlers.intake_consult import _reconcile_driver_correction  # type: ignore

    print("E1 - receipt builder, the twin pair on a 12-period row")
    pfx = "ops.lob_models[0].products[0]"
    receipt = {
        "written": [
            (f"{pfx}.units_per_week_capacity", 9.2308, 40.0),
            (f"{pfx}.units_per_period_capacity", 40.0, 173.3333),
        ],
        "dropped": [],
        "periods_by_prefix": {pfx: 12.0},
        "names_by_prefix": {pfx: "Property contract"},
    }
    text = receipt_summary(receipt).replace("→", "->")
    print("  receipt:", text)
    check("E1 week twin spoken as weekly capacity -> 40", "weekly capacity -> 40" in text, text)
    check("E1 period cell spoken as monthly capacity -> 173", "monthly capacity -> 173" in text, text)
    check("E1 NEVER monthly capacity -> 40", "monthly capacity -> 40" not in text.replace("-> 40;", "-> 40;")
          or "monthly capacity -> 40" not in text, text)
    # exact absence, spelled plainly
    check("E1 absence (exact)", "monthly capacity -> 40" not in text, text)

    print("\nE2 - say-do tail, the converted stated figure is covered")
    row_before = {
        "product_name": "Property contract", "unit_price": 520.0,
        "utilization_rate": 0.82, "operating_periods_per_year": 12.0,
        "units_per_period_capacity": 40.0, "units_per_week_capacity": 9.2308,
        "unit_cadence": "month",
    }
    ops_before = {"lob_models": [{"products": [row_before]}]}
    ops_after = copy.deepcopy(ops_before)
    ops_after["lob_models"][0]["products"][0]["units_per_period_capacity"] = 173.3333
    ops_after["lob_models"][0]["products"][0]["units_per_week_capacity"] = 40.0
    msg = "Sorry - mowing capacity is 40 a week."
    _, note0 = _reconcile_driver_correction(
        ops_before=ops_before, ops_after=copy.deepcopy(ops_after), user_message=msg,
        extra_derivable=[173.3333])
    tail0 = str((note0 or {}).get("stream_note") or "")
    print("  undeclared:", tail0)
    check("E2 (documenting) undeclared call shows the pre-fix tail",
          "didn't end up using 40" in tail0, tail0)
    try:
        _, note1 = _reconcile_driver_correction(
            ops_before=ops_before, ops_after=copy.deepcopy(ops_after), user_message=msg,
            extra_derivable=[173.3333], converted_stated=[40.0])
    except TypeError as exc:
        check("E2 declared call accepted (structural)", False, str(exc))
        note1 = None
    tail1 = str((note1 or {}).get("stream_note") or "")
    print("  declared:  ", tail1)
    check("E2 declared: stream note still ships", "models at about" in tail1, tail1)
    check("E2 declared: NO false non-use claim of the stated 40",
          "didn't end up using 40" not in tail1, tail1)
    print()
    if FAILS:
        print(f"RESULT: RED - {len(FAILS)}: " + "; ".join(FAILS))
        return 1
    print("RESULT: GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
