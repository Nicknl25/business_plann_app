# -*- coding: utf-8 -*-
"""GOAL-ANCHOR RED-PROOF (conversational-state audit #1, Nick-ruled).

The one genuinely dead-ended solicitation: "what is one concrete goal
you want to hit in about the next 12 months?" - every client answers
with their real ambition, and the ROADMAP never consumed it. Now the
capture (ops_json.milestones, existing machinery, pinned here as
load-bearing) feeds the roadmap: the paths build toward the client's
own stated goal, in their words.

  G1  CAPTURE PIN: the deterministic fallback extracts the goal from
      the live Brightline phrasing (the pipeline the anchor rides)
  G2  PAYLOAD + COPY: roadmap_payload carries client_goal and
      _roadmap_message anchors to it; absent goal = untouched copy
  G3  END-TO-END: gate_and_turn's roadmap names the client's own goal
      when ops_json carries the captured milestone (the real caller
      wiring, walking fixture -> corner collapse -> roadmap)

Protocol: RED on 539fb17 (roadmap_payload has no client_goal; the
message never anchors), GREEN on the fix.
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
from client_intake_and_finmo.intake_coherence import (  # noqa: E402
    controller as ctl,
    section as sec,
)

GOAL_ANSWER = ("I'd like to be full at 60 visits a week and actually pay "
               "myself properly. Right now I take what's left and some "
               "months that isn't much.")


def g1():
    m = ic._fallback_ops_pending_milestone_from_text(GOAL_ANSWER)
    return (isinstance(m, dict) and "60 visits" in str(m.get("description"))
            and str(m.get("timing")).strip() != "")


guarded("G1 CAPTURE PIN: the live Brightline goal answer extracts to a milestone", g1)


def g2():
    p = ctl.roadmap_payload(
        corner={"q11": {}, "gap_quarterly": 21482.0}, eval_result={},
        bounds={"team": {"min_annual_payroll": 120000.0}},
        client_goal={"description": "be full at 60 visits a week and pay "
                                    "myself properly",
                     "timing": "Within the next 12 months"})
    m = sec._roadmap_message(p)
    p2 = ctl.roadmap_payload(
        corner={"q11": {}, "gap_quarterly": 21482.0}, eval_result={},
        bounds={})
    m2 = sec._roadmap_message(p2)
    return ("You told me your goal" in m and "60 visits" in m
            and "distance, not worth" in m
            and "You told me your goal" not in m2)


guarded("G2 PAYLOAD+COPY: the roadmap anchors to the stated goal; absent goal = untouched", g2)


WALK_OPS = {"business_type": "Commercial cleaning services",
            "business_naics_6": "561720",
            "business_description_summary":
                "Commercial office cleaning under recurring monthly "
                "contracts with night crews.",
            "milestones": [{"description": "be full at 60 visits a week and "
                                           "actually pay myself properly",
                            "timing": "Within the next 12 months"}],
            "lob_models": [{"lob_name": "Cleaning", "products": [{
                "product_name": "Monthly office contract", "unit_price": 1200.0,
                "units_per_period_capacity": 22.0,
                "operating_periods_per_year": 12.0, "utilization_rate": 0.8}]}]}
WALK_FIN = {"current_revenue": 253440.0, "baseline_payroll_year1": 260000.0,
            "current_payroll": 260000.0, "payroll_total_year1": 260000.0,
            "other_opex_absolute": 55000.0, "marketing_total_year1": 12000.0,
            "cogs_percent_of_revenue": 0.07, "monthly_rent_expense": 2500.0}


def _stamped_walking_state(fin, ops):
    state = {
        "margin_band_judgment": {
            "q11": {"low": 0.12, "high": 0.22},
            "gross_margin_floor_q11": 0.30,
            "fixed_cost_burden_max_q11": 0.90,
            "ni_margin_floor_q11": 0.02,
            "labor_intensity_class": "high",
            "labor_treatment": "all_labor_in_payroll_line",
        },
        "judged_growth": {"qoq_start": 0.05, "qoq_end": 0.02,
                          "source": "test", "year1_annual_growth": 0.2,
                          "mature_annual_growth": 0.08},
        "demand_response": {"evidence_level": "thin", "withheld": True,
                            "price_response": None, "marketing_response": None,
                            "volume_headroom": None, "notes": []},
        "essentials_response": {"evidence_level": "thin", "withheld": True,
                                "lines": {}, "notes": []},
        "status": "walking",
        "gap_open": 9000.0, "gap_initial": 12000.0,
        "round": {"key": "cost_structure"},
        "rounds_done": [],
        "_lever_writes": {"marketing_total_year1":
                          {"from": 23850.0, "to": 12000.0}},
        "bounds": {
            "feasible_region_exists": True,
            "existing_lines": [{
                "lob": "Cleaning", "product": "Monthly office contract",
                "unit_price": 1200.0, "annual_units": 211.2,
                "price_multiplier_max": 1.01, "volume_multiplier_max": 1.01,
                "utilization_rate": 0.8,
            }],
            "team": {"min_annual_payroll": 250000.0},
            "cogs_percent_of_revenue_min": 0.07,
            "marketing_floor_annual": 12000.0,
            "rent_monthly_min": 2500.0,
            "other_opex_annual_min": 55000.0,
        },
    }
    digest, _ = sec._compute_band_identity_digest(
        state, ops_json=ops, people_json={}, market_json={},
        marketing_model_json={}, financials_json=fin,
    )
    state["digest_hash"] = digest
    return state


def g3():
    ops = copy.deepcopy(WALK_OPS)
    fin = dict(WALK_FIN)
    fin["_coherence"] = _stamped_walking_state(fin, ops)
    t1, fin1, _ = sec.gate_and_turn(
        ops_json=ops, people_json={}, market_json={},
        marketing_model_json={}, financials_json=fin,
        financials_year1_json={}, user_text="ok, what's next?")
    st1 = (fin1.get("_coherence") or {})
    if not st1.get("corner_collapse_hold"):
        print("  (G3 setup: no corner-collapse hold; status:", st1.get("status"), ")")
        return False
    t2, fin2, _ = sec.gate_and_turn(
        ops_json=ops, people_json={}, market_json={},
        marketing_model_json={}, financials_json=dict(fin1),
        financials_year1_json={},
        user_text="those figures are all correct, that's really my payroll")
    st2 = (fin2.get("_coherence") or {})
    msg2 = str((t2 or {}).get("assistant_message") or "")
    return (st2.get("status") == "roadmap"
            and "You told me your goal" in msg2 and "60 visits" in msg2)


guarded("G3 END-TO-END: the rendered roadmap names the client's own stated goal", g3)


print(f"\n{sum(1 for r in results if r)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
