"""CW-016 (i2) reconcile refinement - targeted RED/GREEN.

The Ironbridge event, exact numbers: stated revenue $11,097,600 (client's
P&L). The $4,000->$4,300 unit-price repair moved implied revenue from
$10,968,000 (pre_gap 1.17%) to $11,097,600 exactly (post_gap 0.0). The
classifier's structure-fix floor (pre_gap > 8%) missed it, the propagate
branch multiplied stated by 1.0118 -> $11,228,731, and the client had to
catch and revert it (turn 125).

Refinement: post_gap <= 1% => reconcile at ANY pre_gap.
Negative controls: the verified propagate cases (genuine price changes
that move the model AWAY from stated) must still propagate.
"""
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")

from api_handlers.intake_consult import _driver_correction_disposition  # noqa: E402

STATED = 11_097_600.0

results = []


def check(label, got, want):
    ok = got == want
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + f"{label}: got {got}, want {want}")


# 1. IRONBRIDGE, exact: correction lands the model ON the stated figure.
check("Ironbridge structure-fix at small pre_gap (1.17% -> 0.0%)",
      _driver_correction_disposition(
          pre_implied=10_968_000.0, post_implied=STATED, stated=STATED),
      "reconcile")
# 2. Same shape, post_gap just inside 1% (lands within rounding of stated).
check("near-exact landing (post_gap 0.8%) reconciles",
      _driver_correction_disposition(
          pre_implied=10_968_000.0, post_implied=STATED * 1.008, stated=STATED),
      "reconcile")
# 3. NEG Stonewater-class: model agreed (pre_gap ~0), price rise moves it
#    AWAY by 5.8% -> forward-looking value change, must still propagate.
check("NEG price rise +5.8% still propagates",
      _driver_correction_disposition(
          pre_implied=STATED, post_implied=STATED * 1.058, stated=STATED),
      "propagate")
# 4. NEG Harpeth-class: +4.9% away from stated -> propagate.
check("NEG price rise +4.9% still propagates",
      _driver_correction_disposition(
          pre_implied=STATED * 1.002, post_implied=STATED * 1.049, stated=STATED),
      "propagate")
# 5. Ironclad-class (the original F1 case): big misread repaired
#    (pre_gap 16% -> post_gap 0.5%) -> reconcile, as before.
check("Ironclad structure-fix (16% -> 0.5%) reconciles",
      _driver_correction_disposition(
          pre_implied=STATED * 1.16, post_implied=STATED * 1.005, stated=STATED),
      "reconcile")
# 6. Immaterial change (factor within 0.5%, no landing signal) -> none.
check("immaterial change stays none",
      _driver_correction_disposition(
          pre_implied=STATED * 1.03, post_implied=STATED * 1.031, stated=STATED),
      "none")
# 7. NEG partial repair: big misread improves but does NOT land
#    (pre 20% -> post 12%): structure-fix per the original rule ->
#    reconcile branch requires post_gap < 5%, so disposition is none
#    (hold, no propagate) - unchanged behavior.
check("partial repair (20% -> 12%) stays none",
      _driver_correction_disposition(
          pre_implied=STATED * 1.20, post_implied=STATED * 1.12, stated=STATED),
      "none")

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
