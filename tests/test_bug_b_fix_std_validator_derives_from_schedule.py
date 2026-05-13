"""Phase 9 P3.10 Bug B fix — smoke tests for the STD% validator
derivation change.

Verifies:
  - Validator's expected value for finmo_short_term_debt_percent_of_ltd
    is now derived from the debt schedule's next-4-quarters principal
    repayment, NOT from intake-stated STD%/LTD ratio × closing_debt.
  - When FINMO's short_term_debt matches the next-4-quarter schedule
    sum, validator passes (zero formula errors).
  - When FINMO's short_term_debt differs from the schedule sum,
    validator emits a formula_failed error tagged with the new
    derivation key.
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


class BugBFixSTDValidatorDerivesFromScheduleTest(unittest.TestCase):
  def test_derivation_marker_present_in_validator_source(self) -> None:
    """The validator now tags the formula_failed error with
    derivation=sum_next_4_quarters_principal_repayment_from_schedule."""
    p = (
      pathlib.Path(PYTHON_ROOT)
      / "client_intake_and_finmo"
      / "post_intake_runtime_validation"
      / "balance_sheet_driver_validation.py"
    )
    text = p.read_text(encoding="utf-8")
    self.assertIn(
      "derivation=sum_next_4_quarters_principal_repayment_from_schedule",
      text,
      "Bug B fix marker missing from validator source",
    )

  def test_old_value_times_closing_debt_derivation_removed(self) -> None:
    """The old `expected = int(round(value * closing_debt))` line is
    removed from the finmo_short_term_debt_percent_of_ltd branch."""
    p = (
      pathlib.Path(PYTHON_ROOT)
      / "client_intake_and_finmo"
      / "post_intake_runtime_validation"
      / "balance_sheet_driver_validation.py"
    )
    text = p.read_text(encoding="utf-8")
    # Find the STD branch
    start = text.index('elif validation_key == "finmo_short_term_debt_percent_of_ltd":')
    end_marker = "  return errors"
    end = text.index(end_marker, start)
    branch = text[start:end]
    self.assertNotIn(
      "expected = int(round(value * closing_debt))",
      branch,
      "Old intake-derived expected formula should be removed from STD branch",
    )

  def test_validator_passes_when_finmo_std_matches_schedule_4q_sum(self) -> None:
    """End-to-end synthetic: FINMO short_term_debt = sum of next 4
    quarters' principal repayment. Validator should NOT raise a
    formula_failed for the STD lever."""
    from client_intake_and_finmo.post_intake_runtime_validation.balance_sheet_driver_validation import (  # noqa: WPS433
      balance_sheet_driver_finalize_errors,
    )

    HORIZON = 20
    quarterly_repay = 15000  # $300K LTD amortizing over 20 quarters
    schedule_rows = []
    opening = 300000
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
    opening = 300000
    for q in range(1, HORIZON + 1):
      closing = max(0, opening - quarterly_repay)
      # Sum of next 4 quarters' repayment from this quarter onward.
      next_four = sum(
        quarterly_repay
        for nq in range(q, q + 4)
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
      opening = closing
    finmo_json = {"quarter_rows": finmo_rows}

    # Synthetic model_input with the STD lever set to a non-zero value
    # so it's "applicable." The test only checks that the STD validator
    # branch passes; other validation_keys may still raise.
    model_input_json = {
      "sections": {
        "balance_sheet": [
          {
            "lever_id": "balance_sheet::Short Term Debt (% of LTD)",
            "label": "Short Term Debt (% of LTD)",
            "controller_write": True,
            "values": [0.0] + [0.20] * HORIZON,  # value = 0.20 (would have produced expected = 0.20 × LTD pre-fix)
          },
        ],
      },
    }

    errors = balance_sheet_driver_finalize_errors(
      financials_json={"total_debt_outstanding": 300000.0, "short_term_debt_percent_of_long_term_debt": 0.20},
      ops_json={},
      model_input_json=model_input_json,
      finmo_json=finmo_json,
      debt_schedule=debt_schedule,
      cash_strategy_second_pass_result={},
    )

    std_formula_errors = [
      e for e in errors
      if "Short Term Debt (% of LTD)" in str(e)
      and "balance_sheet_driver_formula_failed" in str(e)
    ]
    self.assertEqual(
      std_formula_errors, [],
      f"Expected no STD formula_failed errors; got {std_formula_errors}",
    )

  def test_validator_raises_when_finmo_std_diverges_from_schedule_4q_sum(self) -> None:
    """Counter-test: if FINMO's short_term_debt does NOT match the
    schedule's 4-quarter sum, the validator emits the formula_failed
    error with the new derivation tag."""
    from client_intake_and_finmo.post_intake_runtime_validation.balance_sheet_driver_validation import (  # noqa: WPS433
      balance_sheet_driver_finalize_errors,
    )

    HORIZON = 20
    quarterly_repay = 15000
    schedule_rows = []
    opening = 300000
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

    # FINMO with WRONG STD (way off from the schedule sum).
    finmo_rows = []
    opening = 300000
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
        "short_term_debt": 99999,  # WRONG
        "accounts_receivable": 0.0,
        "accounts_payable": 0.0,
        "inventory": 0.0,
      })
      opening = closing
    finmo_json = {"quarter_rows": finmo_rows}

    model_input_json = {
      "sections": {
        "balance_sheet": [
          {
            "lever_id": "balance_sheet::Short Term Debt (% of LTD)",
            "label": "Short Term Debt (% of LTD)",
            "controller_write": True,
            "values": [0.0] + [0.20] * HORIZON,
          },
        ],
      },
    }

    errors = balance_sheet_driver_finalize_errors(
      financials_json={"total_debt_outstanding": 300000.0, "short_term_debt_percent_of_long_term_debt": 0.20},
      ops_json={},
      model_input_json=model_input_json,
      finmo_json=finmo_json,
      debt_schedule=debt_schedule,
      cash_strategy_second_pass_result={},
    )

    std_formula_errors = [
      e for e in errors
      if "Short Term Debt (% of LTD)" in str(e)
      and "balance_sheet_driver_formula_failed" in str(e)
    ]
    self.assertGreater(
      len(std_formula_errors), 0,
      "Expected at least one STD formula_failed error",
    )
    # Verify the derivation tag is present
    self.assertTrue(
      any("derivation=sum_next_4_quarters_principal_repayment_from_schedule" in str(e)
          for e in std_formula_errors),
      f"Derivation tag missing from error: {std_formula_errors[:1]}",
    )


if __name__ == "__main__":
  unittest.main()
