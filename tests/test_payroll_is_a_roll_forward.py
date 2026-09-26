"""PAYROLL IS AN FTE ROLL-FORWARD, BY GROUP, BY QUARTER (Nick 2026-09-26).

Every payroll defect of 2026-09-25/26 came from one choice: the app authored
a `target_payroll_percent_of_revenue` and built a roster to hit it.
Bellweather's executive designed a 431,000 team and proved Q11 net margin
+7.0%; the GPT author picked 62%, the model carried her stated 482,000 x
load, and acceptance failed a plan the app had already solved.

Under a roll-forward that input does not exist. Payroll is FTE x salary and
the percentage is an OUTPUT. These are the identities that make it safe to
build a plan on.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "python",
                             "client_intake_and_finmo"))

from client_intake_and_finmo.post_intake_headcount import rollforward as RF  # noqa: E402

# groups in the CLIENT'S words - never a fixed industry list
BELLWEATHER = [
    {"group_name": "Owner and lead artisan", "opening_fte": 1.0,
     "average_annual_salary": 88000.0, "is_owner": True},
    {"group_name": "Studio manager", "opening_fte": 1.0,
     "average_annual_salary": 72000.0},
    {"group_name": "Glass artisans", "opening_fte": 6.0,
     "average_annual_salary": 53667.0},
]
KEIR = [
    {"group_name": "Owner and general manager", "opening_fte": 1.0,
     "average_annual_salary": 140000.0, "is_owner": True},
    {"group_name": "Shop foreman", "opening_fte": 1.0,
     "average_annual_salary": 95000.0},
    {"group_name": "Fabricators and fitters", "opening_fte": 9.0,
     "average_annual_salary": 68889.0},
]


def _grid(groups, **kw):
  kw.setdefault("horizon_quarters", 20)
  kw.setdefault("burden_rate", 0.22)
  kw.setdefault("annual_salary_increase", 0.03)
  return RF.build_group_rollforward(groups=groups, **kw)


class PayrollIsARollForward(unittest.TestCase):

  def test_the_three_identities_hold_every_group_every_quarter(self):
    for name, groups in (("Bellweather", BELLWEATHER), ("Keir", KEIR)):
      broken = RF.identities(_grid(groups))
      self.assertEqual([], broken, "%s: %s" % (name, broken[:3]))

  def test_year_one_reconciles_to_her_stated_payroll(self):
    """The stub is her opening team, so Q1 opens from reality and the
    stated-payroll door is true by construction, not by a tolerance."""
    for groups, stated in ((BELLWEATHER, 482000.0), (KEIR, 855000.0)):
      grid = _grid(groups)
      pay = RF.payroll_by_quarter(grid)
      year_one = sum(pay[q] for q in (1, 2, 3, 4))
      self.assertAlmostEqual(year_one, stated * 1.22, delta=stated * 0.005,
                             msg="year one %s vs stated %s loaded"
                                 % (year_one, stated))

  def test_the_executives_exits_actually_land(self):
    """The defect this replaces: an approved design that never reached a
    payroll row."""
    base = RF.payroll_by_quarter(_grid(BELLWEATHER))
    directive = {"groups": [{"group": "Glass artisans", "exits_q": {"2": 2}}]}
    after = RF.payroll_by_quarter(
        _grid(RF.apply_executive_design(BELLWEATHER, directive)))
    self.assertLess(sum(after[q] for q in (1, 2, 3, 4)),
                    sum(base[q] for q in (1, 2, 3, 4)),
                    "the executive's exits did not change payroll")
    self.assertEqual(
        [], RF.identities(_grid(RF.apply_executive_design(BELLWEATHER, directive))))

  def test_an_owner_can_never_be_cut(self):
    """Not a title-token exemption downstream - unrepresentable here."""
    directive = {"groups": [{"group": "Owner and lead artisan",
                             "exits_q": {"2": 1}}]}
    grid = _grid(RF.apply_executive_design(BELLWEATHER, directive))
    owner = [g for g in grid["groups"] if g["is_owner"]][0]
    for row in owner["quarters"]:
      self.assertEqual(0.0, row[RF.ROW_EXITS])
      self.assertEqual(1.0, row[RF.ROW_ENDING])
    self.assertEqual([], RF.identities(grid))

  def test_nobody_is_ever_shrunk_below_a_whole_person(self):
    """Nick 2026-08-28: payroll is NOT clipped to fit revenue. A person
    stays at 1.0 or exits; FTE only moves in whole planned steps."""
    grid = _grid(BELLWEATHER)
    for g in grid["groups"]:
      for row in g["quarters"]:
        ending = row[RF.ROW_ENDING]
        self.assertAlmostEqual(ending, round(ending), places=6,
                               msg="a fractional person appeared: %s" % ending)

  def test_the_raise_lands_once_a_year_not_every_quarter(self):
    grid = _grid(BELLWEATHER, annual_salary_increase=0.03)
    salaries = [q[RF.ROW_AVG_SALARY] for q in grid["groups"][2]["quarters"]]
    base = salaries[0]
    self.assertAlmostEqual(salaries[3], base, places=2)        # year 1 flat
    self.assertAlmostEqual(salaries[4], round(base * 1.03, 2), places=2)
    self.assertAlmostEqual(salaries[19], round(base * (1.03 ** 4), 2),
                           delta=1.0)                           # 4 raises, not 19

  def test_payroll_is_an_output_not_a_target(self):
    """There is no percent-of-revenue input anywhere in the contract."""
    grid = _grid(BELLWEATHER)
    blob = repr(grid)
    self.assertNotIn("target_payroll_percent_of_revenue", blob)
    self.assertNotIn("right_size_factor", blob)

  def test_the_client_may_edit_hires_and_exits_and_nothing_else(self):
    grid = _grid(BELLWEATHER)
    self.assertEqual([RF.ROW_HIRES, RF.ROW_EXITS],
                     grid["client_editable_rows"])
    for g in grid["groups"]:
      for row in g["quarters"]:
        self.assertEqual([RF.ROW_HIRES, RF.ROW_EXITS], row["client_editable"])

  def test_her_forecast_edit_changes_the_plan(self):
    """'the user needs to be able to adjust her forecast for the FTE'."""
    edited = [dict(g) for g in BELLWEATHER]
    edited[2] = dict(edited[2], planned_hires={"5": 2})
    base = RF.ending_fte_by_quarter(_grid(BELLWEATHER))
    after = RF.ending_fte_by_quarter(_grid(edited))
    self.assertEqual(base[4], after[4])
    self.assertEqual(base[5] + 2, after[5])
    self.assertEqual([], RF.identities(_grid(edited)))

  def test_the_block_is_the_layout_the_client_sees(self):
    """Nine rows, in this order, matching the reference model exactly."""
    self.assertEqual(
        ["Opening FTE", "Planned hires", "Planned exits", "Ending FTE",
         "Average paid FTE", "Average annual salary", "Cash compensation",
         "Payroll taxes and benefits", "Total employment cost"],
        list(RF.BLOCK_ROWS))

  def test_it_is_quarterly_and_the_stub_is_her_opening_team(self):
    grid = _grid(BELLWEATHER)
    self.assertEqual("quarterly", grid["cadence"])
    self.assertEqual(20, grid["horizon_quarters"])
    artisans = grid["groups"][2]
    self.assertEqual(6.0, artisans["stub"][RF.ROW_ENDING])
    self.assertEqual(6.0, artisans["quarters"][0][RF.ROW_OPENING])

  def test_the_burden_is_a_live_editable_assumption(self):
    """Nick: it must be an assumption in the workbook that can be changed,
    so the sheet reflects a new rate instead of carrying a baked number."""
    grid = _grid(BELLWEATHER, burden_rate=0.22)
    burden = grid["assumptions"]["payroll_tax_and_benefit_burden"]
    self.assertEqual(0.22, burden["value"])
    self.assertTrue(burden["editable"])
    self.assertIn(RF.ROW_TAXES, burden["drives_rows"])
    raise_ = grid["assumptions"]["annual_salary_increase"]
    self.assertEqual(0.03, raise_["value"])
    self.assertTrue(raise_["editable"])
    # and the workbook must write that row as a formula, not a constant
    self.assertIn("payroll_tax_and_benefit_burden",
                  grid["workbook_formula_rows"][RF.ROW_TAXES])

  def test_changing_the_burden_changes_the_plan(self):
    a = RF.payroll_by_quarter(_grid(BELLWEATHER, burden_rate=0.22))
    b = RF.payroll_by_quarter(_grid(BELLWEATHER, burden_rate=0.30))
    self.assertGreater(b[1], a[1])

  def test_income_statement_payroll_equals_the_sum_of_the_groups(self):
    grid = _grid(KEIR)
    for t in grid["totals"]:
      q = t["quarter_index"]
      by_group = sum(g["quarters"][q - 1][RF.ROW_TOTAL] for g in grid["groups"])
      self.assertAlmostEqual(by_group, t[RF.ROW_TOTAL], places=2)

  def test_per_employee_ratios_have_a_moving_denominator(self):
    directive = {"groups": [{"group": "Fabricators and fitters",
                             "hires_q": {"9": 3}}]}
    grid = _grid(RF.apply_executive_design(KEIR, directive))
    fte = RF.ending_fte_by_quarter(grid)
    self.assertNotEqual(fte[1], fte[20],
                        "FTE never moves, so a frozen denominator would hide")
    self.assertEqual(fte[1] + 3, fte[20])


if __name__ == "__main__":
  unittest.main()
