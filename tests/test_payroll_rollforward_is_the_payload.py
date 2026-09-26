"""THE ROLL-FORWARD IS WHAT THE RUN SHIPS, NOT A SECOND OPINION.

`test_payroll_is_a_roll_forward.py` pins the engine. This pins the WIRING:
the payload the workbook, the model input, finmo, the realism gate and the
written plan all read is the group roll-forward, and the things Nick said to
keep are still there.

Step 4 of the directive checks these on a live run. They are pinned here so
a live run is not how we find out.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "python",
                             "client_intake_and_finmo"))

from client_intake_and_finmo.post_intake_headcount import (  # noqa: E402
    rollforward as RF,
    rollforward_payload as RP,
)

HORIZON = 20
BURDEN = 0.22
RAISE = 0.03


def _authored_rows(*, team, horizon=HORIZON, raise_rate=RAISE):
  """The payload rows as the AUTHOR leaves them.

  One row per role per quarter, wages already OEWS-resolved and inflated by
  the policy's year offset - the exact shape
  `_build_payroll_headcount_payload_from_contract` hands to the normalizer.
  """
  rows = []
  for spec in team:
    for q in range(int(spec.get("first_quarter") or 1), horizon + 1):
      first_q = int(spec.get("first_quarter") or 1)
      fte = spec["fte_by_q"].get(q, spec["fte_by_q"][max(k for k in spec["fte_by_q"]
                                                         if k <= q)])
      prior_keys = [k for k in spec["fte_by_q"] if k <= q - 1]
      prior = (spec["fte_by_q"].get(q - 1, spec["fte_by_q"][max(prior_keys)])
               if prior_keys else 0.0)
      start = (spec["fte_by_q"][first_q] if q == first_q and first_q == 1
               else (0.0 if q == first_q else prior))
      wage = round(spec["wage"] * ((1.0 + raise_rate) ** ((q - 1) // 4)))
      row = {
        "quarter_index": q,
        "staffing_class": spec["staffing_class"],
        "starting_fte": round(start, 2),
        "hires": round(max(0.0, fte - start), 2),
        "ending_fte": round(fte, 2),
        "average_fte": round((start + fte) / 2.0, 2),
        "annual_wage": wage,
        "payroll_taxes_benefits_percent": BURDEN,
        "wage_source": spec.get("wage_source", "oews_median"),
      }
      if spec["staffing_class"] == "key_person":
        row["person_name"] = spec["person_name"]
        row["position_title"] = spec["title"]
      else:
        row["position_title"] = spec["title"]
        row["oews_occ_title"] = spec["oews_title"]
      rows.append(row)
  return rows


KEIR = [
    {"staffing_class": "key_person", "person_name": "Rosalind Keir",
     "title": "Owner and General Manager", "wage": 140000.0,
     "wage_source": "client_override", "fte_by_q": {1: 1.0}},
    {"staffing_class": "key_person", "person_name": "Dev Ramanathan",
     "title": "Shop Foreman", "wage": 95000.0,
     "wage_source": "client_override", "fte_by_q": {1: 1.0}},
    {"staffing_class": "supporting_staff", "title": "Fabricators and fitters",
     "oews_title": "Structural Metal Fabricators and Fitters", "wage": 68889.0,
     "fte_by_q": {1: 9.0, 9: 11.0}},
]
# a group with NO rows until the quarter it starts - the author omits a title
# that does not exist yet, so its first resolved wage is already inflated
LATE = [
    {"staffing_class": "key_person", "person_name": "Tomas Ilves",
     "title": "Owner", "wage": 120000.0, "fte_by_q": {1: 1.0}},
    {"staffing_class": "supporting_staff", "title": "Delivery drivers",
     "oews_title": "Light Truck Drivers", "wage": 44000.0,
     "first_quarter": 6, "fte_by_q": {6: 2.0}},
]
# two named people who share a title, and a group that starts mid-plan
SPLIT = [
    {"staffing_class": "key_person", "person_name": "Ada Voss",
     "title": "Co-Owner", "wage": 90000.0, "fte_by_q": {1: 1.0}},
    {"staffing_class": "key_person", "person_name": "Mira Voss",
     "title": "Co-Owner", "wage": 90000.0, "fte_by_q": {1: 1.0}},
    {"staffing_class": "supporting_staff", "title": "Delivery drivers",
     "oews_title": "Light Truck Drivers", "wage": 44000.0,
     "fte_by_q": {1: 0.0, 6: 2.0}},
]


# A REAL PART-TIMER, AND A TRAJECTORY THAT LANDS OFF THE 2-DP GRID. 0.5 opening
# plus 0.25 gives an average paid FTE of 0.625, which the app rounds to 0.63 and
# a sheet formula must round the same way or the two disagree by a dollar.
PART_TIME = [
    {"staffing_class": "key_person", "person_name": "Noor Habib",
     "title": "Owner", "wage": 80000.0, "fte_by_q": {1: 1.0}},
    {"staffing_class": "supporting_staff", "title": "Saturday counter staff",
     "oews_title": "Retail Salespersons", "wage": 33000.0,
     "fte_by_q": {1: 0.5, 2: 0.75, 7: 1.25}},
]


def _payload(rows, **kw):
  payload = {
    "schedule_horizon_quarters": HORIZON,
    "target_payroll_percent_of_revenue": 0.41,
    "rows": [dict(r) for r in rows],
    "quarter_totals": [
      {"quarter_index": q,
       "ending_fte": round(sum(r["ending_fte"] for r in rows
                               if r["quarter_index"] == q), 2),
       "payroll": sum(int(round(r["average_fte"] * r["annual_wage"] / 4.0 * 1.22))
                      for r in rows if r["quarter_index"] == q)}
      for q in range(1, HORIZON + 1)
    ],
  }
  trace = RP.normalize_payload_to_group_rollforward(
    payload, horizon=HORIZON, annual_salary_increase=RAISE, **kw)
  return payload, trace


class TheRollForwardIsThePayload(unittest.TestCase):

  def test_the_three_identities_hold_on_the_shipped_rows(self):
    cases = [("Keir", KEIR, None), ("Split", SPLIT, None),
             ("Late", LATE, None), ("PartTime", PART_TIME, None),
             # with exits on the board, because ending == opening + hires is
             # right up until the quarter somebody leaves
             ("Keir after a restructure", KEIR,
              {"groups": [{"group": "Fabricators and fitters",
                           "exits_q": {"5": 4, "9": 1}}]})]
    for name, team, directive in cases:
      kw = {"team_directive": directive} if directive else {}
      payload, trace = _payload(_authored_rows(team=team), **kw)
      self.assertTrue(trace["applied"], name)
      self.assertEqual([], RP.identities_from_payload_rows(payload["rows"]), name)
      self.assertNotIn("identity_breaks", trace, name)
      if directive:
        self.assertEqual(
          5.0, max(r["exits"] for r in payload["rows"]) + 1.0,
          "%s: the exits must be ON the rows for this to be a test" % name)

  def test_every_row_carries_its_group_and_its_exits(self):
    payload, _ = _payload(_authored_rows(team=KEIR))
    for row in payload["rows"]:
      self.assertTrue(str(row.get("group_name") or "").strip())
      self.assertIn("exits", row)

  def test_income_statement_payroll_equals_the_sum_of_the_group_totals(self):
    """Step 4's check, to the dollar - not to a tolerance.

    The money is recomputed HERE with the workbook's own formula chain
    (ROUND((opening+ending)/2,2) -> ROUND(avg*salary/4,0) -> ROUND(cash*burden,0)),
    so this compares the payload against an independent arithmetic, not
    against itself.
    """
    for team in (KEIR, PART_TIME):
      self._payroll_ties_out(team)

  def _payroll_ties_out(self, team):
    payload, _ = _payload(_authored_rows(team=team))
    grid = payload[RP.ROLLFORWARD_PAYLOAD_KEY]
    burden = grid["payroll_tax_and_benefit_burden"]
    by_quarter = {int(t["quarter_index"]): int(t["payroll"])
                  for t in payload["quarter_totals"]}
    sheet_by_quarter = {}
    for row in payload["rows"]:
      q = int(row["quarter_index"])
      average = round((row["starting_fte"] + row["ending_fte"]) / 2.0, 2)
      cash = round(average * row["annual_wage"] / 4.0)
      taxes = round(cash * burden)
      self.assertEqual(cash, int(row["quarterly_wage_cost"]))
      self.assertEqual(taxes, int(row["quarterly_taxes_benefits"]))
      self.assertEqual(cash + taxes, int(row["total_quarterly_payroll"]))
      sheet_by_quarter[q] = sheet_by_quarter.get(q, 0) + cash + taxes
    for total in grid["totals"]:
      q = int(total["quarter_index"])
      self.assertEqual(sheet_by_quarter[q], int(total["total_employment_cost"]),
                       "Q%d: the sheet's formula %s vs the group blocks %s"
                       % (q, sheet_by_quarter[q], total["total_employment_cost"]))
      self.assertEqual(sheet_by_quarter[q], by_quarter[q],
                       "Q%d: the sheet's formula %s vs income-statement payroll %s"
                       % (q, sheet_by_quarter[q], by_quarter[q]))

  def test_her_opening_team_survives_the_rewrite(self):
    """Q1 is her roster. The stated-payroll reconciliation reads year one, so
    a roll-forward that moved it would break a door that already works."""
    rows = _authored_rows(team=KEIR)
    before = sum(int(round(r["average_fte"] * r["annual_wage"] / 4.0 * 1.22))
                 for r in rows if r["quarter_index"] == 1)
    payload, _ = _payload(rows)
    after = sum(int(r["total_quarterly_payroll"]) for r in payload["rows"]
                if int(r["quarter_index"]) == 1)
    self.assertAlmostEqual(before, after, delta=max(2.0, before * 0.001))
    self.assertEqual(
      11.0, sum(r["ending_fte"] for r in payload["rows"]
                if int(r["quarter_index"]) == 1))

  def test_oews_wages_are_the_authors_wages(self):
    """Nick: keep OEWS exactly as it is. The group's salary is the author's
    resolved wage, read at Q1 where the policy's inflation factor is 1.0."""
    payload, _ = _payload(_authored_rows(team=KEIR))
    q1 = {r["group_name"]: r for r in payload["rows"] if int(r["quarter_index"]) == 1}
    self.assertEqual(140000, q1["Owner and General Manager"]["annual_wage"])
    self.assertEqual(95000, q1["Shop Foreman"]["annual_wage"])
    self.assertEqual(68889, q1["Fabricators and fitters"]["annual_wage"])
    for row in payload["rows"]:
      self.assertTrue(str(row.get("wage_source") or "").strip(),
                      "the wage's provenance must survive the rewrite")
      if str(row.get("staffing_class")) != "key_person":
        self.assertTrue(str(row.get("oews_occ_title") or "").strip())

  def test_the_raise_is_the_policys_raise_and_lands_once_a_year(self):
    payload, _ = _payload(_authored_rows(team=KEIR))
    salaries = {int(r["quarter_index"]): int(r["annual_wage"])
                for r in payload["rows"]
                if r["group_name"] == "Fabricators and fitters"}
    self.assertEqual(salaries[1], salaries[4])
    self.assertEqual(salaries[5], round(salaries[1] * 1.03))
    self.assertEqual(salaries[5], salaries[8])
    self.assertLess(abs(salaries[17] - round(salaries[1] * (1.03 ** 4))), 3)

  def test_a_group_that_starts_mid_plan_is_not_raised_twice(self):
    """Its first resolved wage already carries the policy's year-2 step, so the
    base is read back DOWN to a Q1 equivalent. Without that, a group hired in
    year two compounds five raises in a five-year plan instead of four."""
    payload, _ = _payload(_authored_rows(team=LATE))
    drivers = {int(r["quarter_index"]): r for r in payload["rows"]
               if r["group_name"] == "Delivery drivers"}
    self.assertEqual(0.0, drivers[1]["ending_fte"])
    self.assertEqual(0.0, drivers[5]["ending_fte"])
    self.assertEqual(2.0, drivers[6]["ending_fte"])
    self.assertEqual(44000, drivers[1]["annual_wage"])
    self.assertEqual(round(44000 * 1.03), drivers[6]["annual_wage"])
    self.assertEqual(round(44000 * (1.03 ** 4)), drivers[17]["annual_wage"])
    self.assertEqual([], RP.identities_from_payload_rows(payload["rows"]))

  def test_two_named_people_with_one_title_stay_two_groups(self):
    payload, trace = _payload(_authored_rows(team=SPLIT))
    names = sorted({r["group_name"] for r in payload["rows"]})
    self.assertEqual(3, len(names), names)
    self.assertEqual(2, len([n for n in names if n.startswith("Co-Owner")]), names)
    self.assertEqual(3, trace["group_count"])

  def test_the_executives_exits_land_on_the_payload(self):
    """The Bellweather defect: an approved design that never reached a row."""
    rows = _authored_rows(team=KEIR)
    base, _ = _payload(rows)
    after, trace = _payload(
      rows, team_directive={"groups": [{"group": "Fabricators and fitters",
                                        "exits_q": {"5": 4}}]})
    self.assertEqual([], RP.identities_from_payload_rows(after["rows"]))
    q6_before = [r for r in base["rows"] if int(r["quarter_index"]) == 6]
    q6_after = [r for r in after["rows"] if int(r["quarter_index"]) == 6]
    self.assertEqual(sum(r["ending_fte"] for r in q6_before) - 4.0,
                     sum(r["ending_fte"] for r in q6_after))
    self.assertLess(sum(r["total_quarterly_payroll"] for r in q6_after),
                    sum(r["total_quarterly_payroll"] for r in q6_before))
    self.assertEqual(1, trace["executive_design"]["changed_group_count"])

  def test_a_design_that_names_a_group_we_do_not_have_is_not_silent(self):
    _, trace = _payload(
      _authored_rows(team=KEIR),
      team_directive={"groups": [{"group": "studio artisans", "exits_q": {"2": 2}}]})
    self.assertEqual(["studio artisans"],
                     trace["executive_design"]["named_groups_not_found"])

  def test_the_owner_cannot_be_exited_by_a_directive(self):
    after, _ = _payload(
      _authored_rows(team=KEIR),
      team_directive={"groups": [{"group": "Owner and General Manager",
                                  "exits_q": {"3": 1}}]})
    owner = [r for r in after["rows"]
             if r["group_name"] == "Owner and General Manager"]
    for row in owner:
      self.assertEqual(0.0, row["exits"])
      self.assertEqual(1.0, row["ending_fte"])

  def test_the_burden_and_the_raise_are_on_the_payload_for_the_workbook(self):
    """Nick: both must be live cells in the sheet, which means the payload has
    to carry them as assumptions, not bake them into the numbers."""
    payload, _ = _payload(_authored_rows(team=KEIR))
    grid = payload[RP.ROLLFORWARD_PAYLOAD_KEY]
    self.assertEqual(0.22, grid["payroll_tax_and_benefit_burden"])
    self.assertEqual(0.03, grid["annual_salary_increase"])
    self.assertEqual("quarterly", grid["cadence"])
    self.assertEqual(HORIZON, grid["horizon_quarters"])
    self.assertEqual(3, len(grid["groups"]))
    for group in grid["groups"]:
      self.assertEqual(HORIZON, len(group["quarters"]))
      for row in group["quarters"]:
        for field in RP.FIELD_BY_BLOCK_ROW.values():
          self.assertIn(field, row)

  def test_there_is_no_percentage_input_left_in_the_rows(self):
    payload, _ = _payload(_authored_rows(team=KEIR))
    blob = repr(payload["rows"]) + repr(payload[RP.ROLLFORWARD_PAYLOAD_KEY])
    self.assertNotIn("target_payroll_percent_of_revenue", blob)
    self.assertNotIn("right_size_factor", blob)

  def test_the_payload_still_passes_the_payroll_validator(self):
    """The rewritten rows go through the same door every payload goes
    through - including the FTE identity, which now reads exits."""
    from client_intake_and_finmo.post_intake_headcount.lookup import (
        _validate_schedule_row,
    )
    payload, _ = _payload(_authored_rows(team=KEIR))
    errors = []
    for index, row in enumerate(payload["rows"]):
      _validate_schedule_row(row, path=f"rows[{index}]", errors=errors,
                             max_quarter=HORIZON)
    self.assertEqual([], errors[:5])

  def test_a_row_with_exits_would_have_failed_the_old_identity(self):
    """Proof the widening is load-bearing, not decorative."""
    from client_intake_and_finmo.post_intake_headcount.lookup import (
        _validate_schedule_row,
    )
    row = {"quarter_index": 4, "staffing_class": "supporting_staff",
           "oews_occ_title": "Structural Metal Fabricators and Fitters",
           "annual_wage": 68889, "wage_source": "oews_median",
           "payroll_taxes_benefits_percent": 0.22,
           "starting_fte": 9.0, "hires": 0.0, "exits": 4.0, "ending_fte": 5.0}
    errors = []
    _validate_schedule_row(row, path="rows[0]", errors=errors, max_quarter=HORIZON)
    self.assertEqual([], errors)
    self.assertGreater(abs((9.0 + 0.0) - 5.0), 0.01)  # the pre-exits check

  def test_her_crews_become_the_supporting_groups(self):
    """One intake question, her words on the block - and when she gives more
    crews than the author gave titles (or fewer), the block is FOLDED into
    hers, not matched one-to-one. Nick: "groups where possible, not one per
    person", named in her words."""
    payload, trace = _payload(
      _authored_rows(team=KEIR),
      people_json={"team_groups": [{"group_name": "Shop crew", "headcount": 6},
                                   {"group_name": "Field fitters", "headcount": 3}]})
    names = {r["group_name"] for r in payload["rows"]}
    self.assertIn("Shop crew", names)
    self.assertIn("Field fitters", names)
    self.assertNotIn("Fabricators and fitters", names)
    # her named people are NOT folded
    self.assertIn("Owner and General Manager", names)
    self.assertIn("Shop Foreman", names)
    fold = trace["client_group_names"]
    self.assertTrue(fold["folded"])
    self.assertEqual(["Fabricators and fitters"], fold["replaced_authored_groups"])
    self.assertEqual([], RP.identities_from_payload_rows(payload["rows"]))

  def test_the_fold_keeps_the_money_when_her_count_differs(self):
    """THE MONEY IS PRESERVED, NOT THE AUTHOR'S FTE. The author's block FTE is
    an estimate it derived from a budget; her headcount and her stated pool
    are both FACTS she gave. So the fold takes HER count and divides the
    block's own money by it - year one does not move, and the plan shows the
    number of people she actually employs.

    Her 6 + 4 = 10 against the author's 9 is the real shape (Pellingham: she
    said twelve field staff, the author built fractional shares of six OEWS
    occupations)."""
    rows = _authored_rows(team=KEIR)
    before, _ = _payload(rows)
    after, _ = _payload(
      rows,
      people_json={"team_groups": [{"group_name": "Shop crew", "headcount": 6},
                                   {"group_name": "Field fitters", "headcount": 4}]})
    def q1_money(payload):
      return sum(int(r["total_quarterly_payroll"]) for r in payload["rows"]
                 if int(r["quarter_index"]) == 1)
    def q1_fte(payload, groups):
      return sum(r["ending_fte"] for r in payload["rows"]
                 if int(r["quarter_index"]) == 1 and r["group_name"] in groups)
    self.assertAlmostEqual(q1_money(before), q1_money(after),
                           delta=max(3.0, q1_money(before) * 0.002))
    # her people, not the author's estimate
    self.assertEqual(10.0, q1_fte(after, {"Shop crew", "Field fitters"}))
    self.assertEqual(9.0, q1_fte(before, {"Fabricators and fitters"}))
    # and the named people are untouched on both sides
    named = {"Owner and General Manager", "Shop Foreman"}
    self.assertEqual(q1_fte(before, named), q1_fte(after, named))

  def test_the_fold_carries_the_oews_match_and_the_wage_source(self):
    """Her name on the block, the government match still behind it - the
    payload validator requires it and the wage's provenance depends on it."""
    payload, _ = _payload(
      _authored_rows(team=KEIR),
      people_json={"team_groups": [{"group_name": "Shop crew", "headcount": 9}]})
    crew = [r for r in payload["rows"] if r["group_name"] == "Shop crew"]
    self.assertTrue(crew)
    for row in crew:
      self.assertEqual("Shop crew", row["position_title"])
      self.assertEqual("Structural Metal Fabricators and Fitters",
                       row["oews_occ_title"])
      self.assertTrue(str(row["wage_source"]).strip())
      self.assertNotIn("person_name", row)

  def test_a_headcount_nowhere_near_the_block_is_refused_and_recorded(self):
    """She says forty, the author built nine: that is a disagreement to
    surface, not to average away. The authored groups stand and the trace
    says why."""
    payload, trace = _payload(
      _authored_rows(team=KEIR),
      people_json={"team_groups": [{"group_name": "Night shift", "headcount": 40}]})
    fold = trace["client_group_names"]
    self.assertFalse(fold["folded"])
    self.assertEqual("stated_headcount_far_from_the_authored_block",
                     fold["reason"])
    self.assertEqual(40.0, fold["stated_headcount"])
    names = {r["group_name"] for r in payload["rows"]}
    self.assertIn("Fabricators and fitters", names)
    self.assertNotIn("Night shift", names)

  def test_nothing_is_rewritten_when_there_are_no_rows(self):
    payload = {"schedule_horizon_quarters": HORIZON, "rows": []}
    self.assertIsNone(
      RP.normalize_payload_to_group_rollforward(payload, horizon=HORIZON))
    self.assertEqual([], payload["rows"])
    self.assertNotIn(RP.ROLLFORWARD_PAYLOAD_KEY, payload)

  def test_it_is_idempotent(self):
    """It runs at the builder AND after labor scaling; a second pass must not
    move the plan."""
    payload, _ = _payload(_authored_rows(team=KEIR))
    first = [dict(r) for r in payload["rows"]]
    RP.normalize_payload_to_group_rollforward(
      payload, horizon=HORIZON, annual_salary_increase=RAISE)
    for before, after in zip(first, payload["rows"]):
      self.assertEqual(before["group_name"], after["group_name"])
      self.assertEqual(before["ending_fte"], after["ending_fte"])
      self.assertEqual(before["annual_wage"], after["annual_wage"])
      self.assertEqual(before["total_quarterly_payroll"],
                       after["total_quarterly_payroll"])

  def test_the_block_rows_are_the_reference_layout(self):
    self.assertEqual(list(RF.BLOCK_ROWS), list(RP.FIELD_BY_BLOCK_ROW.keys()))


if __name__ == "__main__":
  unittest.main()
