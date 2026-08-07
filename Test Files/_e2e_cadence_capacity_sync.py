"""CW-018 driver-cadence family (1) - cadence-aware capacity sync.

The verbatim week<->period copies put a monthly/annual count into the
weekly-named legacy field; the engine's fallback multiplies that field
by 13 (13x-52x inflation when the primary pair is missing). Fills are
now CONVERTED so the legacy fallback is arithmetically identical to the
canonical path, and annual cadences default periods=1.
"""
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")
from dotenv import load_dotenv

load_dotenv()
from api_handlers.intake_consult import _normalize_ops_capacity_compat  # noqa: E402

results = []


def check(label, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label)


def norm(unit):
    ops = {"lob_models": [{"products": [dict(unit)]}]}
    out = _normalize_ops_capacity_compat(ops)
    return out["lob_models"][0]["products"][0]


# Monthly product, period stated: week fill is CONVERTED (30*12/52),
# so engine fallback week*13 == period*periods/4 exactly.
p = norm({"unit_cadence": "monthly", "units_per_period_capacity": 30})
check("monthly: periods defaulted 12", p.get("operating_periods_per_year") == 12)
check("monthly: week fill converted (not verbatim 30)",
      abs(p["units_per_week_capacity"] - 30 * 12 / 52.0) < 1e-6)
check("monthly: fallback == primary",
      abs(p["units_per_week_capacity"] * 13 - 30 * 12 / 4.0) < 1e-6)

# Annual product (the Vanguard/CW-014 shape): periods defaults 1; a
# stated 160/year never lands as 'weekly 160'.
p2 = norm({"unit_cadence": "annual", "units_per_period_capacity": 160})
check("annual: periods defaulted 1", p2.get("operating_periods_per_year") == 1)
check("annual: week fill converted (160/52, not 160)",
      abs(p2["units_per_week_capacity"] - 160 / 52.0) < 1e-6)
check("annual: fallback == primary (40/quarter, not 2080)",
      abs(p2["units_per_week_capacity"] * 13 - 160 * 1 / 4.0) < 1e-4)

# Weekly unchanged: verbatim period=week is correct at periods=52.
p3 = norm({"unit_cadence": "weekly", "units_per_week_capacity": 25})
check("weekly: period = week, periods 52",
      p3.get("units_per_period_capacity") == 25 and p3.get("operating_periods_per_year") == 52)

# Contract cadence with stated periods: converted fill.
p4 = norm({"unit_cadence": "contract", "units_per_period_capacity": 8,
           "operating_periods_per_year": 4})
check("contract w/ periods: week fill converted (8*4/52)",
      abs(p4["units_per_week_capacity"] - 8 * 4 / 52.0) < 1e-6)

# Unknown cadence + unknown periods: NO mislabeled fill manufactured.
p5 = norm({"units_per_period_capacity": 12})
check("unknown/unknown: no phantom weekly fill",
      "units_per_week_capacity" not in p5 or p5.get("units_per_week_capacity") is None)

# Both fields present: nothing overwritten.
p6 = norm({"unit_cadence": "monthly", "units_per_period_capacity": 30,
           "units_per_week_capacity": 7})
check("both present: untouched", p6["units_per_week_capacity"] == 7
      and p6["units_per_period_capacity"] == 30)

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
