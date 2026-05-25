"""P3.33 Phase 3 step 9d — FailFastCode enum closure + partition tests.

The enum is the source of truth for the 25 fail-fast points catalogued
in docs/architecture/p3_33_phase35_fail_fast_inventory.md. These tests
guard:

  * Every FailFastCode appears in exactly one phase's frozenset.
  * Every phase that the inventory says has fail-fast points has them
    registered.
  * Cross-phase claims raise (mismatch detection).
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


from client_intake_and_finmo.post_intake_diagnostics.fail_fast_codes import (
  FAIL_FAST_CODES_BY_PHASE,
  FAIL_FAST_PREFIX,
  FailFastCode,
  fail_fast_code_belongs_to_phase,
)
from client_intake_and_finmo.post_intake_diagnostics.phase_codes import (
  PhaseCode,
)


EXPECTED_COUNT = 25


class FailFastCodeEnumTest(unittest.TestCase):
  def test_enum_has_25_members(self) -> None:
    self.assertEqual(len(list(FailFastCode)), EXPECTED_COUNT)

  def test_prefix_constant(self) -> None:
    self.assertEqual(FAIL_FAST_PREFIX, "post_intake_fail_fast::")

  def test_values_are_snake_case_with_fail_prefix(self) -> None:
    for code in FailFastCode:
      self.assertTrue(code.value.startswith("fail_"),
                      msg=f"{code.value} missing fail_ prefix")
      self.assertEqual(code.value, code.value.lower())
      self.assertNotIn(" ", code.value)


class FailFastPartitionTest(unittest.TestCase):
  def test_every_code_in_exactly_one_phase(self) -> None:
    seen: dict = {}
    for phase, codes in FAIL_FAST_CODES_BY_PHASE.items():
      for code in codes:
        self.assertNotIn(
          code, seen,
          msg=f"{code.value} appears in two phases: "
              f"{seen.get(code, '?')} and {phase.value}")
        seen[code] = phase.value
    self.assertEqual(len(seen), EXPECTED_COUNT,
                     msg=f"expected {EXPECTED_COUNT} codes, got {len(seen)}")

  def test_every_enum_member_partitioned(self) -> None:
    partitioned = set()
    for codes in FAIL_FAST_CODES_BY_PHASE.values():
      partitioned.update(codes)
    self.assertEqual(set(FailFastCode), partitioned,
                     msg="enum members and partition are out of sync")

  def test_phases_with_fail_fast_points(self) -> None:
    # Per inventory: every phase has at least one fail-fast point.
    for phase in PhaseCode:
      self.assertIn(
        phase, FAIL_FAST_CODES_BY_PHASE,
        msg=f"phase {phase.value} has no fail-fast partition entry")
      self.assertGreaterEqual(
        len(FAIL_FAST_CODES_BY_PHASE[phase]), 1,
        msg=f"phase {phase.value} has empty fail-fast set")

  def test_belongs_to_phase_positive(self) -> None:
    self.assertTrue(fail_fast_code_belongs_to_phase(
      FailFastCode.FAIL_REALISM_BAND_SOURCE_MISSING,
      PhaseCode.REALISM_GATE))

  def test_belongs_to_phase_negative(self) -> None:
    self.assertFalse(fail_fast_code_belongs_to_phase(
      FailFastCode.FAIL_REALISM_BAND_SOURCE_MISSING,
      PhaseCode.CASH_PASS))


if __name__ == "__main__":
  unittest.main()
