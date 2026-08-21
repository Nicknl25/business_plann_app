"""Annual aggregation is DECLARED, not inferred from the words in a label.

Why this exists. `annual_mode_for()` read the display label and guessed:
`_ANNUALIZED_LABELS` by exact match, then hints on "opening" / "ending " /
"rate" / "days". That made a label two things at once - the row's identity in
code and its presentation to a client - so a pure reword could silently change
the maths. Measured before the change:

    "Interest Rate"          -> annualize   |  "Interest Rate per quarter" -> average
    "Opening Debt"           -> year_start  |  "Debt at start of quarter"  -> sum
    "Ending Cash"            -> year_end    |  "Cash at period end"        -> sum

Every one of those rewords turns a BALANCE into a SUM - four quarter-end
balances added together, the defect found on 2026-08-19 where Ending Cash Y1
read 391,730 against a true 127,623.

Nothing was broken at the time: 18 rows disagreed with their hints and all 18
were held right by an explicit mode. Sixteen of them were the whole balance
sheet, held by ONE implicit `if statement == "Balance Sheet"`.
"""
from __future__ import annotations

import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (REPO, os.path.join(REPO, "python")):
  if path not in sys.path:
    sys.path.insert(0, path)

from client_statements_output_excel import finmo_sheet  # noqa: E402
from client_statements_output_excel.excel_utils import (  # noqa: E402
  ANNUAL_AVERAGE, ANNUAL_SUM, ANNUAL_YEAR_END, ANNUAL_YEAR_START,
)

#: The tail is allowed to be exactly this big. Growing it is a decision, and
#: changing this number is how that decision gets made in the open.
EXPECTED_TAIL_SIZE = 1


class DeclaredModeTests(unittest.TestCase):

  def test_the_balance_sheet_is_declared_not_inferred(self):
    """Sixteen rows used to ride on one implicit statement check."""
    for label in ("Cash", "Accounts Receivable", "Total Assets",
                  "Total Liabilities & Equity", "Retained Earnings"):
      self.assertEqual(
        finmo_sheet._declared_annual_mode("Balance Sheet", label),
        ANNUAL_YEAR_END, f"{label} must take the year's end, not sum four of them")

  def test_the_two_balances_on_the_cash_flow_statement(self):
    """The pair that was actually summed in a delivered workbook."""
    self.assertEqual(
      finmo_sheet._declared_annual_mode("Cash Flow", "Beginning Cash"),
      ANNUAL_YEAR_START)
    self.assertEqual(
      finmo_sheet._declared_annual_mode("Cash Flow", "Ending Cash"),
      ANNUAL_YEAR_END)

  def test_flows_still_sum(self):
    """The other half. A fix that turned the cash-flow statement into a balance
    sheet would satisfy the test above and be worse."""
    for statement, label in (("Income Statement", "Revenue"),
                             ("Income Statement", "Marketing"),
                             ("Cash Flow", "Net Income"),
                             ("Cash Flow", "Operating Cash Flow")):
      self.assertEqual(
        finmo_sheet._declared_annual_mode(statement, label), ANNUAL_SUM)

  def test_a_reworded_label_does_not_change_the_maths(self):
    """The whole point. The declaration keys on the STATEMENT, so the label is
    free to be reworded for a client without touching the aggregation."""
    for label in ("Cash", "Cash at bank", "Cash and equivalents", "Money in"):
      self.assertEqual(
        finmo_sheet._declared_annual_mode("Balance Sheet", label),
        ANNUAL_YEAR_END, f"rewording to {label!r} changed the annual maths")


class TailTests(unittest.TestCase):
  """The tail is listed, counted, and loud."""

  def test_the_tail_is_exactly_the_declared_size(self):
    self.assertEqual(
      len(finmo_sheet._TAIL_PREFIXES), EXPECTED_TAIL_SIZE,
      "the declared tail changed size - that is a decision to make in the "
      "open, not a number to update quietly")

  def test_the_tail_is_matched_explicitly_not_guessed(self):
    self.assertEqual(
      finmo_sheet._declared_annual_mode(
        "Break-Even", "Break-Even Units - Primary line / dog groom"),
      ANNUAL_AVERAGE)

  def test_an_undeclared_statement_raises_rather_than_guessing(self):
    """A new statement reaching this must be visible. Silence is the failure
    mode the whole change exists to remove."""
    with self.assertRaises(ValueError) as caught:
      finmo_sheet._declared_annual_mode("Some New Statement", "Some Row")
    self.assertIn("undeclared", str(caught.exception))


if __name__ == "__main__":
  unittest.main()
