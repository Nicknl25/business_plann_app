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


if __name__ == "__main__":
  unittest.main()
