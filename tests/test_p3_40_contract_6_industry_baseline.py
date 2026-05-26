"""Top-level + cross-field + Adjustment B acceptance tests for
Contract 6 (IndustryBaselineResolvedContract).

Spec: ``docs/architecture/p3_40_contract_6_industry_baseline_spec.md``
§6 Commit 1c.

5 test classes per spec:
- IndustryBaselineResolvedContractTopLevelTest: valid full
  payload + required-field rejection + extra='forbid'.
- CompositionInternalTest: each sub-contract's invariant
  violation propagates through the top-level validator.
- CrossFieldInvariantTest: F10 + F12 invariants firing through
  top-level construction.
- ContractSixDoesNotComposeContractFiveTest: F1 explicit
  verification that Contract 6 has ZERO composition with
  Contract 5.
- ApiBoundaryContractViolationTest: Adjustment B per Contracts
  3-5 pattern.
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

from client_intake_and_finmo.post_intake_contracts.industry_baseline_resolved_contract import (  # noqa: E402
  INDUSTRY_BASELINE_STAGE_LABEL,
  BusinessProfileInputContract,
  CascadeResolverPayloadContract,
  CohortSqlRowContract,
  ContractViolation,
  GetBandsViewBandContract,
  GetBandsViewContract,
  IndustryBaselineResolvedContract,
  PopulationSummaryContract,
  PopulationSummarySectionContract,
)
from _p3_40_contract_6_fixtures import (  # noqa: E402
  valid_business_profile_dict,
  valid_cascade_resolver_payload_dict,
  valid_cohort_sql_row_dict,
  valid_get_bands_view_dict,
  valid_industry_baseline_resolved_dict,
  valid_population_summary_dict,
  valid_population_summary_section_dict,
)


# ---------------------------------------------------------------------------
# IndustryBaselineResolvedContract -- top-level shape + extra='forbid'
# ---------------------------------------------------------------------------

class IndustryBaselineResolvedContractTopLevelTest(unittest.TestCase):

  def test_valid_full_payload_accepted(self) -> None:
    contract = IndustryBaselineResolvedContract.model_validate(
      valid_industry_baseline_resolved_dict()
    )
    self.assertIsInstance(contract.business_profile, BusinessProfileInputContract)
    self.assertEqual(len(contract.cascade_payloads), 2)
    self.assertEqual(len(contract.cohort_rows), 2)
    self.assertEqual(len(contract.get_bands_views), 2)
    self.assertIsNotNone(contract.population_summary)

  def test_extra_top_level_field_forbidden(self) -> None:
    """F18: extra='forbid' on top-level."""
    payload = valid_industry_baseline_resolved_dict()
    payload["unmodeled_top_level_field"] = {"foo": "bar"}
    with self.assertRaises(ValidationError) as ctx:
      IndustryBaselineResolvedContract.model_validate(payload)
    self.assertIn("unmodeled_top_level_field", str(ctx.exception))

  def test_missing_business_profile_rejected(self) -> None:
    payload = valid_industry_baseline_resolved_dict()
    del payload["business_profile"]
    with self.assertRaises(ValidationError) as ctx:
      IndustryBaselineResolvedContract.model_validate(payload)
    self.assertIn("business_profile", str(ctx.exception))

  def test_empty_cascade_payloads_dict_allowed(self) -> None:
    """cascade_payloads is Dict[str, ...] with default_factory=dict.
    Empty is structurally valid (e.g., when no cascade lookup
    fired in a test scenario)."""
    payload = valid_industry_baseline_resolved_dict()
    payload["cascade_payloads"] = {}
    payload["cohort_rows"] = []
    payload["get_bands_views"] = {}
    contract = IndustryBaselineResolvedContract.model_validate(payload)
    self.assertEqual(contract.cascade_payloads, {})
    self.assertEqual(contract.cohort_rows, [])
    self.assertEqual(contract.get_bands_views, {})

  def test_population_summary_optional_absent(self) -> None:
    payload = valid_industry_baseline_resolved_dict(
      include_population_summary=False,
    )
    contract = IndustryBaselineResolvedContract.model_validate(payload)
    self.assertIsNone(contract.population_summary)


# ---------------------------------------------------------------------------
# Composition propagation -- sub-contract violations bubble up
# ---------------------------------------------------------------------------

class CompositionInternalTest(unittest.TestCase):
  """Each sub-contract's invariant + Literal violation must
  propagate through the top-level validator. Demonstrates the
  6 sub-contracts are real sub-models, not opaque Dicts."""

  def test_business_profile_naics_non_pattern_propagates_acceptance(self) -> None:
    """R16 closure (Cleanup Commit 2): F11 pattern DROPPED per
    §0 alignment with 5b/5d. Non-pattern naics_6 values
    propagate as ACCEPTED through top-level model_validate
    (previously rejected per F11 pattern). PSL2 production-
    reality-wins: runner.py:562 upstream strip prevents these
    values from reaching production payloads."""
    payload = valid_industry_baseline_resolved_dict()
    payload["business_profile"]["naics_6"] = "ABC"
    contract = IndustryBaselineResolvedContract.model_validate(payload)
    self.assertEqual(contract.business_profile.naics_6, "ABC")

  def test_cascade_payload_literal_violation_propagates(self) -> None:
    """F13 trust_flag typo in any cascade_payloads entry
    surfaces through top-level."""
    payload = valid_industry_baseline_resolved_dict()
    payload["cascade_payloads"]["gross_margin_percent"]["trust_flag"] = "bad_flag"
    with self.assertRaises(ValidationError) as ctx:
      IndustryBaselineResolvedContract.model_validate(payload)
    self.assertIn("trust_flag", str(ctx.exception))

  def test_cohort_sql_row_monotonicity_propagates(self) -> None:
    """F12 (a) violation in any cohort_rows entry surfaces
    through top-level."""
    payload = valid_industry_baseline_resolved_dict()
    payload["cohort_rows"][0]["benchmark_min"] = 0.99
    payload["cohort_rows"][0]["benchmark_target"] = 0.40
    payload["cohort_rows"][0]["benchmark_max"] = 0.55
    with self.assertRaises(ValidationError) as ctx:
      IndustryBaselineResolvedContract.model_validate(payload)
    self.assertIn("monotonicity", str(ctx.exception))

  def test_get_bands_view_band_monotonicity_propagates(self) -> None:
    """F12 (b) violation inside get_bands_views[section].bands
    propagates."""
    payload = valid_industry_baseline_resolved_dict()
    bands = payload["get_bands_views"]["drivers"]["bands"]
    first_lever_id = next(iter(bands.keys()))
    bands[first_lever_id]["benchmark_min"] = 0.99
    bands[first_lever_id]["benchmark_target"] = 0.40
    bands[first_lever_id]["benchmark_max"] = 0.55
    with self.assertRaises(ValidationError) as ctx:
      IndustryBaselineResolvedContract.model_validate(payload)
    self.assertIn("monotonicity", str(ctx.exception))

  def test_population_summary_f10_propagates(self) -> None:
    """F10 zero-resolved-total violation in population_summary
    propagates through top-level."""
    payload = valid_industry_baseline_resolved_dict()
    payload["population_summary"] = {
      "drivers": {"resolved": 0, "skipped": 5},
    }
    with self.assertRaises(ValidationError) as ctx:
      IndustryBaselineResolvedContract.model_validate(payload)
    self.assertIn("zero resolved", str(ctx.exception))


# ---------------------------------------------------------------------------
# Cross-field invariants end-to-end at top-level
# ---------------------------------------------------------------------------

class CrossFieldInvariantTest(unittest.TestCase):
  """F10 + F12 firing through top-level construction. Distinct
  from CompositionInternalTest above -- those test propagation;
  these test the invariants themselves on their owning sub-
  contracts."""

  # --- F10: PopulationSummary resolved >= 1 ---

  def test_population_summary_single_resolved_accepted(self) -> None:
    """F10: even a single resolved band anywhere satisfies the
    invariant. Closes FAIL_COHORT_BANDS_MISSING precondition
    per v1 §F-2."""
    contract = PopulationSummaryContract.model_validate({
      "drivers": valid_population_summary_section_dict(resolved=1),
    })
    self.assertEqual(contract.drivers.resolved, 1)

  def test_population_summary_zero_resolved_rejected(self) -> None:
    with self.assertRaises(ValidationError) as ctx:
      PopulationSummaryContract.model_validate({})
    self.assertIn("zero resolved", str(ctx.exception))

  # --- F12 (a): CohortSqlRow monotonicity ---

  def test_cohort_sql_row_monotonicity_min_lt_target_lt_max_accepted(self) -> None:
    contract = CohortSqlRowContract.model_validate(
      valid_cohort_sql_row_dict(
        benchmark_min=0.20, benchmark_target=0.40, benchmark_max=0.55,
      )
    )
    self.assertEqual(contract.benchmark_min, 0.20)

  def test_cohort_sql_row_monotonicity_target_gt_max_rejected(self) -> None:
    payload = valid_cohort_sql_row_dict(
      benchmark_min=0.20, benchmark_target=0.60, benchmark_max=0.55,
    )
    with self.assertRaises(ValidationError):
      CohortSqlRowContract.model_validate(payload)


# ---------------------------------------------------------------------------
# F1: Contract 6 explicit no-composition with Contract 5
# ---------------------------------------------------------------------------

class ContractSixDoesNotComposeContractFiveTest(unittest.TestCase):
  """Pin F1 disposition end-to-end. Contract 6 does NOT
  re-import or wrap IntakeDraftContract; the business_profile
  is a 4-field EXTRACTION from Contract 5 intake fields, not
  a composition."""

  def test_contract_6_module_does_not_import_intake_draft_contract(self) -> None:
    """Inspect the Contract 6 module's imports -- intake_draft_contract
    must not appear."""
    import client_intake_and_finmo.post_intake_contracts.industry_baseline_resolved_contract as c6
    import inspect
    source = inspect.getsource(c6)
    self.assertNotIn(
      "intake_draft_contract",
      source,
      msg="Contract 6 must not import from intake_draft_contract per F1",
    )
    self.assertNotIn(
      "IntakeDraftContract", source,
      msg="Contract 6 must not reference IntakeDraftContract per F1",
    )

  def test_business_profile_is_standalone_4_field_input(self) -> None:
    """The business_profile sub-contract types the 4-field
    extracted dict at runner.py:573-579, NOT an
    IntakeDraftContract wrap."""
    bp = BusinessProfileInputContract.model_validate(
      valid_business_profile_dict()
    )
    # 4 declared fields per F2 + F11
    self.assertEqual(
      set(BusinessProfileInputContract.model_fields.keys()),
      {"naics_6", "target_annual_revenue", "stage", "business_model"},
    )


# ---------------------------------------------------------------------------
# Adjustment B -- API-boundary ContractViolation propagation
# ---------------------------------------------------------------------------

class ApiBoundaryContractViolationTest(unittest.TestCase):
  """Mirror of Contracts 3-5 ApiBoundaryContractViolationTest.
  Per trace Div-6 the API handler at intake_consult.py:7377
  catches ``except Exception as exc:`` and logs str(exc).
  ContractViolation is Exception subclass (not RuntimeError),
  so it skips the line-7298 RuntimeError branch and lands in
  the line-7377 generic catch as structured 500 with
  detail=str(exc) carrying INDUSTRY_BASELINE_STAGE_LABEL."""

  def _violation(self) -> ContractViolation:
    return ContractViolation(
      stage=INDUSTRY_BASELINE_STAGE_LABEL,
      field="population_summary",
      expected="at_least_1_resolved_band_across_5_sections",
      actual="zero",
      source_payload={"redacted": "..."},
    )

  def test_violation_message_uses_industry_baseline_stage_label(self) -> None:
    exc = self._violation()
    self.assertIn(INDUSTRY_BASELINE_STAGE_LABEL, str(exc))

  def test_violation_attributes_accessible_for_structured_handling(self) -> None:
    exc = self._violation()
    self.assertEqual(exc.stage, INDUSTRY_BASELINE_STAGE_LABEL)
    self.assertEqual(exc.field, "population_summary")
    self.assertEqual(exc.expected, "at_least_1_resolved_band_across_5_sections")
    self.assertEqual(exc.actual, "zero")
    self.assertIsInstance(exc.source_payload, dict)

  def test_violation_survives_generic_exception_catch(self) -> None:
    """Mirrors intake_consult.py:7377 catch pattern exactly."""
    try:
      raise self._violation()
    except Exception as exc:  # exact pattern from line 7377
      log_line = str(exc).strip() or "system_run_failed"
      self.assertIn(INDUSTRY_BASELINE_STAGE_LABEL, log_line)
      self.assertIn("population_summary", log_line)
      self.assertNotEqual(log_line, "system_run_failed")

  def test_violation_str_does_not_dump_source_payload(self) -> None:
    """source_payload may be a 100KB industry-baseline dict at
    the wire level; the str(violation) the API handler logs
    MUST stay readable. Adjustment B safety check carried from
    Contracts 3-5."""
    exc = self._violation()
    log_str = str(exc)
    self.assertLess(len(log_str), 500)
    self.assertNotIn("redacted", log_str)


if __name__ == "__main__":
  unittest.main()
