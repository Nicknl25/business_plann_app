"""Top-level + Adjustment B acceptance tests for Contract 5
(IntakeDraftContract).

Spec: ``docs/architecture/p3_40_contract_5_intake_draft_spec.md``
section 6 Commit 1c.

Test classes (per spec section 6 -- 3 classes, NOT 5 because
Contract 5 has no composition and no cross-field invariants in
Commit 1a):

- IntakeDraftContractAcceptanceTest: valid full payload accepted +
  per-required-field rejection.
- FulfillmentJsonDispositionTest: F1 (a) Optional disposition
  pinned end-to-end.
- ApiBoundaryContractViolationTest: Adjustment B per Contracts
  3 + 4 pattern. ContractViolation message uses
  INTAKE_DRAFT_STAGE_LABEL; structured attrs accessible;
  survives intake_consult.py:7377 generic Exception catch;
  source_payload not dumped into str.
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

from client_intake_and_finmo.post_intake_contracts.intake_draft_contract import (  # noqa: E402
  INTAKE_DRAFT_STAGE_LABEL,
  ContractViolation,
  IntakeDraftContract,
)
from _p3_40_contract_5_fixtures import (  # noqa: E402
  valid_intake_draft_dict,
)


# ---------------------------------------------------------------------------
# IntakeDraftContract -- full-payload acceptance + per-field
# rejection coverage (mirrors Contracts 3-4 TopLevelTest scope)
# ---------------------------------------------------------------------------

class IntakeDraftContractAcceptanceTest(unittest.TestCase):

  def test_valid_full_payload_accepted(self) -> None:
    contract = IntakeDraftContract.model_validate(valid_intake_draft_dict())
    # Per Commit 5b-3 retrofit: operating_model_json is now typed
    # as OperatingModelJsonContract -- attribute access, not dict
    # lookup. business_naics_6 is one of the 4 production extras
    # (T3) populated by default in valid_operating_model_json_dict().
    self.assertEqual(
      contract.operating_model_json.business_naics_6, "722515",
    )
    self.assertIsNotNone(contract.fulfillment_json)

  def test_valid_payload_with_no_fulfillment_accepted(self) -> None:
    """The minimum-viable payload omits fulfillment_json -- 7
    required Tier-A fields present, 1 Tier-F Optional absent."""
    payload = valid_intake_draft_dict(include_fulfillment_json=False)
    contract = IntakeDraftContract.model_validate(payload)
    self.assertIsNone(contract.fulfillment_json)
    self.assertEqual(
      contract.planning_context_summary_json["planning_mode"], "growth",
    )

  def _assert_missing_required_field_rejected_exhaustively(
    self, field_name: str,
  ) -> None:
    payload = valid_intake_draft_dict()
    del payload[field_name]
    with self.assertRaises(ValidationError) as ctx:
      IntakeDraftContract.model_validate(payload)
    self.assertIn(field_name, str(ctx.exception))

  def test_missing_operating_model_json_rejected_exhaustive(self) -> None:
    self._assert_missing_required_field_rejected_exhaustively(
      "operating_model_json",
    )

  def test_missing_target_market_json_rejected_exhaustive(self) -> None:
    self._assert_missing_required_field_rejected_exhaustively(
      "target_market_json",
    )

  def test_missing_people_json_rejected_exhaustive(self) -> None:
    self._assert_missing_required_field_rejected_exhaustively("people_json")

  def test_missing_financials_json_rejected_exhaustive(self) -> None:
    self._assert_missing_required_field_rejected_exhaustively("financials_json")

  def test_missing_financials_year1_json_rejected_exhaustive(self) -> None:
    self._assert_missing_required_field_rejected_exhaustively(
      "financials_year1_json",
    )

  def test_missing_marketing_model_json_rejected_exhaustive(self) -> None:
    self._assert_missing_required_field_rejected_exhaustively(
      "marketing_model_json",
    )

  def test_missing_planning_context_summary_json_rejected_exhaustive(self) -> None:
    self._assert_missing_required_field_rejected_exhaustively(
      "planning_context_summary_json",
    )


# ---------------------------------------------------------------------------
# F1 (a) fulfillment_json disposition pinned end-to-end
# ---------------------------------------------------------------------------

class FulfillmentJsonDispositionTest(unittest.TestCase):
  """Three test cases pin F1 (a). Mirrors Contract 4's
  PhantomReadFieldsOptionalTest pattern. Pins the disposition so
  a future contract tightening to required doesn't slip through
  silently."""

  def test_fulfillment_json_absent_validates_as_none(self) -> None:
    """Tier F field -- Optional[Dict[str, Any]] = None per F1 (a)."""
    payload = valid_intake_draft_dict(include_fulfillment_json=False)
    contract = IntakeDraftContract.model_validate(payload)
    self.assertIsNone(contract.fulfillment_json)

  def test_fulfillment_json_empty_dict_accepted(self) -> None:
    """No schema enforcement at field level (Trace T4.1 + v1
    inventory section F-2). Empty dict reflects production
    reality after a single fulfillment.* patch that didn't add
    keys."""
    payload = valid_intake_draft_dict()
    payload["fulfillment_json"] = {}
    contract = IntakeDraftContract.model_validate(payload)
    self.assertEqual(contract.fulfillment_json, {})

  def test_fulfillment_json_arbitrary_keys_accepted(self) -> None:
    """Patch-system writes arbitrary keys -- the contract reflects
    this; no schema gate (per v1 section F-2 known bug, captured
    here intentionally rather than papered over)."""
    payload = valid_intake_draft_dict()
    payload["fulfillment_json"] = {
      "fulfillment_model": "membership",
      "future_arbitrary_key": [1, 2, {"nested": True}],
      "another": None,
    }
    contract = IntakeDraftContract.model_validate(payload)
    self.assertEqual(
      contract.fulfillment_json["future_arbitrary_key"], [1, 2, {"nested": True}],
    )


# ---------------------------------------------------------------------------
# Adjustment B -- API-boundary ContractViolation propagation
# ---------------------------------------------------------------------------

class ApiBoundaryContractViolationTest(unittest.TestCase):
  """Mirror of Contracts 3 + 4 ApiBoundaryContractViolationTest.
  Per trace Div-6: the API handler at intake_consult.py:7377
  catches ``except Exception as exc:`` and logs ``str(exc)``.
  ContractViolation is Exception subclass (not RuntimeError) so it
  skips the line-7298 RuntimeError branch and lands in the
  line-7377 generic catch as a structured 500 with
  ``detail=str(exc)`` carrying ``INTAKE_DRAFT_STAGE_LABEL``.

  The catch chain wraps ``_run_planning_system_for_draft`` ->
  ``_run_planning_system_for_draft_unified`` ->
  ``prepare_initial_grid_for_draft`` -- so a ContractViolation
  raised by Contract 5's gate at runner.py:30+ propagates through
  the same chain Contracts 3 + 4 validated.
  """

  def _violation(self) -> ContractViolation:
    return ContractViolation(
      stage=INTAKE_DRAFT_STAGE_LABEL,
      field="financials_json",
      expected="Dict[str, Any]",
      actual="None",
      source_payload={"redacted": "..."},
    )

  def test_violation_message_uses_intake_draft_stage_label(self) -> None:
    exc = self._violation()
    self.assertIn(INTAKE_DRAFT_STAGE_LABEL, str(exc))

  def test_violation_attributes_accessible_for_structured_handling(self) -> None:
    exc = self._violation()
    self.assertEqual(exc.stage, INTAKE_DRAFT_STAGE_LABEL)
    self.assertEqual(exc.field, "financials_json")
    self.assertEqual(exc.expected, "Dict[str, Any]")
    self.assertEqual(exc.actual, "None")
    self.assertIsInstance(exc.source_payload, dict)

  def test_violation_survives_generic_exception_catch(self) -> None:
    """Mirrors intake_consult.py:7377 catch pattern exactly."""
    try:
      raise self._violation()
    except Exception as exc:  # exact pattern from line 7377
      log_line = str(exc).strip() or "system_run_failed"
      self.assertIn(INTAKE_DRAFT_STAGE_LABEL, log_line)
      self.assertIn("financials_json", log_line)
      self.assertNotEqual(log_line, "system_run_failed")

  def test_violation_str_does_not_dump_source_payload(self) -> None:
    """source_payload may be a 100KB intake-draft dict at the wire
    level; the str(violation) the API handler logs MUST stay
    readable. Adjustment B safety check carried from Contracts
    3 + 4."""
    exc = self._violation()
    log_str = str(exc)
    self.assertLess(len(log_str), 500)
    self.assertNotIn("redacted", log_str)


if __name__ == "__main__":
  unittest.main()
