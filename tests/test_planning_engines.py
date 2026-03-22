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
  _build_direct_solver_inputs,
  _exact_patches_from_solution,
  _build_solver_state_model,
  _solver_required,
  build_consistency_solver_state,
)
from constraint_engine import build_constraint_engine_bundle  # type: ignore  # noqa: E402
from constraint_traits import extract_normalized_traits  # type: ignore  # noqa: E402
from convergence_policy import build_convergence_policy  # type: ignore  # noqa: E402
from forecast_engine import build_forecast_engine_bundle  # type: ignore  # noqa: E402


class PlanningEnginesTests(unittest.TestCase):
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
    direct_inputs = _build_direct_solver_inputs(state_model=state_model or {})
    self.assertIsNotNone(direct_inputs)
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


if __name__ == "__main__":
  unittest.main()
