"""CW-017 FULL BATCH - informant demotions + engine fragility conversions.

Every tractable member unit-verified here with boundary cases and the
non-negotiable negative controls; the deep-path members (E2 rebuild
comparison, E3 STD chain, E6 bundles in situ) are verified by the three
full real-case reruns (Ironbridge, Vanguard, Sunny) on the final build.
"""
import sys
import types

sys.path.insert(0, "C:/dev/business_plann_app/python")

from dotenv import load_dotenv

load_dotenv()

results = []


def check(label, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label)


# ============ INFORMANT DEMOTION 1: set_drivers anchors ============
from client_intake_and_finmo.post_intake_amalgamated.tools.set_drivers import (  # noqa: E402
    _check_anchor_band_violations,
    _manager_anchor_walls,
)

BANDS = {"expenses::Cost of Goods Sold": {"robust_min": 0.35, "robust_max": 0.65}}
ANCHORS = {"expenses::Cost of Goods Sold": {"q1": 0.78, "q11": 0.80, "q20": 0.82}}
OC = {"model_input_template": {"solver_input": {"fitted_envelope_per_q": {
    "cogs_percent_of_revenue": {
        "min": {str(q): 0.70 for q in range(1, 21)},
        "max": {str(q): 0.85 for q in range(1, 21)},
    },
}}}}
walls = _manager_anchor_walls(OC)
v, a = _check_anchor_band_violations(ANCHORS, BANDS, manager_walls=walls)
check("D1 anchors above cohort but within manager wall -> ZERO vetoes", not v)
check("D1 all three anchors demoted to advisories",
      sorted(x["anchor"] for x in a) == ["q1", "q11", "q20"]
      and all(x["code"] == "driver_anchor_above_band_max_advisory" for x in a))
v2, a2 = _check_anchor_band_violations(ANCHORS, BANDS, manager_walls={})
check("D1 NEG raw-cohort (no walls) still VETOES all three", len(v2) == 3 and not a2)
ANCHORS_HOT = {"expenses::Cost of Goods Sold": {"q11": 0.95}}
v3, a3 = _check_anchor_band_violations(ANCHORS_HOT, BANDS, manager_walls=walls)
check("D1 NEG above-manager-wall anchor still VETOES", len(v3) == 1 and not a3)
ANCHORS_LOW = {"expenses::Cost of Goods Sold": {"q11": 0.72}}
v4, a4 = _check_anchor_band_violations(
    ANCHORS_LOW, {"expenses::Cost of Goods Sold": {"robust_min": 0.75, "robust_max": 0.90}},
    manager_walls=walls)
check("D1 below-band-min within wall demotes too",
      not v4 and a4 and a4[0]["code"] == "driver_anchor_below_band_min_advisory")

# ============ INFORMANT DEMOTION 2: degenerate anchor ============
from client_intake_and_finmo.post_intake_headcount.band_fitting import (  # noqa: E402
    rescale_envelope_to_operator,
)

ENV = {"sga_percent_of_revenue": {"min": 0.10, "target": 0.20, "max": 0.35}}
# Luna-class: operator level so low the rescaled ceiling < cohort floor.
out, degen = rescale_envelope_to_operator(ENV, {"sga_percent_of_revenue": 0.002})
d = degen.get("sga_percent_of_revenue") or {}
b = out.get("sga_percent_of_revenue") or {}
check("D2 low-side action is fact-preserving union span",
      d.get("action") == "kept_union_span_fact_preserved")
check("D2 operator's stated level stays INSIDE the search range",
      b.get("min", 1.0) <= 0.002 <= b.get("max", 0.0))
check("D2 cohort reach kept (ceiling = raw cohort max)", b.get("max") == 0.35)
check("D2 target anchored to the client's fact", b.get("target") == 0.002)
# NEG: high-side behavior unchanged (operator kept, flagged only).
out_h, degen_h = rescale_envelope_to_operator(ENV, {"sga_percent_of_revenue": 0.90})
check("D2 NEG high-side still kept_operator_level",
      (degen_h.get("sga_percent_of_revenue") or {}).get("action") == "kept_operator_level")
# NEG: normal anchor unchanged (no degeneracy record).
out_n, degen_n = rescale_envelope_to_operator(ENV, {"sga_percent_of_revenue": 0.18})
check("D2 NEG normal anchor rescales with no degeneracy", not degen_n
      and abs((out_n["sga_percent_of_revenue"]["target"]) - 0.18) < 1e-9)

# ============ INFORMANT DEMOTION 3: judged-growth qoq cap ============
from client_intake_and_finmo.post_intake_contracts.runner import (  # noqa: E402
    build_python_stage_ramp_contract,
)

def _build_contract(judged):
    mi = {"solver_input": {"judged_growth": judged}} if judged else {}
    return build_python_stage_ramp_contract(
        business_facts={"business_stage": "operating"},
        ops_json={"business_stage": "operating"},
        financials_json={},
        financials_year1_json={},
        people_json={},
        planning_mode="standard",
        planning_mode_reason="test",
        model_input_json=mi,
        finmo_json={},
        r_and_d_applicability={"r_and_d_enabled": False},
    )

c_judged = _build_contract({"qoq_start": 0.12, "qoq_end": 0.10})
grid_j = c_judged["quarter_ramp_grid"]
q2 = next(r for r in grid_j if r["q"] == 2)
check("D3 judged 12% governs rev_target (cohort cap gone)",
      q2["rev_target"] == 0.12)
check("D3 rev_max = judged peak + headroom", q2["rev_max"] == 0.15)
c_none = _build_contract(None)
grid_n = c_none["quarter_ramp_grid"]
q2n = next(r for r in grid_n if r["q"] == 2)
check("D3 NEG no judgment -> cohort/default qoq governs (<= 12%)",
      q2n["rev_target"] < 0.12 and q2n["rev_max"] < 0.15)

# ============ #5 band-identity digest ============
import copy as _copy  # noqa: E402
_calls = {"n": 0}
_stub = types.ModuleType("client_intake_and_finmo.post_intake_headcount.gpt_margin_band_judgment")
def _stub_author(**kwargs):
    _calls["n"] += 1
    return {"ok": True, "judgment": {
        "q11_ebitda_band": {"low": 0.05, "high": 0.10},
        "q20_ebitda_band": {"low": 0.06, "high": 0.11},
    }}
def _stub_validate(*args, **kwargs):
    return dict(kwargs.get("judgment") or (args[0] if args else {}))
def _stub_from_mi(mi):
    return None
_stub.gpt_author_margin_band_once = _stub_author
_stub.validate_margin_band_judgment = _stub_validate
_stub.margin_band_from_model_input = _stub_from_mi
_real_mod = sys.modules.get("client_intake_and_finmo.post_intake_headcount.gpt_margin_band_judgment")
sys.modules["client_intake_and_finmo.post_intake_headcount.gpt_margin_band_judgment"] = _stub
try:
    from client_intake_and_finmo.intake_coherence.section import _ensure_margin_band  # noqa: E402
    OPS_A = {"business_type": "distributor", "lob_models": [{"lob_name": "Accounts", "products": [{
        "product_name": "Active account", "unit_price": 3400,
        "units_per_period_capacity": 280, "operating_periods_per_year": 12,
        "utilization_rate": 0.70,
    }]}]}
    st = _ensure_margin_band({}, ops_json=OPS_A, people_json={}, market_json={},
                             marketing_model_json={}, financials_json={"current_revenue": 1000000},
                             financials_year1_json={})
    first_calls = _calls["n"]
    # The Vanguard knob edit: price + utilization change, structure identical.
    OPS_B = _copy.deepcopy(OPS_A)
    OPS_B["lob_models"][0]["products"][0]["unit_price"] = 3700
    OPS_B["lob_models"][0]["products"][0]["utilization_rate"] = 0.75
    st2 = _ensure_margin_band(dict(st), ops_json=OPS_B, people_json={}, market_json={},
                              marketing_model_json={}, financials_json={"current_revenue": 1000000},
                              financials_year1_json={})
    check("#5 band authored once", first_calls == 1)
    check("#5 knob edit does NOT re-judge (stamp reused)", _calls["n"] == first_calls)
    check("#5 stamp survives knob edit", st2.get("margin_band_judgment") is not None)
    # NEG: an identity-level change (new product) MUST re-judge.
    OPS_C = _copy.deepcopy(OPS_A)
    OPS_C["lob_models"][0]["products"].append({"product_name": "Panel shop build", "unit_price": 9000})
    _ensure_margin_band(dict(st2), ops_json=OPS_C, people_json={}, market_json={},
                        marketing_model_json={}, financials_json={"current_revenue": 1000000},
                        financials_year1_json={})
    check("#5 NEG identity change (new product) re-judges", _calls["n"] == first_calls + 1)
finally:
    if _real_mod is not None:
        sys.modules["client_intake_and_finmo.post_intake_headcount.gpt_margin_band_judgment"] = _real_mod
    else:
        sys.modules.pop("client_intake_and_finmo.post_intake_headcount.gpt_margin_band_judgment", None)

# ============ E1 statement math hybrid ============
from client_intake_and_finmo.fail_fast.post_intake_fail_fast.fail_fast import (  # noqa: E402
    assert_post_intake_finmo_statement_integrity,
)

def _stmt_row(q, rev, cogs, gp, imbalance=0.0):
    return {
        "quarter_index": q, "revenue": rev, "cost_of_goods_sold": cogs,
        "gross_profit": gp, "ebitda": gp, "interest": 0.0, "depreciation": 0.0,
        "taxes": 0.0, "net_income": gp, "payroll": 0.0, "marketing": 0.0,
        "general_and_administrative": 0.0, "research_and_development": 0.0,
        "lease_rent": 0.0, "operating_cash_flow": 0.0, "investing_cash_flow": 0.0,
        "financing_cash_flow": 0.0, "net_cash_flow": 0.0, "beginning_cash": 0.0,
        "ending_cash": 0.0, "cash": 0.0, "accounts_receivable": 0.0,
        "inventory": 0.0, "prepaid_expenses": 0.0, "ppe": 0.0,
        "current_assets": 0.0, "current_liabilities": 0.0,
        "capital_expenditures": 0.0, "debt_issuance": 0.0, "debt_repayment": 0.0,
        "accounts_payable": 0.0, "short_term_debt": 0.0, "deferred_revenue": 0.0,
        "long_term_debt": 0.0, "owners_capital": 0.0, "retained_earnings": gp,
        "other_equity": 0.0, "total_assets": gp, "total_liabilities": 0.0,
        "total_equity": gp, "total_liabilities_and_equity": gp + imbalance,
        "capital_lease_obligation": 0.0, "right_of_use_asset": 0.0,
    }

def _stmt_raises(make_row):
    rows = [make_row(q) for q in range(1, 21)]
    try:
        assert_post_intake_finmo_statement_integrity(
            finmo_json={"quarter_rows": rows}, stage="e2e")
        return False
    except Exception as exc:
        if "core_row_invalid" in str(exc):
            raise AssertionError(f"test row missing core fields: {exc}")
        return True

# Rounding-boundary straddle: rev-cogs = 1000.4999 vs gp = 1000.5001 -
# old exact int-round equality tripped (1000 != 1001); hybrid passes.
check("E1 rounding-boundary straddle PASSES",
      not _stmt_raises(lambda q: _stmt_row(q, 1000.4999, 0.0, 1000.5001)))
check("E1 NEG real $5 statement break still FAILS",
      _stmt_raises(lambda q: _stmt_row(q, 1000.0, 0.0, 1005.0)))
check("E1 NEG real $5 balance imbalance still FAILS",
      _stmt_raises(lambda q: _stmt_row(q, 1000.0, 0.0, 1000.0, imbalance=5.0)))

# ============ E3 LTD + stored-totals derived tolerances ============
from client_intake_and_finmo.post_intake_runtime_validation.balance_sheet_driver_validation import (  # noqa: E402
    balance_sheet_reconciliation_errors,
)

def _bs_row(assets, liab, eq):
    return {"quarter_index": 1, "total_assets": assets, "total_liabilities": liab,
            "total_equity": eq, "cash": 0, "accounts_receivable": 0, "inventory": 0,
            "prepaid_expenses": 0, "ppe": 0, "accounts_payable": 0,
            "short_term_debt": 0, "long_term_debt": 0, "deferred_revenue": 0,
            "owners_capital": 0, "retained_earnings": 0, "other_equity": 0}

errs = balance_sheet_reconciliation_errors(
    finmo_json={"quarter_rows": [_bs_row(1000002.0, 500000.0, 500000.0)]})
check("E3 $2 three-rounding drift PASSES (was >1 fail)", not errs)
errs2 = balance_sheet_reconciliation_errors(
    finmo_json={"quarter_rows": [_bs_row(1000050.0, 500000.0, 500000.0)]})
check("E3 NEG $50 real imbalance still FAILS", bool(errs2))

# ============ E4 debt schedule derived tolerances ============
from client_intake_and_finmo.post_intake_debt_schedule.schedule import (  # noqa: E402
    validate_debt_schedule_payload,
)

def _debt_payload(drift):
    rows = []
    opening = 100000
    for q in range(1, 21):
        rep = 5000
        closing = max(0, opening - rep) + (drift if q == 1 else 0)
        rows.append({"quarter_index": q, "opening_debt": opening,
                     "actual_debt_issuance": 0, "actual_debt_repayment": rep,
                     "closing_debt": closing, "interest_rate": 0.02,
                     "interest_expense": int(opening * 0.02)})
        opening = closing
    return {"source_of_truth": "post_intake_debt_schedule",
            "lookup_function": "debt_schedule_quarter_lookup", "rows": rows}

from client_intake_and_finmo.post_intake_debt_schedule.schedule import (  # noqa: E402
    DEBT_SCHEDULE_LOOKUP_FUNCTION, DEBT_SCHEDULE_SOURCE_OF_TRUTH,
)

def _debt_violations(drift):
    p = _debt_payload(drift)
    p["source_of_truth"] = DEBT_SCHEDULE_SOURCE_OF_TRUTH
    p["lookup_function"] = DEBT_SCHEDULE_LOOKUP_FUNCTION
    return [v for v in validate_debt_schedule_payload(debt_schedule=p)
            if v.get("reason") == "principal_rollforward_invalid"]

check("E4 $2 rollforward rounding drift PASSES (was exact-equality fail)",
      not _debt_violations(2))
check("E4 NEG $50 rollforward break still FAILS", bool(_debt_violations(50)))

# ============ E5 lease component-sum derived tolerances ============
from client_intake_and_finmo.post_intake_capital_lease.schedule import (  # noqa: E402
    fail_fast_lease_interest_components_misaligned,
)

def _lease_interest_raises(drift):
    row = {"quarter_index": 1, "interest": 1000 + drift,
           "debt_interest_expense": 600, "lease_interest_expense": 400}
    try:
        fail_fast_lease_interest_components_misaligned(
            finmo_payload={"quarter_rows": [row]}, stage="e2e")
        return False
    except Exception:
        return True

check("E5 $2 three-rounding interest drift PASSES", not _lease_interest_raises(2))
check("E5 NEG $5 interest mismatch still FAILS", _lease_interest_raises(5))

# ============ E7 solver tolerance hybrid ============
from client_intake_and_finmo.post_intake_solver.sanity_assertion import (  # noqa: E402
    _value_is_within_target,
)

check("E7 float-noise breach at $2M scale PASSES",
      _value_is_within_target(produced=2_000_000.0 * (1 + 2e-10),
                              target_min=None, target_max=2_000_000.0,
                              numeric_tolerance=1e-6))
check("E7 NEG $50 real breach at $2M still FAILS",
      not _value_is_within_target(produced=2_000_050.0, target_min=None,
                                  target_max=2_000_000.0, numeric_tolerance=1e-6))
check("E7 ratio-scale floor unchanged (0.001 breach on 0.65 fails)",
      not _value_is_within_target(produced=0.651, target_min=None,
                                  target_max=0.65, numeric_tolerance=1e-6))

# ============ E9 percent bounds float epsilon ============
from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (  # noqa: E402
    _PERCENT_FLOAT_EPSILON,
)

check("E9 epsilon is float-noise scale only (no semantic loosening)",
      _PERCENT_FLOAT_EPSILON == 1e-9)

# ============ E11 WC-days single authority ============
from client_intake_and_finmo.post_intake_amalgamated.evaluate_plan import (  # noqa: E402
    _metric_current_from_finmo,
)

row_q3 = {"quarter_index": 1, "date": "2026-07-01", "revenue": 1_000_000.0,
          "accounts_receivable": 500_000.0}
val = _metric_current_from_finmo("ar_days_dso", [row_q3])
check("E11 cascade uses actual-calendar days (Q3 = 92), not 91.25",
      abs(val - 0.5 * 92.0) < 1e-9)

# ============ E13 judged healthy floor in burden exception ============
from client_intake_and_finmo.post_intake_realism import formulas as _formulas  # noqa: E402

check("E13 judged-band-low wired into the healthy-floor exception",
      "_judged_band_low" in open(
          "python/client_intake_and_finmo/post_intake_realism/formulas.py",
          encoding="utf-8").read())

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
