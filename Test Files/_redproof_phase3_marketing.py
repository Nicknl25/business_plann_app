# -*- coding: utf-8 -*-
"""UNIVERSAL ENGINE PHASE 3 RED-PROOF (marketing family: baseline
derives from THE MODEL only; the stale-copy fallback is deleted).

  M1  NO STALE RE-DERIVATION: with no model provided, the family never
      recomputes the adjustment against the baseline's own cached copy
  M2  MODEL WINS: with a model present, baseline cells + adjustment
      derive from it, overwriting any stale copy (invariant)
  M3  PERCENT DERIVES: marketing_percent_of_revenue always recomputes
      from the stated total (invariant)
  M4  ENGINE LIVENESS: the canonical pass recomputes the family
      (invariant)

Protocol: RED on 669609e (M1), GREEN on phase 3.
"""
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

Y1 = {"company_revenue_total_year1": 500000.0}


def m1():
    fin = {
        "marketing_total_year1": 6000.0,
        "baseline_marketing": 45000.0,          # STALE cached copy - the
        # live model has since moved to 20,000 and this call has no
        # model in hand. The adjustment was last derived against the
        # LIVE model (-14,000); a stale re-derivation would write
        # 6,000 - 45,000 = -39,000 over it.
        "baseline_marketing_percent": 0.09,
        "marketing_adjustment": -14000.0,
    }
    out = ic._sync_marketing_field_family(
        financials_json=fin, financials_year1_json=Y1,
        marketing_model_json={},                 # NO model this call
    )
    adj = out.get("marketing_adjustment")
    baseline = out.get("baseline_marketing")
    return adj == -14000.0 and baseline == 45000.0 and \
        out.get("marketing_total_year1") == 6000.0


guarded("M1 NO STALE RE-DERIVATION: an absent model never recomputes against the cached baseline", m1)


def m2():
    fin = {
        "marketing_total_year1": 6000.0,
        "baseline_marketing": 45000.0,          # stale
        "baseline_marketing_percent": 0.09,
    }
    out = ic._sync_marketing_field_family(
        financials_json=fin, financials_year1_json=Y1,
        marketing_model_json={"baseline_marketing": 20000.0,
                              "baseline_marketing_percent": 0.04},
    )
    return (out.get("baseline_marketing") == 20000.0
            and abs(float(out.get("marketing_adjustment")) - (6000.0 - 20000.0)) < 1e-6)


guarded("M2 MODEL WINS: a present model re-derives baseline + adjustment over the stale copy", m2)


def m3():
    out = ic._sync_marketing_field_family(
        financials_json={"marketing_total_year1": 25000.0,
                         "marketing_percent_of_revenue": 0.004},
        financials_year1_json=Y1, marketing_model_json={},
    )
    return abs(float(out.get("marketing_percent_of_revenue")) - 0.05) < 1e-9


guarded("M3 PERCENT DERIVES from the stated total (the CW-007 family law)", m3)


def m4():
    fin, _y1 = ic._sync_financials_consult_persistence_state(
        financials_json={"marketing_total_year1": 12000.0,
                         "_financials_revenue_intro_done": True,
                         "current_revenue": 500000.0},
        financials_year1_json=dict(Y1),
        marketing_model_json={"baseline_marketing": 30000.0,
                              "baseline_marketing_percent": 0.06},
        people_json=None, ops_json={},
    )
    return (fin.get("baseline_marketing") == 30000.0
            and abs(float(fin.get("marketing_adjustment")) - (12000.0 - 30000.0)) < 1e-6)


guarded("M4 ENGINE LIVENESS: the canonical pass derives the family from the model", m4)


print(f"\n{sum(1 for r in results if r)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
