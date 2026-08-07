"""INTAKE_CONSTANTS_LEDGER conversions 1a/1b/1c - targeted RED/GREEN.

Nick's approved rulings (2026-08-07), with the framing requirement:
the $1 balance-rounding invariant is PRESERVED - the scale term is a
float-noise allowance active only at extreme magnitude, never a
business-relative loosening.

1a accounting equation: MUST prove BOTH directions -
   - ~$500M quarters, BALANCED equation with $3 float-noise residue:
     old fatal check killed the run; new tolerance (max($1, 5e8x1e-8
     = $5)) passes.
   - normal $2M scale, $3 REAL imbalance: fails before AND after
     (the $1 floor untouched at all realistic scales).
   - $500M with $50 real imbalance: still fails (dollars, not
     nano-relative, fail at any scale).
1b count ceiling: a 5,000-delivery business's triplet lands.
1c dollar floor: a sub-$1,000 annual stream lands (floor is now the
   product's own unit price).
"""
import copy
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")

from dotenv import load_dotenv

load_dotenv()

from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (  # noqa: E402
    accounting_equation_tolerance,
    assert_post_intake_accounting_equation,
)
from api_handlers.intake_consult import _reconcile_driver_correction  # noqa: E402

results = []


def check(label, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label)


def finmo_rows(assets_scale, imbalance):
    """One live quarter whose components sum to assets_scale on the
    asset side and assets_scale - imbalance on the L+E side."""
    return {"quarter_rows": [{
        "quarter_index": 1,
        "cash": assets_scale * 0.2,
        "accounts_receivable": assets_scale * 0.3,
        "inventory": assets_scale * 0.1,
        "prepaid_expenses": 0.0,
        "ppe": assets_scale * 0.4,
        "right_of_use_asset": 0.0,
        "accounts_payable": assets_scale * 0.25,
        "short_term_debt": 0.0,
        "deferred_revenue": 0.0,
        "long_term_debt": assets_scale * 0.25,
        "capital_lease_obligation": 0.0,
        "owners_capital": assets_scale * 0.3,
        "retained_earnings": assets_scale * 0.2 - imbalance,
        "other_equity": 0.0,
    }]}


def equation_raises(assets_scale, imbalance):
    try:
        assert_post_intake_accounting_equation(
            finmo_json=finmo_rows(assets_scale, imbalance), stage="e2e_test")
        return False
    except Exception:
        return True


# --- 1a: the tolerance function itself -------------------------------------
check("tol at $2M quarter is exactly $1 (floor untouched)",
      accounting_equation_tolerance(2_000_000.0) == 1.0)
check("tol at $50M quarter is exactly $1 (floor untouched)",
      accounting_equation_tolerance(50_000_000.0) == 1.0)
check("tol at $100M quarter is exactly $1 (boundary)",
      accounting_equation_tolerance(100_000_000.0) == 1.0)
check("tol at $500M quarter is $5 (float-noise allowance)",
      accounting_equation_tolerance(500_000_000.0) == 5.0)

# --- 1a: the fatal check end-to-end ----------------------------------------
# $500M quarter, $3 residue: pure float noise on a balanced book.
check("$500M + $3 residue PASSES (was fatal)",
      not equation_raises(500_000_000.0, 3.0))
# Normal scale, $3 residue: a REAL imbalance - $1 floor still bites.
check("$2M + $3 imbalance still FAILS (invariant preserved)",
      equation_raises(2_000_000.0, 3.0))
# $500M, $50 residue: real imbalance at scale - still fails.
check("$500M + $50 imbalance still FAILS",
      equation_raises(500_000_000.0, 50.0))
# Balanced books pass everywhere.
check("$2M balanced PASSES", not equation_raises(2_000_000.0, 0.0))
check("$500M balanced PASSES", not equation_raises(500_000_000.0, 0.0))

# --- 1b: 5,000-unit business triplet landing -------------------------------
OPS_DELIVERY = {"lob_models": [{"products": [{
    "product_name": "Delivery",
    "unit_price": 180,
    "units_per_period_capacity": 300,
    "operating_periods_per_year": 12,
    "utilization_rate": 1.0,
}]}]}
ops_after, note = _reconcile_driver_correction(
    ops_before=copy.deepcopy(OPS_DELIVERY),
    ops_after=copy.deepcopy(OPS_DELIVERY),
    user_message="That's not right - we do 5,000 deliveries a year at $180 "
    "each, which is $900,000, not what you have.",
)
p = ops_after["lob_models"][0]["products"][0]
check("5,000-count triplet lands capacity (was invisible above 2,000)",
      abs(float(p.get("units_per_period_capacity") or 0) - 5000.0 / 12.0) < 1e-6)
check("5,000-count landing narrates $900,000",
      isinstance(note, dict) and "$900,000" in str(note.get("stream_note") or ""))

# --- 1c: sub-$1,000 stream landing -----------------------------------------
OPS_CUPS = {"lob_models": [{"products": [{
    "product_name": "Lemonade cup",
    "unit_price": 4,
    "units_per_period_capacity": 3,
    "operating_periods_per_year": 52,
    "utilization_rate": 1.0,
}]}]}
ops_after2, note2 = _reconcile_driver_correction(
    ops_before=copy.deepcopy(OPS_CUPS),
    ops_after=copy.deepcopy(OPS_CUPS),
    user_message="It's a small side thing - about 200 cups a year at $4 "
    "each, $800 for the year.",
)
p2 = ops_after2["lob_models"][0]["products"][0]
check("sub-$1,000 target lands capacity (was invisible below $1,000)",
      abs(float(p2.get("units_per_period_capacity") or 0) - 200.0 / 52.0) < 1e-6)

# --- negative control: no-figure turn still lands nothing ------------------
ops_after3, note3 = _reconcile_driver_correction(
    ops_before=copy.deepcopy(OPS_DELIVERY),
    ops_after=copy.deepcopy(OPS_DELIVERY),
    user_message="What's next?",
)
check("NEG no-figure turn lands nothing",
      ops_after3 == OPS_DELIVERY and note3 is None)

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
