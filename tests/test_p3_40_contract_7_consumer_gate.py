"""Acceptance tests for Contract 7 Commit 3 boundary gates.

3 wired gates per F9/F10:
- Producer-side: mirror.py:329+ at build_mirror return -- Shape
  A (MirrorContract, F5 alias-sync invariant). Fires only when
  conn + draft_id + planning_run_id are supplied (production
  path).
- Consumer-side: Mirror.to_dict() at mirror.py:182-192 -- Shape
  A. Canonical serialization point; catches in-process mutation
  that violated invariants.
- Consumer-side: responder.py:269+ -- Shape D
  (ValidationStateProjectionContract, F6 i-iv invariants). Fires
  when validation_state is non-empty.

These tests exercise the 2 enforcement helpers directly with
representative valid + invalid payloads + Adjustment B
end-to-end + best-effort emit.

Spec: ``docs/architecture/p3_40_contract_7_amalgamated_session_spec.md`` §6 Commit 3.

5 test classes:
- MirrorGateTest: Shape A gate (mirror full) acceptance + F5
  alias-sync rejection + both side strings accepted.
- ValidationStateConsumerGateTest: Shape D gate acceptance +
  F6 (i)/(ii) cap violations + F6 (iv) outside_band violation.
- ApiCatchPatternEndToEndTest: Adjustment B per Contracts 3-6
  pattern.
- DiagnosticEmitBestEffortTest: both helpers succeed when
  emit_diagnostic_fn raises.
- ShapeDistinguisherTest: F12 single PhaseCode + per-shape
  diagnostic_data['shape'] partition.
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
ROOT = os.path.abspath(os.path.join(HERE, os.pardir))
for path in (PYTHON_ROOT, ROOT, HERE):
  if path not in sys.path:
    sys.path.insert(0, path)


from client_intake_and_finmo.post_intake_contracts.enforcement import (  # noqa: E402
  AMALGAMATED_SESSION_STAGE_LABEL,
  SIDE_CONSUMER,
  SIDE_PRODUCER,
  validate_amalgamated_session_at_boundary,
  validate_amalgamated_validation_state_at_boundary,
)
from client_intake_and_finmo.post_intake_contracts.amalgamated_session_contract import (  # noqa: E402
  ContractViolation,
  MirrorContract,
  ValidationStateProjectionContract,
)
from _p3_40_contract_7_fixtures import (  # noqa: E402
  valid_lever_margin_entry_dict,
  valid_mirror_dict,
  valid_validation_state_projection_dict,
)


# ---------------------------------------------------------------------------
# Shape A gate (mirror full -- producer + consumer)
# ---------------------------------------------------------------------------

class MirrorGateTest(unittest.TestCase):
  """F9 + F10/§5.2.1 Shape A gate. Same helper services both
  the producer-side (mirror.py:329+ at build_mirror return) and
  consumer-side (Mirror.to_dict()) wirings -- side= string
  distinguishes in diagnostic_data."""

  def test_valid_mirror_through_producer_gate(self) -> None:
    contract = validate_amalgamated_session_at_boundary(
      valid_mirror_dict(), side=SIDE_PRODUCER,
    )
    self.assertIsInstance(contract, MirrorContract)

  def test_valid_mirror_through_consumer_gate(self) -> None:
    contract = validate_amalgamated_session_at_boundary(
      valid_mirror_dict(), side=SIDE_CONSUMER,
    )
    self.assertIsInstance(contract, MirrorContract)

  def test_f5_alias_sync_violation_rejected(self) -> None:
    """F5: when plan_state contains both balance_sheet and
    capex_rd, payloads MUST match (Bug 2 fix invariant)."""
    payload = valid_mirror_dict()
    payload["plan_state"]["balance_sheet"] = {"a": 1}
    payload["plan_state"]["capex_rd"] = {"a": 2}
    with self.assertRaises(ContractViolation) as ctx:
      validate_amalgamated_session_at_boundary(
        payload, side=SIDE_PRODUCER,
      )
    self.assertIn("alias-sync", str(ctx.exception))

  def test_missing_required_field_rejected(self) -> None:
    payload = valid_mirror_dict()
    del payload["invariants"]
    with self.assertRaises(ContractViolation) as ctx:
      validate_amalgamated_session_at_boundary(
        payload, side=SIDE_CONSUMER,
      )
    self.assertEqual(ctx.exception.stage, AMALGAMATED_SESSION_STAGE_LABEL)


# ---------------------------------------------------------------------------
# Shape D gate (validation_state slice -- consumer-side)
# ---------------------------------------------------------------------------

class ValidationStateConsumerGateTest(unittest.TestCase):
  """F10/§5.2.2 Shape D gate wired at responder.py:269+. Exercises
  the F6 (i)/(ii)/(iv) cross-field invariants -- regressions in
  the Bug 3 producer filter surface immediately."""

  def test_valid_projection_accepted(self) -> None:
    contract = validate_amalgamated_validation_state_at_boundary(
      valid_validation_state_projection_dict(), side=SIDE_CONSUMER,
    )
    self.assertIsInstance(contract, ValidationStateProjectionContract)

  def test_f6_i_failing_check_names_cap_violation_rejected(self) -> None:
    """F6 (i): cap=12 per mirror.py:34."""
    payload = valid_validation_state_projection_dict(
      failing_check_count=15,
      failing_check_names=[f"c_{i}" for i in range(13)],
      failing_check_names_truncated=True,
    )
    with self.assertRaises(ContractViolation):
      validate_amalgamated_validation_state_at_boundary(
        payload, side=SIDE_CONSUMER,
      )

  def test_f6_ii_failing_lever_margins_cap_violation_rejected(self) -> None:
    """F6 (ii): cap=12 mirror of (i) for lever margins."""
    payload = valid_validation_state_projection_dict(
      failing_lever_margins_count=13,
      failing_lever_margins_truncated=True,
    )
    with self.assertRaises(ContractViolation):
      validate_amalgamated_validation_state_at_boundary(
        payload, side=SIDE_CONSUMER,
      )

  def test_f6_iv_outside_band_filter_violation_rejected(self) -> None:
    """F6 (iv): every failing_lever_margins entry MUST have
    outside_band=True (Bug 3 producer filter at mirror.py:130-133)."""
    payload = valid_validation_state_projection_dict()
    payload["failing_lever_margins"].append(
      valid_lever_margin_entry_dict(outside_band=False),
    )
    with self.assertRaises(ContractViolation) as ctx:
      validate_amalgamated_validation_state_at_boundary(
        payload, side=SIDE_CONSUMER,
      )
    self.assertIn("outside_band", str(ctx.exception))


# ---------------------------------------------------------------------------
# Adjustment B end-to-end through the API handler catch pattern
# ---------------------------------------------------------------------------

class ApiCatchPatternEndToEndTest(unittest.TestCase):
  """Mirror of Contracts 3-6 ApiCatchPatternEndToEndTest. The 3
  gates are wired in production at mirror.py:329+ (Shape A
  producer), Mirror.to_dict (Shape A consumer), and
  responder.py:269+ (Shape D consumer). All ContractViolations
  propagate through the API handler's `except Exception as exc:`
  at intake_consult.py:7377."""

  def test_violation_is_subclass_of_exception(self) -> None:
    self.assertTrue(issubclass(ContractViolation, Exception))

  def test_violation_is_NOT_subclass_of_runtime_error(self) -> None:
    """Must skip the line-7298 RuntimeError catch so it lands
    in the line-7377 generic catch."""
    self.assertFalse(issubclass(ContractViolation, RuntimeError))

  def test_violation_str_used_by_api_log_carries_stage_and_field(self) -> None:
    """Mirrors intake_consult.py:7377 pattern."""
    payload = valid_mirror_dict()
    payload["plan_state"]["balance_sheet"] = {"x": 1}
    payload["plan_state"]["capex_rd"] = {"x": 2}
    try:
      validate_amalgamated_session_at_boundary(
        payload, side=SIDE_PRODUCER,
      )
      self.fail("expected ContractViolation")
    except Exception as exc:  # exact pattern from line 7377
      log_line = str(exc).strip() or "system_run_failed"
      self.assertIn(AMALGAMATED_SESSION_STAGE_LABEL, log_line)
      self.assertNotEqual(log_line, "system_run_failed")


# ---------------------------------------------------------------------------
# Diagnostic emit is best-effort across both helpers
# ---------------------------------------------------------------------------

class DiagnosticEmitBestEffortTest(unittest.TestCase):

  def _broken_emitter(self, **_kwargs):
    raise RuntimeError("simulated diagnostic emission failure")

  def test_mirror_helper_succeeds_when_emit_raises(self) -> None:
    contract = validate_amalgamated_session_at_boundary(
      valid_mirror_dict(),
      side=SIDE_PRODUCER,
      emit_diagnostic_fn=self._broken_emitter,
    )
    self.assertIsInstance(contract, MirrorContract)

  def test_validation_state_helper_succeeds_when_emit_raises(self) -> None:
    contract = validate_amalgamated_validation_state_at_boundary(
      valid_validation_state_projection_dict(),
      side=SIDE_CONSUMER,
      emit_diagnostic_fn=self._broken_emitter,
    )
    self.assertIsInstance(contract, ValidationStateProjectionContract)


# ---------------------------------------------------------------------------
# F0 + F12: per-shape diagnostic_data partition under single PhaseCode
# ---------------------------------------------------------------------------

class _CapturingEmitter:
  def __init__(self):
    self.calls = []

  def __call__(self, **kwargs):
    self.calls.append(kwargs)


class ShapeDistinguisherTest(unittest.TestCase):
  """F0 + F12: SINGLE PhaseCode AMALGAMATED_SESSION_CONTRACT
  covers both sub-contract gates; diagnostic_data['shape']
  partitions queries by sub-shape (mirror / validation_state)."""

  def test_mirror_gate_carries_shape_mirror(self) -> None:
    emitter = _CapturingEmitter()
    validate_amalgamated_session_at_boundary(
      valid_mirror_dict(),
      side=SIDE_PRODUCER, emit_diagnostic_fn=emitter,
    )
    self.assertEqual(len(emitter.calls), 1)
    self.assertEqual(emitter.calls[0]["diagnostic_data"]["shape"], "mirror")

  def test_validation_state_gate_carries_shape_validation_state(self) -> None:
    emitter = _CapturingEmitter()
    validate_amalgamated_validation_state_at_boundary(
      valid_validation_state_projection_dict(),
      side=SIDE_CONSUMER, emit_diagnostic_fn=emitter,
    )
    self.assertEqual(len(emitter.calls), 1)
    self.assertEqual(
      emitter.calls[0]["diagnostic_data"]["shape"], "validation_state",
    )


if __name__ == "__main__":
  unittest.main()
