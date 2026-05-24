"""Phase 9 P3.33 Phase 3 step 5a — cascade policy tables.

Verifies the §5 cascade tables match the spec column-by-column: each
mode has the right tier ids, the right reason_codes, the right step
types, and the bound-relaxation / floor positions match spec §4.1 +
§8.3.

Also verifies the §14.x user decisions are encoded: anchor authority
order (§14.2), bound-relaxation cap (§14.1), progress threshold
(§14.5).
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


class CascadeShapeTest(unittest.TestCase):
  """Per-cascade tier ids + spec-mandated Type B / floor positions."""

  def test_all_five_cascades_match_spec_section_5(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (
      FailureMode,
    )
    from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
      get_cascade,
    )
    from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (
      ReasonCode, StepType,
    )

    # tier ids per mode
    cases = {
      FailureMode.VIABILITY_INVARIANT:
        ["V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8"],
      FailureMode.GROWTH_INVARIANT:
        ["G1", "G2", "G3", "G4", "G5", "G6", "G7"],
      FailureMode.CAPACITY_INVARIANT:
        ["C1", "C2", "C3", "C4", "C5", "C6"],
      FailureMode.BAND_INVARIANT:
        ["B1", "B2", "B3", "B4"],
      FailureMode.COHERENCE_INVARIANT:
        ["H1", "H2", "H3", "H4", "H5"],
    }
    for mode, expected_ids in cases.items():
      tiers = get_cascade(mode)
      self.assertEqual([t.tier_id for t in tiers], expected_ids,
                       msg=f"{mode.value}: tier id list mismatch")
      self.assertTrue(tiers[-1].is_floor,
                      msg=f"{mode.value}: final tier must be the floor")

    # spec-mandated Type B positions: V3 (pricing), V6 (payroll restructure),
    # G3 (pricing), G5 (target compression), C4 (target compression), B3 (rare).
    via = get_cascade(FailureMode.VIABILITY_INVARIANT)
    self.assertEqual(via[2].step_type, StepType.TYPE_B)  # V3
    self.assertEqual(via[5].step_type, StepType.TYPE_B)  # V6
    grw = get_cascade(FailureMode.GROWTH_INVARIANT)
    self.assertEqual(grw[2].step_type, StepType.TYPE_B)  # G3
    self.assertEqual(grw[4].step_type, StepType.TYPE_B)  # G5
    cap = get_cascade(FailureMode.CAPACITY_INVARIANT)
    self.assertEqual(cap[3].step_type, StepType.TYPE_B)  # C4

    # C2 over C1 — utilization re-anchor preferred over capacity resize.
    self.assertEqual(cap[0].reason_code, ReasonCode.CAPACITY_UTIL_REANCHORED)
    self.assertEqual(cap[1].reason_code, ReasonCode.CAPACITY_RESIZED)


class TierPropertiesTest(unittest.TestCase):
  def test_is_bound_relaxation_recognized_per_mode(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (
      FailureMode,
    )
    from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
      get_cascade,
    )
    # V7, G6, C5, B3, H4 should report is_bound_relaxation=True.
    self.assertTrue(get_cascade(FailureMode.VIABILITY_INVARIANT)[6].is_bound_relaxation)
    self.assertTrue(get_cascade(FailureMode.GROWTH_INVARIANT)[5].is_bound_relaxation)
    self.assertTrue(get_cascade(FailureMode.CAPACITY_INVARIANT)[4].is_bound_relaxation)
    self.assertTrue(get_cascade(FailureMode.BAND_INVARIANT)[2].is_bound_relaxation)
    self.assertTrue(get_cascade(FailureMode.COHERENCE_INVARIANT)[3].is_bound_relaxation)

  def test_is_target_compression_recognized(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (
      FailureMode,
    )
    from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
      get_cascade,
    )
    # G5 and C4 are target compressions.
    self.assertTrue(get_cascade(FailureMode.GROWTH_INVARIANT)[4].is_target_compression)
    self.assertTrue(get_cascade(FailureMode.CAPACITY_INVARIANT)[3].is_target_compression)


class AccessorTest(unittest.TestCase):
  def test_get_tier_returns_named_tier(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (
      FailureMode,
    )
    from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
      get_tier,
    )
    t = get_tier(FailureMode.VIABILITY_INVARIANT, "V3")
    self.assertEqual(t.name, "Pricing")

  def test_get_tier_raises_for_unknown_id(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (
      FailureMode,
    )
    from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
      get_tier,
    )
    with self.assertRaises(KeyError):
      get_tier(FailureMode.VIABILITY_INVARIANT, "V99")

  def test_next_tier_advances(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (
      FailureMode,
    )
    from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
      next_tier,
    )
    nxt = next_tier(FailureMode.VIABILITY_INVARIANT, "V3")
    self.assertIsNotNone(nxt)
    self.assertEqual(nxt.tier_id, "V4")

  def test_next_tier_from_none_returns_first(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (
      FailureMode,
    )
    from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
      next_tier,
    )
    nxt = next_tier(FailureMode.GROWTH_INVARIANT, None)
    self.assertIsNotNone(nxt)
    self.assertEqual(nxt.tier_id, "G1")

  def test_next_tier_at_end_returns_none(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (
      FailureMode,
    )
    from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
      next_tier,
    )
    self.assertIsNone(next_tier(FailureMode.VIABILITY_INVARIANT, "V8"))

  def test_meta_mode_has_no_cascade(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (
      FailureMode,
    )
    from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
      get_cascade,
    )
    with self.assertRaises(KeyError):
      get_cascade(FailureMode.META_INVARIANT)


class UserDecisionConstantsTest(unittest.TestCase):
  def test_q1_bound_relaxation_cap_3x5pct(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
      BOUND_RELAXATION_STEP_FRACTION,
      BOUND_RELAXATION_MAX_ATTEMPTS,
      BOUND_RELAXATION_CUMULATIVE_CAP,
    )
    self.assertEqual(BOUND_RELAXATION_STEP_FRACTION, 0.05)
    self.assertEqual(BOUND_RELAXATION_MAX_ATTEMPTS, 3)
    self.assertAlmostEqual(BOUND_RELAXATION_CUMULATIVE_CAP, 0.15)

  def test_q2_anchor_authority_order(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
      coherence_anchor_order,
    )
    self.assertEqual(
      coherence_anchor_order(),
      ("stage_ramp", "drivers", "payroll", "capex_rd", "balance_sheet"),
    )

  def test_q5_progress_threshold_10pct(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
      PROGRESS_THRESHOLD_FRACTION,
      MAX_CONSECUTIVE_NO_PROGRESS,
    )
    self.assertAlmostEqual(PROGRESS_THRESHOLD_FRACTION, 0.10)
    self.assertEqual(MAX_CONSECUTIVE_NO_PROGRESS, 2)

  def test_budget_defaults(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
      DEFAULT_TOOL_CALL_BUDGET,
      BUDGET_AWARE_THRESHOLD,
      BUDGET_FLOOR_THRESHOLD,
    )
    self.assertEqual(DEFAULT_TOOL_CALL_BUDGET, 35)
    self.assertEqual(BUDGET_AWARE_THRESHOLD, 5)
    self.assertEqual(BUDGET_FLOOR_THRESHOLD, 1)


class ModePriorityTest(unittest.TestCase):
  def test_section_7_1_priority_order(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (
      FailureMode,
    )
    from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
      MODE_PRIORITY,
    )
    self.assertEqual(MODE_PRIORITY, (
      FailureMode.BAND_INVARIANT,
      FailureMode.COHERENCE_INVARIANT,
      FailureMode.CAPACITY_INVARIANT,
      FailureMode.GROWTH_INVARIANT,
      FailureMode.VIABILITY_INVARIANT,
    ))


class ReasonCodeCoverageTest(unittest.TestCase):
  def test_every_cascade_tier_reason_code_belongs_to_mode(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
      CASCADES,
    )
    from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (
      reason_code_belongs_to_mode,
    )
    for mode, tiers in CASCADES.items():
      for tier in tiers:
        self.assertTrue(
          reason_code_belongs_to_mode(tier.reason_code, mode),
          msg=f"{tier.tier_id}: {tier.reason_code.value} not in {mode.value}",
        )


if __name__ == "__main__":
  unittest.main()
