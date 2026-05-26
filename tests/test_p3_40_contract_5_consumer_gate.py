"""Acceptance tests for Contract 5 Commit 3 consumer-side gate.

The gate is wired inside ``prepare_initial_grid_for_draft`` at
runner.py:189 (immediately before the 8 ``parse_json_dict(
draft.get(<column>))`` reads at lines 190-197). These tests
exercise ``validate_intake_draft_at_boundary`` directly with
representative valid + invalid payloads; the in-handler placement
itself is exercised through the import path + the existing
acceptance suite.

Spec: ``docs/architecture/p3_40_contract_5_intake_draft_spec.md`` section 6.

Coverage:
  - Gate accepts a valid 8-field bundle (returns parsed
    IntakeDraftContract instance).
  - Gate rejects representative missing-required-field cases.
  - Gate rejects unknown top-level fields per F6 extra='forbid'.
  - Flag 1 (a) fulfillment_json Optional pinned through the gate
    path -- absent and present both accepted.
  - Adjustment B end-to-end: ContractViolation propagates through
    the API handler's `except Exception as exc:` catch at
    intake_consult.py:7377 with stage tag + field path in
    str(exc). Mirrors Contracts 3 + 4 ApiCatchPatternEndToEndTest.
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
  INTAKE_DRAFT_STAGE_LABEL,
  SIDE_CONSUMER,
  validate_intake_draft_at_boundary,
)
from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (  # noqa: E402
  ContractViolation,
)
from client_intake_and_finmo.post_intake_contracts.intake_draft_contract import (  # noqa: E402
  IntakeDraftContract,
)
from _p3_40_contract_5_fixtures import (  # noqa: E402
  valid_intake_draft_dict,
)


# ---------------------------------------------------------------------------
# Gate accepts valid payload
# ---------------------------------------------------------------------------

class ValidPayloadAcceptedTest(unittest.TestCase):

  def test_valid_payload_returns_parsed_contract(self) -> None:
    payload = valid_intake_draft_dict()
    contract = validate_intake_draft_at_boundary(payload, side=SIDE_CONSUMER)
    self.assertIsInstance(contract, IntakeDraftContract)
    self.assertIsNotNone(contract.fulfillment_json)


# ---------------------------------------------------------------------------
# Gate rejects missing required fields with ContractViolation
# ---------------------------------------------------------------------------

class GateRejectsMissingRequiredFieldTest(unittest.TestCase):
  """Representative subset (4 of 7 required Tier-A fields). spec
  section 6 Commit 3 calls for 4 representative tests."""

  def _assert_violation_for_missing(self, field_name: str) -> ContractViolation:
    payload = valid_intake_draft_dict()
    del payload[field_name]
    with self.assertRaises(ContractViolation) as ctx:
      validate_intake_draft_at_boundary(payload, side=SIDE_CONSUMER)
    return ctx.exception

  def test_missing_operating_model_json_rejected(self) -> None:
    exc = self._assert_violation_for_missing("operating_model_json")
    self.assertEqual(exc.stage, INTAKE_DRAFT_STAGE_LABEL)
    self.assertIn("operating_model_json", exc.field)

  def test_missing_financials_json_rejected(self) -> None:
    exc = self._assert_violation_for_missing("financials_json")
    self.assertEqual(exc.stage, INTAKE_DRAFT_STAGE_LABEL)
    self.assertIn("financials_json", exc.field)

  def test_missing_marketing_model_json_rejected(self) -> None:
    exc = self._assert_violation_for_missing("marketing_model_json")
    self.assertEqual(exc.stage, INTAKE_DRAFT_STAGE_LABEL)
    self.assertIn("marketing_model_json", exc.field)

  def test_missing_planning_context_summary_json_rejected(self) -> None:
    exc = self._assert_violation_for_missing("planning_context_summary_json")
    self.assertEqual(exc.stage, INTAKE_DRAFT_STAGE_LABEL)
    self.assertIn("planning_context_summary_json", exc.field)


# ---------------------------------------------------------------------------
# F6 extra='forbid' rejection through the gate
# ---------------------------------------------------------------------------

class GateRejectsUnknownTopLevelFieldTest(unittest.TestCase):

  def test_unknown_field_rejected_through_gate(self) -> None:
    """F6 disposition pinned end-to-end through the gate.
    realism_memo_json is the headline F2 EXCLUDE case."""
    payload = valid_intake_draft_dict()
    payload["realism_memo_json"] = {"diagnostic": "blob"}
    with self.assertRaises(ContractViolation) as ctx:
      validate_intake_draft_at_boundary(payload, side=SIDE_CONSUMER)
    self.assertEqual(ctx.exception.stage, INTAKE_DRAFT_STAGE_LABEL)
    self.assertIn("realism_memo_json", ctx.exception.field)


# ---------------------------------------------------------------------------
# Flag 1 (a) fulfillment_json Optional pinned through the gate path
# ---------------------------------------------------------------------------

class FulfillmentJsonOptionalAtGateTest(unittest.TestCase):

  def test_fulfillment_json_absent_accepted_at_gate(self) -> None:
    """F1 (a) Optional pinned through the gate. Matches production
    reality: SQL column legitimately NULL when no fulfillment.*
    patch ever ran."""
    payload = valid_intake_draft_dict(include_fulfillment_json=False)
    contract = validate_intake_draft_at_boundary(payload, side=SIDE_CONSUMER)
    self.assertIsNone(contract.fulfillment_json)

  def test_fulfillment_json_present_accepted_at_gate(self) -> None:
    payload = valid_intake_draft_dict(include_fulfillment_json=True)
    contract = validate_intake_draft_at_boundary(payload, side=SIDE_CONSUMER)
    self.assertIsNotNone(contract.fulfillment_json)


# ---------------------------------------------------------------------------
# Adjustment B end-to-end through the API handler catch pattern
# ---------------------------------------------------------------------------

class ApiCatchPatternEndToEndTest(unittest.TestCase):
  """Mirror of Contracts 3 + 4 ApiCatchPatternEndToEndTest. The
  gate is wired INSIDE prepare_initial_grid_for_draft at runner.py:
  189; ContractViolation propagates through the API handler's
  `except Exception as exc:` (line 7377 region) -- ContractViolation
  is Exception subclass not RuntimeError, so it skips the line-
  7298 branch."""

  def test_violation_is_subclass_of_exception(self) -> None:
    self.assertTrue(issubclass(ContractViolation, Exception))

  def test_violation_is_NOT_subclass_of_runtime_error(self) -> None:
    """Critical: ContractViolation must skip the line-7298
    RuntimeError catch so it lands in the line-7377 generic
    catch. If ContractViolation becomes a RuntimeError subclass,
    the detail format diverges silently."""
    self.assertFalse(issubclass(ContractViolation, RuntimeError))

  def test_violation_str_used_by_api_log_carries_stage_and_field(self) -> None:
    """Mirrors intake_consult.py:7377 pattern -- str(exc) is logged
    via app.logger.exception + persisted via
    _persist_failed_system_run_snapshot(detail=str(exc))."""
    payload = valid_intake_draft_dict()
    del payload["financials_json"]
    try:
      validate_intake_draft_at_boundary(payload, side=SIDE_CONSUMER)
      self.fail("expected ContractViolation")
    except Exception as exc:  # exact pattern from line 7377
      log_line = str(exc).strip() or "system_run_failed"
      self.assertIn(INTAKE_DRAFT_STAGE_LABEL, log_line)
      self.assertIn("financials_json", log_line)
      self.assertNotEqual(log_line, "system_run_failed")


# ---------------------------------------------------------------------------
# Diagnostic emit is best-effort
# ---------------------------------------------------------------------------

class DiagnosticEmitBestEffortTest(unittest.TestCase):

  def test_valid_payload_succeeds_when_emit_callback_raises(self) -> None:
    """Observability must never break the gate."""
    def _broken_emitter(**_kwargs):
      raise RuntimeError("simulated diagnostic emission failure")
    payload = valid_intake_draft_dict()
    contract = validate_intake_draft_at_boundary(
      payload, side=SIDE_CONSUMER, emit_diagnostic_fn=_broken_emitter,
    )
    self.assertIsInstance(contract, IntakeDraftContract)

  def test_violation_path_succeeds_when_emit_callback_raises(self) -> None:
    def _broken_emitter(**_kwargs):
      raise RuntimeError("simulated diagnostic emission failure")
    payload = valid_intake_draft_dict()
    del payload["financials_json"]
    with self.assertRaises(ContractViolation):
      validate_intake_draft_at_boundary(
        payload, side=SIDE_CONSUMER, emit_diagnostic_fn=_broken_emitter,
      )


if __name__ == "__main__":
  unittest.main()
