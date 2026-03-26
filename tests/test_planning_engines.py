from __future__ import annotations

import json
import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = ROOT / "python"
CLIENT_DIR = PYTHON_DIR / "client_intake_and_finmo"
for path in (str(PYTHON_DIR), str(CLIENT_DIR)):
  if path not in sys.path:
    sys.path.insert(0, path)


from benchmark_resolver import resolve_alpha_benchmark_payload  # type: ignore  # noqa: E402
from consistency_financials import (  # type: ignore  # noqa: E402
  build_consistency_financial_summary,
  build_consistency_financial_table,
)
from consistency_solver import (  # type: ignore  # noqa: E402
  _apply_exact_patches,
  _archetype_consistency,
  _build_client_scenario_output,
  _build_profile_solver_contract,
  _derive_commercial_archetype,
  _derive_scenario_posture,
  _build_lever_summary,
  _build_direct_solver_inputs,
  _build_solver_state_model,
  _build_scenario_forecast_bundle,
  _exact_patches_from_solution,
  _label_and_rationale_from_patches,
  _presentation_issues,
  _normalize_ratio,
  _safe_float,
  _select_client_ready_scenarios,
  _select_materially_distinct_scenarios,
  _solver_required,
  _solve_direct_profile,
  _solver_profiles,
  _sync_marketing_derived_fields,
  apply_consistency_solver_choice,
  build_consistency_solver_state,
)
from solver_trace import configure_solver_trace_run, reset_solver_trace_stage, trace, trace_lazy  # type: ignore  # noqa: E402
from constraint_engine import build_constraint_engine_bundle  # type: ignore  # noqa: E402
from constraint_traits import extract_normalized_traits, resolve_business_classification  # type: ignore  # noqa: E402
from convergence_policy import build_convergence_policy  # type: ignore  # noqa: E402
from forecast_engine import build_forecast_engine_bundle  # type: ignore  # noqa: E402
from financials_year1 import (  # type: ignore  # noqa: E402
  apply_revenue_driver_patch,
  assemble_financials_year1,
  build_revenue_driver_signature,
  build_revenue_math_line,
)
from api_handlers.intake_consult import (  # type: ignore  # noqa: E402
  _advance_persisted_financials_stage,
  _apply_capacity_target_value,
  _build_consistency_modified_plan_payload,
  _build_violation_resolution_summary,
  _build_consistency_finalized_message,
  _build_capacity_target_question,
  _financials_ready_for_consistency,
  _financials_stage_is_controller_owned,
  _maybe_run_consistency_closeout,
  _maybe_handle_financials_generic_patch_turn,
  _find_missing_capacity_target,
  _run_consistency_closeout,
  _serialize_debug_draft_row,
)
from intake_consult_draft import (  # type: ignore  # noqa: E402
  append_messages,
  _consistency_completion_requested,
  _is_valid_consistency_modified_plan_payload,
)
from consistency_strategy_advisor import _openai_model as _strategy_advisor_openai_model  # type: ignore  # noqa: E402


class PlanningEnginesTests(unittest.TestCase):
  def test_strategy_advisor_uses_same_default_model_as_rest_of_app(self) -> None:
    with patch.dict("os.environ", {}, clear=True):
      self.assertEqual(_strategy_advisor_openai_model(), "gpt-5.1")

  def _benchmark_payload(
    self,
    *,
    fallback_level: str = "naics_6",
    confidence_score: float = 0.85,
    gross_margin_min: float = 0.5,
    gross_margin_max: float = 0.65,
    ebitda_margin_min: float = 0.05,
    ebitda_margin_max: float = 0.18,
    payroll_min: float = 0.18,
    payroll_max: float = 0.35,
    opex_min: float = 0.08,
    opex_max: float = 0.18,
    inventory_min: float = 0.0,
    inventory_max: float = 10.0,
  ) -> dict:
    return {
      "fallback_level": fallback_level,
      "confidence_score": confidence_score,
      "revenue_growth_path": [0.03, 0.025, 0.02, 0.02],
      "gross_margin_band": {"min": gross_margin_min, "max": gross_margin_max},
      "ebitda_margin_band": {"min": ebitda_margin_min, "max": ebitda_margin_max},
      "payroll_intensity": {"min": payroll_min, "max": payroll_max},
      "opex_intensity": {"min": opex_min, "max": opex_max},
      "capex_percent_revenue": {"min": 0.02, "max": 0.04},
      "depreciation_percent_revenue": {"min": 0.01, "max": 0.02},
      "working_capital": {
        "dso": {"min": 20, "max": 35},
        "dpo": {"min": 15, "max": 30},
        "inventory_days": {"min": inventory_min, "max": inventory_max},
      },
    }

  def _run_solver_case(
    self,
    *,
    ops_json: dict,
    people_json: dict,
    financials_json: dict,
    financials_year1_json: dict,
    marketing_model_json: dict,
    normalized_traits: dict,
    benchmark_payload: dict,
    constraint_engine_state: dict,
  ) -> dict:
    with patch("consistency_solver._gpt_strategy_required", return_value=False):
      solver_state = build_consistency_solver_state(
        ops_json=ops_json,
        people_json=people_json,
        financials_json=financials_json,
        financials_year1_json=financials_year1_json,
        marketing_model_json=marketing_model_json,
        normalized_traits=normalized_traits,
        benchmark_payload=benchmark_payload,
        constraint_engine_state=constraint_engine_state,
      )
    self.assertIsNotNone(solver_state)
    return solver_state or {}

  def test_consistency_financial_summary_prefers_controller_current_payroll(self) -> None:
    summary = build_consistency_financial_summary(
      financials_json={
        "current_payroll": 286940,
        "payroll_total_year1": 363772.5,
        "cogs_total_year1": 15750,
        "marketing_total_year1": 42000,
        "other_operating_expense": 1200,
        "monthly_rent_expense": 2000,
      },
      financials_year1_json={"company_revenue_total_year1": 262500},
    )

    self.assertEqual(summary["payroll"], 286940)
    self.assertAlmostEqual(summary["ebitda"], 262500 - 15750 - 286940 - 42000 - 25200)

  def test_constraint_engine_does_not_force_unfunded_inferred_roles_into_year1_floor(self) -> None:
    bundle = build_constraint_engine_bundle(
      shared_context={
        "operating_model": {
          "business_type": "Professional service",
          "capacity_driver": "labor",
          "sales_modality": "project_based",
          "customer_type": "b2b",
          "business_stage": "operating",
        },
        "people_capability": {
          "people": [
            {"full_name": "Partner A", "annual_wage": 60000},
            {"full_name": "Partner B", "annual_wage": 60000},
          ],
          "inferred_roles": [
            {"role_title": "Paralegal", "annual_wage": 60000, "months_until_hire": 6},
          ],
        },
        "financials": {
          "current_payroll": 120000,
          "payroll_total_year1": 120000,
          "cogs_total_year1": 12000,
          "marketing_total_year1": 6000,
          "other_operating_expense": 12000,
        },
      },
      operating_model_json={
        "business_type": "Professional service",
        "capacity_driver": "labor",
        "sales_modality": "project_based",
        "customer_type": "b2b",
        "business_stage": "operating",
      },
      people_json={
        "people": [
          {"full_name": "Partner A", "annual_wage": 60000},
          {"full_name": "Partner B", "annual_wage": 60000},
        ],
        "inferred_roles": [
          {"role_title": "Paralegal", "annual_wage": 60000, "months_until_hire": 6},
        ],
      },
      financials_json={
        "current_payroll": 120000,
        "payroll_total_year1": 120000,
        "cogs_total_year1": 12000,
        "marketing_total_year1": 6000,
        "other_operating_expense": 12000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 120000,
        "unit_price": 100,
        "utilization_rate": 0.666667,
        "avg_units_per_period_year1": 100,
        "operating_periods_per_year": 12,
        "units_per_period_capacity": 150,
      },
    )

    metrics = bundle["constraint_engine_state"]["current_metrics"]
    self.assertAlmostEqual(metrics["people_payroll_floor"], 120000, delta=1.0)
    self.assertAlmostEqual(metrics["structural_payroll_floor"], 120000, delta=1.0)
    self.assertAlmostEqual(metrics["baseline_adjustable_active_months"], 0.0, delta=0.01)

  def test_extract_normalized_traits_is_deterministic(self) -> None:
    traits = extract_normalized_traits(
      operating_model={
        "business_naics_6": "541611",
        "consumer_type": "B2B",
        "sales_modality": "online platform",
        "capacity_driver": "software automation",
        "unit_cadence": "monthly subscription",
        "geographic_scope": "national",
        "business_stage": "operating",
        "shipping_method": "digital delivery",
      },
      target_market={"consumer_type": "b2b"},
      fulfillment_json={"personnel": "platform", "time": "remote same day"},
    )

    self.assertEqual(traits["naics_6"], "541611")
    self.assertEqual(traits["customer_type"], "b2b")
    self.assertEqual(traits["sales_modality"], "online")
    self.assertEqual(traits["capacity_driver"], "system")
    self.assertEqual(traits["unit_cadence"], "recurring")
    self.assertEqual(traits["geographic_scope"], "national")
    self.assertEqual(traits["business_stage"], "operating")
    self.assertEqual(traits["fulfillment_shape"], "digital_remote")
    self.assertEqual(traits["classification_source"], "persisted_business_type")

  def test_phase0_resolve_business_classification_uses_persisted_business_type_and_naics(self) -> None:
    mapping = resolve_business_classification(
      operating_model={"business_naics_6": "541110", "business_type": "Law Firm"},
      conn=object(),
    )

    self.assertEqual(
      mapping,
      {
        "naics_6": "541110",
        "business_type": "Law Firm",
        "source": "persisted_business_type",
      },
    )

  def test_phase0_resolve_business_classification_returns_none_without_persisted_values(self) -> None:
    mapping = resolve_business_classification(
      operating_model={},
      conn=object(),
    )

    self.assertEqual(
      mapping,
      {
        "naics_6": None,
        "business_type": None,
        "source": "none",
      },
    )

  @patch("constraint_traits.resolve_business_classification")
  def test_phase0_extract_traits_uses_persisted_business_type_and_naics(
    self,
    mock_mapping,
  ) -> None:
    mock_mapping.return_value = {
      "naics_6": "541110",
      "business_type": "Law Firm",
      "source": "persisted_business_type",
    }

    traits = extract_normalized_traits(
      operating_model={
        "business_naics_6": "541110",
        "business_type": "Law Firm",
        "consumer_type": "B2B",
        "sales_modality": "local service",
        "capacity_driver": "labor",
        "geographic_scope": "local",
        "business_stage": "operating",
      },
      conn=object(),
    )

    self.assertEqual(traits["naics_6"], "541110")
    self.assertEqual(traits["business_type"], "Law Firm")
    self.assertIsNone(traits["industry"])
    self.assertIsNone(traits["sector"])
    self.assertEqual(traits["classification_source"], "persisted_business_type")

  @patch("benchmark_resolver._fetch_growth_rows")
  @patch("benchmark_resolver._fetch_sector_rows")
  def test_benchmark_resolver_falls_back_to_trait_based_sector(
    self,
    mock_sector_rows,
    mock_growth_rows,
  ) -> None:
    mock_growth_rows.return_value = []
    mock_sector_rows.return_value = (
      [
        {
          "gross_margin_q": 0.48,
          "ebitda_margin_q": 0.14,
          "sga_percent": 0.16,
          "rnd_percent": 0.02,
          "capex_percent_revenue": 0.03,
          "depreciation_percent_revenue": 0.015,
          "dso": 28,
          "dpo": 21,
          "inventory_days": 12,
        },
        {
          "gross_margin_q": 0.52,
          "ebitda_margin_q": 0.18,
          "sga_percent": 0.14,
          "rnd_percent": 0.01,
          "capex_percent_revenue": 0.025,
          "depreciation_percent_revenue": 0.014,
          "dso": 31,
          "dpo": 24,
          "inventory_days": 10,
        },
      ],
      [
        {"fiscalDateEnding": "2025-09-30", "revenue_growth_q": 0.03},
        {"fiscalDateEnding": "2025-12-31", "revenue_growth_q": 0.025},
      ],
      "2025-12-31",
    )

    payload = resolve_alpha_benchmark_payload(
      normalized_traits={"sector": "Technology Services"},
      conn=object(),
    )

    self.assertEqual(payload["fallback_level"], "trait_based")
    self.assertEqual(payload["fallback_source"], "sector:Technology Services")
    self.assertGreater(payload["confidence_score"], 0.0)
    self.assertEqual(len(payload["revenue_growth_path"]), 2)

  def test_consistency_summary_uses_year1_fallback_totals(self) -> None:
    summary = build_consistency_financial_summary(
      financials_json={"monthly_rent_expense": 1000, "annual_interest_payment": 5000},
      financials_year1_json={
        "company_revenue_total_year1": 240000,
        "company_cogs_total_year1": 96000,
        "company_payroll_total_year1": 72000,
        "company_marketing_total_year1": 12000,
        "other_operating_expense_total_year1": 18000,
      },
    )

    self.assertEqual(summary["revenue"], 240000.0)
    self.assertEqual(summary["cogs"], 96000.0)
    self.assertEqual(summary["payroll"], 72000.0)
    self.assertEqual(summary["marketing"], 12000.0)
    self.assertEqual(summary["other_opex_non_rent"], 18000.0)
    self.assertEqual(summary["rent_annualized"], 12000.0)

  def test_consistency_table_includes_quarterly_ebitda_forecast(self) -> None:
    summary = {
      "revenue": 240000,
      "cogs": 96000,
      "gross_profit": 144000,
      "payroll": 72000,
      "marketing": 12000,
      "other_opex": 30000,
      "ebitda": 30000,
      "interest": 5000,
      "taxes": 0,
      "net_income": 25000,
    }
    forecast_quarters = [{"quarter_index": i + 1, "ebitda": 10000 + (i * 250)} for i in range(20)]

    markdown = build_consistency_financial_table(summary, forecast_quarters=forecast_quarters)

    self.assertIn("Quarterly EBITDA Forecast", markdown)
    self.assertIn("| Year 5 |", markdown)
    self.assertIn("$10,000", markdown)

  @patch("constraint_engine.extract_normalized_traits")
  @patch("constraint_engine.resolve_alpha_benchmark_payload")
  def test_constraint_engine_flags_high_and_low_ebitda(
    self,
    mock_benchmark,
    mock_traits,
  ) -> None:
    mock_traits.return_value = {
      "naics_6": "541611",
      "sector": "Technology Services",
      "customer_type": "b2b",
      "sales_modality": "project_based",
      "capacity_driver": "labor",
      "unit_cadence": "contract",
      "geographic_scope": "national",
      "business_stage": "operating",
      "fulfillment_shape": "digital_remote",
    }
    mock_benchmark.return_value = {
      "fallback_level": "naics_6",
      "confidence_score": 0.9,
      "gross_margin_band": {"min": 0.45, "max": 0.60},
      "ebitda_margin_band": {"min": 0.08, "max": 0.18},
      "payroll_intensity": {"min": 0.18, "max": 0.35},
      "opex_intensity": {"min": 0.08, "max": 0.20},
      "working_capital": {
        "dso": {"min": 20, "max": 40},
        "dpo": {"min": 15, "max": 30},
        "inventory_days": {"min": 0, "max": 5},
      },
    }

    low_bundle = build_constraint_engine_bundle(
      operating_model_json={"unit_price": 100, "utilization_rate": 0.6, "capacity_driver": "labor"},
      financials_json={
        "cogs_total_year1": 30000,
        "payroll_total_year1": 50000,
        "marketing_total_year1": 15000,
        "other_operating_expense": 20000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 100000,
        "unit_price": 100,
        "avg_units_per_week_year1": 20,
        "operating_weeks_per_year": 52,
        "utilization_rate": 0.6,
      },
      marketing_model_json={"expected_units_year1": 1040},
    )
    high_bundle = build_constraint_engine_bundle(
      operating_model_json={"unit_price": 100, "utilization_rate": 0.6, "capacity_driver": "labor"},
      financials_json={
        "cogs_total_year1": 10000,
        "payroll_total_year1": 5000,
        "marketing_total_year1": 0,
        "other_operating_expense": 5000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 100000,
        "unit_price": 100,
        "avg_units_per_week_year1": 20,
        "operating_weeks_per_year": 52,
        "utilization_rate": 0.6,
      },
      marketing_model_json={"expected_units_year1": 1040},
    )

    self.assertIn("ebitda_margin_too_low", low_bundle["constraint_engine_state"]["violations"])
    self.assertIn("ebitda_margin_too_high", high_bundle["constraint_engine_state"]["violations"])

  def test_solver_always_required_for_reality_governance(self) -> None:
    required = _solver_required(
      {
        "revenue": 100000,
        "ebitda": 45000,
        "net_income": 40000,
      },
      constraint_engine_state={
        "violations": ["ebitda_margin_too_high"],
        "soft_violation_codes": ["ebitda_margin_too_high"],
      },
    )

    self.assertTrue(required)

  def test_solver_state_runs_for_soft_ebitda_only_case(self) -> None:
    solver_state = build_consistency_solver_state(
      ops_json={"capacity_driver": "space", "sales_modality": "retail"},
      people_json={
        "people": [{"full_name": "Owner", "role_title": "Manager", "annual_wage": 70000}],
        "inferred_roles": [{"role_title": "Cashier", "annual_wage": 35000, "months_until_hire": 4}],
      },
      financials_json={
        "cogs_total_year1": 430000,
        "payroll_total_year1": 70000,
        "marketing_total_year1": 18000,
        "other_operating_expense": 90000,
      },
      financials_year1_json={
        "lobs": [
          {
            "lob_name": "Store",
            "products": [
              {
                "product_name": "Prepared Meals",
                "unit_price": 14,
                "units_per_period_capacity": 900,
                "avg_units_per_period_year1": 720,
                "operating_periods_per_year": 52,
                "utilization_rate": 0.8,
              },
              {
                "product_name": "Catering Trays",
                "unit_price": 90,
                "units_per_period_capacity": 40,
                "avg_units_per_period_year1": 22,
                "operating_periods_per_year": 52,
                "utilization_rate": 0.55,
              },
            ],
          }
        ],
        "company_revenue_total_year1": 627120,
      },
      marketing_model_json={"expected_units_year1": 38584, "reachable_market": 250000},
      normalized_traits={
        "business_stage": "operating",
        "capacity_driver": "space",
        "sales_modality": "retail",
      },
      benchmark_payload=self._benchmark_payload(
        gross_margin_min=0.34,
        gross_margin_max=0.45,
        ebitda_margin_min=0.03,
        ebitda_margin_max=0.10,
        payroll_min=0.10,
        payroll_max=0.18,
        opex_min=0.08,
        opex_max=0.16,
        inventory_min=18.0,
        inventory_max=40.0,
      ),
      constraint_engine_state={
        "violations": ["ebitda_margin_too_low"],
        "soft_violation_codes": ["ebitda_margin_too_low"],
        "constraint_confidence_score": 0.85,
        "fallback_level": "naics_6",
        "supportable_unit_range": {"min": 30000, "max": 45000},
        "supportable_revenue_range": {"min": 560000, "max": 700000},
        "utilization_range": {"min": 0.55, "max": 0.85},
        "gross_margin_band": {"min": 0.34, "max": 0.45},
        "ebitda_margin_band": {"min": 0.03, "max": 0.10},
        "payroll_intensity_band": {"min": 0.10, "max": 0.18},
        "opex_intensity_band": {"min": 0.08, "max": 0.16},
        "marketing_intensity_band": {"min": 0.01, "max": 0.04},
        "current_metrics": {"capacity_units_year1": 50000.0},
      },
    )

    self.assertIsNotNone(solver_state)
    self.assertIsInstance(solver_state, dict)
    self.assertIn((solver_state or {}).get("status"), {"awaiting_choice", "blocking_unresolved"})

  def test_solver_enters_minimal_viability_mode_for_structurally_valid_loss(self) -> None:
    solver_state = build_consistency_solver_state(
      ops_json={
        "unit_price": 100,
        "utilization_rate": 0.6,
        "capacity_driver": "labor",
        "sales_modality": "local_service",
      },
      people_json={
        "people": [{"full_name": "Owner", "role_title": "Trainer", "annual_wage": 100000}],
        "inferred_roles": [{"role_title": "Front Desk", "annual_wage": 36000, "months_until_hire": 6}],
      },
      financials_json={
        "cogs_total_year1": 90000,
        "payroll_total_year1": 100000,
        "marketing_total_year1": 10000,
        "other_operating_expense": 120000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 300000,
        "unit_price": 100,
        "utilization_rate": 0.6,
        "avg_units_per_period_year1": 57.6923,
        "operating_periods_per_year": 52,
      },
      marketing_model_json={"expected_units_year1": 3000, "reachable_market": 20000},
      normalized_traits={
        "business_stage": "operating",
        "capacity_driver": "labor",
        "sales_modality": "local_service",
        "customer_type": "b2b",
        "unit_cadence": "weekly",
      },
      benchmark_payload=self._benchmark_payload(
        gross_margin_min=0.52,
        gross_margin_max=0.75,
        ebitda_margin_min=0.06,
        ebitda_margin_max=0.18,
        payroll_min=0.2,
        payroll_max=0.4,
        opex_min=0.08,
        opex_max=0.2,
      ),
      constraint_engine_state={
        "violations": ["ebitda_margin_too_low", "opex_too_high"],
        "soft_violation_codes": ["ebitda_margin_too_low", "opex_too_high"],
        "constraint_confidence_score": 0.85,
        "fallback_level": "naics_6",
        "supportable_unit_range": {"min": 2600, "max": 3600},
        "supportable_revenue_range": {"min": 260000, "max": 360000},
        "utilization_range": {"min": 0.5, "max": 0.8},
        "gross_margin_band": {"min": 0.52, "max": 0.75},
        "ebitda_margin_band": {"min": 0.06, "max": 0.18},
        "payroll_intensity_band": {"min": 0.2, "max": 0.4},
        "opex_intensity_band": {"min": 0.08, "max": 0.2},
        "marketing_intensity_band": {"min": 0.01, "max": 0.05},
        "current_metrics": {
          "capacity_units_year1": 4200.0,
          "people_payroll_floor": 100000.0,
          "structural_payroll_floor": 95000.0,
          "active_role_months_year1": 15.0,
          "fte_equivalent_year1": 1.25,
          "required_fte_from_workload": 1.1,
        },
      },
    )

    self.assertIsNotNone(solver_state)
    self.assertEqual((solver_state or {}).get("status"), "awaiting_choice")
    self.assertEqual((solver_state or {}).get("selected_target_label"), "minimal_viability_adjustment")
    scenarios = (solver_state or {}).get("scenarios") or []
    self.assertTrue(scenarios)

    viability_scenario = next(
      (
        scenario for scenario in scenarios
        if isinstance(scenario, dict) and scenario.get("solution_profile_id") == "viability_stabilize"
      ),
      None,
    )
    self.assertIsNotNone(viability_scenario)
    exact_patches = (viability_scenario or {}).get("exact_patches") or {}
    year1_patch = exact_patches.get("financials_year1_patch") if isinstance(exact_patches, dict) else {}
    financials_patch = exact_patches.get("financials_patch") if isinstance(exact_patches, dict) else {}
    marketing_patch = exact_patches.get("marketing_model_patch") if isinstance(exact_patches, dict) else {}
    role_updates = exact_patches.get("people_role_updates") if isinstance(exact_patches, dict) else []

    patched_price = _safe_float((year1_patch or {}).get("unit_price"))
    if patched_price > 0:
      self.assertLessEqual(patched_price, 115.0)
      self.assertGreaterEqual(patched_price, 100.0)

    expected_units = _safe_float((marketing_patch or {}).get("expected_units_year1"))
    if expected_units > 0:
      self.assertLessEqual(expected_units, 3000.0)

    patched_other_opex = _safe_float((financials_patch or {}).get("other_operating_expense"))
    if patched_other_opex > 0:
      self.assertGreaterEqual(patched_other_opex, 114000.0)

    patched_cogs = _safe_float((financials_patch or {}).get("cogs_total_year1"))
    if patched_cogs > 0:
      self.assertGreaterEqual(patched_cogs, 87300.0)

    for update in role_updates or []:
      self.assertLessEqual(_safe_float((update or {}).get("months_until_hire")), 9.0)

  def test_solver_strategy_layer_drives_allowed_scenarios(self) -> None:
    solver_state = build_consistency_solver_state(
      ops_json={
        "unit_price": 40,
        "utilization_rate": 0.5,
        "capacity_driver": "system",
        "sales_modality": "online",
      },
      people_json={
        "people": [{"full_name": "Founder", "role_title": "Operator", "annual_wage": 60000}],
        "inferred_roles": [{"role_title": "Support", "annual_wage": 48000, "months_until_hire": 6}],
      },
      financials_json={
        "cogs_total_year1": 140000,
        "payroll_total_year1": 60000,
        "marketing_total_year1": 30000,
        "other_operating_expense": 50000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 400000,
        "unit_price": 40,
        "utilization_rate": 0.5,
        "avg_units_per_period_year1": 833.3333,
        "operating_periods_per_year": 12,
      },
      marketing_model_json={"expected_units_year1": 10000, "reachable_market": 300000},
      normalized_traits={
        "business_stage": "operating",
        "capacity_driver": "system",
        "sales_modality": "online",
        "customer_type": "b2c",
        "unit_cadence": "subscription",
      },
      benchmark_payload=self._benchmark_payload(
        gross_margin_min=0.45,
        gross_margin_max=0.7,
        ebitda_margin_min=0.04,
        ebitda_margin_max=0.16,
        payroll_min=0.12,
        payroll_max=0.26,
        opex_min=0.08,
        opex_max=0.18,
      ),
      constraint_engine_state={
        "violations": ["payroll_too_light", "ebitda_margin_too_low"],
        "hard_violation_codes": ["payroll_too_light"],
        "soft_violation_codes": ["ebitda_margin_too_low"],
        "constraint_confidence_score": 0.82,
        "fallback_level": "naics_6",
        "supportable_unit_range": {"min": 9000, "max": 18000},
        "supportable_revenue_range": {"min": 360000, "max": 720000},
        "utilization_range": {"min": 0.45, "max": 0.88},
        "gross_margin_band": {"min": 0.45, "max": 0.7},
        "ebitda_margin_band": {"min": 0.04, "max": 0.16},
        "payroll_intensity_band": {"min": 0.12, "max": 0.26},
        "opex_intensity_band": {"min": 0.08, "max": 0.18},
        "marketing_intensity_band": {"min": 0.04, "max": 0.18},
        "current_metrics": {
          "capacity_units_year1": 22000.0,
          "people_payroll_floor": 60000.0,
          "structural_payroll_floor": 85000.0,
          "active_role_months_year1": 18.0,
          "fte_equivalent_year1": 1.5,
          "required_fte_from_workload": 1.8,
        },
      },
    )

    self.assertIsNotNone(solver_state)
    state_model = (solver_state or {}).get("state_model") or {}
    strategy_layer = state_model.get("strategy_layer") or {}
    self.assertEqual(strategy_layer.get("source"), "deterministic")
    diagnosis = strategy_layer.get("diagnosis") or {}
    self.assertEqual(diagnosis.get("primary_cause"), "payroll-driven")
    strategy_ids = [str(item.get("strategy_id") or "") for item in (strategy_layer.get("strategies") or []) if isinstance(item, dict)]
    self.assertIn("staffing_ramp_adjustment", strategy_ids)
    self.assertLessEqual(len(strategy_ids), 2)
    self.assertIn(strategy_ids[0], (diagnosis.get("preferred_strategy_ids") or []))

    scenarios = (solver_state or {}).get("scenarios") or []
    self.assertTrue(scenarios)
    for scenario in scenarios:
      self.assertIn(str((scenario or {}).get("strategy_id") or ""), strategy_ids)
      self.assertTrue((scenario or {}).get("strategy_name"))
      self.assertIsInstance((scenario or {}).get("allowed_levers"), list)
      self.assertIsInstance((scenario or {}).get("relationship_rules"), list)

  def test_gpt_strategy_layer_can_override_selected_strategies(self) -> None:
    with patch(
      "consistency_solver._gpt_strategy_selection",
      return_value={
        "primary_cause": "pricing-driven",
        "secondary_causes": ["utilization-driven"],
        "reason": "Price realization is the cleanest repair lever for this case.",
        "business_model_assessment": "This is a digitally delivered business with room for modest price improvement, but demand should soften if price moves too far.",
        "severity_class": "mild",
        "severity_reason": "Margins are weak but not structurally catastrophic for this model.",
        "minimum_package_strength": "moderate",
        "required_lever_families": ["price_up", "util_down"],
        "forbidden_lever_families": ["payroll_down"],
        "controller_directives": {
          "minimum_meaningful_levers": 2,
          "require_multi_lever_coordination": True,
          "preserve_capacity_staffing_link": True,
          "preserve_price_demand_link": True,
          "preserve_marketing_demand_link": False,
          "prefer_delay_over_delete": True,
          "aggression_level": "moderate",
          "escalate_on_retry": True,
          "minimum_package_count": 1,
        },
        "target_margin_path": {
          "year1_min": -0.01,
          "year1_max": 0.04,
          "year2_min": 0.04,
          "year2_max": 0.10,
          "year3_min": 0.10,
          "year3_max": 0.18,
        },
        "target_posture": {
          "year1_ebitda_posture": "near_break_even",
          "year2_ebitda_posture": "modestly_positive",
          "year3_ebitda_posture": "stable_positive",
          "staffing_posture": "measured",
          "pricing_posture": "disciplined",
          "demand_posture": "slightly_softened",
          "cost_posture": "controlled",
        },
        "coordinated_lever_packages": [
              {
                "quarter_start": 1,
                "quarter_end": 8,
                "levers": ["price_up", "util_down"],
                "expected_effects": ["demand_softens_with_price"],
                "minimum_strength": "moderate",
                "rationale": "Early pricing improvements should be paired with a modest demand softening assumption.",
              }
            ],
        "selected_strategy_ids": ["pricing_adjustment"],
        "strategy_overrides": [
          {
            "strategy_id": "pricing_adjustment",
            "allowed_levers": ["price_up", "util_down", "hire_delay"],
            "constraints": {
              "price_up_cap_ratio": 0.18,
              "util_down_cap_ratio": 0.12,
              "hire_delay_max_months_total": 24.0,
              "units_min_ratio": 0.9,
            },
            "forecast_orchestration": {
              "orchestration_summary": "Delay non-core growth levers until later years.",
              "quarter_policies": [
                {
                  "quarter_start": 1,
                  "quarter_end": 8,
                  "demand_posture": "moderate",
                  "staffing_posture": "hold",
                  "cost_posture": "moderate",
                  "growth_multiplier": 0.9,
                  "convergence_multiplier": 0.85,
                  "price_growth_bias": 0.002,
                  "utilization_target_bias": -0.01,
                  "marketing_ratio_bias": -0.002,
                  "opex_ratio_bias": -0.001,
                  "payroll_ratio_bias": 0.0,
                  "capacity_release_multiplier": 1.0,
                  "active_levers": ["price_up", "hire_delay"],
                }
              ],
              "role_timing_overrides": [],
              "milestone_timing_overrides": [],
              "event_response": {
                "hire_capacity_multiplier": 1.0,
                "hire_growth_bonus_delta": 0.0,
                "marketing_growth_multiplier": 1.0,
                "milestone_capacity_multiplier": 1.0,
                "milestone_growth_multiplier": 1.0,
              },
            },
          }
        ],
        "global_overrides": {
          "price_min_ratio": 0.95,
          "price_max_ratio": 1.22,
          "util_min": 0.56,
          "util_max": 0.88,
          "marketing_up_cap_ratio": 0.14,
          "marketing_down_cap_ratio": 0.08,
          "other_opex_down_cap_ratio": 0.03,
          "other_opex_up_cap_ratio": 0.02,
          "cogs_ratio_min": 0.52,
          "cogs_ratio_max": 0.6,
          "marketing_role": "primary",
          "opex_flexibility": "tight",
        },
        "baseline_forecast_orchestration": {
          "orchestration_summary": "Baseline follows the same delayed-hiring path.",
          "quarter_policies": [
            {
              "quarter_start": 1,
              "quarter_end": 20,
              "demand_posture": "moderate",
              "staffing_posture": "hold",
              "cost_posture": "moderate",
              "growth_multiplier": 0.95,
              "convergence_multiplier": 0.9,
              "price_growth_bias": 0.001,
              "utilization_target_bias": -0.005,
              "marketing_ratio_bias": -0.001,
              "opex_ratio_bias": -0.001,
              "payroll_ratio_bias": 0.0,
              "capacity_release_multiplier": 1.0,
              "active_levers": ["price_up", "hire_delay"],
            }
          ],
          "role_timing_overrides": [],
          "milestone_timing_overrides": [],
          "event_response": {
            "hire_capacity_multiplier": 1.0,
            "hire_growth_bonus_delta": 0.0,
            "marketing_growth_multiplier": 1.0,
            "milestone_capacity_multiplier": 1.0,
            "milestone_growth_multiplier": 1.0,
          },
        },
        "expected_year1_ebitda_margin_min": -0.01,
        "expected_year1_ebitda_margin_max": 0.04,
      },
    ):
      solver_state = build_consistency_solver_state(
        ops_json={
          "unit_price": 120,
          "utilization_rate": 0.62,
          "capacity_driver": "system",
          "sales_modality": "online",
        },
        people_json={
          "people": [{"full_name": "Founder", "role_title": "Owner", "annual_wage": 70000}],
          "inferred_roles": [],
        },
        financials_json={
          "cogs_total_year1": 210000,
          "payroll_total_year1": 70000,
          "marketing_total_year1": 18000,
          "other_operating_expense": 90000,
        },
        financials_year1_json={
          "company_revenue_total_year1": 360000,
          "unit_price": 120,
          "utilization_rate": 0.62,
          "avg_units_per_period_year1": 250.0,
          "operating_periods_per_year": 12,
        },
        marketing_model_json={"expected_units_year1": 3000, "reachable_market": 80000},
        normalized_traits={
          "business_stage": "operating",
          "capacity_driver": "system",
          "sales_modality": "online",
          "customer_type": "b2c",
          "unit_cadence": "monthly",
        },
        benchmark_payload=self._benchmark_payload(
          gross_margin_min=0.45,
          gross_margin_max=0.68,
          ebitda_margin_min=0.04,
          ebitda_margin_max=0.16,
          payroll_min=0.12,
          payroll_max=0.28,
          opex_min=0.08,
          opex_max=0.18,
        ),
        constraint_engine_state={
          "violations": ["gross_margin_too_low", "ebitda_margin_too_low"],
          "soft_violation_codes": ["gross_margin_too_low", "ebitda_margin_too_low"],
          "constraint_confidence_score": 0.84,
          "fallback_level": "naics_6",
          "supportable_unit_range": {"min": 2500, "max": 4200},
          "supportable_revenue_range": {"min": 300000, "max": 520000},
          "utilization_range": {"min": 0.5, "max": 0.82},
          "gross_margin_band": {"min": 0.45, "max": 0.68},
          "ebitda_margin_band": {"min": 0.04, "max": 0.16},
          "payroll_intensity_band": {"min": 0.12, "max": 0.28},
          "opex_intensity_band": {"min": 0.08, "max": 0.18},
          "marketing_intensity_band": {"min": 0.03, "max": 0.12},
          "current_metrics": {
            "capacity_units_year1": 5000.0,
            "people_payroll_floor": 70000.0,
            "structural_payroll_floor": 70000.0,
          },
        },
      )

    self.assertIsNotNone(solver_state)
    state_model = (solver_state or {}).get("state_model") or {}
    strategy_layer = state_model.get("strategy_layer") or {}
    self.assertEqual(strategy_layer.get("source"), "gpt")
    strategies = [item for item in (strategy_layer.get("strategies") or []) if isinstance(item, dict)]
    self.assertEqual([str(item.get("strategy_id") or "") for item in strategies], ["pricing_adjustment"])
    strategy = strategies[0]
    self.assertEqual(strategy.get("allowed_levers"), ["price_up", "util_down", "hire_delay"])
    constraints = strategy.get("constraints") or {}
    self.assertAlmostEqual(_safe_float(constraints.get("price_up_cap_ratio")), 0.18, places=6)
    self.assertAlmostEqual(_safe_float(constraints.get("util_down_cap_ratio")), 0.12, places=6)
    self.assertAlmostEqual(_safe_float(constraints.get("hire_delay_max_months_total")), 24.0, places=6)
    diagnosis = strategy_layer.get("diagnosis") or {}
    self.assertEqual(diagnosis.get("primary_cause"), "pricing-driven")
    self.assertEqual(diagnosis.get("preferred_strategy_ids"), ["pricing_adjustment"])
    self.assertEqual(diagnosis.get("gpt_primary_cause"), "pricing-driven")
    self.assertEqual(diagnosis.get("secondary_causes"), ["utilization-driven"])
    self.assertEqual(diagnosis.get("severity_class"), "mild")
    self.assertEqual(diagnosis.get("minimum_package_strength"), "moderate")
    self.assertEqual(diagnosis.get("required_lever_families"), ["price_up", "util_down"])
    self.assertEqual(diagnosis.get("forbidden_lever_families"), ["payroll_down"])
    self.assertEqual((diagnosis.get("controller_directives") or {}).get("minimum_meaningful_levers"), 2)
    self.assertEqual((diagnosis.get("controller_directives") or {}).get("aggression_level"), "moderate")
    self.assertAlmostEqual(_safe_float((diagnosis.get("target_margin_path") or {}).get("year2_min")), 0.04, places=6)
    self.assertEqual((diagnosis.get("target_posture") or {}).get("year2_ebitda_posture"), "modestly_positive")
    self.assertEqual((diagnosis.get("coordinated_lever_packages") or [])[0]["levers"], ["price_up", "util_down"])
    self.assertAlmostEqual(_safe_float(diagnosis.get("gpt_expected_year1_ebitda_margin_min")), -0.01, places=6)
    self.assertAlmostEqual(_safe_float(diagnosis.get("gpt_expected_year1_ebitda_margin_max")), 0.04, places=6)
    applied = ((strategy_layer.get("strategy_selection") or {}).get("applied_global_overrides") or {})
    self.assertTrue(applied)
    price_envelope = (((solver_state or {}).get("state_model") or {}).get("constraint_profile") or {}).get("price_envelope") or {}
    self.assertAlmostEqual(_safe_float(price_envelope.get("min")), 114.0, places=2)
    self.assertAlmostEqual(_safe_float(price_envelope.get("max")), 146.4, places=2)
    util_envelope = (((solver_state or {}).get("state_model") or {}).get("constraint_profile") or {}).get("utilization_envelope") or {}
    self.assertAlmostEqual(_safe_float(util_envelope.get("min")), 0.56, places=6)
    self.assertAlmostEqual(_safe_float(util_envelope.get("max")), 0.88, places=6)
    commercial_context = (((solver_state or {}).get("state_model") or {}).get("constraint_profile") or {}).get("commercial_context") or {}
    self.assertEqual(commercial_context.get("marketing_role"), "primary")
    self.assertEqual(commercial_context.get("opex_flexibility"), "tight")
    cogs_envelope = (((solver_state or {}).get("state_model") or {}).get("constraint_profile") or {}).get("cogs_envelope") or {}
    self.assertAlmostEqual(_safe_float(cogs_envelope.get("min_ratio")), 0.52, places=6)
    self.assertAlmostEqual(_safe_float(cogs_envelope.get("max_ratio")), 0.6, places=6)
    self.assertIn("forecast_orchestration", strategy)
    baseline_forecast_state = (((solver_state or {}).get("state_model") or {}).get("baseline_forecast_bundle") or {}).get("forecast_engine_state") or {}
    self.assertIn("forecast_orchestration", baseline_forecast_state)

  def test_solver_blocks_when_gpt_strategy_selection_is_required_but_missing(self) -> None:
    with patch("consistency_solver._gpt_strategy_required", return_value=True), patch(
      "consistency_solver._gpt_strategy_selection",
      return_value={},
    ):
      solver_state = build_consistency_solver_state(
        ops_json={
          "unit_price": 180,
          "utilization_rate": 0.75,
          "capacity_driver": "labor",
          "sales_modality": "local_service",
        },
        people_json={
          "people": [{"full_name": "Owner", "role_title": "Attorney", "annual_wage": 90000}],
          "inferred_roles": [],
        },
        financials_json={
          "cogs_total_year1": 120000,
          "payroll_total_year1": 90000,
          "marketing_total_year1": 20000,
          "other_operating_expense": 30000,
        },
        financials_year1_json={
          "company_revenue_total_year1": 360000,
          "unit_price": 180,
          "utilization_rate": 0.75,
          "avg_units_per_period_year1": 166.6667,
          "operating_periods_per_year": 12,
        },
        marketing_model_json={"expected_units_year1": 2000, "reachable_market": 10000},
        normalized_traits={
          "business_stage": "operating",
          "capacity_driver": "labor",
          "sales_modality": "local_service",
          "customer_type": "b2b",
        },
        benchmark_payload=self._benchmark_payload(
          gross_margin_min=0.55,
          gross_margin_max=0.70,
          ebitda_margin_min=0.00,
          ebitda_margin_max=0.18,
          payroll_min=0.18,
          payroll_max=0.40,
          opex_min=0.08,
          opex_max=0.20,
        ),
        constraint_engine_state={
          "violations": ["payroll_too_light", "ebitda_margin_too_low"],
          "hard_violation_codes": ["payroll_too_light"],
          "soft_violation_codes": ["ebitda_margin_too_low"],
          "constraint_confidence_score": 0.8,
          "fallback_level": "naics_6",
          "supportable_unit_range": {"min": 1400, "max": 2400},
          "supportable_revenue_range": {"min": 280000, "max": 420000},
          "utilization_range": {"min": 0.55, "max": 0.85},
          "gross_margin_band": {"min": 0.55, "max": 0.70},
          "ebitda_margin_band": {"min": 0.00, "max": 0.18},
          "payroll_intensity_band": {"min": 0.18, "max": 0.40},
          "opex_intensity_band": {"min": 0.08, "max": 0.20},
          "marketing_intensity_band": {"min": 0.03, "max": 0.08},
          "current_metrics": {
            "capacity_units_year1": 2666.6667,
            "people_payroll_floor": 90000,
            "structural_payroll_floor": 105000,
          },
        },
      )

    self.assertIsNotNone(solver_state)
    self.assertEqual((solver_state or {}).get("status"), "blocking_unresolved")
    self.assertEqual((solver_state or {}).get("blocking_reason"), "gpt_strategy_selection_unavailable")
    state_model = (solver_state or {}).get("state_model") or {}
    strategy_layer = state_model.get("strategy_layer") or {}
    self.assertEqual(strategy_layer.get("source"), "gpt_required_unavailable")
    self.assertEqual((strategy_layer.get("strategies") or []), [])

  def test_solver_blocks_when_gpt_strategy_blueprint_is_invalid(self) -> None:
    with patch("consistency_solver._gpt_strategy_required", return_value=True), patch(
      "consistency_solver._gpt_strategy_selection",
      return_value={
        "primary_cause": "pricing-driven",
        "reason": "Thin answer.",
        "selected_strategy_ids": ["pricing_adjustment"],
        "strategy_overrides": [],
        "global_overrides": None,
        "baseline_forecast_orchestration": {
          "orchestration_summary": "Baseline path.",
          "quarter_policies": [],
          "role_timing_overrides": [],
          "milestone_timing_overrides": [],
          "event_response": {
            "hire_capacity_multiplier": 1.0,
            "hire_growth_bonus_delta": 0.0,
            "marketing_growth_multiplier": 1.0,
            "milestone_capacity_multiplier": 1.0,
            "milestone_growth_multiplier": 1.0,
          },
        },
        "expected_year1_ebitda_margin_min": -0.02,
        "expected_year1_ebitda_margin_max": 0.04,
      },
    ):
      solver_state = build_consistency_solver_state(
        ops_json={
          "unit_price": 180,
          "utilization_rate": 0.75,
          "capacity_driver": "labor",
          "sales_modality": "local_service",
        },
        people_json={
          "people": [{"full_name": "Owner", "role_title": "Attorney", "annual_wage": 90000}],
          "inferred_roles": [],
        },
        financials_json={
          "cogs_total_year1": 120000,
          "payroll_total_year1": 90000,
          "marketing_total_year1": 20000,
          "other_operating_expense": 30000,
        },
        financials_year1_json={
          "company_revenue_total_year1": 360000,
          "unit_price": 180,
          "utilization_rate": 0.75,
          "avg_units_per_period_year1": 166.6667,
          "operating_periods_per_year": 12,
        },
        marketing_model_json={"expected_units_year1": 2000, "reachable_market": 10000},
        normalized_traits={
          "business_stage": "operating",
          "capacity_driver": "labor",
          "sales_modality": "local_service",
          "customer_type": "b2b",
        },
        benchmark_payload=self._benchmark_payload(
          gross_margin_min=0.55,
          gross_margin_max=0.70,
          ebitda_margin_min=0.00,
          ebitda_margin_max=0.18,
          payroll_min=0.18,
          payroll_max=0.40,
          opex_min=0.08,
          opex_max=0.20,
        ),
        constraint_engine_state={
          "violations": ["payroll_too_light", "ebitda_margin_too_low"],
          "hard_violation_codes": ["payroll_too_light"],
          "soft_violation_codes": ["ebitda_margin_too_low"],
          "constraint_confidence_score": 0.8,
          "fallback_level": "naics_6",
          "supportable_unit_range": {"min": 1400, "max": 2400},
          "supportable_revenue_range": {"min": 280000, "max": 420000},
          "utilization_range": {"min": 0.55, "max": 0.85},
          "gross_margin_band": {"min": 0.55, "max": 0.70},
          "ebitda_margin_band": {"min": 0.00, "max": 0.18},
          "payroll_intensity_band": {"min": 0.18, "max": 0.40},
          "opex_intensity_band": {"min": 0.08, "max": 0.20},
          "marketing_intensity_band": {"min": 0.03, "max": 0.08},
          "current_metrics": {
            "capacity_units_year1": 2666.6667,
            "people_payroll_floor": 90000,
            "structural_payroll_floor": 105000,
          },
        },
      )

    self.assertEqual((solver_state or {}).get("status"), "blocking_unresolved")
    self.assertEqual((solver_state or {}).get("blocking_reason"), "gpt_strategy_selection_unavailable")
    strategy_layer = (((solver_state or {}).get("state_model") or {}).get("strategy_layer") or {})
    self.assertEqual(strategy_layer.get("source"), "gpt_required_invalid_blueprint")
    self.assertEqual((((strategy_layer.get("diagnosis") or {})).get("strategy_advisor_error")), "strategy_advisor_invalid_blueprint")

  def test_solver_blocks_when_gpt_required_blueprint_is_severe_but_underpowered(self) -> None:
    with patch("consistency_solver._gpt_strategy_required", return_value=True), patch(
      "consistency_solver._gpt_strategy_selection",
      return_value={
        "primary_cause": "pricing-driven",
        "secondary_causes": ["mixed"],
        "reason": "A repricing path is needed.",
        "business_model_assessment": "The business is structurally broken and needs a large reset.",
        "severity_class": "severe",
        "severity_reason": "Year 1 economics are structurally non-viable.",
        "minimum_package_strength": "strong",
        "required_lever_families": ["price_up", "util_down"],
        "forbidden_lever_families": ["payroll_down"],
        "controller_directives": {
          "minimum_meaningful_levers": 2,
          "require_multi_lever_coordination": True,
          "preserve_capacity_staffing_link": True,
          "preserve_price_demand_link": True,
          "preserve_marketing_demand_link": True,
          "prefer_delay_over_delete": True,
          "aggression_level": "moderate",
          "escalate_on_retry": False,
          "minimum_package_count": 1,
        },
        "target_margin_path": {
          "year1_min": -0.20,
          "year1_max": -0.10,
          "year2_min": -0.16,
          "year2_max": -0.05,
          "year3_min": -0.14,
          "year3_max": 0.02,
        },
        "target_posture": {
          "year1_ebitda_posture": "stabilize",
          "year2_ebitda_posture": "narrow losses",
          "year3_ebitda_posture": "approach breakeven",
          "staffing_posture": "delay",
          "pricing_posture": "raise price",
          "demand_posture": "paced",
          "cost_posture": "tighten",
        },
        "coordinated_lever_packages": [
          {
            "quarter_start": 1,
            "quarter_end": 8,
            "levers": ["price_up", "util_down"],
            "expected_effects": ["demand_softens_with_price"],
            "minimum_strength": "light",
            "rationale": "A small early price reset.",
          }
        ],
        "selected_strategy_ids": ["pricing_adjustment"],
        "strategy_overrides": [],
        "global_overrides": None,
        "baseline_forecast_orchestration": {
          "orchestration_summary": "baseline",
          "quarter_policies": [],
          "role_timing_overrides": [],
          "milestone_timing_overrides": [],
          "event_response": {
            "hire_capacity_multiplier": 1.0,
            "hire_growth_bonus_delta": 0.0,
            "marketing_growth_multiplier": 1.0,
            "milestone_capacity_multiplier": 1.0,
            "milestone_growth_multiplier": 1.0,
          },
        },
        "expected_year1_ebitda_margin_min": -0.20,
        "expected_year1_ebitda_margin_max": -0.10,
      },
    ):
      solver_state = build_consistency_solver_state(
        ops_json={
          "unit_price": 180,
          "utilization_rate": 0.75,
          "capacity_driver": "labor",
          "sales_modality": "local_service",
        },
        people_json={
          "people": [{"full_name": "Owner", "role_title": "Attorney", "annual_wage": 90000}],
          "inferred_roles": [],
        },
        financials_json={
          "cogs_total_year1": 120000,
          "payroll_total_year1": 90000,
          "marketing_total_year1": 20000,
          "other_operating_expense": 30000,
        },
        financials_year1_json={
          "company_revenue_total_year1": 360000,
          "unit_price": 180,
          "utilization_rate": 0.75,
          "avg_units_per_period_year1": 166.6667,
          "operating_periods_per_year": 12,
        },
        marketing_model_json={"expected_units_year1": 2000, "reachable_market": 10000},
        normalized_traits={
          "business_stage": "startup",
          "capacity_driver": "labor",
          "sales_modality": "local_service",
        },
        benchmark_payload=self._benchmark_payload(
          gross_margin_min=0.55,
          gross_margin_max=0.70,
          ebitda_margin_min=0.00,
          ebitda_margin_max=0.18,
          payroll_min=0.18,
          payroll_max=0.40,
          opex_min=0.08,
          opex_max=0.20,
        ),
        constraint_engine_state={
          "violations": ["payroll_too_light", "ebitda_margin_too_low"],
          "hard_violation_codes": ["payroll_too_light"],
          "soft_violation_codes": ["ebitda_margin_too_low"],
          "constraint_confidence_score": 0.8,
          "fallback_level": "naics_6",
          "supportable_unit_range": {"min": 1400, "max": 2400},
          "supportable_revenue_range": {"min": 280000, "max": 420000},
          "utilization_range": {"min": 0.55, "max": 0.85},
          "gross_margin_band": {"min": 0.55, "max": 0.70},
          "ebitda_margin_band": {"min": 0.00, "max": 0.18},
          "payroll_intensity_band": {"min": 0.18, "max": 0.40},
          "opex_intensity_band": {"min": 0.08, "max": 0.20},
          "marketing_intensity_band": {"min": 0.03, "max": 0.08},
          "current_metrics": {
            "capacity_units_year1": 2666.6667,
            "people_payroll_floor": 90000,
            "structural_payroll_floor": 105000,
          },
        },
      )

    self.assertEqual((solver_state or {}).get("status"), "blocking_unresolved")
    self.assertEqual((solver_state or {}).get("blocking_reason"), "gpt_strategy_selection_unavailable")
    strategy_layer = (((solver_state or {}).get("state_model") or {}).get("strategy_layer") or {})
    self.assertEqual(strategy_layer.get("source"), "gpt_required_invalid_blueprint")

  def test_solver_runs_even_without_blocking_or_viability_trigger(self) -> None:
    with patch("consistency_solver._gpt_strategy_required", return_value=False):
      solver_state = build_consistency_solver_state(
        ops_json={
          "unit_price": 120,
          "utilization_rate": 0.72,
          "capacity_driver": "system",
          "sales_modality": "online",
        },
        people_json={
          "people": [{"full_name": "Founder", "role_title": "Owner", "annual_wage": 80000}],
          "inferred_roles": [],
        },
        financials_json={
          "cogs_total_year1": 90000,
          "payroll_total_year1": 80000,
          "marketing_total_year1": 12000,
          "other_operating_expense": 18000,
        },
        financials_year1_json={
          "company_revenue_total_year1": 300000,
          "unit_price": 120,
          "utilization_rate": 0.72,
          "avg_units_per_period_year1": 208.3333,
          "operating_periods_per_year": 12,
        },
        marketing_model_json={"expected_units_year1": 2500, "reachable_market": 20000},
        normalized_traits={
          "business_stage": "operating",
          "business_type": "Software business",
          "capacity_driver": "system",
          "sales_modality": "online",
          "customer_type": "b2b",
          "unit_cadence": "monthly",
        },
        benchmark_payload=self._benchmark_payload(),
        constraint_engine_state={
          "violations": [],
          "hard_violation_codes": [],
          "soft_violation_codes": [],
          "context_violation_codes": [],
          "constraint_confidence_score": 0.85,
          "supportable_unit_range": {"min": 1800, "max": 3200},
          "supportable_revenue_range": {"min": 240000, "max": 420000},
          "utilization_range": {"min": 0.60, "max": 0.82},
          "gross_margin_band": {"min": 0.55, "max": 0.72},
          "ebitda_margin_band": {"min": 0.06, "max": 0.24},
          "payroll_intensity_band": {"min": 0.14, "max": 0.30},
          "opex_intensity_band": {"min": 0.06, "max": 0.18},
          "marketing_intensity_band": {"min": 0.02, "max": 0.08},
          "current_metrics": {
            "capacity_units_year1": 2500.0,
            "people_payroll_floor": 80000,
            "structural_payroll_floor": 80000,
          },
        },
      )

    self.assertIsNotNone(solver_state)
    self.assertIsInstance(solver_state, dict)
    self.assertIn((solver_state or {}).get("status"), {"awaiting_choice", "blocking_unresolved"})
    self.assertIsInstance(((solver_state or {}).get("state_model") or {}).get("baseline_forecast_bundle"), dict)

  def test_high_ebitda_realism_case_includes_reality_normalization_strategy(self) -> None:
    with patch("consistency_solver._gpt_strategy_required", return_value=False):
      solver_state = build_consistency_solver_state(
        ops_json={
          "unit_price": 500,
          "utilization_rate": 0.95,
          "capacity_driver": "labor",
          "sales_modality": "project_based",
        },
        people_json={
          "people": [{"full_name": "Founder", "role_title": "Consultant", "annual_wage": 90000}],
          "inferred_roles": [],
        },
        financials_json={
          "cogs_total_year1": 20000,
          "payroll_total_year1": 90000,
          "marketing_total_year1": 5000,
          "other_operating_expense": 12000,
        },
        financials_year1_json={
          "company_revenue_total_year1": 420000,
          "unit_price": 500,
          "utilization_rate": 0.95,
          "avg_units_per_period_year1": 70,
          "operating_periods_per_year": 12,
        },
        marketing_model_json={"expected_units_year1": 900, "reachable_market": 5000},
        normalized_traits={
          "business_stage": "operating",
          "business_type": "Professional services",
          "capacity_driver": "labor",
          "sales_modality": "project_based",
          "customer_type": "b2b",
          "unit_cadence": "monthly",
        },
        benchmark_payload=self._benchmark_payload(
          gross_margin_min=0.45,
          gross_margin_max=0.70,
          ebitda_margin_min=0.04,
          ebitda_margin_max=0.20,
          payroll_min=0.18,
          payroll_max=0.40,
          opex_min=0.08,
          opex_max=0.20,
        ),
        constraint_engine_state={
          "violations": ["gross_margin_too_high", "ebitda_margin_too_high", "utilization_too_high"],
          "hard_violation_codes": [],
          "soft_violation_codes": ["gross_margin_too_high", "ebitda_margin_too_high", "utilization_too_high"],
          "context_violation_codes": [],
          "constraint_confidence_score": 0.8,
          "supportable_unit_range": {"min": 700, "max": 1000},
          "supportable_revenue_range": {"min": 300000, "max": 450000},
          "utilization_range": {"min": 0.55, "max": 0.82},
          "gross_margin_band": {"min": 0.45, "max": 0.70},
          "ebitda_margin_band": {"min": 0.04, "max": 0.20},
          "payroll_intensity_band": {"min": 0.18, "max": 0.40},
          "opex_intensity_band": {"min": 0.08, "max": 0.20},
          "marketing_intensity_band": {"min": 0.02, "max": 0.08},
          "current_metrics": {
            "capacity_units_year1": 840.0,
            "people_payroll_floor": 90000,
            "structural_payroll_floor": 90000,
            "utilization_rate": 0.95,
          },
        },
      )

    self.assertIsNotNone(solver_state)
    strategy_layer = (((solver_state or {}).get("state_model") or {}).get("strategy_layer") or {})
    diagnosis = strategy_layer.get("diagnosis") or {}
    self.assertEqual(diagnosis.get("primary_cause"), "pricing-driven")
    strategy_ids = [
      str(item.get("strategy_id") or "").strip()
      for item in (strategy_layer.get("strategy_catalog") or [])
      if isinstance(item, dict)
    ]
    self.assertIn("reality_normalization_strategy", strategy_ids)
    preferred = list(diagnosis.get("preferred_strategy_ids") or [])
    self.assertTrue(preferred)
    self.assertEqual(preferred[0], "reality_normalization_strategy")

  def test_strategy_diagnosis_selects_pricing_strategies_for_margin_problem(self) -> None:
    solver_state = build_consistency_solver_state(
      ops_json={
        "unit_price": 120,
        "utilization_rate": 0.62,
        "capacity_driver": "system",
        "sales_modality": "online",
      },
      people_json={
        "people": [{"full_name": "Founder", "role_title": "Owner", "annual_wage": 70000}],
        "inferred_roles": [],
      },
      financials_json={
        "cogs_total_year1": 210000,
        "payroll_total_year1": 70000,
        "marketing_total_year1": 18000,
        "other_operating_expense": 90000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 360000,
        "unit_price": 120,
        "utilization_rate": 0.62,
        "avg_units_per_period_year1": 250.0,
        "operating_periods_per_year": 12,
      },
      marketing_model_json={"expected_units_year1": 3000, "reachable_market": 80000},
      normalized_traits={
        "business_stage": "operating",
        "capacity_driver": "system",
        "sales_modality": "online",
        "customer_type": "b2c",
        "unit_cadence": "monthly",
      },
      benchmark_payload=self._benchmark_payload(
        gross_margin_min=0.45,
        gross_margin_max=0.68,
        ebitda_margin_min=0.04,
        ebitda_margin_max=0.16,
        payroll_min=0.12,
        payroll_max=0.28,
        opex_min=0.08,
        opex_max=0.18,
      ),
      constraint_engine_state={
        "violations": ["gross_margin_too_low", "ebitda_margin_too_low"],
        "soft_violation_codes": ["gross_margin_too_low", "ebitda_margin_too_low"],
        "constraint_confidence_score": 0.84,
        "fallback_level": "naics_6",
        "supportable_unit_range": {"min": 2500, "max": 4200},
        "supportable_revenue_range": {"min": 300000, "max": 520000},
        "utilization_range": {"min": 0.5, "max": 0.82},
        "gross_margin_band": {"min": 0.45, "max": 0.68},
        "ebitda_margin_band": {"min": 0.04, "max": 0.16},
        "payroll_intensity_band": {"min": 0.12, "max": 0.28},
        "opex_intensity_band": {"min": 0.08, "max": 0.18},
        "marketing_intensity_band": {"min": 0.03, "max": 0.12},
        "current_metrics": {
          "capacity_units_year1": 5000.0,
          "people_payroll_floor": 70000.0,
          "structural_payroll_floor": 70000.0,
        },
      },
    )

    self.assertIsNotNone(solver_state)
    state_model = (solver_state or {}).get("state_model") or {}
    strategy_layer = state_model.get("strategy_layer") or {}
    diagnosis = strategy_layer.get("diagnosis") or {}
    self.assertEqual(diagnosis.get("primary_cause"), "pricing-driven")
    strategy_ids = [str(item.get("strategy_id") or "") for item in (strategy_layer.get("strategies") or []) if isinstance(item, dict)]
    self.assertIn("pricing_adjustment", strategy_ids)
    self.assertLessEqual(len(strategy_ids), 2)

  def test_solver_state_model_allows_role_delay_beyond_twelve_months(self) -> None:
    baseline_summary = build_consistency_financial_summary(
      financials_json={
        "cogs_total_year1": 60000,
        "payroll_total_year1": 90000,
        "marketing_total_year1": 15000,
        "other_operating_expense": 40000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 260000,
        "unit_price": 125,
        "utilization_rate": 0.6,
        "avg_units_per_period_year1": 40.0,
        "operating_periods_per_year": 52,
      },
    )
    state_model = _build_solver_state_model(
      ops_json={"capacity_driver": "labor", "sales_modality": "local_service"},
      people_json={
        "people": [{"full_name": "Owner", "role_title": "Lead", "annual_wage": 90000}],
        "inferred_roles": [{"role_title": "Coordinator", "annual_wage": 42000, "months_until_hire": 6}],
      },
      financials_json={
        "cogs_total_year1": 60000,
        "marketing_total_year1": 15000,
        "other_operating_expense": 40000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 260000,
        "unit_price": 125,
        "utilization_rate": 0.6,
        "avg_units_per_period_year1": 40.0,
        "operating_periods_per_year": 52,
      },
      marketing_model_json={"expected_units_year1": 2080, "reachable_market": 15000},
      normalized_traits={
        "business_stage": "operating",
        "capacity_driver": "labor",
        "sales_modality": "local_service",
      },
      baseline_summary=baseline_summary,
      constraint_engine_state={
        "supportable_unit_range": {"min": 1800, "max": 3200},
        "supportable_revenue_range": {"min": 220000, "max": 360000},
        "utilization_range": {"min": 0.5, "max": 0.82},
        "gross_margin_band": {"min": 0.5, "max": 0.7},
        "ebitda_margin_band": {"min": 0.02, "max": 0.15},
        "payroll_intensity_band": {"min": 0.18, "max": 0.38},
        "opex_intensity_band": {"min": 0.08, "max": 0.18},
        "constraint_confidence_score": 0.8,
        "fallback_level": "naics_6",
        "violations": ["ebitda_margin_too_low"],
        "current_metrics": {"capacity_units_year1": 3400.0},
      },
    )

    roles = ((((state_model or {}).get("controllable_drivers") or {}).get("people") or {}).get("inferred_roles") or [])
    self.assertTrue(roles)
    self.assertGreaterEqual(_safe_float((roles[0] or {}).get("max_months")), 18.0)

  def test_solver_uses_physical_capacity_from_constraint_engine(self) -> None:
    baseline_summary = build_consistency_financial_summary(
      financials_json={
        "cogs_total_year1": 40000,
        "payroll_total_year1": 90000,
        "marketing_total_year1": 10000,
        "other_operating_expense": 20000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 180000,
        "unit_price": 2000,
        "utilization_rate": 0.6,
        "avg_units_per_period_year1": 27,
        "operating_periods_per_year": 1,
      },
    )
    state_model = _build_solver_state_model(
      ops_json={"unit_price": 2000, "utilization_rate": 0.6, "capacity_driver": "labor"},
      people_json={"future_roles": []},
      financials_json={
        "marketing_total_year1": 10000,
        "other_operating_expense": 20000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 180000,
        "unit_price": 2000,
        "utilization_rate": 0.6,
        "avg_units_per_period_year1": 27,
        "operating_periods_per_year": 1,
      },
      marketing_model_json={"expected_units_year1": 27},
      baseline_summary=baseline_summary,
      constraint_engine_state={
        "supportable_unit_range": {"min": 20, "max": 27},
        "supportable_revenue_range": {"min": 120000, "max": 180000},
        "utilization_range": {"min": 0.5, "max": 0.9},
        "ebitda_margin_band": {"min": 0.08, "max": 0.18},
        "opex_intensity_band": {"min": 0.05, "max": 0.25},
        "constraints": [],
        "violations": ["ebitda_margin_too_low"],
        "current_metrics": {"capacity_units_year1": 45.0},
      },
    )

    direct_inputs = _build_direct_solver_inputs(state_model=state_model or {})

    self.assertIsNotNone(direct_inputs)
    self.assertEqual(direct_inputs["capacity_units"], 45.0)

  def test_forecast_engine_blocks_hard_unresolved_year1(self) -> None:
    bundle = build_forecast_engine_bundle(
      financials_json={
        "cogs_total_year1": 96000,
        "payroll_total_year1": 72000,
        "marketing_total_year1": 12000,
        "other_operating_expense": 18000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 240000,
        "unit_price": 100,
        "utilization_rate": 0.6,
        "avg_units_per_period_year1": 200,
        "operating_periods_per_year": 12,
      },
      benchmark_payload={"fallback_level": "naics_6", "confidence_score": 0.9},
      constraint_engine_state={
        "violations": ["payroll_too_light", "ebitda_margin_too_low"],
        "hard_violation_codes": ["payroll_too_light"],
        "soft_violation_codes": ["ebitda_margin_too_low"],
      },
    )

    self.assertEqual(bundle["forecast_engine_state"]["status"], "ready")
    self.assertEqual(bundle["forecast_engine_state"]["year1_warning_status"], "blocked_unresolved_year1")
    self.assertEqual(bundle["forecast_engine_state"]["blocking_violations"], ["payroll_too_light"])
    self.assertEqual(len(bundle["forecast_quarters"]), 20)
    self.assertEqual(len(bundle["forecast_years"]), 5)

  def test_forecast_engine_allows_soft_realism_violations(self) -> None:
    bundle = build_forecast_engine_bundle(
      financials_json={
        "cogs_total_year1": 96000,
        "payroll_total_year1": 72000,
        "marketing_total_year1": 12000,
        "other_operating_expense": 18000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 240000,
        "unit_price": 100,
        "utilization_rate": 0.6,
        "avg_units_per_period_year1": 200,
        "operating_periods_per_year": 12,
      },
      benchmark_payload={"fallback_level": "naics_6", "confidence_score": 0.9},
      constraint_engine_state={
        "violations": ["gross_margin_too_low"],
        "soft_violation_codes": ["gross_margin_too_low"],
      },
    )

    self.assertEqual(bundle["forecast_engine_state"]["status"], "ready")
    self.assertEqual(len(bundle["forecast_quarters"]), 20)

  def test_hard_invalid_year1_blocks_even_when_soft_valid_year1_forecasts(self) -> None:
    hard_invalid = build_forecast_engine_bundle(
      financials_json={
        "cogs_total_year1": 70000,
        "payroll_total_year1": 35000,
        "marketing_total_year1": 8000,
        "other_operating_expense": 12000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 240000,
        "unit_price": 100,
        "utilization_rate": 0.35,
        "avg_units_per_period_year1": 200,
        "operating_periods_per_year": 12,
      },
      benchmark_payload={"fallback_level": "naics_6", "confidence_score": 0.9},
      constraint_engine_state={
        "violations": ["utilization_too_low"],
        "hard_violation_codes": ["utilization_too_low"],
      },
    )
    soft_only = build_forecast_engine_bundle(
      financials_json={
        "cogs_total_year1": 98000,
        "payroll_total_year1": 72000,
        "marketing_total_year1": 12000,
        "other_operating_expense": 24000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 240000,
        "unit_price": 100,
        "utilization_rate": 0.62,
        "avg_units_per_period_year1": 200,
        "operating_periods_per_year": 12,
      },
      benchmark_payload={"fallback_level": "naics_6", "confidence_score": 0.9},
      constraint_engine_state={
        "violations": ["gross_margin_too_low"],
        "soft_violation_codes": ["gross_margin_too_low"],
      },
    )

    self.assertEqual(hard_invalid["forecast_engine_state"]["status"], "ready")
    self.assertEqual(hard_invalid["forecast_engine_state"]["year1_warning_status"], "blocked_unresolved_year1")
    self.assertEqual(soft_only["forecast_engine_state"]["status"], "ready")

  @patch("constraint_engine.extract_normalized_traits")
  @patch("constraint_engine.resolve_alpha_benchmark_payload")
  def test_constraint_engine_keeps_demand_support_soft_when_marketing_is_modeled(
    self,
    mock_benchmark,
    mock_traits,
  ) -> None:
    mock_traits.return_value = {
      "naics_6": "722511",
      "sector": "Consumer Cyclical",
      "customer_type": "b2c",
      "sales_modality": "local_service",
      "capacity_driver": "labor",
      "unit_cadence": "recurring",
      "geographic_scope": "local",
      "business_stage": "operating",
      "fulfillment_shape": "onsite_service",
    }
    mock_benchmark.return_value = {
      "fallback_level": "generic",
      "confidence_score": 0.2,
      "gross_margin_band": {"min": 0.7, "max": 0.8},
      "ebitda_margin_band": {"min": -0.15, "max": -0.05},
      "payroll_intensity": {"min": 0.05, "max": 0.10},
      "opex_intensity": {"min": 0.02, "max": 0.04},
      "working_capital": {"dso": {"min": 10, "max": 20}, "dpo": {"min": 10, "max": 20}, "inventory_days": {"min": 5, "max": 15}},
    }

    bundle = build_constraint_engine_bundle(
      operating_model_json={"unit_price": 30, "utilization_rate": 0.75, "capacity_driver": "labor", "sales_modality": "local service", "business_stage": "operating"},
      financials_json={
        "cogs_total_year1": 300000,
        "payroll_total_year1": 280000,
        "marketing_total_year1": 25000,
        "other_operating_expense": 120000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 900000,
        "unit_price": 30,
        "avg_units_per_period_year1": 2500,
        "operating_periods_per_year": 12,
        "utilization_rate": 0.75,
      },
      marketing_model_json={"expected_units_year1": 30000, "demand_supports_required_units": True},
    )

    engine = bundle["constraint_engine_state"]
    self.assertGreater(engine["supportable_unit_range"]["max"], 30000)
    self.assertNotIn("demand_unsupported", engine["violations"])

  @patch("constraint_engine.extract_normalized_traits")
  @patch("constraint_engine.resolve_alpha_benchmark_payload")
  def test_constraint_engine_ignores_generic_benchmark_band_for_realism_floor(
    self,
    mock_benchmark,
    mock_traits,
  ) -> None:
    mock_traits.return_value = {
      "naics_6": "541110",
      "sector": "Financial",
      "customer_type": "b2b",
      "sales_modality": "project_based",
      "capacity_driver": "labor",
      "unit_cadence": "contract",
      "geographic_scope": "local",
      "business_stage": "operating",
      "fulfillment_shape": "onsite_service",
    }
    mock_benchmark.return_value = {
      "fallback_level": "generic",
      "confidence_score": 0.2,
      "gross_margin_band": {"min": 0.9, "max": 0.95},
      "ebitda_margin_band": {"min": -0.18, "max": -0.08},
      "payroll_intensity": {"min": 0.05, "max": 0.10},
      "opex_intensity": {"min": 0.01, "max": 0.03},
      "working_capital": {"dso": {"min": 20, "max": 40}, "dpo": {"min": 10, "max": 20}, "inventory_days": {"min": 0, "max": 5}},
    }

    bundle = build_constraint_engine_bundle(
      operating_model_json={"unit_price": 100, "utilization_rate": 0.6, "capacity_driver": "labor", "sales_modality": "project based", "business_stage": "operating"},
      financials_json={
        "cogs_total_year1": 30000,
        "payroll_total_year1": 50000,
        "marketing_total_year1": 15000,
        "other_operating_expense": 20000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 100000,
        "unit_price": 100,
        "avg_units_per_week_year1": 20,
        "operating_weeks_per_year": 52,
        "utilization_rate": 0.6,
      },
      marketing_model_json={"expected_units_year1": 1040},
    )

    ebitda_band = bundle["constraint_engine_state"]["ebitda_margin_band"]
    self.assertGreater(ebitda_band["max"], -0.08)

  @patch("constraint_engine.extract_normalized_traits")
  @patch("constraint_engine.resolve_alpha_benchmark_payload")
  def test_constraint_engine_derives_payroll_from_people_when_missing(
    self,
    mock_benchmark,
    mock_traits,
  ) -> None:
    mock_traits.return_value = {
      "naics_6": "541611",
      "sector": "Technology Services",
      "customer_type": "b2b",
      "sales_modality": "project_based",
      "capacity_driver": "labor",
      "unit_cadence": "contract",
      "geographic_scope": "national",
      "business_stage": "operating",
      "fulfillment_shape": "digital_remote",
    }
    mock_benchmark.return_value = {
      "fallback_level": "naics_6",
      "confidence_score": 0.9,
      "gross_margin_band": {"min": 0.45, "max": 0.60},
      "ebitda_margin_band": {"min": 0.08, "max": 0.18},
      "payroll_intensity": {"min": 0.18, "max": 0.35},
      "opex_intensity": {"min": 0.08, "max": 0.20},
      "working_capital": {
        "dso": {"min": 20, "max": 40},
        "dpo": {"min": 15, "max": 30},
        "inventory_days": {"min": 0, "max": 5},
      },
    }

    bundle = build_constraint_engine_bundle(
      operating_model_json={"unit_price": 100, "utilization_rate": 0.6, "capacity_driver": "labor"},
      people_json={
        "people": [{"role_title": "Owner", "annual_wage": 90000}],
        "inferred_roles": [{"role_title": "Analyst", "annual_wage": 60000, "months_until_hire": 6}],
      },
      financials_json={
        "cogs_total_year1": 30000,
        "marketing_total_year1": 15000,
        "other_operating_expense": 20000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 100000,
        "unit_price": 100,
        "avg_units_per_week_year1": 20,
        "operating_weeks_per_year": 52,
        "utilization_rate": 0.6,
      },
      marketing_model_json={"expected_units_year1": 1040},
    )

    self.assertGreater(bundle["constraint_engine_state"]["current_metrics"]["payroll_intensity"], 0.0)

  @patch("constraint_engine.extract_normalized_traits")
  @patch("constraint_engine.resolve_alpha_benchmark_payload")
  def test_constraint_engine_uses_child_weighted_utilization_metrics(
    self,
    mock_benchmark,
    mock_traits,
  ) -> None:
    mock_traits.return_value = {
      "naics_6": "541611",
      "sector": "Professional Services",
      "customer_type": "b2b",
      "sales_modality": "project_based",
      "capacity_driver": "labor",
      "unit_cadence": "contract",
      "geographic_scope": "local",
      "business_stage": "operating",
      "fulfillment_shape": "in_person",
    }
    mock_benchmark.return_value = {
      "fallback_level": "naics_4",
      "confidence_score": 0.6,
      "gross_margin_band": {"min": 0.45, "max": 0.7},
      "ebitda_margin_band": {"min": 0.05, "max": 0.18},
      "payroll_intensity": {"min": 0.1, "max": 0.3},
      "opex_intensity": {"min": 0.08, "max": 0.2},
      "working_capital": {"dso": {"min": 20, "max": 40}, "dpo": {"min": 10, "max": 30}, "inventory_days": {"min": 0, "max": 5}},
    }

    bundle = build_constraint_engine_bundle(
      operating_model_json={"unit_price": 1000, "utilization_rate": 0.2, "capacity_driver": "labor", "sales_modality": "project based", "business_stage": "operating"},
      financials_json={
        "cogs_total_year1": 120000,
        "payroll_total_year1": 180000,
        "marketing_total_year1": 15000,
        "other_operating_expense": 60000,
      },
      financials_year1_json={
        "utilization_rate": 0.2,
        "lobs": [
          {
            "lob_name": "Services",
            "products": [
              {
                "product_name": "Advisory",
                "unit_cadence": "contract",
                "unit_price": 5000,
                "units_per_period_capacity": 10,
                "avg_active_units_year1": 8,
                "annual_turns_per_year": 2.0,
                "utilization_rate": 0.8,
                "revenue_total_year1": 80000,
                "annual_completed_units_year1": 16,
              },
              {
                "product_name": "Audit",
                "unit_cadence": "contract",
                "unit_price": 10000,
                "units_per_period_capacity": 6,
                "avg_active_units_year1": 3,
                "annual_turns_per_year": 2.0,
                "utilization_rate": 0.5,
                "revenue_total_year1": 60000,
                "annual_completed_units_year1": 6,
              },
            ],
          }
        ],
        "company_revenue_total_year1": 140000,
      },
    )

    current_metrics = bundle["constraint_engine_state"]["current_metrics"]
    self.assertGreater(current_metrics["child_product_count"], 0)
    self.assertAlmostEqual(current_metrics["utilization_rate"], 11.0 / 16.0, places=6)
    self.assertNotEqual(current_metrics["utilization_rate"], 0.2)

  @patch("constraint_engine.extract_normalized_traits")
  @patch("constraint_engine.resolve_alpha_benchmark_payload")
  def test_constraint_engine_flags_low_utilization_for_operating_labor_business(
    self,
    mock_benchmark,
    mock_traits,
  ) -> None:
    mock_traits.return_value = {
      "naics_6": "541110",
      "sector": "Professional Services",
      "customer_type": "b2b",
      "sales_modality": "project_based",
      "capacity_driver": "labor",
      "unit_cadence": "contract",
      "geographic_scope": "local",
      "business_stage": "operating",
      "fulfillment_shape": "in_person",
    }
    mock_benchmark.return_value = {
      "fallback_level": "naics_3",
      "confidence_score": 0.5,
      "gross_margin_band": {"min": 0.45, "max": 0.65},
      "ebitda_margin_band": {"min": 0.05, "max": 0.18},
      "payroll_intensity": {"min": 0.18, "max": 0.35},
      "opex_intensity": {"min": 0.08, "max": 0.2},
      "working_capital": {"dso": {"min": 20, "max": 40}, "dpo": {"min": 10, "max": 30}, "inventory_days": {"min": 0, "max": 5}},
    }

    bundle = build_constraint_engine_bundle(
      operating_model_json={"capacity_driver": "labor", "sales_modality": "project based", "business_stage": "operating", "utilization_rate": 0.39},
      financials_json={
        "cogs_total_year1": 150000,
        "payroll_total_year1": 320000,
        "marketing_total_year1": 400000,
        "other_operating_expense": 250000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 2100000,
        "unit_price": 12000,
        "avg_units_per_period_year1": 29.25,
        "operating_periods_per_year": 6.0,
        "units_per_period_capacity": 75,
        "utilization_rate": 0.39,
      },
    )

    self.assertIn("utilization_too_low", bundle["constraint_engine_state"]["violations"])
    self.assertIn("utilization_too_low", bundle["constraint_engine_state"]["hard_violation_codes"])

  @patch("constraint_engine.extract_normalized_traits")
  @patch("constraint_engine.resolve_alpha_benchmark_payload")
  def test_constraint_engine_flags_marketing_too_high_when_marketing_balloons(
    self,
    mock_benchmark,
    mock_traits,
  ) -> None:
    mock_traits.return_value = {
      "naics_6": "541611",
      "sector": "Professional Services",
      "customer_type": "b2b",
      "sales_modality": "project_based",
      "capacity_driver": "labor",
      "unit_cadence": "contract",
      "geographic_scope": "local",
      "business_stage": "operating",
      "fulfillment_shape": "in_person",
    }
    mock_benchmark.return_value = {
      "fallback_level": "naics_4",
      "confidence_score": 0.55,
      "gross_margin_band": {"min": 0.45, "max": 0.7},
      "ebitda_margin_band": {"min": 0.05, "max": 0.18},
      "payroll_intensity": {"min": 0.12, "max": 0.28},
      "opex_intensity": {"min": 0.08, "max": 0.2},
      "working_capital": {"dso": {"min": 20, "max": 40}, "dpo": {"min": 10, "max": 30}, "inventory_days": {"min": 0, "max": 5}},
    }

    bundle = build_constraint_engine_bundle(
      operating_model_json={"capacity_driver": "labor", "sales_modality": "project based", "business_stage": "operating"},
      financials_json={
        "cogs_total_year1": 300000,
        "payroll_total_year1": 500000,
        "marketing_total_year1": 760000,
        "other_operating_expense": 180000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 2100000,
        "unit_price": 12000,
        "avg_units_per_period_year1": 35,
        "operating_periods_per_year": 5,
        "units_per_period_capacity": 60,
        "utilization_rate": 0.583333,
      },
    )

    self.assertIn("marketing_too_high", bundle["constraint_engine_state"]["violations"])
    self.assertIn("marketing_intensity_band", bundle["constraint_engine_state"])

  @patch("constraint_engine.extract_normalized_traits")
  @patch("constraint_engine.resolve_alpha_benchmark_payload")
  def test_constraint_engine_uses_structural_workload_payroll_floor(
    self,
    mock_benchmark,
    mock_traits,
  ) -> None:
    mock_traits.return_value = {
      "naics_6": "541611",
      "sector": "Professional Services",
      "customer_type": "b2b",
      "sales_modality": "local_service",
      "capacity_driver": "labor",
      "unit_cadence": "weekly",
      "geographic_scope": "local",
      "business_stage": "operating",
      "fulfillment_shape": "in_person",
    }
    mock_benchmark.return_value = {
      "fallback_level": "naics_4",
      "confidence_score": 0.65,
      "gross_margin_band": {"min": 0.4, "max": 0.65},
      "ebitda_margin_band": {"min": 0.05, "max": 0.18},
      "payroll_intensity": {"min": 0.02, "max": 0.08},
      "opex_intensity": {"min": 0.05, "max": 0.16},
      "working_capital": {"dso": {"min": 20, "max": 40}, "dpo": {"min": 10, "max": 30}, "inventory_days": {"min": 0, "max": 5}},
    }

    bundle = build_constraint_engine_bundle(
      operating_model_json={"capacity_driver": "labor", "sales_modality": "local service", "business_stage": "operating"},
      people_json={
        "people": [
          {"full_name": "A", "annual_wage": 50000},
          {"full_name": "B", "annual_wage": 50000},
        ],
        "inferred_roles": [],
      },
      financials_json={
        "cogs_total_year1": 120000,
        "payroll_total_year1": 100000,
        "marketing_total_year1": 20000,
        "other_operating_expense": 70000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 700000,
        "unit_price": 350,
        "avg_units_per_period_year1": 40,
        "operating_periods_per_year": 50,
        "units_per_period_capacity": 55,
        "utilization_rate": 0.727273,
      },
    )

    current_metrics = bundle["constraint_engine_state"]["current_metrics"]
    self.assertIn("payroll_too_light", bundle["constraint_engine_state"]["violations"])
    self.assertIn("payroll_too_light", bundle["constraint_engine_state"]["hard_violation_codes"])
    self.assertGreater(current_metrics["structural_payroll_floor"], 100000.0)

  @patch("constraint_engine.extract_normalized_traits")
  @patch("constraint_engine.resolve_alpha_benchmark_payload")
  def test_constraint_engine_marks_capacity_support_as_hard_constraint(
    self,
    mock_benchmark,
    mock_traits,
  ) -> None:
    mock_traits.return_value = {
      "naics_6": "722511",
      "business_type": "Restaurant",
      "customer_type": "b2c",
      "sales_modality": "retail",
      "capacity_driver": "labor",
      "unit_cadence": "weekly",
      "geographic_scope": "local",
      "business_stage": "operating",
      "fulfillment_shape": "in_person_local",
    }
    mock_benchmark.return_value = self._benchmark_payload()

    bundle = build_constraint_engine_bundle(
      operating_model_json={"capacity_driver": "labor", "sales_modality": "retail", "business_stage": "operating"},
      financials_json={
        "cogs_total_year1": 110000,
        "payroll_total_year1": 130000,
        "marketing_total_year1": 15000,
        "other_operating_expense": 40000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 300000,
        "unit_price": 25,
        "avg_units_per_week_year1": 340,
        "operating_weeks_per_year": 52,
        "units_per_week_capacity": 200,
        "utilization_rate": 0.9,
      },
    )

    self.assertIn("capacity_unsupported", bundle["constraint_engine_state"]["violations"])
    self.assertIn("capacity_unsupported", bundle["constraint_engine_state"]["hard_violation_codes"])

  @patch("constraint_engine.extract_normalized_traits")
  @patch("constraint_engine.resolve_alpha_benchmark_payload")
  def test_constraint_engine_handles_structural_payroll_floor_when_revenue_is_missing(
    self,
    mock_benchmark,
    mock_traits,
  ) -> None:
    mock_traits.return_value = {
      "naics_6": "621610",
      "sector": "Health Care",
      "customer_type": "b2c",
      "sales_modality": "local_service",
      "capacity_driver": "labor",
      "unit_cadence": "weekly",
      "geographic_scope": "local",
      "business_stage": "operating",
      "fulfillment_shape": "in_person_local",
    }
    mock_benchmark.return_value = {
      "fallback_level": "naics_6",
      "confidence_score": 0.8,
      "gross_margin_band": {"min": 0.35, "max": 0.55},
      "ebitda_margin_band": {"min": 0.04, "max": 0.14},
      "payroll_intensity": {"min": 0.18, "max": 0.34},
      "opex_intensity": {"min": 0.08, "max": 0.18},
      "working_capital": {"dso": {"min": 20, "max": 40}, "dpo": {"min": 15, "max": 30}, "inventory_days": {"min": 0, "max": 5}},
    }

    bundle = build_constraint_engine_bundle(
      operating_model_json={"capacity_driver": "labor", "sales_modality": "local_service"},
      people_json={
        "people": [{"full_name": "Owner", "role_title": "Director", "annual_wage": 95000}],
        "inferred_roles": [{"role_title": "Caregiver", "annual_wage": 42000, "months_until_hire": 2}],
      },
      financials_json={
        "cogs_total_year1": 355000,
        "payroll_total_year1": 137000,
        "marketing_total_year1": 26000,
        "other_operating_expense": 62000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 0,
        "unit_price": 820,
        "utilization_rate": 0.65,
        "avg_units_per_period_year1": 17,
        "operating_periods_per_year": 52,
      },
      marketing_model_json={"expected_units_year1": 884, "reachable_market": 12000},
    )

    state = bundle["constraint_engine_state"]
    self.assertIsInstance(state.get("violations"), list)
    self.assertIn("current_metrics", state)
    self.assertIsNone((state.get("current_metrics") or {}).get("payroll_intensity"))

  def test_sync_marketing_derived_fields_clamps_to_realism_bounds(self) -> None:
    next_model, next_financials = _sync_marketing_derived_fields(
      marketing_model_json={"expected_units_year1": 4000, "reachable_market": 20000},
      financials_json={"baseline_marketing": 20000},
      financials_year1_json={"company_revenue_total_year1": 500000},
      units_per_dollar=0.01,
      min_total=25000,
      max_total=60000,
    )

    self.assertEqual(next_model["marketing_total_year1"], 60000)
    self.assertEqual(next_financials["marketing_total_year1"], 60000)

  def test_solver_uses_marketing_realism_cap_from_constraint_engine(self) -> None:
    baseline_summary = build_consistency_financial_summary(
      financials_json={
        "cogs_total_year1": 300000,
        "payroll_total_year1": 500000,
        "marketing_total_year1": 760000,
        "other_operating_expense": 180000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 2100000,
        "unit_price": 12000,
        "utilization_rate": 0.58,
        "avg_units_per_period_year1": 35,
        "operating_periods_per_year": 5,
      },
    )
    state_model = _build_solver_state_model(
      ops_json={"capacity_driver": "labor", "sales_modality": "project_based"},
      people_json={"future_roles": []},
      financials_json={
        "marketing_total_year1": 760000,
        "other_operating_expense": 180000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 2100000,
        "unit_price": 12000,
        "utilization_rate": 0.58,
        "avg_units_per_period_year1": 35,
        "operating_periods_per_year": 5,
      },
      marketing_model_json={"expected_units_year1": 175, "reachable_market": 500},
      baseline_summary=baseline_summary,
      constraint_engine_state={
        "supportable_unit_range": {"min": 120, "max": 220},
        "supportable_revenue_range": {"min": 1440000, "max": 2640000},
        "utilization_range": {"min": 0.45, "max": 0.82},
        "gross_margin_band": {"min": 0.45, "max": 0.72},
        "ebitda_margin_band": {"min": 0.05, "max": 0.18},
        "marketing_intensity_band": {"min": 0.02, "max": 0.08},
        "opex_intensity_band": {"min": 0.08, "max": 0.2},
        "constraint_confidence_score": 0.8,
        "fallback_level": "naics_4",
        "constraints": [],
        "violations": ["marketing_too_high", "ebitda_margin_too_low"],
        "current_metrics": {"capacity_units_year1": 301.72},
      },
    )
    direct_inputs = _build_direct_solver_inputs(state_model=state_model or {})

    self.assertIsNotNone(direct_inputs)
    self.assertLessEqual((direct_inputs or {})["marketing_upper"], 168000.0)

  def test_local_labor_service_tightens_marketing_and_disables_demand_link(self) -> None:
    baseline_summary = build_consistency_financial_summary(
      financials_json={
        "cogs_total_year1": 120000,
        "payroll_total_year1": 180000,
        "marketing_total_year1": 30000,
        "other_operating_expense": 60000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 600000,
        "unit_price": 250,
        "utilization_rate": 0.72,
        "avg_units_per_period_year1": 46.1538,
        "operating_periods_per_year": 52,
      },
    )
    state_model = _build_solver_state_model(
      ops_json={"capacity_driver": "labor", "sales_modality": "local_service"},
      people_json={"future_roles": []},
      financials_json={"marketing_total_year1": 30000, "other_operating_expense": 60000},
      financials_year1_json={
        "company_revenue_total_year1": 600000,
        "unit_price": 250,
        "utilization_rate": 0.72,
        "avg_units_per_period_year1": 46.1538,
        "operating_periods_per_year": 52,
      },
      marketing_model_json={"expected_units_year1": 2400, "reachable_market": 15000},
      normalized_traits={
        "business_type": "Law Firm",
        "sales_modality": "local_service",
        "capacity_driver": "labor",
        "customer_type": "b2b",
        "business_stage": "operating",
      },
      baseline_summary=baseline_summary,
      constraint_engine_state={
        "supportable_unit_range": {"min": 1800, "max": 3000},
        "supportable_revenue_range": {"min": 450000, "max": 750000},
        "utilization_range": {"min": 0.6, "max": 0.82},
        "gross_margin_band": {"min": 0.45, "max": 0.75},
        "ebitda_margin_band": {"min": 0.08, "max": 0.18},
        "marketing_intensity_band": {"min": 0.02, "max": 0.10},
        "opex_intensity_band": {"min": 0.08, "max": 0.18},
        "constraint_confidence_score": 0.8,
        "fallback_level": "naics_6",
        "constraints": [],
        "violations": ["ebitda_margin_too_low"],
        "current_metrics": {"capacity_units_year1": 3328.0},
      },
    )

    constraint_profile = (state_model or {}).get("constraint_profile") or {}
    marketing_envelope = constraint_profile.get("marketing_envelope") or {}
    demand_curve = constraint_profile.get("demand_curve") or {}
    direct_inputs = _build_direct_solver_inputs(state_model=state_model or {})
    self.assertEqual(marketing_envelope.get("commercial_role"), "constrained")
    self.assertFalse(demand_curve.get("enabled"))
    self.assertLessEqual(_safe_float(marketing_envelope.get("max")), 31800.0)
    self.assertEqual(((state_model or {}).get("fixed_facts") or {}).get("commercial_context", {}).get("commercial_archetype"), "labor_local_service")
    self.assertFalse((((state_model or {}).get("fixed_facts") or {}).get("commercial_context", {}).get("growth_demand_mode_enabled")))
    self.assertFalse(bool((direct_inputs or {}).get("growth_demand_mode_enabled")))

  def test_online_business_keeps_marketing_as_real_growth_lever(self) -> None:
    baseline_summary = build_consistency_financial_summary(
      financials_json={
        "cogs_total_year1": 220000,
        "payroll_total_year1": 140000,
        "marketing_total_year1": 40000,
        "other_operating_expense": 50000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 700000,
        "unit_price": 35,
        "utilization_rate": 0.7,
        "avg_units_per_period_year1": 1666.6667,
        "operating_periods_per_year": 12,
      },
    )
    state_model = _build_solver_state_model(
      ops_json={"capacity_driver": "system", "sales_modality": "online"},
      people_json={"future_roles": []},
      financials_json={"marketing_total_year1": 40000, "other_operating_expense": 50000},
      financials_year1_json={
        "company_revenue_total_year1": 700000,
        "unit_price": 35,
        "utilization_rate": 0.7,
        "avg_units_per_period_year1": 1666.6667,
        "operating_periods_per_year": 12,
      },
      marketing_model_json={"expected_units_year1": 20000, "reachable_market": 200000},
      normalized_traits={
        "business_type": "Subscription Box",
        "sales_modality": "online",
        "capacity_driver": "system",
        "customer_type": "b2c",
        "business_stage": "operating",
        "unit_cadence": "subscription",
      },
      baseline_summary=baseline_summary,
      constraint_engine_state={
        "supportable_unit_range": {"min": 18000, "max": 32000},
        "supportable_revenue_range": {"min": 620000, "max": 900000},
        "utilization_range": {"min": 0.55, "max": 0.88},
        "gross_margin_band": {"min": 0.45, "max": 0.75},
        "ebitda_margin_band": {"min": 0.06, "max": 0.18},
        "marketing_intensity_band": {"min": 0.03, "max": 0.18},
        "opex_intensity_band": {"min": 0.06, "max": 0.16},
        "constraint_confidence_score": 0.85,
        "fallback_level": "naics_6",
        "constraints": [],
        "violations": ["ebitda_margin_too_low"],
        "current_metrics": {"capacity_units_year1": 36000.0},
      },
    )

    constraint_profile = (state_model or {}).get("constraint_profile") or {}
    marketing_envelope = constraint_profile.get("marketing_envelope") or {}
    demand_curve = constraint_profile.get("demand_curve") or {}
    direct_inputs = _build_direct_solver_inputs(state_model=state_model or {})
    self.assertEqual(marketing_envelope.get("commercial_role"), "primary")
    self.assertTrue(demand_curve.get("enabled"))
    self.assertGreaterEqual(_safe_float(marketing_envelope.get("max")), 58000.0)
    self.assertEqual(((state_model or {}).get("fixed_facts") or {}).get("commercial_context", {}).get("commercial_archetype"), "scalable_online")
    self.assertTrue((((state_model or {}).get("fixed_facts") or {}).get("commercial_context", {}).get("growth_demand_mode_enabled")))
    self.assertTrue(bool((direct_inputs or {}).get("growth_demand_mode_enabled")))

  def test_commercial_archetype_is_derived_from_traits_not_business_type_name(self) -> None:
    law_archetype = _derive_commercial_archetype(
      normalized_traits={
        "business_type": "Law Firm",
        "capacity_driver": "labor",
        "sales_modality": "project_based",
        "customer_type": "b2b",
        "unit_cadence": "contract",
        "business_stage": "operating",
      },
    )
    consulting_archetype = _derive_commercial_archetype(
      normalized_traits={
        "business_type": "Consulting Firm",
        "capacity_driver": "labor",
        "sales_modality": "project_based",
        "customer_type": "b2b",
        "unit_cadence": "contract",
        "business_stage": "operating",
      },
    )
    unseen_archetype = _derive_commercial_archetype(
      normalized_traits={
        "business_type": "Blue Rocket Zebra Labs",
        "capacity_driver": "labor",
        "sales_modality": "project_based",
        "customer_type": "b2b",
        "unit_cadence": "contract",
        "business_stage": "operating",
      },
    )

    self.assertEqual(law_archetype, "labor_professional_service")
    self.assertEqual(consulting_archetype, law_archetype)
    self.assertEqual(unseen_archetype, law_archetype)

  def test_growth_enabled_demand_path_staffs_up_before_cutting_units(self) -> None:
    profiles = _solver_profiles(
      state_model={
        "fixed_facts": {
          "sales_modality": "online",
          "capacity_driver": "system",
          "commercial_context": {
            "marketing_role": "primary",
            "marketing_demand_link": True,
            "growth_demand_mode_enabled": True,
            "marketing_up_cap_ratio": 0.45,
            "marketing_down_cap_ratio": 0.30,
            "other_opex_down_cap_ratio": 0.12,
            "other_opex_up_cap_ratio": 0.10,
            "opex_flexibility": "moderate",
          },
        },
        "constraint_profile": {
          "constraint_engine_violations": ["payroll_too_light", "ebitda_margin_too_low"],
        },
      },
    )
    growth_profile = next(item for item in profiles if item.get("profile_id") == "growth_first")
    self.assertTrue(bool((growth_profile.get("constraints") or {}).get("prefer_growth_units")))

    direct_inputs = {
      "current_price": 300.0,
      "price_enabled": True,
      "price_lower": 285.0,
      "price_upper": 315.0,
      "current_util": 0.5,
      "util_min": 0.45,
      "util_max": 0.95,
      "baseline_units": 500.0,
      "capacity_units": 1000.0,
      "units_min": 450.0,
      "units_max": 1000.0,
      "current_marketing": 5000.0,
      "marketing_min": 5000.0,
      "marketing_upper": 12000.0,
      "marketing_support_units_baseline": 500.0,
      "marketing_support_units_min": 500.0,
      "marketing_support_units_max": 1000.0,
      "marketing_units_per_dollar": 0.1,
      "growth_demand_mode_enabled": True,
      "current_other_opex": 15000.0,
      "other_opex_min": 14000.0,
      "other_opex_max": 17000.0,
      "other_opex_enabled": True,
      "payroll_ratio_min": 0.0,
      "payroll_ratio_max": 0.0,
      "opex_ratio_min": 0.0,
      "opex_ratio_max": 0.0,
      "fixed_people_payroll": 60000.0,
      "baseline_planned_payroll": 30000.0,
      "baseline_payroll_support": 90000.0,
      "target_payroll_min_total": 90000.0,
      "target_payroll_max_total": 95000.0,
      "people_payroll_floor": 60000.0,
      "structural_payroll_floor": 90000.0,
      "structural_payroll_base": 90000.0,
      "payroll_support_basis": "role_months",
      "units_per_active_role_month": 30.0,
      "fixed_active_role_months": 12.0,
      "baseline_adjustable_active_months": 6.0,
      "adjustable_role_month_cost_floor": 5000.0,
      "units_per_payroll_dollar": 0.0,
      "role_month_support_profile": [{"month_share": 1.0, "monthly_wage_floor": 5000.0}],
      "hard_utilization_floor": 0.45,
      "constraint_violations": ["payroll_too_light", "ebitda_margin_too_low"],
      "roles": [
        {
          "role_title": "Growth Hire",
          "base_months": 6,
          "min_months": 0,
          "max_months": 6,
          "annual_wage": 60000.0,
          "wage_floor": 60000.0,
          "wage_ceiling": 66000.0,
          "baseline_year1_amount": 30000.0,
        }
      ],
      "constraint_profile": {
        "capacity_curve": {"enabled": True, "basis": "role_months", "units_per_active_role_month": 30.0},
        "demand_curve": {"enabled": True, "units_per_marketing_dollar": 0.1, "baseline_supported_units": 900.0},
      },
      "expected_units": 900.0,
      "required_units_semantic": None,
      "staffing_supported_capacity_semantic": None,
      "demand_supported_units_semantic": None,
      "reachable_market_semantic": None,
      "current_revenue": 150000.0,
      "current_cogs": 45000.0,
      "current_interest": 0.0,
      "current_other_opex_total": 15000.0,
      "current_payroll_total": 90000.0,
      "rent_annualized": 5000.0,
      "current_cogs_ratio": 0.3,
      "cogs_ratio_min": 0.28,
      "cogs_ratio_max": 0.34,
      "solve_mode": "parent_fallback",
      "product_driver_basis": [],
    }

    solution = _solve_direct_profile(
      profile=growth_profile,
      direct_inputs=direct_inputs,
      target_ebitda_min=0.0,
      enforce_blocking_bands=False,
    )

    self.assertIsNotNone(solution)
    self.assertGreaterEqual(_safe_float((solution or {}).get("annual_units_total")), 719.0)
    self.assertGreater(_safe_float((solution or {}).get("marketing_total_year1")), 5000.0)
    self.assertGreater(
      _safe_float((solution or {}).get("structural_payroll_required_total")),
      90000.0,
    )
    self.assertLess((_safe_float(((solution or {}).get("role_months") or {}).get("Growth Hire"))), 6.0)

  def test_local_labor_service_tightens_other_opex_range(self) -> None:
    baseline_summary = build_consistency_financial_summary(
      financials_json={
        "cogs_total_year1": 120000,
        "payroll_total_year1": 180000,
        "marketing_total_year1": 18000,
        "other_operating_expense": 100000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 620000,
        "unit_price": 250,
        "utilization_rate": 0.72,
        "avg_units_per_period_year1": 47.6923,
        "operating_periods_per_year": 52,
      },
    )
    state_model = _build_solver_state_model(
      ops_json={"capacity_driver": "labor", "sales_modality": "project_based"},
      people_json={"future_roles": []},
      financials_json={"marketing_total_year1": 18000, "other_operating_expense": 100000},
      financials_year1_json={
        "company_revenue_total_year1": 620000,
        "unit_price": 250,
        "utilization_rate": 0.72,
        "avg_units_per_period_year1": 47.6923,
        "operating_periods_per_year": 52,
      },
      marketing_model_json={"expected_units_year1": 2480, "reachable_market": 20000},
      normalized_traits={
        "business_type": "Consulting Firm",
        "sales_modality": "project_based",
        "capacity_driver": "labor",
        "customer_type": "b2b",
        "business_stage": "operating",
      },
      baseline_summary=baseline_summary,
      constraint_engine_state={
        "supportable_unit_range": {"min": 1800, "max": 3200},
        "supportable_revenue_range": {"min": 500000, "max": 820000},
        "utilization_range": {"min": 0.6, "max": 0.82},
        "gross_margin_band": {"min": 0.45, "max": 0.75},
        "ebitda_margin_band": {"min": 0.06, "max": 0.18},
        "marketing_intensity_band": {"min": 0.02, "max": 0.08},
        "opex_intensity_band": {"min": 0.10, "max": 0.22},
        "constraint_confidence_score": 0.85,
        "fallback_level": "naics_6",
        "constraints": [],
        "violations": ["ebitda_margin_too_low"],
        "current_metrics": {"capacity_units_year1": 3400.0},
      },
    )

    opex_envelope = ((state_model or {}).get("constraint_profile") or {}).get("other_opex_envelope") or {}
    self.assertEqual(opex_envelope.get("flexibility"), "tight")
    self.assertGreaterEqual(_safe_float(opex_envelope.get("min")), 94000.0)
    self.assertLessEqual(_safe_float(opex_envelope.get("max")), 104000.0)

  def test_build_profile_solver_contract_translates_gpt_strategy_into_feasible_solver_bounds(self) -> None:
    contract = _build_profile_solver_contract(
      state_model={
        "strategy_layer": {
          "source": "gpt",
          "diagnosis": {"primary_cause": "payroll-driven"},
          "strategy_selection": {
            "business_model_assessment": "Home health requires staffing, supported visit capacity, and demand pacing to move together.",
            "required_lever_families": ["hire_delay", "price_up"],
            "forbidden_lever_families": ["payroll_down"],
            "controller_directives": {
              "minimum_meaningful_levers": 3,
              "require_multi_lever_coordination": True,
              "preserve_capacity_staffing_link": True,
              "preserve_price_demand_link": True,
              "preserve_marketing_demand_link": False,
              "prefer_delay_over_delete": True,
              "aggression_level": "high",
              "escalate_on_retry": True,
              "minimum_package_count": 1,
            },
            "target_margin_path": {
              "year1_min": -0.70,
              "year1_max": -0.25,
              "year2_min": -0.20,
              "year2_max": 0.02,
              "year3_min": 0.04,
              "year3_max": 0.12,
            },
            "target_posture": {
              "year1_ebitda_posture": "still_negative_but_improving",
              "year2_ebitda_posture": "moving_toward_break_even",
              "year3_ebitda_posture": "credible_viability",
              "staffing_posture": "phased",
              "pricing_posture": "disciplined",
              "demand_posture": "measured",
              "cost_posture": "controlled",
            },
            "coordinated_lever_packages": [
              {
                "quarter_start": 1,
                "quarter_end": 4,
                "levers": ["hire_delay", "price_up", "util_down"],
                "expected_effects": ["capacity_tighter_until_hires", "demand_softens_with_price"],
                "minimum_strength": "strong",
                "rationale": "Early staffing delays should be paired with lower throughput expectations and modest price support.",
              }
            ],
          },
        }
      },
      direct_inputs={
        "current_revenue": 218400.0,
        "baseline_units": 1456.0,
        "units_min": 1383.2,
        "units_max": 1580.8,
        "current_price": 150.0,
        "price_lower": 150.0,
        "price_upper": 172.5,
        "current_cogs_ratio": 0.64,
        "cogs_ratio_min": 0.60,
        "cogs_ratio_max": 0.68,
        "marketing_min": 17472.0,
        "marketing_upper": 21000.0,
        "current_other_opex": 1000.0,
        "other_opex_min": 48155.016,
        "other_opex_max": 48155.016,
        "rent_annualized": 0.0,
        "current_interest": 0.0,
        "fixed_people_payroll": 200440.0,
        "baseline_planned_payroll": 220902.5,
        "baseline_payroll_support": 421342.5,
        "people_payroll_floor": 200440.0,
        "structural_payroll_floor": 421342.5,
        "structural_payroll_base": 421342.5,
        "target_payroll_min_total": 200440.0,
        "target_payroll_max_total": 404752.875,
        "constraint_violations": [
          "ebitda_margin_too_low",
          "payroll_too_heavy",
          "opex_too_light",
        ],
        "roles": [
          {
            "role_title": "RN",
            "base_months": 0,
            "min_months": 0,
            "max_months": 24,
            "annual_wage": 81820.0,
            "baseline_year1_amount": 81820.0,
          },
          {
            "role_title": "PT",
            "base_months": 0,
            "min_months": 0,
            "max_months": 24,
            "annual_wage": 55000.0,
            "baseline_year1_amount": 55000.0,
          },
          {
            "role_title": "Billing / Compliance",
            "base_months": 0,
            "min_months": 0,
            "max_months": 24,
            "annual_wage": 42000.0,
            "baseline_year1_amount": 42000.0,
          },
          {
            "role_title": "Intake / Scheduling",
            "base_months": 0,
            "min_months": 0,
            "max_months": 24,
            "annual_wage": 42082.5,
            "baseline_year1_amount": 42082.5,
          },
        ],
      },
      profile={
        "strategy_id": "viability_stabilize",
        "profile_id": "operations_first",
        "strategy_source": "gpt",
        "allowed_levers": ["price_up", "hire_delay"],
        "constraints": {
          "price_up_cap_ratio": 0.15,
          "hire_delay_max_months_total": 24.0,
          "other_opex_down_cap_ratio": 0.05,
        },
        "forecast_orchestration": {
          "role_timing_overrides": [
            {"role_title": "RN", "months_until_activate": 6},
            {"role_title": "PT", "months_until_activate": 18},
            {"role_title": "Billing / Compliance", "months_until_activate": 18},
            {"role_title": "Intake / Scheduling", "months_until_activate": 18},
          ]
        },
      },
      target_ebitda_min=-152880.0,
      target_ebitda_max=-65520.0,
    )

    contract_inputs = contract["direct_inputs"]
    contract_profile = contract["profile"]
    diagnostics = contract["diagnostics"]

    self.assertEqual(_safe_float(contract_inputs["structural_payroll_floor"]), 200440.0)
    self.assertAlmostEqual(_safe_float(contract_inputs["target_payroll_max_total"]), 241350.0, places=2)
    self.assertEqual(_safe_float(contract_inputs["other_opex_min"]), 950.0)
    self.assertEqual(_safe_float(contract_inputs["other_opex_max"]), 1000.0)
    self.assertIn("price_up", contract_profile["allowed_levers"])
    self.assertIn("hire_delay", contract_profile["allowed_levers"])
    self.assertIn("util_down", contract_profile["allowed_levers"])
    self.assertNotIn("payroll_down", contract_profile["allowed_levers"])
    self.assertGreaterEqual(_safe_float((contract_profile.get("constraints") or {}).get("util_down_cap_ratio")), 0.08)
    self.assertEqual((contract_profile.get("controller_directives") or {}).get("minimum_meaningful_levers"), 3)
    self.assertEqual(_safe_float(contract["target_ebitda_min"]), -152880.0)
    self.assertEqual(_safe_float(contract["target_ebitda_max"]), -65520.0)
    self.assertIn("translated_gpt_role_timing_into_payroll_contract", diagnostics["adjustments"])
    self.assertNotIn("relaxed_unreachable_target_ebitda_band", diagnostics["adjustments"])
    self.assertNotIn("target_ebitda_min_exceeds_contract_upper_bound", diagnostics["issues"])
    self.assertIn("util_down", ((diagnostics.get("controller_profile") or {}).get("effective_lever_families") or []))
    self.assertIn("util_down", ((diagnostics.get("controller_profile") or {}).get("package_lever_families") or []))
    self.assertIn("capacity_tighter_until_hires", ((diagnostics.get("controller_profile") or {}).get("package_expected_effects") or []))
    self.assertEqual((diagnostics.get("controller_profile") or {}).get("retry_attempt"), 0)

  def test_build_profile_solver_contract_escalates_on_retry_for_gpt_blueprint(self) -> None:
    contract = _build_profile_solver_contract(
      state_model={
        "strategy_layer": {
          "source": "gpt",
          "diagnosis": {"primary_cause": "pricing-driven", "governed_retry_attempt": 2},
          "strategy_selection": {
            "business_model_assessment": "The business needs a stronger coordinated repricing and demand reset to become credible.",
            "required_lever_families": ["price_up", "util_down"],
            "forbidden_lever_families": ["payroll_down"],
            "controller_directives": {
              "minimum_meaningful_levers": 2,
              "require_multi_lever_coordination": True,
              "preserve_capacity_staffing_link": False,
              "preserve_price_demand_link": True,
              "preserve_marketing_demand_link": False,
              "prefer_delay_over_delete": True,
              "aggression_level": "high",
              "escalate_on_retry": True,
              "minimum_package_count": 1,
            },
            "target_margin_path": {
              "year1_min": -0.10,
              "year1_max": 0.02,
              "year2_min": 0.05,
              "year2_max": 0.10,
              "year3_min": 0.10,
              "year3_max": 0.18,
            },
            "target_posture": {
              "year1_ebitda_posture": "near_break_even",
              "year2_ebitda_posture": "positive",
              "year3_ebitda_posture": "stable_positive",
              "staffing_posture": "measured",
              "pricing_posture": "disciplined",
              "demand_posture": "slightly_softened",
              "cost_posture": "controlled",
            },
            "coordinated_lever_packages": [
              {
                "quarter_start": 1,
                "quarter_end": 4,
                "levers": ["price_up", "util_down"],
                "expected_effects": ["demand_softens_with_price"],
                "minimum_strength": "strong",
                "rationale": "Retry should lean harder into a coordinated reprice and demand reset.",
              }
            ],
          },
        }
      },
      direct_inputs={
        "current_revenue": 300000.0,
        "baseline_units": 2500.0,
        "units_min": 2300.0,
        "units_max": 3200.0,
        "current_price": 120.0,
        "price_lower": 118.0,
        "price_upper": 132.0,
        "current_cogs_ratio": 0.55,
        "cogs_ratio_min": 0.50,
        "cogs_ratio_max": 0.60,
        "marketing_min": 12000.0,
        "marketing_upper": 18000.0,
        "current_other_opex": 22000.0,
        "other_opex_min": 21000.0,
        "other_opex_max": 23000.0,
        "rent_annualized": 0.0,
        "current_interest": 0.0,
        "fixed_people_payroll": 70000.0,
        "baseline_planned_payroll": 0.0,
        "baseline_payroll_support": 70000.0,
        "people_payroll_floor": 70000.0,
        "structural_payroll_floor": 70000.0,
        "structural_payroll_base": 70000.0,
        "target_payroll_min_total": 70000.0,
        "target_payroll_max_total": 85000.0,
        "constraint_violations": ["ebitda_margin_too_low"],
        "roles": [],
      },
      profile={
        "strategy_id": "pricing_adjustment",
        "profile_id": "pricing_adjustment",
        "strategy_source": "gpt",
        "allowed_levers": ["price_up", "util_down"],
        "constraints": {
          "price_up_cap_ratio": 0.12,
          "util_down_cap_ratio": 0.08,
          "units_min_ratio": 0.95,
        },
        "forecast_orchestration": {},
      },
      target_ebitda_min=-30000.0,
      target_ebitda_max=6000.0,
    )

    constraints = (contract.get("profile") or {}).get("constraints") or {}
    diagnostics = contract.get("diagnostics") or {}
    self.assertGreaterEqual(_safe_float(constraints.get("price_up_cap_ratio")), 0.20)
    self.assertGreaterEqual(_safe_float(constraints.get("util_down_cap_ratio")), 0.15)
    self.assertLessEqual(_safe_float(constraints.get("units_min_ratio")), 0.91)
    self.assertEqual((diagnostics.get("controller_profile") or {}).get("retry_attempt"), 2)

  def test_build_profile_solver_contract_carries_gpt_multi_lever_packages_into_numeric_contract(self) -> None:
    contract = _build_profile_solver_contract(
      state_model={
        "strategy_layer": {
          "source": "gpt",
          "diagnosis": {
            "primary_cause": "payroll-driven",
            "target_margin_path": {
              "year1_min": -0.22,
              "year1_max": -0.10,
              "year2_min": -0.12,
              "year2_max": -0.02,
              "year3_min": -0.03,
              "year3_max": 0.05,
            },
          },
          "strategy_selection": {
            "selected_strategy_ids": ["demand_supported_growth"],
            "business_model_assessment": "Home health needs support overhead first and demand growth only after staffing catches up.",
            "required_lever_families": ["staffing_support"],
            "forbidden_lever_families": [],
            "controller_directives": {
              "require_multi_lever_coordination": True,
              "preserve_marketing_demand_link": True,
              "preserve_capacity_staffing_link": True,
              "minimum_meaningful_levers": 4,
            },
            "target_posture": {
              "year1": "stabilize",
              "year2": "build",
              "year3": "approach_viability",
            },
            "target_margin_path": {
              "year1_min": -0.22,
              "year1_max": -0.10,
              "year2_min": -0.12,
              "year2_max": -0.02,
              "year3_min": -0.03,
              "year3_max": 0.05,
            },
            "coordinated_lever_packages": [
              {
                "quarter_start": 1,
                "quarter_end": 4,
                "minimum_strength": "strong",
                "levers": ["hire_advance", "payroll_up", "opex_up"],
                "expected_effects": [
                  "support overhead rises with staffing",
                  "capacity expands with staffing",
                ],
              },
              {
                "quarter_start": 5,
                "quarter_end": 12,
                "minimum_strength": "moderate",
                "levers": ["marketing_to_demand_link", "utilization_adjustment"],
                "expected_effects": [
                  "demand growth requires marketing support",
                  "utilization gradually increases after hiring",
                ],
              },
            ],
          },
        }
      },
      direct_inputs={
        "current_revenue": 600000.0,
        "current_other_opex": 1200.0,
        "other_opex_min": 1200.0,
        "other_opex_max": 1200.0,
        "opex_ratio_min": 0.08,
        "opex_ratio_max": 0.16,
        "rent_annualized": 0.0,
        "current_marketing": 10000.0,
        "marketing_min": 10000.0,
        "marketing_upper": 10000.0,
        "constraint_violations": ["opex_too_light", "payroll_too_light", "capacity_unsupported"],
      },
      profile={
        "strategy_id": "demand_supported_growth",
        "strategy_source": "gpt",
        "allowed_levers": ["hire_advance", "payroll_up"],
        "constraints": {"payroll_up_max_ratio": 0.10},
        "forecast_orchestration": {},
      },
      target_ebitda_min=-120000.0,
      target_ebitda_max=-40000.0,
    )

    diagnostics = contract.get("diagnostics") or {}
    controller_profile = diagnostics.get("controller_profile") or {}
    allowed_levers = set(controller_profile.get("effective_lever_families") or [])
    orchestration = (contract.get("profile") or {}).get("forecast_orchestration") or {}
    policies = orchestration.get("quarter_policies") or []

    self.assertIn("other_opex_up", allowed_levers)
    self.assertIn("marketing_up", allowed_levers)
    self.assertIn("util_up", allowed_levers)
    self.assertGreater(_safe_float((contract.get("direct_inputs") or {}).get("other_opex_max")), 1200.0)
    self.assertGreater(_safe_float((contract.get("direct_inputs") or {}).get("marketing_upper")), 10000.0)
    self.assertGreaterEqual(len(policies), 2)
    self.assertIn("expanded_opex_contract_to_realism_band", diagnostics.get("adjustments") or [])
    self.assertIn("expanded_marketing_contract_for_demand_support", diagnostics.get("adjustments") or [])
    self.assertFalse(
      {
        "missing_required_lever_families",
        "missing_package_lever_families",
        "missing_package_orchestration",
        "untranslated_support_opex_effect",
        "untranslated_marketing_support_effect",
        "untranslated_staffing_capacity_effect",
      }.intersection(set(diagnostics.get("issues") or []))
    )

  def test_build_profile_solver_contract_accepts_broad_gpt_business_lever_families(self) -> None:
    contract = _build_profile_solver_contract(
      state_model={
        "strategy_layer": {
          "source": "gpt",
          "diagnosis": {"primary_cause": "pricing-driven"},
          "strategy_selection": {
            "selected_strategy_ids": ["viability_stabilize", "pricing_adjustment"],
            "business_model_assessment": "The business needs moderate repricing, paced staffing, and realistic support overhead.",
            "required_lever_families": [
              "pricing",
              "utilization",
              "hiring_timing_and_structural_payroll",
              "overhead_opex",
            ],
            "forbidden_lever_families": [],
            "controller_directives": {
              "minimum_meaningful_levers": 3,
              "require_multi_lever_coordination": True,
              "preserve_capacity_staffing_link": True,
              "preserve_price_demand_link": True,
              "preserve_marketing_demand_link": True,
              "prefer_delay_over_delete": True,
              "aggression_level": "high",
              "escalate_on_retry": True,
              "minimum_package_count": 2,
            },
            "target_margin_path": {
              "year1_min": -0.22,
              "year1_max": -0.12,
              "year2_min": -0.15,
              "year2_max": -0.05,
              "year3_min": -0.05,
              "year3_max": 0.05,
            },
            "target_posture": {
              "year1_ebitda_posture": "stabilize severe losses",
              "year2_ebitda_posture": "narrow losses",
              "year3_ebitda_posture": "approach break-even",
              "staffing_posture": "delay non-essential support roles and pace activations with demand",
              "pricing_posture": "moderate price increases inside payer norms",
              "demand_posture": "moderate growth tied to supportable capacity",
              "cost_posture": "increase support overhead to realistic levels while trimming avoidable spend",
            },
            "coordinated_lever_packages": [
              {
                "quarter_start": 1,
                "quarter_end": 4,
                "levers": ["pricing", "hiring_timing_and_structural_payroll", "overhead_opex"],
                "expected_effects": [
                  "support overhead rises with staffing",
                  "capacity expands with staffing",
                ],
                "minimum_strength": "strong",
                "rationale": "Correct the overbuilt leadership structure and early support burden.",
              },
              {
                "quarter_start": 5,
                "quarter_end": 12,
                "levers": ["utilization", "marketing_to_demand_link"],
                "expected_effects": [
                  "demand growth requires marketing support",
                  "utilization gradually increases after hiring",
                ],
                "minimum_strength": "moderate",
                "rationale": "Grow into a better cost base after capacity is in place.",
              },
            ],
          },
        }
      },
      direct_inputs={
        "current_revenue": 560000.0,
        "current_other_opex": 15000.0,
        "other_opex_min": 15000.0,
        "other_opex_max": 15000.0,
        "opex_ratio_min": 0.08,
        "opex_ratio_max": 0.18,
        "rent_annualized": 0.0,
        "current_marketing": 24000.0,
        "marketing_min": 24000.0,
        "marketing_upper": 24000.0,
        "constraint_violations": ["opex_too_light", "payroll_too_heavy", "capacity_unsupported"],
        "current_payroll_total": 420000.0,
        "fixed_people_payroll": 250000.0,
        "structural_payroll_floor": 250000.0,
        "target_payroll_min_total": 250000.0,
        "target_payroll_max_total": 420000.0,
        "roles": [],
      },
      profile={
        "strategy_id": "viability_stabilize",
        "strategy_source": "gpt",
        "allowed_levers": ["price_up"],
        "constraints": {"price_up_cap_ratio": 0.08},
        "forecast_orchestration": {},
      },
      target_ebitda_min=-120000.0,
      target_ebitda_max=-60000.0,
    )

    diagnostics = contract.get("diagnostics") or {}
    controller_profile = diagnostics.get("controller_profile") or {}
    effective = set(controller_profile.get("effective_lever_families") or [])

    self.assertTrue({"price_up", "util_up", "util_down", "hire_advance", "hire_delay", "payroll_up", "payroll_down", "other_opex_up", "other_opex_down"}.intersection(effective))
    self.assertNotIn("missing_required_lever_families", diagnostics.get("issues") or [])
    self.assertNotIn("missing_package_lever_families", diagnostics.get("issues") or [])

  def test_build_profile_solver_contract_marks_unreachable_gpt_target_path_as_underpowered(self) -> None:
    contract = _build_profile_solver_contract(
      state_model={
        "strategy_layer": {
          "source": "gpt",
          "diagnosis": {
            "primary_cause": "pricing-driven",
            "severity_class": "severe",
            "minimum_package_strength": "strong",
          },
          "strategy_selection": {
            "selected_strategy_ids": ["pricing_adjustment"],
            "business_model_assessment": "Broken economics require a strong restructuring path.",
            "severity_class": "severe",
            "severity_reason": "Year 1 economics are structurally non-viable.",
            "minimum_package_strength": "strong",
            "required_lever_families": ["price_up", "cogs_down", "other_opex_down", "hire_delay"],
            "forbidden_lever_families": [],
            "controller_directives": {
              "minimum_meaningful_levers": 4,
              "require_multi_lever_coordination": True,
              "preserve_capacity_staffing_link": True,
              "preserve_price_demand_link": True,
              "preserve_marketing_demand_link": True,
              "prefer_delay_over_delete": True,
              "aggression_level": "high",
              "escalate_on_retry": True,
              "minimum_package_count": 2,
            },
            "target_margin_path": {
              "year1_min": -0.20,
              "year1_max": -0.10,
              "year2_min": -0.10,
              "year2_max": 0.00,
              "year3_min": 0.00,
              "year3_max": 0.08,
            },
            "target_posture": {
              "year1_ebitda_posture": "stabilize",
              "year2_ebitda_posture": "narrow losses",
              "year3_ebitda_posture": "approach breakeven",
              "staffing_posture": "delay",
              "pricing_posture": "raise price",
              "demand_posture": "paced",
              "cost_posture": "tighten",
            },
            "coordinated_lever_packages": [
              {
                "quarter_start": 1,
                "quarter_end": 8,
                "levers": ["price_up", "cogs_down", "other_opex_down", "hire_delay"],
                "expected_effects": ["support overhead rises with staffing"],
                "minimum_strength": "strong",
                "rationale": "Reset unit economics and delay overbuild.",
              },
              {
                "quarter_start": 9,
                "quarter_end": 20,
                "levers": ["price_up", "util_up", "cogs_down"],
                "expected_effects": ["costs scale with growth"],
                "minimum_strength": "moderate",
                "rationale": "Improve later-year economics gradually.",
              },
            ],
          },
        }
      },
      direct_inputs={
        "current_revenue": 312000.0,
        "baseline_units": 3900.0,
        "units_min": 3600.0,
        "units_max": 4200.0,
        "current_price": 80.0,
        "price_lower": 80.0,
        "price_upper": 88.0,
        "cogs_ratio_min": 0.72,
        "cogs_ratio_max": 0.78,
        "target_payroll_min_total": 249990.0,
        "target_payroll_max_total": 260000.0,
        "structural_payroll_floor": 249990.0,
        "marketing_min": 40000.0,
        "marketing_upper": 45000.0,
        "other_opex_min": 90000.0,
        "other_opex_max": 110000.0,
        "rent_annualized": 14400.0,
        "current_interest": 0.0,
        "constraint_violations": ["gross_margin_too_low", "ebitda_margin_too_low"],
        "roles": [],
      },
      profile={
        "strategy_id": "pricing_adjustment",
        "strategy_source": "gpt",
        "allowed_levers": ["price_up", "cogs_down", "other_opex_down", "hire_delay"],
        "constraints": {"price_up_cap_ratio": 0.10, "cogs_down_cap_ratio": 0.02, "other_opex_down_cap_ratio": 0.04},
        "forecast_orchestration": {},
      },
      target_ebitda_min=-62400.0,
      target_ebitda_max=-31200.0,
    )

    diagnostics = contract.get("diagnostics") or {}
    self.assertIn("target_ebitda_min_exceeds_contract_upper_bound", diagnostics.get("issues") or [])
    self.assertIn("underpowered_gpt_target_path", diagnostics.get("issues") or [])

  def test_presentation_issues_reject_all_negative_degrading_target_path(self) -> None:
    issues = _presentation_issues(
      {
        "scenario_id": "home-health-weak",
        "archetype": "operations",
        "label": "Operational balance",
        "rationale": "This path stabilizes early operations but is still commercially weak.",
        "lever_families": ["payroll", "other_opex", "marketing"],
        "remaining_blocking_count": 0,
        "remaining_violation_count": 0,
        "realism_distance": 0.02,
        "target_distance": 0.02,
        "distortion_total": 0.3,
        "disruption_score": 0.3,
        "forecast_years": [
          {"year_index": 1, "revenue": 600000.0, "ebitda": -140000.0},
          {"year_index": 2, "revenue": 620000.0, "ebitda": -155000.0},
          {"year_index": 3, "revenue": 650000.0, "ebitda": -175000.0},
          {"year_index": 4, "revenue": 675000.0, "ebitda": -195000.0},
          {"year_index": 5, "revenue": 700000.0, "ebitda": -210000.0},
        ],
      },
      state_model={
        "strategy_layer": {
          "diagnosis": {
            "target_margin_path": {
              "year1_min": -0.22,
              "year1_max": -0.10,
              "year2_min": -0.12,
              "year2_max": -0.02,
              "year3_min": -0.03,
              "year3_max": 0.05,
            }
          }
        }
      },
    )

    self.assertIn("all_negative_five_year_path", issues)
    self.assertIn("degrading_five_year_path", issues)
    self.assertIn("target_path_miss", issues)

  def test_presentation_issues_flag_absorber_story_for_local_labor_business(self) -> None:
    issues = _presentation_issues(
      {
        "archetype": "operations",
        "label": "Operational balance: Set Year-1 marketing to $55,000 + Set other operating expense to $22,000",
        "rationale": "This path reset the Year-1 marketing ramp, and rebalances staffing, workload, and timing to make operations believable.",
        "summary": {"revenue": 300000, "marketing": 55000},
        "lever_families": ["marketing", "other_opex"],
        "meaningful_families": ["marketing", "other_opex"],
        "exact_patches": {
          "financials_patch": {"other_operating_expense": 22000},
          "marketing_model_patch": {"expected_units_year1": 1800},
        },
      },
      state_model={
        "fixed_facts": {
          "sales_modality": "local_service",
          "capacity_driver": "labor",
          "commercial_context": {"marketing_role": "constrained"},
        },
        "constraint_profile": {"utilization_envelope": {"min": 0.55}},
      },
    )

    self.assertIn("marketing_absorber_story", issues)
    self.assertIn("commercial_absorber_story", issues)

  def test_solver_profiles_reduce_marketing_and_opex_as_first_line_local_service_levers(self) -> None:
    state_model = {
      "fixed_facts": {
        "sales_modality": "local_service",
        "capacity_driver": "labor",
        "commercial_context": {
          "marketing_role": "constrained",
          "marketing_up_cap_ratio": 0.06,
          "marketing_down_cap_ratio": 0.25,
          "opex_flexibility": "tight",
          "other_opex_down_cap_ratio": 0.06,
          "other_opex_up_cap_ratio": 0.04,
        },
      },
      "constraint_profile": {
        "constraint_engine_violations": ["ebitda_margin_too_low"],
      },
      "objective_policy": {
        "distortion_weights": {
          "price_up": 18.0,
          "price_down": 24.0,
          "util_up": 4.0,
          "util_down": 4.0,
          "marketing_up": 4.0,
          "marketing_down": 5.0,
          "other_opex_down": 2.0,
          "other_opex_up": 2.0,
          "cogs_down": 1.5,
          "cogs_up": 1.5,
          "hire_delay": 6.0,
          "hire_advance": 3.5,
          "payroll_down": 8.0,
          "payroll_up": 3.5,
        },
      },
    }

    profiles = _solver_profiles(state_model=state_model)
    ops_profile = next(item for item in profiles if item.get("profile_id") == "operations_first")
    growth_profile = next(item for item in profiles if item.get("profile_id") == "growth_first")

    self.assertGreater(_safe_float(ops_profile["weights"]["marketing_up"]), _safe_float(growth_profile["weights"]["marketing_up"]))
    self.assertGreater(_safe_float(ops_profile["weights"]["other_opex_down"]), 2.0)
    self.assertLess(_safe_float(ops_profile["constraints"]["marketing_up_cap_ratio"]), _safe_float(growth_profile["constraints"]["marketing_up_cap_ratio"]))

  def test_label_and_rationale_call_out_marketing_heavy_path(self) -> None:
    label, rationale, families = _label_and_rationale_from_patches(
      {
        "marketing_model_patch": {"expected_units_year1": 4000},
        "financials_patch": {"marketing_total_year1": 60000},
      },
      archetype="growth",
      archetype_display="Growth path",
      dominant_tradeoff="keeps more of the revenue plan while leaning on marketing support",
    )

    self.assertIn("Growth path:", label)
    self.assertIn("Marketing-heavy path", label)
    self.assertIn("marketing", families)
    self.assertIn("leans more heavily on marketing", rationale)

  def test_label_and_rationale_reflect_operations_archetype(self) -> None:
    label, rationale, families = _label_and_rationale_from_patches(
      {
        "financials_year1_patch": {"utilization_rate": 0.68},
        "people_role_updates": [{"role_title": "Paralegal", "months_until_hire": 3}],
      },
      archetype="operations",
      archetype_display="Operational balance",
      dominant_tradeoff="rebalances staffing, workload, and timing to make operations believable",
    )

    self.assertIn("Operational balance:", label)
    self.assertIn("utilization", families)
    self.assertIn("hire_delay", families)
    self.assertIn("rebalances staffing, workload, and timing", rationale)

  def test_growth_candidate_gets_growth_posture_and_consistency(self) -> None:
    candidate = {
      "archetype": "growth",
      "meaningful_families": ["marketing", "payroll", "utilization"],
      "lever_families": ["marketing", "payroll", "utilization"],
      "baseline_required_units": 500.0,
      "baseline_expected_units": 500.0,
      "scenario_required_units": 720.0,
      "scenario_expected_units": 900.0,
      "baseline_revenue": 150000.0,
      "scenario_revenue": 216000.0,
      "lever_summary": {
        "raw_family_moves": {
          "marketing_up": 0.2,
          "payroll_up": 0.18,
          "hire_advance": 0.2,
          "util_up": 0.12,
        },
        "dominant_family": "marketing",
      },
    }

    candidate.update(_derive_scenario_posture(candidate))
    consistency = _archetype_consistency(candidate)

    self.assertEqual(candidate["demand_posture"], "preserve")
    self.assertEqual(candidate["staffing_posture"], "add_support")
    self.assertEqual(candidate["cost_posture"], "protect")
    self.assertGreater(_safe_float(consistency.get("archetype_consistency_score")), 3.0)
    self.assertFalse(consistency.get("archetype_consistency_issues"))

  def test_archetype_mismatch_is_flagged_for_efficiency_marketing_story(self) -> None:
    candidate = {
      "archetype": "efficiency",
      "label": "Efficiency path: Reset Year-1 marketing support",
      "rationale": "This path keeps more of the Year-1 demand in place and accepts support spend where it remains credible.",
      "meaningful_families": ["marketing", "utilization"],
      "lever_families": ["marketing", "utilization"],
      "baseline_required_units": 500.0,
      "baseline_expected_units": 500.0,
      "scenario_required_units": 650.0,
      "scenario_expected_units": 700.0,
      "baseline_revenue": 150000.0,
      "scenario_revenue": 190000.0,
      "lever_summary": {
        "raw_family_moves": {
          "marketing_up": 0.24,
          "util_up": 0.08,
        },
        "dominant_family": "marketing",
      },
      "summary": {"revenue": 190000, "marketing": 42000},
      "exact_patches": {
        "marketing_model_patch": {"expected_units_year1": 700},
      },
    }
    candidate.update(_derive_scenario_posture(candidate))
    candidate.update(_archetype_consistency(candidate))

    issues = _presentation_issues(
      candidate,
      state_model={
        "fixed_facts": {
          "sales_modality": "online",
          "capacity_driver": "system",
          "commercial_context": {"marketing_role": "primary"},
        },
        "constraint_profile": {"utilization_envelope": {"min": 0.4}},
      },
    )

    self.assertIn("archetype_mismatch", issues)
    self.assertIn("weak_archetype_identity", issues)

  def test_growth_archetype_requires_demand_and_staffing_mix(self) -> None:
    candidate = {
      "archetype": "growth",
      "meaningful_families": ["marketing"],
      "lever_families": ["marketing"],
      "baseline_required_units": 500.0,
      "baseline_expected_units": 500.0,
      "scenario_required_units": 700.0,
      "scenario_expected_units": 700.0,
      "baseline_revenue": 150000.0,
      "scenario_revenue": 190000.0,
      "lever_summary": {
        "raw_family_moves": {"marketing_up": 0.4},
        "dominant_family": "marketing",
        "dominant_family_share": 1.0,
        "coordination_issues": ["demand_without_staffing"],
      },
    }

    candidate.update(_derive_scenario_posture(candidate))
    consistency = _archetype_consistency(candidate)

    self.assertIn("growth_missing_staffing_support", consistency["archetype_consistency_issues"])
    self.assertIn("single_lever_dominance", consistency["archetype_consistency_issues"])

  def test_select_materially_distinct_scenarios_prefers_archetype_diversity(self) -> None:
    selected = _select_materially_distinct_scenarios(
      [
        {
          "scenario_id": "1",
          "solution_profile_id": "balanced",
          "archetype": "operations",
          "dominant_tradeoff": "ops",
          "lever_families": ["utilization", "payroll"],
          "exact_patches": {"financials_year1_patch": {"utilization_rate": 0.7}},
          "remaining_blocking_count": 0,
          "remaining_violation_count": 0,
          "realism_distance": 0.01,
          "target_distance": 0.01,
          "distortion_total": 0.2,
          "disruption_score": 0.2,
          "ebitda": 10000,
        },
        {
          "scenario_id": "2",
          "solution_profile_id": "operations_first",
          "archetype": "operations",
          "dominant_tradeoff": "ops-two",
          "lever_families": ["utilization", "payroll"],
          "exact_patches": {"financials_year1_patch": {"utilization_rate": 0.705}},
          "remaining_blocking_count": 0,
          "remaining_violation_count": 0,
          "realism_distance": 0.02,
          "target_distance": 0.02,
          "distortion_total": 0.25,
          "disruption_score": 0.25,
          "ebitda": 9800,
        },
        {
          "scenario_id": "3",
          "solution_profile_id": "growth_first",
          "archetype": "growth",
          "dominant_tradeoff": "growth",
          "lever_families": ["marketing", "utilization"],
          "exact_patches": {"marketing_model_patch": {"expected_units_year1": 4400}},
          "remaining_blocking_count": 0,
          "remaining_violation_count": 0,
          "realism_distance": 0.015,
          "target_distance": 0.015,
          "distortion_total": 0.22,
          "disruption_score": 0.22,
          "ebitda": 9900,
        },
        {
          "scenario_id": "4",
          "solution_profile_id": "profit_first",
          "archetype": "efficiency",
          "dominant_tradeoff": "efficiency",
          "lever_families": ["other_opex", "cogs"],
          "exact_patches": {"financials_patch": {"other_operating_expense": 28000}},
          "remaining_blocking_count": 0,
          "remaining_violation_count": 0,
          "realism_distance": 0.018,
          "target_distance": 0.018,
          "distortion_total": 0.24,
          "disruption_score": 0.24,
          "ebitda": 9950,
        },
      ]
    )

    self.assertEqual(len(selected), 3)
    self.assertEqual({item["archetype"] for item in selected}, {"operations", "growth", "efficiency"})

  def test_build_lever_summary_tracks_meaningful_multi_lever_moves(self) -> None:
    summary = _build_lever_summary(
      exact_patches={
        "financials_year1_patch": {
          "product_overrides": {
            "services::advisory": {"unit_price": 2100, "utilization_rate": 0.74},
            "services::audit": {"avg_units_per_period_year1": 18},
          }
        },
        "financials_patch": {
          "other_operating_expense": 42000,
          "cogs_total_year1": 96000,
        },
        "marketing_model_patch": {"expected_units_year1": 1800},
        "people_role_updates": [{"role_title": "Analyst", "months_until_hire": 3, "annual_wage": 85000}],
      },
      family_raw_components={
        "price_up": 0.02,
        "util_down": 0.06,
        "marketing_down": 0.08,
        "other_opex_down": 0.1,
        "cogs_up": 0.04,
        "hire_advance": 0.12,
        "payroll_up": 0.05,
      },
    )

    self.assertGreaterEqual(summary["meaningful_lever_count"], 5)
    self.assertIn("price", summary["meaningful_families"])
    self.assertIn("utilization", summary["meaningful_families"])
    self.assertIn("payroll", summary["meaningful_families"])
    self.assertEqual(summary["changed_products"], 2)
    self.assertGreater(summary["coordination_score"], 5.0)
    self.assertLess(_safe_float(summary["dominant_family_share"]), 0.72)
    self.assertGreaterEqual(summary["aligned_pair_count"], 2)
    self.assertFalse(summary["coordination_issues"])

  def test_build_lever_summary_flags_single_lever_dominance_and_disconnected_moves(self) -> None:
    summary = _build_lever_summary(
      exact_patches={
        "marketing_model_patch": {"expected_units_year1": 2600},
      },
      family_raw_components={
        "marketing_up": 0.9,
        "util_up": 0.01,
      },
    )

    self.assertEqual(summary["meaningful_lever_count"], 1)
    self.assertGreater(_safe_float(summary["dominant_family_share"]), 0.72)
    self.assertIn("demand_without_staffing", summary["coordination_issues"])

  def test_presentation_issues_flag_bizarre_marketing_and_child_parent_conflict(self) -> None:
    issues = _presentation_issues(
      {
        "archetype": "operations",
        "label": "Operational balance: Set Year-1 marketing to $90,000",
        "rationale": "This path reset the Year-1 marketing ramp, and rebalances staffing, workload, and timing to make operations believable.",
        "summary": {"revenue": 300000, "marketing": 90000},
        "exact_patches": {
          "financials_year1_patch": {
            "unit_price": 120,
            "product_overrides": {
              "care::private duty": {"unit_price": 118, "utilization_rate": 0.66},
            },
          }
        },
        "forecast_engine_state": {"starting_state": {"utilization": 0.5}},
      },
      state_model={
        "fixed_facts": {"sales_modality": "local_service", "capacity_driver": "labor"},
        "constraint_profile": {"utilization_envelope": {"min": 0.55}},
      },
    )

    self.assertIn("bizarre_marketing", issues)
    self.assertIn("child_parent_contradiction", issues)

  def test_select_client_ready_scenarios_filters_near_clones_and_weak_options(self) -> None:
    selected = _select_client_ready_scenarios(
      [
        {
          "scenario_id": "1",
          "solution_profile_id": "balanced",
          "archetype": "operations",
          "dominant_tradeoff": "rebalances staffing, workload, and timing to make operations believable",
          "label": "Operational balance: Set utilization to 68%",
          "rationale": "This path reset utilization to a more supportable level, and rebalances staffing, workload, and timing to make operations believable.",
          "lever_families": ["utilization", "payroll"],
          "summary": {"revenue": 300000, "marketing": 18000},
          "exact_patches": {
            "financials_year1_patch": {"utilization_rate": 0.68},
            "people_role_updates": [{"role_title": "Coordinator", "months_until_hire": 4}],
          },
          "remaining_blocking_count": 0,
          "remaining_violation_count": 0,
          "realism_distance": 0.01,
          "target_distance": 0.01,
          "distortion_total": 0.2,
          "disruption_score": 0.2,
          "ebitda": 10000,
        },
        {
          "scenario_id": "2",
          "solution_profile_id": "operations_first",
          "archetype": "operations",
          "dominant_tradeoff": "rebalances staffing, workload, and timing to make operations believable",
          "label": "Operational balance: Set utilization to 68.5%",
          "rationale": "This path reset utilization to a more supportable level, and rebalances staffing, workload, and timing to make operations believable.",
          "lever_families": ["utilization", "payroll"],
          "summary": {"revenue": 301000, "marketing": 18100},
          "exact_patches": {"financials_year1_patch": {"utilization_rate": 0.685}},
          "remaining_blocking_count": 0,
          "remaining_violation_count": 0,
          "realism_distance": 0.011,
          "target_distance": 0.011,
          "distortion_total": 0.21,
          "disruption_score": 0.21,
          "ebitda": 10050,
        },
        {
          "scenario_id": "3",
          "solution_profile_id": "growth_first",
          "archetype": "growth",
          "dominant_tradeoff": "keeps more of the revenue ambition while adding enough support to stay credible",
          "label": "Growth path: Set Year-1 marketing to $75,000",
          "rationale": "This path reset the Year-1 marketing ramp, and keeps more of the revenue ambition while adding enough support to stay credible.",
          "lever_families": ["marketing", "payroll", "utilization"],
          "summary": {"revenue": 320000, "marketing": 75000},
          "exact_patches": {
            "marketing_model_patch": {"expected_units_year1": 4200},
            "financials_patch": {"payroll_total_year1": 98000},
            "people_role_updates": [{"role_title": "Closer", "months_until_hire": 2}],
          },
          "remaining_blocking_count": 0,
          "remaining_violation_count": 0,
          "realism_distance": 0.015,
          "target_distance": 0.015,
          "distortion_total": 0.25,
          "disruption_score": 0.25,
          "ebitda": 10100,
        },
        {
          "scenario_id": "4",
          "solution_profile_id": "profit_first",
          "archetype": "efficiency",
          "dominant_tradeoff": "trades some upside for cleaner margin structure and tighter cost control",
          "label": "Efficiency path: Set other operating expense to $24,000",
          "rationale": "This path reset non-rent operating spend, and trades some upside for cleaner margin structure and tighter cost control.",
          "lever_families": ["other_opex", "cogs", "utilization"],
          "summary": {"revenue": 295000, "marketing": 15000},
          "exact_patches": {
            "financials_patch": {"other_operating_expense": 24000},
            "financials_year1_patch": {"utilization_rate": 0.63},
          },
          "remaining_blocking_count": 0,
          "remaining_violation_count": 0,
          "realism_distance": 0.012,
          "target_distance": 0.012,
          "distortion_total": 0.23,
          "disruption_score": 0.23,
          "ebitda": 10200,
        },
      ],
      state_model={
        "fixed_facts": {"sales_modality": "local_service", "capacity_driver": "labor"},
        "constraint_profile": {"utilization_envelope": {"min": 0.55}},
      },
    )

    self.assertEqual(len(selected), 3)
    self.assertEqual({item["archetype"] for item in selected}, {"operations", "growth", "efficiency"})
    self.assertTrue(all(not item.get("presentation_issues") for item in selected))

  def test_select_client_ready_scenarios_rejects_single_lever_dominance(self) -> None:
    selected = _select_client_ready_scenarios(
      [
        {
          "scenario_id": "dom",
          "solution_profile_id": "growth_first",
          "archetype": "growth",
          "label": "Growth path: Raise marketing",
          "rationale": "This path keeps more of the revenue ambition while adding enough support to stay credible.",
          "lever_families": ["marketing"],
          "summary": {"revenue": 220000, "marketing": 70000},
          "exact_patches": {"marketing_model_patch": {"expected_units_year1": 2400}},
          "remaining_blocking_count": 0,
          "remaining_violation_count": 0,
          "realism_distance": 0.01,
          "target_distance": 0.01,
          "distortion_total": 0.2,
          "disruption_score": 0.2,
          "ebitda": 9000,
          "dominant_tradeoff": "keeps more of the revenue ambition while adding enough support to stay credible",
          "lever_summary": {
            "meaningful_families": ["marketing"],
            "meaningful_lever_count": 1,
            "raw_family_moves": {"marketing": 0.9},
            "dominant_family": "marketing",
            "dominant_family_share": 0.9,
            "coordination_score": 0.8,
            "coordination_issues": ["demand_without_staffing"],
          },
        }
      ],
      state_model={
        "fixed_facts": {
          "sales_modality": "online",
          "capacity_driver": "system",
          "commercial_context": {"marketing_role": "primary"},
        },
        "constraint_profile": {"utilization_envelope": {"min": 0.4}},
      },
    )

    self.assertEqual(selected, [])

  def test_select_client_ready_scenarios_rejects_bad_five_year_path_even_with_zero_blockers(self) -> None:
    selected = _select_client_ready_scenarios(
      [
        {
          "scenario_id": "bad-outer-years",
          "solution_profile_id": "demand_supported_growth",
          "archetype": "operations",
          "label": "Operational balance",
          "rationale": "This path stabilizes staffing but never reaches a viable path.",
          "lever_families": ["payroll", "other_opex", "marketing", "utilization"],
          "remaining_blocking_count": 0,
          "remaining_violation_count": 0,
          "realism_distance": 0.01,
          "target_distance": 0.01,
          "distortion_total": 0.2,
          "disruption_score": 0.2,
          "ebitda": -40000.0,
          "dominant_tradeoff": "stabilizes operations first",
          "forecast_years": [
            {"year_index": 1, "revenue": 600000.0, "ebitda": -90000.0},
            {"year_index": 2, "revenue": 620000.0, "ebitda": -110000.0},
            {"year_index": 3, "revenue": 650000.0, "ebitda": -130000.0},
            {"year_index": 4, "revenue": 675000.0, "ebitda": -145000.0},
            {"year_index": 5, "revenue": 700000.0, "ebitda": -160000.0},
          ],
          "contract_diagnostics": {
            "controller_profile": {
              "target_margin_path": {
                "year1_min": -0.22,
                "year1_max": -0.10,
                "year2_min": -0.12,
                "year2_max": -0.02,
                "year3_min": -0.03,
                "year3_max": 0.05,
              }
            }
          },
        }
      ],
      state_model={
        "fixed_facts": {"sales_modality": "local_service", "capacity_driver": "labor"},
        "constraint_profile": {"utilization_envelope": {"min": 0.5}},
      },
    )

    self.assertEqual(selected, [])

  def test_convergence_policy_softens_generic_fallback(self) -> None:
    strong = build_convergence_policy(
      normalized_traits={"business_stage": "operating", "capacity_driver": "labor"},
      benchmark_payload={"fallback_level": "naics_6", "confidence_score": 0.9},
    )
    weak = build_convergence_policy(
      normalized_traits={"business_stage": "operating", "capacity_driver": "labor"},
      benchmark_payload={"fallback_level": "generic", "confidence_score": 0.2},
    )

    self.assertGreater(strong["global_convergence_strength"], weak["global_convergence_strength"])
    self.assertLess(strong["band_expansion"], weak["band_expansion"])

  def test_forecast_engine_emits_20_quarters_and_policy(self) -> None:
    bundle = build_forecast_engine_bundle(
      financials_json={
        "cogs_total_year1": 96000,
        "payroll_total_year1": 72000,
        "marketing_total_year1": 12000,
        "other_operating_expense": 18000,
        "annual_interest_payment": 5000,
        "ar_balance": 15000,
        "ap_balance": 9000,
        "inventory_balance": 5000,
        "current_capex": 8000,
        "current_depreciation": 3000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 240000,
        "unit_price": 100,
        "utilization_rate": 0.6,
        "avg_units_per_period_year1": 200,
        "operating_periods_per_year": 12,
      },
      normalized_traits={
        "business_stage": "operating",
        "capacity_driver": "labor",
        "sales_modality": "local_service",
      },
      benchmark_payload={
        "confidence_score": 0.8,
        "fallback_level": "naics_6",
        "revenue_growth_path": [0.03, 0.025, 0.02, 0.02],
        "gross_margin_band": {"min": 0.45, "max": 0.55},
        "ebitda_margin_band": {"min": 0.08, "max": 0.18},
        "payroll_intensity": {"min": 0.18, "max": 0.24},
        "opex_intensity": {"min": 0.12, "max": 0.18},
        "capex_percent_revenue": {"min": 0.02, "max": 0.04},
        "depreciation_percent_revenue": {"min": 0.01, "max": 0.02},
        "working_capital": {
          "dso": {"min": 20, "max": 35},
          "dpo": {"min": 15, "max": 30},
          "inventory_days": {"min": 10, "max": 20},
        },
      },
      constraint_engine_state={
        "utilization_range": {"min": 0.5, "max": 0.75},
        "gross_margin_band": {"min": 0.4, "max": 0.6},
        "ebitda_margin_band": {"min": 0.05, "max": 0.2},
        "supportable_unit_range": {"min": 0, "max": 3000},
        "current_metrics": {"utilization_rate": 0.6},
      },
    )

    self.assertEqual(len(bundle["forecast_quarters"]), 20)
    self.assertEqual(len(bundle["forecast_years"]), 5)
    self.assertEqual(bundle["forecast_engine_state"]["status"], "ready")
    self.assertIn("convergence_policy", bundle["forecast_engine_state"])
    self.assertIn(bundle["forecast_engine_state"]["convergence_source"], {"constraint_engine", "hybrid", "alpha"})
    self.assertGreaterEqual(bundle["forecast_engine_state"]["forecast_confidence"], 0.0)
    self.assertIn("forecast_years", bundle["forecast_engine_state"])
    self.assertEqual(bundle["engine_versions"]["forecast_engine_version"], "forecast-engine/v3")
    self.assertEqual(bundle["engine_versions"]["convergence_policy_version"], "convergence-policy/v1")

  def test_forecast_engine_prefers_constraint_engine_targets_over_alpha(self) -> None:
    bundle = build_forecast_engine_bundle(
      financials_json={
        "cogs_total_year1": 120000,
        "payroll_total_year1": 80000,
        "marketing_total_year1": 16000,
        "other_operating_expense": 30000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 320000,
        "unit_price": 125,
        "utilization_rate": 0.68,
        "avg_units_per_period_year1": 51.282051,
        "operating_periods_per_year": 52,
      },
      normalized_traits={
        "business_stage": "operating",
        "capacity_driver": "labor",
        "sales_modality": "local_service",
      },
      benchmark_payload={
        "confidence_score": 0.95,
        "fallback_level": "naics_6",
        "revenue_growth_path": [0.04, 0.03, 0.025, 0.02],
        "gross_margin_band": {"min": 0.70, "max": 0.76},
        "ebitda_margin_band": {"min": 0.18, "max": 0.24},
        "payroll_intensity": {"min": 0.10, "max": 0.14},
        "opex_intensity": {"min": 0.05, "max": 0.08},
      },
      constraint_engine_state={
        "constraint_confidence_score": 0.82,
        "utilization_range": {"min": 0.62, "max": 0.8},
        "gross_margin_band": {"min": 0.44, "max": 0.52},
        "ebitda_margin_band": {"min": 0.06, "max": 0.12},
        "payroll_intensity_band": {"min": 0.22, "max": 0.34},
        "opex_intensity_band": {"min": 0.08, "max": 0.16},
        "supportable_unit_range": {"min": 2000, "max": 3400},
      },
    )

    target_state = bundle["forecast_engine_state"]["target_state"]
    self.assertNotEqual(bundle["forecast_engine_state"]["convergence_source"], "alpha")
    engine_gross_mid = (0.44 + 0.52) / 2.0
    alpha_gross_mid = (0.70 + 0.76) / 2.0
    self.assertLess(abs(target_state["gross_margin"] - engine_gross_mid), abs(target_state["gross_margin"] - alpha_gross_mid))
    engine_payroll_mid = (0.22 + 0.34) / 2.0
    alpha_payroll_mid = (0.10 + 0.14) / 2.0
    self.assertLess(abs(target_state["payroll_intensity"] - engine_payroll_mid), abs(target_state["payroll_intensity"] - alpha_payroll_mid))

  def test_forecast_engine_preserves_scenario_identity_across_years(self) -> None:
    common_kwargs = {
      "financials_json": {
        "cogs_total_year1": 96000,
        "payroll_total_year1": 72000,
        "marketing_total_year1": 18000,
        "other_operating_expense": 22000,
      },
      "financials_year1_json": {
        "company_revenue_total_year1": 260000,
        "unit_price": 110,
        "utilization_rate": 0.67,
        "avg_units_per_period_year1": 196.969697,
        "operating_periods_per_year": 12,
      },
      "normalized_traits": {
        "business_stage": "startup",
        "capacity_driver": "system",
        "sales_modality": "online",
      },
      "benchmark_payload": {
        "confidence_score": 0.8,
        "fallback_level": "naics_6",
        "revenue_growth_path": [0.05, 0.04, 0.03, 0.025],
        "gross_margin_band": {"min": 0.50, "max": 0.62},
        "ebitda_margin_band": {"min": 0.08, "max": 0.18},
        "payroll_intensity": {"min": 0.14, "max": 0.24},
        "opex_intensity": {"min": 0.10, "max": 0.18},
      },
      "constraint_engine_state": {
        "constraint_confidence_score": 0.76,
        "utilization_range": {"min": 0.6, "max": 0.82},
        "gross_margin_band": {"min": 0.48, "max": 0.6},
        "ebitda_margin_band": {"min": 0.07, "max": 0.16},
        "payroll_intensity_band": {"min": 0.16, "max": 0.28},
        "opex_intensity_band": {"min": 0.1, "max": 0.17},
        "supportable_unit_range": {"min": 1800, "max": 3400},
      },
    }
    growth_bundle = build_forecast_engine_bundle(
      **common_kwargs,
      scenario_strategy={
        "archetype": "growth",
        "demand_posture": "preserve",
        "staffing_posture": "add_support",
        "cost_posture": "protect",
      },
    )
    efficiency_bundle = build_forecast_engine_bundle(
      **common_kwargs,
      scenario_strategy={
        "archetype": "efficiency",
        "demand_posture": "reduce",
        "staffing_posture": "hold",
        "cost_posture": "tighten",
      },
    )

    growth_year5 = growth_bundle["forecast_years"][-1]
    efficiency_year5 = efficiency_bundle["forecast_years"][-1]
    self.assertGreater(growth_year5["revenue"], efficiency_year5["revenue"])
    growth_margin = growth_year5["ebitda"] / growth_year5["revenue"]
    efficiency_margin = efficiency_year5["ebitda"] / efficiency_year5["revenue"]
    self.assertGreater(abs(growth_margin - efficiency_margin), 0.002)
    self.assertGreater(
      growth_bundle["forecast_engine_state"]["target_state"]["ebitda_margin"],
      efficiency_bundle["forecast_engine_state"]["target_state"]["ebitda_margin"],
    )
    self.assertGreater(
      growth_bundle["forecast_engine_state"]["revenue_growth_path_used"][0],
      efficiency_bundle["forecast_engine_state"]["revenue_growth_path_used"][0],
    )
    self.assertEqual(growth_bundle["forecast_engine_state"]["scenario_strategy"]["archetype"], "growth")
    self.assertEqual(efficiency_bundle["forecast_engine_state"]["scenario_strategy"]["archetype"], "efficiency")

  def test_forecast_engine_growth_path_works_without_benchmark_input(self) -> None:
    bundle = build_forecast_engine_bundle(
      financials_json={
        "cogs_total_year1": 82000,
        "payroll_total_year1": 64000,
        "marketing_total_year1": 14000,
        "other_operating_expense": 20000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 240000,
        "unit_price": 120,
        "utilization_rate": 0.64,
        "avg_units_per_period_year1": 166.666667,
        "operating_periods_per_year": 12,
      },
      normalized_traits={
        "business_stage": "startup",
        "capacity_driver": "system",
        "sales_modality": "online",
      },
      benchmark_payload={},
      constraint_engine_state={
        "constraint_confidence_score": 0.74,
        "utilization_range": {"min": 0.58, "max": 0.8},
        "gross_margin_band": {"min": 0.5, "max": 0.62},
        "ebitda_margin_band": {"min": 0.08, "max": 0.18},
        "payroll_intensity_band": {"min": 0.16, "max": 0.28},
        "opex_intensity_band": {"min": 0.08, "max": 0.18},
        "supportable_unit_range": {"min": 1500, "max": 3200},
      },
      scenario_strategy={
        "archetype": "growth",
        "demand_posture": "preserve",
        "staffing_posture": "add_support",
        "cost_posture": "protect",
      },
    )

    self.assertEqual(bundle["forecast_engine_state"]["status"], "ready")
    self.assertGreater(bundle["forecast_engine_state"]["revenue_growth_path_used"][0], 0.0)

  def test_forecast_engine_delayed_hire_creates_payroll_step_in_correct_quarter(self) -> None:
    bundle = build_forecast_engine_bundle(
      operating_model_json={"capacity_driver": "labor", "sales_modality": "local_service"},
      people_json={
        "people": [{"full_name": "Founder", "annual_wage": 60000}],
        "inferred_roles": [{"role_title": "Analyst", "annual_wage": 60000, "months_until_hire": 6}],
      },
      financials_json={
        "cogs_total_year1": 72000,
        "payroll_total_year1": 90000,
        "marketing_total_year1": 12000,
        "other_operating_expense": 18000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 240000,
        "unit_price": 120,
        "utilization_rate": 0.66,
        "avg_units_per_period_year1": 166.666667,
        "operating_periods_per_year": 12,
      },
      normalized_traits={
        "business_stage": "operating",
        "capacity_driver": "labor",
        "sales_modality": "local_service",
      },
      benchmark_payload={},
      constraint_engine_state={
        "constraint_confidence_score": 0.8,
        "utilization_range": {"min": 0.58, "max": 0.78},
        "gross_margin_band": {"min": 0.5, "max": 0.62},
        "ebitda_margin_band": {"min": 0.08, "max": 0.18},
        "payroll_intensity_band": {"min": 0.22, "max": 0.36},
        "opex_intensity_band": {"min": 0.08, "max": 0.16},
        "supportable_unit_range": {"min": 1500, "max": 2600},
        "current_metrics": {
          "capacity_units_year1": 2400.0,
          "active_role_months_year1": 18.0,
          "units_per_active_role_month": 133.333333,
        },
      },
      scenario_strategy={
        "archetype": "operations",
        "demand_posture": "moderate",
        "staffing_posture": "add_support",
        "cost_posture": "moderate",
      },
    )

    q1 = bundle["forecast_quarters"][0]
    q2 = bundle["forecast_quarters"][1]
    q3 = bundle["forecast_quarters"][2]
    self.assertAlmostEqual(q1["payroll"], q2["payroll"], delta=30.0)
    self.assertGreater(q3["payroll"], q2["payroll"] * 1.2)

  def test_forecast_engine_uses_gpt_orchestration_to_delay_role_activation(self) -> None:
    bundle = build_forecast_engine_bundle(
      operating_model_json={"capacity_driver": "labor", "sales_modality": "local_service"},
      people_json={
        "people": [{"full_name": "Founder", "annual_wage": 60000}],
        "inferred_roles": [{"role_title": "Analyst", "annual_wage": 60000, "months_until_hire": 6}],
      },
      financials_json={
        "cogs_total_year1": 72000,
        "payroll_total_year1": 90000,
        "marketing_total_year1": 12000,
        "other_operating_expense": 18000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 240000,
        "unit_price": 120,
        "utilization_rate": 0.66,
        "avg_units_per_period_year1": 166.666667,
        "operating_periods_per_year": 12,
      },
      normalized_traits={
        "business_stage": "operating",
        "capacity_driver": "labor",
        "sales_modality": "local_service",
      },
      benchmark_payload={},
      constraint_engine_state={
        "constraint_confidence_score": 0.8,
        "utilization_range": {"min": 0.58, "max": 0.78},
        "gross_margin_band": {"min": 0.5, "max": 0.62},
        "ebitda_margin_band": {"min": 0.08, "max": 0.18},
        "payroll_intensity_band": {"min": 0.22, "max": 0.36},
        "opex_intensity_band": {"min": 0.08, "max": 0.16},
        "supportable_unit_range": {"min": 1500, "max": 2600},
        "current_metrics": {
          "capacity_units_year1": 2400.0,
          "active_role_months_year1": 18.0,
          "units_per_active_role_month": 133.333333,
        },
      },
      scenario_strategy={
        "archetype": "operations",
        "demand_posture": "moderate",
        "staffing_posture": "add_support",
        "cost_posture": "moderate",
        "forecast_orchestration": {
          "orchestration_summary": "Delay analyst hire until Year 2.",
          "quarter_policies": [
            {
              "quarter_start": 1,
              "quarter_end": 20,
              "demand_posture": "moderate",
              "staffing_posture": "hold",
              "cost_posture": "moderate",
              "growth_multiplier": 1.0,
              "convergence_multiplier": 1.0,
              "price_growth_bias": 0.0,
              "utilization_target_bias": 0.0,
              "marketing_ratio_bias": 0.0,
              "opex_ratio_bias": 0.0,
              "payroll_ratio_bias": 0.0,
              "capacity_release_multiplier": 1.0,
              "active_levers": ["hire_delay"],
            }
          ],
          "role_timing_overrides": [{"role_title": "Analyst", "months_until_activate": 15}],
          "milestone_timing_overrides": [],
          "event_response": {
            "hire_capacity_multiplier": 1.0,
            "hire_growth_bonus_delta": 0.0,
            "marketing_growth_multiplier": 1.0,
            "milestone_capacity_multiplier": 1.0,
            "milestone_growth_multiplier": 1.0,
          },
        },
      },
    )

    q3 = bundle["forecast_quarters"][2]
    q5 = bundle["forecast_quarters"][4]
    q6 = bundle["forecast_quarters"][5]
    self.assertAlmostEqual(q3["payroll"], q5["payroll"], delta=30.0)
    self.assertGreater(q6["payroll"], q5["payroll"] * 1.15)
    self.assertEqual(bundle["forecast_engine_state"]["forecast_orchestration"]["role_timing_overrides"][0]["role_title"], "Analyst")

  def test_forecast_engine_gpt_orchestration_moves_multiple_financial_families(self) -> None:
    baseline = build_forecast_engine_bundle(
      operating_model_json={"capacity_driver": "system", "sales_modality": "online"},
      financials_json={
        "cogs_total_year1": 80000,
        "payroll_total_year1": 70000,
        "marketing_total_year1": 10000,
        "other_operating_expense": 18000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 252000,
        "unit_price": 50,
        "utilization_rate": 0.7,
        "avg_units_per_period_year1": 420,
        "operating_periods_per_year": 12,
      },
      normalized_traits={
        "business_stage": "startup",
        "capacity_driver": "system",
        "sales_modality": "online",
      },
      benchmark_payload={},
      constraint_engine_state={
        "constraint_confidence_score": 0.75,
        "utilization_range": {"min": 0.55, "max": 0.82},
        "gross_margin_band": {"min": 0.52, "max": 0.68},
        "ebitda_margin_band": {"min": 0.08, "max": 0.22},
        "payroll_intensity_band": {"min": 0.12, "max": 0.26},
        "opex_intensity_band": {"min": 0.08, "max": 0.18},
        "supportable_unit_range": {"min": 3000, "max": 9000},
        "current_metrics": {"capacity_units_year1": 7200.0},
      },
      scenario_strategy={
        "archetype": "growth",
        "demand_posture": "preserve",
        "staffing_posture": "add_support",
        "cost_posture": "protect",
      },
    )
    orchestrated = build_forecast_engine_bundle(
      operating_model_json={"capacity_driver": "system", "sales_modality": "online"},
      financials_json={
        "cogs_total_year1": 80000,
        "payroll_total_year1": 70000,
        "marketing_total_year1": 10000,
        "other_operating_expense": 18000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 252000,
        "unit_price": 50,
        "utilization_rate": 0.7,
        "avg_units_per_period_year1": 420,
        "operating_periods_per_year": 12,
      },
      normalized_traits={
        "business_stage": "startup",
        "capacity_driver": "system",
        "sales_modality": "online",
      },
      benchmark_payload={},
      constraint_engine_state={
        "constraint_confidence_score": 0.75,
        "utilization_range": {"min": 0.55, "max": 0.82},
        "gross_margin_band": {"min": 0.52, "max": 0.68},
        "ebitda_margin_band": {"min": 0.08, "max": 0.22},
        "payroll_intensity_band": {"min": 0.12, "max": 0.26},
        "opex_intensity_band": {"min": 0.08, "max": 0.18},
        "supportable_unit_range": {"min": 3000, "max": 9000},
        "current_metrics": {"capacity_units_year1": 7200.0},
      },
      scenario_strategy={
        "archetype": "growth",
        "demand_posture": "preserve",
        "staffing_posture": "add_support",
        "cost_posture": "protect",
        "forecast_orchestration": {
          "orchestration_summary": "Invest earlier in demand and support, then tighten opex later.",
          "quarter_policies": [
            {
              "quarter_start": 1,
              "quarter_end": 8,
              "demand_posture": "preserve",
              "staffing_posture": "add_support",
              "cost_posture": "protect",
              "growth_multiplier": 1.12,
              "convergence_multiplier": 0.85,
              "price_growth_bias": 0.001,
              "utilization_target_bias": 0.01,
              "marketing_ratio_bias": 0.012,
              "opex_ratio_bias": 0.004,
              "payroll_ratio_bias": 0.008,
              "capacity_release_multiplier": 1.04,
              "active_levers": ["marketing_up", "payroll_up", "util_up"],
            },
            {
              "quarter_start": 9,
              "quarter_end": 20,
              "demand_posture": "preserve",
              "staffing_posture": "rebalance",
              "cost_posture": "moderate",
              "growth_multiplier": 0.94,
              "convergence_multiplier": 0.9,
              "price_growth_bias": 0.0,
              "utilization_target_bias": 0.0,
              "marketing_ratio_bias": -0.004,
              "opex_ratio_bias": -0.006,
              "payroll_ratio_bias": -0.004,
              "capacity_release_multiplier": 1.08,
              "active_levers": ["marketing_down", "other_opex_down"],
            },
          ],
          "role_timing_overrides": [],
          "milestone_timing_overrides": [],
          "event_response": {
            "hire_capacity_multiplier": 1.15,
            "hire_growth_bonus_delta": 0.002,
            "marketing_growth_multiplier": 1.15,
            "milestone_capacity_multiplier": 1.1,
            "milestone_growth_multiplier": 1.05,
          },
        },
      },
    )

    base_q2 = baseline["forecast_quarters"][1]
    orch_q2 = orchestrated["forecast_quarters"][1]
    orch_q12 = orchestrated["forecast_quarters"][11]
    self.assertGreater(orch_q2["marketing"], base_q2["marketing"])
    self.assertGreater(orch_q2["payroll"], base_q2["payroll"])
    self.assertGreater(orch_q2["revenue"], base_q2["revenue"])
    self.assertLess(orch_q12["opex"], orch_q2["opex"])

  def test_forecast_engine_milestone_beyond_year1_changes_year2_capacity(self) -> None:
    bundle = build_forecast_engine_bundle(
      operating_model_json={
        "capacity_driver": "system",
        "sales_modality": "online",
        "milestones": [{"description": "Platform launch", "timing_months_max": 13}],
      },
      financials_json={
        "cogs_total_year1": 80000,
        "payroll_total_year1": 70000,
        "marketing_total_year1": 10000,
        "other_operating_expense": 18000,
      },
      financials_year1_json={
        "lobs": [
          {
            "lob_name": "Software",
            "products": [
              {
                "product_name": "Core Plan",
                "unit_price": 50,
                "units_per_period_capacity": 600,
                "avg_units_per_period_year1": 420,
                "operating_periods_per_year": 12,
                "utilization_rate": 0.7,
              }
            ],
          }
        ],
        "company_revenue_total_year1": 252000,
      },
      normalized_traits={
        "business_stage": "startup",
        "capacity_driver": "system",
        "sales_modality": "online",
      },
      benchmark_payload={},
      constraint_engine_state={
        "constraint_confidence_score": 0.75,
        "utilization_range": {"min": 0.55, "max": 0.82},
        "gross_margin_band": {"min": 0.52, "max": 0.68},
        "ebitda_margin_band": {"min": 0.08, "max": 0.22},
        "payroll_intensity_band": {"min": 0.12, "max": 0.26},
        "opex_intensity_band": {"min": 0.08, "max": 0.18},
        "supportable_unit_range": {"min": 3000, "max": 9000},
        "current_metrics": {"capacity_units_year1": 7200.0},
      },
      scenario_strategy={
        "archetype": "growth",
        "demand_posture": "preserve",
        "staffing_posture": "add_support",
        "cost_posture": "protect",
      },
    )

    q4_capacity = bundle["forecast_quarters"][3]["lobs"][0]["products"][0]["capacity_units"]
    q5_capacity = bundle["forecast_quarters"][4]["lobs"][0]["products"][0]["capacity_units"]
    self.assertGreater(q5_capacity, q4_capacity)

  def test_forecast_engine_efficiency_converges_faster_than_growth(self) -> None:
    common_kwargs = {
      "financials_json": {
        "cogs_total_year1": 90000,
        "payroll_total_year1": 70000,
        "marketing_total_year1": 15000,
        "other_operating_expense": 22000,
      },
      "financials_year1_json": {
        "company_revenue_total_year1": 250000,
        "unit_price": 100,
        "utilization_rate": 0.68,
        "avg_units_per_period_year1": 208.333333,
        "operating_periods_per_year": 12,
      },
      "normalized_traits": {
        "business_stage": "operating",
        "capacity_driver": "system",
        "sales_modality": "online",
      },
      "benchmark_payload": {},
      "constraint_engine_state": {
        "constraint_confidence_score": 0.8,
        "utilization_range": {"min": 0.58, "max": 0.82},
        "gross_margin_band": {"min": 0.5, "max": 0.64},
        "ebitda_margin_band": {"min": 0.08, "max": 0.2},
        "payroll_intensity_band": {"min": 0.14, "max": 0.26},
        "opex_intensity_band": {"min": 0.08, "max": 0.18},
        "supportable_unit_range": {"min": 1800, "max": 3600},
      },
    }
    growth_bundle = build_forecast_engine_bundle(
      **common_kwargs,
      scenario_strategy={
        "archetype": "growth",
        "demand_posture": "preserve",
        "staffing_posture": "add_support",
        "cost_posture": "protect",
      },
    )
    efficiency_bundle = build_forecast_engine_bundle(
      **common_kwargs,
      scenario_strategy={
        "archetype": "efficiency",
        "demand_posture": "reduce",
        "staffing_posture": "hold",
        "cost_posture": "tighten",
      },
    )

    self.assertGreater(
      efficiency_bundle["forecast_engine_state"]["convergence_strength"],
      growth_bundle["forecast_engine_state"]["convergence_strength"],
    )

  def test_phase9_client_scenario_output_strips_internal_fields(self) -> None:
    client_output = _build_client_scenario_output(
      {
        "archetype": "growth",
        "demand_posture": "preserve",
        "staffing_posture": "add_support",
        "cost_posture": "protect",
        "summary": {
          "revenue": 260000,
          "ebitda": 22000,
          "payroll": 78000,
          "marketing": 18000,
          "utilization": 0.68,
        },
        "forecast_years": [
          {
            "year_index": 5,
            "revenue": 360000,
            "ebitda": 42000,
            "payroll": 104000,
            "marketing": 26000,
            "utilization": 0.74,
          }
        ],
        "forecast_engine_state": {
          "forecast_confidence": 0.78,
          "convergence_strength": 0.42,
        },
        "label": "Growth path: raise marketing",
        "rationale": "internal rationale",
        "exact_patches": {"financials_patch": {"marketing_total_year1": 18000}},
      },
      scenario_id="1",
    )

    self.assertEqual(
      set(client_output.keys()),
      {"scenario_id", "scenario_name", "summary", "key_metrics", "tradeoff", "confidence"},
    )
    self.assertEqual(client_output["scenario_name"], "Growth Strategy")
    self.assertIn("demand", client_output["summary"].lower())
    self.assertIn("upside", client_output["tradeoff"])
    self.assertIn("downside", client_output["tradeoff"])
    self.assertNotIn("label", client_output)
    self.assertNotIn("exact_patches", client_output)

  def test_consistency_finalized_message_uses_initial_and_modified_sections_only(self) -> None:
    message = _build_consistency_finalized_message(
      solver_state={
        "state_model": {
          "fixed_facts": {
            "business_type": "Law firm",
          }
        }
      },
      selected_scenario={
        "client_output": {
          "summary": "This path preserves client demand while matching it with the staffing and cost structure the firm can realistically support.",
        },
        "dominant_tradeoff": "balances demand and staffing support",
        "lever_families": ["price", "staffing", "utilization"],
      },
      initial_table_markdown="| Line Item | Year 1 |\n| --- | ---: |\n| Revenue | $300,000 |",
      modified_forecast_quarters=[
        {"ebitda": 1000},
        {"ebitda": 2000},
        {"ebitda": 3000},
        {"ebitda": 4000},
      ],
    )

    self.assertIn("Initial Projections", message)
    self.assertIn("Modified Quarterly Projections", message)
    self.assertIn("Law firm", message)
    self.assertIn("Intake is now complete. You may submit the plan.", message)
    self.assertNotIn("Which option number", message)
    self.assertNotIn("Does this Year-1 summary look right", message)

  def test_consistency_modified_plan_payload_is_child_first_and_quarter_authoritative(self) -> None:
    payload = _build_consistency_modified_plan_payload(
      solver_state={
        "state_model": {
          "fixed_facts": {
            "business_type": "Law firm",
            "business_stage": "startup",
            "capacity_driver": "labor",
            "sales_modality": "project_based",
            "customer_type": "b2b",
            "unit_cadence": "monthly",
          }
        }
      },
      selected_scenario={
        "scenario_id": "2",
        "strategy_id": "staffing_ramp_adjustment",
        "archetype": "operations",
        "dominant_tradeoff": "delays support hiring while preserving pricing discipline",
        "demand_posture": "moderate",
        "staffing_posture": "delay",
        "cost_posture": "protect",
        "client_output": {
          "scenario_name": "Operational Balance Strategy",
          "summary": "This path delays support hiring until demand catches up.",
          "tradeoff": "upside: stronger control downside: slower support build",
          "confidence": "medium",
        },
      },
      constraint_bundle={
        "normalized_traits": {"business_stage": "startup"},
        "forecast_engine_state": {
          "forecast_confidence": "medium",
          "convergence_source": "constraint_engine",
          "convergence_strength": 0.35,
          "year1_warning_status": "ready",
          "blocking_violations": [],
          "forecast_orchestration": {
            "role_timing_overrides": [{"role_title": "Paralegal", "activation_quarter": 6}],
            "milestone_timing_overrides": [{"milestone_name": "Second office", "activation_quarter": 9}],
            "event_response": {"hire_event": ["payroll", "capacity"]},
          },
          "forecast_years": [
            {"year_index": 1, "revenue": 300000, "ebitda": 25000, "payroll": 200000},
            {"year_index": 2, "revenue": 360000, "ebitda": 60000, "payroll": 220000},
          ],
        },
      },
      initial_ops_json={"business_type": "Law firm"},
      initial_market_json={"customer_type": "b2b"},
      initial_people_json={"people": [{"full_name": "Partner A"}]},
      initial_financials_json={"payroll_total_year1": 203270, "marketing_total_year1": 36000},
      initial_financials_year1_json={"company_revenue_total_year1": 300000},
      initial_marketing_model_json={"annual_budget": 36000},
      modified_ops_json={"business_type": "Law firm"},
      modified_market_json={"customer_type": "b2b"},
      modified_people_json={"people": [{"full_name": "Partner A"}]},
      modified_financials_json={"payroll_total_year1": 203270, "marketing_total_year1": 36000},
      modified_financials_year1_json={
        "company_revenue_total_year1": 300000,
        "lobs": [{"lob_name": "Legal services", "products": [{"product_name": "Matters"}]}],
      },
      modified_marketing_model_json={"annual_budget": 36000},
      modified_forecast_quarters=[
        {
          "quarter_index": 1,
          "period_label": "Year 1 Q1",
          "revenue": 70000,
          "cogs": 3000,
          "payroll": 48000,
          "marketing": 9000,
          "opex": 4000,
          "ebitda": 6000,
          "lobs": [{"lob_name": "Legal services", "products": [{"product_name": "Matters", "units": 12}]}],
        },
        {
          "quarter_index": 2,
          "period_label": "Year 1 Q2",
          "revenue": 75000,
          "cogs": 3500,
          "payroll": 50000,
          "marketing": 9000,
          "opex": 4200,
          "ebitda": 7000,
          "lobs": [{"lob_name": "Legal services", "products": [{"product_name": "Matters", "units": 13}]}],
        },
      ],
    )

    self.assertEqual(payload["source"], "scenario")
    self.assertTrue(payload["child_first"])
    self.assertEqual(payload["scenario"]["strategy_id"], "staffing_ramp_adjustment")
    self.assertEqual(len(payload["quarter_driver_path"]), 2)
    self.assertEqual(payload["quarter_driver_path"][0]["source_level"], "child_rollup")
    self.assertIn("lobs", payload["quarter_driver_path"][0])
    self.assertNotIn("lobs", payload["quarter_rollups"][0])
    self.assertEqual(payload["timed_events"]["role_timing_overrides"][0]["activation_quarter"], 6)
    self.assertEqual(payload["forecast_meta"]["forecast_confidence"], "medium")
    self.assertEqual(payload["year1_modified_state"]["year_index"], 1)

  def test_serialize_debug_draft_row_parses_consistency_modified_plan_json(self) -> None:
    serialized = _serialize_debug_draft_row(
      {
        "draft_id": "abc",
        "consistency_modified_plan_json": json.dumps(
          {"source": "scenario", "quarter_driver_path": [{"quarter_index": 1}]},
          ensure_ascii=False,
        ),
        "financials_json": json.dumps({}, ensure_ascii=False),
      }
    )

    self.assertEqual(serialized["consistency_modified_plan_json"]["source"], "scenario")
    self.assertEqual(
      serialized["consistency_modified_plan_json"]["quarter_driver_path"][0]["quarter_index"],
      1,
    )

  def test_violation_resolution_summary_reports_cleared_status(self) -> None:
    summary = _build_violation_resolution_summary(
      solver_state=None,
      selected_scenario={
        "remaining_violations": [],
        "remaining_blocking_violations": [],
      },
      constraint_bundle={
        "constraint_engine_state": {
          "violations": ["payroll_too_light", "utilization_too_low"],
        },
        "forecast_engine_state": {
          "blocking_violations": [],
        },
      },
      modified_forecast_quarters=[],
    )

    self.assertEqual(summary["status"], "cleared")
    self.assertEqual(summary["display_status"], "cleared")
    self.assertTrue(summary["all_cleared"])
    self.assertEqual(set(summary["resolved_violations"]), {"payroll_too_light", "utilization_too_low"})
    self.assertEqual(summary["remaining_violations"], [])

  def test_phase9_intake_controller_has_no_legacy_consistency_chat_calls(self) -> None:
    intake_source = (ROOT / "python" / "api_handlers" / "intake_consult.py").read_text(encoding="utf-8")
    self.assertNotIn("consistency_chat_turn(", intake_source)
    self.assertNotIn("interpret_consistency_solver_reply", intake_source)
    self.assertNotIn("rewrite_marketing_state_after_consistency", intake_source)

  def test_consistency_consultant_file_removed(self) -> None:
    consultant_path = ROOT / "python" / "client_intake_and_finmo" / "consistency_consultant.py"
    self.assertFalse(consultant_path.exists())

  def test_legacy_financials_consult_routes_removed(self) -> None:
    api_source = (ROOT / "python" / "api.py").read_text(encoding="utf-8")
    self.assertNotIn("/api/financials-consult/session", api_source)
    self.assertNotIn("/api/financials-consult/draft", api_source)
    self.assertNotIn("/api/financials-consult", api_source)

  def test_legacy_financials_consult_files_removed(self) -> None:
    handler_path = ROOT / "python" / "api_handlers" / "financials_consult.py"
    draft_path = ROOT / "python" / "client_intake_and_finmo" / "financials_consult_draft.py"
    self.assertFalse(handler_path.exists())
    self.assertFalse(draft_path.exists())

  def test_consistency_modified_plan_payload_validator_requires_core_sections(self) -> None:
    self.assertFalse(_is_valid_consistency_modified_plan_payload(None))
    self.assertFalse(_is_valid_consistency_modified_plan_payload({}))
    self.assertFalse(
      _is_valid_consistency_modified_plan_payload(
        {"quarter_driver_path": [], "forecast_years": [], "resolution_summary": {}}
      )
    )
    self.assertTrue(
      _is_valid_consistency_modified_plan_payload(
        {
          "quarter_driver_path": [{"quarter_index": 1}],
          "forecast_years": [{"year": 1}],
          "resolution_summary": {"status": "cleared"},
        }
      )
    )

  def test_consistency_completion_requested_detects_done_write_intent(self) -> None:
    self.assertTrue(
      _consistency_completion_requested(
        status=None,
        active_focus="done",
        consistency_passed=None,
        completed=False,
      )
    )
    self.assertTrue(
      _consistency_completion_requested(
        status="completed",
        active_focus="financials",
        consistency_passed=False,
        completed=False,
      )
    )
    self.assertTrue(
      _consistency_completion_requested(
        status=None,
        active_focus="consistency",
        consistency_passed=True,
        completed=False,
      )
    )
    self.assertFalse(
      _consistency_completion_requested(
        status=None,
        active_focus="market",
        consistency_passed=False,
        completed=False,
      )
    )

  def test_any_unresolved_financials_stage_is_controller_owned(self) -> None:
    self.assertTrue(_financials_stage_is_controller_owned("revenue_intro"))
    self.assertTrue(_financials_stage_is_controller_owned("marketing"))
    self.assertTrue(_financials_stage_is_controller_owned("monthly_rent_expense"))
    self.assertTrue(_financials_stage_is_controller_owned("owner_compensation"))
    self.assertTrue(_financials_stage_is_controller_owned("annual_interest_payment"))
    self.assertTrue(_financials_stage_is_controller_owned("inventory_balance"))
    self.assertFalse(_financials_stage_is_controller_owned(None))
    self.assertFalse(_financials_stage_is_controller_owned(""))

  def test_generic_financials_stage_applies_patch_in_controller_same_turn(self) -> None:
    base_financials = {
      "_financials_revenue_intro_done": True,
      "current_cogs": 1000.0,
      "current_payroll": 2000.0,
      "marketing_total_year1": 500.0,
      "monthly_rent_expense": 0.0,
      "future_rent_expected": False,
    }

    def _fake_route_intent(**kwargs):
      raise AssertionError("route_intent should not be used for generic scalar financial stages")

    def _fake_financials_chat_turn(**kwargs):
      return {"assistant_message": "What should I use for other operating expense?", "finalize_ready": False}

    with patch(
      "api_handlers.intake_consult._advance_persisted_financials_stage",
      return_value=(
        {"assistant_message": "Got it - I'll use $30,000 for owner compensation.\n\nWhat should I use for other operating expense?", "finalize_ready": False},
        dict(base_financials, owner_compensation=30000.0),
        {},
      ),
    ):
      turn, next_financials = _maybe_handle_financials_generic_patch_turn(
        conn=object(),
        draft_id="draft-1",
        business_facts={},
        route_intent=_fake_route_intent,
        financials_chat_turn=_fake_financials_chat_turn,
        intake_context={},
        conversation_messages=[{"role": "user", "content": "Use 30,000"}],
        shared_context={"financials": dict(base_financials)},
        last_assistant="What should I use for owner compensation?",
        user_message="Use 30000 for owner compensation.",
        financials_json=base_financials,
        financials_year1_json={},
        active_stage="owner_compensation",
      )

    self.assertEqual(next_financials["owner_compensation"], 30000.0)
    self.assertIn("owner compensation", str(turn.get("assistant_message") or "").lower())
    self.assertIn("other operating expense", str(turn.get("assistant_message") or "").lower())

  def test_generic_financials_ar_balance_zero_persists_same_turn(self) -> None:
    base_financials = {
      "_financials_revenue_intro_done": True,
      "current_cogs": 1000.0,
      "current_payroll": 2000.0,
      "marketing_total_year1": 500.0,
      "monthly_rent_expense": 0.0,
      "future_rent_expected": False,
      "owner_compensation": 0.0,
      "other_operating_expense": 100.0,
      "current_num_employees": 0,
      "current_capex": 0.0,
      "initial_assets": 0.0,
      "initial_lease": "0,none",
      "initial_equity": 0.0,
      "total_debt_outstanding": 0.0,
      "other_monthly_debt_payments": 0.0,
      "annual_interest_payment": 0.0,
      "annual_principal_payment": 0.0,
      "cash_on_hand": 15000.0,
    }

    def _fake_route_intent(**kwargs):
      raise AssertionError("route_intent should not be used for AR scalar handling")

    def _fake_financials_chat_turn(**kwargs):
      return {"assistant_message": "What amount should I record for accounts payable?", "finalize_ready": False}

    with patch(
      "api_handlers.intake_consult._advance_persisted_financials_stage",
      return_value=(
        {"assistant_message": "Got it - I'll use $0 for accounts receivable.\n\nWhat amount should I record for accounts payable?", "finalize_ready": False},
        dict(base_financials, ar_balance=0.0),
        {},
      ),
    ):
      turn, next_financials = _maybe_handle_financials_generic_patch_turn(
        conn=object(),
        draft_id="draft-1",
        business_facts={},
        route_intent=_fake_route_intent,
        financials_chat_turn=_fake_financials_chat_turn,
        intake_context={},
        conversation_messages=[{"role": "user", "content": "Yes, keep it recorded as 0."}],
        shared_context={"financials": dict(base_financials)},
        last_assistant="As of last month, did any customers owe you money ... and should I keep that recorded as 0?",
        user_message="Yes, as I have consistently stated, the amount is 0 and should remain recorded as such.",
        financials_json=base_financials,
        financials_year1_json={},
        active_stage="ar_balance",
      )

    self.assertEqual(next_financials["ar_balance"], 0.0)
    self.assertIn("accounts receivable", str(turn.get("assistant_message") or "").lower())
    self.assertIn("accounts payable", str(turn.get("assistant_message") or "").lower())

  def test_advance_persisted_financials_stage_finishes_without_chat_when_last_stage(self) -> None:
    persisted_financials = {
      "_financials_revenue_intro_done": True,
      "current_cogs": 1000.0,
      "current_payroll": 2000.0,
      "marketing_total_year1": 500.0,
      "monthly_rent_expense": 0.0,
      "future_rent_expected": False,
      "owner_compensation": 0.0,
      "other_operating_expense": 0.0,
      "current_num_employees": 0,
      "current_capex": 0.0,
      "initial_assets": 0.0,
      "initial_lease": "0,none",
      "initial_equity": 0.0,
      "total_debt_outstanding": 0.0,
      "other_monthly_debt_payments": 0.0,
      "annual_interest_payment": 0.0,
      "annual_principal_payment": 0.0,
      "cash_on_hand": 0.0,
      "ar_balance": 0.0,
      "ap_balance": 0.0,
      "inventory_balance": 0.0,
    }

    def _should_not_chat(**kwargs):
      raise AssertionError("financials_chat_turn should not run after the last controller-owned financial stage")

    with patch(
      "api_handlers.intake_consult._persist_and_reload_financials_progress",
      return_value=(persisted_financials, {}, {}),
    ):
      turn, next_financials, _ = _advance_persisted_financials_stage(
        conn=object(),
        draft_id="draft-1",
        business_facts={},
        financials_chat_turn=_should_not_chat,
        intake_context={},
        conversation_messages=[],
        shared_context={"financials": dict(persisted_financials)},
        financials_json=dict(persisted_financials),
        financials_year1_json={},
        marketing_model_json={},
        acknowledgement="Got it - I'll use $0 for inventory.",
      )

    self.assertFalse(bool(turn.get("finalize_ready")))
    self.assertTrue(bool(turn.get("transition_to_consistency")))
    self.assertIn("moving into the consistency pass", str(turn.get("assistant_message") or "").lower())
    self.assertEqual(next_financials["inventory_balance"], 0.0)

  def test_financials_ready_for_consistency_requires_no_remaining_stage(self) -> None:
    self.assertFalse(
      _financials_ready_for_consistency(
        {
          "_financials_revenue_intro_done": True,
          "current_cogs": 1000.0,
          "current_payroll": 2000.0,
          "marketing_total_year1": 500.0,
        },
        guardrail_triggered=False,
      )
    )
    self.assertFalse(
      _financials_ready_for_consistency(
        {
          "_financials_revenue_intro_done": True,
          "current_cogs": 1000.0,
          "current_payroll": 2000.0,
          "marketing_total_year1": 500.0,
          "monthly_rent_expense": 0.0,
          "future_rent_expected": False,
          "owner_compensation": 0.0,
          "other_operating_expense": 0.0,
          "current_num_employees": 0,
          "current_capex": 0.0,
          "initial_assets": 0.0,
          "initial_lease": "0,none",
          "initial_equity": 0.0,
          "total_debt_outstanding": 0.0,
          "other_monthly_debt_payments": 0.0,
          "annual_interest_payment": 0.0,
          "annual_principal_payment": 0.0,
          "cash_on_hand": 0.0,
          "ar_balance": 0.0,
          "ap_balance": 0.0,
          "inventory_balance": 0.0,
        },
        guardrail_triggered=True,
      )
    )
    self.assertTrue(
      _financials_ready_for_consistency(
        {
          "_financials_revenue_intro_done": True,
          "current_cogs": 1000.0,
          "current_payroll": 2000.0,
          "marketing_total_year1": 500.0,
          "monthly_rent_expense": 0.0,
          "future_rent_expected": False,
          "owner_compensation": 0.0,
          "other_operating_expense": 0.0,
          "current_num_employees": 0,
          "current_capex": 0.0,
          "initial_assets": 0.0,
          "initial_lease": "0,none",
          "initial_equity": 0.0,
          "total_debt_outstanding": 0.0,
          "other_monthly_debt_payments": 0.0,
          "annual_interest_payment": 0.0,
          "annual_principal_payment": 0.0,
          "cash_on_hand": 0.0,
          "ar_balance": 0.0,
          "ap_balance": 0.0,
          "inventory_balance": 0.0,
        },
        guardrail_triggered=False,
      )
    )

  def test_consistency_closeout_gateway_refuses_mid_financials_transition(self) -> None:
    with patch("api_handlers.intake_consult._run_consistency_closeout") as closeout_mock:
      result = _maybe_run_consistency_closeout(
        focus_hint="financials",
        guardrail_triggered=False,
        conn=object(),
        client_id="client-1",
        draft_id="draft-1",
        business_facts={"name": "Test Biz", "start_date": "01/01/2026"},
        business_stage_hint="startup",
        current_date_iso="2026-03-25",
        shared_context={},
        ops_json={},
        market_json={},
        people_json={},
        financials_json={
          "_financials_revenue_intro_done": True,
          "current_cogs": 1000.0,
          "current_payroll": 2000.0,
          "marketing_total_year1": 500.0,
        },
        financials_year1_json={"company_revenue_total_year1": 0.0},
        fulfillment_json={},
        marketing_model_json={},
      )
    self.assertIsNone(result)
    closeout_mock.assert_not_called()

  def test_consistency_closeout_refuses_baseline_fallback_without_governed_scenario(self) -> None:
    constraint_bundle = {
      "forecast_quarters": [{"quarter_index": 1, "revenue": 1000.0}],
      "forecast_engine_state": {"forecast_years": [{"period_label": "Year 1", "revenue": 1000.0}]},
      "constraint_engine_state": {"violations": []},
    }
    with patch(
      "api_handlers.intake_consult._start_consistency_solver_if_needed",
      return_value=({"status": "blocking_unresolved", "scenarios": []}, constraint_bundle),
    ):
      with self.assertRaisesRegex(RuntimeError, "consistency_governed_scenario_missing"):
        _run_consistency_closeout(
          conn=object(),
          client_id="client-1",
          draft_id="draft-1",
          business_facts={"name": "Test Biz", "start_date": "01/01/2026"},
          business_stage_hint="startup",
          current_date_iso="2026-03-25",
          shared_context={},
          ops_json={},
          market_json={},
          people_json={},
          financials_json={"cogs_total_year1": 0.0, "payroll_total_year1": 0.0},
          financials_year1_json={"company_revenue_total_year1": 0.0},
          fulfillment_json={},
          marketing_model_json={},
        )

  def test_solver_returns_best_effort_governed_scenarios_when_client_ready_empty(self) -> None:
    with patch("consistency_solver._gpt_strategy_required", return_value=False), patch(
      "consistency_solver._build_profile_solver_contract",
      side_effect=lambda **kwargs: {
        "profile": kwargs["profile"],
        "direct_inputs": kwargs["direct_inputs"],
        "target_ebitda_min": kwargs["target_ebitda_min"],
        "target_ebitda_max": kwargs["target_ebitda_max"],
        "diagnostics": {},
      },
    ), patch(
      "consistency_solver._select_client_ready_scenarios",
      return_value=[],
    ), patch(
      "consistency_solver._select_best_effort_governed_scenarios",
      side_effect=lambda candidates, state_model=None: [dict(candidates[0], presentation_issues=["remaining_blockers"])] if candidates else [],
    ):
      solver_state = build_consistency_solver_state(
        ops_json={
          "unit_price": 120,
          "utilization_rate": 0.72,
          "capacity_driver": "system",
          "sales_modality": "online",
        },
        people_json={
          "people": [{"full_name": "Founder", "role_title": "Owner", "annual_wage": 80000}],
          "inferred_roles": [],
        },
        financials_json={
          "cogs_total_year1": 90000,
          "payroll_total_year1": 80000,
          "marketing_total_year1": 12000,
          "other_operating_expense": 18000,
        },
        financials_year1_json={
          "company_revenue_total_year1": 300000,
          "unit_price": 120,
          "utilization_rate": 0.72,
          "avg_units_per_period_year1": 208.3333,
          "operating_periods_per_year": 12,
        },
        marketing_model_json={},
        normalized_traits={
          "capacity_driver": "system",
          "sales_modality": "online",
          "customer_type": "b2c",
          "business_stage": "operating",
        },
        benchmark_payload=self._benchmark_payload(
          gross_margin_min=0.45,
          gross_margin_max=0.65,
          ebitda_margin_min=0.06,
          ebitda_margin_max=0.20,
          payroll_min=0.18,
          payroll_max=0.33,
          opex_min=0.08,
          opex_max=0.16,
        ),
        constraint_engine_state={
          "violations": ["ebitda_margin_too_low"],
          "hard_violation_codes": [],
          "soft_violation_codes": ["ebitda_margin_too_low"],
          "constraint_confidence_score": 0.75,
          "fallback_level": "naics_6",
          "supportable_unit_range": {"min": 1800, "max": 2800},
          "supportable_revenue_range": {"min": 260000, "max": 360000},
          "utilization_range": {"min": 0.55, "max": 0.85},
          "gross_margin_band": {"min": 0.45, "max": 0.65},
          "ebitda_margin_band": {"min": 0.06, "max": 0.20},
          "payroll_intensity_band": {"min": 0.18, "max": 0.33},
          "opex_intensity_band": {"min": 0.08, "max": 0.16},
          "current_metrics": {"capacity_units_year1": 3000},
        },
      )

    self.assertEqual((solver_state or {}).get("status"), "awaiting_choice")
    self.assertEqual((solver_state or {}).get("selection_mode"), "best_effort_governed")
    self.assertTrue((solver_state or {}).get("scenarios"))

  def test_solver_uses_governed_rescue_scenarios_when_lp_finds_none(self) -> None:
    rescue_candidate = {
      "scenario_id": "1",
      "label": "Operational balance",
      "rationale": "Controller-built governed rescue path.",
      "remaining_violations": [],
      "remaining_blocking_count": 0,
      "remaining_violation_count": 0,
      "realism_distance": 0.03,
      "forecast_quarters": [{"quarter_index": 1, "revenue": 1000.0}],
      "forecast_years": [{"period_label": "Year 1", "revenue": 1000.0}],
      "forecast_engine_state": {"status": "ready"},
      "forecast_summary": {"status": "ready"},
      "exact_patches": {"financials_year1_patch": {"unit_price": 132.0}},
      "lever_summary": {"meaningful_lever_count": 2, "meaningful_families": ["price", "utilization"]},
      "client_output": {},
      "archetype": "operations",
      "archetype_display": "Operational balance",
      "dominant_tradeoff": "keeps the plan inside a governed rescue envelope",
      "strategy_id": "operational_balance_strategy",
      "strategy_name": "Operational balance strategy",
    }
    with patch("consistency_solver._gpt_strategy_required", return_value=False), patch(
      "consistency_solver._solve_direct_profile",
      return_value=None,
    ), patch(
      "consistency_solver._build_governed_rescue_scenarios",
      return_value=[rescue_candidate],
    ):
      solver_state = build_consistency_solver_state(
        ops_json={
          "unit_price": 120,
          "utilization_rate": 0.72,
          "capacity_driver": "system",
          "sales_modality": "online",
        },
        people_json={
          "people": [{"full_name": "Founder", "role_title": "Owner", "annual_wage": 80000}],
          "inferred_roles": [],
        },
        financials_json={
          "cogs_total_year1": 90000,
          "payroll_total_year1": 80000,
          "marketing_total_year1": 12000,
          "other_operating_expense": 18000,
        },
        financials_year1_json={
          "company_revenue_total_year1": 300000,
          "unit_price": 120,
          "utilization_rate": 0.72,
          "avg_units_per_period_year1": 208.3333,
          "operating_periods_per_year": 12,
        },
        marketing_model_json={},
        normalized_traits={
          "capacity_driver": "system",
          "sales_modality": "online",
          "customer_type": "b2c",
          "business_stage": "operating",
        },
        benchmark_payload=self._benchmark_payload(
          gross_margin_min=0.45,
          gross_margin_max=0.65,
          ebitda_margin_min=0.06,
          ebitda_margin_max=0.20,
          payroll_min=0.18,
          payroll_max=0.33,
          opex_min=0.08,
          opex_max=0.16,
        ),
        constraint_engine_state={
          "violations": ["ebitda_margin_too_low"],
          "hard_violation_codes": [],
          "soft_violation_codes": ["ebitda_margin_too_low"],
          "constraint_confidence_score": 0.75,
          "fallback_level": "naics_6",
          "supportable_unit_range": {"min": 1800, "max": 2800},
          "supportable_revenue_range": {"min": 260000, "max": 360000},
          "utilization_range": {"min": 0.55, "max": 0.85},
          "gross_margin_band": {"min": 0.45, "max": 0.65},
          "ebitda_margin_band": {"min": 0.06, "max": 0.20},
          "payroll_intensity_band": {"min": 0.18, "max": 0.33},
          "opex_intensity_band": {"min": 0.08, "max": 0.16},
          "current_metrics": {"capacity_units_year1": 3000},
        },
      )

    self.assertEqual((solver_state or {}).get("status"), "awaiting_choice")
    self.assertEqual((solver_state or {}).get("selection_mode"), "best_effort_governed")
    self.assertTrue((solver_state or {}).get("scenarios"))
    self.assertEqual(((solver_state or {}).get("scenarios") or [])[0].get("strategy_id"), "operational_balance_strategy")

  def test_append_messages_rejects_consistency_completion_without_modified_plan(self) -> None:
    with patch(
      "intake_consult_draft.get_draft",
      return_value={
        "draft_id": "draft-1",
        "client_id": "client-1",
        "messages_json": "[]",
        "consistency_modified_plan_json": None,
      },
    ):
      with self.assertRaisesRegex(RuntimeError, "consistency_completion_requires_modified_plan"):
        append_messages(
          conn=object(),
          draft_id="draft-1",
          new_messages=[],
          active_focus="done",
          consistency_passed=True,
          completed=True,
        )

  def test_solver_trace_respects_flag(self) -> None:
    reset_solver_trace_stage()
    import solver_trace as solver_trace_module  # type: ignore
    log_path = ROOT / "solver_trace_test_output.txt"
    if log_path.exists():
      log_path.unlink()
    with patch.object(solver_trace_module, "_read_root_env_value", return_value="1"), patch.object(
      solver_trace_module,
      "_build_trace_log_path",
      return_value=log_path,
    ):
      buffer = StringIO()
      with patch("sys.stdout", buffer):
        trace("inputs", "Trace test", {"value": 1})
      output = buffer.getvalue()
      self.assertIn("SOLVER TRACE :: INPUTS", output)
      self.assertIn("\"value\": 1", output)
      self.assertTrue(log_path.exists())
      reset_solver_trace_stage()
      log_output = log_path.read_text(encoding="utf-8")
      self.assertIn("SOLVER TRACE :: INPUTS", log_output)
      self.assertIn("\"value\": 1", log_output)
    if log_path.exists():
      log_path.unlink()

    reset_solver_trace_stage()
    with patch.object(solver_trace_module, "_read_root_env_value", return_value="0"):
      buffer = StringIO()
      with patch("sys.stdout", buffer):
        trace_lazy("inputs", "Silent trace", lambda: {"value": 2})
      self.assertEqual(buffer.getvalue(), "")

  def test_solver_trace_reuses_same_named_file_across_resets(self) -> None:
    reset_solver_trace_stage()
    import solver_trace as solver_trace_module  # type: ignore
    log_dir = ROOT / "solver_trace_named_logs"
    log_path = log_dir / "03-24-2026 -- Test a fitness gym business.txt"
    if log_path.exists():
      log_path.unlink()
    if log_dir.exists() and not any(log_dir.iterdir()):
      log_dir.rmdir()

    with patch.object(solver_trace_module, "_read_root_env_value", return_value="1"), patch.object(
      solver_trace_module,
      "_solver_trace_log_dir",
      return_value=log_dir,
    ):
      configure_solver_trace_run("03-24-2026 -- Test a fitness gym business.txt", reset_file=True)
      trace("inputs", "First trace", {"value": 1})
      reset_solver_trace_stage()
      configure_solver_trace_run("03-24-2026 -- Test a fitness gym business.txt", reset_file=False)
      trace("final", "Second trace", {"value": 2})
      reset_solver_trace_stage()
      self.assertTrue(log_path.exists())
      self.assertEqual(len(list(log_dir.glob("*.txt"))), 1)
      log_output = log_path.read_text(encoding="utf-8")
      self.assertIn("First trace", log_output)
      self.assertIn("Second trace", log_output)
    if log_path.exists():
      log_path.unlink()
    if log_dir.exists() and not any(log_dir.iterdir()):
      log_dir.rmdir()

  def test_ops_capacity_target_detects_top_level_monthly_capacity(self) -> None:
    target = _find_missing_capacity_target(
      {"unit_cadence": "monthly", "unit_name": "Monthly membership"},
      fallback_ops={"unit_cadence": "monthly", "unit_name": "Monthly membership"},
    )

    self.assertEqual(target["kind"], "top_level")
    self.assertEqual(target["field"], "units_per_period_capacity")
    self.assertEqual(target["period_label"], "month")
    self.assertIn("Monthly membership", _build_capacity_target_question(target))

  def test_ops_capacity_target_detects_missing_product_capacity_in_multi_product_model(self) -> None:
    target = _find_missing_capacity_target(
      {
        "lob_models": [
          {
            "lob_name": "Memberships",
            "products": [
              {
                "product_name": "Monthly Membership",
                "unit_cadence": "monthly",
                "units_per_period_capacity": 500,
              },
              {
                "product_name": "Personal Training Session",
                "unit_cadence": "weekly",
              },
            ],
          }
        ],
      },
      fallback_ops={"unit_name": "session"},
    )

    self.assertEqual(target["kind"], "product")
    self.assertEqual(target["field"], "units_per_week_capacity")
    self.assertEqual(target["period_label"], "week")
    self.assertIn("Personal Training Session", _build_capacity_target_question(target))

  def test_ops_capacity_target_value_updates_only_missing_product(self) -> None:
    snapshot = {
      "lob_models": [
        {
          "lob_name": "Memberships",
          "products": [
            {
              "product_name": "Monthly Membership",
              "unit_cadence": "monthly",
              "units_per_period_capacity": 500,
            },
            {
              "product_name": "Personal Training Session",
              "unit_cadence": "weekly",
            },
          ],
        }
      ],
    }
    target = _find_missing_capacity_target(snapshot, fallback_ops={"unit_name": "session"})
    updated = _apply_capacity_target_value(snapshot, target or {}, 60)

    products = updated["lob_models"][0]["products"]
    self.assertEqual(products[0]["units_per_period_capacity"], 500)
    self.assertEqual(products[1]["units_per_week_capacity"], 60.0)

  def test_forecast_engine_soft_growth_saturation_dampens_late_growth_without_capacity_unlock(self) -> None:
    common_kwargs = {
      "financials_json": {
        "cogs_total_year1": 95000,
        "payroll_total_year1": 70000,
        "marketing_total_year1": 12000,
        "other_operating_expense": 18000,
      },
      "financials_year1_json": {
        "lobs": [
          {
            "lob_name": "Store",
            "products": [
              {
                "product_name": "Core",
                "unit_price": 40,
                "units_per_period_capacity": 500,
                "avg_units_per_period_year1": 440,
                "operating_periods_per_year": 12,
                "utilization_rate": 0.88,
              }
            ],
          }
        ],
        "company_revenue_total_year1": 211200,
      },
      "normalized_traits": {
        "business_stage": "operating",
        "capacity_driver": "space",
        "sales_modality": "retail",
      },
      "benchmark_payload": {},
      "constraint_engine_state": {
        "constraint_confidence_score": 0.8,
        "utilization_range": {"min": 0.6, "max": 0.9},
        "gross_margin_band": {"min": 0.48, "max": 0.62},
        "ebitda_margin_band": {"min": 0.08, "max": 0.18},
        "payroll_intensity_band": {"min": 0.14, "max": 0.24},
        "opex_intensity_band": {"min": 0.08, "max": 0.16},
        "supportable_unit_range": {"min": 4000, "max": 6000},
        "current_metrics": {"capacity_units_year1": 6000.0},
      },
      "scenario_strategy": {
        "archetype": "growth",
        "demand_posture": "preserve",
        "staffing_posture": "add_support",
        "cost_posture": "protect",
      },
    }
    stalled_bundle = build_forecast_engine_bundle(
      operating_model_json={"capacity_driver": "space", "sales_modality": "retail"},
      **common_kwargs,
    )
    unlocked_bundle = build_forecast_engine_bundle(
      operating_model_json={
        "capacity_driver": "space",
        "sales_modality": "retail",
        "milestones": [{"description": "Second bay opens", "timing_months_max": 10}],
      },
      **common_kwargs,
    )

    stalled_q19 = stalled_bundle["forecast_quarters"][18]["revenue"]
    stalled_q20 = stalled_bundle["forecast_quarters"][19]["revenue"]
    unlocked_q19 = unlocked_bundle["forecast_quarters"][18]["revenue"]
    unlocked_q20 = unlocked_bundle["forecast_quarters"][19]["revenue"]
    stalled_late_growth = (stalled_q20 / stalled_q19) - 1.0
    unlocked_late_growth = (unlocked_q20 / unlocked_q19) - 1.0
    self.assertGreater(unlocked_late_growth, stalled_late_growth)

  def test_solver_uses_product_overrides_when_child_drivers_exist(self) -> None:
    baseline_summary = build_consistency_financial_summary(
      financials_json={
        "cogs_total_year1": 90000,
        "payroll_total_year1": 120000,
        "marketing_total_year1": 15000,
        "other_operating_expense": 40000,
      },
      financials_year1_json={
        "lobs": [
          {
            "lob_name": "Services",
            "products": [
              {
                "product_name": "Advisory",
                "unit_price": 2000,
                "units_per_period_capacity": 12,
                "avg_units_per_period_year1": 8,
                "operating_periods_per_year": 12,
                "utilization_rate": 0.6667,
              },
              {
                "product_name": "Audit",
                "unit_price": 3500,
                "units_per_period_capacity": 6,
                "avg_units_per_period_year1": 4,
                "operating_periods_per_year": 12,
                "utilization_rate": 0.6667,
              },
            ],
            "revenue_total_year1": 360000,
          }
        ],
        "company_revenue_total_year1": 360000,
      },
    )
    state_model = _build_solver_state_model(
      ops_json={"capacity_driver": "labor"},
      people_json={"future_roles": []},
      financials_json={
        "marketing_total_year1": 15000,
        "other_operating_expense": 40000,
      },
      financials_year1_json={
        "lobs": [
          {
            "lob_name": "Services",
            "products": [
              {
                "product_name": "Advisory",
                "unit_price": 2000,
                "units_per_period_capacity": 12,
                "avg_units_per_period_year1": 8,
                "operating_periods_per_year": 12,
                "utilization_rate": 0.6667,
              },
              {
                "product_name": "Audit",
                "unit_price": 3500,
                "units_per_period_capacity": 6,
                "avg_units_per_period_year1": 4,
                "operating_periods_per_year": 12,
                "utilization_rate": 0.6667,
              },
            ],
          }
        ],
        "company_revenue_total_year1": 360000,
      },
      marketing_model_json={"expected_units_year1": 144},
      baseline_summary=baseline_summary,
      constraint_engine_state={
        "supportable_unit_range": {"min": 120, "max": 180},
        "supportable_revenue_range": {"min": 330000, "max": 420000},
        "utilization_range": {"min": 0.55, "max": 0.8},
        "gross_margin_band": {"min": 0.45, "max": 0.7},
        "ebitda_margin_band": {"min": 0.08, "max": 0.18},
        "opex_intensity_band": {"min": 0.08, "max": 0.2},
        "constraint_confidence_score": 0.8,
        "fallback_level": "naics_6",
        "constraints": [],
        "violations": ["ebitda_margin_too_low"],
        "current_metrics": {"capacity_units_year1": 216.0},
      },
    )
    self.assertEqual((state_model or {}).get("solve_mode"), "child_first")
    direct_inputs = _build_direct_solver_inputs(state_model=state_model or {})
    self.assertIsNotNone(direct_inputs)
    self.assertEqual((direct_inputs or {}).get("solve_mode"), "child_first")
    exact = _exact_patches_from_solution(
      solution={
        "price": 2725,
        "utilization_rate": 0.74,
        "annual_units_total": 160.8,
        "child_product_solution": {
          "services::advisory": {
            "unit_price": 2100,
            "utilization_rate": 0.75,
            "avg_units_per_period_year1": 9,
          },
          "services::audit": {
            "unit_price": 3600,
            "utilization_rate": 0.7,
            "avg_units_per_period_year1": 4.2,
          },
        },
        "marketing_total_year1": 20000,
        "marketing_support_units_year1": 155,
        "other_operating_expense": 36000,
        "cogs_total_year1": 95000,
        "role_months": {},
        "role_year1_payroll": {},
        "role_wage_meta": {},
      },
      direct_inputs=direct_inputs or {},
      ops_json={"capacity_driver": "labor"},
    )

    year1_patch = exact.get("financials_year1_patch") or {}
    self.assertIn("product_overrides", year1_patch)
    self.assertNotIn("unit_price", year1_patch)
    self.assertNotIn("utilization_rate", year1_patch)
    self.assertEqual(len(year1_patch["product_overrides"]), 2)
    self.assertIn("services::advisory", year1_patch["product_overrides"])
    self.assertIn("services::audit", year1_patch["product_overrides"])

  def test_solver_uses_child_mode_for_single_product_child_data(self) -> None:
    baseline_summary = build_consistency_financial_summary(
      financials_json={
        "cogs_total_year1": 25000,
        "payroll_total_year1": 50000,
        "marketing_total_year1": 5000,
        "other_operating_expense": 15000,
      },
      financials_year1_json={
        "lobs": [
          {
            "lob_name": "Care",
            "products": [
              {
                "product_name": "Private Duty",
                "unit_price": 35,
                "units_per_period_capacity": 500,
                "avg_units_per_period_year1": 350,
                "operating_periods_per_year": 12,
                "utilization_rate": 0.7,
              }
            ],
          }
        ],
        "company_revenue_total_year1": 147000,
      },
    )
    state_model = _build_solver_state_model(
      ops_json={"capacity_driver": "labor"},
      people_json={"future_roles": []},
      financials_json={
        "marketing_total_year1": 5000,
        "other_operating_expense": 15000,
      },
      financials_year1_json={
        "lobs": [
          {
            "lob_name": "Care",
            "products": [
              {
                "product_name": "Private Duty",
                "unit_price": 35,
                "units_per_period_capacity": 500,
                "avg_units_per_period_year1": 350,
                "operating_periods_per_year": 12,
                "utilization_rate": 0.7,
              }
            ],
          }
        ],
        "company_revenue_total_year1": 147000,
      },
      marketing_model_json={"expected_units_year1": 4200},
      baseline_summary=baseline_summary,
      constraint_engine_state={
        "supportable_unit_range": {"min": 3500, "max": 5000},
        "supportable_revenue_range": {"min": 130000, "max": 190000},
        "utilization_range": {"min": 0.6, "max": 0.82},
        "gross_margin_band": {"min": 0.45, "max": 0.75},
        "ebitda_margin_band": {"min": 0.05, "max": 0.2},
        "opex_intensity_band": {"min": 0.08, "max": 0.2},
        "constraint_confidence_score": 0.8,
        "fallback_level": "naics_6",
        "constraints": [],
        "violations": ["ebitda_margin_too_low"],
        "current_metrics": {"capacity_units_year1": 6000.0},
      },
    )
    direct_inputs = _build_direct_solver_inputs(state_model=state_model or {})
    exact = _exact_patches_from_solution(
      solution={
        "price": 36.5,
        "utilization_rate": 0.75,
        "annual_units_total": 4500,
        "child_product_solution": {
          "care::private duty": {
            "unit_price": 36.5,
            "utilization_rate": 0.75,
            "avg_units_per_period_year1": 375,
          },
        },
        "marketing_total_year1": 5400,
        "marketing_support_units_year1": 4500,
        "other_operating_expense": 14000,
        "cogs_total_year1": 28000,
        "role_months": {},
        "role_year1_payroll": {},
        "role_wage_meta": {},
      },
      direct_inputs=direct_inputs or {},
      ops_json={"capacity_driver": "labor"},
    )

    self.assertEqual((state_model or {}).get("solve_mode"), "child_first")
    self.assertEqual((direct_inputs or {}).get("solve_mode"), "child_first")
    year1_patch = exact.get("financials_year1_patch") or {}
    self.assertIn("product_overrides", year1_patch)
    self.assertEqual(set((year1_patch.get("product_overrides") or {}).keys()), {"care::private duty"})
    self.assertNotIn("unit_price", year1_patch)
    self.assertNotIn("utilization_rate", year1_patch)

  def test_solver_falls_back_to_parent_when_child_driver_data_is_incomplete(self) -> None:
    baseline_summary = build_consistency_financial_summary(
      financials_json={
        "cogs_total_year1": 40000,
        "payroll_total_year1": 60000,
        "marketing_total_year1": 8000,
        "other_operating_expense": 18000,
      },
      financials_year1_json={
        "unit_price": 120,
        "utilization_rate": 0.65,
        "avg_units_per_period_year1": 40,
        "operating_periods_per_year": 12,
        "company_revenue_total_year1": 57600,
        "lobs": [
          {
            "lob_name": "Programs",
            "products": [
              {
                "product_name": "Core",
                "unit_price": None,
                "units_per_period_capacity": 0,
                "avg_units_per_period_year1": 0,
                "operating_periods_per_year": 12,
              }
            ],
          }
        ],
      },
    )
    state_model = _build_solver_state_model(
      ops_json={"capacity_driver": "labor", "unit_price": 120, "utilization_rate": 0.65},
      people_json={"future_roles": []},
      financials_json={
        "marketing_total_year1": 8000,
        "other_operating_expense": 18000,
      },
      financials_year1_json={
        "unit_price": 120,
        "utilization_rate": 0.65,
        "avg_units_per_period_year1": 40,
        "operating_periods_per_year": 12,
        "company_revenue_total_year1": 57600,
        "lobs": [
          {
            "lob_name": "Programs",
            "products": [
              {
                "product_name": "Core",
                "unit_price": None,
                "units_per_period_capacity": 0,
                "avg_units_per_period_year1": 0,
                "operating_periods_per_year": 12,
              }
            ],
          }
        ],
      },
      marketing_model_json={"expected_units_year1": 480},
      baseline_summary=baseline_summary,
      constraint_engine_state={
        "supportable_unit_range": {"min": 400, "max": 650},
        "supportable_revenue_range": {"min": 50000, "max": 85000},
        "utilization_range": {"min": 0.55, "max": 0.8},
        "gross_margin_band": {"min": 0.35, "max": 0.7},
        "ebitda_margin_band": {"min": 0.05, "max": 0.2},
        "opex_intensity_band": {"min": 0.08, "max": 0.2},
        "constraint_confidence_score": 0.8,
        "fallback_level": "naics_6",
        "constraints": [],
        "violations": ["ebitda_margin_too_low"],
        "current_metrics": {"capacity_units_year1": 720.0},
      },
    )
    direct_inputs = _build_direct_solver_inputs(state_model=state_model or {})
    exact = _exact_patches_from_solution(
      solution={
        "price": 126,
        "utilization_rate": 0.72,
        "marketing_total_year1": 9000,
        "marketing_support_units_year1": 520,
        "other_operating_expense": 17000,
        "cogs_total_year1": 41000,
        "role_months": {},
        "role_year1_payroll": {},
        "role_wage_meta": {},
      },
      direct_inputs=direct_inputs or {},
      ops_json={"capacity_driver": "labor"},
    )

    self.assertEqual((state_model or {}).get("solve_mode"), "parent_fallback")
    self.assertEqual((direct_inputs or {}).get("solve_mode"), "parent_fallback")
    year1_patch = exact.get("financials_year1_patch") or {}
    self.assertNotIn("product_overrides", year1_patch)
    self.assertEqual(year1_patch.get("unit_price"), 126)
    self.assertEqual(year1_patch.get("utilization_rate"), 0.72)

  def test_child_first_solver_can_move_one_product_without_scaling_all_children(self) -> None:
    baseline_summary = build_consistency_financial_summary(
      financials_json={
        "cogs_total_year1": 6000,
        "payroll_total_year1": 7000,
        "marketing_total_year1": 0,
        "other_operating_expense": 2500,
      },
      financials_year1_json={
        "lobs": [
          {
            "lob_name": "Services",
            "products": [
              {
                "product_name": "A",
                "unit_price": 100,
                "units_per_period_capacity": 10,
                "avg_units_per_period_year1": 8.5,
                "operating_periods_per_year": 12,
                "utilization_rate": 0.85,
              },
              {
                "product_name": "B",
                "unit_price": 200,
                "units_per_period_capacity": 10,
                "avg_units_per_period_year1": 5,
                "operating_periods_per_year": 12,
                "utilization_rate": 0.5,
              },
            ],
          }
        ],
        "company_revenue_total_year1": 22200,
      },
    )
    state_model = _build_solver_state_model(
      ops_json={"capacity_driver": "labor"},
      people_json={"future_roles": []},
      financials_json={"marketing_total_year1": 0, "other_operating_expense": 2500},
      financials_year1_json={
        "lobs": [
          {
            "lob_name": "Services",
            "products": [
              {
                "product_name": "A",
                "unit_price": 100,
                "units_per_period_capacity": 10,
                "avg_units_per_period_year1": 8.5,
                "operating_periods_per_year": 12,
                "utilization_rate": 0.85,
              },
              {
                "product_name": "B",
                "unit_price": 200,
                "units_per_period_capacity": 10,
                "avg_units_per_period_year1": 5,
                "operating_periods_per_year": 12,
                "utilization_rate": 0.5,
              },
            ],
          }
        ],
      },
      marketing_model_json={"expected_units_year1": 162},
      baseline_summary=baseline_summary,
      constraint_engine_state={
        "supportable_unit_range": {"min": 150, "max": 204},
        "supportable_revenue_range": {"min": 22000, "max": 28000},
        "utilization_range": {"min": 0.5, "max": 0.85},
        "gross_margin_band": {"min": 0.55, "max": 0.75},
        "ebitda_margin_band": {"min": 0.32, "max": 0.45},
        "opex_intensity_band": {"min": 0.05, "max": 0.15},
        "constraint_confidence_score": 0.9,
        "fallback_level": "naics_6",
        "constraints": [],
        "violations": ["ebitda_margin_too_low"],
        "current_metrics": {"capacity_units_year1": 240.0},
      },
    )
    direct_inputs = _build_direct_solver_inputs(state_model=state_model or {})
    self.assertEqual((direct_inputs or {}).get("solve_mode"), "child_first")
    direct_inputs = dict(direct_inputs or {})
    direct_inputs["price_enabled"] = False
    direct_inputs["current_marketing"] = 0.0
    direct_inputs["marketing_min"] = 0.0
    direct_inputs["marketing_upper"] = 0.0
    direct_inputs["marketing_units_per_dollar"] = 0.0
    direct_inputs["marketing_support_units_baseline"] = 162.0
    direct_inputs["marketing_support_units_min"] = 162.0
    direct_inputs["marketing_support_units_max"] = 162.0
    direct_inputs["other_opex_enabled"] = False
    direct_inputs["cogs_ratio_min"] = direct_inputs["current_cogs_ratio"]
    direct_inputs["cogs_ratio_max"] = direct_inputs["current_cogs_ratio"]
    direct_inputs["units_min"] = 180.0
    constraint_profile = dict(direct_inputs.get("constraint_profile") or {})
    capacity_curve = dict(constraint_profile.get("capacity_curve") or {})
    capacity_curve["hard_units_min"] = 180.0
    constraint_profile["capacity_curve"] = capacity_curve
    direct_inputs["constraint_profile"] = constraint_profile

    profile = _solver_profiles(state_model=state_model or {})[0]
    solution = _solve_direct_profile(
      profile=profile,
      direct_inputs=direct_inputs,
      target_ebitda_min=None,
      target_ebitda_max=None,
      enforce_blocking_bands=False,
    )

    self.assertIsNotNone(solution)
    child_solution = (solution or {}).get("child_product_solution") or {}
    product_a = child_solution.get("services::a") or {}
    product_b = child_solution.get("services::b") or {}
    self.assertEqual((solution or {}).get("changed_child_product_count"), 1)
    self.assertAlmostEqual(product_a.get("utilization_rate"), 0.85, places=4)
    self.assertGreater(product_b.get("utilization_rate"), 0.5)

  def test_child_first_exact_patches_do_not_scale_unchanged_siblings(self) -> None:
    exact = _exact_patches_from_solution(
      solution={
        "child_product_solution": {
          "services::advisory": {
            "unit_price": 110,
            "utilization_rate": 0.6,
            "avg_units_per_period_year1": 6,
          },
          "services::audit": {
            "unit_price": 200,
            "utilization_rate": 0.5,
            "avg_units_per_period_year1": 3,
          },
        },
        "annual_units_total": 108.0,
        "marketing_total_year1": 0,
        "marketing_support_units_year1": 108,
        "other_operating_expense": 10000,
        "cogs_total_year1": 20000,
        "role_months": {},
        "role_year1_payroll": {},
        "role_wage_meta": {},
      },
      direct_inputs={
        "solve_mode": "child_first",
        "current_price": 150,
        "current_util": 0.56,
        "current_marketing": 0,
        "marketing_support_units_baseline": 108,
        "current_other_opex": 10000,
        "current_cogs": 20000,
        "capacity_units": 192,
        "constraint_profile": {"marketing_children": {}},
        "product_driver_basis": [
          {
            "product_key": "services::advisory",
            "unit_price": 100,
            "utilization_rate": 0.6,
            "avg_units_per_period_year1": 6,
            "units_per_period_capacity": 10,
            "operating_periods_per_year": 12,
          },
          {
            "product_key": "services::audit",
            "unit_price": 200,
            "utilization_rate": 0.5,
            "avg_units_per_period_year1": 3,
            "units_per_period_capacity": 6,
            "operating_periods_per_year": 12,
          },
        ],
      },
      ops_json={"capacity_driver": "labor"},
    )

    year1_patch = exact.get("financials_year1_patch") or {}
    overrides = year1_patch.get("product_overrides") or {}
    self.assertNotIn("unit_price", year1_patch)
    self.assertNotIn("utilization_rate", year1_patch)
    self.assertIn("services::advisory", overrides)
    self.assertNotIn("services::audit", overrides)
    self.assertEqual(overrides["services::advisory"]["unit_price"], 110)

  def test_apply_exact_patches_preserves_solver_owned_payroll_totals(self) -> None:
    next_ops, next_people, next_financials, next_year1, next_marketing = _apply_exact_patches(
      ops_json={"milestones": []},
      people_json={
        "people": [
          {"role_title": "Founder", "annual_wage": 120000},
        ],
        "inferred_roles": [
          {"role_title": "Caregiver", "annual_wage": 60000, "months_until_hire": 6},
        ],
      },
      financials_json={
        "current_payroll": 150000,
        "payroll_total_year1": 150000,
        "monthly_rent_expense": 2000,
      },
      financials_year1_json={"company_revenue_total_year1": 500000},
      marketing_model_json={},
      exact_patches={
        "financials_patch": {
          "current_payroll": 265000,
          "payroll_total_year1": 265000,
        },
      },
    )

    self.assertEqual(next_ops.get("milestones"), [])
    self.assertEqual(next_year1.get("company_revenue_total_year1"), 500000)
    self.assertEqual(next_marketing, {})
    self.assertEqual(next_financials.get("current_payroll"), 265000)
    self.assertEqual(next_financials.get("payroll_total_year1"), 265000)
    self.assertAlmostEqual(_safe_float(next_financials.get("baseline_payroll_year1")), 150000.0, places=2)
    self.assertAlmostEqual(_safe_float(next_financials.get("payroll_adjustment")), 115000.0, places=2)
    self.assertEqual((next_people.get("inferred_roles") or [])[0].get("months_until_hire"), 6)

  def test_apply_consistency_solver_choice_uses_modified_state_without_reapplying_baseline(self) -> None:
    scenario = {
      "scenario_id": "1",
      "exact_patches": {
        "financials_patch": {
          "current_payroll": 265000,
          "payroll_total_year1": 265000,
        },
      },
      "modified_state": {
        "ops_json": {"capacity_driver": "labor"},
        "people_json": {
          "people": [{"role_title": "Founder", "annual_wage": 120000}],
          "inferred_roles": [{"role_title": "Caregiver", "annual_wage": 60000, "months_until_hire": 6}],
        },
        "financials_json": {
          "current_revenue": 500000,
          "current_cogs": 220000,
          "current_payroll": 265000,
          "payroll_total_year1": 265000,
          "marketing_total_year1": 25000,
          "other_operating_expense": 15000,
          "monthly_rent_expense": 2000,
        },
        "financials_year1_json": {
          "company_revenue_total_year1": 500000,
          "company_cogs_total_year1": 220000,
        },
        "marketing_model_json": {"expected_units_year1": 100},
      },
    }
    applied_choice = apply_consistency_solver_choice(
      ops_json={"capacity_driver": "labor"},
      people_json={
        "people": [{"role_title": "Founder", "annual_wage": 120000}],
        "inferred_roles": [{"role_title": "Caregiver", "annual_wage": 60000, "months_until_hire": 6}],
      },
      financials_json={
        "current_revenue": 500000,
        "current_cogs": 220000,
        "current_payroll": 150000,
        "payroll_total_year1": 150000,
        "marketing_total_year1": 25000,
        "other_operating_expense": 15000,
        "monthly_rent_expense": 2000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 500000,
        "company_cogs_total_year1": 220000,
      },
      marketing_model_json={"expected_units_year1": 100},
      solver_state={"scenarios": [scenario]},
      selected_scenario_id="1",
      overrides={},
    )

    self.assertIsNotNone(applied_choice)
    self.assertEqual((applied_choice or {}).get("financials_json", {}).get("current_payroll"), 265000)
    self.assertEqual((applied_choice or {}).get("financials_json", {}).get("payroll_total_year1"), 265000)

  def test_apply_revenue_driver_patch_supports_lob_product_keys(self) -> None:
    patched = apply_revenue_driver_patch(
      {
        "lobs": [
          {
            "lob_name": "Advisory",
            "products": [
              {
                "product_name": "Core",
                "unit_price": 100,
                "units_per_period_capacity": 10,
                "avg_units_per_period_year1": 5,
                "operating_periods_per_year": 12,
                "utilization_rate": 0.5,
              }
            ],
          },
          {
            "lob_name": "Audit",
            "products": [
              {
                "product_name": "Core",
                "unit_price": 200,
                "units_per_period_capacity": 8,
                "avg_units_per_period_year1": 4,
                "operating_periods_per_year": 12,
                "utilization_rate": 0.5,
              }
            ],
          },
        ]
      },
      {
        "product_overrides": {
          "advisory::core": {"unit_price": 125},
          "audit::core": {"unit_price": 225},
        }
      },
    )

    lobs = patched.get("lobs") or []
    advisory_price = lobs[0]["products"][0]["unit_price"]
    audit_price = lobs[1]["products"][0]["unit_price"]
    self.assertEqual(advisory_price, 125.0)
    self.assertEqual(audit_price, 225.0)

  def test_apply_revenue_driver_patch_ignores_parent_driver_patch_when_product_overrides_exist(self) -> None:
    patched = apply_revenue_driver_patch(
      {
        "lobs": [
          {
            "lob_name": "Services",
            "products": [
              {
                "product_name": "Advisory",
                "unit_price": 100,
                "units_per_period_capacity": 10,
                "avg_units_per_period_year1": 6,
                "operating_periods_per_year": 12,
                "utilization_rate": 0.6,
              },
              {
                "product_name": "Audit",
                "unit_price": 200,
                "units_per_period_capacity": 6,
                "avg_units_per_period_year1": 3,
                "operating_periods_per_year": 12,
                "utilization_rate": 0.5,
              },
            ],
          }
        ]
      },
      {
        "unit_price": 999,
        "utilization_rate": 0.95,
        "product_overrides": {
          "services::advisory": {"unit_price": 110},
        },
      },
    )

    advisory = patched["lobs"][0]["products"][0]
    audit = patched["lobs"][0]["products"][1]
    self.assertEqual(advisory["unit_price"], 110.0)
    self.assertEqual(audit["unit_price"], 200.0)
    self.assertEqual(audit["utilization_rate"], 0.5)

  def test_financials_year1_weekly_product_uses_weekly_semantics(self) -> None:
    assembled = assemble_financials_year1(
      {
        "operating_model": {
          "business_type": "Tutoring",
          "unit_name": "session",
          "unit_cadence": "weekly",
          "lob_models": [
            {
              "lob_name": "Tutoring",
              "products": [
                {
                  "product_name": "1:1 Tutoring",
                  "unit_name": "session",
                  "unit_cadence": "weekly",
                  "unit_price": 80,
                  "units_per_week_capacity": 30,
                  "avg_units_per_week_year1": 22.5,
                  "operating_weeks_per_year": 48,
                }
              ],
            }
          ],
        }
      }
    )

    product = assembled["lobs"][0]["products"][0]
    self.assertEqual(product["driver_schema"]["cadence_type"], "weekly")
    self.assertEqual(product["avg_units_per_week_year1"], 22.5)
    self.assertEqual(product["operating_weeks_per_year"], 48.0)
    self.assertEqual(product["units_per_week_capacity"], 30.0)
    self.assertEqual(product["annual_units_year1"], 1080.0)
    self.assertEqual(product["revenue_total_year1"], 86400.0)

  def test_financials_year1_monthly_product_uses_monthly_semantics(self) -> None:
    assembled = assemble_financials_year1(
      {
        "operating_model": {
          "business_type": "Subscription Box",
          "unit_name": "subscriber",
          "unit_cadence": "monthly",
          "lob_models": [
            {
              "lob_name": "Memberships",
              "products": [
                {
                  "product_name": "Standard Plan",
                  "unit_name": "subscriber",
                  "unit_cadence": "monthly",
                  "unit_price": 50,
                  "units_per_month_capacity": 400,
                  "avg_units_per_month_year1": 260,
                  "operating_months_per_year": 12,
                }
              ],
            }
          ],
        }
      }
    )

    product = assembled["lobs"][0]["products"][0]
    self.assertEqual(product["driver_schema"]["cadence_type"], "monthly")
    self.assertEqual(product["avg_units_per_month_year1"], 260.0)
    self.assertEqual(product["operating_months_per_year"], 12.0)
    self.assertEqual(product["units_per_month_capacity"], 400.0)
    self.assertEqual(product["annual_units_year1"], 3120.0)
    self.assertEqual(product["revenue_total_year1"], 156000.0)

  def test_financials_year1_contract_product_uses_concurrency_semantics(self) -> None:
    assembled = assemble_financials_year1(
      {
        "operating_model": {
          "business_type": "Law Firm",
          "unit_name": "matter",
          "unit_cadence": "contract",
          "lob_models": [
            {
              "lob_name": "Legal Services",
              "products": [
                {
                  "product_name": "Business Matters",
                  "unit_name": "matter",
                  "unit_cadence": "contract",
                  "unit_price": 12000,
                  "concurrent_capacity_units": 30,
                  "avg_active_units_year1": 22.5,
                  "annual_turns_per_year": 2.5,
                }
              ],
            }
          ],
        }
      }
    )

    product = assembled["lobs"][0]["products"][0]
    self.assertEqual(product["driver_schema"]["cadence_type"], "contract")
    self.assertEqual(product["avg_active_units_year1"], 22.5)
    self.assertEqual(product["annual_turns_per_year"], 2.5)
    self.assertEqual(product["concurrent_capacity_units"], 30.0)
    self.assertEqual(product["annual_completed_units_year1"], 56.25)
    self.assertEqual(product["annual_units_year1"], 56.25)
    self.assertEqual(product["revenue_total_year1"], 675000.0)
    self.assertAlmostEqual(product["utilization_rate"], 0.75, places=6)
    self.assertEqual(product["cadence_metadata"]["authoritative_avg_units_field"], "avg_active_units_year1")

    math_line = build_revenue_math_line(assembled, unit_name="matter")
    self.assertIn("active matter", math_line)
    self.assertIn("~2.5 turns/year", math_line)

    signature = build_revenue_driver_signature(assembled)
    self.assertIn("\"cadence_type\": \"contract\"", signature)
    self.assertIn("\"annual_turns_per_year\": 2.5", signature)

  def test_financials_year1_missing_child_volume_does_not_default_to_full_capacity(self) -> None:
    assembled = assemble_financials_year1(
      {
        "operating_model": {
          "business_type": "Law Firm",
          "unit_name": "matter",
          "unit_cadence": "contract",
          "lob_models": [
            {
              "lob_name": "Legal Services",
              "products": [
                {
                  "product_name": "Business Matters",
                  "unit_name": "matter",
                  "unit_cadence": "contract",
                  "unit_price": 12000,
                  "concurrent_capacity_units": 30,
                  "annual_turns_per_year": 2.5,
                }
              ],
            }
          ],
        }
      }
    )

    product = assembled["lobs"][0]["products"][0]
    self.assertEqual(product["avg_active_units_year1"], 0.0)
    self.assertEqual(product["annual_completed_units_year1"], 0.0)
    self.assertEqual(product["annual_units_year1"], 0.0)
    self.assertEqual(product["revenue_total_year1"], 0.0)

  def test_financials_year1_mixed_child_lobs_preserve_cadence_specific_semantics(self) -> None:
    assembled = assemble_financials_year1(
      {
        "operating_model": {
          "business_type": "Mixed Model",
          "lob_models": [
            {
              "lob_name": "Services",
              "products": [
                {
                  "product_name": "Weekly Care",
                  "unit_name": "visit",
                  "unit_cadence": "weekly",
                  "unit_price": 120,
                  "units_per_week_capacity": 40,
                  "avg_units_per_week_year1": 30,
                  "operating_weeks_per_year": 50,
                }
              ],
            },
            {
              "lob_name": "Cases",
              "products": [
                {
                  "product_name": "Advisory Retainers",
                  "unit_name": "client",
                  "unit_cadence": "contract",
                  "unit_price": 18000,
                  "concurrent_capacity_units": 12,
                  "avg_active_units_year1": 9,
                  "annual_turns_per_year": 1.8,
                }
              ],
            },
          ],
        }
      }
    )

    weekly = assembled["lobs"][0]["products"][0]
    contract = assembled["lobs"][1]["products"][0]
    self.assertEqual(weekly["driver_schema"]["cadence_type"], "weekly")
    self.assertEqual(contract["driver_schema"]["cadence_type"], "contract")
    self.assertEqual(weekly["annual_units_year1"], 1500.0)
    self.assertEqual(contract["annual_completed_units_year1"], 16.2)
    self.assertEqual(
      assembled["company_revenue_total_year1"],
      weekly["revenue_total_year1"] + contract["revenue_total_year1"],
    )

  def test_assemble_financials_year1_does_not_apply_parent_revenue_drivers_to_child_products(self) -> None:
    assembled = assemble_financials_year1(
      {
        "operating_model": {
          "lob_models": [
            {
              "lob_name": "Services",
              "products": [
                {
                  "product_name": "Advisory",
                  "unit_name": "engagement",
                  "unit_cadence": "monthly",
                  "unit_price": 1000,
                  "units_per_period_capacity": 10,
                  "avg_units_per_period_year1": 6,
                  "operating_periods_per_year": 12,
                },
                {
                  "product_name": "Audit",
                  "unit_name": "engagement",
                  "unit_cadence": "monthly",
                  "unit_price": 2000,
                  "units_per_period_capacity": 6,
                  "avg_units_per_period_year1": 3,
                  "operating_periods_per_year": 12,
                },
              ],
            }
          ],
        }
      },
      {
        "unit_price": 9999,
        "utilization_rate": 0.95,
        "lobs": [
          {
            "lob_name": "Services",
            "products": [
              {
                "product_name": "Advisory",
                "unit_price": 1100,
                "avg_units_per_period_year1": 7,
                "utilization_rate": 0.7,
              }
            ],
          }
        ],
      },
    )

    advisory = assembled["lobs"][0]["products"][0]
    audit = assembled["lobs"][0]["products"][1]
    self.assertEqual(advisory["unit_price"], 1100.0)
    self.assertEqual(advisory["utilization_rate"], 0.7)
    self.assertEqual(audit["unit_price"], 2000.0)
    self.assertNotEqual(audit["unit_price"], 9999.0)
    self.assertNotEqual(audit["utilization_rate"], 0.95)

  def test_forecast_engine_carries_child_products_forward(self) -> None:
    bundle = build_forecast_engine_bundle(
      financials_json={
        "cogs_total_year1": 96000,
        "payroll_total_year1": 72000,
        "marketing_total_year1": 12000,
        "other_operating_expense": 18000,
        "annual_interest_payment": 5000,
      },
      financials_year1_json={
        "lobs": [
          {
            "lob_name": "Care",
            "products": [
              {
                "product_name": "Private Duty",
                "unit_price": 35,
                "units_per_period_capacity": 500,
                "avg_units_per_period_year1": 360,
                "operating_periods_per_year": 12,
                "utilization_rate": 0.72,
              },
              {
                "product_name": "Companion",
                "unit_price": 28,
                "units_per_period_capacity": 300,
                "avg_units_per_period_year1": 210,
                "operating_periods_per_year": 12,
                "utilization_rate": 0.7,
              },
            ],
          }
        ],
        "company_revenue_total_year1": 211680,
      },
      normalized_traits={
        "business_stage": "operating",
        "capacity_driver": "labor",
        "sales_modality": "local_service",
      },
      benchmark_payload={
        "confidence_score": 0.8,
        "fallback_level": "naics_6",
        "revenue_growth_path": [0.03, 0.025, 0.02, 0.02],
        "gross_margin_band": {"min": 0.45, "max": 0.55},
        "ebitda_margin_band": {"min": 0.08, "max": 0.18},
        "payroll_intensity": {"min": 0.18, "max": 0.24},
        "opex_intensity": {"min": 0.12, "max": 0.18},
        "capex_percent_revenue": {"min": 0.02, "max": 0.04},
        "depreciation_percent_revenue": {"min": 0.01, "max": 0.02},
        "working_capital": {
          "dso": {"min": 20, "max": 35},
          "dpo": {"min": 15, "max": 30},
          "inventory_days": {"min": 10, "max": 20},
        },
      },
      constraint_engine_state={
        "utilization_range": {"min": 0.5, "max": 0.8},
        "gross_margin_band": {"min": 0.4, "max": 0.6},
        "ebitda_margin_band": {"min": 0.05, "max": 0.2},
        "supportable_unit_range": {"min": 0, "max": 9000},
        "current_metrics": {"utilization_rate": 0.71},
      },
    )

    self.assertEqual(bundle["forecast_engine_state"]["status"], "ready")
    self.assertTrue(bundle["forecast_quarters"])
    self.assertIn("lobs", bundle["forecast_quarters"][0])
    self.assertEqual(len(bundle["forecast_quarters"][0]["lobs"]), 1)
    self.assertEqual(len(bundle["forecast_quarters"][0]["lobs"][0]["products"]), 2)

  def test_direct_solver_inputs_use_structural_payroll_floor_for_labor_business(self) -> None:
    baseline_summary = build_consistency_financial_summary(
      financials_json={
        "cogs_total_year1": 120000,
        "payroll_total_year1": 90000,
        "marketing_total_year1": 20000,
        "other_operating_expense": 30000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 360000,
        "unit_price": 180,
        "utilization_rate": 0.75,
        "avg_units_per_period_year1": 38.461538,
        "operating_periods_per_year": 52,
      },
    )
    state_model = _build_solver_state_model(
      ops_json={
        "unit_price": 180,
        "utilization_rate": 0.75,
        "capacity_driver": "labor",
        "sales_modality": "local_service",
      },
      people_json={
        "people": [
          {"full_name": "Owner", "role_title": "Attorney", "annual_wage": 90000},
        ],
        "inferred_roles": [
          {"role_title": "Paralegal", "annual_wage": 60000, "months_until_hire": 6},
        ],
      },
      financials_json={
        "cogs_total_year1": 120000,
        "payroll_total_year1": 90000,
        "marketing_total_year1": 20000,
        "other_operating_expense": 30000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 360000,
        "unit_price": 180,
        "utilization_rate": 0.75,
        "avg_units_per_period_year1": 38.461538,
        "operating_periods_per_year": 52,
      },
      marketing_model_json={"expected_units_year1": 2000, "reachable_market": 10000},
      baseline_summary=baseline_summary,
      constraint_engine_state={
        "violations": ["payroll_too_light", "ebitda_margin_too_low"],
        "constraint_confidence_score": 0.8,
        "fallback_level": "naics_6",
        "supportable_unit_range": {"min": 1500, "max": 2600},
        "supportable_revenue_range": {"min": 300000, "max": 430000},
        "utilization_range": {"min": 0.6, "max": 0.85},
        "gross_margin_band": {"min": 0.55, "max": 0.7},
        "ebitda_margin_band": {"min": 0.05, "max": 0.18},
        "payroll_intensity_band": {"min": 0.18, "max": 0.4},
        "opex_intensity_band": {"min": 0.08, "max": 0.2},
        "marketing_intensity_band": {"min": 0.03, "max": 0.08},
        "current_metrics": {
          "capacity_units_year1": 2666.6667,
          "people_payroll_floor": 90000,
          "structural_payroll_floor": 105000,
          "active_role_months_year1": 18,
          "fte_equivalent_year1": 1.5,
          "required_fte_from_workload": 1.6,
        },
      },
    )

    direct_inputs = _build_direct_solver_inputs(state_model=state_model or {})

    self.assertIsNotNone(direct_inputs)
    self.assertEqual((direct_inputs or {}).get("people_payroll_floor"), 90000.0)
    self.assertEqual((direct_inputs or {}).get("structural_payroll_floor"), 105000.0)
    self.assertEqual((direct_inputs or {}).get("payroll_support_basis"), "role_months")
    self.assertGreater((direct_inputs or {}).get("units_per_active_role_month", 0.0), 0.0)
    self.assertGreater((direct_inputs or {}).get("adjustable_role_month_cost_floor", 0.0), 0.0)
    self.assertGreaterEqual((direct_inputs or {}).get("target_payroll_min_total", 0.0), 90000.0)

  def test_direct_solver_inputs_do_not_over_tighten_system_business_payroll(self) -> None:
    baseline_summary = build_consistency_financial_summary(
      financials_json={
        "cogs_total_year1": 180000,
        "payroll_total_year1": 45000,
        "marketing_total_year1": 25000,
        "other_operating_expense": 50000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 500000,
        "unit_price": 50,
        "utilization_rate": 0.7,
        "avg_units_per_period_year1": 833.3333,
        "operating_periods_per_year": 12,
      },
    )
    state_model = _build_solver_state_model(
      ops_json={
        "unit_price": 50,
        "utilization_rate": 0.7,
        "capacity_driver": "system",
        "sales_modality": "online",
      },
      people_json={
        "people": [
          {"full_name": "Founder", "role_title": "Operator", "annual_wage": 45000},
        ],
        "inferred_roles": [],
      },
      financials_json={
        "cogs_total_year1": 180000,
        "payroll_total_year1": 45000,
        "marketing_total_year1": 25000,
        "other_operating_expense": 50000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 500000,
        "unit_price": 50,
        "utilization_rate": 0.7,
        "avg_units_per_period_year1": 833.3333,
        "operating_periods_per_year": 12,
      },
      marketing_model_json={"expected_units_year1": 10000, "reachable_market": 50000},
      baseline_summary=baseline_summary,
      constraint_engine_state={
        "violations": ["ebitda_margin_too_low"],
        "constraint_confidence_score": 0.8,
        "fallback_level": "naics_6",
        "supportable_unit_range": {"min": 8000, "max": 14000},
        "supportable_revenue_range": {"min": 400000, "max": 650000},
        "utilization_range": {"min": 0.55, "max": 0.85},
        "gross_margin_band": {"min": 0.45, "max": 0.7},
        "ebitda_margin_band": {"min": 0.08, "max": 0.2},
        "payroll_intensity_band": {"min": 0.06, "max": 0.18},
        "opex_intensity_band": {"min": 0.1, "max": 0.22},
        "marketing_intensity_band": {"min": 0.03, "max": 0.08},
        "current_metrics": {
          "capacity_units_year1": 14285.7143,
          "people_payroll_floor": 45000,
          "structural_payroll_floor": 45000,
          "active_role_months_year1": 12,
          "fte_equivalent_year1": 1.0,
          "required_fte_from_workload": 1.0,
        },
      },
    )

    direct_inputs = _build_direct_solver_inputs(state_model=state_model or {})

    self.assertIsNotNone(direct_inputs)
    self.assertEqual((direct_inputs or {}).get("payroll_support_basis"), "payroll")
    self.assertEqual((direct_inputs or {}).get("structural_payroll_floor"), 45000.0)
    self.assertGreaterEqual((direct_inputs or {}).get("target_payroll_min_total", 0.0), 30000.0)

  def test_solver_clears_payroll_blocker_with_staffing_or_workload_changes(self) -> None:
    solver_state = build_consistency_solver_state(
      ops_json={
        "unit_price": 180,
        "utilization_rate": 0.75,
        "capacity_driver": "labor",
        "sales_modality": "local_service",
      },
      people_json={
        "people": [
          {"full_name": "Owner", "role_title": "Attorney", "annual_wage": 90000},
        ],
        "inferred_roles": [
          {"role_title": "Paralegal", "annual_wage": 60000, "months_until_hire": 6},
        ],
      },
      financials_json={
        "cogs_total_year1": 120000,
        "payroll_total_year1": 90000,
        "marketing_total_year1": 20000,
        "other_operating_expense": 30000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 360000,
        "unit_price": 180,
        "utilization_rate": 0.75,
        "avg_units_per_period_year1": 38.461538,
        "operating_periods_per_year": 52,
      },
      marketing_model_json={"expected_units_year1": 2000, "reachable_market": 10000},
      constraint_engine_state={
        "violations": ["payroll_too_light", "ebitda_margin_too_low"],
        "constraint_confidence_score": 0.8,
        "fallback_level": "naics_6",
        "supportable_unit_range": {"min": 1400, "max": 2400},
        "supportable_revenue_range": {"min": 280000, "max": 420000},
        "utilization_range": {"min": 0.55, "max": 0.85},
        "gross_margin_band": {"min": 0.55, "max": 0.7},
        "ebitda_margin_band": {"min": 0.0, "max": 0.18},
        "payroll_intensity_band": {"min": 0.18, "max": 0.4},
        "opex_intensity_band": {"min": 0.08, "max": 0.2},
        "marketing_intensity_band": {"min": 0.03, "max": 0.08},
        "current_metrics": {
          "capacity_units_year1": 2666.6667,
          "people_payroll_floor": 90000,
          "structural_payroll_floor": 105000,
          "active_role_months_year1": 18,
          "fte_equivalent_year1": 1.5,
          "required_fte_from_workload": 1.6,
        },
      },
    )

    self.assertIsNotNone(solver_state)
    self.assertEqual((solver_state or {}).get("status"), "awaiting_choice")
    scenarios = (solver_state or {}).get("scenarios") or []
    self.assertTrue(scenarios)
    self.assertTrue(
      any(
        "payroll_too_light" not in ((scenario.get("remaining_violations") or []))
        and (
          bool((scenario.get("exact_patches") or {}).get("people_role_updates"))
          or _safe_float(((scenario.get("exact_patches") or {}).get("marketing_model_patch") or {}).get("expected_units_year1")) < 2000.0
          or _normalize_ratio(((scenario.get("exact_patches") or {}).get("financials_year1_patch") or {}).get("utilization_rate")) < 0.75
        )
        for scenario in scenarios
        if isinstance(scenario, dict)
      )
    )

  def test_nontrivial_solver_repairs_use_multiple_meaningful_levers(self) -> None:
    solver_state = build_consistency_solver_state(
      ops_json={
        "unit_price": 120,
        "utilization_rate": 0.7,
        "capacity_driver": "labor",
        "sales_modality": "local_service",
      },
      people_json={
        "people": [{"full_name": "Owner", "role_title": "Therapist", "annual_wage": 80000}],
        "inferred_roles": [
          {"role_title": "Assistant", "annual_wage": 52000, "months_until_hire": 6},
        ],
      },
      financials_json={
        "cogs_total_year1": 85000,
        "payroll_total_year1": 80000,
        "marketing_total_year1": 18000,
        "other_operating_expense": 26000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 260000,
        "unit_price": 120,
        "utilization_rate": 0.7,
        "avg_units_per_period_year1": 41.6667,
        "operating_periods_per_year": 52,
      },
      marketing_model_json={"expected_units_year1": 2167, "reachable_market": 12000},
      constraint_engine_state={
        "violations": ["payroll_too_light", "ebitda_margin_too_low", "marketing_too_high"],
        "constraint_confidence_score": 0.8,
        "fallback_level": "naics_6",
        "supportable_unit_range": {"min": 1500, "max": 2400},
        "supportable_revenue_range": {"min": 220000, "max": 340000},
        "utilization_range": {"min": 0.55, "max": 0.82},
        "gross_margin_band": {"min": 0.5, "max": 0.68},
        "ebitda_margin_band": {"min": 0.04, "max": 0.16},
        "payroll_intensity_band": {"min": 0.2, "max": 0.42},
        "opex_intensity_band": {"min": 0.08, "max": 0.18},
        "marketing_intensity_band": {"min": 0.03, "max": 0.07},
        "current_metrics": {
          "capacity_units_year1": 3095.2381,
          "people_payroll_floor": 80000,
          "structural_payroll_floor": 122000,
          "active_role_months_year1": 18,
          "fte_equivalent_year1": 1.5,
          "required_fte_from_workload": 2.1,
        },
      },
    )

    scenarios = (solver_state or {}).get("scenarios") or []
    self.assertTrue(scenarios)
    self.assertTrue(all((scenario.get("meaningful_lever_count") or 0) >= 2 for scenario in scenarios))
    self.assertTrue(all((scenario.get("coordination_score") or 0.0) > 1.5 for scenario in scenarios))
    self.assertTrue(all((scenario.get("lever_summary") or {}).get("meaningful_families") for scenario in scenarios))

  def test_feasible_solver_scenario_gets_forecast_even_when_baseline_is_blocked(self) -> None:
    bundle = _build_scenario_forecast_bundle(
      baseline_state={
        "ops_json": {
          "unit_price": 100,
          "utilization_rate": 0.6,
          "capacity_driver": "labor",
          "sales_modality": "local_service",
        },
        "people_json": {"people": [], "inferred_roles": []},
        "financials_json": {
          "cogs_total_year1": 96000,
          "payroll_total_year1": 72000,
          "marketing_total_year1": 12000,
          "other_operating_expense": 18000,
          "annual_interest_payment": 5000,
        },
        "financials_year1_json": {
          "company_revenue_total_year1": 240000,
          "unit_price": 100,
          "utilization_rate": 0.6,
          "avg_units_per_period_year1": 200,
          "operating_periods_per_year": 12,
        },
        "marketing_model_json": {"expected_units_year1": 2400, "reachable_market": 12000},
      },
      exact_patches={
        "financials_year1_patch": {"unit_price": 102.0, "utilization_rate": 0.64},
        "financials_patch": {"other_operating_expense": 17000, "cogs_total_year1": 93000},
        "marketing_model_patch": {"expected_units_year1": 2500},
      },
      remaining_violations=[],
      constraint_engine_state={
        "violations": ["ebitda_margin_too_low"],
        "utilization_range": {"min": 0.5, "max": 0.8},
        "gross_margin_band": {"min": 0.55, "max": 0.68},
        "ebitda_margin_band": {"min": 0.18, "max": 0.24},
        "supportable_unit_range": {"min": 1800, "max": 3200},
        "current_metrics": {"utilization_rate": 0.6},
      },
      normalized_traits={
        "business_stage": "operating",
        "capacity_driver": "labor",
        "sales_modality": "local_service",
      },
      benchmark_payload={
        "fallback_level": "naics_6",
        "confidence_score": 0.9,
        "revenue_growth_path": [0.03, 0.025, 0.02, 0.02],
        "gross_margin_band": {"min": 0.58, "max": 0.64},
        "ebitda_margin_band": {"min": 0.18, "max": 0.24},
        "payroll_intensity": {"min": 0.22, "max": 0.34},
        "opex_intensity": {"min": 0.10, "max": 0.18},
        "capex_percent_revenue": {"min": 0.02, "max": 0.04},
        "depreciation_percent_revenue": {"min": 0.01, "max": 0.02},
        "working_capital": {
          "dso": {"min": 20, "max": 35},
          "dpo": {"min": 15, "max": 30},
          "inventory_days": {"min": 10, "max": 20},
        },
      },
    )

    self.assertEqual((bundle.get("forecast_engine_state") or {}).get("status"), "ready")
    self.assertEqual(len(bundle.get("forecast_quarters") or []), 20)
    self.assertEqual(len(bundle.get("forecast_years") or []), 5)
    self.assertIsNotNone((bundle.get("forecast_summary") or {}).get("year5_exit_ebitda"))

  @patch("constraint_engine.extract_normalized_traits")
  @patch("constraint_engine.resolve_alpha_benchmark_payload")
  def test_phase10_constraint_bundle_to_solver_chain_for_multi_product_retail_case(
    self,
    mock_benchmark,
    mock_traits,
  ) -> None:
    mock_traits.return_value = {
      "naics_6": "445110",
      "sector": "Retail Trade",
      "customer_type": "b2c",
      "sales_modality": "retail",
      "capacity_driver": "space",
      "unit_cadence": "weekly",
      "geographic_scope": "local",
      "business_stage": "operating",
      "fulfillment_shape": "in_person_local",
    }
    mock_benchmark.return_value = self._benchmark_payload(
      gross_margin_min=0.34,
      gross_margin_max=0.45,
      ebitda_margin_min=0.03,
      ebitda_margin_max=0.10,
      payroll_min=0.10,
      payroll_max=0.18,
      opex_min=0.08,
      opex_max=0.16,
      inventory_min=18.0,
      inventory_max=40.0,
    )

    ops_json = {"capacity_driver": "space", "sales_modality": "retail"}
    people_json = {
      "people": [{"full_name": "Owner", "role_title": "Manager", "annual_wage": 70000}],
      "inferred_roles": [{"role_title": "Cashier", "annual_wage": 35000, "months_until_hire": 4}],
    }
    financials_json = {
      "cogs_total_year1": 430000,
      "payroll_total_year1": 70000,
      "marketing_total_year1": 18000,
      "other_operating_expense": 90000,
    }
    financials_year1_json = {
      "lobs": [
        {
          "lob_name": "Store",
          "products": [
            {
              "product_name": "Prepared Meals",
              "unit_price": 14,
              "units_per_period_capacity": 900,
              "avg_units_per_period_year1": 720,
              "operating_periods_per_year": 52,
              "utilization_rate": 0.8,
            },
            {
              "product_name": "Catering Trays",
              "unit_price": 90,
              "units_per_period_capacity": 40,
              "avg_units_per_period_year1": 22,
              "operating_periods_per_year": 52,
              "utilization_rate": 0.55,
            },
          ],
        }
      ],
      "company_revenue_total_year1": 627120,
    }
    marketing_model_json = {"expected_units_year1": 38584, "reachable_market": 250000}

    bundle = build_constraint_engine_bundle(
      operating_model_json=ops_json,
      people_json=people_json,
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
      marketing_model_json=marketing_model_json,
    )
    solver_state = build_consistency_solver_state(
      ops_json=ops_json,
      people_json=people_json,
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
      marketing_model_json=marketing_model_json,
      normalized_traits=bundle["normalized_traits"],
      benchmark_payload=bundle["benchmark_payload"],
      constraint_engine_state=bundle["constraint_engine_state"],
    )

    if solver_state is None:
      self.assertEqual(bundle["constraint_engine_state"]["hard_violation_codes"], [])
      return

    self.assertEqual(solver_state["status"], "awaiting_choice")
    self.assertEqual(solver_state["solve_mode"], "child_first")
    strategy_layer = ((solver_state or {}).get("state_model") or {}).get("strategy_layer") or {}
    self.assertLessEqual(len((strategy_layer.get("strategies") or [])), 2)
    scenarios = solver_state.get("scenarios") or []
    self.assertGreaterEqual(len(scenarios), 1)
    self.assertTrue(all((scenario.get("forecast_engine_state") or {}).get("status") == "ready" for scenario in scenarios))
    self.assertTrue(all(len((scenario.get("forecast_quarters") or [])) == 20 for scenario in scenarios))
    for scenario in scenarios:
      year1_patch = ((scenario.get("exact_patches") or {}).get("financials_year1_patch") or {})
      self.assertIn("product_overrides", year1_patch)
      self.assertNotIn("unit_price", year1_patch)
      self.assertNotIn("utilization_rate", year1_patch)

  def test_phase10_regression_matrix_covers_solver_modes_and_outcomes(self) -> None:
    parent_service_case = {
      "name": "single_product_local_service",
      "expected_mode": "parent_fallback",
      "expected_status": "awaiting_choice",
      "ops_json": {
        "unit_price": 180,
        "utilization_rate": 0.75,
        "capacity_driver": "labor",
        "sales_modality": "local_service",
      },
      "people_json": {
        "people": [{"full_name": "Owner", "role_title": "Attorney", "annual_wage": 90000}],
        "inferred_roles": [{"role_title": "Paralegal", "annual_wage": 60000, "months_until_hire": 6}],
      },
      "financials_json": {
        "cogs_total_year1": 120000,
        "payroll_total_year1": 90000,
        "marketing_total_year1": 20000,
        "other_operating_expense": 30000,
      },
      "financials_year1_json": {
        "company_revenue_total_year1": 360000,
        "unit_price": 180,
        "utilization_rate": 0.75,
        "avg_units_per_period_year1": 38.461538,
        "operating_periods_per_year": 52,
      },
      "marketing_model_json": {"expected_units_year1": 2000, "reachable_market": 10000},
      "normalized_traits": {
        "business_stage": "operating",
        "capacity_driver": "labor",
        "sales_modality": "local_service",
      },
      "benchmark_payload": self._benchmark_payload(
        gross_margin_min=0.55,
        gross_margin_max=0.7,
        ebitda_margin_min=0.0,
        ebitda_margin_max=0.18,
        payroll_min=0.18,
        payroll_max=0.4,
        opex_min=0.08,
        opex_max=0.2,
        inventory_min=0.0,
        inventory_max=5.0,
      ),
      "constraint_engine_state": {
        "violations": ["payroll_too_light", "ebitda_margin_too_low"],
        "constraint_confidence_score": 0.8,
        "fallback_level": "naics_6",
        "supportable_unit_range": {"min": 1400, "max": 2400},
        "supportable_revenue_range": {"min": 280000, "max": 420000},
        "utilization_range": {"min": 0.55, "max": 0.85},
        "gross_margin_band": {"min": 0.55, "max": 0.7},
        "ebitda_margin_band": {"min": 0.0, "max": 0.18},
        "payroll_intensity_band": {"min": 0.18, "max": 0.4},
        "opex_intensity_band": {"min": 0.08, "max": 0.2},
        "marketing_intensity_band": {"min": 0.03, "max": 0.08},
        "current_metrics": {
          "capacity_units_year1": 2666.6667,
          "people_payroll_floor": 90000,
          "structural_payroll_floor": 105000,
          "active_role_months_year1": 18,
          "fte_equivalent_year1": 1.5,
          "required_fte_from_workload": 1.6,
        },
      },
    }
    contract_case = {
      "name": "contract_labor_professional_service",
      "expected_mode": "child_first",
      "expected_status": "blocking_unresolved",
      "ops_json": {"capacity_driver": "labor", "sales_modality": "project_based"},
      "people_json": {
        "people": [
          {"full_name": "Partner A", "role_title": "Partner", "annual_wage": 120000},
          {"full_name": "Partner B", "role_title": "Partner", "annual_wage": 60000},
        ],
        "inferred_roles": [
          {"role_title": "Paralegal", "annual_wage": 60000, "months_until_hire": 4},
          {"role_title": "Office Manager", "annual_wage": 50000, "months_until_hire": 8},
        ],
      },
      "financials_json": {
        "cogs_total_year1": 15000,
        "payroll_total_year1": 180000,
        "marketing_total_year1": 12000,
        "other_operating_expense": 50000,
      },
      "financials_year1_json": {
        "lobs": [
          {
            "lob_name": "Legal",
            "products": [
              {
                "product_name": "Retainer Matters",
                "unit_cadence": "contract",
                "unit_price": 18000,
                "units_per_period_capacity": 12,
                "avg_units_per_period_year1": 7,
                "operating_periods_per_year": 2.2,
                "utilization_rate": 0.39,
              }
            ],
          }
        ],
        "company_revenue_total_year1": 277200,
      },
      "marketing_model_json": {"expected_units_year1": 15.4, "reachable_market": 80},
      "normalized_traits": {
        "business_stage": "operating",
        "capacity_driver": "labor",
        "sales_modality": "project_based",
        "unit_cadence": "contract",
      },
      "benchmark_payload": self._benchmark_payload(
        fallback_level="naics_3",
        confidence_score=0.72,
        gross_margin_min=0.72,
        gross_margin_max=0.88,
        ebitda_margin_min=0.08,
        ebitda_margin_max=0.22,
        payroll_min=0.28,
        payroll_max=0.5,
        opex_min=0.06,
        opex_max=0.16,
        inventory_min=0.0,
        inventory_max=3.0,
      ),
      "constraint_engine_state": {
        "violations": ["ebitda_margin_too_low", "payroll_too_light", "utilization_too_low"],
        "constraint_confidence_score": 0.72,
        "fallback_level": "naics_3",
        "supportable_unit_range": {"min": 10, "max": 20},
        "supportable_revenue_range": {"min": 300000, "max": 520000},
        "utilization_range": {"min": 0.55, "max": 0.82},
        "gross_margin_band": {"min": 0.72, "max": 0.9},
        "ebitda_margin_band": {"min": 0.06, "max": 0.2},
        "payroll_intensity_band": {"min": 0.3, "max": 0.52},
        "opex_intensity_band": {"min": 0.05, "max": 0.15},
        "marketing_intensity_band": {"min": 0.01, "max": 0.04},
        "current_metrics": {
          "capacity_units_year1": 24.0,
          "people_payroll_floor": 180000,
          "structural_payroll_floor": 240000,
          "active_role_months_year1": 30,
          "fte_equivalent_year1": 2.5,
          "required_fte_from_workload": 3.4,
        },
      },
    }

    for case in (parent_service_case, contract_case):
      with self.subTest(case=case["name"]):
        solver_state = self._run_solver_case(
          ops_json=case["ops_json"],
          people_json=case["people_json"],
          financials_json=case["financials_json"],
          financials_year1_json=case["financials_year1_json"],
          marketing_model_json=case["marketing_model_json"],
          normalized_traits=case["normalized_traits"],
          benchmark_payload=case["benchmark_payload"],
          constraint_engine_state=case["constraint_engine_state"],
        )
        self.assertEqual(solver_state["solve_mode"], case["expected_mode"])
        self.assertEqual(solver_state["status"], case["expected_status"])
        if case["expected_status"] == "awaiting_choice":
          scenarios = solver_state.get("scenarios") or []
          self.assertTrue(scenarios)
          self.assertLessEqual(len(scenarios), 3)
          if solver_state.get("selection_mode") == "client_ready":
            self.assertTrue(all(not (scenario.get("presentation_issues") or []) for scenario in scenarios))
          else:
            allowed_best_effort_issues = {
              "target_path_miss",
              "degrading_five_year_path",
              "all_negative_five_year_path",
            }
            self.assertTrue(
              all(
                set(scenario.get("presentation_issues") or []).issubset(allowed_best_effort_issues)
                for scenario in scenarios
              )
            )
          self.assertTrue(all((scenario.get("meaningful_lever_count") or 0) >= 2 for scenario in scenarios))
          if case["name"] != "contract_labor_professional_service":
            self.assertGreaterEqual(
              len({str(scenario.get("archetype") or "").strip() for scenario in scenarios if scenario.get("archetype")}),
              min(2, len(scenarios)),
            )
        else:
          self.assertIn(
            solver_state.get("blocking_reason"),
            {"no_client_ready_scenarios", "no_viable_scenarios", "missing_solver_state_model", "gpt_strategy_selection_unavailable"},
          )

  def test_phase10_feasible_solver_cases_emit_ready_forecasts_and_child_only_patches(self) -> None:
    cases = [
      self._run_solver_case(
        ops_json={
          "unit_price": 180,
          "utilization_rate": 0.75,
          "capacity_driver": "labor",
          "sales_modality": "local_service",
        },
        people_json={
          "people": [{"full_name": "Owner", "role_title": "Attorney", "annual_wage": 90000}],
          "inferred_roles": [{"role_title": "Paralegal", "annual_wage": 60000, "months_until_hire": 6}],
        },
        financials_json={
          "cogs_total_year1": 120000,
          "payroll_total_year1": 90000,
          "marketing_total_year1": 20000,
          "other_operating_expense": 30000,
        },
        financials_year1_json={
          "company_revenue_total_year1": 360000,
          "unit_price": 180,
          "utilization_rate": 0.75,
          "avg_units_per_period_year1": 38.461538,
          "operating_periods_per_year": 52,
        },
        marketing_model_json={"expected_units_year1": 2000, "reachable_market": 10000},
        normalized_traits={
          "business_stage": "operating",
          "capacity_driver": "labor",
          "sales_modality": "local_service",
        },
        benchmark_payload=self._benchmark_payload(
          gross_margin_min=0.55,
          gross_margin_max=0.7,
          ebitda_margin_min=0.0,
          ebitda_margin_max=0.18,
          payroll_min=0.18,
          payroll_max=0.4,
          opex_min=0.08,
          opex_max=0.2,
          inventory_min=0.0,
          inventory_max=5.0,
        ),
        constraint_engine_state={
          "violations": ["payroll_too_light", "ebitda_margin_too_low"],
          "constraint_confidence_score": 0.8,
          "fallback_level": "naics_6",
          "supportable_unit_range": {"min": 1400, "max": 2400},
          "supportable_revenue_range": {"min": 280000, "max": 420000},
          "utilization_range": {"min": 0.55, "max": 0.85},
          "gross_margin_band": {"min": 0.55, "max": 0.7},
          "ebitda_margin_band": {"min": 0.0, "max": 0.18},
          "payroll_intensity_band": {"min": 0.18, "max": 0.4},
          "opex_intensity_band": {"min": 0.08, "max": 0.2},
          "marketing_intensity_band": {"min": 0.03, "max": 0.08},
          "current_metrics": {
            "capacity_units_year1": 2666.6667,
            "people_payroll_floor": 90000,
            "structural_payroll_floor": 105000,
            "active_role_months_year1": 18,
            "fte_equivalent_year1": 1.5,
            "required_fte_from_workload": 1.6,
          },
        },
      ),
    ]

    for solver_state in cases:
      with self.subTest(solve_mode=solver_state["solve_mode"]):
        self.assertEqual(solver_state["status"], "awaiting_choice")
        scenarios = solver_state.get("scenarios") or []
        ready_scenarios = [
          scenario for scenario in scenarios
          if (scenario.get("forecast_engine_state") or {}).get("status") == "ready"
        ]
        self.assertTrue(ready_scenarios)
        self.assertTrue(all(len((scenario.get("forecast_quarters") or [])) == 20 for scenario in ready_scenarios))
        self.assertTrue(
          all((scenario.get("forecast_summary") or {}).get("year5_exit_ebitda") is not None for scenario in ready_scenarios)
        )
        self.assertGreaterEqual(
          len({str(scenario.get("archetype_display") or "").strip() for scenario in scenarios if scenario.get("archetype_display")}),
          min(2, len(scenarios)),
        )
        if solver_state["solve_mode"] == "child_first":
          for scenario in scenarios:
            year1_patch = ((scenario.get("exact_patches") or {}).get("financials_year1_patch") or {})
            self.assertIn("product_overrides", year1_patch)
            self.assertNotIn("unit_price", year1_patch)
            self.assertNotIn("utilization_rate", year1_patch)

  def test_phase10_startup_and_operating_forecasts_use_different_convergence_profiles(self) -> None:
    common_inputs = {
      "financials_json": {
        "cogs_total_year1": 180000,
        "payroll_total_year1": 45000,
        "marketing_total_year1": 25000,
        "other_operating_expense": 50000,
        "annual_interest_payment": 5000,
      },
      "financials_year1_json": {
        "company_revenue_total_year1": 500000,
        "unit_price": 50,
        "utilization_rate": 0.7,
        "avg_units_per_period_year1": 833.3333,
        "operating_periods_per_year": 12,
      },
      "constraint_engine_state": {
        "utilization_range": {"min": 0.55, "max": 0.85},
        "gross_margin_band": {"min": 0.45, "max": 0.7},
        "ebitda_margin_band": {"min": 0.08, "max": 0.2},
        "supportable_unit_range": {"min": 8000, "max": 14000},
        "current_metrics": {"utilization_rate": 0.7},
      },
      "benchmark_payload": self._benchmark_payload(
        gross_margin_min=0.45,
        gross_margin_max=0.7,
        ebitda_margin_min=0.08,
        ebitda_margin_max=0.2,
        payroll_min=0.06,
        payroll_max=0.18,
        opex_min=0.1,
        opex_max=0.22,
        inventory_min=0.0,
        inventory_max=3.0,
      ),
    }
    startup_bundle = build_forecast_engine_bundle(
      normalized_traits={
        "business_stage": "startup",
        "capacity_driver": "system",
        "sales_modality": "online",
      },
      **common_inputs,
    )
    operating_bundle = build_forecast_engine_bundle(
      normalized_traits={
        "business_stage": "operating",
        "capacity_driver": "system",
        "sales_modality": "online",
      },
      **common_inputs,
    )

    self.assertEqual(startup_bundle["forecast_engine_state"]["status"], "ready")
    self.assertEqual(operating_bundle["forecast_engine_state"]["status"], "ready")
    startup_policy = startup_bundle["forecast_engine_state"]["convergence_policy"]
    operating_policy = operating_bundle["forecast_engine_state"]["convergence_policy"]
    self.assertGreater(startup_policy["stage_start_quarter"], operating_policy["stage_start_quarter"])
    self.assertLess(startup_policy["global_convergence_strength"], operating_policy["global_convergence_strength"])
    self.assertLess(
      startup_policy["metrics"]["ebitda_margin"]["strength"],
      operating_policy["metrics"]["ebitda_margin"]["strength"],
    )


if __name__ == "__main__":
  unittest.main()
