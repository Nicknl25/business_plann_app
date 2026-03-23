from __future__ import annotations

import sys
import unittest
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
  _build_lever_summary,
  _build_direct_solver_inputs,
  _build_scenario_forecast_bundle,
  _exact_patches_from_solution,
  _build_solver_state_model,
  _label_and_rationale_from_patches,
  _presentation_issues,
  _normalize_ratio,
  _safe_float,
  _select_client_ready_scenarios,
  _select_materially_distinct_scenarios,
  _solver_required,
  _sync_marketing_derived_fields,
  build_consistency_solver_state,
)
from constraint_engine import build_constraint_engine_bundle  # type: ignore  # noqa: E402
from constraint_traits import extract_normalized_traits  # type: ignore  # noqa: E402
from convergence_policy import build_convergence_policy  # type: ignore  # noqa: E402
from forecast_engine import build_forecast_engine_bundle  # type: ignore  # noqa: E402
from financials_year1 import (  # type: ignore  # noqa: E402
  apply_revenue_driver_patch,
  assemble_financials_year1,
  build_revenue_driver_signature,
  build_revenue_math_line,
)


class PlanningEnginesTests(unittest.TestCase):
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

  def test_solver_required_for_high_ebitda_violation(self) -> None:
    required = _solver_required(
      {
        "revenue": 100000,
        "ebitda": 45000,
        "net_income": 40000,
      },
      constraint_engine_state={"violations": ["ebitda_margin_too_high"]},
    )

    self.assertTrue(required)

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

  def test_forecast_engine_blocks_unresolved_year1(self) -> None:
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
      constraint_engine_state={"violations": ["ebitda_margin_too_low"]},
    )

    self.assertEqual(bundle["forecast_engine_state"]["status"], "blocked_unresolved_year1")
    self.assertEqual(bundle["forecast_quarters"], [])

  def test_forecast_engine_blocks_non_ebitda_realism_violations(self) -> None:
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
      constraint_engine_state={"violations": ["gross_margin_too_low"]},
    )

    self.assertEqual(bundle["forecast_engine_state"]["status"], "blocked_unresolved_year1")
    self.assertEqual(bundle["forecast_quarters"], [])

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
    self.assertGreater(current_metrics["structural_payroll_floor"], 100000.0)

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
          "exact_patches": {"financials_year1_patch": {"utilization_rate": 0.68}},
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
          "lever_families": ["marketing", "utilization"],
          "summary": {"revenue": 320000, "marketing": 75000},
          "exact_patches": {"marketing_model_patch": {"expected_units_year1": 4200}},
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
          "lever_families": ["other_opex", "cogs"],
          "summary": {"revenue": 295000, "marketing": 15000},
          "exact_patches": {"financials_patch": {"other_operating_expense": 24000}},
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
    self.assertEqual(bundle["forecast_engine_state"]["status"], "ready")
    self.assertIn("convergence_policy", bundle["forecast_engine_state"])
    self.assertEqual(bundle["engine_versions"]["forecast_engine_version"], "forecast-engine/v3")
    self.assertEqual(bundle["engine_versions"]["convergence_policy_version"], "convergence-policy/v1")

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
                  "units_per_period_capacity": 30,
                  "operating_periods_per_year": 48,
                  "utilization_rate": 0.75,
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
                  "units_per_period_capacity": 400,
                  "avg_units_per_period_year1": 260,
                  "operating_periods_per_year": 12,
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
                  "units_per_period_capacity": 30,
                  "avg_units_per_period_year1": 22.5,
                  "operating_periods_per_year": 2.5,
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
    self.assertEqual(product["annual_completed_units_year1"], 56.25)
    self.assertEqual(product["annual_units_year1"], 56.25)
    self.assertEqual(product["revenue_total_year1"], 675000.0)
    self.assertAlmostEqual(product["utilization_rate"], 0.75, places=6)

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
                  "units_per_period_capacity": 30,
                  "operating_periods_per_year": 2.5,
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
                  "units_per_period_capacity": 40,
                  "avg_units_per_period_year1": 30,
                  "operating_periods_per_year": 50,
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
                  "units_per_period_capacity": 12,
                  "avg_units_per_period_year1": 9,
                  "operating_periods_per_year": 1.8,
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
          "structural_payroll_floor": 160000,
          "active_role_months_year1": 18,
          "fte_equivalent_year1": 1.5,
          "required_fte_from_workload": 2.4,
        },
      },
    )

    direct_inputs = _build_direct_solver_inputs(state_model=state_model or {})

    self.assertIsNotNone(direct_inputs)
    self.assertEqual((direct_inputs or {}).get("people_payroll_floor"), 90000.0)
    self.assertEqual((direct_inputs or {}).get("structural_payroll_floor"), 160000.0)
    self.assertGreater((direct_inputs or {}).get("workload_payroll_per_unit", 0.0), 0.0)
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
    self.assertEqual((direct_inputs or {}).get("workload_payroll_per_unit"), 0.0)
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
          "structural_payroll_floor": 160000,
          "active_role_months_year1": 18,
          "fte_equivalent_year1": 1.5,
          "required_fte_from_workload": 2.4,
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
    solver_state = self._run_solver_case(
      ops_json=ops_json,
      people_json=people_json,
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
      marketing_model_json=marketing_model_json,
      normalized_traits=bundle["normalized_traits"],
      benchmark_payload=bundle["benchmark_payload"],
      constraint_engine_state=bundle["constraint_engine_state"],
    )

    self.assertEqual(solver_state["status"], "awaiting_choice")
    self.assertEqual(solver_state["solve_mode"], "child_first")
    scenarios = solver_state.get("scenarios") or []
    self.assertGreaterEqual(len(scenarios), 2)
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
          "structural_payroll_floor": 160000,
          "active_role_months_year1": 18,
          "fte_equivalent_year1": 1.5,
          "required_fte_from_workload": 2.4,
        },
      },
    }
    retail_child_case = {
      "name": "multi_product_retail",
      "expected_mode": "child_first",
      "expected_status": "awaiting_choice",
      "ops_json": {"capacity_driver": "space", "sales_modality": "retail"},
      "people_json": {
        "people": [{"full_name": "Owner", "role_title": "Manager", "annual_wage": 70000}],
        "inferred_roles": [{"role_title": "Cashier", "annual_wage": 35000, "months_until_hire": 4}],
      },
      "financials_json": {
        "cogs_total_year1": 430000,
        "payroll_total_year1": 70000,
        "marketing_total_year1": 18000,
        "other_operating_expense": 90000,
      },
      "financials_year1_json": {
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
      "marketing_model_json": {"expected_units_year1": 38584, "reachable_market": 250000},
      "normalized_traits": {
        "business_stage": "operating",
        "capacity_driver": "space",
        "sales_modality": "retail",
      },
      "benchmark_payload": self._benchmark_payload(
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
      "constraint_engine_state": {
        "violations": ["ebitda_margin_too_low"],
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

    for case in (parent_service_case, retail_child_case, contract_case):
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
          self.assertTrue(all(not (scenario.get("presentation_issues") or []) for scenario in scenarios))
          self.assertTrue(all((scenario.get("meaningful_lever_count") or 0) >= 2 for scenario in scenarios))
          self.assertGreaterEqual(
            len({str(scenario.get("archetype") or "").strip() for scenario in scenarios if scenario.get("archetype")}),
            min(2, len(scenarios)),
          )
        else:
          self.assertIn(
            solver_state.get("blocking_reason"),
            {"no_client_ready_scenarios", "no_viable_scenarios", "missing_solver_state_model"},
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
            "structural_payroll_floor": 160000,
            "active_role_months_year1": 18,
            "fte_equivalent_year1": 1.5,
            "required_fte_from_workload": 2.4,
          },
        },
      ),
      self._run_solver_case(
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
