"""Phase 9 P3.33 Phase 3 step 9a part 1 — PhaseCode + EventCode + Status enums.

Hermetic tests for the closed-enum surface in
``post_intake_diagnostics.phase_codes``. The writer + DDL land in the
next commit (9a part 2) with their own tests against an in-memory
fake cursor.

Confirms:
  - PhaseCode has exactly 13 phases (per step-9 directive).
  - Status enum covers started / completed / failed / skipped.
  - Every PhaseCode has at least one EventCode registered.
  - EventCode total is in the directive's ~30-50 range (we ship 49).
  - Every EventCode belongs to exactly one phase (no overlaps).
  - event_code_belongs_to_phase accepts matched pairs + rejects
    mismatched ones.
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)

from client_intake_and_finmo.post_intake_diagnostics.phase_codes import (  # noqa: E402,E501
  EVENT_CODES_BY_PHASE,
  EventCode,
  PhaseCode,
  Status,
  event_code_belongs_to_phase,
)


class PhaseCodeEnumTest(unittest.TestCase):
  def test_phase_code_has_eighteen_phases(self) -> None:
    # 18 = 13 original + MODEL_INPUT_CONTRACT (P3.40 Contract 1)
    #    + SOLVER_INPUT_CONTRACT (P3.40 Contract 3)
    #    + WORKBOOK_PAYLOAD_CONTRACT (P3.40 Contract 2 diagnostic
    #      restoration follow-up)
    #    + SOLVER_OUTPUT_CONTRACT (P3.40 Contract 4)
    #    + INTAKE_DRAFT_CONTRACT (P3.40 Contract 5).
    self.assertEqual(len(PhaseCode), 18)

  def test_status_enum_values(self) -> None:
    self.assertEqual(Status.STARTED.value, "started")
    self.assertEqual(Status.COMPLETED.value, "completed")
    self.assertEqual(Status.FAILED.value, "failed")
    self.assertEqual(Status.SKIPPED.value, "skipped")

  def test_every_phase_has_at_least_one_event(self) -> None:
    for phase in PhaseCode:
      events = EVENT_CODES_BY_PHASE.get(phase)
      self.assertIsNotNone(events, msg=f"{phase.value} has no events")
      self.assertGreater(len(events), 0, msg=f"{phase.value} has empty events set")

  def test_event_codes_count_is_substantial(self) -> None:
    """Per step-9 directive: ~30-50 events across the phases."""
    total = sum(len(s) for s in EVENT_CODES_BY_PHASE.values())
    self.assertGreaterEqual(total, 40)


class PhaseEventPairingTest(unittest.TestCase):
  def test_matched_pair_accepted(self) -> None:
    self.assertTrue(event_code_belongs_to_phase(
      EventCode.CASCADE_PROPOSAL_CONFIRMED, PhaseCode.CASCADE_WALK,
    ))
    self.assertTrue(event_code_belongs_to_phase(
      EventCode.FINALIZE_VALIDATION_FAILED, PhaseCode.FINALIZE,
    ))

  def test_mismatched_pair_rejected(self) -> None:
    self.assertFalse(event_code_belongs_to_phase(
      EventCode.CASCADE_PROPOSAL_CONFIRMED, PhaseCode.CASH_PASS,
    ))

  def test_every_event_code_belongs_to_exactly_one_phase(self) -> None:
    """No event_code should appear under two phase partitions, and the
    union of all phase partitions should be every EventCode entry."""
    seen: dict = {}
    for phase, events in EVENT_CODES_BY_PHASE.items():
      for event in events:
        if event in seen:
          self.fail(
            f"{event.value} appears under both "
            f"{seen[event].value} and {phase.value}"
          )
        seen[event] = phase
    self.assertEqual(len(seen), len(EventCode))


if __name__ == "__main__":
  unittest.main()
