"""Phase 9 P3.10 iter 14 fix — STD Layer 1 forward-simulated clipping.

Iter 14's NexGen failure analysis showed an asymmetry in Layer 1's
STD computation:

  - Live quarter's `debt_repayment` field at finmo_model.py:366 is
    `min(requested_repayment, debt_opening + requested_issuance)`.
  - The `short_term_debt` projection summed RAW lever values for
    Q+1..Q+4 (no clipping).

When the cash pass authors `Debt Repayment` lever values exceeding
the remaining principal balance (which iter 13's floor-based
distribution cap enables), the rebuilt debt-schedule's
`total_principal_payment` for those quarters gets clipped to the
remaining balance. The validator at
balance_sheet_driver_validation.py:584-597 reads from that rebuilt
schedule, so its `expected` is the CLIPPED projection. FINMO's
stored `short_term_debt` was the RAW projection. Divergence ->
finalize fails.

Fix: forward-simulate the next 4 quarters from `debt_closing`,
applying the same `min(requested, available)` clipping per quarter,
so FINMO's STD matches what the rebuilt schedule will produce by
construction.

This test suite asserts:
  1. Raw lever in horizon (no over-paydown) -> behavior matches
     iter 8's assertions exactly (clipped == raw when raw fits).
  2. Lever values exceeding remaining balance -> STD reflects the
     clipped trajectory, not the raw lever sum.
  3. Forward simulation correctly handles `Debt Issuance` adding
     headroom in projected quarters.
  4. Horizon clip from iter 8 still works at Q19/Q20.

Universal-app: same code path, no archetype branching.
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


def _build_model_input(
  *,
  repayment_values_q1_to_q20: list,
  issuance_values_q1_to_q20: list,
  opening_debt: float,
) -> dict:
  """Minimal model_input — every other lever zero so we can isolate STD."""
  zeros_21 = [0.0] * 21
  repayments = [0.0] + [float(v) for v in repayment_values_q1_to_q20]
  issuances = [0.0] + [float(v) for v in issuance_values_q1_to_q20]
  assert len(repayments) == 21 and len(issuances) == 21
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
      "debt_repayment": float(r.get("debt_repayment") or 0.0),
      "long_term_debt": float(r.get("long_term_debt") or 0.0),
    }
    for r in rows
  }


class STDForwardSimulateClippingTest(unittest.TestCase):
  """Iter 14 root-cause fix — projection clipping mirrors live clipping."""

  def test_lever_exceeds_remaining_balance_std_uses_clipped_not_raw(self) -> None:
    """Opening debt $100K, lever asks $40K/quarter from Q1.
    After Q1: balance = $60K. After Q2: $20K. Q3 raw $40K, clipped $20K.
    Q4..Q20 raw $40K, clipped $0.

    At Q1, RAW lever sum for Q2..Q5 = 4 * $40K = $160K (broken behavior).
    CLIPPED projection for Q2..Q5 = $40K + $20K + $0 + $0 = $60K.

    The fix must produce $60K, not $160K.
    """
    repayments = [40_000.0] * 20
    issuances = [0.0] * 20
    rows = _run_finmo(_build_model_input(
      repayment_values_q1_to_q20=repayments,
      issuance_values_q1_to_q20=issuances,
      opening_debt=100_000.0,
    ))
    # Sanity: live debt_repayment IS being clipped per quarter.
    self.assertEqual(int(round(rows[1]["debt_repayment"])), 40_000)
    self.assertEqual(int(round(rows[2]["debt_repayment"])), 40_000)
    self.assertEqual(int(round(rows[3]["debt_repayment"])), 20_000)
    self.assertEqual(int(round(rows[4]["debt_repayment"])), 0)
    self.assertEqual(int(round(rows[5]["debt_repayment"])), 0)
    # Q1 STD = sum(clipped(Q2..Q5)) = 40K + 20K + 0 + 0 = 60K
    self.assertEqual(
      int(round(rows[1]["short_term_debt"])), 60_000,
      f"Q1 STD must be the CLIPPED projection 40K+20K+0+0=60K, "
      f"NOT the raw lever sum 4*40K=160K. Got {rows[1]['short_term_debt']}",
    )
    # Q2 STD = sum(clipped(Q3..Q6)) = 20K + 0 + 0 + 0 = 20K
    self.assertEqual(int(round(rows[2]["short_term_debt"])), 20_000)
    # Q3 onward debt_closing == 0; STD must be 0
    self.assertEqual(int(round(rows[3]["short_term_debt"])), 0)
    self.assertEqual(int(round(rows[4]["short_term_debt"])), 0)

  def test_uniform_repayment_within_balance_matches_iter_8_behavior(self) -> None:
    """When the lever values fit within the remaining balance the
    clipped projection equals the raw projection — this is the iter 8
    fixture, regression-checked."""
    repayments = [15_000.0] * 20
    issuances = [0.0] * 20
    rows = _run_finmo(_build_model_input(
      repayment_values_q1_to_q20=repayments,
      issuance_values_q1_to_q20=issuances,
      opening_debt=300_000.0,
    ))
    self.assertEqual(int(round(rows[1]["short_term_debt"])), 60_000)
    self.assertEqual(int(round(rows[17]["short_term_debt"])), 45_000)
    self.assertEqual(int(round(rows[18]["short_term_debt"])), 30_000)
    self.assertEqual(int(round(rows[19]["short_term_debt"])), 15_000)
    self.assertEqual(int(round(rows[20]["short_term_debt"])), 0)

  def test_issuance_in_projected_quarter_adds_to_clipping_headroom(self) -> None:
    """Q1 closing balance: $0. Q2 issues $50K, asks $30K repayment ->
    clipped to $30K. Q3 issues $0, asks $30K -> available = $20K, clipped to $20K.
    Q4..Q5 ask $30K but balance = $0 -> clipped to 0.

    Q1 STD = sum(clipped(Q2..Q5)) = 30K + 20K + 0 + 0 = 50K.
    """
    issuances = [0.0, 50_000.0] + [0.0] * 18
    repayments = [0.0, 30_000.0, 30_000.0, 30_000.0, 30_000.0] + [0.0] * 15
    rows = _run_finmo(_build_model_input(
      repayment_values_q1_to_q20=repayments,
      issuance_values_q1_to_q20=issuances,
      opening_debt=0.0,
    ))
    # Sanity: live behavior
    self.assertEqual(int(round(rows[1]["debt_repayment"])), 0)
    self.assertEqual(int(round(rows[2]["debt_repayment"])), 30_000)
    self.assertEqual(int(round(rows[3]["debt_repayment"])), 20_000)
    self.assertEqual(int(round(rows[4]["debt_repayment"])), 0)
    # Q1 STD: forward-sim from debt_closing(Q1)=0, sees Q2 issuance=$50K.
    self.assertEqual(
      int(round(rows[1]["short_term_debt"])), 50_000,
      f"Q1 STD forward-sim must include Q2 issuance giving $30K + $20K = $50K. "
      f"Got {rows[1]['short_term_debt']}",
    )

  def test_horizon_clip_q19_only_q20_in_window(self) -> None:
    """Iter 8 horizon clip preserved — Q19 STD uses only Q20 of the
    Q20..Q23 window."""
    repayments = [10_000.0] * 20
    issuances = [0.0] * 20
    rows = _run_finmo(_build_model_input(
      repayment_values_q1_to_q20=repayments,
      issuance_values_q1_to_q20=issuances,
      opening_debt=300_000.0,
    ))
    self.assertEqual(int(round(rows[19]["short_term_debt"])), 10_000)
    self.assertEqual(int(round(rows[20]["short_term_debt"])), 0)

  def test_finmo_std_matches_validator_canonical_formula(self) -> None:
    """End-to-end equivalence: FINMO's stored short_term_debt MUST
    equal the sum of the next 4 quarters' actual debt_repayment
    fields. This is the contract the validator at
    balance_sheet_driver_validation.py:558-606 enforces."""
    # NexGen-shaped scenario: aggressive front-loaded paydown that
    # exceeds remaining balance in the back half.
    repayments = [
      27_000.0, 28_000.0, 30_000.0, 35_000.0,    # Q1-Q4
      40_000.0, 45_000.0, 50_000.0, 55_000.0,    # Q5-Q8
      60_000.0, 65_000.0, 70_000.0, 75_000.0,    # Q9-Q12
      80_000.0, 85_000.0, 90_000.0, 95_000.0,    # Q13-Q16
      100_000.0, 105_000.0, 110_000.0, 115_000.0, # Q17-Q20
    ]
    issuances = [0.0] * 20
    rows = _run_finmo(_build_model_input(
      repayment_values_q1_to_q20=repayments,
      issuance_values_q1_to_q20=issuances,
      opening_debt=400_000.0,
    ))
    # For every Q in 1..20, FINMO's short_term_debt must equal the
    # sum of debt_repayment for Q+1..Q+4 (clipped to live horizon).
    for q in range(1, 21):
      window = list(range(q + 1, q + 5))
      expected_from_actuals = sum(
        rows[w]["debt_repayment"] for w in window if w in rows
      )
      actual_std = rows[q]["short_term_debt"]
      self.assertAlmostEqual(
        actual_std, expected_from_actuals, places=0,
        msg=(
          f"Q{q} STD ({actual_std}) must equal sum of next-4-quarter "
          f"debt_repayment ({expected_from_actuals}) — this is the "
          f"validator's canonical contract."
        ),
      )


class FormulaContractDocReflectsClippedProjectionTest(unittest.TestCase):
  """The FORMULA_REGISTRY entry for Short Term Debt must describe
  the clipped projection, not the raw-lever sum."""

  def test_short_term_debt_formula_doc_mentions_clipping(self) -> None:
    from financial_model_engine import finmo_model  # noqa: WPS433
    formula = finmo_model.FORMULA_REGISTRY.get("Short Term Debt", "")
    self.assertIn(
      "min(",
      formula,
      "Short Term Debt FORMULA_REGISTRY entry must describe the "
      "min(requested, available) clipping that mirrors the live quarter.",
    )


class SourceLevelInvariantsTest(unittest.TestCase):
  """Source-level guards on the iter 14 fix shape."""

  def test_finmo_model_uses_forward_simulation_for_std(self) -> None:
    import pathlib
    text = (
      pathlib.Path(PYTHON_ROOT)
      / "financial_model_engine" / "finmo_model.py"
    ).read_text(encoding="utf-8")
    # The iter 14 fix introduces a forward-simulation loop using
    # debt_closing as the seed. Find the construct.
    self.assertIn(
      "_simulated_closing = debt_closing",
      text,
      "finmo_model.py must seed STD forward-sim from the live "
      "quarter's debt_closing balance.",
    )
    self.assertIn(
      "_actual_clipped = min(_requested_repayment, _available)",
      text,
      "finmo_model.py STD forward-sim must clip per-quarter the same "
      "way line 366 clips the live quarter's debt_repayment.",
    )

  def test_finmo_model_does_not_sum_raw_lever_for_std(self) -> None:
    import pathlib
    text = (
      pathlib.Path(PYTHON_ROOT)
      / "financial_model_engine" / "finmo_model.py"
    ).read_text(encoding="utf-8")
    # The pre-iter-14 anti-pattern was a list comp summing
    # _row_value(... DEBT_REPAYMENT_LABEL, q) for q in windowed.
    # That exact shape must be gone.
    self.assertNotIn(
      "short_term_debt = sum(\n      max(0.0, _row_value(model_inputs, \"schedules\", DEBT_REPAYMENT_LABEL, q))\n      for q in windowed",
      text,
      "finmo_model.py must NOT sum raw lever values for STD — "
      "that was the iter 14 root-cause asymmetry.",
    )


if __name__ == "__main__":
  unittest.main()
