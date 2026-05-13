"""Phase 9 P3.10 STD canonical-source layer 1 — Python FINMO computation.

Verifies the architectural target:
  short_term_debt[q] = sum(DEBT_REPAYMENT[q+1..q+4])
  - exclusive of the current quarter (standard "current portion of LTD")
  - read from the schedule's per-quarter principal repayment lever
  - out-of-horizon quarters contribute zero (Q19 -> Q20+0+0+0,
    Q20 -> 0+0+0+0)

Also verifies that the FINMO computation and the C3 validator now use
THE SAME WINDOW so they agree by construction (validator's expected ==
FINMO's actual for any straight-line schedule).
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


FINMO_MODEL_PATH = (
  pathlib.Path(PYTHON_ROOT) / "financial_model_engine" / "finmo_model.py"
)
VALIDATOR_PATH = (
  pathlib.Path(PYTHON_ROOT)
  / "client_intake_and_finmo"
  / "post_intake_runtime_validation"
  / "balance_sheet_driver_validation.py"
)


class STDCanonicalSourceLayer1Test(unittest.TestCase):
  def test_finmo_doc_string_documents_schedule_derived_std(self) -> None:
    """The documented formula table at finmo_model.py:72 records the
    schedule-derived STD computation, not the legacy STD% × LTD."""
    text = FINMO_MODEL_PATH.read_text(encoding="utf-8")
    self.assertNotIn(
      '"Short Term Debt": "balance_sheet::Short Term Debt (% of LTD) * Long Term Debt"',
      text,
      "Legacy STD%×LTD documentation must be gone from the formula table",
    )
    self.assertIn(
      'SUM(schedules::',
      text,
      "Documented formula must reference schedules::Debt Repayment",
    )
    self.assertIn(
      "for q+1..q+4",
      text,
      "Documented window must be q+1..q+4 (exclusive of current quarter)",
    )

  def test_finmo_compute_no_longer_uses_std_pct_lever(self) -> None:
    """The actual computation site no longer reads the STD% lever."""
    text = FINMO_MODEL_PATH.read_text(encoding="utf-8")
    self.assertNotIn(
      '_row_value(model_inputs, "balance_sheet", "Short Term Debt (% of LTD)"',
      text,
      "FINMO must no longer compute STD from the STD%-of-LTD lever",
    )

  def test_finmo_compute_uses_schedule_repayment_window(self) -> None:
    """FINMO's STD computation is `sum(DEBT_REPAYMENT for q+1..q+5)`."""
    text = FINMO_MODEL_PATH.read_text(encoding="utf-8")
    self.assertIn(
      'range(quarter.quarter_index + 1, quarter.quarter_index + 5)',
      text,
      "FINMO must sum schedule repayment for q+1..q+4 (range stop=q+5)",
    )
    self.assertIn(
      '"schedules", DEBT_REPAYMENT_LABEL,',
      text,
      "FINMO must read from schedules::Debt Repayment lever",
    )

  def test_validator_uses_same_q_plus_1_to_q_plus_4_window(self) -> None:
    """The validator at balance_sheet_driver_validation.py uses the
    same q+1..q+4 window — by construction agreement with FINMO."""
    text = VALIDATOR_PATH.read_text(encoding="utf-8")
    # Find the STD branch
    start = text.index('elif validation_key == "finmo_short_term_debt_percent_of_ltd":')
    end = text.index('def balance_sheet_driver_zero_but_applicable_errors(')
    branch = text[start:end]
    self.assertIn(
      "range(quarter_index + 1, quarter_index + 5)",
      branch,
      "Validator must sum schedule repayment for q+1..q+4",
    )
    self.assertNotIn(
      "range(quarter_index, quarter_index + 4)",
      branch,
      "Validator must NOT sum the inclusive q..q+3 window",
    )

  def test_validator_derivation_tag_marks_exclusive_window(self) -> None:
    text = VALIDATOR_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "derivation=sum_next_4_quarters_principal_repayment_from_schedule_exclusive",
      text,
      "Derivation tag must reflect the exclusive q+1..q+4 window",
    )

  def test_finmo_and_validator_agree_by_construction_uniform_schedule(self) -> None:
    """End-to-end agreement check: build a synthetic FINMO + schedule
    where each quarter has principal=$15K, run FINMO's computation
    inline, then call the validator. Validator must emit zero STD
    formula errors."""
    from client_intake_and_finmo.post_intake_runtime_validation.balance_sheet_driver_validation import (  # noqa: WPS433
      balance_sheet_driver_finalize_errors,
    )

    HORIZON = 20
    quarterly_repay = 15000

    # Schedule rows (from Layer 1 perspective: schedule-as-source-of-truth)
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

    # FINMO rows where short_term_debt is computed per the new
    # Layer 1 rule (q+1..q+4 from schedule).
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
      financials_json={"total_debt_outstanding": 300_000.0,
                       "short_term_debt_percent_of_long_term_debt": 0.20},
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
      f"FINMO STD == validator expected by construction; got {std_errors}",
    )

  def test_q19_q20_horizon_edge_clipping(self) -> None:
    """Q19 sums Q20+0+0+0; Q20 sums 0+0+0+0. Validator agrees."""
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

    # Independently confirm Q19 and Q20 expected
    q19_row = next(r for r in finmo_rows if r["quarter_index"] == 19)
    q20_row = next(r for r in finmo_rows if r["quarter_index"] == 20)
    self.assertEqual(q19_row["short_term_debt"], 15000,
                     "Q19 STD = repayment[Q20] + 0 + 0 + 0 = 15000")
    self.assertEqual(q20_row["short_term_debt"], 0,
                     "Q20 STD = 0 + 0 + 0 + 0 = 0 (no quarters beyond horizon)")

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
      financials_json={"total_debt_outstanding": 300_000.0,
                       "short_term_debt_percent_of_long_term_debt": 0.20},
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
    self.assertEqual(std_errors, [],
                     f"Q19/Q20 horizon-edge clipping must agree; got {std_errors}")


if __name__ == "__main__":
  unittest.main()
