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

Item 6 (Nick, 2026-09-09 evening, R2): "authoring above the stated total
means the model invented people; scaling down to their number is
correct." The down-scale STAYS; every down-scale is LOGGED loudly as a
distinct REST_OF_TEAM_ANCHOR_DOWNSCALE line carrying the stated pool, the
authored pool, the factor and the gap in dollars, so Nick can see whether
the author routinely over-builds. Not emitted at factor >= 1 or inside
the 0.5% no-op band. The math, the stamps and the schedule rows do not
move - the byte-equal pin below carries the digest recorded at ebc8c77
before the line was added.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import logging
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo.post_intake_headcount import schedule as _sched  # noqa: E402
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


def _anchor_with_log(rows, pool):
  """Run the anchor with the module logger captured; return
  (rows, anchor, [REST_OF_TEAM_ANCHOR* lines])."""
  buf = io.StringIO()
  h = logging.StreamHandler(buf)
  h.setLevel(logging.INFO)
  lg = logging.getLogger(_sched.__name__)
  old_level = lg.level
  lg.addHandler(h)
  lg.setLevel(logging.INFO)
  try:
    out_rows, anchor = _anchor_supporting_rows_to_stated_pool(
      copy.deepcopy(rows), people_json={"rest_of_team_payroll_year1": pool})
  finally:
    lg.removeHandler(h)
    lg.setLevel(old_level)
  lines = [l for l in buf.getvalue().splitlines() if "REST_OF_TEAM_ANCHOR" in l]
  return out_rows, anchor, lines


def _digest(rows, anchor):
  blob = json.dumps({"rows": rows, "anchor": anchor}, sort_keys=True,
                    separators=(",", ":"))
  return hashlib.sha256(blob.encode()).hexdigest()[:16]


# Recorded at ebc8c77 (before the DOWNSCALE line existed) by
# replay_gate/_payroll_directive_audit/r6_downscale/r6_downscale_digest.py:
# the Marchetti-shaped roster (Q1 authored pool 189,801.60) against a stated
# pool of 100,000 - factor 0.5269, applied.
DOWNSCALE_DIGEST_AT_EBC8C77 = "34ff11069a09e312"
UPSCALE_DIGEST_AT_EBC8C77 = "248670d1f002e283"


class RestOfTeamAnchorDownscaleLog(unittest.TestCase):
  """Item 6: the down-scale is kept and logged loudly; nothing else moves."""

  def test_downscale_logs_the_gap_line_with_four_figures(self):
    rows, anchor, lines = _anchor_with_log(MARCHETTI_LIKE, 100000.0)
    self.assertTrue(anchor["applied"])
    self.assertAlmostEqual(anchor["factor"], 0.5269, places=4)
    down = [l for l in lines if "REST_OF_TEAM_ANCHOR_DOWNSCALE" in l]
    self.assertEqual(len(down), 1, lines)
    self.assertIn("stated_pool=100000.00", down[0])
    self.assertIn("authored_pool=189801.60", down[0])
    self.assertIn("factor=0.5269", down[0])
    self.assertIn("gap_dollars=89801.60", down[0])
    # the existing applied line still rides beside it
    self.assertTrue(any(l.startswith("REST_OF_TEAM_ANCHOR applied") for l in lines), lines)

  def test_downscale_schedule_and_stamp_are_byte_equal_to_the_record(self):
    """The log line is the ONLY change: rows + stamp digest equal the one
    recorded at ebc8c77 before the line was added."""
    rows, anchor, _ = _anchor_with_log(MARCHETTI_LIKE, 100000.0)
    self.assertEqual(_digest(rows, anchor), DOWNSCALE_DIGEST_AT_EBC8C77)
    self.assertNotIn("gap_dollars", json.dumps(anchor))
    # and the shape is what the math says: every FTE x 0.5269, hires re-derived
    self.assertEqual(
      [(r["quarter_index"], r["starting_fte"], r["hires"], r["ending_fte"]) for r in rows],
      [(1, 0.0, 1.05, 1.05), (1, 0.0, 0.7, 0.7), (2, 1.05, 0.27, 1.32), (2, 0.7, 0.0, 0.7)])

  def test_upscale_does_not_log_the_downscale_line(self):
    rows, anchor, lines = _anchor_with_log(MARCHETTI_LIKE, 523000.0)
    self.assertTrue(anchor["applied"])
    self.assertGreater(anchor["factor"], 1.0)
    self.assertFalse(any("DOWNSCALE" in l for l in lines), lines)
    self.assertEqual(_digest(rows, anchor), UPSCALE_DIGEST_AT_EBC8C77)

  def test_noop_band_does_not_log_the_downscale_line(self):
    """Inside the 0.5% band on the low side: already_anchored, silent."""
    pool = round(_q1_pool(MARCHETTI_LIKE) * 0.996, 2)
    rows, anchor, lines = _anchor_with_log(MARCHETTI_LIKE, pool)
    self.assertFalse(anchor["applied"])
    self.assertEqual(anchor["anchor_disposition"], "already_anchored")
    self.assertEqual(lines, [])
    self.assertEqual(rows, MARCHETTI_LIKE)

  def test_downscale_just_outside_the_band_logs_it(self):
    pool = round(_q1_pool(MARCHETTI_LIKE) * 0.99, 2)
    _, anchor, lines = _anchor_with_log(MARCHETTI_LIKE, pool)
    self.assertTrue(anchor["applied"])
    down = [l for l in lines if "REST_OF_TEAM_ANCHOR_DOWNSCALE" in l]
    self.assertEqual(len(down), 1, lines)
    self.assertIn("factor=0.9900", down[0])
    self.assertIn(f"stated_pool={pool:.2f}", down[0])


if __name__ == "__main__":
  unittest.main()
