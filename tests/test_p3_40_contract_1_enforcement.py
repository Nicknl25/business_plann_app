"""Acceptance tests for the producer-side / consumer-side enforcement
helper added in Contract 1 Commit 3.

Spec: ``docs/architecture/p3_40_contract_1_finmo_model_input_spec.md`` §6.

Tests the helper itself in isolation (no production wiring) so the
gate semantics are covered without requiring a live draft + DB to
exercise the runner. The runtime wiring at
``post_intake_initial_grid/runner.py`` is verified via the existing
test suite (no Contract 1 regressions) and live runs after deploy.
"""

from __future__ import annotations

import math
import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)
if HERE not in sys.path:
  sys.path.insert(0, HERE)


from client_intake_and_finmo.post_intake_contracts.enforcement import (  # noqa: E402
  MODEL_INPUT_STAGE_LABEL,
  SIDE_CONSUMER,
  SIDE_PRODUCER,
  validate_model_input_at_boundary,
)
from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (  # noqa: E402
  ContractViolation,
  FinmoModelInputContract,
)
from client_intake_and_finmo.post_intake_diagnostics.phase_codes import (  # noqa: E402
  EventCode,
  PhaseCode,
  Status,
)
from _p3_40_contract_1_fixtures import (  # noqa: E402
  valid_balance_sheet_row,
  valid_revenue_row,
  valid_top_level,
)


class _Recorder:
  """Fake emit_diagnostic_fn that records each call."""

  def __init__(self) -> None:
    self.calls = []

  def __call__(self, **kwargs):
    self.calls.append(kwargs)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class ValidatePassTest(unittest.TestCase):

  def test_returns_validated_contract(self) -> None:
    result = validate_model_input_at_boundary(
      valid_top_level(), side=SIDE_PRODUCER,
    )
    self.assertIsInstance(result, FinmoModelInputContract)
    self.assertEqual(result.business_name, "Test Co")

  def test_emits_validated_event_with_producer_side(self) -> None:
    rec = _Recorder()
    validate_model_input_at_boundary(
      valid_top_level(), side=SIDE_PRODUCER, emit_diagnostic_fn=rec,
    )
    self.assertEqual(len(rec.calls), 1)
    call = rec.calls[0]
    self.assertEqual(call["phase"], PhaseCode.MODEL_INPUT_CONTRACT)
    self.assertEqual(call["event_code"], EventCode.MODEL_INPUT_CONTRACT_VALIDATED)
    self.assertEqual(call["status"], Status.COMPLETED)
    self.assertEqual(call["diagnostic_data"]["side"], SIDE_PRODUCER)
    self.assertEqual(call["diagnostic_data"]["stage"], MODEL_INPUT_STAGE_LABEL)
    # Row counts surfaced for observability
    self.assertEqual(call["diagnostic_data"]["revenue_row_count"], 3)
    self.assertEqual(call["diagnostic_data"]["expense_row_count"], 1)
    self.assertEqual(call["diagnostic_data"]["balance_sheet_row_count"], 3)
    self.assertEqual(call["diagnostic_data"]["schedule_row_count"], 0)

  def test_consumer_side_label_distinguished(self) -> None:
    rec = _Recorder()
    validate_model_input_at_boundary(
      valid_top_level(), side=SIDE_CONSUMER, emit_diagnostic_fn=rec,
    )
    self.assertEqual(rec.calls[0]["diagnostic_data"]["side"], SIDE_CONSUMER)

  def test_no_emitter_means_no_emit(self) -> None:
    # Should validate cleanly with no emitter supplied
    result = validate_model_input_at_boundary(
      valid_top_level(), side=SIDE_PRODUCER,
    )
    self.assertIsInstance(result, FinmoModelInputContract)


# ---------------------------------------------------------------------------
# Failure path — pydantic ValidationError -> ContractViolation
# ---------------------------------------------------------------------------

class ValidateFailureTest(unittest.TestCase):

  def test_missing_required_field_raises_contract_violation(self) -> None:
    bad = valid_top_level()
    del bad["business_name"]
    with self.assertRaises(ContractViolation) as ctx:
      validate_model_input_at_boundary(bad, side=SIDE_PRODUCER)
    exc = ctx.exception
    self.assertEqual(exc.stage, MODEL_INPUT_STAGE_LABEL)
    self.assertIn("business_name", exc.field)
    self.assertIs(exc.source_payload, bad)

  def test_wrong_contract_version_raises_with_field_path(self) -> None:
    bad = valid_top_level()
    bad["contract_version"] = "financial_model_inputs_v1"
    with self.assertRaises(ContractViolation) as ctx:
      validate_model_input_at_boundary(bad, side=SIDE_PRODUCER)
    self.assertIn("contract_version", ctx.exception.field)

  def test_nested_failure_carries_dotted_path(self) -> None:
    bad = valid_top_level()
    # Set NaN inside a revenue row's values; expect path like
    # sections.revenue.0.values.value_finite
    bad["sections"]["revenue"][0]["values"][3] = float("nan")
    with self.assertRaises(ContractViolation) as ctx:
      validate_model_input_at_boundary(bad, side=SIDE_PRODUCER)
    self.assertIn("sections", ctx.exception.field)
    self.assertIn("revenue", ctx.exception.field)
    self.assertIn("finite", ctx.exception.expected.lower())

  def test_emits_violation_event_before_raising(self) -> None:
    rec = _Recorder()
    bad = valid_top_level()
    del bad["sections"]
    with self.assertRaises(ContractViolation):
      validate_model_input_at_boundary(
        bad, side=SIDE_PRODUCER, emit_diagnostic_fn=rec,
      )
    self.assertEqual(len(rec.calls), 1)
    call = rec.calls[0]
    self.assertEqual(call["event_code"], EventCode.MODEL_INPUT_CONTRACT_VIOLATION)
    self.assertEqual(call["status"], Status.FAILED)
    self.assertEqual(call["diagnostic_data"]["side"], SIDE_PRODUCER)
    self.assertEqual(call["diagnostic_data"]["stage"], MODEL_INPUT_STAGE_LABEL)
    self.assertIn("field", call["diagnostic_data"])
    self.assertGreaterEqual(call["diagnostic_data"]["error_count"], 1)

  def test_emitter_failure_does_not_swallow_contract_violation(self) -> None:
    def broken_emitter(**kwargs):
      raise RuntimeError("emitter is down")
    bad = valid_top_level()
    del bad["business_name"]
    # ContractViolation should still propagate even though the emitter raised.
    with self.assertRaises(ContractViolation):
      validate_model_input_at_boundary(
        bad, side=SIDE_PRODUCER, emit_diagnostic_fn=broken_emitter,
      )

  def test_emitter_failure_does_not_block_success_path(self) -> None:
    def broken_emitter(**kwargs):
      raise RuntimeError("emitter is down")
    result = validate_model_input_at_boundary(
      valid_top_level(), side=SIDE_PRODUCER, emit_diagnostic_fn=broken_emitter,
    )
    self.assertIsInstance(result, FinmoModelInputContract)

  def test_cross_section_violation_routes_through_contract_violation(self) -> None:
    # WC days incomplete triple is a cross-section invariant
    bad = valid_top_level()
    bad["sections"]["balance_sheet"] = [
      valid_balance_sheet_row(label="Accounts Receivable Days"),
      valid_balance_sheet_row(label="Accounts Payable Days"),
      # missing "Inventory Days"
    ]
    with self.assertRaises(ContractViolation) as ctx:
      validate_model_input_at_boundary(bad, side=SIDE_PRODUCER)
    self.assertIn("working capital days rows incomplete", ctx.exception.expected.lower())

  def test_stage_label_is_correct(self) -> None:
    self.assertEqual(
      MODEL_INPUT_STAGE_LABEL, "AMALGAMATED_SESSION→MODEL_INPUT",
    )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class EnforcementEdgeCasesTest(unittest.TestCase):

  def test_actual_truncated_for_huge_input(self) -> None:
    # Generate a huge invalid value to confirm the actual field is
    # bounded (~200 chars + ellipsis), keeping error messages readable.
    bad = valid_top_level()
    bad["sections"]["revenue"][0]["values"][3] = float("inf")
    with self.assertRaises(ContractViolation) as ctx:
      validate_model_input_at_boundary(bad, side=SIDE_PRODUCER)
    self.assertLessEqual(len(ctx.exception.actual), 250)

  def test_custom_stage_override_respected(self) -> None:
    bad = valid_top_level()
    del bad["business_name"]
    with self.assertRaises(ContractViolation) as ctx:
      validate_model_input_at_boundary(
        bad, side=SIDE_PRODUCER, stage="MY_CUSTOM_STAGE",
      )
    self.assertEqual(ctx.exception.stage, "MY_CUSTOM_STAGE")


if __name__ == "__main__":
  unittest.main(verbosity=2)
