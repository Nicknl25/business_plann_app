"""Phase 9 P3.33 Phase 3 step 4a — ReasonCode / AppliedBy / StepType enums.

Verifies the closed-enum surfaces in ``protocol.reason_codes`` match spec
§10.2 (ReasonCode), §10.3 (AppliedBy), and §6 (StepType), and that the
``(mode, reason_code)`` pairing rule rejects mismatched pairs.

The ``post_intake_restructuring_log`` DDL + row writer (which use these
enums) land in the next commit and are covered there.
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


class ReasonCodeEnumTest(unittest.TestCase):
  def test_reason_code_enum_is_closed_set(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (
      ReasonCode,
    )
    values = {c.value for c in ReasonCode}
    # Spec §10.2 enumerates 38 codes total
    # (9 VIABILITY + 8 GROWTH + 7 CAPACITY + 5 BAND + 6 COHERENCE + 3 meta).
    self.assertEqual(len(values), 38)
    # Spot-check one code per mode plus the meta tail.
    for expected in (
      "VIABILITY_COST_RATIO_TUNED",
      "GROWTH_RAMP_RESHAPED",
      "CAPACITY_UTIL_REANCHORED",
      "BAND_CLIPPED",
      "COHERENCE_ANCHOR_CHOSEN",
      "META_ESCALATED",
      "STAGNATION_FLOOR_ALL",
      "BUDGET_EXHAUSTED_FLOOR",
    ):
      self.assertIn(expected, values)

  def test_reason_code_is_str_enum(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (
      ReasonCode,
    )
    # str-Enum lets callers serialise without manual .value calls.
    self.assertEqual(str(ReasonCode.VIABILITY_BOUND_RELAXED.value),
                     "VIABILITY_BOUND_RELAXED")
    self.assertEqual(ReasonCode.BAND_CLIPPED.value, "BAND_CLIPPED")


class AppliedByEnumTest(unittest.TestCase):
  def test_applied_by_enum_is_closed_set(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (
      AppliedBy,
    )
    values = {a.value for a in AppliedBy}
    self.assertEqual(values, {
      "amalgamated_gpt_confirmed",
      "amalgamated_gpt_vetoed",
      "amalgamated_gpt_chose",
      "amalgamated_gpt_other",
      "amalgamated_gpt_other_out_band",
      "deterministic_floor",
      "floor_primitive",
      "meta_escalation",
      "budget_aware_auto_confirm",
      "monotonic_guard_reverted",
    })


class StepTypeEnumTest(unittest.TestCase):
  def test_step_type_enum_values(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (
      StepType,
    )
    self.assertEqual(StepType.TYPE_A.value, "A")
    self.assertEqual(StepType.TYPE_B.value, "B")
    self.assertEqual(StepType.FLOOR.value, "floor")
    self.assertEqual(StepType.META.value, "meta")


class ReasonCodeBelongsToModeTest(unittest.TestCase):
  def test_accepts_matched_pair(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (
      FailureMode,
    )
    from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (
      ReasonCode,
      reason_code_belongs_to_mode,
    )
    self.assertTrue(reason_code_belongs_to_mode(
      ReasonCode.VIABILITY_COST_RATIO_TUNED, FailureMode.VIABILITY_INVARIANT
    ))
    self.assertTrue(reason_code_belongs_to_mode(
      ReasonCode.STAGNATION_FLOOR_ALL, FailureMode.META_INVARIANT
    ))
    self.assertTrue(reason_code_belongs_to_mode(
      ReasonCode.GROWTH_TARGET_COMPRESSED, FailureMode.GROWTH_INVARIANT
    ))
    self.assertTrue(reason_code_belongs_to_mode(
      ReasonCode.BAND_CLIPPED, FailureMode.BAND_INVARIANT
    ))
    self.assertTrue(reason_code_belongs_to_mode(
      ReasonCode.COHERENCE_ANCHOR_CHOSEN, FailureMode.COHERENCE_INVARIANT
    ))
    self.assertTrue(reason_code_belongs_to_mode(
      ReasonCode.CAPACITY_UTIL_REANCHORED, FailureMode.CAPACITY_INVARIANT
    ))

  def test_rejects_cross_pair(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (
      FailureMode,
    )
    from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (
      ReasonCode,
      reason_code_belongs_to_mode,
    )
    # VIABILITY reason against a GROWTH mode is illegal.
    self.assertFalse(reason_code_belongs_to_mode(
      ReasonCode.VIABILITY_COST_RATIO_TUNED, FailureMode.GROWTH_INVARIANT
    ))
    # META meta-code against a VIABILITY mode is illegal too.
    self.assertFalse(reason_code_belongs_to_mode(
      ReasonCode.STAGNATION_FLOOR_ALL, FailureMode.VIABILITY_INVARIANT
    ))


if __name__ == "__main__":
  unittest.main()
