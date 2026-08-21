"""The row registry RAISES on a miss instead of resolving it to 0.

Every cross-sheet reference in the workbook is addressed through this registry,
because row numbers are a function of business shape. The accessors used to
return 0 on a miss - silently - so a typo or a renamed label produced a
plausible-looking row number and the consequence surfaced somewhere else
entirely: a formula pointing at row 0, a bridge row wired to nothing, or worst
of all `_ANNUALIZED_LABELS`, where a miss reroutes annual aggregation and puts a
wrong number in the annual columns.

Measured before the change: across both fixtures and all four accessors there
were exactly TWO misses in the whole workbook, both deliberate and both
documented. That is what made raising safe.
"""
from __future__ import annotations

import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (REPO, os.path.join(REPO, "python")):
  if path not in sys.path:
    sys.path.insert(0, path)

from client_statements_output_excel.excel_utils import (  # noqa: E402
  RowRegistryMiss,
  WorkbookBuildContext,
)


class ScheduleRowTests(unittest.TestCase):

  def setUp(self):
    self.ctx = WorkbookBuildContext()
    self.ctx.add_schedule_row("Debt Schedule", "Interest Rate", 12)

  def test_a_hit_returns_the_row(self):
    self.assertEqual(self.ctx.schedule_row("Debt Schedule", "Interest Rate"), 12)

  def test_a_renamed_label_raises_rather_than_returning_zero(self):
    """THE hazard this exists for. Renaming a row changes the registry KEY, and
    every consumer keyed on the old string must move in the same commit. Before
    this, they resolved to 0 instead and nothing said a word."""
    with self.assertRaises(RowRegistryMiss):
      self.ctx.schedule_row("Debt Schedule", "Interest Rate per quarter")

  def test_the_message_names_what_is_registered(self):
    """A miss should tell you what you could have meant, not just that you were
    wrong - otherwise the next person greps for it."""
    with self.assertRaises(RowRegistryMiss) as caught:
      self.ctx.schedule_row("Debt Schedule", "Interst Rate")
    self.assertIn("Interest Rate", str(caught.exception))

  def test_an_unknown_sheet_raises_too(self):
    with self.assertRaises(RowRegistryMiss):
      self.ctx.schedule_row("No Such Sheet", "Interest Rate")

  def test_optional_returns_zero_for_a_row_that_may_not_exist(self):
    """The escape hatch, used by exactly two callers, both documented at their
    call site: per-line COGS rows on single-line drafts, and the Marketing
    Schedule sheet on a draft with no marketing payload."""
    self.assertEqual(
      self.ctx.optional_schedule_row("Debt Schedule", "Lease Life"), 0)
    self.assertEqual(self.ctx.optional_schedule_row("No Such Sheet", "x"), 0)


class SiblingAccessorTests(unittest.TestCase):
  """model_input_row, finmo_row and source_row STILL resolve a miss to 0.

  I widened the raise to all four on too narrow a measurement - the gate's two
  fixtures showed no misses, so I generalised. The unit-test fixture carries a
  thinner P&L and raised immediately, and calc_sheet.py:136/157 and
  checks_sheet.py:852 guard on falsiness because they genuinely mean absence.
  Pinned as-is so the current behaviour is deliberate rather than assumed, and
  so a later attempt to close them has to change this test on purpose.
  """

  def test_the_siblings_still_return_zero_on_a_miss(self):
    ctx = WorkbookBuildContext()
    self.assertEqual(ctx.model_input_row("is::Nope"), 0)
    self.assertEqual(ctx.finmo_row("Income Statement", "Nope"), 0)
    self.assertEqual(ctx.source_row("Income Statement", "Nope"), 0)


if __name__ == "__main__":
  unittest.main()
