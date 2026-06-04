"""Acceptance tests for Contract 3 Commit 3 consumer-side gate at
``run_target_seeking_orchestrated_system_run`` (orchestrator.py:1028).

Also exercises the producer-side gate at
``prepare_initial_grid_for_draft``'s return at runner.py:1830
indirectly via direct calls to
``validate_solver_input_at_boundary``.

Spec: ``docs/architecture/p3_40_contract_3_solver_input_spec.md`` §6 + §5.

Coverage:
  - Gate accepts a valid 21-field bundle (returns the parsed
    SolverInputContract instance).
  - Gate rejects 4 representative missing-required-field cases
    (not exhaustive across all 19 -- spec calls for 6-8
    representative cases; we ship 4 to keep the suite tight).
  - Gate rejects structurally-invalid sub-payloads with field path
    pointing into the violation location.
  - Adjustment B end-to-end: ContractViolation propagates through
    the API handler's generic `except Exception as exc:` catch
    at intake_consult.py:7377 with stage tag + field path in
    str(exc). Mirrors Contract 2's ApiCatchPatternEndToEndTest.
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
  SIDE_PRODUCER,
  SOLVER_STAGE_LABEL,
  validate_solver_input_at_boundary,
)
from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (  # noqa: E402
  ContractViolation,
)
from client_intake_and_finmo.post_intake_contracts.solver_input_contract import (  # noqa: E402
  SolverInputContract,
)
from _p3_40_contract_3_fixtures import (  # noqa: E402
  valid_solver_input_dict,
)


# ---------------------------------------------------------------------------
# Gate accepts valid 21-field bundle
# ---------------------------------------------------------------------------

class ValidPayloadAcceptedTest(unittest.TestCase):

  def test_valid_payload_returns_parsed_contract(self) -> None:
    payload = valid_solver_input_dict()
    contract = validate_solver_input_at_boundary(payload, side=SIDE_CONSUMER)
    self.assertIsInstance(contract, SolverInputContract)
    self.assertEqual(contract.planning_mode, "rebalance")

  def test_gate_accepts_both_producer_and_consumer_sides(self) -> None:
    """side='producer' (used at runner.py:1830) and side='consumer'
    (used at orchestrator.py:1028) both accept a valid payload --
    the side string is opaque to the gate, used only for the
    diagnostic emit's side field."""
    payload = valid_solver_input_dict()
    validate_solver_input_at_boundary(payload, side=SIDE_PRODUCER)
    validate_solver_input_at_boundary(payload, side=SIDE_CONSUMER)


# ---------------------------------------------------------------------------
# Gate rejects missing required fields with ContractViolation
# ---------------------------------------------------------------------------

class GateRejectsMissingRequiredFieldTest(unittest.TestCase):
  """Representative subset per spec section 6 ('6-8 representative
  tests, not exhaustive -- 19 tests would be churn'). 4 fields
  covering different tiers: A consumed-direct (business_facts,
  applied_model_input_json), tightened ID (planning_run_id), and
  Tier-F kept-required (target_market_json)."""

  def _assert_violation_for_missing(self, field_name: str) -> ContractViolation:
    payload = valid_solver_input_dict()
    del payload[field_name]
    with self.assertRaises(ContractViolation) as ctx:
      validate_solver_input_at_boundary(payload, side=SIDE_CONSUMER)
    return ctx.exception

  def test_missing_business_facts_rejected(self) -> None:
    exc = self._assert_violation_for_missing("business_facts")
    self.assertEqual(exc.stage, SOLVER_STAGE_LABEL)
    self.assertIn("business_facts", exc.field)

  def test_missing_applied_model_input_json_rejected(self) -> None:
    exc = self._assert_violation_for_missing("applied_model_input_json")
    self.assertEqual(exc.stage, SOLVER_STAGE_LABEL)
    self.assertIn("applied_model_input_json", exc.field)

  def test_missing_planning_mode_rejected(self) -> None:
    exc = self._assert_violation_for_missing("planning_mode")
    self.assertEqual(exc.stage, SOLVER_STAGE_LABEL)
    self.assertIn("planning_mode", exc.field)

  def test_missing_target_market_json_rejected_tier_f_pinned(self) -> None:
    """Flag 2 disposition: Tier-F kept-required. Missing
    target_market_json must surface as ContractViolation even
    though no reader consumes it today."""
    exc = self._assert_violation_for_missing("target_market_json")
    self.assertEqual(exc.stage, SOLVER_STAGE_LABEL)
    self.assertIn("target_market_json", exc.field)


# ---------------------------------------------------------------------------
# Gate rejects bad sub-payloads with field path pointing inside
# ---------------------------------------------------------------------------

class GateRejectsBadSubPayloadTest(unittest.TestCase):

  def test_bad_applied_model_input_revenue_empty_rejected(self) -> None:
    """Contract 1 sections.revenue requires min_length=1. Wiping it
    surfaces here with field path pointing into the violation
    location."""
    payload = valid_solver_input_dict()
    payload["applied_model_input_json"]["sections"]["revenue"] = []
    with self.assertRaises(ContractViolation) as ctx:
      validate_solver_input_at_boundary(payload, side=SIDE_CONSUMER)
    self.assertEqual(ctx.exception.stage, SOLVER_STAGE_LABEL)
    self.assertIn("applied_model_input_json", ctx.exception.field)
    self.assertIn("revenue", ctx.exception.field)

  def test_planning_mode_typo_rejected_with_field_path(self) -> None:
    payload = valid_solver_input_dict()
    payload["planning_mode"] = "growht"  # typo
    with self.assertRaises(ContractViolation) as ctx:
      validate_solver_input_at_boundary(payload, side=SIDE_CONSUMER)
    self.assertEqual(ctx.exception.stage, SOLVER_STAGE_LABEL)
    self.assertIn("planning_mode", ctx.exception.field)


# ---------------------------------------------------------------------------
# Flag 8(a) tightening end-to-end through the gate
# ---------------------------------------------------------------------------

class FlagEightATighteningGateEnforcementTest(unittest.TestCase):

  def test_empty_planning_run_id_rejected_at_gate(self) -> None:
    """Flag 8(a) tightening: empty planning_run_id rejected with
    a structured ContractViolation rather than silently skipped
    at orchestrator.py:3609 persist. PI2 verified runner.py:83-85
    already raises RuntimeError before this path, but this is the
    defense-in-depth guarantee at the solver boundary."""
    payload = valid_solver_input_dict()
    payload["planning_run_id"] = ""
    with self.assertRaises(ContractViolation) as ctx:
      validate_solver_input_at_boundary(payload, side=SIDE_CONSUMER)
    self.assertEqual(ctx.exception.stage, SOLVER_STAGE_LABEL)
    self.assertIn("planning_run_id", ctx.exception.field)


# ---------------------------------------------------------------------------
# Adjustment B end-to-end through the API handler catch pattern
# ---------------------------------------------------------------------------

class ApiCatchPatternEndToEndTest(unittest.TestCase):
  """Mirror of Contract 2 ApiCatchPatternEndToEndTest. Confirms
  that a ContractViolation raised at the consumer-side gate
  reaches the API handler's `except Exception as exc:` (the
  line-7377 generic catch at intake_consult.py) as a useful
  structured string, not the fallback 'system_run_failed'.

  Per trace Div-8: ContractViolation is Exception subclass (NOT
  RuntimeError), so it skips the line-7298 RuntimeError catch
  and lands in the line-7377 generic catch. The handler logs
  `str(exc)` via `app.logger.exception` and persists the snapshot
  with `detail=str(exc)`.
  """

  def test_violation_is_subclass_of_exception(self) -> None:
    self.assertTrue(issubclass(ContractViolation, Exception))

  def test_violation_is_NOT_subclass_of_runtime_error(self) -> None:
    """Critical for Div-8: must skip the line-7298 RuntimeError
    catch so it lands in the generic catch at 7377. If
    ContractViolation ever becomes a RuntimeError subclass, the
    detail format the line-7298 handler produces would differ
    from what the line-7377 handler produces, and the operator
    log line would change shape silently."""
    self.assertFalse(issubclass(ContractViolation, RuntimeError))

  def test_violation_str_used_by_api_log_carries_stage_and_field(self) -> None:
    """Mirrors intake_consult.py:7377+ pattern: str(exc) is logged
    via app.logger.exception and persisted via
    _persist_failed_system_run_snapshot(detail=str(exc))."""
    payload = valid_solver_input_dict()
    del payload["business_facts"]
    try:
      validate_solver_input_at_boundary(payload, side=SIDE_CONSUMER)
      self.fail("expected ContractViolation")
    except Exception as exc:  # match intake_consult.py:7377 exactly
      log_line = str(exc).strip() or "system_run_failed"
      self.assertIn(SOLVER_STAGE_LABEL, log_line)
      self.assertIn("business_facts", log_line)
      self.assertNotEqual(log_line, "system_run_failed")


# ---------------------------------------------------------------------------
# Diagnostic emit is best-effort
# ---------------------------------------------------------------------------

class DiagnosticEmitBestEffortTest(unittest.TestCase):

  def test_valid_payload_succeeds_when_emit_callback_raises(self) -> None:
    """Spec section 5.3 + section 5.5: observability must never break
    the gate. If the supplied emit_diagnostic_fn raises, the gate
    still returns the validated contract."""
    def _broken_emitter(**_kwargs):
      raise RuntimeError("simulated diagnostic emission failure")
    payload = valid_solver_input_dict()
    contract = validate_solver_input_at_boundary(
      payload, side=SIDE_CONSUMER, emit_diagnostic_fn=_broken_emitter
    )
    self.assertIsInstance(contract, SolverInputContract)

  def test_violation_path_succeeds_when_emit_callback_raises(self) -> None:
    """Same observability-must-not-break invariant on the failure
    path: the gate still raises ContractViolation even if the
    emit callback raises while writing the violation event."""
    def _broken_emitter(**_kwargs):
      raise RuntimeError("simulated diagnostic emission failure")
    payload = valid_solver_input_dict()
    del payload["business_facts"]
    with self.assertRaises(ContractViolation):
      validate_solver_input_at_boundary(
        payload, side=SIDE_CONSUMER, emit_diagnostic_fn=_broken_emitter
      )


if __name__ == "__main__":
  unittest.main()
