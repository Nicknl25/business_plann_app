"""Phase 9 P3.33 remediation — Commit 7a (C9).

Cascade tier proposer coverage. Existing tests covered V1, V3, V6,
V7, G5, B3 (6/30). This file adds proposer unit tests for every
remaining non-floor tier across all five cascades. Floor tiers
(V8, G7, C6, B4, H5) are handled by floor.py and never reach
propose_for_tier; they're confirmed to raise ValueError when called.
"""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)

from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (  # noqa: E402,E501
  CheckResult, EvaluatePlanResult, FailureMode, LeverMargin,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (  # noqa: E402,E501
  CASCADES, get_cascade, get_tier,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (  # noqa: E402,E501
  StepType,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.restructure_proposer import (  # noqa: E402,E501
  Proposal, propose_for_tier,
)


def _margin(*, section, field, current=None, band_min=None,
            band_target=None, band_max=None, outside_band=False,
            pinned_min=False, pinned_max=False):
  return LeverMargin(
    lever_id=field, section=section, current=current,
    band_min=band_min, band_target=band_target, band_max=band_max,
    outside_band=outside_band, pinned_min=pinned_min, pinned_max=pinned_max,
  )


def _result_with_margins(margins, *, failing_check="ebitda_positive_by_q11",
                        worst_distance=-0.04):
  return EvaluatePlanResult(
    all_pass=False, round_number=1,
    structural_completeness=True, strictness="full_acceptance_gate",
    checks=[],
    lever_margins=list(margins),
    worst_failing_check=failing_check, worst_failing_distance=worst_distance,
  )


def _generic_margins_for_tier(tier):
  """Build a margin list that gives every band-tracked lever in the
  tier a current value in-band so propose_for_tier yields a Proposal."""
  margins = []
  for lv in tier.levers:
    if lv.section in ("*",):  # sentinel levers (B1/B2/etc.) — no margin needed
      continue
    margins.append(_margin(
      section=lv.section, field=lv.field,
      current=0.5, band_min=0.3, band_target=0.4, band_max=0.6,
    ))
  return margins


# ---------------------------------------------------------------------------
# Non-floor tiers — one parameterized test per cascade
# ---------------------------------------------------------------------------

class ViabilityTierProposerTest(unittest.TestCase):
  """V2, V4, V5 (V1, V3, V6, V7 already covered in step-5d tests)."""

  def _assert_proposes(self, tier_id, expected_step_type):
    tier = get_tier(FailureMode.VIABILITY_INVARIANT, tier_id)
    margins = _generic_margins_for_tier(tier)
    result = _result_with_margins(margins)
    out = propose_for_tier(FailureMode.VIABILITY_INVARIANT, tier, result)
    self.assertIsNotNone(out, f"Tier {tier_id} must produce a proposal")
    head = out[0] if isinstance(out, list) else out
    self.assertEqual(head.tier_id, tier_id)
    self.assertEqual(head.mode, FailureMode.VIABILITY_INVARIANT)
    self.assertEqual(head.step_type, expected_step_type)

  def test_v2(self) -> None: self._assert_proposes("V2", StepType.TYPE_A)
  def test_v4(self) -> None: self._assert_proposes("V4", StepType.TYPE_A)
  def test_v5(self) -> None: self._assert_proposes("V5", StepType.TYPE_A)


class GrowthTierProposerTest(unittest.TestCase):
  """G1, G2, G3, G4, G6 (G5 already covered)."""

  def _assert_proposes(self, tier_id, expected_step_type):
    tier = get_tier(FailureMode.GROWTH_INVARIANT, tier_id)
    margins = _generic_margins_for_tier(tier)
    result = _result_with_margins(margins,
                                  failing_check="revenue_not_flat_q1_q10")
    out = propose_for_tier(FailureMode.GROWTH_INVARIANT, tier, result)
    self.assertIsNotNone(out, f"Tier {tier_id} must produce a proposal")
    head = out[0] if isinstance(out, list) else out
    self.assertEqual(head.tier_id, tier_id)
    self.assertEqual(head.step_type, expected_step_type)

  def test_g1(self) -> None: self._assert_proposes("G1", StepType.TYPE_A)
  def test_g2(self) -> None: self._assert_proposes("G2", StepType.TYPE_A)
  def test_g3(self) -> None: self._assert_proposes("G3", StepType.TYPE_B)
  def test_g4(self) -> None: self._assert_proposes("G4", StepType.TYPE_A)
  def test_g6(self) -> None: self._assert_proposes("G6", StepType.TYPE_A)


class CapacityTierProposerTest(unittest.TestCase):
  """C1, C2, C3, C4, C5 (none previously covered)."""

  def _assert_proposes(self, tier_id, expected_step_type):
    tier = get_tier(FailureMode.CAPACITY_INVARIANT, tier_id)
    margins = _generic_margins_for_tier(tier)
    result = _result_with_margins(margins,
                                  failing_check="stage_ramp_max_util_respected")
    out = propose_for_tier(FailureMode.CAPACITY_INVARIANT, tier, result)
    self.assertIsNotNone(out)
    head = out[0] if isinstance(out, list) else out
    self.assertEqual(head.tier_id, tier_id)
    self.assertEqual(head.step_type, expected_step_type)

  def test_c1(self) -> None: self._assert_proposes("C1", StepType.TYPE_A)
  def test_c2(self) -> None: self._assert_proposes("C2", StepType.TYPE_A)
  def test_c3(self) -> None: self._assert_proposes("C3", StepType.TYPE_A)
  def test_c4(self) -> None: self._assert_proposes("C4", StepType.TYPE_B)
  def test_c5(self) -> None: self._assert_proposes("C5", StepType.TYPE_A)


class BandTierProposerTest(unittest.TestCase):
  """B1, B2 (B3 already covered). All have '*' sentinel levers."""

  def _assert_proposes(self, tier_id, expected_step_type):
    tier = get_tier(FailureMode.BAND_INVARIANT, tier_id)
    # Band tiers use '*' sentinel levers; the proposer falls back to a
    # placeholder proposal (no margin recorded path).
    result = _result_with_margins([_margin(
      section="drivers", field="expenses::Marketing",
      current=0.5, band_min=0.3, band_target=0.4, band_max=0.6,
      outside_band=True,
    )])
    out = propose_for_tier(FailureMode.BAND_INVARIANT, tier, result)
    self.assertIsNotNone(out)
    head = out[0] if isinstance(out, list) else out
    self.assertEqual(head.tier_id, tier_id)
    self.assertEqual(head.step_type, expected_step_type)

  def test_b1(self) -> None: self._assert_proposes("B1", StepType.TYPE_A)
  def test_b2(self) -> None: self._assert_proposes("B2", StepType.TYPE_A)


class CoherenceTierProposerTest(unittest.TestCase):
  """H1, H2, H3, H4 (none previously covered)."""

  def _assert_proposes(self, tier_id, expected_step_type):
    tier = get_tier(FailureMode.COHERENCE_INVARIANT, tier_id)
    result = _result_with_margins(
      [_margin(section="drivers", field="expenses::Marketing",
               current=0.5, band_min=0.3, band_target=0.4, band_max=0.6)],
      failing_check="stage_ramp_rev_max_respected",
    )
    out = propose_for_tier(FailureMode.COHERENCE_INVARIANT, tier, result)
    self.assertIsNotNone(out)
    head = out[0] if isinstance(out, list) else out
    self.assertEqual(head.tier_id, tier_id)
    self.assertEqual(head.step_type, expected_step_type)

  def test_h1(self) -> None: self._assert_proposes("H1", StepType.TYPE_A)
  def test_h2(self) -> None: self._assert_proposes("H2", StepType.TYPE_A)
  def test_h3(self) -> None: self._assert_proposes("H3", StepType.TYPE_A)
  def test_h4(self) -> None: self._assert_proposes("H4", StepType.TYPE_A)


# ---------------------------------------------------------------------------
# Floor tiers — propose_for_tier must NOT be called for them
# ---------------------------------------------------------------------------

class FloorTiersRejectedByProposerTest(unittest.TestCase):
  """V8, G7, C6, B4, H5 are all FLOOR tiers; propose_for_tier raises."""

  def _assert_floor_raises(self, mode, tier_id):
    tier = get_tier(mode, tier_id)
    self.assertTrue(tier.is_floor)
    self.assertEqual(tier.step_type, StepType.FLOOR)
    result = _result_with_margins([])
    with self.assertRaises(ValueError):
      propose_for_tier(mode, tier, result)

  def test_v8_floor(self) -> None:
    self._assert_floor_raises(FailureMode.VIABILITY_INVARIANT, "V8")
  def test_g7_floor(self) -> None:
    self._assert_floor_raises(FailureMode.GROWTH_INVARIANT, "G7")
  def test_c6_floor(self) -> None:
    self._assert_floor_raises(FailureMode.CAPACITY_INVARIANT, "C6")
  def test_b4_floor(self) -> None:
    self._assert_floor_raises(FailureMode.BAND_INVARIANT, "B4")
  def test_h5_floor(self) -> None:
    self._assert_floor_raises(FailureMode.COHERENCE_INVARIANT, "H5")


# ---------------------------------------------------------------------------
# Coverage completeness — every non-floor tier must be in the test set above
# ---------------------------------------------------------------------------

class CoverageMatrixTest(unittest.TestCase):
  """Regression: any new tier added to a cascade table must also be
  added to this test file's per-cascade test class."""

  EXISTING_OR_NEW_COVERAGE = {
    "V1", "V2", "V3", "V4", "V5", "V6", "V7",
    "G1", "G2", "G3", "G4", "G5", "G6",
    "C1", "C2", "C3", "C4", "C5",
    "B1", "B2", "B3",
    "H1", "H2", "H3", "H4",
  }

  def test_every_non_floor_tier_covered(self) -> None:
    uncovered = []
    for mode, tiers in CASCADES.items():
      for t in tiers:
        if t.is_floor:
          continue
        if t.tier_id not in self.EXISTING_OR_NEW_COVERAGE:
          uncovered.append(f"{mode.value}::{t.tier_id}")
    self.assertEqual(uncovered, [],
                     f"New tiers without test coverage: {uncovered}")


if __name__ == "__main__":
  unittest.main()
