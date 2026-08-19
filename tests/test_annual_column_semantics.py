"""The ANNUAL COLUMN semantics, pinned (2026-08-19).

mini's audit of the W1-X5 stack found the workbook telling a client two
different Y1 cash numbers on the SAME sheet: the Balance Sheet's Cash row read
127,623 (the year-end balance, correct) while the Cash Flow statement's Ending
Cash row two blocks below read 391,730 - the four quarter-end BALANCES added
together. Beginning Cash was summed the same way.

The cause was routing by STATEMENT rather than by ROW: "year-end unless it is
the Balance Sheet, otherwise sum". Beginning/Ending Cash are balances that live
on the cash-flow statement, so the blanket rule swept them into the flow bucket.

Two things are pinned here, and the second matters as much as the first:
  1. a balance row is aggregated as a balance wherever it lives, and
  2. the flow rows around it still SUM - a fix that turned the cash-flow
     statement into a balance sheet would satisfy (1) and be worse.
"""
from __future__ import annotations

import os
import re
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (REPO, os.path.join(REPO, "python"), os.path.join(REPO, "tests")):
  if path not in sys.path:
    sys.path.insert(0, path)

from _p3_40_contract_2_fixtures import valid_workbook_payload_dict  # noqa: E402
from client_statements_output_excel import design  # noqa: E402
from client_statements_output_excel.data import DraftWorkbookData  # noqa: E402
from client_statements_output_excel.excel_utils import (  # noqa: E402
  ANNUAL_AVERAGE,
  ANNUAL_SUM,
  ANNUAL_YEAR_END,
  ANNUAL_YEAR_START,
  CURRENCY_FORMAT,
  annual_mode_for,
)
from client_statements_output_excel.workbook_builder import (  # noqa: E402
  build_client_financial_model_workbook,
)


def _workbook():
  payload = valid_workbook_payload_dict()
  return build_client_financial_model_workbook(DraftWorkbookData(
    draft_row={"business_name": "Fixture Co", "address_city": "Madison", "address_state": "WI"},
    model_input_json=payload.get("model_input_json") or {},
    finmo_json=payload.get("finmo_json") or {},
    payroll_headcount=payload.get("payroll_headcount") or {},
    debt_schedule=payload.get("debt_schedule") or {},
    planning_run_json=payload.get("planning_run_json") or {},
    run_diagnostics=payload.get("run_diagnostics"),
  ))


class AnnualModeRoutingTests(unittest.TestCase):
  """The router decides from the row's own meaning, not its neighbourhood."""

  def test_cash_flow_balance_rows_are_not_summed(self):
    # The exact two rows mini caught. Both are BALANCES on a flow statement.
    self.assertEqual(annual_mode_for("Beginning Cash", CURRENCY_FORMAT), ANNUAL_YEAR_START)
    self.assertEqual(annual_mode_for("Ending Cash", CURRENCY_FORMAT), ANNUAL_YEAR_END)

  def test_flow_rows_still_sum(self):
    # The other half of the fix: the cash-flow statement is still a flow
    # statement. If these ever come back as balances the year understates by 4x.
    for label in ("Net Income", "Depreciation", "Change in Working Capital",
                  "Net Cash from Operations", "Capital Expenditures",
                  "Revenue", "Cost of Goods Sold", "Operating Expenses"):
      self.assertEqual(annual_mode_for(label, CURRENCY_FORMAT), ANNUAL_SUM,
                       f"{label!r} must sum across the year")

  def test_rate_rows_average_and_balance_rows_take_the_year_end(self):
    self.assertEqual(annual_mode_for("Gross Margin %", design.FMT_PERCENT), ANNUAL_AVERAGE)
    self.assertEqual(annual_mode_for("Closing PPE Balance", CURRENCY_FORMAT), ANNUAL_YEAR_END)
    self.assertEqual(annual_mode_for("Opening Debt", CURRENCY_FORMAT), ANNUAL_YEAR_START)

  def test_the_balance_sheet_does_not_depend_on_the_router(self):
    """A boundary worth stating rather than papering over.

    The router recognises balances by NAME, and a bare "Total Assets" carries no
    balance word - it routes to SUM on its own. That is harmless because the
    Balance Sheet is aggregated as a balance by STATEMENT, ahead of the router;
    the router only decides the rows on the income and cash-flow statements.
    Widening the hint list to cover every balance-sheet noun would move rows on
    the schedules that share those words, so the two rules stay layered - and
    this test says so, so a later reader does not read SUM here as a bug.
    """
    self.assertEqual(annual_mode_for("Total Assets", CURRENCY_FORMAT), ANNUAL_SUM)

  def test_ending_prefix_does_not_capture_a_flow_that_merely_mentions_it(self):
    # "Ending " is matched as a PREFIX on purpose: a row like "Spending on
    # Marketing" contains the letters and is a flow.
    self.assertEqual(annual_mode_for("Spending on Marketing", CURRENCY_FORMAT), ANNUAL_SUM)


class WorkbookAnnualColumnTests(unittest.TestCase):
  """The built sheet, not just the router."""

  @classmethod
  def setUpClass(cls):
    cls.ws = _workbook()["FINMO"]
    cls.rows = {}
    for r in range(1, cls.ws.max_row + 1):
      label = cls.ws.cell(row=r, column=1).value
      if isinstance(label, str) and label.strip():
        cls.rows.setdefault(label.strip(), []).append(r)

  def _annual_formulas(self, label):
    row = self.rows[label][0]
    out = []
    for c in range(1, self.ws.max_column + 1):
      v = self.ws.cell(row=row, column=c).value
      if isinstance(v, str) and v.startswith("=") and c > 23:
        out.append(v)
    return row, out

  def test_ending_cash_takes_the_last_quarter_not_the_sum(self):
    row, formulas = self._annual_formulas("Ending Cash")
    self.assertTrue(formulas, "no annual columns found on Ending Cash")
    for f in formulas:
      self.assertRegex(f, rf"^=[A-Z]+{row}$",
                       f"Ending Cash annual column is {f!r} - a balance must "
                       f"take one quarter-end, never add four of them")

  def test_beginning_cash_takes_the_first_quarter(self):
    row, formulas = self._annual_formulas("Beginning Cash")
    self.assertTrue(formulas)
    for f in formulas:
      self.assertRegex(f, rf"^=[A-Z]+{row}$")

  def test_the_two_statements_agree_on_year_end_cash(self):
    """The client-facing symptom: one sheet, two different Y1 cash numbers."""
    bs_row, bs = self._annual_formulas("Cash")
    cf_row, cf = self._annual_formulas("Ending Cash")
    self.assertEqual(len(bs), len(cf))
    col = lambda f: re.match(r"^=([A-Z]+)\d+$", f).group(1)
    for b, c in zip(bs, cf):
      self.assertEqual(col(b), col(c),
                       f"Balance Sheet Cash reads column {col(b)} of the year "
                       f"while Cash Flow Ending Cash reads {col(c)} - the two "
                       f"statements would print different year-end cash")


if __name__ == "__main__":
  unittest.main()
