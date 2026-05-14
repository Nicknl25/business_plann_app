"""Phase 9 P3.10 iter 16 fix — exclude ΔSTD from operating cash flow.

Iter 15 corrected Total Liabilities double-counting (LTD = closing - STD).
That surfaced a compensating bug in the cash-flow construction:

  changes_in_current_liabilities = current_liabilities - previous_current_liabilities

where current_liabilities included STD. So ΔSTD was being treated as
operating cash inflow — inflating cash by accumulated ΔSTD. Pre-iter-15
this hidden bug compensated the displayed-LTD double-counting, so the
balance sheet "balanced" via two compensating errors. Post-iter-15 only
the displayed-LTD bug was fixed; cash inflation persisted; balance
sheet failed to reconcile.

Iter 16 fix: cash-flow's changes_in_current_liabilities uses the
OPERATIONAL subset only (AP + Deferred Revenue), excluding STD.
STD reclassification is a balance-sheet presentation change, not an
actual cash event.

The displayed `current_liabilities` row on the balance sheet remains
AP + STD + DR — that's the correct balance-sheet line. Only the
cash-flow delta computation changes.

Adds:
  - balance_sheet_reconciliation_errors fail-fast (always fires;
    asserts total_assets == total_liabilities + total_equity per Q).
  - Wired into finalize alongside the existing global invariant checks.
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
  opening_short_term_debt: float = 0.0,
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
        "short_term_debt_opening_balance_seed": float(opening_short_term_debt),
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
      "total_assets": float(r.get("total_assets") or 0.0),
      "total_liabilities": float(r.get("total_liabilities") or 0.0),
      "total_equity": float(r.get("total_equity") or 0.0),
      "total_liabilities_and_equity": float(r.get("total_liabilities_and_equity") or 0.0),
      "current_liabilities": float(r.get("current_liabilities") or 0.0),
      "changes_in_current_liabilities": float(r.get("changes_in_current_liabilities") or 0.0),
      "short_term_debt": float(r.get("short_term_debt") or 0.0),
      "long_term_debt": float(r.get("long_term_debt") or 0.0),
      "debt_closing_balance": float(r.get("debt_closing_balance") or 0.0),
      "accounts_payable": float(r.get("accounts_payable") or 0.0),
      "deferred_revenue": float(r.get("deferred_revenue") or 0.0),
    }
    for r in rows
  }


class BalanceSheetReconcilesAcrossScenariosTest(unittest.TestCase):
  """Fix 1 + 2 outcome: balance sheet reconciles every quarter."""

  def _assert_reconciles(self, rows: dict, label: str) -> None:
    for q, r in rows.items():
      ta = int(round(r["total_assets"]))
      tle = int(round(r["total_liabilities"] + r["total_equity"]))
      self.assertLessEqual(
        abs(ta - tle), 1,
        f"{label} Q{q} balance sheet must reconcile: "
        f"assets={ta} liab+equity={tle} diff={ta - tle}",
      )

  def test_nexgen_shape_aggressive_paydown_balance_sheet_reconciles(self) -> None:
    """Front-loaded paydown that exceeds remaining balance — the
    NexGen-shaped scenario that exposed Bug B."""
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
    self._assert_reconciles(rows, "nexgen-shape")

  def test_zero_debt_scenario_balance_sheet_reconciles(self) -> None:
    """Business with no debt — STD = 0 every quarter, ΔSTD = 0,
    no behavior change vs pre-iter-16."""
    rows = _run_finmo(_build_model_input(
      repayment_values_q1_to_q20=[0.0] * 20,
      issuance_values_q1_to_q20=[0.0] * 20,
      opening_debt=0.0,
    ))
    self._assert_reconciles(rows, "zero-debt")
    for q in range(1, 21):
      self.assertEqual(int(round(rows[q]["short_term_debt"])), 0)
      self.assertEqual(int(round(rows[q]["long_term_debt"])), 0)

  def test_sunny_shape_steady_paydown_balance_sheet_reconciles(self) -> None:
    """Steady $15K/q straight-line paydown (Sunny class) must
    reconcile after iter 16."""
    rows = _run_finmo(_build_model_input(
      repayment_values_q1_to_q20=[15_000.0] * 20,
      issuance_values_q1_to_q20=[0.0] * 20,
      opening_debt=300_000.0,
    ))
    self._assert_reconciles(rows, "sunny-shape")


class OperatingCashFlowDeltaUsesOperationalSubsetOnlyTest(unittest.TestCase):
  """Fix 1 contract: changes_in_current_liabilities = ΔAP + ΔDR
  (excludes STD)."""

  def test_changes_in_current_liab_does_not_react_to_std_changes(self) -> None:
    """Synthetic: AP and DR both stay 0 across every quarter (no
    revenue/expenses → AP=DR=0). STD fluctuates wildly via paydown.
    changes_in_current_liabilities MUST be 0 every quarter — STD
    deltas don't count toward operating cash flow."""
    repayments = [50_000.0, 75_000.0, 100_000.0, 50_000.0] + [10_000.0] * 16
    rows = _run_finmo(_build_model_input(
      repayment_values_q1_to_q20=repayments,
      issuance_values_q1_to_q20=[0.0] * 20,
      opening_debt=300_000.0,
    ))
    # Sanity: STD is non-zero and changing across early quarters.
    std_series = [int(round(rows[q]["short_term_debt"])) for q in range(1, 21)]
    self.assertTrue(any(s != std_series[0] for s in std_series),
                    "fixture should produce varying STD")
    # Critical: changes_in_current_liabilities is 0 for every quarter
    # (AP=DR=0 fixture → operational delta is always 0).
    for q in range(1, 21):
      self.assertEqual(
        int(round(rows[q]["changes_in_current_liabilities"])), 0,
        f"Q{q} ΔCL must be 0 (operational subset zero) — "
        f"got {rows[q]['changes_in_current_liabilities']}; "
        f"STD={rows[q]['short_term_debt']}",
      )

  def test_displayed_current_liabilities_still_includes_std(self) -> None:
    """The displayed `current_liabilities` row on the balance sheet
    remains AP + STD + DR. Only the cash-flow delta uses the
    operational subset. The display contract is unchanged."""
    rows = _run_finmo(_build_model_input(
      repayment_values_q1_to_q20=[15_000.0] * 20,
      issuance_values_q1_to_q20=[0.0] * 20,
      opening_debt=200_000.0,
    ))
    for q in range(1, 21):
      cl = rows[q]["current_liabilities"]
      ap = rows[q]["accounts_payable"]
      std = rows[q]["short_term_debt"]
      dr = rows[q]["deferred_revenue"]
      self.assertAlmostEqual(
        cl, ap + std + dr, places=0,
        msg=f"Q{q} displayed current_liabilities must remain AP + STD + DR",
      )


class BalanceSheetReconciliationValidatorTest(unittest.TestCase):
  """Fix 3: validator is unconditional and surfaces per-component breakdown."""

  def setUp(self) -> None:
    from client_intake_and_finmo.post_intake_runtime_validation import (  # noqa: WPS433
      balance_sheet_driver_validation as mod,
    )
    self._fn = mod.balance_sheet_reconciliation_errors

  def _row(self, q: int, **overrides) -> dict:
    base = {
      "quarter_index": q,
      "cash": 100, "accounts_receivable": 0, "inventory": 0,
      "prepaid_expenses": 0, "ppe": 0,
      "accounts_payable": 0, "short_term_debt": 0, "deferred_revenue": 0,
      "long_term_debt": 0,
      "owners_capital": 100, "retained_earnings": 0, "other_equity": 0,
      "total_assets": 100,
      "total_liabilities": 0,
      "total_equity": 100,
    }
    base.update(overrides)
    return base

  def test_validator_passes_when_balance_sheet_reconciles(self) -> None:
    rows = [self._row(q) for q in range(1, 21)]
    errors = self._fn(finmo_json={"quarter_rows": rows})
    self.assertEqual(errors, [])

  def test_validator_hard_fails_when_assets_exceed_liab_plus_equity(self) -> None:
    rows = [
      self._row(7, total_assets=1000, total_liabilities=400, total_equity=500)
    ]
    errors = self._fn(finmo_json={"quarter_rows": rows})
    self.assertEqual(len(errors), 1)
    self.assertIn("balance_sheet_reconciliation_failed", errors[0])
    self.assertIn("q=7", errors[0])
    self.assertIn("total_assets=1000", errors[0])
    self.assertIn("total_liabilities_plus_equity=900", errors[0])
    self.assertIn("diff=100", errors[0])

  def test_validator_diagnostic_includes_per_component_breakdown(self) -> None:
    """When the equation fails, the diagnostic must surface assets
    AND liabilities AND equity components so a post-mortem can see
    which line is off."""
    rows = [
      self._row(
        3,
        cash=200, accounts_receivable=50, inventory=10, prepaid_expenses=5, ppe=100,
        accounts_payable=20, short_term_debt=15, deferred_revenue=5, long_term_debt=80,
        owners_capital=100, retained_earnings=50, other_equity=10,
        total_assets=365,
        total_liabilities=120,
        total_equity=160,  # 365 - 280 = 85 diff
      )
    ]
    errors = self._fn(finmo_json={"quarter_rows": rows})
    self.assertEqual(len(errors), 1)
    err = errors[0]
    self.assertIn("cash=200", err)
    self.assertIn("ar=50", err)
    self.assertIn("inv=10", err)
    self.assertIn("prepaid=5", err)
    self.assertIn("ppe=100", err)
    self.assertIn("ap=20", err)
    self.assertIn("std=15", err)
    self.assertIn("dr=5", err)
    self.assertIn("ltd=80", err)
    self.assertIn("oc=100", err)
    self.assertIn("re=50", err)
    self.assertIn("oe=10", err)

  def test_validator_tolerates_one_dollar_rounding(self) -> None:
    rows = [self._row(5, total_assets=1000, total_liabilities=600, total_equity=399)]
    errors = self._fn(finmo_json={"quarter_rows": rows})
    self.assertEqual(errors, [])

  def test_validator_fires_unconditionally_no_applicability_gating(self) -> None:
    """Unlike the iter 15 STD/LTD coherence validator (N/A when
    debt=0), this validator MUST fire even when there's no debt."""
    rows = [
      self._row(
        2,
        cash=500, ppe=0,
        accounts_payable=0, short_term_debt=0, deferred_revenue=0, long_term_debt=0,
        owners_capital=100, retained_earnings=0, other_equity=0,
        total_assets=500,
        total_liabilities=0,
        total_equity=100,  # 500 vs 100, diff=400, no debt anywhere
      )
    ]
    errors = self._fn(finmo_json={"quarter_rows": rows})
    self.assertEqual(len(errors), 1)
    self.assertIn("balance_sheet_reconciliation_failed", errors[0])
    self.assertIn("q=2", errors[0])


class FinalizeWiresBalanceSheetReconciliationValidatorTest(unittest.TestCase):
  def test_finalize_imports_reconciliation_validator(self) -> None:
    text = FINALIZE_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "balance_sheet_reconciliation_errors",
      text,
      "finalize_post_intake.py must import the iter 16 BS reconciliation validator",
    )

  def test_finalize_calls_reconciliation_validator(self) -> None:
    text = FINALIZE_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "balance_sheet_reconciliation_errors(\n        finmo_json=",
      text,
      "finalize_post_intake.py must invoke the validator with finmo_json",
    )


class WorkbookCurrentLiabilityChangeUsesOperationalSubsetTest(unittest.TestCase):
  def test_workbook_current_liability_change_excludes_short_term_debt(self) -> None:
    text = WORKBOOK_FINMO_SHEET.read_text(encoding="utf-8")
    # The new formula constructs (AP + DR) - (prior AP + prior DR).
    # The pre-iter-16 reference to the displayed Current Liabilities
    # row in the change-formula must be gone.
    self.assertNotIn(
      "current_liability_change = f\"={_fr(ctx, 'Balance Sheet', 'Current Liabilities', col)}-{_prior(ctx, 'Balance Sheet', 'Current Liabilities', col)}\"",
      text,
      "workbook current_liability_change must NOT reference the displayed "
      "Current Liabilities row (which includes STD) — that was Bug B.",
    )
    # Must reference Accounts Payable + Deferred Revenue explicitly.
    self.assertIn(
      "_fr(ctx, 'Balance Sheet', 'Accounts Payable', col)",
      text,
    )
    self.assertIn(
      "_fr(ctx, 'Balance Sheet', 'Deferred Revenue', col)",
      text,
    )


class SourceLevelInvariantsTest(unittest.TestCase):
  def test_finmo_model_uses_operational_subset_for_ocf_delta(self) -> None:
    text = FINMO_MODEL_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "operational_current_liabilities = accounts_payable + deferred_revenue",
      text,
      "finmo_model.py must define operational_current_liabilities as AP + DR (no STD)",
    )
    self.assertIn(
      "changes_in_current_liabilities = (\n      operational_current_liabilities - previous_operational_current_liabilities\n    )",
      text,
      "finmo_model.py changes_in_current_liabilities must subtract operational subsets",
    )

  def test_finmo_model_seeds_previous_operational_current_liabilities(self) -> None:
    text = FINMO_MODEL_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "previous_operational_current_liabilities",
      text,
      "finmo_model.py must seed previous_operational_current_liabilities from intake AP",
    )

  def test_finmo_model_displayed_current_liabilities_still_includes_std(self) -> None:
    text = FINMO_MODEL_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "current_liabilities = accounts_payable + short_term_debt + deferred_revenue",
      text,
      "Displayed current_liabilities row must remain AP + STD + DR",
    )

  def test_validator_function_present(self) -> None:
    text = VALIDATOR_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "def balance_sheet_reconciliation_errors(",
      text,
      "balance_sheet_driver_validation.py must define the iter 16 reconciliation validator",
    )


if __name__ == "__main__":
  unittest.main()
