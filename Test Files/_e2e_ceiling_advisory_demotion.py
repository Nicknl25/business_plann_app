"""CW-017 (a) stage-ramp ceiling advisory demotion - targeted RED/GREEN.

The Vanguard failure, exact: the Python builder took the MANAGER'S
judged per-quarter fitted wall as cost authority and authored cogs_max
0.81 (Q8-10) -> 0.85 (Q20); the tool's cohort-band check vetoed against
robust_max 0.805716 -> fail_round1_set_tool_rejected -> run dead. The
informant vetoed the owner - the exact inversion Wave 2 demoted for
floors; ceilings never got the demotion (confirmed unfired member, not
a regression: 1b47199 touched only the floor branch).

GREEN: Q8-10 (delta 0.0043) suppressed as 2dp GRID ROUNDING (within
half a grid unit of the band edge - the author's own round() cannot
manufacture a breach); Q11+ (deltas 0.014-0.044) demote to ADVISORY
because the manager's wall covers them.

NON-NEGOTIABLE NEGATIVE CONTROLS (Nick):
 - raw-cohort fallback (no manager wall) -> the veto STAYS;
 - a value above the manager's own wall -> veto stays even with walls.
"""
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")

from client_intake_and_finmo.post_intake_amalgamated.tools.set_stage_ramp_contract import (  # noqa: E402
    _check_band_violations,
    _manager_ceiling_walls,
)

results = []


def check(label, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label)


# The Vanguard grid, verbatim from the failure record.
VANGUARD_COGS_MAX = {**{q: 0.78 for q in range(1, 8)},
                     8: 0.81, 9: 0.81, 10: 0.81,
                     11: 0.82, 12: 0.82, 13: 0.82,
                     14: 0.83, 15: 0.83, 16: 0.83,
                     17: 0.84, 18: 0.84, 19: 0.84, 20: 0.85}
CONTRACT = {"quarter_ramp_grid": [
    {"q": q, "cogs_max": VANGUARD_COGS_MAX[q]} for q in range(1, 21)
]}
BANDS = {"stage_ramp::cogs_max": {"robust_min": 0.35, "robust_max": 0.805716}}

# The manager's fitted wall - the authority the builder followed.
MODEL_INPUT = {"solver_input": {"fitted_envelope_per_q": {
    "cogs_percent_of_revenue": {"max": {str(q): VANGUARD_COGS_MAX[q] for q in range(1, 21)}},
}}}

walls = _manager_ceiling_walls(MODEL_INPUT)
check("walls extracted from fitted_envelope_per_q", walls.get("cogs_max", {}).get(20) == 0.85)

violations, advisories = _check_band_violations(CONTRACT, BANDS, manager_walls=walls)
ceiling_viol = [v for v in violations if v["code"] == "stage_ramp_above_band_max"]
ceiling_adv = [a for a in advisories if a["code"] == "stage_ramp_ceiling_above_cohort_band_advisory"]
check("Vanguard grid: ZERO ceiling vetoes (run survives)", not ceiling_viol)
check("Q8-10 phantom rounding breaches fully suppressed",
      not any(e["quarter_index"] in (8, 9, 10) for e in ceiling_adv + ceiling_viol))
check("Q11-20 genuine manager-above-cohort -> advisories (10 quarters)",
      sorted(a["quarter_index"] for a in ceiling_adv) == list(range(11, 21)))
check("advisory records the manager wall",
      all("manager_wall" in a for a in ceiling_adv))

# NEG 1 (non-negotiable): NO manager wall -> the raw-cohort veto stays.
viol_nc, adv_nc = _check_band_violations(CONTRACT, BANDS, manager_walls={})
check("NEG raw-cohort fallback still VETOES Q11-20",
      sorted(v["quarter_index"] for v in viol_nc if v["code"] == "stage_ramp_above_band_max")
      == list(range(11, 21)))
check("NEG fallback also suppresses only the rounding phantoms (Q8-10)",
      not any(v["quarter_index"] in (8, 9, 10) for v in viol_nc))

# NEG 2: value exceeding the manager's own wall -> veto even with walls.
# (The check numbers quarters positionally; a one-row grid is quarter 1.)
CONTRACT_HOT = {"quarter_ramp_grid": [{"q": 1, "cogs_max": 0.95}]}
walls_low = {"cogs_max": {1: 0.85}}
viol_hot, adv_hot = _check_band_violations(CONTRACT_HOT, BANDS, manager_walls=walls_low)
check("NEG above-manager-wall value still VETOES",
      any(v["code"] == "stage_ramp_above_band_max" and v["quarter_index"] == 1 for v in viol_hot)
      and not adv_hot)

# Floors unchanged: a floor below robust_min stays an advisory (Wave 2).
CONTRACT_FLOOR = {"quarter_ramp_grid": [{"q": 11, "ni_floor": 0.01}]}
BANDS_FLOOR = {"stage_ramp::ni_floor": {"robust_min": 0.05, "robust_max": 0.40}}
viol_f, adv_f = _check_band_violations(CONTRACT_FLOOR, BANDS_FLOOR, manager_walls={})
check("Wave-2 floor demotion unchanged",
      not viol_f and any(a["code"] == "stage_ramp_floor_below_cohort_band_advisory" for a in adv_f))

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
