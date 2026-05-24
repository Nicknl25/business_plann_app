"""Phase 9 P3.10 STD canonical-source layer 3 — obsolete STD% lever
removal.

Verifies that the load-bearing computation path no longer uses the
`balance_sheet::Short Term Debt (% of LTD)` lever:
  - cash-pass writer (apply_short_term_debt_current_portion +
    build_short_term_debt_current_portion_plan) is gone
  - cash-pass orchestrator wrapper (_apply_cash_pass_short_term_debt_current_portion)
    is gone
  - convergence pipeline stages (cash_short_term_debt_seed +
    cash_short_term_debt_current_portion) are gone
  - finmo_bridge no longer seeds the lever from intake STD ratio
  - SHORT_TERM_DEBT_RATIO_LEVER_ID + _CASH_STRATEGY_SHORT_TERM_DEBT_RATIO_LEVER_ID
    constants are gone
  - validator's STD branch still fires when there's debt outstanding
    even though the lever is now an inert zero (universal-app: same
    code path for every business)

Residual decorative references in authored-driver registries
(target_solver, orchestrator, quarter_grid, path_engine, influence_map,
fail_fast) and SQL DDL (post_intake_mapping CASE branches) and the
workbook Model Inputs / Working Capital sheet rows are intentionally
left in place; they no longer drive any computation but rendering them
as inert rows is harmless (and removing them would push surface area
beyond the user's 6-file scope budget).
"""

from __future__ import annotations

import os
import pathlib
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


SCHEDULE_PATH = (
  pathlib.Path(PYTHON_ROOT)
  / "client_intake_and_finmo"
  / "post_intake_debt_schedule"
  / "schedule.py"
)
SCHEDULE_INIT_PATH = (
  pathlib.Path(PYTHON_ROOT)
  / "client_intake_and_finmo"
  / "post_intake_debt_schedule"
  / "__init__.py"
)
CASH_RUNNER_PATH = (
  pathlib.Path(PYTHON_ROOT)
  / "client_intake_and_finmo"
  / "post_intake_cash"
  / "runner.py"
)
FINMO_BRIDGE_PATH = (
  pathlib.Path(PYTHON_ROOT) / "client_intake_and_finmo" / "finmo_bridge.py"
)
VALIDATOR_PATH = (
  pathlib.Path(PYTHON_ROOT)
  / "client_intake_and_finmo"
  / "post_intake_runtime_validation"
  / "balance_sheet_driver_validation.py"
)


class STDCanonicalSourceLayer3SymbolRemovalTest(unittest.TestCase):
  def test_cash_pass_writer_function_definitions_gone_from_schedule_module(self) -> None:
    text = SCHEDULE_PATH.read_text(encoding="utf-8")
    self.assertNotIn(
      "def apply_short_term_debt_current_portion(",
      text,
      "apply_short_term_debt_current_portion definition must be removed",
    )
    self.assertNotIn(
      "def build_short_term_debt_current_portion_plan(",
      text,
      "build_short_term_debt_current_portion_plan definition must be removed",
    )

  def test_short_term_debt_ratio_lever_id_constant_gone(self) -> None:
    text = SCHEDULE_PATH.read_text(encoding="utf-8")
    self.assertNotIn(
      "SHORT_TERM_DEBT_RATIO_LEVER_ID = _lookup_lever_id(",
      text,
      "SHORT_TERM_DEBT_RATIO_LEVER_ID constant must be removed",
    )

  def test_cash_runner_wrapper_function_gone(self) -> None:
    text = CASH_RUNNER_PATH.read_text(encoding="utf-8")
    self.assertNotIn(
      "def _apply_cash_pass_short_term_debt_current_portion(",
      text,
      "_apply_cash_pass_short_term_debt_current_portion definition must be removed",
    )
    self.assertNotIn(
      "_CASH_STRATEGY_SHORT_TERM_DEBT_RATIO_LEVER_ID = post_intake_driver_target_single_lever_id_for_target_driver",
      text,
      "_CASH_STRATEGY_SHORT_TERM_DEBT_RATIO_LEVER_ID constant must be removed",
    )
    self.assertNotIn(
      "apply_short_term_debt_current_portion as _debt_schedule_apply_short_term_current_portion",
      text,
      "Import alias for the deleted writer must be removed",
    )

  # test_convergence_runner_pipeline_stages_gone removed in P3.33 Phase 3
  # step 7 — the convergence runner file itself was deleted, making this
  # source-inspection regression check vacuous.

  def test_finmo_bridge_no_longer_seeds_lever_from_intake(self) -> None:
    text = FINMO_BRIDGE_PATH.read_text(encoding="utf-8")
    # The seeding code at the row builder no longer reads short_term_debt
    # from financials_json — it just appends 0.0.
    self.assertNotIn(
      'short_term_ratio = _ratio((financials_json or {}).get("short_term_debt"), (financials_json or {}).get("total_debt_outstanding"))',
      text,
      "Intake-derived STD ratio seeding must be removed",
    )

  def test_cash_runner_post_pass_check_for_missing_std_lever_gone(self) -> None:
    text = CASH_RUNNER_PATH.read_text(encoding="utf-8")
    # Only check the structural appendlist call (the literal string
    # may appear in inline comments documenting the removal).
    self.assertNotIn(
      'cash_contract_failures.append(\n      {\n        "error": "cash_debt_schedule_short_term_current_portion_missing"',
      text,
      "Cash-pass post-pass append of cash_debt_schedule_short_term_current_portion_missing must be removed",
    )
    self.assertNotIn(
      "missing_short_term_current_portion_rows.append(",
      text,
      "All structural references to the deleted post-pass STD check must be removed",
    )

  def test_schedule_init_does_not_export_deleted_functions(self) -> None:
    text = SCHEDULE_INIT_PATH.read_text(encoding="utf-8")
    self.assertNotIn(
      "apply_short_term_debt_current_portion,",
      text,
      "__init__.py must not re-export the deleted writer",
    )
    self.assertNotIn(
      "build_short_term_debt_current_portion_plan,",
      text,
      "__init__.py must not re-export the deleted plan builder",
    )


class STDCanonicalSourceLayer3ValidatorStillFiresTest(unittest.TestCase):
  def test_validator_std_branch_runs_when_lever_is_inert_and_debt_exists(self) -> None:
    """End-to-end: simulate the post-Layer-3 state where the STD% lever
    sits at 0 in model_input. Validator must still fire the STD branch
    (because closing_debt > 0) and pass when finmo's short_term_debt
    matches the schedule-derived expected."""
    from client_intake_and_finmo.post_intake_runtime_validation.balance_sheet_driver_validation import (  # noqa: WPS433
      balance_sheet_driver_finalize_errors,
    )

    HORIZON = 20
    quarterly_repay = 15000

    schedule_rows = []
    opening = 300_000
    for q in range(1, HORIZON + 1):
      closing = max(0, opening - quarterly_repay)
      schedule_rows.append({
        "quarter_index": q,
        "opening_debt": opening,
        "closing_debt": closing,
        "total_principal_payment": quarterly_repay,
      })
      opening = closing
    debt_schedule = {"rows": schedule_rows}

    finmo_rows = []
    opening = 300_000
    for q in range(1, HORIZON + 1):
      closing = max(0, opening - quarterly_repay)
      next_four = sum(
        quarterly_repay
        for nq in range(q + 1, q + 5)
        if nq <= HORIZON
      )
      finmo_rows.append({
        "quarter_index": q,
        "date": "2026-01-01",
        "days_in_quarter": 90,
        "revenue": 1000.0,
        "cost_of_goods_sold": 0.0,
        "marketing": 0.0,
        "research_and_development": 0.0,
        "lease_rent": 0.0,
        "payroll": 0.0,
        "general_and_administrative": 0.0,
        "long_term_debt": closing,
        "short_term_debt": next_four,
        "accounts_receivable": 0.0,
        "accounts_payable": 0.0,
        "inventory": 0.0,
      })
    finmo_json = {"quarter_rows": finmo_rows}

    # CRITICAL: the STD% lever is INERT (all zeros) — the post-Layer-3
    # state. No more cash-pass writer means the lever stays at 0.
    model_input_json = {
      "sections": {
        "balance_sheet": [
          {
            "lever_id": "balance_sheet::Short Term Debt (% of LTD)",
            "label": "Short Term Debt (% of LTD)",
            "controller_write": False,
            "values": [0.0] * (HORIZON + 1),  # all zeros — lever is inert
          },
        ],
      },
    }

    errors = balance_sheet_driver_finalize_errors(
      financials_json={"total_debt_outstanding": 300_000.0},
      ops_json={},
      model_input_json=model_input_json,
      finmo_json=finmo_json,
      debt_schedule=debt_schedule,
      cash_strategy_second_pass_result={},
    )

    std_errors = [
      e for e in errors
      if "Short Term Debt (% of LTD)" in str(e)
      and "balance_sheet_driver_formula_failed" in str(e)
    ]
    self.assertEqual(
      std_errors, [],
      f"Validator must pass when finmo STD matches schedule; got {std_errors}",
    )

  def test_validator_std_branch_still_catches_mismatches(self) -> None:
    """Counter-test: with the lever inert AND finmo's STD wrong, the
    validator must still hard-fail."""
    from client_intake_and_finmo.post_intake_runtime_validation.balance_sheet_driver_validation import (  # noqa: WPS433
      balance_sheet_driver_finalize_errors,
    )

    HORIZON = 20
    quarterly_repay = 15000

    schedule_rows = []
    opening = 300_000
    for q in range(1, HORIZON + 1):
      closing = max(0, opening - quarterly_repay)
      schedule_rows.append({
        "quarter_index": q,
        "opening_debt": opening,
        "closing_debt": closing,
        "total_principal_payment": quarterly_repay,
      })
      opening = closing
    debt_schedule = {"rows": schedule_rows}

    # FINMO with WRONG STD.
    finmo_rows = []
    opening = 300_000
    for q in range(1, HORIZON + 1):
      closing = max(0, opening - quarterly_repay)
      finmo_rows.append({
        "quarter_index": q,
        "date": "2026-01-01",
        "days_in_quarter": 90,
        "revenue": 1000.0,
        "cost_of_goods_sold": 0.0,
        "marketing": 0.0,
        "research_and_development": 0.0,
        "lease_rent": 0.0,
        "payroll": 0.0,
        "general_and_administrative": 0.0,
        "long_term_debt": closing,
        "short_term_debt": 99_999,  # WRONG — should be ~60K early, declining
        "accounts_receivable": 0.0,
        "accounts_payable": 0.0,
        "inventory": 0.0,
      })
    finmo_json = {"quarter_rows": finmo_rows}

    model_input_json = {
      "sections": {
        "balance_sheet": [
          {
            "lever_id": "balance_sheet::Short Term Debt (% of LTD)",
            "label": "Short Term Debt (% of LTD)",
            "controller_write": False,
            "values": [0.0] * (HORIZON + 1),
          },
        ],
      },
    }

    errors = balance_sheet_driver_finalize_errors(
      financials_json={"total_debt_outstanding": 300_000.0},
      ops_json={},
      model_input_json=model_input_json,
      finmo_json=finmo_json,
      debt_schedule=debt_schedule,
      cash_strategy_second_pass_result={},
    )

    std_errors = [
      e for e in errors
      if "Short Term Debt (% of LTD)" in str(e)
      and "balance_sheet_driver_formula_failed" in str(e)
    ]
    self.assertGreater(
      len(std_errors), 0,
      "Validator must hard-fail on STD mismatch even when lever is inert",
    )


if __name__ == "__main__":
  unittest.main()
