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
# COGS dollars are NOT in the set (Nick's basis ruling, proven by the
# keystone F&F rerun): a stated dollar is a capture SOURCE - the write
# lands and tags dollars-primary; blanket-dropping it silently
# discarded her stated $5,900 at the capture moment.
_bf, _op, _mk, _pp, fin3, _ff = _apply_scoped_patch(
    {"financials.current_payroll": 999.0,
     "financials.payroll_total_year1": 999.0,
     "financials.baseline_payroll_year1": 999.0,
     "financials.other_opex_absolute": 999.0,
     "financials.current_cogs": 5900.0,
     "financials.marketing_percent_of_revenue": 0.99,
     "financials.cash_on_hand": 5000.0},
    business_facts={}, ops_json={}, market_json={},
    people_json={}, financials_json={"current_payroll": 143400.0},
    fulfillment_json={})
check("R3 derived twins unpatchable; sources still patchable "
      "(cash + stated cogs dollars landed, payroll echo did not)",
      fin3["current_payroll"] == 143400.0 and fin3.get("current_cogs") == 5900.0
      and fin3.get("cash_on_hand") == 5000.0)
check("R3b the unpatchable set covers the derived family and ONLY it "
      "(cogs dollar fields are capture sources)",
      {"current_payroll", "payroll_total_year1", "baseline_payroll_year1",
       "payroll_basis_people_roles", "other_opex_absolute",
       "marketing_percent_of_revenue",
       "owner_compensation"} <= set(_RECALC_DERIVED_FINANCIALS_FIELDS)
      and "current_cogs" not in _RECALC_DERIVED_FINANCIALS_FIELDS
      and "cogs_total_year1" not in _RECALC_DERIVED_FINANCIALS_FIELDS)

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

# R5b: ONE-HOME ops drivers (keystone F&F finding): a flat-key driver
# write on a single-product model lands on the product row every
# reader actually reads - never a second home (price 60/capacity 40
# sat in the flat fields while the product kept 112/30 and the
# pipeline kept building on the corrected-away numbers).
_ops_fork = {"unit_price": 112, "units_per_week_capacity": 30,
             "lob_models": [{"lob_name": "Primary line of business",
                             "products": [{"product_name": "Mobile grooming appointment",
                                           "unit_price": 112,
                                           "units_per_period_capacity": 30,
                                           "units_per_week_capacity": 30,
                                           "utilization_rate": 0.7,
                                           "operating_periods_per_year": 52}]}]}
_bf5, ops5b, _mk5, _pp5, _fin5b, _ff5 = _apply_scoped_patch(
    {"ops.unit_price": 60.0, "ops.units_per_week_capacity": 40.0,
     "ops.units_per_period_capacity": 40.0},
    business_facts={}, ops_json=_ops_fork, market_json={},
    people_json={}, financials_json={}, fulfillment_json={})
_p5b = ops5b["lob_models"][0]["products"][0]
check("R5b flat ops driver write lands on the PRODUCT row (60/40 in "
      "both homes, no fork)",
      _p5b["unit_price"] == 60.0
      and _p5b["units_per_period_capacity"] == 40.0
      and ops5b["unit_price"] == 60.0)

# R6: idempotence - a second pass changes nothing (spreadsheet law).
fin6a, y6a = _sync_financials_consult_persistence_state(
    financials_json=copy.deepcopy(FIN), financials_year1_json={},
    people_json=copy.deepcopy(PPL), ops_json={})
fin6b, y6b = _sync_financials_consult_persistence_state(
    financials_json=copy.deepcopy(fin6a), financials_year1_json=copy.deepcopy(y6a),
    people_json=copy.deepcopy(PPL), ops_json={})
check("R6 the Recalc is idempotent", fin6a == fin6b and y6a == y6b)

# ============ BASIS RULINGS (Nick): stated durable, derived live ======
# B1: dollars-basis COGS is DURABLE under revenue movement (the F&F
# $5,900 -> $14,676 class dies for stated-dollar clients).
fin_b1 = {"cogs_basis": "dollars", "current_cogs": 5900.0,
          "cogs_total_year1": 5900.0, "cogs_percent_of_revenue": 0.12,
          "_financials_revenue_intro_done": False}
y1_b1 = {"company_revenue_total_year1": 122304.0}
fin_b1o, _ = _sync_financials_consult_persistence_state(
    financials_json=fin_b1, financials_year1_json=y1_b1,
    people_json=None, ops_json={})
check("B1 stated COGS dollars durable under 2.5x revenue ($5,900 stays; "
      "ratio re-derives to 4.8%)",
      fin_b1o["current_cogs"] == 5900.0
      and abs(fin_b1o["cogs_percent_of_revenue"] - 5900.0 / 122304.0) < 1e-9)

# B2: ratio-basis (stated percent) keeps ratio-primary (variable costs
# scale with revenue - status quo for percent-stating clients).
fin_b2 = {"cogs_basis": "ratio", "cogs_percent_of_revenue": 0.12,
          "current_cogs": 5900.0, "_financials_revenue_intro_done": False}
fin_b2o, _ = _sync_financials_consult_persistence_state(
    financials_json=fin_b2, financials_year1_json=y1_b1,
    people_json=None, ops_json={})
check("B2 stated ratio stays ratio-primary (12% of $122,304 = $14,676)",
      abs(fin_b2o["current_cogs"] - 0.12 * 122304.0) < 0.01)

# B3: legacy (no tag) preserves old ratio-primary behavior.
fin_b3 = {"cogs_percent_of_revenue": 0.12, "current_cogs": 5900.0,
          "_financials_revenue_intro_done": False}
fin_b3o, _ = _sync_financials_consult_persistence_state(
    financials_json=fin_b3, financials_year1_json=y1_b1,
    people_json=None, ops_json={})
check("B3 legacy untagged drafts keep ratio-primary (status quo)",
      abs(fin_b3o["current_cogs"] - 0.12 * 122304.0) < 0.01)

# B4: marketing baseline refreshes LIVE from the model; the stated
# total stays durable; adjustment computes against the live baseline.
fin_b4 = {"marketing_total_year1": 600.0, "baseline_marketing": 5000.0,
          "baseline_marketing_percent": 0.05,
          "_financials_revenue_intro_done": False}
fin_b4o, _ = _sync_financials_consult_persistence_state(
    financials_json=fin_b4, financials_year1_json=y1_b1,
    marketing_model_json={"baseline_marketing": 8000.0,
                          "baseline_marketing_percent": 0.0654},
    people_json=None, ops_json={})
check("B4 marketing baseline LIVE (5,000 stale copy -> 8,000 model); "
      "stated $600 durable; adjustment vs live baseline",
      fin_b4o["baseline_marketing"] == 8000.0
      and fin_b4o["marketing_total_year1"] == 600.0
      and fin_b4o["marketing_adjustment"] == 600.0 - 8000.0)

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
