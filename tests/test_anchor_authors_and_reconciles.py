"""The anchor authors, records, and reconciles (Nick's rulings
2026-09-10, Vespertine & Co. baf8b1e7).

Vespertine stated $450,000 of payroll (two named at $201,000 plus a
$249,000 rest-of-team pool). The capacity author produced ZERO
supporting rows, so the anchor - whose only tool was a uniform FTE
scaler - hit `factor = rot / q1_pool` with q1_pool 0, stamped
`no_q1_supporting_fte` and returned the roster untouched. The pool
vanished: $245,220 modelled against $450,000 stated, a 45%
understatement that the industry-cohort payroll check ticked because it
asks whether payroll is normal for the trade, never whether it matches
what the client said. The plan then claimed seven people at $245,000
while its own two named people came to $201,000.

1. CREATE, don't just multiply. A repair mechanism that can only scale
   what exists is a multiplier. With a stated pool and no roster the
   anchor authors the block, sized to the pool.
2. RECORD EITHER WAY. launch_ratio was computed inside the band branch
   and thrown away by the exits that could not act - which is how a
   0.447 launch left no trace. Every disposition stamps it.
3/4. RECONCILE OR SAY SO, at the ONE door every payload is built
   through, not on a lineage: stated figures may inform a labor-class
   choice; they do not licence an output that contradicts them.
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

from client_intake_and_finmo.post_intake_headcount import schedule as S  # noqa: E402


def _named(wage, q=1, fte=1.0):
  return {"quarter_index": q, "staffing_class": "key_person",
          "annual_wage": wage, "ending_fte": fte, "starting_fte": fte,
          "payroll_taxes_benefits_percent": 0.22,
          "annual_wage_inflation_rate": 0.03}


def _supporting(wage, fte, q=1):
  return {"quarter_index": q, "staffing_class": "supporting_staff",
          "annual_wage": wage, "ending_fte": fte, "starting_fte": fte,
          "hires": 0.0}


VESPERTINE_NAMED = [_named(112000), _named(89000)]      # $201,000
VESPERTINE_POOL = {"rest_of_team_payroll_year1": 249000}  # stated $450,000


class AnchorAuthorsTests(unittest.TestCase):
  def test_authors_a_block_when_there_is_nothing_to_scale(self):
    """THE VESPERTINE SHAPE: stated pool, zero supporting rows."""
    rows, anchor = S._anchor_supporting_rows_to_stated_pool(
      [], people_json=VESPERTINE_POOL, key_people_rows=VESPERTINE_NAMED,
      horizon=20)
    self.assertEqual(anchor["anchor_disposition"], "authored_from_stated_pool")
    self.assertTrue(anchor["applied"])
    self.assertTrue(rows, "the anchor authored nothing")
    q1 = [r for r in rows if r["quarter_index"] == 1]
    self.assertEqual(len(q1), 1)
    carried = q1[0]["annual_wage"] * q1[0]["ending_fte"]
    self.assertAlmostEqual(carried, 249000, delta=1000)

  def test_authored_block_spans_the_whole_horizon_flat(self):
    rows, _ = S._anchor_supporting_rows_to_stated_pool(
      [], people_json=VESPERTINE_POOL, key_people_rows=VESPERTINE_NAMED,
      horizon=20)
    self.assertEqual(len({r["quarter_index"] for r in rows}), 20)
    for r in rows:
      self.assertEqual(r["starting_fte"], r["ending_fte"])
      self.assertEqual(r["hires"], 0.0)
      self.assertEqual(r["staffing_class"], "supporting_staff")

  def test_wage_basis_is_stamped_not_invented(self):
    _, anchor = S._anchor_supporting_rows_to_stated_pool(
      [], people_json=VESPERTINE_POOL, key_people_rows=VESPERTINE_NAMED,
      horizon=20)
    self.assertEqual(anchor["created_wage_basis"], "lowest_named_wage")
    self.assertAlmostEqual(anchor["q1_supporting_pool_after"], 249000,
                           delta=1000)

  def test_no_stated_pool_still_does_nothing(self):
    rows, anchor = S._anchor_supporting_rows_to_stated_pool(
      [], people_json={"rest_of_team_payroll_year1": 0},
      key_people_rows=VESPERTINE_NAMED, horizon=20)
    self.assertEqual(rows, [])
    self.assertIsNone(anchor)


class AnchorStampsEveryPathTests(unittest.TestCase):
  def test_in_band_exit_carries_the_ratio(self):
    rows, anchor = S._anchor_supporting_rows_to_stated_pool(
      [_supporting(60000, 4.0)], people_json=VESPERTINE_POOL,
      key_people_rows=VESPERTINE_NAMED, horizon=20)
    self.assertEqual(anchor["anchor_disposition"], "launch_in_band")
    self.assertIsNotNone(anchor["launch_ratio"])
    self.assertAlmostEqual(anchor["launch_ratio"], (201000 + 240000) / 450000,
                           places=3)

  def test_every_disposition_stamps_named_and_stated(self):
    for rows_in in ([], [_supporting(60000, 4.0)], [_supporting(10000, 0.5)]):
      _, anchor = S._anchor_supporting_rows_to_stated_pool(
        list(rows_in), people_json=VESPERTINE_POOL,
        key_people_rows=VESPERTINE_NAMED, horizon=20)
      self.assertIn("launch_ratio", anchor)
      self.assertEqual(anchor["named_q1_wages"], 201000.0)
      self.assertEqual(anchor["stated_total_payroll"], 450000.0)


class ReconciliationGateTests(unittest.TestCase):
  def _payload(self, rows):
    return {"rows": rows, "quarter_totals": []}

  def test_reconciled_payload_is_stamped_and_passes(self):
    payload = self._payload(VESPERTINE_NAMED + [_supporting(62250, 4.0)])
    anchor = {"stated_total_payroll": 450000.0,
              "anchor_disposition": "launch_in_band"}
    S._stamp_stated_payroll_reconciliation(payload, anchor)
    rec = payload["stated_payroll_reconciliation"]
    self.assertTrue(rec["reconciled"])
    self.assertAlmostEqual(rec["ratio"], 1.0, places=2)

  def test_understatement_fails_loudly(self):
    """The exact Vespertine outcome: named only, pool dropped."""
    payload = self._payload(list(VESPERTINE_NAMED))
    anchor = {"stated_total_payroll": 450000.0,
              "anchor_disposition": "no_q1_supporting_fte"}
    with self.assertRaises(Exception) as cm:
      S._stamp_stated_payroll_reconciliation(payload, anchor)
    self.assertIn("payroll_authored_off_stated_payroll", repr(cm.exception)
                  + str(cm.exception))

  def test_overstatement_fails_loudly_too(self):
    """Bramblewood's 1.64x is the same gate from the other side."""
    payload = self._payload(VESPERTINE_NAMED + [_supporting(100000, 5.0)])
    anchor = {"stated_total_payroll": 450000.0,
              "anchor_disposition": "launch_in_band"}
    with self.assertRaises(Exception):
      S._stamp_stated_payroll_reconciliation(payload, anchor)

  def test_no_stated_total_stands_aside(self):
    payload = self._payload(list(VESPERTINE_NAMED))
    S._stamp_stated_payroll_reconciliation(payload, {"stated_total_payroll": 0})
    self.assertNotIn("stated_payroll_reconciliation", payload)


if __name__ == "__main__":
  unittest.main()
