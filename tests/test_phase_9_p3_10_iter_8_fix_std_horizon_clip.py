"""Phase 9 P3.10 iter 8 fix — horizon-edge clip on Layer 1's STD sum.

Iter 8's diagnostic showed Layer 1's source code was running with the
correct EXCLUSIVE q+1..q+4 window, but `_row_value(..., q)` for q > 20
silently returned the LAST quarter's value (because
`ControllerWriteRow._storage_index` clamps OOB indices to QUARTER_COUNT).
Result: Q17..Q20 all summed to 4*$15K = $60K instead of the correct
$45K/$30K/$15K/$0 horizon-edge values.

This test suite directly exercises `calculate_finmo_model` against a
synthetic 20-quarter $15K/quarter debt schedule and asserts the
expected EXCLUSIVE q+1..q+4 horizon-clipped values for Q1, Q17, Q18,
Q19, Q20.

Universal-app: same code path, no archetype branching, no clipping
beyond the horizon (which IS the clip).
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


def _build_synthetic_model_input_for_uniform_debt_schedule(
  *, quarterly_repayment: int = 15_000, opening_debt: int = 300_000
) -> dict:
  """Minimal model_input that produces a uniform $15K/quarter debt
  schedule via the schedules::Debt Repayment lever. Every other lever
  is zero/empty so we focus the assertion on STD."""
  # 21 values per lever: stub Q0 + Q1..Q20 live
  zeros_21 = [0.0] * 21
  repayment_values = [0.0] + [float(quarterly_repayment)] * 20
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
           "controller_write": True, "values": zeros_21},
          {"label": "Debt Repayment (Scheduled)",
           "lever_id": "schedules::Debt Repayment (Scheduled)",
           "controller_write": True, "values": repayment_values},
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


class STDHorizonClipTest(unittest.TestCase):
  def setUp(self) -> None:
    from financial_model_engine.finmo_model import calculate_finmo_model  # noqa: WPS433
    from financial_model_engine.model_inputs import FinancialModelInputs  # noqa: WPS433
    self._calc = calculate_finmo_model
    self._book_cls = FinancialModelInputs

  def _run(self) -> dict:
    """Run FINMO once on the synthetic uniform-$15K-schedule model
    input and return a dict mapping quarter_index -> short_term_debt."""
    mi = _build_synthetic_model_input_for_uniform_debt_schedule()
    book = self._book_cls.from_model_input_json(mi)
    result = self._calc(book)
    rows = result.quarter_rows()
    return {int(r.get("quarter_index") or 0): float(r.get("short_term_debt") or 0.0) for r in rows}

  def test_q1_full_in_horizon_window_sums_to_60k(self) -> None:
    """Q1 -> [Q2, Q3, Q4, Q5] -> all in horizon, all $15K -> $60K."""
    std_by_q = self._run()
    self.assertEqual(int(round(std_by_q[1])), 60_000,
                     f"Q1 STD must be 4 * $15K = $60K (got {std_by_q[1]})")

  def test_q17_three_in_horizon_sums_to_45k(self) -> None:
    """Q17 -> [Q18, Q19, Q20, Q21] -> Q21 is OOB -> $15K * 3 = $45K.
    Iter 8's bug made this $60K via _storage_index clamp."""
    std_by_q = self._run()
    self.assertEqual(int(round(std_by_q[17])), 45_000,
                     f"Q17 STD must be Q18+Q19+Q20+0 = $45K (got {std_by_q[17]})")

  def test_q18_two_in_horizon_sums_to_30k(self) -> None:
    """Q18 -> [Q19, Q20, Q21, Q22] -> $15K * 2 = $30K."""
    std_by_q = self._run()
    self.assertEqual(int(round(std_by_q[18])), 30_000,
                     f"Q18 STD must be Q19+Q20+0+0 = $30K (got {std_by_q[18]})")

  def test_q19_one_in_horizon_sums_to_15k(self) -> None:
    """Q19 -> [Q20, Q21, Q22, Q23] -> only Q20 in horizon -> $15K."""
    std_by_q = self._run()
    self.assertEqual(int(round(std_by_q[19])), 15_000,
                     f"Q19 STD must be Q20+0+0+0 = $15K (got {std_by_q[19]})")

  def test_q20_no_in_horizon_sums_to_0(self) -> None:
    """Q20 -> [Q21, Q22, Q23, Q24] -> all OOB -> $0."""
    std_by_q = self._run()
    self.assertEqual(int(round(std_by_q[20])), 0,
                     f"Q20 STD must be 0+0+0+0 = $0 (got {std_by_q[20]})")

  def test_storage_index_clamp_is_NOT_silently_returning_last_quarter(self) -> None:
    """Direct probe of the underlying bug: confirm _row_value for q=21
    against a populated lever returns the clamped LAST quarter's value
    (this is the OOB behavior we're guarding around). If this assertion
    flips, the underlying helper was changed and the guard may be
    redundant — investigate."""
    from financial_model_engine.finmo_model import _row_value  # noqa: WPS433
    mi = _build_synthetic_model_input_for_uniform_debt_schedule()
    book = self._book_cls.from_model_input_json(mi)
    # Q20 in horizon -> $15K (the lever's last live value)
    self.assertEqual(_row_value(book, "schedules", "Debt Repayment (Scheduled)", 20),
                     15_000.0)
    # Q21 OOB -> CLAMPS to Q20's value (current helper semantics).
    # If this ever returns 0.0 instead, _storage_index was fixed and
    # the horizon guard in finmo_model.py:short_term_debt becomes
    # redundant (but still correct).
    self.assertEqual(
      _row_value(book, "schedules", "Debt Repayment (Scheduled)", 21),
      15_000.0,
      "_storage_index still clamps OOB to QUARTER_COUNT; the horizon "
      "guard in Layer 1's STD sum is what makes the math correct.",
    )


if __name__ == "__main__":
  unittest.main()
