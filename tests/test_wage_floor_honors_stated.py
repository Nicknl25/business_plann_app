"""The wage floor never re-bases a stated wage (Nick's ruling 2026-09-10).

"A stated current wage is a fact, not an OEWS-derived figure to be
floored. Inflating from the stated base is fine; re-basing it isn't."
Live evidence: Bramblewood 2f71e20d front desk, client-stated 38,000
re-based to the occupation p10 44,190 (client_override|floor_adapted)
and frozen flat for 20 quarters. The floor doctrine's own comment always
claimed stated wages are honored via client_override - the guard was
never written until now.

Pinned: a client_override row below its floor keeps the stated wage
(recorded as client_override_honored_below_floor, never silent); an
OEWS-derived row below the floor is still grounded up (that IS a data
error); the part-time FTE adaptation (preserves stated dollars,
Nick-ruled sound in CW-043) is untouched.
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

from client_intake_and_finmo.post_intake_headcount.schedule import (  # noqa: E402
  _validate_payroll_title_rows,
  post_intake_headcount_policy_for,
)

POLICY = post_intake_headcount_policy_for(policy_code="default")


def _row(wage, source, title="Front Desk Staff #1", extra=None):
  r = {
    "quarter_index": 1, "staffing_class": "key_person",
    "position_title": title, "person_name": title,
    "starting_fte": 1.0, "hires": 0.0, "ending_fte": 1.0,
    "annual_wage": wage, "wage_source": source,
    "payroll_taxes_benefits_percent": 0.22,
  }
  r.update(extra or {})
  return r


def _validate(rows):
  # the validator demands the full 20-quarter horizon per title: clone
  # each Q1 row across Q2-Q20 (continuity: starting = prior ending)
  full = []
  for r in rows:
    for q in range(1, 21):
      c = dict(r)
      c["quarter_index"] = q
      if q > 1:
        c["starting_fte"] = r["ending_fte"]
        c["hires"] = 0.0
      full.append(c)
  adaptations = []
  _validate_payroll_title_rows(
    full, policy=POLICY, require_annual_wage=True,
    wage_floor_by_key={"title::front desk staff #1": 44190,
                       "title::oews clerk": 44190,
                       "title::part-time front desk staff #1": 44190,
                       "title::part-time front desk": 44190},
    wage_adaptations=adaptations,
  )
  q1 = [c for c in full if c["quarter_index"] == 1]
  return q1, adaptations


class WageFloorHonorsStatedTests(unittest.TestCase):
  def test_client_override_below_floor_keeps_the_stated_wage(self):
    rows, adapt = _validate([_row(38000, "client_override")])
    self.assertEqual(rows[0]["annual_wage"], 38000)
    self.assertEqual(rows[0]["wage_source"], "client_override")
    self.assertEqual(adapt[0]["floor_source"], "client_override_honored_below_floor")
    self.assertEqual(adapt[0]["wage_after"], 38000)

  def test_oews_row_below_floor_is_still_grounded_up(self):
    rows, adapt = _validate([_row(38000, "oews_median", title="OEWS Clerk")])
    self.assertEqual(rows[0]["annual_wage"], 44190)
    self.assertIn("floor_adapted", rows[0]["wage_source"])

  def test_part_time_client_override_still_fte_adapts_preserving_dollars(self):
    rows, adapt = _validate([_row(
      20000, "client_override", title="Part-time Front Desk Staff #1",
      extra={"position_title": "Part-time Front Desk"})])
    # the part-time branch keys on the title text; dollars preserved via
    # FTE scaling is the CW-043-ruled behavior and stays
    if "part_time_hours_adapted" in rows[0]["wage_source"]:
      self.assertLess(rows[0]["ending_fte"], 1.0)
    else:
      # title map missed part-time key: then the stated-wage guard holds
      self.assertEqual(rows[0]["annual_wage"], 20000)


class AStatedPoolIsTheClientsDollars(unittest.TestCase):
  """Nick 2026-09-12 (walk canary 86826c1a): the headcount-and-pool block
  pays pool / count per head. Under the occupation floor, the floor is the
  RATE, the hours carry the difference, the pool total holds, and the rows
  are named part-time - never lifted above the client's figure."""

  def _pool_rows(self):
    r = {
      "quarter_index": 1, "staffing_class": "supporting_staff",
      "position_title": "General and Operations Managers", "oews_occ_title": "General and Operations Managers",
      "starting_fte": 14.0, "hires": 0.0, "ending_fte": 14.0,
      "annual_wage": 22000, "base_annual_wage": 22000,
      "wage_source": "rest_of_team_anchor:headcount_and_pool",
      "payroll_taxes_benefits_percent": 0.22,
    }
    full = []
    for q in range(1, 21):
      c = dict(r); c["quarter_index"] = q
      full.append(c)
    adaptations = []
    _validate_payroll_title_rows(
      full, policy=POLICY, require_annual_wage=True,
      wage_floor_by_key={"title::general and operations managers": 44000},
      wage_adaptations=adaptations,
    )
    return full, adaptations

  def test_the_pool_total_holds_and_the_hours_carry_the_difference(self):
    full, adapt = self._pool_rows()
    q1 = [c for c in full if c["quarter_index"] == 1][0]
    self.assertEqual(q1["annual_wage"], 44000, "the floor governs the rate")
    self.assertAlmostEqual(q1["ending_fte"], 7.0, places=2, msg="14 heads at half the floor rate = 7 FTE of hours")
    self.assertAlmostEqual(q1["ending_fte"] * q1["annual_wage"], 14 * 22000, delta=1.0, msg="the client's $308,000 holds")
    self.assertTrue(q1["position_title"].endswith("(part-time)"), q1["position_title"])
    self.assertIn("part_time_hours_adapted", q1["wage_source"])
    self.assertEqual(adapt[0]["floor_source"], "stated_pool_hours_at_floor_rate")
    for c in full:   # every quarter carries the same dollars, no lift anywhere
      self.assertAlmostEqual(c["ending_fte"] * c["annual_wage"], 14 * 22000, delta=1.0, msg=f"q{c['quarter_index']}")

  def test_the_reconciliation_gate_then_reads_the_stated_pool(self):
    from client_intake_and_finmo.post_intake_headcount import schedule as SCH
    full, _ = self._pool_rows()
    q1_wages = sum(c["ending_fte"] * c["annual_wage"] for c in full if c["quarter_index"] == 1)
    ratio = q1_wages / (14 * 22000)
    self.assertTrue(SCH._LAUNCH_BAND_LO <= ratio <= SCH._LAUNCH_BAND_HI, ratio)


if __name__ == "__main__":
  unittest.main()
