"""PAYROLL CAUSE-SPLIT E2E (Nick-ruled Option A + sub-ruling ii).

Production paths: _costs_round -> payroll_cause_split -> the honest
lever only; apply_router_patch -> remaining -> _apply_scoped_patch
(owner one-door / phase_planned_hires pseudo-field) -> THE RECALC
restamps the rollup; the fold holds remainders that would touch named
people; the wall message names the cause-appropriate exit.
RED evidence: the old aggregate move was a proportional wage cut
across real staff (cut-insurance) and a silent NO-OP on owner-only
teams.
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
    _apply_scoped_patch, _sync_financials_consult_persistence_state,
)
from client_intake_and_finmo.intake_coherence.controller import (  # noqa: E402
    Thresholds, _costs_round, payroll_cause_split,
)
from client_intake_and_finmo.intake_coherence.evaluator import (  # noqa: E402
    basis_from_intake,
)
from client_intake_and_finmo.intake_coherence.section import (  # noqa: E402
    apply_router_patch,
)

# Basis-row fixtures per cause.
ROWS_OWNER = [
    {"source": "people", "role_title": "Owner and Groomer",
     "annual_wage": 66000.0, "year1_payroll_amount": 66000.0},
    {"source": "rest_of_team_payroll", "role_title": "Rest of team (client-stated total)",
     "annual_wage": 12000.0, "year1_payroll_amount": 12000.0},
]
ROWS_PLANNED = [
    {"source": "people", "role_title": "Owner", "annual_wage": 30000.0,
     "year1_payroll_amount": 30000.0},
    {"source": "inferred_role", "role_title": "Senior Stylist",
     "annual_wage": 48000.0, "months_until_hire": 2,
     "year1_payroll_amount": 40000.0},
]
ROWS_STAFFED = [
    {"source": "people", "role_title": "Owner & Lead Cleaner",
     "annual_wage": 50400.0, "year1_payroll_amount": 50400.0},
    {"source": "people", "role_title": "Lead Cleaner & Trainer",
     "annual_wage": 31000.0, "year1_payroll_amount": 31000.0},
    {"source": "rest_of_team_payroll", "role_title": "Rest of team (client-stated total)",
     "annual_wage": 62000.0, "year1_payroll_amount": 62000.0},
]

# C1-C3: the classifier names the dominant cause.
c1 = payroll_cause_split({"payroll_basis_people_roles": ROWS_OWNER})
c2 = payroll_cause_split({"payroll_basis_people_roles": ROWS_PLANNED})
c3 = payroll_cause_split({"payroll_basis_people_roles": ROWS_STAFFED})
check("C1 owner-dominated classified (66k owner vs 12k rest)",
      c1["kind"] == "owner_dominated" and c1["owner_annual"] == 66000.0)
check("C2 planned-hires classified (40k phasable vs 30k owner)",
      c2["kind"] == "planned_hires" and c2["phasable_annual"] == 40000.0)
check("C3 staffed classified (93k staffed+rest vs 50.4k owner)",
      c3["kind"] == "staffed" and c3["staffed_annual"] == 93000.0)

# Shared round fixtures: a gap + a team floor below current payroll.
OPS = {"lob_models": [{"lob_name": "L", "products": [{
    "product_name": "unit", "unit_price": 100.0,
    "units_per_period_capacity": 40.0, "operating_periods_per_year": 52.0,
    "utilization_rate": 0.7}]}]}
# band_low high enough that every cause fixture carries a live gap
# (rounds only build while a gap is open).
TH = Thresholds(gm_floor=0.3, burden_max=0.85, band_low=0.55,
                ni_floor=0.02, band_high=0.60, judged=True)
BOUNDS = {"existing_lines": [], "cost_floors": {},
          "team": {"min_annual_payroll": 48000.0}}


def _fin(rows, total):
    return {"current_revenue": 145600.0, "baseline_payroll_year1": total,
            "current_payroll": total, "payroll_total_year1": total,
            "other_opex_absolute": 40000.0, "marketing_total_year1": 600.0,
            "cogs_percent_of_revenue": 0.08,
            "payroll_basis_people_roles": copy.deepcopy(rows)}


def _round_for(rows, total):
    fin = _fin(rows, total)
    basis = basis_from_intake(financials_json=fin, ops_json=OPS,
                              financials_year1_json={})
    return _costs_round(basis, TH, BOUNDS, fin)


# C4: owner-dominated -> owner-draw move (one-door patch), never a
# generic team cut.
r4 = _round_for(ROWS_OWNER, 78000.0)
mv4 = {k: m for o in (r4 or {}).get("options", []) for k, m in (o.get("moves") or {}).items()}
check("C4 owner-dominated offers OWNER-DRAW via the one door "
      f"(people.owner_pay_monthly; moves={sorted(mv4)})",
      "owner_draw" in mv4 and "payroll" not in mv4
      and mv4["owner_draw"]["field_patch"]["field"] == "owner_pay_monthly")

# C5: planned hires -> hire-timing move (phases starts, cuts no one).
r5 = _round_for(ROWS_PLANNED, 70000.0)
mv5 = {k: m for o in (r5 or {}).get("options", []) for k, m in (o.get("moves") or {}).items()}
check("C5 planned hires offer HIRE TIMING (phase_planned_hires)",
      "hire_timing" in mv5
      and mv5["hire_timing"]["field_patch"]["field"] == "phase_planned_hires")

# C6: staffed -> NO payroll-family move at all (revenue levers are the
# closers; the old proportional cut is dead as an offer).
r6 = _round_for(ROWS_STAFFED, 143400.0)
mv6 = {k: m for o in (r6 or {}).get("options", []) for k, m in (o.get("moves") or {}).items()}
check("C6 staffed team: NO machine payroll cut offered "
      f"(moves={sorted(mv6)})",
      not any(k in mv6 for k in ("payroll", "owner_draw", "hire_timing")))

# C7: APPLY owner-draw end to end: option -> remaining -> scoped apply
# one-door -> Recalc restamps the rollup.
fin7 = _fin(ROWS_OWNER, 78000.0)
ppl7 = {"people": [{"role_title": "Owner and Groomer", "annual_wage": 66000.0,
                    "wage_source": "client_override"}],
        "rest_of_team_payroll_year1": 12000.0}
fin7["_coherence"] = {"round": r4}
_opt7 = next(o for o in r4["options"] if "owner_draw" in (o.get("moves") or {}))
rem7, _ops7, fin7b, _n7 = apply_router_patch(
    patch={"coherence.option": _opt7["id"]}, ops_json=OPS, financials_json=fin7)
check("C7 owner-draw option routes to the one door (remaining carries "
      "people.owner_pay_monthly)", "people.owner_pay_monthly" in rem7)
_bf, _op, _mk, ppl7b, fin7c, _ff = _apply_scoped_patch(
    rem7, business_facts={}, ops_json=OPS, market_json={},
    people_json=ppl7, financials_json=fin7b, fulfillment_json={})
fin7d, _ = _sync_financials_consult_persistence_state(
    financials_json=fin7c, financials_year1_json={},
    people_json=ppl7b, ops_json=OPS)
_expected_monthly = _opt7["moves"]["owner_draw"]["field_patch"]["value"]
check("C7b owner role updated + rollup restamped "
      f"(owner {_expected_monthly * 12:.0f}/yr; trio "
      f"{fin7d.get('payroll_total_year1'):.0f})",
      abs(ppl7b["people"][0]["annual_wage"] - _expected_monthly * 12) < 1.0
      and abs(fin7d["payroll_total_year1"] - (_expected_monthly * 12 + 12000.0)) < 1.0)

# C8: APPLY hire-timing: months pushed, rollup prorates down, no wage
# touched.
ppl8 = {"people": [{"role_title": "Owner", "annual_wage": 30000.0,
                    "wage_source": "client_override"}],
        "inferred_roles": [{"role_title": "Senior Stylist",
                            "annual_wage": 48000.0, "months_until_hire": 2}]}
_bf, _op, _mk, ppl8b, fin8b, _ff = _apply_scoped_patch(
    {"people.phase_planned_hires": {"months_add": 12}},
    business_facts={}, ops_json=OPS, market_json={},
    people_json=ppl8, financials_json=_fin(ROWS_PLANNED, 70000.0),
    fulfillment_json={})
fin8c, _ = _sync_financials_consult_persistence_state(
    financials_json=fin8b, financials_year1_json={},
    people_json=ppl8b, ops_json=OPS)
check("C8 hire timing: months_until_hire -> 12, year-1 payroll drops to "
      f"the owner alone (trio {fin8c.get('payroll_total_year1'):.0f} == 30,000), "
      "wage untouched (48,000)",
      ppl8b["inferred_roles"][0]["months_until_hire"] == 12
      and ppl8b["inferred_roles"][0]["annual_wage"] == 48000.0
      and abs(fin8c["payroll_total_year1"] - 30000.0) < 1.0)

# C9: SUB-RULING (ii) SURFACE - the held remainder reaches the very
# next gate message as the HOW question (live gate, real band author).
from client_intake_and_finmo.intake_coherence.section import gate_and_turn  # noqa: E402

fin9 = {"current_revenue": 145600.0, "baseline_payroll_year1": 42000.0,
        "current_payroll": 42000.0, "payroll_total_year1": 42000.0,
        "other_opex_absolute": 17400.0, "marketing_total_year1": 600.0,
        "cogs_percent_of_revenue": 0.08,
        "_payroll_fold_hold": {"unapplied": -20000.0}}
turn9, fin9b, sfx9 = gate_and_turn(
    ops_json=copy.deepcopy(OPS), people_json={}, market_json={},
    marketing_model_json={}, financials_json=fin9, financials_year1_json={})
_all_text = str((turn9 or {}).get("assistant_message") or "") + str(sfx9 or "")
check("C9 held remainder surfaces as the HOW question on the next gate "
      "message and the flag clears",
      "won't assume" in _all_text and "20,000" in _all_text
      and "_payroll_fold_hold" not in fin9b)

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
