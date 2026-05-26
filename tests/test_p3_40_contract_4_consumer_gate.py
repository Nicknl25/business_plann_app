"""Acceptance tests for Contract 4 Commit 3 consumer-side gate.

The gate is wired at intake_consult.py:7276 (immediately after
`result = _run_planning_system_for_draft(...)`). These tests
exercise ``validate_solver_output_at_boundary`` directly with
representative valid + invalid payloads; the in-handler placement
itself is exercised through the import path + the existing
acceptance suite.

Spec: ``docs/architecture/p3_40_contract_4_solver_output_spec.md`` §6.

Coverage:
  - Gate accepts a valid 20-field bundle (returns parsed
    SolverOutputContract instance).
  - Gate rejects representative missing-required-field cases.
  - Gate rejects structurally-invalid sub-payloads with field path
    pointing into the violation location.
  - Cross-field invariant 4.3 fires through the gate.
  - Adjustment B end-to-end: ContractViolation propagates through
    the API handler's `except Exception as exc:` catch at
    intake_consult.py:7377 with stage tag + field path in
    str(exc). Mirrors Contract 3's ApiCatchPatternEndToEndTest.
  - Diagnostic emit best-effort: gate succeeds even when the
    emit_diagnostic_fn raises.
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
  SIDE_CONSUMER,
  SOLVER_OUTPUT_STAGE_LABEL,
  validate_solver_output_at_boundary,
)
from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (  # noqa: E402
  ContractViolation,
)
from client_intake_and_finmo.post_intake_contracts.solver_output_contract import (  # noqa: E402
  SolverOutputContract,
)
from _p3_40_contract_4_fixtures import (  # noqa: E402
  valid_solver_output_dict,
)


# ---------------------------------------------------------------------------
# Gate accepts valid payload
# ---------------------------------------------------------------------------

class ValidPayloadAcceptedTest(unittest.TestCase):

  def test_valid_payload_returns_parsed_contract(self) -> None:
    payload = valid_solver_output_dict()
    contract = validate_solver_output_at_boundary(payload, side=SIDE_CONSUMER)
    self.assertIsInstance(contract, SolverOutputContract)
    self.assertEqual(contract.plan_confidence, "high_no_adaptation")


# ---------------------------------------------------------------------------
# Gate rejects missing required fields with ContractViolation
# ---------------------------------------------------------------------------

class GateRejectsMissingRequiredFieldTest(unittest.TestCase):
  """Representative subset (4 of 5 required fields). spec section 6
  Commit 3 calls for 4 representative tests."""

  def _assert_violation_for_missing(self, field_name: str) -> ContractViolation:
    payload = valid_solver_output_dict()
    del payload[field_name]
    with self.assertRaises(ContractViolation) as ctx:
      validate_solver_output_at_boundary(payload, side=SIDE_CONSUMER)
    return ctx.exception

  def test_missing_model_input_json_rejected(self) -> None:
    exc = self._assert_violation_for_missing("model_input_json")
    self.assertEqual(exc.stage, SOLVER_OUTPUT_STAGE_LABEL)
    self.assertIn("model_input_json", exc.field)

  def test_missing_finmo_json_rejected(self) -> None:
    exc = self._assert_violation_for_missing("finmo_json")
    self.assertEqual(exc.stage, SOLVER_OUTPUT_STAGE_LABEL)
    self.assertIn("finmo_json", exc.field)

  def test_missing_plan_confidence_rejected(self) -> None:
    exc = self._assert_violation_for_missing("plan_confidence")
    self.assertEqual(exc.stage, SOLVER_OUTPUT_STAGE_LABEL)
    self.assertIn("plan_confidence", exc.field)

  def test_missing_target_seeking_diagnostics_rejected(self) -> None:
    exc = self._assert_violation_for_missing("target_seeking_diagnostics")
    self.assertEqual(exc.stage, SOLVER_OUTPUT_STAGE_LABEL)
    self.assertIn("target_seeking_diagnostics", exc.field)


# ---------------------------------------------------------------------------
# Gate rejects bad sub-payloads with field path pointing inside
# ---------------------------------------------------------------------------

class GateRejectsBadSubPayloadTest(unittest.TestCase):

  def test_bad_model_input_revenue_empty_rejected(self) -> None:
    """Contract 1 sections.revenue requires min_length=1. Wiping
    it surfaces here with field path pointing into the violation
    location."""
    payload = valid_solver_output_dict()
    payload["model_input_json"]["sections"]["revenue"] = []
    with self.assertRaises(ContractViolation) as ctx:
      validate_solver_output_at_boundary(payload, side=SIDE_CONSUMER)
    self.assertEqual(ctx.exception.stage, SOLVER_OUTPUT_STAGE_LABEL)
    self.assertIn("model_input_json", ctx.exception.field)
    self.assertIn("revenue", ctx.exception.field)

  def test_bad_capital_lease_schedule_envelope_rejected(self) -> None:
    """Flag 5 override sub-contract surfaces invariant failures
    through the gate."""
    payload = valid_solver_output_dict()
    payload["capital_lease_schedule"]["contract_version"] = "post_intake_capital_lease_schedule_v2"
    with self.assertRaises(ContractViolation) as ctx:
      validate_solver_output_at_boundary(payload, side=SIDE_CONSUMER)
    self.assertEqual(ctx.exception.stage, SOLVER_OUTPUT_STAGE_LABEL)
    self.assertIn("capital_lease_schedule", ctx.exception.field)


# ---------------------------------------------------------------------------
# Cross-field invariant 4.3 enforcement through the gate
# ---------------------------------------------------------------------------

class CrossFieldInvariantThroughGateTest(unittest.TestCase):
  """Invariant 4.3 (plan_confidence_matches_cascade_presence) per
  Flag 4(c) ADD. Confirm the cross-field check fires through the
  gate (not just at SolverOutputContract.model_validate)."""

  def test_cascade_fired_with_high_no_adaptation_rejected_at_gate(self) -> None:
    payload = valid_solver_output_dict(cascade_fired=True)
    payload["plan_confidence"] = "high_no_adaptation"
    with self.assertRaises(ContractViolation) as ctx:
      validate_solver_output_at_boundary(payload, side=SIDE_CONSUMER)
    self.assertEqual(ctx.exception.stage, SOLVER_OUTPUT_STAGE_LABEL)


# ---------------------------------------------------------------------------
# Adjustment B end-to-end through the API handler catch pattern
# ---------------------------------------------------------------------------

class ApiCatchPatternEndToEndTest(unittest.TestCase):
  """Mirror of Contract 3 ApiCatchPatternEndToEndTest. The gate is
  wired INSIDE intake_consult.py's inner try block at
  intake_consult.py:7276+ so ContractViolation lands in the
  `except Exception as exc:` branch (line 7377 region). Per trace
  Div-6 the handler logs `str(exc)` via `app.logger.exception`
  and persists via `_persist_failed_system_run_snapshot`. The
  str(ContractViolation) format carries SOLVER_OUTPUT_STAGE_LABEL
  + field path."""

  def test_violation_is_subclass_of_exception(self) -> None:
    self.assertTrue(issubclass(ContractViolation, Exception))

  def test_violation_is_NOT_subclass_of_runtime_error(self) -> None:
    """Critical: must skip the line-7298 RuntimeError catch so it
    lands in the line-7377 generic catch. If ContractViolation
    becomes a RuntimeError subclass, the detail format diverges
    silently."""
    self.assertFalse(issubclass(ContractViolation, RuntimeError))

  def test_violation_str_used_by_api_log_carries_stage_and_field(self) -> None:
    """Mirrors intake_consult.py:7377 pattern -- str(exc) is logged
    via app.logger.exception + persisted via
    _persist_failed_system_run_snapshot(detail=str(exc))."""
    payload = valid_solver_output_dict()
    del payload["model_input_json"]
    try:
      validate_solver_output_at_boundary(payload, side=SIDE_CONSUMER)
      self.fail("expected ContractViolation")
    except Exception as exc:  # exact pattern from line 7377
      log_line = str(exc).strip() or "system_run_failed"
      self.assertIn(SOLVER_OUTPUT_STAGE_LABEL, log_line)
      self.assertIn("model_input_json", log_line)
      self.assertNotEqual(log_line, "system_run_failed")


# ---------------------------------------------------------------------------
# Diagnostic emit is best-effort
# ---------------------------------------------------------------------------

class DiagnosticEmitBestEffortTest(unittest.TestCase):

  def test_valid_payload_succeeds_when_emit_callback_raises(self) -> None:
    """Observability must never break the gate."""
    def _broken_emitter(**_kwargs):
      raise RuntimeError("simulated diagnostic emission failure")
    payload = valid_solver_output_dict()
    contract = validate_solver_output_at_boundary(
      payload, side=SIDE_CONSUMER, emit_diagnostic_fn=_broken_emitter,
    )
    self.assertIsInstance(contract, SolverOutputContract)

  def test_violation_path_succeeds_when_emit_callback_raises(self) -> None:
    def _broken_emitter(**_kwargs):
      raise RuntimeError("simulated diagnostic emission failure")
    payload = valid_solver_output_dict()
    del payload["model_input_json"]
    with self.assertRaises(ContractViolation):
      validate_solver_output_at_boundary(
        payload, side=SIDE_CONSUMER, emit_diagnostic_fn=_broken_emitter,
      )


if __name__ == "__main__":
  unittest.main()
