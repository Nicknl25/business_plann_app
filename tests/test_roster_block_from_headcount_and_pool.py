"""STANDING RULE (Nick 2026-09-12): never depend on the client saying the right
thing. "A real client says 'the rest of the team is about 1.4 million' and
stops. Build the created roster block from HEADCOUNT AND POOL - twenty-two
people, two named, twenty in the pool, $1.41M, about $70,500 a head, and the
count is right by construction. Never derive a headcount from money when the
client stated one. Occupations only describe those roles; they don't decide
how many."

Isolde & Parry (be39492d): 22 people stated, 2 named, a $1.41M pool - and the
schedule built 36 "Emergency Medical Technicians" because the pool was
spread over the capacity author's occupation at its OEWS wage.
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo.post_intake_headcount import schedule as SCH  # noqa: E402


def _named(quarters=8):
  rows = []
  for q in range(1, quarters + 1):
    rows.append({"quarter_index": q, "staffing_class": "key_person", "person_name": "Isolde Marchbanks", "annual_wage": 205000,
                 "starting_fte": 1.0, "hires": 0.0, "ending_fte": 1.0})
    rows.append({"quarter_index": q, "staffing_class": "key_person", "person_name": "Dr. Cassius Parry", "annual_wage": 285000,
                 "starting_fte": 1.0, "hires": 0.0, "ending_fte": 1.0})
  return rows


def _authored_emts(quarters=8):
  """What the capacity author produced: EMTs at the OEWS median, growing."""
  rows = []
  for q in range(1, quarters + 1):
    fte = 30.0 + (q - 1) * 1.0
    rows.append({"quarter_index": q, "staffing_class": "supporting_staff", "position_title": "Emergency Medical Technicians",
                 "oews_occ_title": "Emergency Medical Technicians", "oews_occ_code": "29-2042", "annual_wage": 39160,
                 "base_annual_wage": 39160, "starting_fte": fte, "hires": 1.0, "ending_fte": fte + 1.0,
                 "payroll_taxes_benefits_percent": 0.22, "wage_source": "oews_median"})
  return rows


class TheCountComesFromTheClient(unittest.TestCase):
  def test_isolde_twenty_two_people_two_named_twenty_in_the_pool(self):
    rows, anchor = SCH._anchor_supporting_rows_to_stated_pool(
      _authored_emts(), people_json={"rest_of_team_payroll_year1": 1410000.0}, key_people_rows=_named(), horizon=8,
      stated_headcount=22)
    self.assertEqual(anchor["anchor_disposition"], "headcount_and_pool")
    self.assertEqual(anchor["supporting_count"], 20)
    self.assertEqual(anchor["named_count"], 2)
    self.assertEqual(anchor["wage_per_head"], 70500)
    q1 = [r for r in rows if r["quarter_index"] == 1]
    self.assertAlmostEqual(sum(r["ending_fte"] for r in q1), 20.0, places=1, msg="the count is right by construction")
    self.assertEqual({r["annual_wage"] for r in rows}, {70500}, "paid from the pool, a head at a time")
    self.assertAlmostEqual(anchor["q1_supporting_pool_after"], 1410000.0, delta=20000)
    self.assertEqual(q1[0]["position_title"], "Emergency Medical Technicians", "the occupation only describes")
    self.assertEqual(q1[0]["wage_source"], "rest_of_team_anchor:headcount_and_pool")

  def test_without_a_stated_headcount_the_pool_still_anchors_as_before(self):
    rows, anchor = SCH._anchor_supporting_rows_to_stated_pool(
      _authored_emts(), people_json={"rest_of_team_payroll_year1": 1410000.0}, key_people_rows=_named(), horizon=8)
    self.assertNotEqual(anchor["anchor_disposition"], "headcount_and_pool")
    self.assertIn(anchor["anchor_disposition"], ("applied", "launch_in_band", "already_anchored"))

  def test_a_stated_count_no_larger_than_the_named_people_changes_nothing(self):
    rows, anchor = SCH._anchor_supporting_rows_to_stated_pool(
      _authored_emts(), people_json={"rest_of_team_payroll_year1": 1410000.0}, key_people_rows=_named(), horizon=8,
      stated_headcount=2)
    self.assertNotEqual(anchor["anchor_disposition"], "headcount_and_pool")

  def test_the_growth_shape_is_kept_and_hires_re_derive(self):
    rows, _anchor = SCH._anchor_supporting_rows_to_stated_pool(
      _authored_emts(), people_json={"rest_of_team_payroll_year1": 1410000.0}, key_people_rows=_named(), horizon=8,
      stated_headcount=22)
    by_q = {r["quarter_index"]: r for r in rows}
    self.assertLess(by_q[1]["ending_fte"], by_q[8]["ending_fte"], "the author's growth shape survives")
    for r in rows:
      self.assertAlmostEqual(r["starting_fte"] + r["hires"], r["ending_fte"], places=2)

  def test_no_authored_occupations_gives_one_honest_block_at_the_stated_count(self):
    rows, anchor = SCH._anchor_supporting_rows_to_stated_pool(
      [], people_json={"rest_of_team_payroll_year1": 1410000.0}, key_people_rows=_named(), horizon=8, stated_headcount=22)
    self.assertEqual(anchor["anchor_disposition"], "headcount_and_pool")
    q1 = [r for r in rows if r["quarter_index"] == 1]
    self.assertEqual(len(q1), 1)
    self.assertEqual(q1[0]["ending_fte"], 20.0)
    self.assertEqual(q1[0]["annual_wage"], 70500)

  def test_the_stated_headcount_is_read_from_the_financials_the_client_answered(self):
    self.assertEqual(SCH._stated_headcount({"current_num_employees": 22}), 22)
    self.assertEqual(SCH._stated_headcount({"current_num_employees": "31"}), 31)
    self.assertIsNone(SCH._stated_headcount({"current_num_employees": 0}))
    self.assertIsNone(SCH._stated_headcount({}))
    src = open(SCH.__file__, encoding="utf-8").read()
    self.assertIn("stated_headcount=_stated_headcount(financials_json)", src)


if __name__ == "__main__":
  unittest.main()
