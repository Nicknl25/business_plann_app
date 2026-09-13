"""THE AGREEMENT FROM INTAKE IS A Q11 TARGET, NOT A Q1 STRUCTURE (Wren &
Calloway 07a5b10f, 2026-09-12, the first client through the solved round).

The client agreed to "other operating costs easing from $3.48M to $2.02M a
year by Q11". The runner fed that Q11 share in as the OPERATOR'S cost level
(restructure semantics: a redesigned business's shares from Q1), so the
built model halved the client's actual overhead in Q1 ($870K -> $417K a
quarter) and then let the cascade mature further to $224K by Q11 - the
actuals edited on day one, and a path far outside what was agreed.

Pinned: for an intake directive the operator's actuals stay the anchor and
the agreed shares become the band's floor and target at maturity; a real
restructure directive keeps its Q1 semantics.
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo.post_intake_headcount import band_fitting as BF  # noqa: E402
from client_intake_and_finmo.post_intake_initial_grid import runner as R  # noqa: E402
from client_intake_and_finmo.intake_coherence import path as P  # noqa: E402


class TheAgreedSharesAreTheFloorAndTheTargetAtMaturity(unittest.TestCase):
  def test_the_envelope_is_pinned_to_the_agreement_never_below_it(self):
    env = {"sga_percent_of_revenue": {"min": 0.40, "target": 0.55, "max": 0.70},
           "cogs_percent_of_revenue": {"min": 0.20, "target": 0.25, "max": 0.30},
           "marketing_percent_of_revenue": {"min": 0.01, "target": 0.02, "max": 0.05}}
    applied = BF.apply_agreed_shares(env, {"sga_percent_of_revenue": 0.2875, "cogs_percent_of_revenue": 0.2326,
                                           "marketing_percent_of_revenue": 0.0136, "rent_percent_of_revenue": 0.07})
    self.assertEqual(env["sga_percent_of_revenue"], {"min": 0.2875, "target": 0.2875, "max": 0.70})
    self.assertEqual(env["cogs_percent_of_revenue"], {"min": 0.2326, "target": 0.2326, "max": 0.30})
    self.assertEqual(env["marketing_percent_of_revenue"], {"min": 0.0136, "target": 0.0136, "max": 0.05})
    self.assertNotIn("rent_percent_of_revenue", applied, "a metric with no band is left alone")
    self.assertEqual(applied["sga_percent_of_revenue"]["before"], {"min": 0.40, "target": 0.55, "max": 0.70})

  def test_a_share_above_the_cohort_max_raises_the_max_and_garbage_is_ignored(self):
    env = {"sga_percent_of_revenue": {"min": 0.05, "target": 0.10, "max": 0.20}}
    BF.apply_agreed_shares(env, {"sga_percent_of_revenue": 0.45})
    self.assertEqual(env["sga_percent_of_revenue"], {"min": 0.45, "target": 0.45, "max": 0.45})
    env2 = {"sga_percent_of_revenue": {"min": 0.05, "target": 0.10, "max": 0.20}}
    self.assertEqual(BF.apply_agreed_shares(env2, {"sga_percent_of_revenue": 1.4}), {})
    self.assertEqual(BF.apply_agreed_shares(env2, None), {})
    self.assertEqual(env2["sga_percent_of_revenue"], {"min": 0.05, "target": 0.10, "max": 0.20})

  def test_the_pass_applies_them_before_the_author_and_after_the_operator_rescale(self):
    src = inspect.getsource(BF.run_band_fitting_pass)
    self.assertIn("agreed_shares", src)
    self.assertLess(src.index("rescale_envelope_to_operator"), src.index("apply_agreed_shares(envelope, agreed_shares)"))
    self.assertLess(src.index("apply_agreed_shares(envelope, agreed_shares)"), src.index("author_fn = _author_fn"))


class TheRunnerKeepsTheActualsAsTheAnchorForAnIntakeDirective(unittest.TestCase):
  def test_an_intake_directive_is_routed_to_agreed_shares_and_a_restructure_to_operator_levels(self):
    src = inspect.getsource(R.prepare_initial_grid_for_draft)
    self.assertIn('_rs_from_intake = str(_restructure_directive.get("source") or "") == "intake_coherence_path"', src)
    self.assertIn("_bf_agreed_shares[_rs_band_key] = round(float(_rs_cost_v), 6)", src)
    self.assertIn("agreed_shares=_bf_agreed_shares or None", src)
    self.assertIn('shared_context["intake_agreement_band_floors"]', src)
    # the operator-level override survives for a real restructure only
    self.assertIn("if _rs_from_intake:\n                _bf_agreed_shares[_rs_band_key]", src)
    self.assertIn("else:\n                _bf_operator_levels[_rs_band_key]", src)

  def test_the_intake_directive_declares_its_source(self):
    src = inspect.getsource(P.directive_for)
    self.assertIn('"source": "intake_coherence_path"', src)


if __name__ == "__main__":
  unittest.main()
