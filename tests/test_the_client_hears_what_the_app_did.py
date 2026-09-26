"""ONE MOUTH (Nick 2026-09-25).

  "The LLM talks. Not the machine. NOTHING IS APPENDED TO THE MODEL'S REPLY.
   Not a receipt, not a note, not a correction, not a 'couldn't apply that'.
   Ever. What the code wants to say goes INTO the consultant call as material
   and the model writes one sentence that carries it."

Two conditions, both pinned here:

  1. THE MODEL NEVER SEES A FIELD NAME. Given the key it will say the key -
     that is how "baseline cogs, cogs basis naics, cogs basis rationale ..."
     reached a client in one parenthetical.

  2. AN ACKNOWLEDGEMENT MUST NOT DEPEND ON A LINE EXISTING PER FIELD. Today a
     field with no line gets silence - the capital-lease answer was the only
     financial answer in its stage with no receipt. So every leaf that can
     hold a value is either given words or DECLARED unspoken; a leaf in
     neither is a coverage bug, and this test is where it shows up.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "python",
                             "client_intake_and_finmo"))

from api_handlers import intake_consult as IC  # noqa: E402

# Every numeric leaf that actually held a value across the last 120 COMPLETED
# drafts, measured 2026-09-25. This is the real write surface, not a guess.
LEAVES_IN_THE_WILD = [
    "unit_price", "units_per_week_capacity", "units_per_period_capacity",
    "units_per_month_capacity", "utilization_rate",
    "operating_periods_per_year", "operating_weeks_per_year",
    "operating_months_per_year", "concurrent_capacity_units",
    "annual_turns_per_year", "avg_units_per_week_year1",
    "avg_units_per_month_year1", "avg_units_per_period_year1",
    "avg_active_units_year1", "annual_units_year1",
    "annual_completed_units_year1", "revenue_total_year1",
    "company_revenue_total_year1", "cogs_percent_of_line_revenue",
    "current_revenue", "current_cogs", "current_payroll",
    "payroll_total_year1", "rest_of_team_payroll_year1", "owner_pay_monthly",
    "total_team_payroll", "annual_wage", "owner_compensation",
    "year1_payroll_amount", "months_until_hire",
    "marketing_total_year1", "marketing_percent_of_revenue",
    "monthly_rent_expense", "other_operating_expense", "other_opex_absolute",
    "current_num_employees", "current_employee_count",
    "total_debt_outstanding", "annual_interest_payment",
    "annual_principal_payment", "cash_on_hand", "ar_balance", "ap_balance",
    "inventory_balance", "capital_lease_obligation",
    "cogs_percent_of_revenue", "cogs_total_year1",
    "income_min", "income_max", "age_min", "age_max",
    "funding_split_debt_share", "maintenance_capex_rate", "timing_months_max",
    # declared unspoken
    "confidence", "version", "asked_turn_index", "proposal_cap",
    "months_counted_year1", "baseline_payroll_year1", "baseline_marketing",
    "baseline_marketing_percent", "baseline_cogs", "baseline_cogs_percent",
    "marketing_adjustment", "payroll_adjustment", "cogs_adjustment",
]

# the eight that reached a real client in one sentence
THE_EIGHT = ["baseline_cogs", "baseline_cogs_percent", "cogs_adjustment",
             "cogs_basis", "cogs_basis_naics", "cogs_basis_rationale",
             "cogs_basis_years_used", "cogs_fit_band"]


class TheClientHearsWhatTheAppDid(unittest.TestCase):

  def test_every_leaf_is_either_given_words_or_declared_unspoken(self):
    """Nick's second condition. A leaf in neither table would be
    acknowledged with silence, which is the capital-lease gap again."""
    gap = [k for k in LEAVES_IN_THE_WILD
           if not IC._client_label(k) and k not in IC._INTERNAL_NOT_SPOKEN]
    self.assertEqual(
        [], gap,
        "these can hold a value but have no words and are not declared "
        "unspoken - a client would simply never be told: %s" % gap)

  def test_a_label_is_never_the_key_wearing_spaces(self):
    """The old fallback was LABELS.get(f, f.replace("_", " ")). That is not
    a label, it is the key with the underscores taken out."""
    for key in LEAVES_IN_THE_WILD:
      label = IC._client_label(key)
      if label is None:
        continue
      self.assertNotEqual(label, key.replace("_", " "),
                          "%r is the key, not English" % label)
      self.assertNotIn("_", label, "%r still carries a field name" % label)

  def test_the_eight_names_that_reached_a_client_are_unsayable(self):
    for key in THE_EIGHT:
      self.assertIsNone(IC._client_label(key),
                        "%r can still be said to a client" % key)

  def test_material_drops_a_fact_it_has_no_words_for(self):
    m = IC.new_turn_material()
    IC.add_material(m, "not_landed", field="cogs_basis_naics")
    self.assertEqual([], m, "an unsayable field became material: %s" % m)

  def test_material_carries_english_and_never_the_key(self):
    m = IC.new_turn_material()
    IC.add_material(m, "landed", field="rest_of_team_payroll_year1",
                    value=620000)
    IC.add_material(m, "landed", field="capital_lease_obligation",
                    value=48000)
    self.assertEqual(2, len(m))
    for entry in m:
      self.assertIn("about", entry)
      self.assertNotIn("_", entry["about"])
    self.assertEqual(620000, m[0]["value"])

  def test_a_capital_lease_answer_can_be_acknowledged(self):
    """The defect in its own words: every financial answer in that stage got
    a receipt naming the field and the value except this one."""
    self.assertIsNotNone(IC._client_label("capital_lease_obligation"))


if __name__ == "__main__":
  unittest.main()
