from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = ROOT / "python"
CLIENT_DIR = PYTHON_DIR / "client_intake_and_finmo"
if str(PYTHON_DIR) not in sys.path:
  sys.path.insert(0, str(PYTHON_DIR))
if str(CLIENT_DIR) not in sys.path:
  sys.path.insert(0, str(CLIENT_DIR))

from api_handlers.intake_consult import _build_planning_run_payload, _consistency_closeout_ready_for_completion
from client_intake_and_finmo.intake_consult_draft import _is_valid_planning_run_payload
from client_intake_and_finmo.quarter_grid import (
  available_planning_modes,
  determine_planning_mode,
  extract_quarter_grid_rows,
  planning_mode_prompt_file,
)


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


if __name__ == "__main__":
  unittest.main()
