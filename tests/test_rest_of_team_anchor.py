"""Nick's payroll directive (2026-09-09), fix 3, pinned.

THE REST-OF-TEAM ANCHOR: the client's stated rest-of-team payroll pool
(people_json.rest_of_team_payroll_year1) anchors the supporting roster -
it never again sits beside a capacity-derived roster that ignores it.
Live evidence: Marchetti & Fen (3201a64c) captured $523,000 and authored
3.32 supporting FTE (~$190K) for a nine-person practice; Ardenwald
(65e3c466) captured $986,000 against a $745K authored pool.

Mechanics pinned here: uniform FTE scaling across every quarter (OEWS
wages untouched, growth shape preserved), Q1 annualized supporting wage
bill lands on the stated pool, per-row starting + hires = ending is
re-derived exactly after rounding, and every outcome is provenance-
stamped (rest_of_team_anchor) - applied, already_anchored, or
no_q1_supporting_fte - never silent.
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
  _anchor_supporting_rows_to_stated_pool,
)


def _row(q, title, start, hires, end, wage):
  return {
    "quarter_index": q, "oews_occ_title": title, "staffing_class":
    "supporting_staff", "starting_fte": start, "hires": hires,
    "ending_fte": end, "annual_wage": wage,
  }


# A Marchetti-shaped roster: two titles, Q1 pool far under the stated pool,
# growth in Q2.
MARCHETTI_LIKE = [
  _row(1, "Architectural and Civil Drafters", 0.0, 2.0, 2.0, 60000),
  _row(1, "Office and Administrative Support Workers", 0.0, 1.32, 1.32, 52880),
  _row(2, "Architectural and Civil Drafters", 2.0, 0.5, 2.5, 60000),
  _row(2, "Office and Administrative Support Workers", 1.32, 0.0, 1.32, 52880),
]


def _q1_pool(rows):
  return sum(
    float(r["ending_fte"]) * float(r["annual_wage"])
    for r in rows if r["quarter_index"] == 1
  )


class RestOfTeamAnchorTests(unittest.TestCase):
  def test_q1_pool_lands_on_stated_pool(self):
    rot = 523000.0
    rows, anchor = _anchor_supporting_rows_to_stated_pool(
      [dict(r) for r in MARCHETTI_LIKE],
      people_json={"rest_of_team_payroll_year1": rot},
    )
    self.assertTrue(anchor["applied"])
    self.assertEqual(anchor["anchor_disposition"], "applied")
    # rounding to 2dp FTE leaves at most ~0.005 FTE per row of drift
    self.assertLess(abs(_q1_pool(rows) - rot), 0.01 * rot)

  def test_wages_untouched_and_shape_preserved(self):
    rows, _ = _anchor_supporting_rows_to_stated_pool(
      [dict(r) for r in MARCHETTI_LIKE],
      people_json={"rest_of_team_payroll_year1": 523000.0},
    )
    self.assertEqual({r["annual_wage"] for r in rows}, {60000, 52880})
    drafters = {r["quarter_index"]: r for r in rows
                if r["oews_occ_title"].startswith("Architectural")}
    ratio = drafters[2]["ending_fte"] / drafters[1]["ending_fte"]
    self.assertAlmostEqual(ratio, 2.5 / 2.0, places=2)

  def test_fte_invariant_holds_exactly_after_rounding(self):
    rows, _ = _anchor_supporting_rows_to_stated_pool(
      [dict(r) for r in MARCHETTI_LIKE],
      people_json={"rest_of_team_payroll_year1": 523000.0},
    )
    for r in rows:
      self.assertAlmostEqual(
        r["starting_fte"] + r["hires"], r["ending_fte"], places=9,
        msg=f"starting+hires must equal ending on {r}",
      )

  def test_no_stated_pool_means_no_move(self):
    rows, anchor = _anchor_supporting_rows_to_stated_pool(
      [dict(r) for r in MARCHETTI_LIKE], people_json={},
    )
    self.assertIsNone(anchor)
    self.assertEqual(rows, MARCHETTI_LIKE)

  def test_already_anchored_pool_is_untouched_but_stamped(self):
    rot = _q1_pool(MARCHETTI_LIKE)
    rows, anchor = _anchor_supporting_rows_to_stated_pool(
      [dict(r) for r in MARCHETTI_LIKE],
      people_json={"rest_of_team_payroll_year1": rot},
    )
    self.assertFalse(anchor["applied"])
    self.assertEqual(anchor["anchor_disposition"], "already_anchored")
    self.assertEqual(rows, MARCHETTI_LIKE)

  def test_zero_q1_fte_is_stamped_never_scaled(self):
    later_only = [_row(2, "Architectural and Civil Drafters", 0.0, 1.0, 1.0, 60000)]
    rows, anchor = _anchor_supporting_rows_to_stated_pool(
      [dict(r) for r in later_only],
      people_json={"rest_of_team_payroll_year1": 100000.0},
    )
    self.assertFalse(anchor["applied"])
    self.assertEqual(anchor["anchor_disposition"], "no_q1_supporting_fte")
    self.assertEqual(rows, later_only)


if __name__ == "__main__":
  unittest.main()
