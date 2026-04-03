from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = ROOT / "python"
CLIENT_DIR = PYTHON_DIR / "client_intake_and_finmo"
if str(PYTHON_DIR) not in sys.path:
  sys.path.insert(0, str(PYTHON_DIR))
if str(CLIENT_DIR) not in sys.path:
  sys.path.insert(0, str(CLIENT_DIR))

from api_handlers.intake_consult import (
  _backfill_planning_run_from_closeout,
  _apply_scoped_patch,
  _build_financials_live_turn,
  _build_intake_complete_planning_run_payload,
  _build_consistency_business_model_snapshot,
  _build_consistency_candidate_issues,
  _build_consistency_coherence_signals,
  _build_consistency_controller_state,
  _build_consistency_reality_overview,
  _build_consistency_runtime_payload_for_persistence,
  _consistency_followup_state,
  _next_focus_from_consistency_closeout,
  _render_consistency_assistant_text,
  _normalize_financials_router_patch,
  _run_financials_turn_and_sync,
  _run_consistency_closeout,
  _financials_stage_default_patch,
  _should_run_consistency_on_confirm,
  _build_planning_run_payload,
  _consistency_closeout_ready_for_completion,
)
from client_intake_and_finmo.finmo_bridge import _annualized_lease_commitment, build_python_finmo_json, build_python_model_input_json
from client_intake_and_finmo.intake_consult_draft import _is_valid_planning_run_payload
from client_intake_and_finmo.realism_memo import (
  build_realism_memo_input,
  empty_realism_memo_payload,
  generate_realism_memo_payload,
  generate_realism_memo_payload_safe,
  is_valid_realism_memo_payload,
  load_realism_memo_grid_advisory_prompt,
  load_realism_memo_reviewer_prompt,
  normalize_realism_memo_payload,
  realism_memo_schema,
)
from client_intake_and_finmo.quarter_grid import (
  _clip_shared_capacity_max_bands,
  available_planning_modes,
  build_governor_payload_from_context,
  build_quarter_grid_prompt,
  determine_planning_mode,
  extract_quarter_grid_rows,
  planning_mode_prompt_file,
  quarter_grid_system_prompt,
)
from financial_model_engine.finmo_model import calculate_finmo_model
from financial_model_engine.model_inputs import FinancialModelInputs


def _sample_model_input_json() -> dict:
  return {
    "start_date": "2026-03-31",
    "periods": [{"quarter_index": index} for index in range(0, 21)],
    "sections": {
      "revenue": [
        {
          "lever_id": "revenue::fitness_gym::Membership::Capacity",
          "label": "Membership Capacity",
          "values": [0] + [100.0] * 20,
        },
        {
          "lever_id": "revenue::fitness_gym::Membership::Unit Price",
          "label": "Membership Price",
          "values": [0] + [125.0] * 20,
        },
      ],
      "expenses": [
        {
          "lever_id": "expenses::Payroll",
          "label": "Payroll",
          "controller_write": True,
          "values": [0] + [50000.0] * 20,
        },
      ],
      "balance_sheet": [
        {
          "lever_id": "balance_sheet::PPE $ (Excluding Capital Leases)",
          "label": "PPE",
          "controller_write": True,
          "values": [0] + [4000.0] * 20,
        },
        {
          "lever_id": "balance_sheet::Accumulated Depreciation",
          "label": "Accumulated Depreciation",
          "controller_write": True,
          "values": [0] + [-500.0] * 20,
        },
        {
          "lever_id": "balance_sheet::Owner's Capital",
          "label": "Owner's Capital",
          "controller_write": True,
          "values": [0] + [10000.0] * 20,
        },
      ],
      "schedules": {
        "rows": [
          {
            "lever_id": "schedules::Capital Expenditures",
            "label": "Capital Expenditures",
            "controller_write": True,
            "values": [0] + [1000.0] * 20,
          },
          {
            "lever_id": "schedules::Plus: Net Additions",
            "label": "Lease Additions",
            "controller_write": True,
            "values": [0] + [250.0] * 20,
          },
        ]
      },
    },
  }


def _sample_finmo_json(*, revenue: float, ebitda: float, ending_cash: float) -> dict:
  quarter_rows = []
  for quarter_index in range(1, 21):
    quarter_rows.append(
      {
        "quarter_index": quarter_index,
        "revenue": revenue,
        "ebitda": ebitda,
        "ending_cash": ending_cash,
        "cost_of_goods_sold": revenue * 0.4,
        "gross_profit": revenue * 0.6,
        "payroll": 50000.0,
        "marketing": 15000.0,
        "lease_rent": 5000.0,
        "general_and_administrative": 12000.0,
        "research_and_development": 0.0,
        "net_income": ebitda * 0.7,
      }
    )
  return {"quarter_rows": quarter_rows}


def _accounting_model_input_json(
  *,
  cash_opening: float,
  ppe_opening: float,
  lease_opening: float,
  owners_capital: float,
  capex: float,
  lease_additions: float,
  lease_principal: float,
  depreciation_rate: float = 0.0,
) -> dict:
  zeros = [0.0] * 20
  return {
    "start_date": "2026-03-31",
    "periods": [{"quarter_index": index} for index in range(1, 21)],
    "sections": {
      "revenue": [],
      "expenses": [
        {"lever_id": "expenses::Cost of Goods Sold", "label": "Cost of Goods Sold", "controller_write": True, "values": zeros},
        {"lever_id": "expenses::Marketing", "label": "Marketing", "controller_write": True, "values": zeros},
        {"lever_id": "expenses::Research & Development", "label": "Research & Development", "controller_write": True, "values": zeros},
        {"lever_id": "expenses::Lease", "label": "Lease", "controller_write": True, "values": zeros},
        {"lever_id": "expenses::Payroll", "label": "Payroll", "controller_write": True, "values": zeros},
        {"lever_id": "expenses::General & Administrative", "label": "General & Administrative", "controller_write": True, "values": zeros},
        {"lever_id": "expenses::Interest Rate", "label": "Interest Rate", "controller_write": True, "values": zeros},
        {"lever_id": "expenses::Depreciation", "label": "Depreciation", "controller_write": True, "values": [depreciation_rate] * 20},
        {"lever_id": "expenses::Taxes", "label": "Taxes", "controller_write": True, "values": zeros},
      ],
      "balance_sheet": [
        {"lever_id": "balance_sheet::Accounts Receivable Days", "label": "Accounts Receivable Days", "controller_write": True, "values": zeros},
        {"lever_id": "balance_sheet::Inventory Days", "label": "Inventory Days", "controller_write": True, "values": zeros},
        {"lever_id": "balance_sheet::Prepaid Expenses (% of Revenue)", "label": "Prepaid Expenses (% of Revenue)", "controller_write": True, "values": zeros},
        {"lever_id": "balance_sheet::Accounts Payable Days", "label": "Accounts Payable Days", "controller_write": True, "values": zeros},
        {"lever_id": "balance_sheet::Short Term Debt (% of LTD)", "label": "Short Term Debt (% of LTD)", "controller_write": True, "values": zeros},
        {"lever_id": "balance_sheet::Deferred Revenue (% of Revenue)", "label": "Deferred Revenue (% of Revenue)", "controller_write": True, "values": zeros},
        {"lever_id": "balance_sheet::Owner's Capital", "label": "Owner's Capital", "controller_write": True, "values": [owners_capital] * 20},
        {"lever_id": "balance_sheet::Other Equity", "label": "Other Equity", "controller_write": True, "values": zeros},
      ],
      "schedules": {
        "cash_opening_balance_seed": cash_opening,
        "ppe_opening_balance_seed": ppe_opening,
        "lease_opening_balance_seed": lease_opening,
        "rows": [
          {"lever_id": "schedules::Plus: Additions (repayments), net", "label": "Plus: Additions (repayments), net", "controller_write": True, "values": zeros},
          {"lever_id": "schedules::Capital Expenditures", "label": "Capital Expenditures", "controller_write": True, "values": [capex] + [0.0] * 19},
          {"lever_id": "schedules::Less: Principal Repayments", "label": "Less: Principal Repayments", "controller_write": True, "values": [lease_principal] + [0.0] * 19},
          {"lever_id": "schedules::Plus: Net Additions", "label": "Plus: Net Additions", "controller_write": True, "values": [lease_additions] + [0.0] * 19},
        ],
      },
    },
  }


class QuarterGridTests(unittest.TestCase):
  def test_prompt_modes_are_file_backed(self) -> None:
    modes = available_planning_modes()
    self.assertIn("turnaround", modes)
    self.assertIn("normalize", modes)
    self.assertIn("rebalance", modes)
    for mode in ("turnaround", "normalize", "rebalance"):
      self.assertTrue(Path(planning_mode_prompt_file(mode)).exists())

  def test_extract_quarter_grid_rows_excludes_derived_ppe_rows(self) -> None:
    rows = extract_quarter_grid_rows(
      model_input_json=_sample_model_input_json(),
      baseline_outputs=_sample_finmo_json(revenue=100000.0, ebitda=5000.0, ending_cash=20000.0)["quarter_rows"],
    )
    row_ids = {str(item.get("row_id") or "") for item in rows}
    self.assertIn("revenue::fitness_gym::Membership::Capacity", row_ids)
    self.assertIn("expenses::Payroll", row_ids)
    self.assertIn("schedules::Capital Expenditures", row_ids)
    self.assertIn("Revenue", row_ids)
    self.assertIn("EBITDA", row_ids)
    self.assertIn("Cash", row_ids)
    self.assertNotIn("balance_sheet::PPE $ (Excluding Capital Leases)", row_ids)
    self.assertNotIn("balance_sheet::Accumulated Depreciation", row_ids)

  def test_determine_planning_mode_turnaround(self) -> None:
    result = determine_planning_mode(
      ops_json={},
      target_market_json={},
      people_json={},
      financials_json={},
      financials_year1_json={},
      fulfillment_json={},
      marketing_model_json={},
      model_input_json=_sample_model_input_json(),
      finmo_json=_sample_finmo_json(revenue=100000.0, ebitda=-25000.0, ending_cash=-5000.0),
      business_facts={},
    )
    self.assertEqual(result["planning_mode"], "turnaround")

  def test_determine_planning_mode_normalize(self) -> None:
    result = determine_planning_mode(
      ops_json={},
      target_market_json={},
      people_json={},
      financials_json={},
      financials_year1_json={},
      fulfillment_json={},
      marketing_model_json={},
      model_input_json=_sample_model_input_json(),
      finmo_json=_sample_finmo_json(revenue=100000.0, ebitda=45000.0, ending_cash=90000.0),
      business_facts={},
    )
    self.assertEqual(result["planning_mode"], "normalize")

  def test_governor_payload_includes_lob_product_summary(self) -> None:
    payload = build_governor_payload_from_context(
      ops_json={
        "lob_models": [
          {
            "lob_name": "IV Therapy",
            "products": [
              {"product_name": "Pay Per Visit", "unit_name": "visit", "unit_cadence": "monthly", "unit_description": "one IV visit"},
              {"product_name": "Membership", "unit_name": "member month", "unit_cadence": "monthly", "unit_description": "monthly plan including visits"},
              {"product_name": "Retail Products", "unit_name": "item", "unit_cadence": "monthly", "unit_description": "supplement product sale"},
            ],
          }
        ]
      },
      target_market_json={},
      people_json={},
      financials_json={},
      financials_year1_json={},
      fulfillment_json={},
      marketing_model_json={},
      model_input_json=_sample_model_input_json(),
      finmo_json=_sample_finmo_json(revenue=100000.0, ebitda=5000.0, ending_cash=20000.0),
      business_facts={},
    )
    self.assertIn("ops_lob_product_summary", payload)
    self.assertEqual(payload["ops_lob_product_summary"][0]["product_count"], 3)

  def test_quarter_grid_prompt_contains_shared_capacity_rule(self) -> None:
    prompt = build_quarter_grid_prompt(
      source_row={"business_name": "Test Biz"},
      grid_rows=extract_quarter_grid_rows(
        model_input_json=_sample_model_input_json(),
        baseline_outputs=_sample_finmo_json(revenue=100000.0, ebitda=5000.0, ending_cash=20000.0)["quarter_rows"],
      )[:2],
      governor_payload={"ops_lob_product_summary": [{"lob_name": "IV Therapy", "product_count": 3}]},
      batch_index=1,
      batch_count=1,
      planning_mode="turnaround",
    )
    self.assertIn("Shared-capacity rule:", prompt)
    self.assertIn("treat that LOB's capacity as one conserved 100% pool", prompt)
    self.assertIn("must fit within that one whole capacity pool", prompt)
    self.assertIn("only treat product capacities as fully independent when the business context clearly supports separate operating capacity", prompt)

  def test_shared_capacity_clipper_trims_only_overflowing_max_band(self) -> None:
    response_json = {
      "summary": "test",
      "rows": [
        {
          "row_id": "revenue::Primary line of business::Individual IV session::Capacity",
          "row_type": "lever",
          "quarter_bands": [{"quarter_index": q, "min_value": 230.0, "max_value": 260.0} for q in range(1, 21)],
        },
        {
          "row_id": "revenue::Primary line of business::Monthly IV membership::Capacity",
          "row_type": "lever",
          "quarter_bands": [{"quarter_index": q, "min_value": 40.0, "max_value": 60.0} for q in range(1, 21)],
        },
        {
          "row_id": "revenue::Primary line of business::Retail wellness products::Capacity",
          "row_type": "lever",
          "quarter_bands": [{"quarter_index": q, "min_value": 80.0, "max_value": 120.0} for q in range(1, 21)],
        },
      ],
    }
    financials_year1_json = {
      "lobs": [
        {
          "lob_name": "Primary line of business",
          "products": [
            {
              "product_name": "Individual IV session",
              "unit_name": "individual IV session",
              "unit_description": "A single mobile IV hydration or vitamin therapy treatment delivered at the client's home or office.",
              "annual_units_year1": 728.0,
              "units_per_period_capacity": 20.0,
              "operating_periods_per_year": 52.0,
            },
            {
              "product_name": "Monthly IV membership",
              "unit_name": "monthly IV membership",
              "unit_description": "One active IV membership for one month, including up to four IV sessions during that month.",
              "annual_units_year1": 120.0,
              "units_per_period_capacity": 20.0,
              "operating_periods_per_year": 12.0,
            },
            {
              "product_name": "Retail wellness products",
              "unit_name": "individual retail item",
              "unit_description": "A single wellness product item such as a bottle or box of vitamins or supplements sold to a customer.",
              "annual_units_year1": 0.0,
              "units_per_period_capacity": 20.0,
              "operating_periods_per_year": 12.0,
            },
          ],
        }
      ]
    }
    clipped = _clip_shared_capacity_max_bands(
      response_json=response_json,
      ops_json={
        "lob_models": [
          {
            "lob_name": "Primary line of business",
            "products": [
              {"product_name": "Individual IV session"},
              {"product_name": "Monthly IV membership"},
              {"product_name": "Retail wellness products"},
            ],
          }
        ]
      },
      financials_year1_json=financials_year1_json,
    )
    result_json = clipped["response_json"]
    iv_row = next(item for item in result_json["rows"] if item["row_id"].endswith("Individual IV session::Capacity"))
    membership_row = next(item for item in result_json["rows"] if item["row_id"].endswith("Monthly IV membership::Capacity"))
    retail_row = next(item for item in result_json["rows"] if item["row_id"].endswith("Retail wellness products::Capacity"))
    self.assertLess(iv_row["quarter_bands"][0]["max_value"], 260.0)
    self.assertLess(membership_row["quarter_bands"][0]["max_value"], 60.0)
    self.assertLess(retail_row["quarter_bands"][0]["max_value"], 120.0)
    self.assertTrue(clipped["clips"])


class FinmoAccountingTests(unittest.TestCase):
  def test_lease_additions_flow_to_ppe_and_accounting_holds(self) -> None:
    model_input_json = _accounting_model_input_json(
      cash_opening=1000.0,
      ppe_opening=500.0,
      lease_opening=1000.0,
      owners_capital=500.0,
      capex=100.0,
      lease_additions=300.0,
      lease_principal=200.0,
      depreciation_rate=0.10,
    )
    result = calculate_finmo_model(FinancialModelInputs.from_model_input_json(model_input_json))
    q1 = result.quarter_rows()[0]
    self.assertAlmostEqual(q1["ppe"], 850.0, places=6)
    self.assertAlmostEqual(q1["lease_closing_balance_total"], 1100.0, places=6)
    self.assertAlmostEqual(q1["financing_cash_flow"], -200.0, places=6)
    self.assertAlmostEqual(q1["investing_cash_flow"], -100.0, places=6)
    self.assertAlmostEqual(q1["accounting_equation_check"], 0.0, places=6)

    finmo_json = build_python_finmo_json(model_input_json=model_input_json)
    self.assertTrue(finmo_json["accounting_check"]["all_ok"])

  def test_principal_repayment_is_capped_to_available_lease_balance(self) -> None:
    model_input_json = _accounting_model_input_json(
      cash_opening=0.0,
      ppe_opening=0.0,
      lease_opening=0.0,
      owners_capital=0.0,
      capex=0.0,
      lease_additions=0.0,
      lease_principal=500.0,
      depreciation_rate=0.0,
    )
    result = calculate_finmo_model(FinancialModelInputs.from_model_input_json(model_input_json))
    q1 = result.quarter_rows()[0]
    self.assertAlmostEqual(q1["lease_principal_repayments"], 0.0, places=6)
    self.assertAlmostEqual(q1["lease_closing_balance_total"], 0.0, places=6)
    self.assertAlmostEqual(q1["financing_cash_flow"], 0.0, places=6)
    self.assertAlmostEqual(q1["accounting_equation_check"], 0.0, places=6)


class InitialLeaseModelingTests(unittest.TestCase):
  def test_annualized_lease_commitment_parses_amount_and_period(self) -> None:
    self.assertEqual(_annualized_lease_commitment("1200,monthly"), 14400.0)
    self.assertEqual(_annualized_lease_commitment("500,quarterly"), 2000.0)
    self.assertEqual(_annualized_lease_commitment("0,none"), 0.0)

  def test_build_python_model_input_json_seeds_lease_from_initial_lease_answer(self) -> None:
    model_input_json = build_python_model_input_json(
      business_facts={"business_name": "Lease Test", "start_date": "2026-03-31"},
      ops_json={},
      people_json={},
      financials_json={"initial_lease": "1200,monthly"},
      financials_year1_json={},
      marketing_model_json={},
    )
    schedules = model_input_json.get("sections", {}).get("schedules", {})
    self.assertEqual(schedules.get("lease_opening_balance_seed"), 14400.0)


class ConsistencyConsultTests(unittest.TestCase):
  def test_consistency_reality_overview_includes_cross_model_fields(self) -> None:
    overview = _build_consistency_reality_overview(
      business_facts={"name": "Test Clinic"},
      ops_json={
        "business_stage": "operating",
        "unit_name": "treatment session",
        "unit_cadence": "weekly",
        "unit_price": 300.0,
        "capacity_driver": "labor",
        "primary_growth_lever": "add providers",
        "consumer_type": "consumer",
        "lob_models": [{"lob_name": "Primary", "products": [{"product_name": "Session"}]}],
      },
      market_json={"target_market_summary": "Adults 30-60 with higher disposable income."},
      people_json={"people": [{"name": "Owner"}], "key_people_summary": "Owner-led clinical operator."},
      financials_json={
        "cash_on_hand": 15000.0,
        "monthly_rent_expense": 5000.0,
        "other_operating_expense": 2500.0,
        "initial_equity": 100000.0,
        "total_debt_outstanding": 20000.0,
      },
      financials_year1_json={"company_revenue_total_year1": 500000.0},
      fulfillment_json={"personnel": "owner", "time": "booked appointments"},
    )
    self.assertEqual(overview["business_name"], "Test Clinic")
    self.assertEqual(overview["product_count"], 1)
    self.assertEqual(overview["core_unit_name"], "treatment session")
    self.assertEqual(overview["people_count"], 1)
    self.assertEqual(overview["cash_on_hand"], 15000.0)
    self.assertEqual(overview["year1_revenue"], 500000.0)

  def test_consistency_business_model_snapshot_includes_structural_context(self) -> None:
    snapshot = _build_consistency_business_model_snapshot(
      business_facts={"name": "Precision Aesthetics Lab"},
      ops_json={
        "business_type": "medical spa",
        "business_naics_6": "621999",
        "business_stage": "operating",
        "legal_entity": "LLC",
        "business_description_summary": "Premium in-studio aesthetics business.",
        "consumer_type": "consumer",
        "shipping_method": "in_person",
        "sales_modality": "appointment",
        "geographic_scope": "local",
        "geographic_coverage": "Dallas metro area",
        "capacity_driver": "licensed provider time",
        "competitive_advantage": "Specialized treatments with efficient room scheduling.",
        "primary_growth_lever": "add providers",
        "milestones": [{"description": "Reach 70 sessions per week", "timing": "within 12 months", "timing_months_max": 12}],
      },
      market_json={
        "target_market_summary": "Affluent consumers seeking aesthetic treatments.",
        "marketing_plan_summary": "Paid search and referrals.",
        "income_intent": [{"income_min": 60000, "income_max": 1000000}],
        "gender_age_intent": [{"gender": "female", "age_min": 30, "age_max": 65}],
        "selections": [{"segment_name": "College educated"}],
      },
      people_json={
        "key_people_summary": "Solo founder-operator.",
        "people": [{"full_name": "Alex Stone", "role_title": "Owner / Nurse Practitioner", "annual_wage": 120000}],
        "inferred_roles": [{"role_title": "Front Desk Coordinator", "annual_wage": 45000, "months_until_hire": 6}],
      },
      financials_json={
        "payroll_total_year1": 120000,
        "owner_compensation": 120000,
        "cash_on_hand": 15000,
        "monthly_rent_expense": 9500,
        "other_operating_expense": 4000,
        "other_monthly_debt_payments": 1500,
        "initial_assets": 180000,
        "initial_equity": 50000,
        "total_debt_outstanding": 120000,
        "annual_interest_payment": 9000,
        "annual_principal_payment": 18000,
      },
      financials_year1_json={
        "company_revenue_total_year1": 2200000,
        "lobs": [
          {
            "lob_name": "Primary line of business",
            "revenue_total_year1": 2200000,
            "products": [
              {
                "product_name": "Advanced aesthetic treatment",
                "unit_name": "session",
                "unit_description": "One completed premium treatment session.",
                "unit_cadence": "weekly",
                "unit_price": 875,
                "units_per_period_capacity": 55,
                "units_per_week_capacity": 55,
                "operating_periods_per_year": 52,
                "utilization_rate": 0.88,
                "annual_units_year1": 2516,
                "revenue_total_year1": 2200000,
              }
            ],
          }
        ],
      },
      fulfillment_json={"personnel": "owner", "time": "scheduled appointments"},
    )
    self.assertEqual(snapshot["business_identity"]["business_type"], "medical spa")
    self.assertEqual(snapshot["operating_model"]["delivery_model"]["sales_modality"], "appointment")
    self.assertEqual(snapshot["products_and_economics"]["product_count"], 1)
    self.assertEqual(
      snapshot["products_and_economics"]["lobs"][0]["products"][0]["unit_price"], 875
    )
    self.assertEqual(snapshot["people_model"]["people_count"], 1)
    self.assertEqual(snapshot["growth_plan"]["milestones"][0]["timing_months_max"], 12)
    self.assertEqual(snapshot["target_customer"]["income_intent_summary"], "$60,000-$1,000,000")
    self.assertEqual(snapshot["financial_position"]["total_debt_outstanding"], 120000)

  def test_consistency_coherence_signals_surface_goal_capacity_and_price_signals(self) -> None:
    signals = _build_consistency_coherence_signals(
      ops_json={
        "business_type": "medical spa",
        "consumer_type": "consumer",
        "capacity_driver": "licensed provider time",
        "shipping_method": "in_person",
        "sales_modality": "appointment",
        "milestones": [
          {"description": "Reach about 70 treatment sessions per week within 12 months.", "timing": "within 12 months", "timing_months_max": 12}
        ],
      },
      market_json={
        "consumer_type": "consumer",
        "target_market_summary": "Affluent but broad consumers.",
        "income_intent": [{"income_min": 60000, "income_max": 1000000}],
      },
      people_json={
        "people": [{"full_name": "Alex Stone", "role_title": "Owner / Nurse Practitioner"}],
        "inferred_roles": [],
      },
      financials_json={
        "payroll_total_year1": 120000,
        "cash_on_hand": 15000,
        "monthly_rent_expense": 9500,
        "other_operating_expense": 4000,
        "other_monthly_debt_payments": 1500,
      },
      financials_year1_json={
        "lobs": [
          {
            "lob_name": "Primary line of business",
            "products": [
              {
                "product_name": "Advanced aesthetic treatment",
                "unit_cadence": "weekly",
                "unit_price": 875,
                "units_per_period_capacity": 55,
                "units_per_week_capacity": 55,
                "operating_periods_per_year": 52,
                "utilization_rate": 0.88,
                "avg_units_per_period_year1": 48.4,
                "annual_units_year1": 2516.8,
                "revenue_total_year1": 2202200,
              }
            ],
          }
        ]
      },
      fulfillment_json={"personnel": "owner", "time": "scheduled appointments"},
    )
    self.assertEqual(signals["people_workload_signals"]["current_people_count"], 1)
    self.assertEqual(signals["goal_signals"][0]["cadence_hint"], "weekly")
    self.assertEqual(signals["direct_goal_capacity_tensions"][0]["goal_value"], 70.0)
    self.assertEqual(signals["direct_goal_capacity_tensions"][0]["product_capacity"], 55.0)
    self.assertEqual(signals["price_market_signals"]["price_points"][0]["income_floor"], 60000)
    self.assertEqual(signals["cash_obligation_signals"]["fixed_monthly_burden_estimate"], 25000.0)

  def test_render_consistency_assistant_text_renders_fact_templates_and_cleans_zero_pairs(self) -> None:
    rendered = _render_consistency_assistant_text(
      "Cash is {{fact:financials.cash_on_hand}} and debt is {{fact:financials.total_debt_outstanding}}. That is 0 of 0.",
      shared_context={"financials": {"cash_on_hand": 0, "total_debt_outstanding": 0}},
      business_facts={},
    )
    self.assertNotIn("{{fact:", rendered)
    self.assertNotIn("0 of 0", rendered)
    self.assertIn("$0", rendered)


class FinancialsRouterPatchTests(unittest.TestCase):
  def test_financials_router_patch_annualizes_owner_comp_monthly_answer(self) -> None:
    patched = _normalize_financials_router_patch(
      patch={"owner_compensation": 10000},
      active_stage="owner_compensation",
      financials_json={},
      financials_year1_json={},
      last_assistant="For owner compensation, as of last month, about how much did you pay yourself from the business, in dollars per month on average?",
      user_message="I paid myself 10000 last month.",
    )
    self.assertIsInstance(patched, dict)
    self.assertEqual(patched["owner_compensation"], 120000.0)

  def test_financials_router_patch_does_not_double_annualize_owner_comp(self) -> None:
    patched = _normalize_financials_router_patch(
      patch={"owner_compensation": 120000},
      active_stage="owner_compensation",
      financials_json={},
      financials_year1_json={},
      last_assistant="As of last month, how much did you pay yourself from the business in wages, draws, or other owner compensation? A dollar amount is fine.",
      user_message="I paid myself 10000 last month, which aligns with my annual owner compensation of 120000.",
    )
    self.assertIsInstance(patched, dict)
    self.assertEqual(patched["owner_compensation"], 120000.0)

  def test_financials_router_patch_accepts_employee_count_stage(self) -> None:
    patched = _normalize_financials_router_patch(
      patch={"current_num_employees": 1},
      active_stage="current_num_employees",
      financials_json={},
      financials_year1_json={},
      last_assistant="What number should I record for current employee count? A whole number is fine.",
      user_message="There is just one person on payroll.",
    )
    self.assertIsInstance(patched, dict)
    self.assertEqual(patched["current_num_employees"], 1)

  def test_financials_router_patch_converts_cogs_percent_to_amount(self) -> None:
    patched = _normalize_financials_router_patch(
      patch={"cogs_percent_of_revenue": 0.22},
      active_stage="cogs",
      financials_json={},
      financials_year1_json={"company_revenue_total_year1": 1000000.0},
      last_assistant="Should I use this Year-1 direct-cost baseline?",
      user_message="Use 22% COGS.",
    )
    self.assertIsInstance(patched, dict)
    self.assertEqual(float(patched["current_cogs"]), 220000.0)
    self.assertEqual(float(patched["cogs_total_year1"]), 220000.0)

  def test_financials_router_patch_normalizes_whole_number_cogs_percent(self) -> None:
    patched = _normalize_financials_router_patch(
      patch={"cogs_percent_of_revenue": 22},
      active_stage="cogs",
      financials_json={},
      financials_year1_json={"company_revenue_total_year1": 1000000.0},
      last_assistant="Does that broadly match how your business works, or should we adjust it because your direct costs are materially different?",
      user_message="Please use 22% COGS.",
    )
    self.assertIsInstance(patched, dict)
    self.assertAlmostEqual(float(patched["cogs_percent_of_revenue"]), 0.22, places=6)
    self.assertEqual(float(patched["cogs_total_year1"]), 220000.0)

  def test_financials_router_patch_annualizes_marketing_monthly_amount(self) -> None:
    patched = _normalize_financials_router_patch(
      patch={"marketing_total_year1": 4000},
      active_stage="marketing",
      financials_json={},
      financials_year1_json={"company_revenue_total_year1": 1000000.0},
      last_assistant="Does that broadly match what it will take to attract and convert customers in Year 1, or should we adjust it because your marketing spend will be materially different?",
      user_message="Use 4000 per month for marketing.",
    )
    self.assertIsInstance(patched, dict)
    self.assertEqual(float(patched["marketing_total_year1"]), 48000.0)
    self.assertAlmostEqual(float(patched["marketing_percent_of_revenue"]), 0.048, places=6)

  def test_build_financials_live_turn_sets_active_stage(self) -> None:
    with patch(
      "api_handlers.intake_consult._resolve_cogs_baseline_or_raise",
      return_value={"baseline_cogs": 220000.0, "baseline_cogs_percent": 0.22},
    ):
      turn, financials_json = _build_financials_live_turn(
        conn=None,
        intake_context={},
        conversation_messages=[],
        shared_context={"operating_model": {"business_naics_6": "812199"}},
        financials_json={"_financials_revenue_intro_done": True},
        financials_year1_json={"company_revenue_total_year1": 1000000.0},
        guardrail_triggered=False,
      )
    self.assertIn("cogs baseline", str(turn["assistant_message"] or "").lower())
    self.assertIsInstance(financials_json, dict)

  def test_build_financials_live_turn_completes_when_no_stage_left(self) -> None:
    turn, financials_json = _build_financials_live_turn(
      conn=None,
      intake_context={},
      conversation_messages=[],
      shared_context={},
      financials_json={
        "_financials_revenue_intro_done": True,
        "current_cogs": 1000.0,
        "cogs_total_year1": 1000.0,
        "current_payroll": 120000.0,
        "payroll_total_year1": 120000.0,
        "marketing_total_year1": 24000.0,
        "monthly_rent_expense": 1000.0,
        "future_rent_expected": False,
        "owner_compensation": 60000.0,
        "other_operating_expense": 500.0,
        "current_num_employees": 1,
        "current_capex": 0.0,
        "initial_assets": 10000.0,
        "initial_lease": "0,none",
        "initial_equity": 5000.0,
        "total_debt_outstanding": 0.0,
        "other_monthly_debt_payments": 0.0,
        "annual_interest_payment": 0.0,
        "annual_principal_payment": 0.0,
        "cash_on_hand": 5000.0,
        "ar_balance": 0.0,
        "ap_balance": 0.0,
        "inventory_balance": 0.0,
      },
      financials_year1_json={},
      guardrail_triggered=False,
    )
    self.assertTrue(turn.get("transition_to_done"))
    self.assertIn("intake", str(turn.get("assistant_message") or "").lower())
    self.assertIsInstance(financials_json, dict)

  def test_run_financials_turn_and_sync_falls_back_for_marketing_monthly_reply(self) -> None:
    baseline_financials = {
      "_financials_revenue_intro_done": True,
      "current_cogs": 220000.0,
      "cogs_total_year1": 220000.0,
      "cogs_percent_of_revenue": 0.22,
      "current_payroll": 120000.0,
      "payroll_total_year1": 120000.0,
    }

    def _route_intent(**kwargs):
      del kwargs
      return {
        "action": "answer_readonly",
        "assistant_message": "Got it - I'll treat your spend as part of a 4000 per month marketing bucket.",
      }

    with patch(
      "api_handlers.intake_consult._advance_persisted_financials_stage",
      return_value=(
        {"assistant_message": "next", "finalize_ready": False},
        {"marketing_total_year1": 48000.0, "marketing_percent_of_revenue": 0.048},
        {},
      ),
    ) as advance_mock:
      turn, updated_financials = _run_financials_turn_and_sync(
        route_intent=_route_intent,
        conn=None,
        intake_context={"draft_id": "draft-1"},
        conversation_messages=[],
        business_facts={},
        shared_context={"marketing": {}},
        last_assistant="Does that broadly match what it will take to attract and convert customers in Year 1, or should we adjust it because your marketing spend will be materially different?",
        user_message="Use 4000 per month for marketing and related costs.",
        financials_json=baseline_financials,
        financials_year1_json={"company_revenue_total_year1": 1000000.0},
      )

    self.assertEqual(turn["assistant_message"], "next")
    self.assertEqual(float(updated_financials["marketing_total_year1"]), 48000.0)
    persisted_financials = advance_mock.call_args.kwargs["financials_json"]
    self.assertEqual(float(persisted_financials["marketing_total_year1"]), 48000.0)
    self.assertAlmostEqual(float(persisted_financials["marketing_percent_of_revenue"]), 0.048, places=6)

  def test_run_financials_turn_and_sync_revenue_intro_confirm_proceed_persists_baseline(self) -> None:
    with patch(
      "api_handlers.intake_consult._advance_persisted_financials_stage",
      return_value=(
        {"assistant_message": "A reasonable Year-1 direct-cost baseline is about $220,000.", "finalize_ready": False},
        {"_financials_revenue_intro_done": True, "current_revenue": 1000000.0},
        {},
      ),
    ):
      turn, next_financials = _run_financials_turn_and_sync(
        route_intent=lambda **_: {"action": "confirm_proceed", "assistant_message": "", "patch": None},
        conn=None,
        intake_context={
          "draft_id": "draft-1",
          "financials_json": {},
          "shared_context": {"operating_model": {"business_naics_6": "812199"}},
        },
        conversation_messages=[{"role": "assistant", "content": "Year 1 revenue summary"}],
        business_facts={"name": "Test Business"},
        shared_context={"operating_model": {"business_naics_6": "812199"}},
        last_assistant="Year 1 revenue summary",
        user_message="Yes, that's right.",
        financials_json={},
        financials_year1_json={"company_revenue_total_year1": 1000000.0},
      )

    self.assertTrue(bool(next_financials.get("_financials_revenue_intro_done")))
    self.assertFalse(bool(turn.get("transition_to_done")))
    self.assertEqual(float(next_financials.get("current_revenue") or 0.0), 1000000.0)
    self.assertIn("direct-cost baseline", str(turn.get("assistant_message") or "").lower())

  def test_run_financials_turn_and_sync_revenue_intro_uses_router_and_not_auto_advance(self) -> None:
    called: dict = {}

    def _router(**kwargs):
      called["confirm_question"] = kwargs.get("confirm_question_override")
      called["shared_context"] = kwargs.get("shared_context")
      return {"action": "confirm_proceed", "assistant_message": "", "patch": None}

    with patch(
      "api_handlers.intake_consult._advance_persisted_financials_stage",
      return_value=(
        {"assistant_message": "A reasonable Year-1 direct-cost baseline is about $220,000.", "finalize_ready": False},
        {"_financials_revenue_intro_done": True, "current_revenue": 1000000.0},
        {},
      ),
    ):
      turn, next_financials = _run_financials_turn_and_sync(
        route_intent=_router,
        conn=None,
        intake_context={
          "draft_id": "draft-1",
          "financials_json": {},
          "shared_context": {"operating_model": {"business_naics_6": "812199"}},
        },
        conversation_messages=[{"role": "assistant", "content": "Year 1 revenue summary"}],
        business_facts={"name": "Test Business"},
        shared_context={"operating_model": {"business_naics_6": "812199"}},
        last_assistant="Year 1 revenue summary",
        user_message="Yes, that's right.",
        financials_json={},
        financials_year1_json={"company_revenue_total_year1": 1000000.0},
      )

    self.assertTrue(bool(next_financials.get("_financials_revenue_intro_done")))
    self.assertIn("revenue baseline", str(called["confirm_question"] or "").lower())
    controller_ctx = dict(called["shared_context"].get("financials_controller") or {})
    self.assertEqual(
      dict(controller_ctx.get("current_stage") or {}).get("patch_targets"),
      ["current_revenue"],
    )
    self.assertIn("direct-cost baseline", str(turn.get("assistant_message") or "").lower())

  def test_run_financials_turn_and_sync_revenue_intro_accepts_concrete_override(self) -> None:
    def _router(**_kwargs):
      return {
        "action": "edit_patch",
        "assistant_message": "Got it. I'll use $900,000 as the Year-1 revenue baseline.",
        "patch": {"current_revenue": 900000.0},
      }

    with patch(
      "api_handlers.intake_consult._advance_persisted_financials_stage",
      return_value=(
        {"assistant_message": "A reasonable Year-1 direct-cost baseline is about $198,000.", "finalize_ready": False},
        {"_financials_revenue_intro_done": True, "current_revenue": 900000.0},
        {},
      ),
    ):
      turn, next_financials = _run_financials_turn_and_sync(
        route_intent=_router,
        conn=None,
        intake_context={
          "draft_id": "draft-1",
          "financials_json": {},
          "shared_context": {"operating_model": {"business_naics_6": "812199"}},
        },
        conversation_messages=[{"role": "assistant", "content": "Year 1 revenue summary"}],
        business_facts={"name": "Test Business"},
        shared_context={"operating_model": {"business_naics_6": "812199"}},
        last_assistant="Year 1 revenue summary",
        user_message="Use 900000 instead.",
        financials_json={},
        financials_year1_json={"company_revenue_total_year1": 1000000.0},
      )

    self.assertTrue(bool(next_financials.get("_financials_revenue_intro_done")))
    self.assertEqual(float(next_financials.get("current_revenue") or 0.0), 900000.0)
    self.assertIn("direct-cost baseline", str(turn.get("assistant_message") or "").lower())

  def test_run_financials_turn_and_sync_payroll_stage_uses_router_and_persists(self) -> None:
    def _router(**_kwargs):
      return {
        "action": "edit_patch",
        "assistant_message": "Got it. I’ll use Year-1 payroll of $120,000.",
        "patch": {"current_payroll": 120000.0},
      }

    with patch(
      "api_handlers.intake_consult._advance_persisted_financials_stage",
      return_value=(
        {"assistant_message": "What do you pay each month for the space you use to run the business?", "finalize_ready": False},
        {
          "_financials_revenue_intro_done": True,
          "current_cogs": 220000.0,
          "marketing_total_year1": 50000.0,
          "current_payroll": 120000.0,
          "payroll_total_year1": 120000.0,
        },
        {},
      ),
    ):
      turn, next_financials = _run_financials_turn_and_sync(
        route_intent=_router,
        conn=None,
        intake_context={
          "draft_id": "draft-1",
          "financials_json": {
            "_financials_revenue_intro_done": True,
            "current_cogs": 220000.0,
            "marketing_total_year1": 50000.0,
          },
          "shared_context": {
            "people_capability": {
              "people": [{"full_name": "Founder", "role_title": "Provider", "annual_wage": 90000.0}],
              "inferred_roles": [],
            },
            "operating_model": {"business_stage": "operating"},
          },
        },
        conversation_messages=[{"role": "assistant", "content": "What should we use for Year-1 payroll?"}],
        business_facts={"name": "Test Business"},
        shared_context={
          "people_capability": {
            "people": [{"full_name": "Founder", "role_title": "Provider", "annual_wage": 90000.0}],
            "inferred_roles": [],
          },
          "operating_model": {"business_stage": "operating"},
        },
        last_assistant="What should we use for Year-1 payroll?",
        user_message="Only the owner is on payroll in Year 1, at $120,000.",
        financials_json={
          "_financials_revenue_intro_done": True,
          "current_cogs": 220000.0,
          "marketing_total_year1": 50000.0,
        },
        financials_year1_json={"company_revenue_total_year1": 1000000.0},
      )

    self.assertEqual(float(next_financials.get("current_payroll") or 0.0), 120000.0)
    self.assertEqual(float(next_financials.get("payroll_total_year1") or 0.0), 120000.0)
    self.assertIn("space", str(turn.get("assistant_message") or "").lower())

  def test_run_financials_turn_and_sync_cogs_percent_phrase_persists_without_parser_logic(self) -> None:
    def _router(**_kwargs):
      return {
        "action": "edit_patch",
        "assistant_message": "Got it. I'll use 22% for Year-1 direct costs.",
        "patch": {"cogs_percent_of_revenue": 0.22},
      }

    with patch(
      "api_handlers.intake_consult._advance_persisted_financials_stage",
      return_value=(
        {"assistant_message": "What should we use for Year-1 payroll?", "finalize_ready": False},
        {
          "_financials_revenue_intro_done": True,
          "current_cogs": 220000.0,
          "cogs_total_year1": 220000.0,
          "cogs_percent_of_revenue": 0.22,
        },
        {},
      ),
    ):
      turn, next_financials = _run_financials_turn_and_sync(
        route_intent=_router,
        conn=None,
        intake_context={
          "draft_id": "draft-1",
          "financials_json": {"_financials_revenue_intro_done": True},
          "shared_context": {"operating_model": {"business_naics_6": "812199"}},
        },
        conversation_messages=[{"role": "assistant", "content": "What should we use for Year-1 direct costs?"}],
        business_facts={"name": "Test Business"},
        shared_context={"operating_model": {"business_naics_6": "812199"}},
        last_assistant="What should we use for Year-1 direct costs?",
        user_message="Use 22% COGS.",
        financials_json={"_financials_revenue_intro_done": True},
        financials_year1_json={"company_revenue_total_year1": 1000000.0},
      )

    self.assertEqual(float(next_financials.get("current_cogs") or 0.0), 220000.0)
    self.assertEqual(float(next_financials.get("cogs_total_year1") or 0.0), 220000.0)
    self.assertAlmostEqual(float(next_financials.get("cogs_percent_of_revenue") or 0.0), 0.22, places=6)
    self.assertIn("payroll", str(turn.get("assistant_message") or "").lower())


class PlanningRunContractTests(unittest.TestCase):
  def test_planning_run_payload_carries_resolution_summary(self) -> None:
    resolution_summary = {"status": "all_cleared", "remaining_blocking_violations": []}
    payload = _build_planning_run_payload(
      stage="consistency_reconciliation",
      status="cleared",
      resolution_summary=resolution_summary,
      planning_mode="turnaround",
      planning_mode_reason="app_classified_turnaround_case",
      prompt_file="turnaround.md",
      gpt_narrative="Resolved and ready.",
    )
    self.assertEqual(payload["resolution_summary"], resolution_summary)
    self.assertTrue(_is_valid_planning_run_payload(copy.deepcopy(payload)))


class ConsistencyControllerTests(unittest.TestCase):
  def _medspa_consistency_state(self) -> tuple[dict, dict, dict, dict, dict, dict]:
    ops_json = {
      "unit_name": "treatment session",
      "unit_cadence": "weekly",
      "unit_price": 875.0,
      "units_per_week_capacity": 55.0,
      "capacity_driver": "labor",
      "shipping_method": "in-person service at studio location",
      "sales_modality": "hybrid",
      "competitive_advantage": "Focused premium clinic",
      "primary_growth_lever": "add providers",
      "milestones": [
        {"description": "Reach about 70 treatment sessions per week.", "timing": "within 12 months"}
      ],
    }
    market_json = {
      "consumer_type": "consumer",
      "income_intent": [{"income_min": 60000}],
      "target_market_summary": "Adults 30 to 65 with household income of $60k and above.",
    }
    people_json = {
      "people": [{"full_name": "Dr. Elaine Thompson", "role_title": "Founder & Lead Injector"}],
      "inferred_roles": [],
    }
    financials_json = {
      "current_payroll": 120000.0,
      "monthly_rent_expense": 9500.0,
      "other_operating_expense": 4000.0,
      "other_monthly_debt_payments": 1500.0,
      "cash_on_hand": 15000.0,
      "total_debt_outstanding": 120000.0,
      "initial_assets": 180000.0,
      "initial_equity": 50000.0,
      "marketing_total_year1": 528000.0,
      "marketing_percent_of_revenue": 528000.0 / 2202200.0,
    }
    financials_year1_json = {
      "company_revenue_total_year1": 2202200.0,
      "lobs": [
        {
          "lob_name": "Primary line of business",
          "revenue_total_year1": 2202200.0,
          "products": [
            {
              "product_name": "treatment session",
              "unit_cadence": "weekly",
              "unit_price": 875.0,
              "units_per_period_capacity": 55.0,
              "units_per_week_capacity": 55.0,
              "utilization_rate": 0.88,
              "avg_units_per_period_year1": 48.4,
              "annual_units_year1": 2516.8,
              "revenue_total_year1": 2202200.0,
              "operating_periods_per_year": 52.0,
            }
          ],
        }
      ],
    }
    fulfillment_json = {"personnel": "Founder performs treatments", "time": "In-person appointments"}
    return ops_json, market_json, people_json, financials_json, financials_year1_json, fulfillment_json

  def test_consistency_controller_prioritizes_goal_capacity_conflict(self) -> None:
    ops_json = {
      "unit_name": "treatment session",
      "unit_cadence": "weekly",
      "unit_price": 875.0,
      "units_per_week_capacity": 55.0,
      "capacity_driver": "labor",
      "shipping_method": "in-person service at studio location",
      "sales_modality": "hybrid",
      "competitive_advantage": "Focused premium clinic",
      "primary_growth_lever": "add providers",
      "milestones": [
        {"description": "Reach about 70 treatment sessions per week.", "timing": "within 12 months"}
      ],
    }
    market_json = {
      "consumer_type": "consumer",
      "income_intent": [{"income_min": 60000}],
      "target_market_summary": "Adults 30 to 65 with household income of $60k and above.",
    }
    people_json = {
      "people": [{"full_name": "Dr. Elaine Thompson", "role_title": "Founder & Lead Injector"}],
      "inferred_roles": [],
    }
    financials_json = {
      "current_payroll": 38580.0,
      "monthly_rent_expense": 6000.0,
      "other_operating_expense": 2000.0,
      "other_monthly_debt_payments": 0.0,
      "cash_on_hand": 50000.0,
      "total_debt_outstanding": 0.0,
      "initial_assets": 100000.0,
      "initial_equity": 50000.0,
    }
    financials_year1_json = {
      "company_revenue_total_year1": 2202200.0,
      "lobs": [
        {
          "lob_name": "Primary line of business",
          "revenue_total_year1": 2202200.0,
          "products": [
            {
              "product_name": "treatment session",
              "unit_cadence": "weekly",
              "unit_price": 875.0,
              "units_per_period_capacity": 55.0,
              "units_per_week_capacity": 55.0,
              "utilization_rate": 0.88,
              "avg_units_per_period_year1": 48.4,
              "annual_units_year1": 2516.8,
              "revenue_total_year1": 2202200.0,
              "operating_periods_per_year": 52.0,
            }
          ],
        }
      ],
    }

    controller = _build_consistency_controller_state(
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
      fulfillment_json={"personnel": "Founder performs treatments", "time": "In-person appointments"},
    )

    self.assertEqual(controller["status"], "issue_pending")
    current_issue = controller["current_issue"]
    self.assertIsInstance(current_issue, dict)
    self.assertEqual(current_issue["issue_code"], "goal_capacity_conflict")
    self.assertIn("ops.milestones", current_issue["default_patch"])

  def test_consistency_controller_regression_surfaces_full_medspa_issue_stack(self) -> None:
    ops_json, market_json, people_json, financials_json, financials_year1_json, fulfillment_json = self._medspa_consistency_state()

    issues = _build_consistency_candidate_issues(
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
      fulfillment_json=fulfillment_json,
    )

    issue_codes = [str(issue.get("issue_code") or "") for issue in issues if isinstance(issue, dict)]
    self.assertEqual(
      issue_codes[:4],
      [
        "goal_capacity_conflict",
        "cash_obligation_gap",
        "people_workload_capacity_tension",
        "price_customer_fit_tension",
      ],
    )

  def test_consistency_controller_regression_rescans_until_all_material_issues_clear(self) -> None:
    ops_json, market_json, people_json, financials_json, financials_year1_json, fulfillment_json = self._medspa_consistency_state()

    controller = _build_consistency_controller_state(
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
      fulfillment_json=fulfillment_json,
    )
    self.assertEqual(str(dict(controller.get("current_issue") or {}).get("issue_code") or ""), "goal_capacity_conflict")

    business_facts: dict = {}

    business_facts, ops_json, market_json, people_json, financials_json, fulfillment_json = _apply_scoped_patch(
      dict(dict(controller.get("current_issue") or {}).get("default_patch") or {}),
      business_facts=business_facts,
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      fulfillment_json=fulfillment_json,
    )

    controller = _build_consistency_controller_state(
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
      fulfillment_json=fulfillment_json,
    )
    self.assertEqual(str(dict(controller.get("current_issue") or {}).get("issue_code") or ""), "cash_obligation_gap")

    business_facts, ops_json, market_json, people_json, financials_json, fulfillment_json = _apply_scoped_patch(
      {"financials.cash_on_hand": 100000.0},
      business_facts=business_facts,
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      fulfillment_json=fulfillment_json,
    )

    controller = _build_consistency_controller_state(
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
      fulfillment_json=fulfillment_json,
    )
    self.assertEqual(str(dict(controller.get("current_issue") or {}).get("issue_code") or ""), "people_workload_capacity_tension")

    upgraded_people = list(people_json.get("people") or [])
    upgraded_people.append({"full_name": "Jordan Patel", "role_title": "Provider"})
    business_facts, ops_json, market_json, people_json, financials_json, fulfillment_json = _apply_scoped_patch(
      {"people.people": upgraded_people},
      business_facts=business_facts,
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      fulfillment_json=fulfillment_json,
    )

    controller = _build_consistency_controller_state(
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
      fulfillment_json=fulfillment_json,
    )
    self.assertEqual(str(dict(controller.get("current_issue") or {}).get("issue_code") or ""), "price_customer_fit_tension")

    business_facts, ops_json, market_json, people_json, financials_json, fulfillment_json = _apply_scoped_patch(
      {"market.income_intent": [{"income_min": 120000}]},
      business_facts=business_facts,
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      fulfillment_json=fulfillment_json,
    )

    controller = _build_consistency_controller_state(
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
      fulfillment_json=fulfillment_json,
    )
    self.assertEqual(str(controller.get("status") or ""), "clear")

  def test_consistency_candidate_issues_include_price_and_workload_tensions(self) -> None:
    issues = _build_consistency_candidate_issues(
      ops_json={
        "capacity_driver": "labor",
        "shipping_method": "in-person service at studio location",
        "sales_modality": "hybrid",
        "milestones": [],
      },
      market_json={
        "consumer_type": "consumer",
        "income_intent": [{"income_min": 60000}],
        "target_market_summary": "Adults with household income of $60k and above.",
      },
      people_json={
        "people": [{"full_name": "Solo Founder", "role_title": "Provider"}],
        "inferred_roles": [],
      },
      financials_json={
        "current_payroll": 38580.0,
        "monthly_rent_expense": 5000.0,
        "other_operating_expense": 2000.0,
        "other_monthly_debt_payments": 0.0,
        "cash_on_hand": 50000.0,
      },
      financials_year1_json={
        "company_revenue_total_year1": 2202200.0,
        "lobs": [
          {
            "lob_name": "Primary",
            "products": [
              {
                "product_name": "treatment session",
                "unit_cadence": "weekly",
                "unit_price": 875.0,
                "units_per_period_capacity": 55.0,
                "units_per_week_capacity": 55.0,
                "utilization_rate": 0.88,
                "avg_units_per_period_year1": 48.4,
                "annual_units_year1": 2516.8,
                "revenue_total_year1": 2202200.0,
                "operating_periods_per_year": 52.0,
              }
            ],
          }
        ],
      },
      fulfillment_json={"personnel": "Founder performs treatments", "time": "In-person appointments"},
    )

    issue_codes = [issue["issue_code"] for issue in issues]
    self.assertIn("people_workload_capacity_tension", issue_codes)
    self.assertIn("price_customer_fit_tension", issue_codes)

  def test_consistency_candidate_issue_exposes_patch_targets(self) -> None:
    issues = _build_consistency_candidate_issues(
      ops_json={
        "capacity_driver": "labor",
        "shipping_method": "in-person service at studio location",
        "sales_modality": "hybrid",
        "milestones": [],
      },
      market_json={
        "consumer_type": "consumer",
        "income_intent": [{"income_min": 60000}],
      },
      people_json={
        "people": [{"full_name": "Solo Founder", "role_title": "Provider"}],
        "inferred_roles": [],
      },
      financials_json={
        "current_payroll": 38580.0,
        "monthly_rent_expense": 5000.0,
        "other_operating_expense": 2000.0,
        "other_monthly_debt_payments": 0.0,
        "cash_on_hand": 50000.0,
      },
      financials_year1_json={
        "company_revenue_total_year1": 2202200.0,
        "lobs": [
          {
            "lob_name": "Primary",
            "products": [
              {
                "product_name": "treatment session",
                "unit_cadence": "weekly",
                "unit_price": 875.0,
                "units_per_period_capacity": 55.0,
                "units_per_week_capacity": 55.0,
                "utilization_rate": 0.88,
                "avg_units_per_period_year1": 48.4,
                "annual_units_year1": 2516.8,
                "revenue_total_year1": 2202200.0,
                "operating_periods_per_year": 52.0,
              }
            ],
          }
        ],
      },
      fulfillment_json={"personnel": "Founder performs treatments", "time": "In-person appointments"},
    )

    workload_issue = next(
      issue for issue in issues
      if isinstance(issue, dict) and str(issue.get("issue_code") or "") == "people_workload_capacity_tension"
    )
    patch_targets = workload_issue.get("patch_targets")
    self.assertIsInstance(patch_targets, list)
    self.assertIn("people.inferred_roles", patch_targets)
    self.assertIn("ops.milestones", patch_targets)

  def test_consistency_controller_current_issue_has_completion_rule(self) -> None:
    controller = _build_consistency_controller_state(
      ops_json={
        "unit_name": "treatment session",
        "unit_cadence": "weekly",
        "unit_price": 875.0,
        "units_per_week_capacity": 55.0,
        "capacity_driver": "labor",
        "shipping_method": "in-person service at studio location",
        "sales_modality": "hybrid",
        "milestones": [{"description": "Reach 70 treatment sessions per week.", "timing": "within 12 months"}],
      },
      market_json={"consumer_type": "consumer", "income_intent": [{"income_min": 60000}]},
      people_json={"people": [{"full_name": "Solo Founder", "role_title": "Provider"}], "inferred_roles": []},
      financials_json={"cash_on_hand": 10000.0, "monthly_rent_expense": 5000.0, "other_operating_expense": 2000.0},
      financials_year1_json={
        "company_revenue_total_year1": 2202200.0,
        "lobs": [{
          "lob_name": "Primary",
          "products": [{
            "product_name": "treatment session",
            "unit_cadence": "weekly",
            "unit_price": 875.0,
            "units_per_period_capacity": 55.0,
            "units_per_week_capacity": 55.0,
            "utilization_rate": 0.88,
            "avg_units_per_period_year1": 48.4,
            "annual_units_year1": 2516.8,
            "revenue_total_year1": 2202200.0,
            "operating_periods_per_year": 52.0,
          }],
        }],
      },
      fulfillment_json={"personnel": "Founder performs treatments", "time": "In-person appointments"},
    )
    current_issue = dict(controller.get("current_issue") or {})
    self.assertEqual(
      dict(current_issue.get("completion_rule") or {}).get("type"),
      "issue_absent_after_rescan",
    )
    edit_surface = controller.get("edit_surface")
    self.assertIsInstance(edit_surface, list)
    self.assertIn("business.name", edit_surface)
    self.assertIn("ops.milestones", edit_surface)
    self.assertIn("ops.lob_models", edit_surface)
    self.assertIn("market.income_intent", edit_surface)
    self.assertIn("people.people", edit_surface)
    self.assertIn("financials.cash_on_hand", edit_surface)
    self.assertIn("fulfillment.personnel", edit_surface)

  def test_legacy_consistency_closeout_compatibility_now_completes_cleanly(self) -> None:
    ops_json = {
      "unit_name": "treatment session",
      "unit_cadence": "weekly",
      "unit_price": 875.0,
      "units_per_week_capacity": 55.0,
      "capacity_driver": "labor",
      "shipping_method": "in-person service at studio location",
      "sales_modality": "hybrid",
      "milestones": [{"description": "Reach about 70 treatment sessions per week.", "timing": "within 12 months"}],
    }
    market_json = {
      "consumer_type": "consumer",
      "income_intent": [{"income_min": 60000}],
      "target_market_summary": "Adults 30 to 65 with household income of $60k and above.",
    }
    people_json = {
      "people": [{"full_name": "Dr. Elaine Thompson", "role_title": "Founder & Lead Injector"}],
      "inferred_roles": [],
    }
    financials_json = {
      "current_payroll": 38580.0,
      "monthly_rent_expense": 6000.0,
      "other_operating_expense": 2000.0,
      "other_monthly_debt_payments": 0.0,
      "cash_on_hand": 50000.0,
      "total_debt_outstanding": 0.0,
      "initial_assets": 100000.0,
      "initial_equity": 50000.0,
    }
    financials_year1_json = {
      "company_revenue_total_year1": 2202200.0,
      "lobs": [{
        "lob_name": "Primary line of business",
        "revenue_total_year1": 2202200.0,
        "products": [{
          "product_name": "treatment session",
          "unit_cadence": "weekly",
          "unit_price": 875.0,
          "units_per_period_capacity": 55.0,
          "units_per_week_capacity": 55.0,
          "utilization_rate": 0.88,
          "avg_units_per_period_year1": 48.4,
          "annual_units_year1": 2516.8,
          "revenue_total_year1": 2202200.0,
          "operating_periods_per_year": 52.0,
        }],
      }],
    }
    with patch(
      "quarter_grid.determine_planning_mode",
      return_value={"planning_mode": "rebalance", "planning_mode_reason": "test", "prompt_file": "rebalance.md"},
    ):
      closeout = _run_consistency_closeout(
        conversation_messages=[{"role": "user", "content": "continue"}],
        conn=None,
        client_id="client-1",
        draft_id="draft-1",
        business_facts={"name": "Test Business", "start_date": "2026-01-01", "address": "Dallas, TX"},
        business_stage_hint="operating",
        current_date_iso="2026-04-02",
        shared_context={},
        ops_json=ops_json,
        market_json=market_json,
        people_json=people_json,
        financials_json=financials_json,
        financials_year1_json=financials_year1_json,
        fulfillment_json={"personnel": "Founder performs treatments", "time": "In-person appointments"},
        marketing_model_json={},
      )

    self.assertTrue(_consistency_closeout_ready_for_completion(closeout))
    self.assertEqual(str(closeout.get("governance_state", {}).get("status") or ""), "cleared")
    planning_run = dict(closeout.get("planning_run_json") or {})
    self.assertEqual(str(planning_run.get("status") or ""), "cleared")
    resolution_summary = dict(planning_run.get("resolution_summary") or {})
    self.assertEqual(str(resolution_summary.get("status") or ""), "all_cleared")

  def test_consistency_runtime_payload_carries_controller_state(self) -> None:
    bundle = _build_consistency_runtime_payload_for_persistence(
      intake_context={
        "consistency_controller": {"status": "issue_pending", "current_issue": {"issue_code": "cash_obligation_gap"}},
        "coherence_signals": {"cash_obligation_signals": {"runway_months_pre_revenue": 1.2}},
        "business_model_snapshot": {"business_identity": {"business_name": "Test Business"}},
        "reality_overview": {"cash_on_hand": 15000.0},
      },
      ops_json={},
      market_json={},
      people_json={},
      financials_json={"cash_on_hand": 15000.0},
      financials_year1_json={},
      marketing_model_json={},
    )
    self.assertEqual(
      dict(bundle.get("consistency_controller") or {}).get("current_issue", {}).get("issue_code"),
      "cash_obligation_gap",
    )

  def test_consistency_followup_state_stays_blocked_until_clear(self) -> None:
    blocked = {
      "planning_run_json": {
        "status": "blocking_unresolved",
        "resolution_summary": {"status": "hard_issues_remaining"},
      }
    }
    cleared = {
      "planning_run_json": {
        "status": "cleared",
        "resolution_summary": {"status": "all_cleared"},
      }
    }

    blocked_state = _consistency_followup_state(blocked)
    self.assertEqual(blocked_state["active_focus_out"], "consistency")
    self.assertFalse(blocked_state["consistency_passed_out"])
    self.assertFalse(blocked_state["completed_out"])
    self.assertIsNone(blocked_state["status_out"])

    cleared_state = _consistency_followup_state(cleared)
    self.assertEqual(cleared_state["active_focus_out"], "done")
    self.assertTrue(cleared_state["consistency_passed_out"])
    self.assertTrue(cleared_state["completed_out"])
    self.assertEqual(cleared_state["status_out"], "completed")

  def test_consistency_closeout_requires_resolution_summary(self) -> None:
    closeout = {
      "governance_state": {"status": "cleared"},
      "planning_run_json": {
        "status": "cleared",
        "resolution_summary": {"status": "all_cleared"},
      },
    }
    self.assertTrue(_consistency_closeout_ready_for_completion(closeout))
    closeout["planning_run_json"] = {"status": "cleared"}
    self.assertFalse(_consistency_closeout_ready_for_completion(closeout))

  def test_backfill_planning_run_from_closeout_builds_missing_payload(self) -> None:
    closeout = {
      "assistant_text": "All clear.",
      "governance_state": {"status": "cleared", "blocking_violations": []},
      "selected_scenario": {},
      "planning_mode": "normalize",
      "planning_mode_reason": "app_classified_normal_case",
      "prompt_file": "normalize.md",
      "planning_run_json": {},
    }
    payload = _backfill_planning_run_from_closeout(closeout)
    self.assertIsInstance(payload, dict)
    self.assertEqual(payload["stage"], "consistency_reconciliation")
    self.assertEqual(payload["status"], "cleared")
    self.assertTrue(isinstance(payload.get("resolution_summary"), dict) and payload["resolution_summary"])

  def test_next_focus_from_consistency_closeout_respects_blocked_vs_done(self) -> None:
    blocked = {
      "governance_state": {"status": "blocking_unresolved"},
      "planning_run_json": {
        "status": "blocking_unresolved",
        "resolution_summary": {"status": "blocking_unresolved"},
      },
    }
    cleared = {
      "governance_state": {"status": "cleared"},
      "planning_run_json": {
        "status": "cleared",
        "resolution_summary": {"status": "all_cleared"},
      },
    }
    self.assertEqual(_next_focus_from_consistency_closeout(blocked), "consistency")
    self.assertEqual(_next_focus_from_consistency_closeout(cleared), "done")

  def test_should_run_consistency_on_confirm_only_at_consistency_boundary(self) -> None:
    self.assertFalse(_should_run_consistency_on_confirm(focus="ops", next_focus="market"))
    self.assertFalse(_should_run_consistency_on_confirm(focus="market", next_focus="people"))
    self.assertFalse(_should_run_consistency_on_confirm(focus="people", next_focus="financials"))
    self.assertFalse(_should_run_consistency_on_confirm(focus="financials", next_focus="done"))
    self.assertFalse(_should_run_consistency_on_confirm(focus="consistency", next_focus="done"))

  def test_intake_complete_planning_run_payload_is_db_safe(self) -> None:
    payload = _build_intake_complete_planning_run_payload()
    self.assertEqual(payload.get("stage"), "intake_complete")
    self.assertEqual(payload.get("status"), "pending")
    resolution_summary = payload.get("resolution_summary") or {}
    self.assertEqual(resolution_summary.get("status"), "intake_complete")
    self.assertTrue(_is_valid_planning_run_payload(payload))

  def test_realism_memo_contract_validates_compact_issue_payload(self) -> None:
    payload = {
      "status": "ready",
      "issues": [
        {
          "issue": "The staffing model looks tight against the operating load.",
          "detail": "The business appears to depend on a delivery pace that leaves limited room for normal friction.",
        }
      ],
    }
    self.assertTrue(is_valid_realism_memo_payload(payload))

  def test_realism_memo_normalization_clips_and_filters_invalid_entries(self) -> None:
    payload = normalize_realism_memo_payload(
      {
        "status": "",
        "issues": [
          {"issue": "A", "detail": "B"},
          {"issue": "", "detail": "skip"},
          {"issue": "C", "detail": "D"},
          {"issue": "E", "detail": "F"},
          {"issue": "G", "detail": "H"},
          {"issue": "I", "detail": "J"},
        ],
      }
    )
    self.assertEqual(payload.get("status"), "ready")
    self.assertEqual(len(payload.get("issues") or []), 4)
    self.assertEqual((payload.get("issues") or [])[0], {"issue": "A", "detail": "B"})

  def test_realism_memo_empty_payload_is_valid(self) -> None:
    payload = empty_realism_memo_payload()
    self.assertTrue(is_valid_realism_memo_payload(payload))
    self.assertEqual(payload.get("status"), "not_generated")

  def test_realism_memo_prompts_define_json_contract_and_advisory_boundary(self) -> None:
    reviewer_prompt = load_realism_memo_reviewer_prompt().lower()
    advisory_prompt = load_realism_memo_grid_advisory_prompt().lower()
    self.assertIn("return json only", reviewer_prompt)
    self.assertIn("\"issues\"", reviewer_prompt)
    self.assertIn("additional context only", advisory_prompt)
    self.assertIn("does not override your normal planning logic", advisory_prompt)

  def test_quarter_grid_prompt_includes_realism_memo_as_advisory_context_only(self) -> None:
    prompt = build_quarter_grid_prompt(
      source_row={
        "business_name": "Precision Aesthetics Lab",
        "realism_memo_json": {
          "status": "ready",
          "issues": [
            {
              "issue": "The staffing model looks tight against the operating load.",
              "detail": "The business appears to depend on a demanding level of execution with limited room for friction.",
            }
          ],
        },
      },
      grid_rows=[{"row_id": "revenue::price", "row_type": "lever", "quarter_bands": []}],
      governor_payload={"company_stage": "operating"},
      batch_index=1,
      batch_count=1,
      planning_mode="normalize",
    )
    prompt_lower = prompt.lower()
    self.assertIn("advisory realism memo", prompt_lower)
    self.assertIn("additional context only", prompt_lower)
    self.assertIn("does not override your normal planning logic", prompt_lower)
    self.assertIn("staffing model looks tight", prompt_lower)

  def test_quarter_grid_system_prompt_repeats_advisory_boundary_when_memo_present(self) -> None:
    prompt = quarter_grid_system_prompt(
      use_real_strategy_prompt=True,
      planning_mode="normalize",
      realism_memo_present=True,
    ).lower()
    self.assertIn("additional context only", prompt)
    self.assertIn("does not override your normal planning logic", prompt)

  def test_realism_memo_input_contains_ops_and_financials_context(self) -> None:
    prompt = build_realism_memo_input(
      ops_json={"business_model": "service", "unit_price": 875},
      financials_json={"cash_on_hand": 15000, "monthly_rent_expense": 9500},
    )
    self.assertIn("ops_json", prompt)
    self.assertIn("financials_json", prompt)
    self.assertIn("unit_price", prompt)
    self.assertIn("cash_on_hand", prompt)

  def test_realism_memo_schema_is_strict_and_limited(self) -> None:
    schema = realism_memo_schema()
    self.assertEqual(schema.get("name"), "realism_memo")
    self.assertTrue(bool(schema.get("strict")))
    issues = dict(dict(schema.get("schema") or {}).get("properties") or {}).get("issues") or {}
    self.assertEqual(issues.get("maxItems"), 4)

  def test_generate_realism_memo_payload_parses_strict_json_response(self) -> None:
    class _FakeResponse:
      status_code = 200
      text = ""

      @staticmethod
      def json() -> dict:
        return {
          "output": [
            {
              "content": [
                {
                  "parsed": {
                    "status": "ready",
                    "issues": [
                      {
                        "issue": "The operating model appears stretched.",
                        "detail": "The plan depends on a demanding level of execution with limited room for friction.",
                      }
                    ],
                  }
                }
              ]
            }
          ]
        }

    with patch("client_intake_and_finmo.realism_memo._require_openai_key", return_value="test-key"), patch(
      "client_intake_and_finmo.realism_memo._post_openai",
      return_value=_FakeResponse(),
    ):
      payload = generate_realism_memo_payload(
        ops_json={"business_model": "service"},
        financials_json={"cash_on_hand": 15000},
      )
    self.assertTrue(is_valid_realism_memo_payload(payload))
    self.assertEqual(payload.get("status"), "ready")
    self.assertEqual(len(payload.get("issues") or []), 1)

  def test_generate_realism_memo_payload_safe_fails_soft(self) -> None:
    with patch(
      "client_intake_and_finmo.realism_memo.generate_realism_memo_payload",
      side_effect=RuntimeError("boom"),
    ):
      payload = generate_realism_memo_payload_safe(
        ops_json={"business_model": "service"},
        financials_json={"cash_on_hand": 15000},
      )
    self.assertEqual(payload.get("status"), "failed")
    self.assertEqual(payload.get("issues"), [])

  def test_financials_confirmable_marketing_stage_has_default_patch(self) -> None:
    shared_context = {
      "operating_model": {
        "business_stage": "operating",
        "unit_name": "treatment session",
        "unit_price": 875.0,
      },
      "target_market": {
        "consumer_type": "consumer",
        "marketing_plan_summary": "Google + Instagram",
      },
      "people_capability": {
        "people": [{"full_name": "Founder", "role_title": "Provider"}],
      },
      "marketing": {},
    }
    financials_year1_json = {
      "company_revenue_total_year1": 2202200.0,
    }
    with patch(
      "api_handlers.intake_consult._resolve_marketing_model_or_raise",
      return_value={
        "baseline_marketing": 352352.0,
        "baseline_marketing_percent": 0.16,
      },
    ):
      default_patch = _financials_stage_default_patch(
        stage_name="marketing",
        shared_context=shared_context,
        financials_year1_json=financials_year1_json,
        business_facts={"name": "Precision Aesthetics Lab", "start_date": "2024-08-05", "address": "Dallas, TX"},
        conn=None,
      )
    self.assertIsInstance(default_patch, dict)
    self.assertGreater(float(default_patch.get("marketing_total_year1") or 0.0), 0.0)
    self.assertGreater(float(default_patch.get("marketing_percent_of_revenue") or 0.0), 0.0)


if __name__ == "__main__":
  unittest.main()
