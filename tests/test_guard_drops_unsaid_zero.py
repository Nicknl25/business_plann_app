"""A ZERO THE CLIENT DID NOT SAY IS NOT A VALUE (2026-09-12, the issue-578
class). Northgate's owner answered the utilization question - "About 85
percent - we have 34 sites under contract" - and the router's line-row patch
carried unit_price = 0.0, a placeholder. Door A's model let it stand and door
C tagged the write router_patch/authorised; the price only became $1,200 two
turns later when the price question was asked. Door A now drops a zero on a
stated-fact leaf when the client's words carry no zero, none, no or nothing -
deterministically, before the model, and on the fail-open path too.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo.intake_guard import door_a as A  # noqa: E402


NORTHGATE_PATCH = {
  "ops.lob_models[0].products[0].unit_price": 0.0,
  "ops.lob_models[0].products[0].units_per_week_capacity": 40.0,
  "ops.lob_models[0].products[0].utilization_rate": 0.85,
}
WORDS = "About 85 percent - we have 34 sites under contract."


class APlaceholderZeroNeverLands(unittest.TestCase):
  def test_the_zero_price_is_dropped_and_the_stated_figures_stay(self):
    kept, dropped = A.drop_unsaid_zeros(NORTHGATE_PATCH, WORDS)
    self.assertNotIn("ops.lob_models[0].products[0].unit_price", kept)
    self.assertEqual(kept["ops.lob_models[0].products[0].units_per_week_capacity"], 40.0)
    self.assertEqual(kept["ops.lob_models[0].products[0].utilization_rate"], 0.85)
    self.assertEqual([d["key"] for d in dropped], ["ops.lob_models[0].products[0].unit_price"])
    self.assertIn("did not say", dropped[0]["why"])

  def test_a_zero_the_client_said_is_a_value(self):
    for words in ("No debt - zero.", "None, nothing owed.", "We don't have any - $0.", "no", "0"):
      kept, dropped = A.drop_unsaid_zeros({"financials.total_debt_outstanding": 0.0}, words)
      self.assertEqual(kept, {"financials.total_debt_outstanding": 0.0}, words)
      self.assertEqual(dropped, [], words)

  def test_a_figure_with_a_zero_in_it_is_not_a_zero(self):
    kept, dropped = A.drop_unsaid_zeros({"financials.monthly_rent_expense": 0.0}, "About 4,500 a month - 10 rooms.")
    self.assertEqual(dropped[0]["key"], "financials.monthly_rent_expense", "the 0 inside 4,500 and 10 is not the client saying zero")

  def test_only_stated_facts_are_judged(self):
    kept, dropped = A.drop_unsaid_zeros({"ops.utilization_note_count": 0, "financials.confidence": 0.0}, WORDS)
    self.assertEqual(dropped, [])
    self.assertEqual(len(kept), 2)

  def test_the_rule_runs_before_the_model_and_on_the_fail_open_path(self):
    def boom(**kw):
      raise RuntimeError("no network")
    with unittest.mock.patch.object(A, "enabled", return_value=True), \
         unittest.mock.patch.object(A, "_key", return_value="test-key"):
      v = A.review(patch=dict(NORTHGATE_PATCH), user_text=WORDS, messages=[], store={}, post=boom)
    self.assertTrue(v.timed_out or v.error)
    self.assertNotIn("ops.lob_models[0].products[0].unit_price", v.patch, "dropped even though the model never ran")
    self.assertEqual(len(v.dropped), 1)
    self.assertTrue(v.changed)


if __name__ == "__main__":
  unittest.main()
