"""Per-sub-contract acceptance tests for Contract 4
(SolverOutputContract).

Spec: ``docs/architecture/p3_40_contract_4_solver_output_spec.md``
§6 Commit 1b. Top-level + cross-field tests land in
``test_p3_40_contract_4_solver_output.py`` (Commit 1c).
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)
if HERE not in sys.path:
  sys.path.insert(0, HERE)


from pydantic import ValidationError  # noqa: E402

from client_intake_and_finmo.post_intake_contracts.solver_output_contract import (  # noqa: E402
  CapitalLeaseScheduleContract,
  CapitalLeaseScheduleRow,
  SUPPORTED_PLAN_CONFIDENCE_VALUES,
  SolverOutputContract,
)
from _p3_40_contract_4_fixtures import (  # noqa: E402
  valid_capital_lease_schedule_dict,
  valid_capital_lease_schedule_row,
  valid_solver_output_dict,
)


# ---------------------------------------------------------------------------
# CapitalLeaseScheduleRow (Flag 5 override)
# ---------------------------------------------------------------------------

class CapitalLeaseScheduleRowTest(unittest.TestCase):

  def test_valid_row_accepted(self) -> None:
    row = CapitalLeaseScheduleRow.model_validate(
      valid_capital_lease_schedule_row()
    )
    self.assertEqual(row.quarter_index, 1)
    self.assertEqual(row.opening_balance, 100000.0)

  def test_missing_finmo_formula_rejected(self) -> None:
    payload = valid_capital_lease_schedule_row()
    del payload["finmo_formula"]
    with self.assertRaises(ValidationError) as ctx:
      CapitalLeaseScheduleRow.model_validate(payload)
    self.assertIn("finmo_formula", str(ctx.exception))

  def test_numeric_fields_accept_int_and_float(self) -> None:
    """Contract 2 1a-fix lesson: numeric fields type as float;
    pydantic v2 coerces int -> float silently. Both must work."""
    payload = valid_capital_lease_schedule_row()
    payload["opening_balance"] = 100000  # int
    payload["principal_payment"] = 5000.5  # float
    row = CapitalLeaseScheduleRow.model_validate(payload)
    self.assertEqual(row.opening_balance, 100000.0)
    self.assertEqual(row.principal_payment, 5000.5)

  def test_quarter_index_bounds_enforced(self) -> None:
    payload = valid_capital_lease_schedule_row()
    payload["quarter_index"] = 21  # le=20
    with self.assertRaises(ValidationError):
      CapitalLeaseScheduleRow.model_validate(payload)
    payload["quarter_index"] = 0  # ge=1
    with self.assertRaises(ValidationError):
      CapitalLeaseScheduleRow.model_validate(payload)

  def test_extra_key_ignored_per_flag_6(self) -> None:
    payload = valid_capital_lease_schedule_row()
    payload["unmodeled_writer_field"] = 42
    row = CapitalLeaseScheduleRow.model_validate(payload)
    self.assertFalse(hasattr(row, "unmodeled_writer_field"))


# ---------------------------------------------------------------------------
# CapitalLeaseScheduleContract envelope (Flag 5 override)
# ---------------------------------------------------------------------------

class CapitalLeaseScheduleContractTest(unittest.TestCase):

  def test_valid_envelope_accepted(self) -> None:
    contract = CapitalLeaseScheduleContract.model_validate(
      valid_capital_lease_schedule_dict()
    )
    self.assertEqual(
      contract.contract_version, "post_intake_capital_lease_schedule_v1"
    )
    self.assertEqual(len(contract.rows), 20)

  def test_wrong_contract_version_rejected(self) -> None:
    payload = valid_capital_lease_schedule_dict()
    payload["contract_version"] = "post_intake_capital_lease_schedule_v2"
    with self.assertRaises(ValidationError) as ctx:
      CapitalLeaseScheduleContract.model_validate(payload)
    self.assertIn("contract_version", str(ctx.exception))

  def test_wrong_schedule_role_rejected(self) -> None:
    payload = valid_capital_lease_schedule_dict()
    payload["schedule_role"] = "draft_capital_lease_schedule"
    with self.assertRaises(ValidationError) as ctx:
      CapitalLeaseScheduleContract.model_validate(payload)
    self.assertIn("schedule_role", str(ctx.exception))

  def test_wrong_schedule_method_rejected(self) -> None:
    payload = valid_capital_lease_schedule_dict()
    payload["schedule_method"] = "double_declining"
    with self.assertRaises(ValidationError) as ctx:
      CapitalLeaseScheduleContract.model_validate(payload)
    self.assertIn("schedule_method", str(ctx.exception))

  def test_missing_rows_rejected(self) -> None:
    payload = valid_capital_lease_schedule_dict()
    del payload["rows"]
    with self.assertRaises(ValidationError) as ctx:
      CapitalLeaseScheduleContract.model_validate(payload)
    self.assertIn("rows", str(ctx.exception))

  def test_extra_envelope_key_ignored(self) -> None:
    payload = valid_capital_lease_schedule_dict()
    payload["unmodeled_envelope_field"] = "anything"
    contract = CapitalLeaseScheduleContract.model_validate(payload)
    self.assertFalse(hasattr(contract, "unmodeled_envelope_field"))


# ---------------------------------------------------------------------------
# plan_confidence Literal -- 11-value typo-lock pair (PSL5 / Flag 4(a))
# ---------------------------------------------------------------------------

class PlanConfidenceLiteralTest(unittest.TestCase):

  def test_supported_constant_matches_literal_set(self) -> None:
    """SUPPORTED_PLAN_CONFIDENCE_VALUES must enumerate exactly the
    11 values the Literal accepts. Drift between the two would
    desync the documentation tuple from the actual contract; this
    test pins both halves."""
    self.assertEqual(len(SUPPORTED_PLAN_CONFIDENCE_VALUES), 11)
    for value in SUPPORTED_PLAN_CONFIDENCE_VALUES:
      payload = valid_solver_output_dict()
      # cascade_fired False -> plan_confidence is high_no_adaptation
      # by default. Set to each Literal value and verify accepted IF
      # consistent with invariant 4.3.
      payload["plan_confidence"] = value
      # For values that are not high_no_adaptation OR terminal_cause_7,
      # invariant 4.3 requires cascade_diagnostics to be present.
      if value not in ("high_no_adaptation", "terminal_cause_7"):
        payload["adaptation_cascade_diagnostics"] = {"tier_landed": 3}
      SolverOutputContract.model_validate(payload)

  def test_typo_rejected(self) -> None:
    """Contract 1 typo-lock pattern: misspelling fails the Literal
    field-level check."""
    payload = valid_solver_output_dict()
    payload["plan_confidence"] = "high_no_adaption"  # typo
    with self.assertRaises(ValidationError) as ctx:
      SolverOutputContract.model_validate(payload)
    self.assertIn("plan_confidence", str(ctx.exception))


# ---------------------------------------------------------------------------
# Tier-D phantom-read fields per PSL2 (a) / Flag 3
# ---------------------------------------------------------------------------

class PhantomReadFieldsOptionalTest(unittest.TestCase):
  """PSL2 (a): the 5 phantom-read fields type as Optional and may
  be present OR absent. Pinned here so a future contract
  tightening to required does not slip through silently."""

  def test_all_five_phantom_read_fields_optional_absent(self) -> None:
    payload = valid_solver_output_dict(include_phantom_reads=False)
    contract = SolverOutputContract.model_validate(payload)
    self.assertIsNone(contract.planning_run_json)
    self.assertIsNone(contract.numeric_solver_feedback_json)
    self.assertIsNone(contract.planning_runtime_json)
    self.assertIsNone(contract.planning_context_summary_json)
    self.assertIsNone(contract.draft_id)

  def test_all_five_phantom_read_fields_accept_when_present(self) -> None:
    payload = valid_solver_output_dict(include_phantom_reads=True)
    contract = SolverOutputContract.model_validate(payload)
    self.assertEqual(contract.planning_run_json, {})
    self.assertEqual(contract.numeric_solver_feedback_json, {})
    self.assertEqual(contract.planning_runtime_json, {})
    self.assertEqual(contract.planning_context_summary_json, {})
    self.assertEqual(contract.draft_id, "draft_test_001")


# ---------------------------------------------------------------------------
# Optional sub-contract fields can be absent (Tier A)
# ---------------------------------------------------------------------------

class OptionalSubContractFieldsTest(unittest.TestCase):

  def test_payroll_headcount_optional_absent(self) -> None:
    payload = valid_solver_output_dict(include_payroll_headcount=False)
    contract = SolverOutputContract.model_validate(payload)
    self.assertIsNone(contract.payroll_headcount)

  def test_debt_schedule_optional_absent(self) -> None:
    payload = valid_solver_output_dict(include_debt_schedule=False)
    contract = SolverOutputContract.model_validate(payload)
    self.assertIsNone(contract.debt_schedule)

  def test_capital_lease_schedule_optional_absent(self) -> None:
    """Flag 5 override: capital_lease_schedule typed via
    CapitalLeaseScheduleContract sub-contract but field itself
    is Optional[...] per orchestrator stamp at orchestrator.py:3166
    which lives inside a try/except."""
    payload = valid_solver_output_dict(include_capital_lease_schedule=False)
    contract = SolverOutputContract.model_validate(payload)
    self.assertIsNone(contract.capital_lease_schedule)

  def test_capital_lease_schedule_typed_when_present(self) -> None:
    payload = valid_solver_output_dict(include_capital_lease_schedule=True)
    contract = SolverOutputContract.model_validate(payload)
    self.assertIsInstance(
      contract.capital_lease_schedule, CapitalLeaseScheduleContract
    )
    self.assertEqual(len(contract.capital_lease_schedule.rows), 20)


# ---------------------------------------------------------------------------
# Tier-E status field (Phase-8 bypass artifact)
# ---------------------------------------------------------------------------

class Tier_E_StatusFieldTest(unittest.TestCase):

  def test_status_optional_absent(self) -> None:
    payload = valid_solver_output_dict()
    contract = SolverOutputContract.model_validate(payload)
    self.assertIsNone(contract.status)

  def test_status_accepts_phase_8_bypass_string(self) -> None:
    payload = valid_solver_output_dict()
    payload["status"] = "phase_8_inner_runner_bypassed"
    contract = SolverOutputContract.model_validate(payload)
    self.assertEqual(contract.status, "phase_8_inner_runner_bypassed")


if __name__ == "__main__":
  unittest.main()
