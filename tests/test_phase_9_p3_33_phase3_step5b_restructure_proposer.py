"""Phase 9 P3.33 Phase 3 step 5b — restructure_proposer.

Hermetic tests on the per-tier proposal builder. Confirms:

  - Type A: picks the highest-priority unpinned lever (§4.3), resolves
    'to_band_target' / 'to_band_max' against LeverMargin, returns a
    structured Proposal with rationale_text including the failing-check
    handle.
  - Smart entry (§4.2): all levers pinned -> None.
  - Type B generators: V3/G3 pricing returns premium + value options,
    G5/C4 returns three compression options, V6 returns class-cut
    options, B3 returns relax-vs-rebuild options.
  - Bound relaxation: V7/G6/C5/H4 returns a Proposal that records the
    relaxed bound (band_max × 1.05) rather than a current/proposed
    lever value.
  - Floor tier: proposer raises (caller routes to floor.py).
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)

from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (  # noqa: E402
  EvaluatePlanResult, FailureMode, LeverMargin,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (  # noqa: E402
  get_tier,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.restructure_proposer import (  # noqa: E402,E501
  propose_for_tier,
)


def _make_margin(*, section, lever_id, current, band_min, band_target, band_max,
                 pinned_min=False, pinned_max=False, outside_band=False, quarter=None):
  return LeverMargin(
    lever_id=lever_id, section=section, quarter=quarter,
    current=current, band_min=band_min, band_target=band_target, band_max=band_max,
    distance_to_min=(current - band_min) if (current is not None and band_min is not None) else None,
    distance_to_max=(band_max - current) if (current is not None and band_max is not None) else None,
    pinned_min=pinned_min, pinned_max=pinned_max, outside_band=outside_band,
  )


def _make_result(*, margins, worst_check=None, worst_distance=None):
  return EvaluatePlanResult(
    all_pass=False, round_number=2,
    structural_completeness=True,
    strictness="full_acceptance_gate",
    lever_margins=margins,
    worst_failing_check=worst_check,
    worst_failing_distance=worst_distance,
  )


class TypeAProposerTest(unittest.TestCase):
  def test_v1_proposes_cogs_to_band_target(self) -> None:
    margins = [
      _make_margin(section="drivers",
                   lever_id="expenses::Cost of Goods Sold",
                   current=0.72, band_min=0.55, band_target=0.65, band_max=0.78),
      _make_margin(section="drivers",
                   lever_id="expenses::Marketing",
                   current=0.10, band_min=0.06, band_target=0.10, band_max=0.14),
    ]
    result = _make_result(margins=margins,
                          worst_check="ebitda_positive_by_q11",
                          worst_distance=-0.04)
    tier = get_tier(FailureMode.VIABILITY_INVARIANT, "V1")
    p = propose_for_tier(FailureMode.VIABILITY_INVARIANT, tier, result)
    self.assertIsNotNone(p)
    self.assertEqual(p.section, "drivers")
    self.assertEqual(p.field, "expenses::Cost of Goods Sold")
    self.assertAlmostEqual(p.current_value, 0.72)
    self.assertAlmostEqual(p.proposed_value, 0.65)
    self.assertIn("ebitda_positive_by_q11", p.rationale_text)
    self.assertIn("0.72", p.rationale_text)

  def test_smart_entry_returns_none_when_all_levers_pinned(self) -> None:
    margins = [
      _make_margin(section="drivers",
                   lever_id="expenses::Cost of Goods Sold",
                   current=0.65, band_min=0.55, band_target=0.65, band_max=0.78),
      _make_margin(section="drivers",
                   lever_id="expenses::Marketing",
                   current=0.10, band_min=0.06, band_target=0.10, band_max=0.14),
      _make_margin(section="drivers",
                   lever_id="expenses::General & Administrative",
                   current=0.18, band_min=0.10, band_target=0.18, band_max=0.25),
      _make_margin(section="drivers",
                   lever_id="expenses::Research & Development",
                   current=0.07, band_min=0.05, band_target=0.07, band_max=0.10),
    ]
    result = _make_result(margins=margins,
                          worst_check="ebitda_positive_by_q11",
                          worst_distance=-0.04)
    tier = get_tier(FailureMode.VIABILITY_INVARIANT, "V1")
    self.assertIsNone(propose_for_tier(FailureMode.VIABILITY_INVARIANT, tier, result))

  def test_out_of_band_lever_jumps_priority(self) -> None:
    """Out-of-band lever wins over priority-1 in-band lever (§4.3
    'most-out-of-band first')."""
    margins = [
      _make_margin(section="drivers",
                   lever_id="expenses::Cost of Goods Sold",
                   current=0.66, band_min=0.55, band_target=0.65, band_max=0.78),
      _make_margin(section="drivers",
                   lever_id="expenses::Marketing",
                   current=0.20, band_min=0.06, band_target=0.10, band_max=0.14,
                   outside_band=True),
    ]
    result = _make_result(margins=margins, worst_check="margin_floor_q11",
                          worst_distance=-0.02)
    tier = get_tier(FailureMode.VIABILITY_INVARIANT, "V1")
    p = propose_for_tier(FailureMode.VIABILITY_INVARIANT, tier, result)
    self.assertIsNotNone(p)
    self.assertEqual(p.field, "expenses::Marketing")


class TypeBProposerTest(unittest.TestCase):
  def test_v3_pricing_returns_premium_and_value_options(self) -> None:
    margins = [
      _make_margin(section="operating_model", lever_id="unit_price",
                   current=20.0, band_min=15.0, band_target=22.0, band_max=30.0),
    ]
    result = _make_result(margins=margins,
                          worst_check="ebitda_positive_by_q11",
                          worst_distance=-0.04)
    tier = get_tier(FailureMode.VIABILITY_INVARIANT, "V3")
    opts = propose_for_tier(FailureMode.VIABILITY_INVARIANT, tier, result)
    self.assertEqual(len(opts), 2)
    self.assertEqual({o.option_id for o in opts}, {"A", "B"})
    a = next(o for o in opts if o.option_id == "A")
    b = next(o for o in opts if o.option_id == "B")
    self.assertAlmostEqual(a.proposed_value, 30.0)
    self.assertAlmostEqual(b.proposed_value, 15.0)
    self.assertIn("Premium", a.summary)
    self.assertIn("Value", b.summary)

  def test_g5_returns_three_compression_options(self) -> None:
    tier = get_tier(FailureMode.GROWTH_INVARIANT, "G5")
    opts = propose_for_tier(
      FailureMode.GROWTH_INVARIANT, tier,
      _make_result(margins=[], worst_check="growth_rate_q8", worst_distance=-0.20),
    )
    self.assertEqual([o.option_id for o in opts], ["A", "B", "C"])
    self.assertEqual([o.proposed_value for o in opts], [0.75, 0.50, 0.25])

  def test_v6_returns_class_cut_options(self) -> None:
    tier = get_tier(FailureMode.VIABILITY_INVARIANT, "V6")
    opts = propose_for_tier(
      FailureMode.VIABILITY_INVARIANT, tier,
      _make_result(margins=[], worst_check="payroll_pct_q11", worst_distance=-0.05),
    )
    self.assertEqual([o.field for o in opts], [
      "classes.general_and_administrative",
      "classes.sales_and_marketing",
      "classes.research_and_development",
    ])

  def test_b3_returns_relax_or_rebuild_options(self) -> None:
    margins = [
      _make_margin(section="drivers",
                   lever_id="expenses::Cost of Goods Sold",
                   current=0.85, band_min=0.55, band_target=0.65, band_max=0.78,
                   outside_band=True),
    ]
    tier = get_tier(FailureMode.BAND_INVARIANT, "B3")
    opts = propose_for_tier(
      FailureMode.BAND_INVARIANT, tier,
      _make_result(margins=margins, worst_check="cogs_in_band", worst_distance=-0.07),
    )
    self.assertEqual(len(opts), 2)
    self.assertEqual({o.option_id for o in opts}, {"A", "B"})


class BoundRelaxationProposerTest(unittest.TestCase):
  def test_v7_relaxes_robust_max_by_5pct(self) -> None:
    margins = [
      _make_margin(section="drivers",
                   lever_id="expenses::Research & Development",
                   current=0.07, band_min=0.05, band_target=0.07, band_max=0.10),
    ]
    tier = get_tier(FailureMode.VIABILITY_INVARIANT, "V7")
    p = propose_for_tier(
      FailureMode.VIABILITY_INVARIANT, tier,
      _make_result(margins=margins),
    )
    self.assertIsNotNone(p)
    self.assertAlmostEqual(p.band_max, 0.10)
    self.assertAlmostEqual(p.proposed_value, 0.10 * 1.05)
    self.assertIn("Relax", p.rationale_text)


class FloorRoutingTest(unittest.TestCase):
  def test_proposer_raises_on_floor_tier(self) -> None:
    tier = get_tier(FailureMode.VIABILITY_INVARIANT, "V8")
    with self.assertRaises(ValueError):
      propose_for_tier(FailureMode.VIABILITY_INVARIANT, tier,
                       _make_result(margins=[]))


if __name__ == "__main__":
  unittest.main()
