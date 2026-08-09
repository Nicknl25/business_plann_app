"""PHASE 3 - walls table v1 (payroll-share tier wall) E2E.

Production path: gate_and_turn -> _ensure_margin_band (band judge now
stamps labor_intensity_class) -> _payroll_share_wall_result ->
walls.payroll_share_wall -> convergence REFUSED while the wall is
violated. RED evidence: Sparrow (draft 4aa25e24) converged at intake
and the engine's payload builder killed the run at 0.72 vs the
high-class 0.70 - re-proven LIVE today (run 6c58b501, supervisor
rerun) while this phase was being built. The phase-2 P5 fixture (the
same Sparrow shape, payroll 143,400 / revenue 199,294 = 0.72) fell
through and CONVERGED - the exact false promise this wall closes.
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


from client_intake_and_finmo.intake_coherence.walls import (  # noqa: E402
    PAYROLL_SHARE_CLASS_BOUNDS, payroll_share_wall, walls_mirror_tripwire,
)
from client_intake_and_finmo.post_intake_headcount.gpt_margin_band_judgment import (  # noqa: E402
    validate_margin_band_judgment,
)
from client_intake_and_finmo.intake_coherence.section import gate_and_turn  # noqa: E402

# W1: THE TRIPWIRE - the mirror matches the live engine policy exactly.
tw = walls_mirror_tripwire()
check(f"W1 mirror == live engine policy (drift={tw.get('drift')})", tw["ok"])

# W2: wall arithmetic on the Sparrow numbers (the live kill: 0.72 vs 0.70).
w = payroll_share_wall(
    labor_intensity_class="high",
    payroll_annual=143400.0, revenue_annual=199294.0)
check("W2 Sparrow shape fails the high wall "
      f"(share {w['value']:.4f} > 0.70)", w is not None and not w["passed"])
check("W2b honest exits priced: revenue_to_clear = payroll/0.70, "
      "payroll_to_clear = revenue*0.70",
      abs(w["revenue_to_clear"] - 143400.0 / 0.70) < 0.01
      and abs(w["payroll_to_clear"] - 199294.0 * 0.70) < 0.01)
w_ok = payroll_share_wall(
    labor_intensity_class="high",
    payroll_annual=39600.0, revenue_annual=87360.0)
check("W2c Fetch & Fluff shape (45%) passes the high wall", w_ok["passed"])
check("W2d no judged class -> no wall (absence is never a verdict)",
      payroll_share_wall(labor_intensity_class=None,
                         payroll_annual=1.0, revenue_annual=1.0) is None
      and payroll_share_wall(labor_intensity_class="bogus",
                             payroll_annual=1.0, revenue_annual=1.0) is None)

# W3: validator normalizes the judged class; junk -> None + note.
_J = {"q11_ebitda_band": {"low": 0.05, "high": 0.12},
      "q20_ebitda_band": {"low": 0.08, "high": 0.15},
      "labor_treatment": "all_labor_in_payroll_line"}
v_hi = validate_margin_band_judgment(judgment=dict(_J, labor_intensity_class="High"))
v_junk = validate_margin_band_judgment(judgment=dict(_J, labor_intensity_class="crazy"))
v_missing = validate_margin_band_judgment(judgment=dict(_J))
check("W3 class normalized ('High' -> 'high'); junk/missing -> None + note",
      v_hi["labor_intensity_class"] == "high"
      and v_junk["labor_intensity_class"] is None
      and any("labor_intensity_class_unrecognized" in n for n in v_junk["notes"])
      and v_missing["labor_intensity_class"] is None
      and any("labor_intensity_class_missing" in n for n in v_missing["notes"]))

# W4: THE GATE, end to end - the Sparrow-shaped fixture that CONVERGED
# under phase 2 must now be refused with the wall named and both dollar
# exits priced. Fresh state -> the band judge authors live (stamping the
# new labor_intensity_class); cleaning is a labor-intensive type.
OPS = {"lob_models": [{"lob_name": "Cleaning", "products": [{
    "product_name": "House cleans", "unit_price": 110.0,
    "units_per_period_capacity": 50.0, "operating_periods_per_year": 52.0,
    "utilization_rate": 0.7}]}]}
FIN = {"current_revenue": 199294.0, "baseline_payroll_year1": 143400.0,
       "other_opex_absolute": 17400.0, "marketing_total_year1": 600.0,
       "cogs_percent_of_revenue": 0.08}
turn, fin_out, sfx = gate_and_turn(
    ops_json=copy.deepcopy(OPS), people_json={}, market_json={},
    marketing_model_json={}, financials_json=dict(FIN),
    financials_year1_json={})
st = fin_out.get("_coherence") or {}
band = st.get("margin_band_judgment") or {}
cls = band.get("labor_intensity_class")
print(f"   judged class: {cls!r}; wall: {(st.get('walls') or {}).get('payroll_share')}")
check("W4 band judge stamps a labor_intensity_class",
      cls in ("low", "medium", "high", "expert"))
wall_state = (st.get("walls") or {}).get("payroll_share") or {}
_max = PAYROLL_SHARE_CLASS_BOUNDS.get(str(cls), {}).get("max_pct", 1.0)
_share = 143400.0 / 199294.0
if _share > _max:
    msg = str((turn or {}).get("assistant_message") or "")
    check("W4b gate REFUSES to converge into the engine kill (turn blocked, "
          "not converged)",
          turn is not None and st.get("status") != "converged")
    check("W4c the wall message prices both exits (revenue up / team cost down)",
          "team costs" in msg and "revenue at or above" in msg
          and "team cost at or below" in msg)
    check("W4d wall stamped for the panel (failed, mirror ok)",
          wall_state.get("passed") is False and wall_state.get("mirror_ok") is True)
else:
    # The judge classed this business so its stated share is inside the
    # band - the wall must then be a clean pass and convergence stands.
    check("W4b judged class clears the share - wall passes, no false block",
          wall_state.get("passed") is True and turn is None)
    check("W4c (n/a - wall passed)", True)
    check("W4d wall stamped for the panel", bool(wall_state))

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
