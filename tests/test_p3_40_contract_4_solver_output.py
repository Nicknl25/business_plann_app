"""Top-level + cross-field + Adjustment B acceptance tests for
Contract 4 (SolverOutputContract).

Spec: ``docs/architecture/p3_40_contract_4_solver_output_spec.md`` §6
Commit 1c.

Test classes mirror Contract 3's Commit 1c structure:
- SolverOutputContractTopLevelTest: required-field rejection +
  extra=forbid on top-level + all optional fields can be absent.
- CompositionWithContract1Test: model_input_json typed as
  FinmoModelInputContract; Contract 1 invariant violations
  propagate.
- CompositionWithContract2Test: finmo_json / payroll_headcount /
  debt_schedule typed via Contract 2 composition; Contract 2
  invariant violations propagate.
- CrossFieldInvariantTest: invariant 4.3
  (plan_confidence_matches_cascade_presence) -- both halves of
  each pair, per Flag 4(c) add.
- ApiBoundaryContractViolationTest: Adjustment B verification
  per Contract 3 pattern.
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
  SOLVER_OUTPUT_STAGE_LABEL,
  ContractViolation,
  DebtScheduleContract,
  FinmoModelInputContract,
  FinmoOutputContract,
  PayrollHeadcountContract,
  SolverOutputContract,
)
from _p3_40_contract_4_fixtures import (  # noqa: E402
  valid_solver_output_dict,
)


# ---------------------------------------------------------------------------
# SolverOutputContract -- top-level + extra=forbid
# ---------------------------------------------------------------------------

class SolverOutputContractTopLevelTest(unittest.TestCase):

  def test_valid_full_payload_accepted(self) -> None:
    contract = SolverOutputContract.model_validate(valid_solver_output_dict())
    self.assertEqual(contract.plan_confidence, "high_no_adaptation")
    self.assertIsInstance(contract.model_input_json, FinmoModelInputContract)

  def test_extra_top_level_field_forbidden(self) -> None:
    payload = valid_solver_output_dict()
    payload["unmodeled_solver_return_key"] = {"foo": "bar"}
    with self.assertRaises(ValidationError) as ctx:
      SolverOutputContract.model_validate(payload)
    self.assertIn("unmodeled_solver_return_key", str(ctx.exception))

  def test_missing_model_input_json_rejected(self) -> None:
    payload = valid_solver_output_dict()
    del payload["model_input_json"]
    with self.assertRaises(ValidationError) as ctx:
      SolverOutputContract.model_validate(payload)
    self.assertIn("model_input_json", str(ctx.exception))

  def test_missing_finmo_json_rejected(self) -> None:
    payload = valid_solver_output_dict()
    del payload["finmo_json"]
    with self.assertRaises(ValidationError) as ctx:
      SolverOutputContract.model_validate(payload)
    self.assertIn("finmo_json", str(ctx.exception))

  def test_missing_plan_confidence_rejected(self) -> None:
    payload = valid_solver_output_dict()
    del payload["plan_confidence"]
    with self.assertRaises(ValidationError) as ctx:
      SolverOutputContract.model_validate(payload)
    self.assertIn("plan_confidence", str(ctx.exception))

  def test_missing_target_seeking_diagnostics_rejected(self) -> None:
    payload = valid_solver_output_dict()
    del payload["target_seeking_diagnostics"]
    with self.assertRaises(ValidationError) as ctx:
      SolverOutputContract.model_validate(payload)
    self.assertIn("target_seeking_diagnostics", str(ctx.exception))

  def test_missing_adaptive_policy_rejected(self) -> None:
    payload = valid_solver_output_dict()
    del payload["adaptive_policy"]
    with self.assertRaises(ValidationError) as ctx:
      SolverOutputContract.model_validate(payload)
    self.assertIn("adaptive_policy", str(ctx.exception))

  def test_all_optional_sub_contracts_can_be_absent(self) -> None:
    """payroll_headcount, debt_schedule, capital_lease_schedule
    are all Optional per orchestrator stamp sites (each lives
    inside a conditional). Valid payload omits all three."""
    payload = valid_solver_output_dict(
      include_payroll_headcount=False,
      include_debt_schedule=False,
      include_capital_lease_schedule=False,
    )
    contract = SolverOutputContract.model_validate(payload)
    self.assertIsNone(contract.payroll_headcount)
    self.assertIsNone(contract.debt_schedule)
    self.assertIsNone(contract.capital_lease_schedule)


# ---------------------------------------------------------------------------
# Composition with Contract 1
# ---------------------------------------------------------------------------

class CompositionWithContract1Test(unittest.TestCase):

  def test_model_input_json_typed_as_finmo_model_input_contract(self) -> None:
    contract = SolverOutputContract.model_validate(valid_solver_output_dict())
    self.assertIsInstance(contract.model_input_json, FinmoModelInputContract)

  def test_contract_1_invariant_violation_propagates(self) -> None:
    """Contract 1 sections.revenue requires min_length=1. Wiping it
    in the model_input_json sub-payload surfaces as ValidationError
    at SolverOutputContract.model_validate."""
    payload = valid_solver_output_dict()
    payload["model_input_json"]["sections"]["revenue"] = []
    with self.assertRaises(ValidationError) as ctx:
      SolverOutputContract.model_validate(payload)
    self.assertIn("revenue", str(ctx.exception))


# ---------------------------------------------------------------------------
# Composition with Contract 2 (finmo_json + payroll_headcount + debt_schedule)
# ---------------------------------------------------------------------------

class CompositionWithContract2Test(unittest.TestCase):

  def test_finmo_json_typed_as_finmo_output_contract(self) -> None:
    contract = SolverOutputContract.model_validate(valid_solver_output_dict())
    self.assertIsInstance(contract.finmo_json, FinmoOutputContract)

  def test_payroll_headcount_typed_as_payroll_headcount_contract(self) -> None:
    contract = SolverOutputContract.model_validate(valid_solver_output_dict())
    self.assertIsInstance(contract.payroll_headcount, PayrollHeadcountContract)

  def test_debt_schedule_typed_as_debt_schedule_contract(self) -> None:
    contract = SolverOutputContract.model_validate(valid_solver_output_dict())
    self.assertIsInstance(contract.debt_schedule, DebtScheduleContract)

  def test_contract_2_finmo_invariant_violation_propagates(self) -> None:
    """Contract 2 FinmoOutputContract requires periods length == 21.
    Truncating it surfaces at SolverOutputContract.model_validate."""
    payload = valid_solver_output_dict()
    payload["finmo_json"]["periods"] = payload["finmo_json"]["periods"][:5]
    with self.assertRaises(ValidationError) as ctx:
      SolverOutputContract.model_validate(payload)
    self.assertIn("periods", str(ctx.exception))


# ---------------------------------------------------------------------------
# Cross-field invariant 4.3 -- plan_confidence_matches_cascade_presence
# ---------------------------------------------------------------------------

class CrossFieldInvariant43Test(unittest.TestCase):
  """Flag 4(c) ADD. Invariant 4.3:
    - cascade FIRED + plan_confidence=='high_no_adaptation' -> REJECT
    - cascade ABSENT + plan_confidence not in {high_no_adaptation,
      terminal_cause_7} -> REJECT
  Catches drift between the two fields co-stamped at
  orchestrator.py:1707 + :1709."""

  # --- cascade fired half ---

  def test_cascade_fired_with_high_no_adaptation_rejected(self) -> None:
    payload = valid_solver_output_dict(cascade_fired=True)
    payload["plan_confidence"] = "high_no_adaptation"  # contradicts cascade
    with self.assertRaises(ValidationError) as ctx:
      SolverOutputContract.model_validate(payload)
    self.assertIn("high_no_adaptation", str(ctx.exception))

  def test_cascade_fired_with_medium_confidence_accepted(self) -> None:
    payload = valid_solver_output_dict(cascade_fired=True)
    payload["plan_confidence"] = "medium_gpt_band_relaxation"
    SolverOutputContract.model_validate(payload)  # should not raise

  # --- cascade absent half ---

  def test_cascade_absent_with_high_no_adaptation_accepted(self) -> None:
    payload = valid_solver_output_dict(cascade_fired=False)
    payload["plan_confidence"] = "high_no_adaptation"
    SolverOutputContract.model_validate(payload)  # should not raise

  def test_cascade_absent_with_terminal_cause_7_accepted(self) -> None:
    payload = valid_solver_output_dict(cascade_fired=False)
    payload["plan_confidence"] = "terminal_cause_7"
    SolverOutputContract.model_validate(payload)  # should not raise

  def test_cascade_absent_with_other_confidence_rejected(self) -> None:
    """cascade=None but plan_confidence=low_target_tolerance_widened
    (a cascade-result value) means one of the two stamps drifted."""
    payload = valid_solver_output_dict(cascade_fired=False)
    payload["plan_confidence"] = "low_target_tolerance_widened"
    with self.assertRaises(ValidationError) as ctx:
      SolverOutputContract.model_validate(payload)
    self.assertIn("cascade did not fire", str(ctx.exception))


# ---------------------------------------------------------------------------
# Adjustment B -- API-boundary ContractViolation propagation
# ---------------------------------------------------------------------------

class ApiBoundaryContractViolationTest(unittest.TestCase):
  """Mirror of Contract 3's ApiBoundaryContractViolationTest. Per
  trace Div-6 the API handler at intake_consult.py:7377 catches
  `except Exception as exc:` and logs str(exc). ContractViolation
  is Exception subclass (not RuntimeError), so it skips the
  line-7298 catch and lands in the generic catch as a structured
  500 with detail=str(exc)."""

  def _violation(self) -> ContractViolation:
    return ContractViolation(
      stage=SOLVER_OUTPUT_STAGE_LABEL,
      field="adaptation_cascade_diagnostics",
      expected="present-when-cascade-fired",
      actual="None",
      source_payload={"redacted": "..."},
    )

  def test_violation_message_uses_solver_output_stage_label(self) -> None:
    exc = self._violation()
    self.assertIn(SOLVER_OUTPUT_STAGE_LABEL, str(exc))

  def test_violation_attributes_accessible_for_structured_handling(self) -> None:
    exc = self._violation()
    self.assertEqual(exc.stage, SOLVER_OUTPUT_STAGE_LABEL)
    self.assertEqual(exc.field, "adaptation_cascade_diagnostics")
    self.assertEqual(exc.expected, "present-when-cascade-fired")
    self.assertEqual(exc.actual, "None")
    self.assertIsInstance(exc.source_payload, dict)

  def test_violation_survives_generic_exception_catch(self) -> None:
    """Mirrors intake_consult.py:7377 catch pattern exactly."""
    try:
      raise self._violation()
    except Exception as exc:  # exact pattern from line 7377
      log_line = str(exc).strip() or "system_run_failed"
      self.assertIn(SOLVER_OUTPUT_STAGE_LABEL, log_line)
      self.assertIn("adaptation_cascade_diagnostics", log_line)
      self.assertNotEqual(log_line, "system_run_failed")

  def test_violation_str_does_not_dump_source_payload(self) -> None:
    exc = self._violation()
    log_str = str(exc)
    self.assertLess(len(log_str), 500)
    self.assertNotIn("redacted", log_str)


if __name__ == "__main__":
  unittest.main()
