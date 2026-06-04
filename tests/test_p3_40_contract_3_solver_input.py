"""Top-level + cross-field + Adjustment B acceptance tests for
Contract 3 (SolverInputContract).

Spec: ``docs/architecture/p3_40_contract_3_solver_input_spec.md`` §6
Commit 1c.

Test classes mirror Contract 2's Commit 1c structure:
- SolverInputContractTopLevelTest: required-field rejection +
  extra=forbid on top-level (Flag 7).
- CompositionWithContract1Test: applied_model_input_json /
  catalog_source_model_input_json typed as FinmoModelInputContract.
- CompositionWithContract2Test: applied_finmo_json typed as
  FinmoOutputContract; stage_ramp_contract / payroll_headcount
  typed via composition with Contract 2.
- CrossFieldInvariantTest: invariants 4.4 (planning_run_id presence,
  Flag 8(a)) + 4.5 (contract_versions_agree, Flag 8(b)).
- ApiBoundaryContractViolationTest: Adjustment B verification.
  Mirrors Contract 2's ApiBoundaryContractViolationTest.
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

from client_intake_and_finmo.post_intake_contracts.solver_input_contract import (  # noqa: E402
  SOLVER_STAGE_LABEL,
  ContractViolation,
  FinmoModelInputContract,
  FinmoOutputContract,
  PayrollHeadcountContract,
  SolverInputContract,
  StageRampContract,
)
from _p3_40_contract_3_fixtures import (  # noqa: E402
  valid_solver_input_dict,
)


# ---------------------------------------------------------------------------
# SolverInputContract — top-level shape + extra=forbid
# ---------------------------------------------------------------------------

class SolverInputContractTopLevelTest(unittest.TestCase):

  def test_valid_full_payload_accepted(self) -> None:
    contract = SolverInputContract.model_validate(valid_solver_input_dict())
    self.assertEqual(contract.draft_id, "draft_test_001")
    self.assertEqual(contract.planning_run_id, "run_test_001")
    self.assertEqual(contract.planning_mode, "rebalance")

  def test_extra_top_level_field_forbidden(self) -> None:
    """Flag 7: extra='forbid' on top-level SolverInputContract."""
    payload = valid_solver_input_dict()
    payload["unmodeled_orchestrator_param"] = {"foo": "bar"}
    with self.assertRaises(ValidationError) as ctx:
      SolverInputContract.model_validate(payload)
    self.assertIn("unmodeled_orchestrator_param", str(ctx.exception))

  def test_missing_draft_id_rejected(self) -> None:
    payload = valid_solver_input_dict()
    del payload["draft_id"]
    with self.assertRaises(ValidationError) as ctx:
      SolverInputContract.model_validate(payload)
    self.assertIn("draft_id", str(ctx.exception))

  def test_missing_business_facts_rejected(self) -> None:
    payload = valid_solver_input_dict()
    del payload["business_facts"]
    with self.assertRaises(ValidationError) as ctx:
      SolverInputContract.model_validate(payload)
    self.assertIn("business_facts", str(ctx.exception))

  def test_missing_applied_model_input_json_rejected(self) -> None:
    payload = valid_solver_input_dict()
    del payload["applied_model_input_json"]
    with self.assertRaises(ValidationError) as ctx:
      SolverInputContract.model_validate(payload)
    self.assertIn("applied_model_input_json", str(ctx.exception))

  def test_missing_applied_finmo_json_rejected(self) -> None:
    payload = valid_solver_input_dict()
    del payload["applied_finmo_json"]
    with self.assertRaises(ValidationError) as ctx:
      SolverInputContract.model_validate(payload)
    self.assertIn("applied_finmo_json", str(ctx.exception))

  def test_missing_planning_mode_rejected(self) -> None:
    payload = valid_solver_input_dict()
    del payload["planning_mode"]
    with self.assertRaises(ValidationError) as ctx:
      SolverInputContract.model_validate(payload)
    self.assertIn("planning_mode", str(ctx.exception))

  def test_missing_planning_mode_reason_rejected(self) -> None:
    payload = valid_solver_input_dict()
    del payload["planning_mode_reason"]
    with self.assertRaises(ValidationError) as ctx:
      SolverInputContract.model_validate(payload)
    self.assertIn("planning_mode_reason", str(ctx.exception))

  def test_all_four_optional_fields_can_be_absent(self) -> None:
    """planning_context_summary_json, grid_application_summary,
    stage_ramp_contract, payroll_headcount are all Optional per
    orchestrator entry signature; valid payload omits all four."""
    payload = valid_solver_input_dict(
      include_planning_context_summary_json=False,
      include_grid_application_summary=False,
      include_stage_ramp_contract=False,
      include_payroll_headcount=False,
    )
    contract = SolverInputContract.model_validate(payload)
    self.assertIsNone(contract.planning_context_summary_json)
    self.assertIsNone(contract.grid_application_summary)
    self.assertIsNone(contract.stage_ramp_contract)
    self.assertIsNone(contract.payroll_headcount)


# ---------------------------------------------------------------------------
# Composition with Contract 1 — FinmoModelInputContract typing
# ---------------------------------------------------------------------------

class CompositionWithContract1Test(unittest.TestCase):

  def test_applied_model_input_json_typed_as_finmo_model_input_contract(self) -> None:
    contract = SolverInputContract.model_validate(valid_solver_input_dict())
    self.assertIsInstance(contract.applied_model_input_json, FinmoModelInputContract)

  def test_catalog_source_model_input_json_typed_as_finmo_model_input_contract(self) -> None:
    """Flag 2 + Flag 6: catalog stays required AND types as Contract 1."""
    contract = SolverInputContract.model_validate(valid_solver_input_dict())
    self.assertIsInstance(contract.catalog_source_model_input_json, FinmoModelInputContract)

  def test_contract_1_invariant_violation_propagates(self) -> None:
    """Contract 1 enforces sections.revenue min_length=1. Wiping it
    in the applied_model_input_json sub-payload should surface as
    a ValidationError at SolverInputContract.model_validate."""
    payload = valid_solver_input_dict()
    payload["applied_model_input_json"]["sections"]["revenue"] = []
    with self.assertRaises(ValidationError) as ctx:
      SolverInputContract.model_validate(payload)
    self.assertIn("revenue", str(ctx.exception))


# ---------------------------------------------------------------------------
# Composition with Contract 2 — Finmo / StageRamp / PayrollHeadcount typing
# ---------------------------------------------------------------------------

class CompositionWithContract2Test(unittest.TestCase):

  def test_applied_finmo_json_typed_as_finmo_output_contract(self) -> None:
    """TC2: applied_finmo_json composes Contract 2's FinmoOutputContract."""
    contract = SolverInputContract.model_validate(valid_solver_input_dict())
    self.assertIsInstance(contract.applied_finmo_json, FinmoOutputContract)

  def test_stage_ramp_contract_typed_as_stage_ramp_contract(self) -> None:
    """Flag 3: stage_ramp_contract composes Contract 2's StageRampContract."""
    contract = SolverInputContract.model_validate(valid_solver_input_dict())
    self.assertIsInstance(contract.stage_ramp_contract, StageRampContract)

  def test_payroll_headcount_typed_as_payroll_headcount_contract(self) -> None:
    contract = SolverInputContract.model_validate(valid_solver_input_dict())
    self.assertIsInstance(contract.payroll_headcount, PayrollHeadcountContract)

  def test_contract_2_finmo_invariant_violation_propagates(self) -> None:
    """Contract 2 FinmoOutputContract requires
    periods length=21. Truncating it should surface here."""
    payload = valid_solver_input_dict()
    payload["applied_finmo_json"]["periods"] = payload["applied_finmo_json"]["periods"][:5]
    with self.assertRaises(ValidationError) as ctx:
      SolverInputContract.model_validate(payload)
    self.assertIn("periods", str(ctx.exception))


# ---------------------------------------------------------------------------
# Cross-field invariants — 4.4 (Flag 8(a)) + 4.5 (Flag 8(b))
# ---------------------------------------------------------------------------

class CrossFieldInvariantTest(unittest.TestCase):

  # --- Invariant 4.4 / Flag 8(a): planning_run_id_present_when_persisting ---

  def test_planning_run_id_present_string_accepted(self) -> None:
    """Flag 8(a) accepted half: a non-empty string passes the
    min_length=1 check."""
    payload = valid_solver_input_dict()
    payload["planning_run_id"] = "run_xyz"
    contract = SolverInputContract.model_validate(payload)
    self.assertEqual(contract.planning_run_id, "run_xyz")

  def test_planning_run_id_None_rejected(self) -> None:
    """Flag 8(a) rejected half: typed as str (NOT Optional[str])
    so None is rejected at field-level validation."""
    payload = valid_solver_input_dict()
    payload["planning_run_id"] = None
    with self.assertRaises(ValidationError) as ctx:
      SolverInputContract.model_validate(payload)
    self.assertIn("planning_run_id", str(ctx.exception))

  def test_planning_run_id_empty_string_rejected(self) -> None:
    """Flag 8(a) rejected half: empty string fails min_length=1.
    Without this check, the orchestrator's persist site at
    orchestrator.py:3609 would silently skip on empty
    planning_run_id."""
    payload = valid_solver_input_dict()
    payload["planning_run_id"] = ""
    with self.assertRaises(ValidationError) as ctx:
      SolverInputContract.model_validate(payload)
    self.assertIn("planning_run_id", str(ctx.exception))

  def test_draft_id_empty_string_rejected(self) -> None:
    """draft_id mirrors planning_run_id (str min_length=1).
    Same rationale: no silent skip at the persist boundary."""
    payload = valid_solver_input_dict()
    payload["draft_id"] = ""
    with self.assertRaises(ValidationError) as ctx:
      SolverInputContract.model_validate(payload)
    self.assertIn("draft_id", str(ctx.exception))

  # --- Invariant 4.5 / Flag 8(b): contract_versions_agree ---

  def test_contract_versions_agreeing_accepted(self) -> None:
    """Default fixture: both Contract-1-typed fields use the same
    fixture builder; contract_version matches by construction."""
    contract = SolverInputContract.model_validate(valid_solver_input_dict())
    self.assertEqual(
      contract.applied_model_input_json.contract_version,
      contract.catalog_source_model_input_json.contract_version,
    )

  def test_contract_versions_disagreeing_rejected(self) -> None:
    """Flag 8(b): if a future migration updates applied but not
    catalog (or vice versa), the cross-field validator fires.

    Both fields are pinned by Contract 1 to
    Literal['finmo_model_input_v3'], so we cannot trigger this
    via the public model_validate path -- the Literal field-level
    check fires FIRST and rejects any non-v3 string. This test
    constructs the SolverInputContract via direct __init__ with
    pre-validated FinmoModelInputContract instances (which exist)
    and confirms the cross-field validator would fire if a future
    migration breaks the Literal lock-step. We exercise the
    invariant by directly mutating the contract_version attribute
    on one of the parsed instances after model_validate completes,
    then re-running the validator manually.
    """
    contract = SolverInputContract.model_validate(valid_solver_input_dict())
    # Simulate drift: bypass Literal by mutating after parse.
    contract.applied_model_input_json.__dict__["contract_version"] = "finmo_model_input_v4"
    # Re-run the validator manually; it should raise.
    with self.assertRaises(ValueError) as ctx:
      contract.contract_versions_agree()
    self.assertIn("contract_version", str(ctx.exception))


# ---------------------------------------------------------------------------
# Adjustment B — API-boundary ContractViolation propagation
# ---------------------------------------------------------------------------

class ApiBoundaryContractViolationTest(unittest.TestCase):
  """Mirror of Contract 2's ApiBoundaryContractViolationTest.

  Verifies ContractViolation's structured shape at the wire
  level: stage tag, field path, expected vs actual, structured
  attributes for future handler, and propagation through the
  generic `except Exception as exc:` catch at
  python/api_handlers/intake_consult.py:7377 (Div-8).
  """

  def _violation(self) -> ContractViolation:
    """Build a representative ContractViolation as the gate would
    produce it."""
    return ContractViolation(
      stage=SOLVER_STAGE_LABEL,
      field="business_facts.fact_template",
      expected="Dict[str, Any]",
      actual="None",
      source_payload={"draft_id": "draft_test_001", "redacted": "..."},
    )

  def test_violation_message_uses_solver_stage_label(self) -> None:
    exc = self._violation()
    self.assertIn(SOLVER_STAGE_LABEL, str(exc))

  def test_violation_attributes_accessible_for_structured_handling(self) -> None:
    """ContractViolation carries stage/field/expected/actual as
    individual attrs so a future handler can route on the boundary
    name without parsing str(exc)."""
    exc = self._violation()
    self.assertEqual(exc.stage, SOLVER_STAGE_LABEL)
    self.assertEqual(exc.field, "business_facts.fact_template")
    self.assertEqual(exc.expected, "Dict[str, Any]")
    self.assertEqual(exc.actual, "None")
    self.assertIsInstance(exc.source_payload, dict)

  def test_violation_survives_generic_exception_catch_with_useful_message(self) -> None:
    """Div-8: the API handler at intake_consult.py:7377 catches
    `except Exception as exc:` and logs str(exc). Confirm the
    ContractViolation propagates as an informative string rather
    than the fallback 'system_run_failed' stack trace would
    produce."""
    try:
      raise self._violation()
    except Exception as exc:  # exact pattern from intake_consult.py:7377
      log_line = str(exc).strip() or "system_run_failed"
      self.assertIn(SOLVER_STAGE_LABEL, log_line)
      self.assertIn("business_facts", log_line)
      self.assertNotEqual(log_line, "system_run_failed")

  def test_violation_str_does_not_dump_source_payload(self) -> None:
    """source_payload may be a 100KB dict at the wire level; the
    str(violation) the API handler logs MUST stay readable.
    Adjustment B safety check."""
    exc = self._violation()
    log_str = str(exc)
    self.assertLess(len(log_str), 500, "str(violation) should stay readable")
    self.assertNotIn("redacted", log_str)


if __name__ == "__main__":
  unittest.main()
