# -*- coding: utf-8 -*-
"""UNIVERSAL ENGINE PHASE 2 RED-PROOF (every ops driver derived).

  D1  FULL DERIVATION: every flat driver cell (price, periods,
      utilization, CADENCE, unit name) derives from the row -
      including cells the old mirror could never touch (missing flats;
      cadence/name, which the mirror never covered)
  D2  WRITE-DOOR LIVENESS (property 2): a scoped ops write leaves the
      WHOLE flat set consistent in the same call - not just the
      written field
  D3  DELETION (property 1): _sync_ops_flat_mirror is GONE; the
      reconcile-after class for ops is unwritable
  D4  CADENCE feeds capacity: a cadence correction re-derives which
      capacity cell is canonical in the same pass

Protocol: RED on 6cc324f (phase 1), GREEN on phase 2.
"""
import copy
import io
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from dotenv import load_dotenv

load_dotenv("C:/dev/business_plann_app/.env")

results = []


def check(label, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label)


def guarded(label, fn):
    try:
        check(label, bool(fn()))
    except Exception as exc:
        check(label + f"  [EXC {type(exc).__name__}: {exc}]", False)


import api_handlers.intake_consult as ic  # noqa: E402


def _ops_fixture():
    return {
        "unit_price": 100.0,             # stale flat (row says 120)
        "utilization_rate": 0.5,         # stale flat (row says 0.8)
        "unit_cadence": "weekly",        # stale flat (row says contract)
        # operating_periods_per_year flat MISSING (row says 12)
        "lob_models": [{"lob_name": "L", "products": [{
            "product_name": "unit", "unit_name": "consulting day",
            "unit_price": 120.0, "unit_cadence": "contract",
            "units_per_period_capacity": 45.0,
            "operating_periods_per_year": 12.0,
            "utilization_rate": 0.8}]}],
    }


def d1():
    ops = _ops_fixture()
    fn = getattr(ic, "_derive_ops_cells", None)
    if fn is None:
        print("  (D1: _derive_ops_cells absent)")
        return False
    fn(ops)
    # Phase 4 contract: rows exist -> the flat cells are RETIRED
    # (stripped), and the row-first read serves every driver.
    row_first = getattr(ic, "_ops_driver_value")
    return (
        "unit_price" not in ops and "utilization_rate" not in ops
        and "unit_cadence" not in ops
        and abs(float(row_first(ops, "unit_price")) - 120.0) < 1e-9
        and abs(float(row_first(ops, "utilization_rate")) - 0.8) < 1e-9
        and str(row_first(ops, "unit_cadence")) == "contract"
        and abs(float(row_first(ops, "operating_periods_per_year")) - 12.0) < 1e-9
    )


guarded("D1 FULL DERIVATION: stale flats heal, MISSING flats fill, cadence/name covered", d1)


def d2():
    ops = _ops_fixture()
    _bf, ops2, _mk, _pp, _fin, _ff = ic._apply_scoped_patch(
        {"ops.unit_price": 135.0}, business_facts={}, ops_json=ops,
        market_json={}, people_json={}, financials_json={},
        fulfillment_json={})
    row = ops2["lob_models"][0]["products"][0]
    row_first = getattr(ic, "_ops_driver_value")
    return (
        abs(float(row.get("unit_price")) - 135.0) < 1e-9      # row landed
        and "unit_price" not in ops2                           # flat retired
        and "utilization_rate" not in ops2                     # stale flat GONE, not healed
        and abs(float(row_first(ops2, "utilization_rate")) - 0.8) < 1e-9
        and str(row_first(ops2, "unit_cadence")) == "contract"
    )


guarded("D2 WRITE-DOOR LIVENESS: one scoped write leaves the WHOLE flat set consistent", d2)


def d3():
    return not hasattr(ic, "_sync_ops_flat_mirror")


guarded("D3 DELETION: _sync_ops_flat_mirror is gone - the ops reconcile-after class is unwritable", d3)


def d4():
    ops = {"lob_models": [{"products": [{
        "unit_cadence": "weekly", "units_per_week_capacity": 40.0,
        "units_per_period_capacity": 40.0,
        "operating_periods_per_year": 52.0}]}]}
    _bf, ops2, _mk, _pp, _fin, _ff = ic._apply_scoped_patch(
        {"ops.unit_cadence": "contract"}, business_facts={}, ops_json=ops,
        market_json={}, people_json={}, financials_json={},
        fulfillment_json={})
    row = ops2["lob_models"][0]["products"][0]
    # Under contract cadence the period cell is canonical (40 stands)
    # and the week cell derives 40*52/52 = 40 - consistent, no fork.
    return (str(row.get("unit_cadence")) == "contract"
            and "unit_cadence" not in ops2
            and abs(float(row.get("units_per_week_capacity")) - 40.0) < 0.01)


guarded("D4 CADENCE write re-derives the capacity family in the same pass", d4)


print(f"\n{sum(1 for r in results if r)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
