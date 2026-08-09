"""PHASE 5 - display refresh E2E: the verdict stamps go live.

Production path: every turn -> _sync_financials_consult_persistence_state
(THE RECALC) -> refresh_eval_stamps -> state.eval / eval_flat /
gap_open / eval_judged_shortfall / walls restamped from the CURRENT
numbers. RED evidence: the verdict layer was completion-attempt-only -
the panel replayed gate-time snapshots between entries (a correction
mid-conversation left a stale gap and a stale judged shortfall on
screen until the next completion attempt).
"""
import copy
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")
from dotenv import load_dotenv

load_dotenv()

results = []


def check(label, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label)


from api_handlers.intake_consult import (  # noqa: E402
    _sync_financials_consult_persistence_state,
)
from client_intake_and_finmo.intake_coherence.section import (  # noqa: E402
    refresh_eval_stamps,
)

BAND = {
    "q11": {"low": 0.10, "high": 0.25, "target": 0.175},
    "q20": {"low": 0.12, "high": 0.30, "target": 0.21},
    "gross_margin_floor_q11": 0.30,
    "fixed_cost_burden_max_q11": 0.75,
    "ni_margin_floor_q11": 0.02,
    "labor_intensity_class": "high",
    "margin_character": "labor-bound personal services",
}
OPS = {"lob_models": [{"lob_name": "Grooming", "products": [{
    "product_name": "Full groom", "unit_price": 60.0,
    "units_per_period_capacity": 40.0, "operating_periods_per_year": 52.0,
    "utilization_rate": 0.7}]}]}
FIN = {"current_revenue": 87360.0, "baseline_payroll_year1": 39600.0,
       "current_payroll": 39600.0, "payroll_total_year1": 39600.0,
       "other_opex_absolute": 17400.0, "other_operating_expense": 1450.0,
       "marketing_total_year1": 600.0, "cogs_percent_of_revenue": 0.08,
       "_financials_revenue_intro_done": True,
       "_coherence": {"margin_band_judgment": BAND, "digest_hash": "x"}}

# D1: the restamp writes a live eval from the current numbers.
fin1 = refresh_eval_stamps(copy.deepcopy(FIN), ops_json=OPS,
                           financials_year1_json={})
st1 = fin1.get("_coherence") or {}
check("D1 eval stamped live (passed verdict + q11 point present)",
      isinstance(st1.get("eval"), dict)
      and st1["eval"].get("q11") is not None
      and st1.get("eval_flat") is not None)

# D2: a correction CHANGES the stamp on the very next Recalc pass - no
# gate entry needed. Payroll doubles -> the stamped q11 payroll moves.
fin2_in = copy.deepcopy(FIN)
fin2_in.update({"baseline_payroll_year1": 79200.0,
                "current_payroll": 79200.0, "payroll_total_year1": 79200.0})
fin2 = refresh_eval_stamps(fin2_in, ops_json=OPS, financials_year1_json={})
p1 = ((st1.get("eval") or {}).get("q11") or {}).get("payroll")
p2 = (((fin2.get("_coherence") or {}).get("eval") or {}).get("q11") or {}).get("payroll")
check(f"D2 correction moves the stamped q11 payroll ({p1} -> {p2}) live",
      p1 is not None and p2 is not None and abs(p2 - 2 * p1) < 1.0)

# D3: stale judged shortfall CLEARS when it no longer holds.
fin3_in = copy.deepcopy(FIN)
fin3_in["_coherence"]["eval_judged_shortfall"] = 7705.0  # stale latch
fin3 = refresh_eval_stamps(fin3_in, ops_json=OPS, financials_year1_json={})
check("D3 stale eval_judged_shortfall cleared (no judged-tier failure now)",
      "eval_judged_shortfall" not in (fin3.get("_coherence") or {}))

# D4: the wall restamps on the same cadence (phase 3 live) - raising
# payroll past the high-class 70% flips the wall to failed.
fin4_in = copy.deepcopy(FIN)
fin4_in.update({"baseline_payroll_year1": 65000.0,
                "current_payroll": 65000.0, "payroll_total_year1": 65000.0})
fin4 = refresh_eval_stamps(fin4_in, ops_json=OPS, financials_year1_json={})
w4 = ((fin4.get("_coherence") or {}).get("walls") or {}).get("payroll_share") or {}
check("D4 wall restamped live (65,000/87,360 = 74% > 70% -> failed)",
      w4.get("passed") is False and abs(w4.get("value", 0) - 65000.0 / 87360.0) < 1e-4)

# D5: no band stamp -> untouched (judgments never authored here).
fin5 = refresh_eval_stamps({"current_revenue": 50000.0}, ops_json=OPS,
                           financials_year1_json={})
check("D5 no judgment, no stamp - draft untouched",
      "_coherence" not in fin5 or not (fin5.get("_coherence") or {}).get("eval"))

# D6: THE PRODUCTION CHAIN - the Recalc itself restamps (a financials
# turn's sync pass carries the live verdict without any gate entry).
fin6_in = copy.deepcopy(FIN)
fin6_in.pop("_financials_revenue_intro_done", None)
fin6_in["_financials_revenue_intro_done"] = True
fin6, _y6 = _sync_financials_consult_persistence_state(
    financials_json=fin6_in, financials_year1_json={},
    people_json=None, ops_json=OPS)
st6 = fin6.get("_coherence") or {}
check("D6 the Recalc pass itself stamps the live eval (production chain)",
      isinstance(st6.get("eval"), dict) and st6["eval"].get("q11") is not None)

# D7: walk narrative state is never moved by the refresh.
fin7_in = copy.deepcopy(FIN)
fin7_in["_coherence"].update({"status": "walking", "gap_initial": 999.0,
                              "rounds_done": ["pricing"]})
fin7 = refresh_eval_stamps(fin7_in, ops_json=OPS, financials_year1_json={})
st7 = fin7.get("_coherence") or {}
check("D7 status/gap_initial/rounds_done untouched by the display refresh",
      st7.get("status") == "walking" and st7.get("gap_initial") == 999.0
      and st7.get("rounds_done") == ["pricing"])

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
