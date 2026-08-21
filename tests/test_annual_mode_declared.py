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

import io
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (REPO, os.path.join(REPO, "python")):
  if path not in sys.path:
    sys.path.insert(0, path)

from client_statements_output_excel import finmo_sheet  # noqa: E402
from client_statements_output_excel import excel_utils  # noqa: E402
from client_statements_output_excel.excel_utils import (  # noqa: E402
  ANNUAL_ANNUALIZE, ANNUAL_AVERAGE, ANNUAL_SUM, ANNUAL_YEAR_END, ANNUAL_YEAR_START,
  annual_mode_for,
)
from client_statements_output_excel import design  # noqa: E402

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


class AnnualizeIsDeclaredOnlyTests(unittest.TestCase):
  """ANNUALIZE - the one mode that MULTIPLIES - is no longer reachable by
  guessing at a label.

  It used to be chosen by exact match against a set holding the single string
  "Interest Rate". That made the row's wording load-bearing on the maths: the
  rename to "Interest Rate per quarter", done so a client could tell which
  period the 2.375% belonged to, would have dropped it out of the set and
  turned a x4 into an average - a quarter of the true annual rate, printed
  next to a debt balance. Measured dead across both fixtures (0 decisions) and
  deleted; both rows that want ANNUALIZE now declare it.
  """

  def test_the_exact_match_set_is_gone(self):
    self.assertFalse(
      hasattr(excel_utils, "_ANNUALIZED_LABELS"),
      "the exact-match label set is back - annual maths must not be chosen by "
      "how a row happens to be worded")

  def test_inference_never_returns_annualize(self):
    """The whole surface, not just the label that used to be special."""
    # every number format the design system defines, not a hand-picked few -
    # a hand-picked list is how the one that matters gets left out
    formats = [getattr(design, n) for n in dir(design) if n.startswith("FMT_")] + [""]
    labels = ("Interest Rate", "Interest Rate per quarter", "interest rate",
              "Opening Debt", "Ending Cash", "Revenue", "Cost of Debt",
              "Annual Rate", "Rate", "")
    for label in labels:
      for fmt in formats:
        self.assertNotEqual(
          annual_mode_for(label, fmt), ANNUAL_ANNUALIZE,
          f"inference produced ANNUALIZE for {label!r} / {fmt!r} - that mode is "
          f"declaration-only")

  def test_the_reworded_rate_still_annualizes_where_it_is_declared(self):
    """The other half. Proving inference cannot reach ANNUALIZE is worthless if
    the two rows that need it lost it - that is the same defect, arrived at
    from the other side."""
    from client_statements_output_excel import schedule_sheets, model_inputs_sheet
    src = io.open(schedule_sheets.__file__, encoding="utf-8").read()
    self.assertIn("ANNUAL_ANNUALIZE", src,
                  "the Debt Schedule rate row no longer declares ANNUALIZE")
    src2 = io.open(model_inputs_sheet.__file__, encoding="utf-8").read()
    self.assertIn("ANNUAL_ANNUALIZE", src2,
                  "the Model Inputs rate row no longer declares ANNUALIZE")


if __name__ == "__main__":
  unittest.main()
