"""Per-sub-contract acceptance tests for Contract 3
(SolverInputContract).

Spec: ``docs/architecture/p3_40_contract_3_solver_input_spec.md`` §6
Commit 1b. Top-level + cross-field tests land in
``test_p3_40_contract_3_solver_input.py`` (Commit 1c).
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
  BusinessFactsForSolverContract,
  SUPPORTED_PLANNING_MODES,
  SolverInputContract,
)
from _p3_40_contract_3_fixtures import (  # noqa: E402
  valid_business_facts_dict,
  valid_solver_input_dict,
)


# ---------------------------------------------------------------------------
# BusinessFactsForSolverContract (the one new sub-contract)
# ---------------------------------------------------------------------------

class BusinessFactsForSolverContractTest(unittest.TestCase):

  def test_valid_minimal_payload_accepted(self) -> None:
    bf = BusinessFactsForSolverContract.model_validate(
      valid_business_facts_dict()
    )
    self.assertEqual(bf.fact_template["business_stage"], "growth")

  def test_missing_fact_template_rejected(self) -> None:
    with self.assertRaises(ValidationError) as ctx:
      BusinessFactsForSolverContract.model_validate({})
    self.assertIn("fact_template", str(ctx.exception))

  def test_extra_top_level_key_ignored(self) -> None:
    """Flag 7: BusinessFactsForSolverContract uses extra=ignore so
    intake-domain writers can add keys without breaking the
    contract. Future Contract 5 may tighten."""
    bf = BusinessFactsForSolverContract.model_validate({
      "fact_template": {"business_stage": "growth"},
      "extra_unmodeled_intake_blob": {"anything": "goes"},
    })
    # ignore -> not present on the model; not an error
    self.assertFalse(hasattr(bf, "extra_unmodeled_intake_blob"))

  def test_fact_template_accepts_arbitrary_dict_shape(self) -> None:
    """Flag 4: fact_template typed as Dict[str, Any] for first cut.
    Contract 5 (IntakeDraftContract) will tighten."""
    bf = BusinessFactsForSolverContract.model_validate({
      "fact_template": {
        "business_stage": "stability",
        "business_model": "marketplace",
        "any_future_key": [1, 2, 3],
      },
    })
    self.assertEqual(bf.fact_template["any_future_key"], [1, 2, 3])


# ---------------------------------------------------------------------------
# planning_mode Literal — typo-lock pair per Contract 1 pattern
# ---------------------------------------------------------------------------

class PlanningModeLiteralTest(unittest.TestCase):

  def test_growth_accepted(self) -> None:
    payload = valid_solver_input_dict()
    payload["planning_mode"] = "growth"
    SolverInputContract.model_validate(payload)

  def test_stability_accepted(self) -> None:
    payload = valid_solver_input_dict()
    payload["planning_mode"] = "stability"
    SolverInputContract.model_validate(payload)

  def test_runway_extension_accepted(self) -> None:
    payload = valid_solver_input_dict()
    payload["planning_mode"] = "runway_extension"
    SolverInputContract.model_validate(payload)

  def test_survival_accepted(self) -> None:
    payload = valid_solver_input_dict()
    payload["planning_mode"] = "survival"
    SolverInputContract.model_validate(payload)

  def test_supported_planning_modes_constant_matches_literal(self) -> None:
    """Constant + Literal must enumerate the same set. If a future
    member is added to the Literal without updating the constant
    (or vice versa) this test surfaces the drift."""
    self.assertEqual(
      set(SUPPORTED_PLANNING_MODES),
      {"growth", "stability", "runway_extension", "survival"},
    )

  def test_typo_rejected(self) -> None:
    """Lock-via-paired-test per Contract 1 typo-rejection pattern.
    The typo IS NOT in SUPPORTED_PLANNING_MODES and must be
    rejected. Pairs with test_*_accepted to pin both halves of the
    contract."""
    payload = valid_solver_input_dict()
    payload["planning_mode"] = "groweth"  # typo
    with self.assertRaises(ValidationError) as ctx:
      SolverInputContract.model_validate(payload)
    self.assertIn("planning_mode", str(ctx.exception))


# ---------------------------------------------------------------------------
# Tier-F field round-trip — kept-required per Flag 2
# ---------------------------------------------------------------------------

class TierFFieldsKeptRequiredTest(unittest.TestCase):
  """Flag 2: target_market_json, planning_result, and
  catalog_source_model_input_json are READER_MISSING today but
  kept required + typed. These tests pin the requirement so a
  future contract loosening doesn't slip through silently."""

  def test_target_market_json_required(self) -> None:
    payload = valid_solver_input_dict()
    del payload["target_market_json"]
    with self.assertRaises(ValidationError) as ctx:
      SolverInputContract.model_validate(payload)
    self.assertIn("target_market_json", str(ctx.exception))

  def test_planning_result_required(self) -> None:
    payload = valid_solver_input_dict()
    del payload["planning_result"]
    with self.assertRaises(ValidationError) as ctx:
      SolverInputContract.model_validate(payload)
    self.assertIn("planning_result", str(ctx.exception))

  def test_catalog_source_model_input_json_required(self) -> None:
    payload = valid_solver_input_dict()
    del payload["catalog_source_model_input_json"]
    with self.assertRaises(ValidationError) as ctx:
      SolverInputContract.model_validate(payload)
    self.assertIn("catalog_source_model_input_json", str(ctx.exception))


# ---------------------------------------------------------------------------
# Tier-C field round-trip — Optional per TC3
# ---------------------------------------------------------------------------

class TierCFieldsOptionalTest(unittest.TestCase):
  """TC3: planning_context_summary_json + grid_application_summary
  are persist-only round-trip; both Optional[Dict[str, Any]] at
  this boundary."""

  def test_planning_context_summary_json_optional_absent(self) -> None:
    payload = valid_solver_input_dict(include_planning_context_summary_json=False)
    contract = SolverInputContract.model_validate(payload)
    self.assertIsNone(contract.planning_context_summary_json)

  def test_grid_application_summary_optional_absent(self) -> None:
    payload = valid_solver_input_dict(include_grid_application_summary=False)
    contract = SolverInputContract.model_validate(payload)
    self.assertIsNone(contract.grid_application_summary)


# ---------------------------------------------------------------------------
# Optional sub-contracts (stage_ramp_contract, payroll_headcount)
# ---------------------------------------------------------------------------

class OptionalSubContractsTest(unittest.TestCase):

  def test_stage_ramp_contract_optional_absent(self) -> None:
    payload = valid_solver_input_dict(include_stage_ramp_contract=False)
    contract = SolverInputContract.model_validate(payload)
    self.assertIsNone(contract.stage_ramp_contract)

  def test_stage_ramp_contract_typed_when_present(self) -> None:
    """Flag 3: when present, stage_ramp_contract types as Contract 2's
    StageRampContract. Composition inherits invariant 4.2
    (quarter_ramp_grid length)."""
    payload = valid_solver_input_dict(include_stage_ramp_contract=True)
    contract = SolverInputContract.model_validate(payload)
    self.assertIsNotNone(contract.stage_ramp_contract)
    self.assertEqual(contract.stage_ramp_contract.stage_family, "growth")
    self.assertEqual(len(contract.stage_ramp_contract.quarter_ramp_grid), 20)

  def test_payroll_headcount_optional_absent(self) -> None:
    payload = valid_solver_input_dict(include_payroll_headcount=False)
    contract = SolverInputContract.model_validate(payload)
    self.assertIsNone(contract.payroll_headcount)

  def test_payroll_headcount_typed_when_present(self) -> None:
    """Composition inherits Contract 2's PayrollHeadcountContract
    horizon-coverage invariant 4.3."""
    payload = valid_solver_input_dict(include_payroll_headcount=True)
    contract = SolverInputContract.model_validate(payload)
    self.assertIsNotNone(contract.payroll_headcount)
    self.assertEqual(
      contract.payroll_headcount.capacity_labor_model,
      "capacity_units_per_supporting_fte",
    )


if __name__ == "__main__":
  unittest.main()
