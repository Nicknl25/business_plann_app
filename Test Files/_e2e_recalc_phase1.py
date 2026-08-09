"""THE RECALC phase 1 - E2E (engine-read field assertions, per the
CW-023 permanent lesson).

Production path: any turn -> _sync_financials_consult_persistence_state
(now THE RECALC: people -> payroll rollup -> owner mirror -> year1 ->
families) -> single persist. RED evidence = the live findings: non-owner
wage corrections recomputed NOTHING (three layers held three payrolls);
payroll_adjustment had ZERO post-intake readers; blocked turns dropped
same-turn ops/people writes.
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


import inspect  # noqa: E402

from api_handlers.intake_consult import (  # noqa: E402
    _RECALC_DERIVED_FINANCIALS_FIELDS,
    _apply_scoped_patch,
    _coherence_blocked_response,
    _sync_financials_consult_persistence_state,
)

# The Sparrow shape (the CW-023 live case), with a NON-OWNER wage
# correction applied on the people side - the residual hole.
PPL = {"people": [
    {"role_title": "Owner & Lead Cleaner", "annual_wage": 50400.0,
     "wage_source": "client_override"},
    {"role_title": "Lead Cleaner & Trainer", "annual_wage": 40000.0,  # was 31,000
     "wage_source": "client_override"},
], "rest_of_team_payroll_year1": 62000.0}
FIN = {"baseline_payroll_year1": 143400.0, "current_payroll": 143400.0,
       "payroll_total_year1": 143400.0, "owner_compensation": 4200.0,
       "payroll_basis_people_roles": [
           {"role_title": "Owner & Lead Cleaner", "annual_wage": 50400.0,
            "year1_payroll_amount": 50400.0, "months_counted_year1": 12},
           {"role_title": "Lead Cleaner & Trainer", "annual_wage": 31000.0,
            "year1_payroll_amount": 31000.0, "months_counted_year1": 12}],
       "_financials_revenue_intro_done": False}

# R1: NON-OWNER wage correction -> the Recalc restamps EVERY engine-read
# field (was: stale forever; gate on 143,400, engine on 143,400, but the
# corrected 152,400 nowhere).
ppl1 = copy.deepcopy(PPL)
fin1, _y1 = _sync_financials_consult_persistence_state(
    financials_json=copy.deepcopy(FIN), financials_year1_json={},
    people_json=ppl1, ops_json={})
check("R1 non-owner wage correction restamps the FULL rollup "
      f"(current_payroll {fin1.get('current_payroll'):,.0f} = 152,400)",
      fin1["current_payroll"] == 152400.0
      and fin1["payroll_total_year1"] == 152400.0
      and fin1["baseline_payroll_year1"] == 152400.0)
_lead = next(r for r in fin1["payroll_basis_people_roles"]
             if "Trainer" in str(r.get("role_title")))
check("R1b basis row coherent (annual_wage == year1_payroll_amount == 40,000)",
      _lead["annual_wage"] == 40000.0 and _lead["year1_payroll_amount"] == 40000.0)
check("R1c owner mirror intact ($4,200/mo)",
      fin1["owner_compensation"] == 4200.0)

# R2: payroll_adjustment FOLD (Nick-ruled): the walk's delta becomes
# people truth - rest-of-team absorbs, field retires, rollup = engine
# number everywhere ("converged on one, built on another" dies).
ppl2 = copy.deepcopy(PPL)
fin2_in = copy.deepcopy(FIN)
fin2_in["payroll_adjustment"] = -20000.0
fin2, _y2 = _sync_financials_consult_persistence_state(
    financials_json=fin2_in, financials_year1_json={},
    people_json=ppl2, ops_json={})
check("R2 fold: rest-of-team absorbs the walk delta (62,000 -> 42,000)",
      ppl2["rest_of_team_payroll_year1"] == 42000.0)
check("R2b adjustment retired to 0; rollup = the folded truth (132,400) "
      "in EVERY engine-read field",
      fin2["payroll_adjustment"] == 0.0
      and fin2["current_payroll"] == 132400.0
      and fin2["payroll_total_year1"] == 132400.0
      and fin2["baseline_payroll_year1"] == 132400.0)

# R2c: a delta deeper than rest-of-team scales non-owner wages
# proportionally (consented via the accepted option); owner untouched.
ppl2c = copy.deepcopy(PPL)
fin2c_in = copy.deepcopy(FIN)
fin2c_in["payroll_adjustment"] = -82000.0  # rest 62k + 20k more
fin2c, _ = _sync_financials_consult_persistence_state(
    financials_json=fin2c_in, financials_year1_json={},
    people_json=ppl2c, ops_json={})
check("R2c deep fold: rest -> 0, non-owner wage scales (40,000 -> 20,000), "
      "owner untouched (50,400)",
      ppl2c["rest_of_team_payroll_year1"] == 0.0
      and ppl2c["people"][1]["annual_wage"] == 20000.0
      and ppl2c["people"][0]["annual_wage"] == 50400.0)

# R3: derived twins are UNPATCHABLE (the generalized opex model).
_bf, _op, _mk, _pp, fin3, _ff = _apply_scoped_patch(
    {"financials.current_payroll": 999.0,
     "financials.payroll_total_year1": 999.0,
     "financials.baseline_payroll_year1": 999.0,
     "financials.other_opex_absolute": 999.0,
     "financials.current_cogs": 999.0,
     "financials.marketing_percent_of_revenue": 0.99,
     "financials.cash_on_hand": 5000.0},
    business_facts={}, ops_json={}, market_json={},
    people_json={}, financials_json={"current_payroll": 143400.0},
    fulfillment_json={})
check("R3 derived twins unpatchable; sources still patchable "
      "(cash landed, payroll echo did not)",
      fin3["current_payroll"] == 143400.0 and "current_cogs" not in fin3
      and fin3.get("cash_on_hand") == 5000.0)
check("R3b the unpatchable set covers the full derived family",
      {"current_payroll", "payroll_total_year1", "baseline_payroll_year1",
       "payroll_basis_people_roles", "other_opex_absolute", "current_cogs",
       "cogs_total_year1", "marketing_percent_of_revenue",
       "owner_compensation"} <= set(_RECALC_DERIVED_FINANCIALS_FIELDS))

# R4: the blocked-turn persist carries every touched section.
_sig = inspect.signature(_coherence_blocked_response)
check("R4 blocked-response persists ops/people/year1 (single-persist rule)",
      all(k in _sig.parameters for k in
          ("ops_json", "people_json", "financials_year1_json")))

# R5: guards - empty people never zeroes stated payroll; no-substance
# drafts skip the payroll sub-graph entirely.
fin5, _ = _sync_financials_consult_persistence_state(
    financials_json={"current_payroll": 88000.0, "payroll_total_year1": 88000.0},
    financials_year1_json={}, people_json={"people": []}, ops_json={})
check("R5 empty people leaves stated payroll untouched (88,000)",
      fin5["current_payroll"] == 88000.0)

# R6: idempotence - a second pass changes nothing (spreadsheet law).
fin6a, y6a = _sync_financials_consult_persistence_state(
    financials_json=copy.deepcopy(FIN), financials_year1_json={},
    people_json=copy.deepcopy(PPL), ops_json={})
fin6b, y6b = _sync_financials_consult_persistence_state(
    financials_json=copy.deepcopy(fin6a), financials_year1_json=copy.deepcopy(y6a),
    people_json=copy.deepcopy(PPL), ops_json={})
check("R6 the Recalc is idempotent", fin6a == fin6b and y6a == y6b)

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
