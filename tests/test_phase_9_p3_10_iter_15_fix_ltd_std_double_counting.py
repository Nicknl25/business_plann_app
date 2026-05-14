"""Phase 9 P3.10 iter 15 fix — STD/LTD double-counting on the balance sheet.

Pre-iter-15 the balance sheet displayed:
  Long Term Debt = debt_schedule_closing_balance     (FULL closing)
  Short Term Debt = sum(next 4 quarters' principal)  (current portion)
  Total Liabilities = ... + STD + LTD                 (DOUBLE COUNTS STD)

Proper accounting:
  Long Term Debt = closing_debt - short_term_debt    (NON-CURRENT only)
  Short Term Debt = sum(next 4 quarters' principal)  (current portion)
  STD + LTD = closing_debt                           (no double count)

Iter 15 fixes:
  - Fix 1 (app): finmo_model.py line ~437 + Q0 stub line ~223 set
    long_term_debt = max(0, debt_closing - short_term_debt).
  - Fix 2 (workbook): finmo_sheet.py LTD formula = closing - STD cell.
  - Fix 3 (validator): balance_sheet_std_ltd_coherence_errors hard
    gate fires only when debt exists; checks STD in [0, closing] and
    LTD = closing - STD.

Tests in this suite:
  - LTD = closing - STD per quarter for a straight-line paydown
  - STD + LTD = closing for every quarter (NexGen-shape)
  - Zero-debt scenario: STD=0, LTD=0, validator does not fire
  - Validator hard-fails when STD > closing (synthetic)
  - Validator hard-fails when LTD != closing - STD (synthetic)
  - Workbook formula uses MAX(0, ... - STD_cell)
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

REPO_ROOT = pathlib.Path(PYTHON_ROOT).parent
WORKBOOK_FINMO_SHEET = REPO_ROOT / "client_statements_output_excel" / "finmo_sheet.py"
FINMO_MODEL_PATH = pathlib.Path(PYTHON_ROOT) / "financial_model_engine" / "finmo_model.py"
VALIDATOR_PATH = (
  pathlib.Path(PYTHON_ROOT)
  / "client_intake_and_finmo"
  / "post_intake_runtime_validation"
  / "balance_sheet_driver_validation.py"
)
FINALIZE_PATH = (
  pathlib.Path(PYTHON_ROOT)
  / "client_intake_and_finmo"
  / "post_intake_runtime_validation"
  / "finalize_post_intake.py"
)


def _build_model_input(
  *,
  repayment_values_q1_to_q20: list,
  issuance_values_q1_to_q20: list,
  opening_debt: float,
) -> dict:
  zeros_21 = [0.0] * 21
  repayments = [0.0] + [float(v) for v in repayment_values_q1_to_q20]
  issuances = [0.0] + [float(v) for v in issuance_values_q1_to_q20]
  return {
    "start_date": "2026-01-01",
    "periods": [
      {"slot_index": 0, "column_index": 7, "year": 2025, "quarter": 0,
       "date": "2025-12-31", "is_stub": True, "days_in_quarter": 90}
    ] + [
      {"slot_index": q, "column_index": 7 + q, "year": 2026 + (q - 1) // 4,
       "quarter": ((q - 1) % 4) + 1, "date": f"2026-{((q-1)%4)*3+1:02d}-01",
       "is_stub": False, "days_in_quarter": 90}
      for q in range(1, 21)
    ],
    "sections": {
      "revenue": [],
      "expenses": [
        {"label": "Cost of Goods Sold", "lever_id": "expenses::Cost of Goods Sold",
         "controller_write": True, "values": zeros_21},
        {"label": "Marketing", "lever_id": "expenses::Marketing",
         "controller_write": True, "values": zeros_21},
        {"label": "Research & Development", "lever_id": "expenses::Research & Development",
         "controller_write": True, "values": zeros_21},
        {"label": "Lease", "lever_id": "expenses::Lease",
         "controller_write": True, "values": zeros_21},
        {"label": "Payroll", "lever_id": "expenses::Payroll",
         "controller_write": True, "values": zeros_21},
        {"label": "General & Administrative", "lever_id": "expenses::General & Administrative",
         "controller_write": True, "values": zeros_21},
        {"label": "Depreciation", "lever_id": "expenses::Depreciation",
         "controller_write": True, "values": zeros_21},
        {"label": "Taxes", "lever_id": "expenses::Taxes",
         "controller_write": True, "values": zeros_21},
        {"label": "Interest Rate", "lever_id": "expenses::Interest Rate",
         "controller_write": True, "values": zeros_21},
      ],
      "balance_sheet": [
        {"label": "Accounts Receivable Days", "lever_id": "balance_sheet::Accounts Receivable Days",
         "controller_write": True, "values": zeros_21},
        {"label": "Inventory Days", "lever_id": "balance_sheet::Inventory Days",
         "controller_write": True, "values": zeros_21},
        {"label": "Accounts Payable Days", "lever_id": "balance_sheet::Accounts Payable Days",
         "controller_write": True, "values": zeros_21},
        {"label": "Prepaid Expenses (% of Revenue)", "lever_id": "balance_sheet::Prepaid Expenses (% of Revenue)",
         "controller_write": True, "values": zeros_21},
        {"label": "Deferred Revenue (% of Revenue)", "lever_id": "balance_sheet::Deferred Revenue (% of Revenue)",
         "controller_write": True, "values": zeros_21},
        {"label": "Owner's Capital", "lever_id": "balance_sheet::Owner's Capital",
         "controller_write": True, "values": zeros_21},
        {"label": "Other Equity", "lever_id": "balance_sheet::Other Equity",
         "controller_write": True, "values": zeros_21},
        {"label": "Distributions", "lever_id": "balance_sheet::Distributions",
         "controller_write": True, "values": zeros_21},
      ],
      "schedules": {
        "debt_opening_balance_seed": float(opening_debt),
        "short_term_debt_opening_balance_seed": 0.0,
        "rows": [
          {"label": "Debt Issuance (New Borrowing)",
           "lever_id": "schedules::Debt Issuance (New Borrowing)",
           "controller_write": True, "values": issuances},
          {"label": "Debt Repayment (Scheduled)",
           "lever_id": "schedules::Debt Repayment (Scheduled)",
           "controller_write": True, "values": repayments},
          {"label": "Capital Expenditures", "lever_id": "schedules::Capital Expenditures",
           "controller_write": True, "values": zeros_21},
          {"label": "Less: Principal Repayments", "lever_id": "schedules::Less: Principal Repayments",
           "controller_write": True, "values": zeros_21},
          {"label": "Plus: Net Additions", "lever_id": "schedules::Plus: Net Additions",
           "controller_write": True, "values": zeros_21},
        ],
      },
    },
  }


def _run_finmo(mi: dict) -> dict:
  from financial_model_engine.finmo_model import calculate_finmo_model  # noqa: WPS433
  from financial_model_engine.model_inputs import FinancialModelInputs  # noqa: WPS433
  book = FinancialModelInputs.from_model_input_json(mi)
  result = calculate_finmo_model(book)
  rows = result.quarter_rows()
  return {
    int(r.get("quarter_index") or 0): {
      "short_term_debt": float(r.get("short_term_debt") or 0.0),
      "long_term_debt": float(r.get("long_term_debt") or 0.0),
      "debt_closing_balance": float(r.get("debt_closing_balance") or 0.0),
      "debt_repayment": float(r.get("debt_repayment") or 0.0),
      "total_liabilities": float(r.get("total_liabilities") or 0.0),
      "current_liabilities": float(r.get("current_liabilities") or 0.0),
    }
    for r in rows
  }


class LTDIsNonCurrentPortionTest(unittest.TestCase):
  """Fix 1: long_term_debt on the balance sheet is closing_debt - STD."""

  def test_straight_line_paydown_ltd_equals_closing_minus_std(self) -> None:
    """$300K opening, $15K/quarter straight-line repayment.
    Each quarter LTD must equal debt_closing - STD."""
    rows = _run_finmo(_build_model_input(
      repayment_values_q1_to_q20=[15_000.0] * 20,
      issuance_values_q1_to_q20=[0.0] * 20,
      opening_debt=300_000.0,
    ))
    for q in range(1, 21):
      closing = rows[q]["debt_closing_balance"]
      std = rows[q]["short_term_debt"]
      ltd = rows[q]["long_term_debt"]
      expected_ltd = max(0.0, closing - std)
      self.assertAlmostEqual(
        ltd, expected_ltd, places=0,
        msg=f"Q{q} LTD ({ltd}) must equal closing({closing}) - STD({std}) = {expected_ltd}",
      )

  def test_std_plus_ltd_equals_closing_debt_for_every_quarter(self) -> None:
    """NexGen-shape: aggressive front-loaded paydown that exceeds
    remaining balance. STD + LTD must equal closing_debt every quarter."""
    repayments = [
      27_000.0, 28_000.0, 30_000.0, 35_000.0,
      40_000.0, 45_000.0, 50_000.0, 55_000.0,
      60_000.0, 65_000.0, 70_000.0, 75_000.0,
      80_000.0, 85_000.0, 90_000.0, 95_000.0,
      100_000.0, 105_000.0, 110_000.0, 115_000.0,
    ]
    rows = _run_finmo(_build_model_input(
      repayment_values_q1_to_q20=repayments,
      issuance_values_q1_to_q20=[0.0] * 20,
      opening_debt=400_000.0,
    ))
    for q in range(1, 21):
      closing = rows[q]["debt_closing_balance"]
      std = rows[q]["short_term_debt"]
      ltd = rows[q]["long_term_debt"]
      self.assertAlmostEqual(
        std + ltd, closing, places=0,
        msg=f"Q{q} STD({std}) + LTD({ltd}) = {std + ltd} must equal closing({closing})",
      )

  def test_zero_debt_scenario_std_and_ltd_both_zero(self) -> None:
    """Business with no debt: STD == 0 and LTD == 0 every quarter."""
    rows = _run_finmo(_build_model_input(
      repayment_values_q1_to_q20=[0.0] * 20,
      issuance_values_q1_to_q20=[0.0] * 20,
      opening_debt=0.0,
    ))
    for q in range(1, 21):
      self.assertEqual(int(round(rows[q]["short_term_debt"])), 0)
      self.assertEqual(int(round(rows[q]["long_term_debt"])), 0)
      self.assertEqual(int(round(rows[q]["debt_closing_balance"])), 0)

  def test_q0_stub_long_term_debt_equals_opening_minus_opening_std(self) -> None:
    """Q0 stub respects same accounting: LTD = opening_debt - opening_STD."""
    mi = _build_model_input(
      repayment_values_q1_to_q20=[10_000.0] * 20,
      issuance_values_q1_to_q20=[0.0] * 20,
      opening_debt=200_000.0,
    )
    mi["sections"]["schedules"]["short_term_debt_opening_balance_seed"] = 40_000.0
    from financial_model_engine.finmo_model import calculate_finmo_model  # noqa: WPS433
    from financial_model_engine.model_inputs import FinancialModelInputs  # noqa: WPS433
    book = FinancialModelInputs.from_model_input_json(mi)
    result = calculate_finmo_model(book)
    stub_rows = result.quarter_rows(include_stub=True)
    q0 = next(r for r in stub_rows if int(r.get("quarter_index") or 0) == 0)
    self.assertEqual(int(round(float(q0.get("short_term_debt") or 0.0))), 40_000)
    self.assertEqual(
      int(round(float(q0.get("long_term_debt") or 0.0))),
      160_000,
      "Q0 LTD must be opening_debt(200K) - opening_STD(40K) = 160K",
    )


class STDLTDCoherenceValidatorTest(unittest.TestCase):
  """Fix 3: validator hard-fails coherence violations; passes when N/A."""

  def setUp(self) -> None:
    from client_intake_and_finmo.post_intake_runtime_validation import (  # noqa: WPS433
      balance_sheet_driver_validation as mod,
    )
    self._fn = mod.balance_sheet_std_ltd_coherence_errors

  def _finmo_json(self, rows: list) -> dict:
    return {"quarter_rows": rows}

  def _schedule(self, closings: dict) -> dict:
    return {
      "rows": [
        {"quarter_index": q, "closing_debt": v}
        for q, v in closings.items()
      ]
    }

  def test_validator_passes_on_correctly_decomposed_std_ltd(self) -> None:
    rows = [
      {"quarter_index": q, "short_term_debt": 50, "long_term_debt": 250,
       "debt_closing_balance": 300}
      for q in range(1, 21)
    ]
    schedule = self._schedule({q: 300 for q in range(1, 21)})
    errors = self._fn(finmo_json=self._finmo_json(rows), debt_schedule=schedule)
    self.assertEqual(errors, [], f"Expected no errors, got: {errors}")

  def test_validator_does_not_fire_when_debt_is_zero(self) -> None:
    """N/A condition: closing_debt == 0 -> no check."""
    rows = [
      {"quarter_index": q, "short_term_debt": 0, "long_term_debt": 0,
       "debt_closing_balance": 0}
      for q in range(1, 21)
    ]
    schedule = self._schedule({q: 0 for q in range(1, 21)})
    errors = self._fn(finmo_json=self._finmo_json(rows), debt_schedule=schedule)
    self.assertEqual(errors, [])

  def test_validator_hard_fails_when_std_exceeds_closing_debt(self) -> None:
    rows = [
      {"quarter_index": 7, "short_term_debt": 500, "long_term_debt": 0,
       "debt_closing_balance": 300}
    ]
    schedule = self._schedule({7: 300})
    errors = self._fn(finmo_json=self._finmo_json(rows), debt_schedule=schedule)
    self.assertEqual(len(errors), 1)
    self.assertIn("balance_sheet_std_ltd_coherence_failed", errors[0])
    self.assertIn("q=7", errors[0])
    self.assertIn("field=short_term_debt", errors[0])
    self.assertIn("expected<=closing_debt=300", errors[0])

  def test_validator_hard_fails_when_ltd_does_not_equal_closing_minus_std(self) -> None:
    """Synthetic broken state: STD=50, LTD=300, closing=300.
    Expected LTD = 300-50 = 250; observed 300 -> violation."""
    rows = [
      {"quarter_index": 4, "short_term_debt": 50, "long_term_debt": 300,
       "debt_closing_balance": 300}
    ]
    schedule = self._schedule({4: 300})
    errors = self._fn(finmo_json=self._finmo_json(rows), debt_schedule=schedule)
    self.assertEqual(len(errors), 1)
    self.assertIn("balance_sheet_std_ltd_coherence_failed", errors[0])
    self.assertIn("q=4", errors[0])
    self.assertIn("field=long_term_debt", errors[0])
    self.assertIn("expected=250", errors[0])
    self.assertIn("derivation=closing_debt(300)_minus_short_term_debt(50)", errors[0])

  def test_validator_hard_fails_when_std_is_negative(self) -> None:
    rows = [
      {"quarter_index": 2, "short_term_debt": -10, "long_term_debt": 100,
       "debt_closing_balance": 100}
    ]
    schedule = self._schedule({2: 100})
    errors = self._fn(finmo_json=self._finmo_json(rows), debt_schedule=schedule)
    self.assertTrue(any("field=short_term_debt" in e and "expected>=0" in e for e in errors))

  def test_validator_uses_schedule_closing_debt_in_preference_to_finmo(self) -> None:
    """When schedule and FINMO disagree on closing_debt, the validator
    must use the schedule (canonical post-cash-pass)."""
    rows = [
      {"quarter_index": 1, "short_term_debt": 80, "long_term_debt": 20,
       "debt_closing_balance": 100}  # FINMO says 100
    ]
    schedule = self._schedule({1: 200})  # schedule says 200
    errors = self._fn(finmo_json=self._finmo_json(rows), debt_schedule=schedule)
    # With schedule_closing=200 and STD=80, expected LTD = 120.
    # Observed LTD=20 -> violation.
    self.assertEqual(len(errors), 1)
    self.assertIn("expected=120", errors[0])
    self.assertIn("closing_debt(200)", errors[0])

  def test_validator_does_not_fire_on_one_unit_rounding(self) -> None:
    """1-unit integer-rounding tolerance: LTD=249 vs expected=250 must pass."""
    rows = [
      {"quarter_index": 5, "short_term_debt": 50, "long_term_debt": 249,
       "debt_closing_balance": 300}
    ]
    schedule = self._schedule({5: 300})
    errors = self._fn(finmo_json=self._finmo_json(rows), debt_schedule=schedule)
    self.assertEqual(errors, [])


class FinalizeWiresSTDLTDCoherenceValidatorTest(unittest.TestCase):
  """Fix 3 wiring: finalize must invoke the new validator."""

  def test_finalize_imports_std_ltd_coherence_errors(self) -> None:
    text = FINALIZE_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "balance_sheet_std_ltd_coherence_errors",
      text,
      "finalize_post_intake.py must import the iter 15 coherence validator",
    )

  def test_finalize_calls_std_ltd_coherence_errors(self) -> None:
    text = FINALIZE_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "balance_sheet_std_ltd_coherence_errors(\n        finmo_json=",
      text,
      "finalize_post_intake.py must invoke the validator with finmo_json",
    )


class WorkbookFINMOSheetUsesNonCurrentLTDTest(unittest.TestCase):
  """Fix 2: workbook LTD formula must subtract STD cell."""

  def test_workbook_ltd_formula_subtracts_short_term_debt_cell(self) -> None:
    text = WORKBOOK_FINMO_SHEET.read_text(encoding="utf-8")
    self.assertIn(
      "ctx.finmo_row(\"Balance Sheet\", \"Long Term Debt\")",
      text,
    )
    # The new formula constructs MAX(0, ... - <STD cell>)
    self.assertIn(
      "MAX(0,",
      text,
      "workbook LTD formula must use MAX(0, ...) to floor at zero",
    )
    self.assertIn(
      "_fr(ctx, 'Balance Sheet', 'Short Term Debt', col)",
      text,
      "workbook LTD formula must reference the Short Term Debt cell in the same column",
    )


class FormulaContractDocReflectsNonCurrentLTDTest(unittest.TestCase):
  """FORMULA_REGISTRY entry for Long Term Debt must describe non-current portion."""

  def test_long_term_debt_doc_documents_subtraction_of_std(self) -> None:
    from financial_model_engine import finmo_model  # noqa: WPS433
    formula = finmo_model.FORMULA_REGISTRY.get("Long Term Debt", "")
    self.assertIn(
      "Short Term Debt",
      formula,
      "Long Term Debt FORMULA_REGISTRY entry must mention the STD subtraction",
    )


class SourceLevelInvariantsTest(unittest.TestCase):
  def test_finmo_model_subtracts_std_in_live_quarter(self) -> None:
    text = FINMO_MODEL_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "long_term_debt = max(0.0, debt_closing - short_term_debt)",
      text,
      "finmo_model.py live-quarter LTD must be debt_closing - short_term_debt",
    )

  def test_finmo_model_subtracts_opening_std_in_q0_stub(self) -> None:
    text = FINMO_MODEL_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "opening_long_term_debt = max(0.0, opening_total_debt - opening_short_term_debt)",
      text,
      "finmo_model.py Q0 stub LTD must be opening_total_debt - opening_short_term_debt",
    )

  def test_validator_function_present_in_balance_sheet_module(self) -> None:
    text = VALIDATOR_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "def balance_sheet_std_ltd_coherence_errors(",
      text,
      "balance_sheet_driver_validation.py must define the iter 15 coherence validator",
    )


if __name__ == "__main__":
  unittest.main()
