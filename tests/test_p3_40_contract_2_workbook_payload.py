"""Top-level + cross-field + API-boundary acceptance tests for
``WorkbookPayloadContract``.

Covers:

  - WorkbookPayloadContract top-level: required fields, optional
    fields, extra="forbid" enforcement, composition with Contract 1.
  - Cross-field invariant 4.1 with Adjustment A chain-raise:
    ``stage_ramp_reachable_when_planning_run_populated``.
  - Adjustment B / API-boundary: ContractViolation's structured
    message format survives the existing API handler's
    ``except Exception as exc:`` pattern at
    ``python/api_handlers/intake_consult.py:7655`` and the
    operator sees a useful error string rather than a 500 stack
    trace. The actual contract gate at
    ``build_client_financial_model_workbook`` entry is wired in
    Commit 3; this commit verifies the message format that Commit
    3's gate will emit.

Per-sub-contract tests for the 10 sub-contracts live in
``test_p3_40_contract_2_subcontracts.py``.

Spec: ``docs/architecture/p3_40_contract_2_workbook_payload_spec.md``.
Shared fixtures in ``_p3_40_contract_2_fixtures.py``.
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

from client_intake_and_finmo.post_intake_contracts.workbook_payload_contract import (  # noqa: E402
  ContractViolation,
  PlanningRunJsonForWorkbookContract,
  WORKBOOK_STAGE_LABEL,
  WorkbookPayloadContract,
)
from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (  # noqa: E402
  FinmoModelInputContract,
)
from _p3_40_contract_2_fixtures import (  # noqa: E402
  valid_planning_run_json_dict,
  valid_workbook_payload_dict,
)


# ---------------------------------------------------------------------------
# Top-level WorkbookPayloadContract
# ---------------------------------------------------------------------------

class WorkbookPayloadContractTopLevelTest(unittest.TestCase):

  def test_valid_full_payload(self) -> None:
    contract = WorkbookPayloadContract.model_validate(valid_workbook_payload_dict())
    self.assertIsInstance(contract.model_input_json, FinmoModelInputContract)
    self.assertIsNotNone(contract.finmo_json)
    self.assertIsNotNone(contract.payroll_headcount)
    self.assertIsNotNone(contract.debt_schedule)
    self.assertIsNotNone(contract.planning_run_json)
    self.assertIsNotNone(contract.run_diagnostics)

  def test_valid_without_optional_planning_run_json(self) -> None:
    payload = valid_workbook_payload_dict(include_planning_run=False)
    self.assertNotIn("planning_run_json", payload)
    contract = WorkbookPayloadContract.model_validate(payload)
    self.assertIsNone(contract.planning_run_json)

  def test_valid_without_optional_run_diagnostics(self) -> None:
    payload = valid_workbook_payload_dict(include_run_diagnostics=False)
    self.assertNotIn("run_diagnostics", payload)
    contract = WorkbookPayloadContract.model_validate(payload)
    self.assertIsNone(contract.run_diagnostics)

  def test_missing_model_input_json_rejected(self) -> None:
    bad = valid_workbook_payload_dict()
    del bad["model_input_json"]
    with self.assertRaises(ValidationError):
      WorkbookPayloadContract.model_validate(bad)

  def test_missing_finmo_json_rejected(self) -> None:
    bad = valid_workbook_payload_dict()
    del bad["finmo_json"]
    with self.assertRaises(ValidationError):
      WorkbookPayloadContract.model_validate(bad)

  def test_missing_payroll_headcount_rejected(self) -> None:
    bad = valid_workbook_payload_dict()
    del bad["payroll_headcount"]
    with self.assertRaises(ValidationError):
      WorkbookPayloadContract.model_validate(bad)

  def test_missing_debt_schedule_rejected(self) -> None:
    """Per Flag 1 (a): debt_schedule is REQUIRED, not Optional."""
    bad = valid_workbook_payload_dict()
    del bad["debt_schedule"]
    with self.assertRaises(ValidationError):
      WorkbookPayloadContract.model_validate(bad)

  def test_extra_top_level_field_forbidden(self) -> None:
    """Per Flag 2 amended: extra="forbid" ONLY at top level."""
    bad = valid_workbook_payload_dict()
    bad["surprise_field"] = "not allowed"
    with self.assertRaises(ValidationError):
      WorkbookPayloadContract.model_validate(bad)


# ---------------------------------------------------------------------------
# Composition with Contract 1
# ---------------------------------------------------------------------------

class CompositionWithContract1Test(unittest.TestCase):

  def test_model_input_json_typed_as_finmo_model_input_contract(self) -> None:
    contract = WorkbookPayloadContract.model_validate(valid_workbook_payload_dict())
    self.assertIsInstance(contract.model_input_json, FinmoModelInputContract)
    # Confirm Contract 1's section structure is reachable through composition
    self.assertEqual(contract.model_input_json.contract_version, "finmo_model_input_v3")
    self.assertIsNotNone(contract.model_input_json.sections.revenue)
    self.assertIsNotNone(contract.model_input_json.sections.schedules)

  def test_contract_1_invariant_violation_propagates_through_composition(self) -> None:
    """If the composed model_input_json fails Contract 1's invariants
    (e.g., empty revenue rows), the workbook contract's validation
    surfaces the same error through pydantic's nested-error path."""
    bad = valid_workbook_payload_dict()
    bad["model_input_json"]["sections"]["revenue"] = []  # Contract 1 requires min_length=1
    with self.assertRaises(ValidationError) as ctx:
      WorkbookPayloadContract.model_validate(bad)
    self.assertIn("revenue", str(ctx.exception))


# ---------------------------------------------------------------------------
# Invariant 4.1 with Adjustment A — chain-raise
# ---------------------------------------------------------------------------

class StageRampReachableChainRaiseTest(unittest.TestCase):
  """Invariant 4.1 / Adjustment A: when ``planning_run_json`` is
  populated, the canonical
  ``unified_convergence_context.business_world_contract.stage_ramp_contract``
  path MUST be reachable. Each None in the chain raises a specific
  message; no short-circuit."""

  def test_planning_run_json_absent_is_ok(self) -> None:
    """No invariant applies when planning_run_json is absent."""
    payload = valid_workbook_payload_dict(include_planning_run=False)
    WorkbookPayloadContract.model_validate(payload)

  def test_planning_run_json_empty_dict_is_ok(self) -> None:
    """An empty planning_run_json dict means
    unified_convergence_context is None — the validator only
    raises when the OUTER planning_run_json is non-None."""
    # We need PlanningRunJsonForWorkbookContract to be present-but-empty
    # to trigger the validator. The fixture builds it via from
    # valid_planning_run_json_dict(include_stage_ramp=False) which
    # returns {} so unified_convergence_context = None at the
    # WorkbookPayloadContract level.
    payload = valid_workbook_payload_dict()
    payload["planning_run_json"] = valid_planning_run_json_dict(include_stage_ramp=False)
    with self.assertRaises(ValidationError) as ctx:
      WorkbookPayloadContract.model_validate(payload)
    self.assertIn("unified_convergence_context missing", str(ctx.exception))

  def test_missing_unified_convergence_context_raises(self) -> None:
    payload = valid_workbook_payload_dict()
    payload["planning_run_json"] = {}  # populated wrapper but no nested keys
    with self.assertRaises(ValidationError) as ctx:
      WorkbookPayloadContract.model_validate(payload)
    self.assertIn("unified_convergence_context", str(ctx.exception))

  def test_missing_business_world_contract_raises(self) -> None:
    payload = valid_workbook_payload_dict()
    payload["planning_run_json"] = {"unified_convergence_context": {}}
    with self.assertRaises(ValidationError) as ctx:
      WorkbookPayloadContract.model_validate(payload)
    self.assertIn("business_world_contract missing", str(ctx.exception))

  def test_missing_stage_ramp_contract_raises(self) -> None:
    payload = valid_workbook_payload_dict()
    payload["planning_run_json"] = {
      "unified_convergence_context": {"business_world_contract": {}},
    }
    with self.assertRaises(ValidationError) as ctx:
      WorkbookPayloadContract.model_validate(payload)
    self.assertIn("stage_ramp_contract missing", str(ctx.exception))
    self.assertIn("canonical path", str(ctx.exception))

  def test_full_chain_populated_is_ok(self) -> None:
    """Happy path: full canonical chain populated."""
    payload = valid_workbook_payload_dict(include_planning_run=True)
    WorkbookPayloadContract.model_validate(payload)


# ---------------------------------------------------------------------------
# Adjustment B — API-boundary / ContractViolation message-format test
# ---------------------------------------------------------------------------

class ApiBoundaryContractViolationTest(unittest.TestCase):
  """Adjustment B: when the consumer-side gate at
  ``build_client_financial_model_workbook`` (wired in Commit 3) fires
  a ContractViolation, the existing API handler at
  ``python/api_handlers/intake_consult.py:7655`` catches it through
  its generic ``except Exception as exc:`` block and surfaces
  ``str(exc).strip()`` to the operator. The handler does NOT
  re-raise; it logs via app.logger.exception and continues.

  This test confirms two properties Commit 3 will rely on:

    1. ContractViolation.__str__ produces a structured message
       ("STAGE: field 'X' expected Y, got Z") that's informative
       to a human reading the API response or server log.

    2. The structured stage/field/expected/actual attributes are
       accessible on the exception instance for any future handler
       that wants to surface them as JSON fields (out of scope for
       Contract 2 — the existing handler uses generic str()).

  The actual integration test that runs
  ``build_client_financial_model_workbook(bad_data)`` and confirms
  the gate fires lands in Commit 3 alongside the gate wiring.
  """

  def test_violation_message_uses_workbook_stage_label(self) -> None:
    exc = ContractViolation(
      stage=WORKBOOK_STAGE_LABEL,
      field="sections.balance_sheet[2].label",
      expected="non-empty string",
      actual="''",
    )
    msg = str(exc)
    # The format the API handler's str(exc) surfaces:
    self.assertIn(WORKBOOK_STAGE_LABEL, msg)
    self.assertIn("sections.balance_sheet[2].label", msg)
    self.assertIn("expected non-empty string", msg)
    self.assertIn("got ''", msg)

  def test_violation_attributes_accessible_for_structured_handling(self) -> None:
    """A future API handler upgrade could read these attributes to
    return structured JSON. Today the handler uses generic str(),
    but the contract preserves the structured payload."""
    payload = {"sections": {"revenue": []}}  # opaque example
    exc = ContractViolation(
      stage=WORKBOOK_STAGE_LABEL,
      field="sections.revenue",
      expected="at least one row",
      actual="empty list",
      source_payload=payload,
    )
    self.assertEqual(exc.stage, WORKBOOK_STAGE_LABEL)
    self.assertEqual(exc.field, "sections.revenue")
    self.assertEqual(exc.expected, "at least one row")
    self.assertEqual(exc.actual, "empty list")
    self.assertIs(exc.source_payload, payload)

  def test_violation_survives_generic_exception_catch_with_useful_message(self) -> None:
    """Simulates the API handler's catch pattern at
    intake_consult.py:7655: `except Exception as exc:
    workbook_export_error = str(exc).strip()`.

    The captured error string MUST identify the boundary AND the
    failing field — a 500 stack trace alone would not tell the
    operator which sub-field of which JSON column is malformed.
    """
    captured_error: str = ""
    try:
      raise ContractViolation(
        stage=WORKBOOK_STAGE_LABEL,
        field="payroll_headcount.rows[3].annual_wage",
        expected="float > 0",
        actual="-100.0",
      )
    except Exception as exc:
      captured_error = str(exc).strip()
    # The captured string identifies BOTH the boundary AND the field:
    self.assertTrue(captured_error.startswith(WORKBOOK_STAGE_LABEL))
    self.assertIn("payroll_headcount.rows[3].annual_wage", captured_error)
    self.assertIn("expected float > 0", captured_error)
    self.assertIn("got -100.0", captured_error)
    # Confirm the message is genuinely actionable — at minimum, it
    # mentions the field path the operator needs to investigate.
    self.assertGreater(len(captured_error), 40)

  def test_violation_str_does_not_dump_source_payload(self) -> None:
    """source_payload may be a huge dict (the full DraftWorkbookData
    bundle). The default str() must NOT include it — otherwise the
    server log fills with 100s of KB per failure and the operator's
    eyes glaze over."""
    huge_payload = {f"key_{i}": "x" * 1000 for i in range(50)}
    exc = ContractViolation(
      stage=WORKBOOK_STAGE_LABEL,
      field="x", expected="y", actual="z",
      source_payload=huge_payload,
    )
    msg = str(exc)
    # source_payload contents must not bleed into the str
    self.assertNotIn("x" * 100, msg)
    self.assertLess(len(msg), 500)


# ---------------------------------------------------------------------------
# Existing-validate_draft_data interop: WorkbookPayloadContract enforces
# the same 4 required-field assumptions that data.py:212 enforces today
# ---------------------------------------------------------------------------

class WorkbookPayloadInteropWithValidateDraftDataTest(unittest.TestCase):
  """The existing ``validate_draft_data(data: DraftWorkbookData)``
  at ``client_statements_output_excel/data.py:212`` requires
  model_input_json, finmo_json, payroll_headcount, and debt_schedule
  to be non-empty. WorkbookPayloadContract enforces the same 4 as
  required fields (plus shape validation on top). This test
  confirms the overlap so Commit 3's replacement of validate_draft_data
  with the contract gate is a strict superset — never weakens
  what was previously enforced."""

  def test_all_four_required_fields_match_validate_draft_data(self) -> None:
    """The 4 currently-required fields each fail validation when
    removed. validate_draft_data raises a RuntimeError listing the
    missing fields; the contract raises ValidationError per field."""
    required = ["model_input_json", "finmo_json", "payroll_headcount", "debt_schedule"]
    for field in required:
      with self.subTest(field=field):
        bad = valid_workbook_payload_dict()
        del bad[field]
        with self.assertRaises(ValidationError):
          WorkbookPayloadContract.model_validate(bad)

  def test_planning_run_json_NOT_required_same_as_validate_draft_data(self) -> None:
    """validate_draft_data does NOT require planning_run_json.
    Contract 2 mirrors: planning_run_json is Optional. Removing
    it must pass."""
    payload = valid_workbook_payload_dict(include_planning_run=False)
    WorkbookPayloadContract.model_validate(payload)

  def test_run_diagnostics_NOT_required_same_as_validate_draft_data(self) -> None:
    """validate_draft_data does NOT require run_diagnostics.
    Contract 2 mirrors: run_diagnostics is Optional."""
    payload = valid_workbook_payload_dict(include_run_diagnostics=False)
    WorkbookPayloadContract.model_validate(payload)


if __name__ == "__main__":
  unittest.main(verbosity=2)
