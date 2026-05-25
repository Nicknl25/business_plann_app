"""Phase 9 P3.33 remediation — Commit 3 (B7).

FailFastCode enum + FAIL_FAST_CODES_BY_PHASE partition reconciliation.

The audit (B7) finds that the enum, the inventory document, the
partition, and the call sites must agree. Step 9d landed an initial
implementation; this commit locks the agreement with parameterized
regression tests so future drift is caught at test time.

What this test file enforces:

  1. Every FailFastCode enum entry belongs to exactly one phase via
     fail_fast_code_belongs_to_phase.
  2. Partition is exhaustive: every phase listed in FAIL_FAST_CODES_BY_PHASE
     contains only valid FailFastCode members; no orphans.
  3. raise_fail_fast accepts every valid (phase, code) pair without
     raising the partition-mismatch ValueError.
  4. The inventory item count (per the docs/architecture inventory
     document) matches the enum count — currently 24.
"""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)

from client_intake_and_finmo.post_intake_diagnostics.fail_fast_codes import (  # noqa: E402,E501
  FailFastCode,
  FAIL_FAST_CODES_BY_PHASE,
  fail_fast_code_belongs_to_phase,
  raise_fail_fast,
)
from client_intake_and_finmo.post_intake_diagnostics.phase_codes import (  # noqa: E402,E501
  PhaseCode,
)


# Inventory document item count (after item 13 was dropped per
# docs/architecture/p3_33_phase35_fail_fast_inventory.md §2.6).
_INVENTORY_ITEM_COUNT = 24


class FailFastCodePartitionTest(unittest.TestCase):
  def test_enum_count_matches_inventory(self) -> None:
    """Inventory document says 24 items; enum must match exactly."""
    self.assertEqual(
      len(list(FailFastCode)), _INVENTORY_ITEM_COUNT,
      f"Enum size drift: {len(list(FailFastCode))} codes in enum vs "
      f"{_INVENTORY_ITEM_COUNT} items in inventory document. Update "
      f"both in lockstep when adding/removing fail-fast points.",
    )

  def test_every_code_belongs_to_exactly_one_phase(self) -> None:
    """Each FailFastCode must appear in exactly one phase's frozenset."""
    issues = []
    for code in FailFastCode:
      phase_matches = [
        phase for phase in PhaseCode
        if fail_fast_code_belongs_to_phase(code, phase)
      ]
      if len(phase_matches) != 1:
        issues.append(
          f"{code.value} -> phases={[p.value for p in phase_matches]}"
        )
    self.assertEqual(
      issues, [],
      "Codes not partitioned cleanly:\n  " + "\n  ".join(issues),
    )

  def test_partition_contains_only_valid_codes(self) -> None:
    """No orphan strings or stale enum members in the partition."""
    enum_members = set(FailFastCode)
    for phase, codes in FAIL_FAST_CODES_BY_PHASE.items():
      for code in codes:
        self.assertIn(
          code, enum_members,
          f"Phase {phase.value} references {code!r} which is not a "
          f"FailFastCode enum member.",
        )

  def test_partition_total_equals_enum_count(self) -> None:
    """Partition must cover all enum members; sizes match."""
    partition_total = sum(len(s) for s in FAIL_FAST_CODES_BY_PHASE.values())
    self.assertEqual(
      partition_total, len(list(FailFastCode)),
      f"Partition total ({partition_total}) != enum count "
      f"({len(list(FailFastCode))}).",
    )


class RaiseFailFastAcceptsAllCodesTest(unittest.TestCase):
  """raise_fail_fast() validates (phase, code) before emitting. This
  test confirms every valid pair passes the validator gate — i.e. each
  code has a phase it can be called from without the validator's
  fail_fast_code_phase_mismatch ValueError."""

  def test_each_code_can_be_raised_with_its_phase(self) -> None:
    for code in FailFastCode:
      # Find this code's phase from the partition.
      its_phase = next(
        (p for p, s in FAIL_FAST_CODES_BY_PHASE.items() if code in s),
        None,
      )
      self.assertIsNotNone(
        its_phase, f"Code {code.value} not in any phase",
      )
      # Calling raise_fail_fast with the matching phase must raise
      # RuntimeError (the fail-fast itself), NOT ValueError (the
      # partition-mismatch guard).
      with self.assertRaises(RuntimeError) as ctx:
        raise_fail_fast(
          conn=None, draft_id="d", planning_run_id="r",
          phase=its_phase, code=code,
          detail="parameterized test", where="test",
        )
      # The exception message must carry the fail-fast prefix + the code value.
      self.assertIn("post_intake_fail_fast::", str(ctx.exception))
      self.assertIn(code.value, str(ctx.exception))

  def test_mismatched_phase_raises_validator_error(self) -> None:
    """When called with a wrong phase, raise_fail_fast raises
    ValueError (the partition-mismatch guard) BEFORE re-raising the
    fail-fast — so misuse never produces a stealthy audit row."""
    # Pick any code and a phase that doesn't own it.
    code = FailFastCode.FAIL_COHORT_BANDS_MISSING
    its_phase = PhaseCode.COHORT_BANDS_POPULATOR
    wrong_phase = next(p for p in PhaseCode if p is not its_phase)
    with self.assertRaises(ValueError) as ctx:
      raise_fail_fast(
        conn=None, draft_id="d", planning_run_id="r",
        phase=wrong_phase, code=code,
        detail="mismatched", where="test",
      )
    self.assertIn("fail_fast_code_phase_mismatch", str(ctx.exception))


if __name__ == "__main__":
  unittest.main()
