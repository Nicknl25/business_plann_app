"""Per-sub-contract acceptance tests for Contract 6
(IndustryBaselineResolvedContract).

Spec: ``docs/architecture/p3_40_contract_6_industry_baseline_spec.md``
§6 Commit 1b. Top-level + cross-field tests land in
``test_p3_40_contract_6_industry_baseline.py`` (Commit 1c).

8 test classes covering:
- BusinessProfileInputContractTest (F11 + F2)
- CascadeResolverPayloadContractTest (F4 + F5-α + F8 + F13)
- CohortSqlRowContractTest (F3 + F8 + F13 + F9 + F12)
- GetBandsViewBandContractTest (F12 + F9 + F7 documentation)
- GetBandsViewContractTest (F3 envelope)
- PopulationSummaryContractTest (F3 + F10)
- LiteralVocabularyConstantsTest (typo-lock pattern per Contract 1)
- ExtraPolicyTest (F18 sub-contract extra='ignore')
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
  SUPPORTED_CONFIDENCE_TIERS,
  SUPPORTED_COHORT_TABLES,
  SUPPORTED_NAICS_LEVELS,
  SUPPORTED_SECTIONS,
  SUPPORTED_TRUST_FLAGS,
  BusinessProfileInputContract,
  CascadeResolverPayloadContract,
  CohortSqlRowContract,
  GetBandsViewBandContract,
  GetBandsViewContract,
  PopulationSummaryContract,
  PopulationSummarySectionContract,
)
from _p3_40_contract_6_fixtures import (  # noqa: E402
  valid_business_profile_dict,
  valid_cascade_resolver_payload_dict,
  valid_cohort_sql_row_dict,
  valid_get_bands_view_band_dict,
  valid_get_bands_view_dict,
  valid_population_summary_dict,
  valid_population_summary_section_dict,
)


# ---------------------------------------------------------------------------
# BusinessProfileInputContract
# ---------------------------------------------------------------------------

class BusinessProfileInputContractTest(unittest.TestCase):
  """F11 NAICS-6 pattern validation + F2 business_model
  Literal[None] pin."""

  def test_valid_minimal_payload_accepted(self) -> None:
    bp = BusinessProfileInputContract.model_validate(
      valid_business_profile_dict()
    )
    self.assertEqual(bp.naics_6, "722515")
    self.assertEqual(bp.business_model, None)

  def test_all_fields_optional_default_none(self) -> None:
    bp = BusinessProfileInputContract.model_validate({"business_model": None})
    self.assertIsNone(bp.naics_6)
    self.assertIsNone(bp.target_annual_revenue)
    self.assertIsNone(bp.stage)

  def test_naics_6_valid_6_digit_accepted(self) -> None:
    bp = BusinessProfileInputContract.model_validate({
      "naics_6": "123456", "business_model": None,
    })
    self.assertEqual(bp.naics_6, "123456")

  def test_naics_6_5_digit_rejected(self) -> None:
    """F11: pattern=r'^[0-9]{6}$' rejects 5-digit strings."""
    with self.assertRaises(ValidationError) as ctx:
      BusinessProfileInputContract.model_validate({
        "naics_6": "12345", "business_model": None,
      })
    self.assertIn("naics_6", str(ctx.exception))

  def test_naics_6_alpha_rejected(self) -> None:
    """F11: pattern rejects alpha-contaminated strings.
    Surfaces v1 §F-3 garbage inputs (e.g., 'ABC') at the contract
    gate instead of silently treating as no_coverage."""
    with self.assertRaises(ValidationError) as ctx:
      BusinessProfileInputContract.model_validate({
        "naics_6": "ABC123", "business_model": None,
      })
    self.assertIn("naics_6", str(ctx.exception))

  def test_business_model_string_rejected(self) -> None:
    """F2 (a) Literal[None] pin. Future code change setting
    business_model = 'saas' surfaces as ContractViolation,
    forcing contract amendment alongside code (R12)."""
    with self.assertRaises(ValidationError) as ctx:
      BusinessProfileInputContract.model_validate({
        "naics_6": "722515", "business_model": "saas",
      })
    self.assertIn("business_model", str(ctx.exception))

  def test_extra_top_level_key_ignored(self) -> None:
    """F18: extra='ignore' on sub-contracts."""
    bp = BusinessProfileInputContract.model_validate({
      "naics_6": "722515", "business_model": None,
      "future_intake_field": "anything",
    })
    self.assertFalse(hasattr(bp, "future_intake_field"))


# ---------------------------------------------------------------------------
# Shape A -- CascadeResolverPayloadContract
# ---------------------------------------------------------------------------

class CascadeResolverPayloadContractTest(unittest.TestCase):
  """F4 fallback_chain_attempted + F5-α NO cohort_query + F8
  confidence_tier Literal + F13 trust_flag + naics_level_used
  Literal pinning."""

  def test_valid_13_field_payload_accepted(self) -> None:
    """F5-α: 13 fields verbatim from lookup.py:240-256. NO
    cohort_query."""
    contract = CascadeResolverPayloadContract.model_validate(
      valid_cascade_resolver_payload_dict()
    )
    self.assertEqual(contract.metric_key, "gross_margin_percent")
    self.assertEqual(len(CascadeResolverPayloadContract.model_fields), 13)
    self.assertNotIn(
      "cohort_query", CascadeResolverPayloadContract.model_fields,
    )

  def test_missing_metric_key_rejected(self) -> None:
    payload = valid_cascade_resolver_payload_dict()
    del payload["metric_key"]
    with self.assertRaises(ValidationError):
      CascadeResolverPayloadContract.model_validate(payload)

  def test_confidence_tier_typo_rejected(self) -> None:
    """F8: Literal['high', 'medium', 'low', 'generic_default']."""
    payload = valid_cascade_resolver_payload_dict()
    payload["confidence_tier"] = "highest"  # typo
    with self.assertRaises(ValidationError) as ctx:
      CascadeResolverPayloadContract.model_validate(payload)
    self.assertIn("confidence_tier", str(ctx.exception))

  def test_trust_flag_typo_rejected(self) -> None:
    """F13: Literal of 6 values."""
    payload = valid_cascade_resolver_payload_dict()
    payload["trust_flag"] = "naics_6_directt"  # typo
    with self.assertRaises(ValidationError) as ctx:
      CascadeResolverPayloadContract.model_validate(payload)
    self.assertIn("trust_flag", str(ctx.exception))

  def test_naics_level_1_rejected(self) -> None:
    """F13: Literal[0, 2, 3, 4, 5, 6] -- non-contiguous; level
    1 not allowed per trace T5.3."""
    payload = valid_cascade_resolver_payload_dict(level_used=1)
    with self.assertRaises(ValidationError) as ctx:
      CascadeResolverPayloadContract.model_validate(payload)
    self.assertIn("naics_level_used", str(ctx.exception))

  def test_fallback_chain_attempted_optional_default_empty(self) -> None:
    """F4 (a): fallback_chain_attempted Optional with empty-list
    default."""
    payload = valid_cascade_resolver_payload_dict()
    del payload["fallback_chain_attempted"]
    contract = CascadeResolverPayloadContract.model_validate(payload)
    self.assertEqual(contract.fallback_chain_attempted, [])


# ---------------------------------------------------------------------------
# Shape B -- CohortSqlRowContract
# ---------------------------------------------------------------------------

class CohortSqlRowContractTest(unittest.TestCase):
  """F3 + F8 + F13 + F9 + F12 monotonicity invariant."""

  def test_valid_20_field_row_accepted(self) -> None:
    """20 fields total (5 PK + 14 data + 1 auto-stamp) per SQL
    DDL at cohort_bands_table.py:32-58 post-Cleanup-Commit-1.
    R10 closure added cohort_query as the 14th data column."""
    contract = CohortSqlRowContract.model_validate(
      valid_cohort_sql_row_dict()
    )
    self.assertEqual(contract.section, "drivers")
    self.assertEqual(len(CohortSqlRowContract.model_fields), 20)
    self.assertIn("cohort_query", CohortSqlRowContract.model_fields)

  def test_cohort_query_optional_default_none(self) -> None:
    """R10 closure (Cleanup Commit 1): cohort_query Optional
    so legacy rows pre-dating the cleanup (which carry NULL
    in the new column) still validate. PSL2 production-reality-
    wins."""
    payload = valid_cohort_sql_row_dict()
    payload.pop("cohort_query", None)
    contract = CohortSqlRowContract.model_validate(payload)
    self.assertIsNone(contract.cohort_query)

  def test_cohort_query_populated_dict_accepted(self) -> None:
    """R10 closure: post-cleanup rows carry the dict directly
    (deserialized from the JSON column at SELECT time)."""
    contract = CohortSqlRowContract.model_validate(
      valid_cohort_sql_row_dict()
    )
    self.assertIsInstance(contract.cohort_query, dict)
    self.assertEqual(contract.cohort_query.get("naics_prefix"), "722515")

  def test_invalid_section_rejected(self) -> None:
    """F3: Literal of 5 values."""
    payload = valid_cohort_sql_row_dict(section="invalid_section")
    with self.assertRaises(ValidationError) as ctx:
      CohortSqlRowContract.model_validate(payload)
    self.assertIn("section", str(ctx.exception))

  def test_capex_rd_section_accepted(self) -> None:
    """F3 (a): capex_rd allowed (defined-but-not-yet-populated
    per v1 §D-2)."""
    payload = valid_cohort_sql_row_dict(section="capex_rd")
    contract = CohortSqlRowContract.model_validate(payload)
    self.assertEqual(contract.section, "capex_rd")

  def test_payroll_section_accepted(self) -> None:
    """F3 (a): payroll allowed (same as capex_rd)."""
    payload = valid_cohort_sql_row_dict(section="payroll")
    contract = CohortSqlRowContract.model_validate(payload)
    self.assertEqual(contract.section, "payroll")

  def test_invalid_cohort_table_rejected(self) -> None:
    payload = valid_cohort_sql_row_dict()
    payload["cohort_table"] = "snowflake"
    with self.assertRaises(ValidationError):
      CohortSqlRowContract.model_validate(payload)

  def test_benchmark_monotonicity_violation_rejected(self) -> None:
    """F12 (a): min > target is a monotonicity violation."""
    payload = valid_cohort_sql_row_dict(
      benchmark_min=0.50, benchmark_target=0.40, benchmark_max=0.55,
    )
    with self.assertRaises(ValidationError) as ctx:
      CohortSqlRowContract.model_validate(payload)
    self.assertIn("monotonicity", str(ctx.exception))

  def test_benchmark_monotonicity_skipped_when_any_none(self) -> None:
    """F12 (a): invariant only fires when all 3 benchmark values
    non-None. Partial population (cohort with NULL benchmark_min)
    must still validate."""
    payload = valid_cohort_sql_row_dict()
    payload["benchmark_min"] = None
    payload["benchmark_target"] = 0.40
    payload["benchmark_max"] = 0.55
    contract = CohortSqlRowContract.model_validate(payload)
    self.assertIsNone(contract.benchmark_min)

  def test_robust_min_max_optional_absent(self) -> None:
    """F9 (a): robust_min/max Optional -- cohort writes them;
    future cascade fallback wouldn't."""
    payload = valid_cohort_sql_row_dict()
    payload["robust_min"] = None
    payload["robust_max"] = None
    contract = CohortSqlRowContract.model_validate(payload)
    self.assertIsNone(contract.robust_min)


# ---------------------------------------------------------------------------
# Shape C -- GetBandsViewBandContract
# ---------------------------------------------------------------------------

class GetBandsViewBandContractTest(unittest.TestCase):
  """F12 (b) monotonicity carried through + R11 closure
  (Cleanup Commit 1): naics_prefix_used + data_source now
  symmetric with Shape B; 14 fields per band post-cleanup."""

  def test_valid_14_field_band_accepted(self) -> None:
    """R11 closure (Cleanup Commit 1): 14 fields per band per
    cohort_bands_table.py:347-388 (production writer post-
    cleanup). Shape B has 20 fields (incl. cohort_query +
    resolved_at + PK fields); Shape C has 14 + envelope.
    Field difference: 4 PK/metadata hoisted to envelope
    (draft_id, planning_run_id, section, lever_id) +
    resolved_at dropped (server-stamped) + cohort_query
    dropped (R10 closure persists to SQL but isn't surfaced
    in the get_bands view -- query-context data, not band-
    data)."""
    contract = GetBandsViewBandContract.model_validate(
      valid_get_bands_view_band_dict()
    )
    self.assertEqual(contract.metric_key, "gross_margin_percent")
    self.assertEqual(len(GetBandsViewBandContract.model_fields), 14)
    # R11 closure: naics_prefix_used + data_source NOW present
    # on Shape C (asymmetry resolved).
    self.assertIn("naics_prefix_used", GetBandsViewBandContract.model_fields)
    self.assertIn("data_source", GetBandsViewBandContract.model_fields)
    # resolved_at still dropped (server-stamped at SQL insert,
    # not surfaced in the GPT-tool view).
    self.assertNotIn("resolved_at", GetBandsViewBandContract.model_fields)

  def test_naics_prefix_used_optional_default_none(self) -> None:
    """R11 closure: Optional default for legacy in-memory
    views (if any cached) that pre-date Cleanup Commit 1."""
    payload = valid_get_bands_view_band_dict()
    payload.pop("naics_prefix_used", None)
    payload.pop("data_source", None)
    contract = GetBandsViewBandContract.model_validate(payload)
    self.assertIsNone(contract.naics_prefix_used)
    self.assertIsNone(contract.data_source)

  def test_naics_prefix_used_populated_value_accepted(self) -> None:
    """R11 closure: post-cleanup in-memory views carry the 2
    new fields populated from Shape B."""
    contract = GetBandsViewBandContract.model_validate(
      valid_get_bands_view_band_dict()
    )
    self.assertEqual(contract.naics_prefix_used, "722515")
    self.assertEqual(contract.data_source, "industry_metrics_alpha")

  def test_benchmark_monotonicity_violation_rejected(self) -> None:
    """F12 (b): same invariant as Shape B."""
    payload = valid_get_bands_view_band_dict(
      benchmark_min=0.60, benchmark_target=0.40, benchmark_max=0.55,
    )
    with self.assertRaises(ValidationError) as ctx:
      GetBandsViewBandContract.model_validate(payload)
    self.assertIn("monotonicity", str(ctx.exception))


# ---------------------------------------------------------------------------
# Shape C envelope -- GetBandsViewContract
# ---------------------------------------------------------------------------

class GetBandsViewContractTest(unittest.TestCase):

  def test_valid_envelope_with_bands_accepted(self) -> None:
    contract = GetBandsViewContract.model_validate(valid_get_bands_view_dict())
    self.assertEqual(contract.section, "drivers")
    self.assertEqual(contract.count, 2)
    self.assertEqual(len(contract.bands), 2)

  def test_empty_bands_dict_allowed(self) -> None:
    """Per v1 §D-2: capex_rd + payroll sections defined-but-not-
    yet-populated. get_bands(section='payroll') returns
    {count: 0, bands: {}} -- the contract permits empty."""
    payload = valid_get_bands_view_dict(section="payroll", lever_ids=[])
    contract = GetBandsViewContract.model_validate(payload)
    self.assertEqual(contract.count, 0)
    self.assertEqual(contract.bands, {})

  def test_invalid_section_rejected(self) -> None:
    payload = valid_get_bands_view_dict(section="drivers")
    payload["section"] = "made_up_section"
    with self.assertRaises(ValidationError):
      GetBandsViewContract.model_validate(payload)


# ---------------------------------------------------------------------------
# Shape D -- PopulationSummaryContract
# ---------------------------------------------------------------------------

class PopulationSummaryContractTest(unittest.TestCase):
  """F3 5-section enumeration + F10 cross-field invariant."""

  def test_valid_3_section_payload_accepted(self) -> None:
    """Defaults populate drivers + balance_sheet + stage_ramp
    (3 sections); capex_rd + payroll absent per v1 §D-2."""
    contract = PopulationSummaryContract.model_validate(
      valid_population_summary_dict()
    )
    self.assertIsNotNone(contract.drivers)
    self.assertIsNotNone(contract.balance_sheet)
    self.assertIsNone(contract.capex_rd)

  def test_all_5_sections_present_accepted(self) -> None:
    """F3 (a): all 5 sections (incl. capex_rd + payroll)
    permitted when populator extends coverage."""
    contract = PopulationSummaryContract.model_validate(
      valid_population_summary_dict(
        include_capex_rd=True, include_payroll=True,
      )
    )
    self.assertIsNotNone(contract.capex_rd)
    self.assertIsNotNone(contract.payroll)

  def test_zero_resolved_total_rejected_f10(self) -> None:
    """F10: total resolved across all 5 sections must be >= 1.
    Closes v1 §F-2 FAIL_COHORT_BANDS_MISSING precondition."""
    payload = {
      "drivers": valid_population_summary_section_dict(resolved=0, skipped=3),
      "balance_sheet": valid_population_summary_section_dict(resolved=0, skipped=2),
    }
    with self.assertRaises(ValidationError) as ctx:
      PopulationSummaryContract.model_validate(payload)
    self.assertIn("zero resolved", str(ctx.exception))

  def test_single_resolved_anywhere_accepted_f10(self) -> None:
    """F10: even a single resolved band anywhere satisfies the
    invariant. The precondition is downstream readability, not
    statistical adequacy."""
    payload = {
      "drivers": valid_population_summary_section_dict(resolved=1, skipped=0),
    }
    contract = PopulationSummaryContract.model_validate(payload)
    self.assertEqual(contract.drivers.resolved, 1)

  def test_all_sections_absent_rejected_f10(self) -> None:
    """F10: zero sections present means zero resolved -- same
    failure mode."""
    with self.assertRaises(ValidationError) as ctx:
      PopulationSummaryContract.model_validate({})
    self.assertIn("zero resolved", str(ctx.exception))


# ---------------------------------------------------------------------------
# Vocabulary constants alignment (Contract 1 typo-lock pattern)
# ---------------------------------------------------------------------------

class LiteralVocabularyConstantsTest(unittest.TestCase):
  """Pin the module-level constants against the Literal sets so
  drift between docs/announcements and contract enforcement
  fails fast."""

  def test_supported_naics_levels_matches(self) -> None:
    self.assertEqual(SUPPORTED_NAICS_LEVELS, (6, 5, 4, 3, 2, 0))

  def test_supported_confidence_tiers_matches(self) -> None:
    self.assertEqual(
      SUPPORTED_CONFIDENCE_TIERS,
      ("high", "medium", "low", "generic_default"),
    )

  def test_supported_trust_flags_matches(self) -> None:
    self.assertEqual(
      SUPPORTED_TRUST_FLAGS,
      (
        "naics_6_direct", "naics_5_fallback", "naics_4_fallback",
        "naics_3_fallback", "naics_2_fallback", "no_coverage",
      ),
    )

  def test_supported_sections_matches(self) -> None:
    self.assertEqual(
      SUPPORTED_SECTIONS,
      ("drivers", "balance_sheet", "stage_ramp", "capex_rd", "payroll"),
    )

  def test_supported_cohort_tables_matches(self) -> None:
    self.assertEqual(SUPPORTED_COHORT_TABLES, ("edgar", "alpha"))


# ---------------------------------------------------------------------------
# Sub-contract extra='ignore' policy (F18)
# ---------------------------------------------------------------------------

class ExtraPolicyTest(unittest.TestCase):
  """F18: sub-contracts use extra='ignore' so producer-emitted
  unmodeled keys don't break validation."""

  def test_cascade_payload_extra_ignored(self) -> None:
    payload = valid_cascade_resolver_payload_dict()
    payload["unmodeled_future_field"] = "anything"
    contract = CascadeResolverPayloadContract.model_validate(payload)
    self.assertFalse(hasattr(contract, "unmodeled_future_field"))

  def test_cohort_sql_row_extra_ignored(self) -> None:
    payload = valid_cohort_sql_row_dict()
    payload["unmodeled_sql_column"] = 42
    contract = CohortSqlRowContract.model_validate(payload)
    self.assertFalse(hasattr(contract, "unmodeled_sql_column"))

  def test_population_summary_section_extra_ignored(self) -> None:
    payload = valid_population_summary_section_dict()
    payload["unmodeled_counter"] = 100
    contract = PopulationSummarySectionContract.model_validate(payload)
    self.assertFalse(hasattr(contract, "unmodeled_counter"))


if __name__ == "__main__":
  unittest.main()
