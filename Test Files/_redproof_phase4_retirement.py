# -*- coding: utf-8 -*-
"""UNIVERSAL ENGINE PHASE 4 RED-PROOF (flat-field retirement).

  T1  RETIREMENT: rows exist -> the flat driver keys are STRIPPED at
      the canonical pass; rowless legacy drafts keep theirs
  T2  READERS ROW-FIRST: the solver trio carries the row-first helper
      and no bare flat-primary driver read survives (source-level)
  T3  LEGACY FALLBACK: each helper reads the row when rows exist and
      the flat only on rowless legacy payloads
  T4  STAMP DEPTH: a restatement of a ROW value on a rows-only draft is
      placed (never flagged unlanded) - the flats used to carry these
      values shallow for the placed-check

Protocol: RED on bc19729 (phase 3), GREEN on phase 4.
"""
import io
import re
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

ROWY = {
    "unit_price": 99.0, "utilization_rate": 0.5,
    "lob_models": [{"products": [{
        "product_name": "unit", "unit_price": 120.0,
        "unit_cadence": "contract", "units_per_period_capacity": 45.0,
        "operating_periods_per_year": 12.0, "utilization_rate": 0.8}]}],
}
ROWLESS = {"unit_price": 75.0, "units_per_week_capacity": 20.0,
           "utilization_rate": 0.6}


def t1():
    import copy
    ops = copy.deepcopy(ROWY)
    ic._derive_ops_cells(ops)
    legacy = copy.deepcopy(ROWLESS)
    ic._derive_ops_cells(legacy)
    return ("unit_price" not in ops and "utilization_rate" not in ops
            and legacy.get("unit_price") == 75.0
            and legacy.get("units_per_week_capacity") == 20.0)


guarded("T1 RETIREMENT: rows -> flats stripped; rowless legacy untouched", t1)


def t2():
    import client_intake_and_finmo.post_intake_solver.feasibility_restoration as fr
    import client_intake_and_finmo.post_intake_solver.orchestrator as orch
    import client_intake_and_finmo.post_intake_solver.structural_feasibility_check as sfc
    import inspect
    ok = True
    for mod in (fr, orch, sfc):
        if not hasattr(mod, "_ops_driver"):
            print(f"  (T2: {mod.__name__} lacks _ops_driver)")
            ok = False
            continue
        src = inspect.getsource(mod)
        bare = re.findall(
            r"\b(?:ops|ops_json|adjusted_ops|adjusted_ops_json)\.get\("
            r"\"(?:unit_price|units_per_week_capacity|units_per_period_capacity"
            r"|utilization_rate|operating_periods_per_year)\"\)",
            src)
        # the helper's own fallback line reads ops.get(field) - by name,
        # not by literal, so any literal hit is a missed repoint
        if bare:
            print(f"  (T2: {mod.__name__} bare flat reads: {bare[:3]})")
            ok = False
    return ok


guarded("T2 READERS ROW-FIRST: solver trio repointed, zero bare flat-primary reads", t2)


def t3():
    import copy
    import client_intake_and_finmo.post_intake_solver.feasibility_restoration as fr
    rowy = copy.deepcopy(ROWY)
    return (float(fr._ops_driver(rowy, "unit_price")) == 120.0
            and float(fr._ops_driver(ROWLESS, "unit_price")) == 75.0)


guarded("T3 LEGACY FALLBACK: row wins when rows exist; flat serves rowless payloads", t3)


def t4():
    # Rows-only BY CONSTRUCTION (no flat keys, no derive call - the old
    # code's derive would repopulate flats and mask the depth miss).
    ops = {"lob_models": [{"products": [{
        "product_name": "unit", "unit_price": 120.0,
        "unit_cadence": "contract", "units_per_period_capacity": 45.0,
        "operating_periods_per_year": 12.0, "utilization_rate": 0.8}]}]}
    fin = ic._stamp_unlanded_figures_note(
        financials_json={"current_revenue": 500000.0},
        people_json={}, ops_json=ops,
        user_message="Right, the price is $120 like we said.",
        applied_notes=[], patch={},
    )
    return "_unlanded_note" not in fin


guarded("T4 STAMP DEPTH: a row-value restatement is placed, never flagged unlanded", t4)


print(f"\n{sum(1 for r in results if r)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
