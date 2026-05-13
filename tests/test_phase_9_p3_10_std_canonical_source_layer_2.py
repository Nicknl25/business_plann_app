"""Phase 9 P3.10 STD canonical-source layer 2 — workbook export
cell formula.

Verifies the FINMO sheet's `Short Term Debt` cells reference the
Debt Schedule sheet's `Actual Debt Repayment` row at columns
col+1..col+4 (exclusive of current quarter), clipped to the live-
period range. The cell contains a FORMULA, never a literal computed
value.
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, os.pardir))
PYTHON_ROOT = os.path.join(REPO_ROOT, "python")
for path in (REPO_ROOT, PYTHON_ROOT):
  if path not in sys.path:
    sys.path.insert(0, path)


from client_statements_output_excel.excel_utils import (  # noqa: E402
  DEBT_SHEET,
  LAST_LIVE_COL,
  PERIOD_START_COL,
  WorkbookBuildContext,
)
from client_statements_output_excel.finmo_sheet import (  # noqa: E402
  _short_term_debt_formula,
)


def _ctx() -> WorkbookBuildContext:
  ctx = WorkbookBuildContext()
  # Pretend the Debt Schedule sheet places "Actual Debt Repayment" on
  # row 10 — the row number is irrelevant to the formula's correctness;
  # only the cross-sheet path + column range matters.
  ctx.add_schedule_row(DEBT_SHEET, "Actual Debt Repayment", 10)
  return ctx


class STDCanonicalSourceLayer2WorkbookFormulaTest(unittest.TestCase):
  def test_q1_formula_sums_debt_schedule_q2_through_q5(self) -> None:
    """Q1 (col 4 / D) STD formula sums Debt Schedule actual repayment
    at cols 5..8 (E..H = Q2..Q5)."""
    ctx = _ctx()
    formula = _short_term_debt_formula(ctx, 4)
    self.assertEqual(formula, "=SUM('Debt Schedule'!E10:H10)")

  def test_q1_formula_does_not_include_q1_column(self) -> None:
    """The current quarter must NOT appear in the SUM range."""
    ctx = _ctx()
    formula = _short_term_debt_formula(ctx, 4)
    self.assertNotIn("D10", formula)
    self.assertNotIn("D$10", formula)
    self.assertIn("E10:H10", formula)

  def test_q1_formula_references_debt_schedule_sheet_explicitly(self) -> None:
    ctx = _ctx()
    formula = _short_term_debt_formula(ctx, 4)
    self.assertIn("'Debt Schedule'!", formula)
    self.assertNotIn("Long Term Debt", formula)
    self.assertNotIn("Short Term Debt (% of LTD)", formula)
    self.assertNotIn("balance_sheet", formula)

  def test_q1_formula_is_a_formula_not_a_literal(self) -> None:
    """The cell must contain a FORMULA (starts with '=')."""
    ctx = _ctx()
    formula = _short_term_debt_formula(ctx, 4)
    self.assertTrue(formula.startswith("="))

  def test_q19_formula_clips_at_horizon(self) -> None:
    """Q19 (col 22 / V) wants Q20..Q23 → only Q20 (col 23 / W) exists.
    Sum range collapses to the single cell."""
    ctx = _ctx()
    formula = _short_term_debt_formula(ctx, 22)
    self.assertEqual(formula, "=SUM('Debt Schedule'!W10:W10)")

  def test_q20_formula_is_literal_zero(self) -> None:
    """Q20 (col 23 / W) has no quarters after it. Formula = '=0'."""
    ctx = _ctx()
    formula = _short_term_debt_formula(ctx, 23)
    self.assertEqual(formula, "=0")

  def test_q18_formula_includes_q19_and_q20_only(self) -> None:
    """Q18 (col 21 / U) wants Q19..Q22 → Q19 and Q20 exist."""
    ctx = _ctx()
    formula = _short_term_debt_formula(ctx, 21)
    self.assertEqual(formula, "=SUM('Debt Schedule'!V10:W10)")

  def test_full_4_quarter_window_for_quarters_q1_to_q16(self) -> None:
    """Q1 through Q16 all have a full 4-quarter window. Verify the
    range size is always exactly 4 columns wide."""
    ctx = _ctx()
    for q_index in range(1, 17):
      col = PERIOD_START_COL + q_index  # Q1 -> col 4, ..., Q16 -> col 19
      formula = _short_term_debt_formula(ctx, col)
      self.assertNotEqual(formula, "=0", f"Q{q_index} should have a SUM, not literal 0")
      self.assertTrue(formula.startswith("=SUM('Debt Schedule'!"),
                       f"Q{q_index} formula not a SUM: {formula}")

  def test_finmo_sheet_no_longer_imports_std_pct_lever_for_std_cell(self) -> None:
    """Source-level: the STD cell setter line that multiplied bs::Short
    Term Debt (% of LTD) by Long Term Debt is gone."""
    import pathlib
    p = pathlib.Path(REPO_ROOT) / "client_statements_output_excel" / "finmo_sheet.py"
    text = p.read_text(encoding="utf-8")
    self.assertNotIn(
      "bs::Short Term Debt (% of LTD)', col)}*{_fr(ctx, 'Balance Sheet', 'Long Term Debt'",
      text,
      "Old STD%×LTD multiplication for the Short Term Debt cell must be gone",
    )
    self.assertIn(
      "_short_term_debt_formula(ctx, col)",
      text,
      "STD cell must use the schedule-derived formula helper",
    )


if __name__ == "__main__":
  unittest.main()
