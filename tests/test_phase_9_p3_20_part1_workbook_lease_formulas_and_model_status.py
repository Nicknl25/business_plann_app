"""Phase 9 P3.20 Part 1 — tests for:

1. Lease Interest formula now references the Interest Rate cell
   (not a Python literal)
2. Lease Asset Depreciation formula now references the Lease
   Opening Balance Q0 cell (not a Python literal)
3. Model Status fail-fast: returns silently on "OK", raises on
   any non-"OK" value, handles missing workbook gracefully.

These are workbook-builder-output tests (load the most recent
ExpressLogix workbook from disk and inspect formulas) plus
fail-fast unit tests using a synthetic minimal workbook for the
Model Status check.
"""

from __future__ import annotations

import os
import re

from openpyxl.utils import get_column_letter
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYTHON_DIR = _REPO_ROOT / "python"
if str(_PYTHON_DIR) not in sys.path:
  sys.path.insert(0, str(_PYTHON_DIR))

_SCHEDULE_SHEETS_PATH = (
  _REPO_ROOT / "client_statements_output_excel" / "schedule_sheets.py"
)


class WorkbookLeaseFormulaSourceTests(unittest.TestCase):
  """Static source-shape checks: the formula generators must use
  cell references, not Python literal interpolation."""

  def setUp(self) -> None:
    self._src = _SCHEDULE_SHEETS_PATH.read_text(encoding="utf-8")

  def _row_formulas(self, rows, label):
    """The 21 quarter cells of one Debt Schedule row."""
    ws = self._debt_sheet()
    return [ws.cell(rows[label], 3 + i).value for i in range(21)]

  def _debt_rows(self):
    """Every Debt Schedule row KEY mapped to its row number.

    Read from the ctx registry, not from the text in column A. These tests
    used to key off the displayed label, so rewording the sheet broke four of
    them at once - which is the exact coupling the key/label separation was
    built to remove. The key is the contract; the label is presentation.
    """
    self._debt_sheet()
    return dict(type(self)._CTX.schedule_rows["Debt Schedule"])

  def _debt_sheet(self):
    """The built Debt Schedule, built once per process."""
    cached = getattr(type(self), "_SHEET", None)
    if cached is not None:
      return cached
    from replay_gate import _bootstrap
    _bootstrap.bind_root(None)
    from replay_gate.context import GateContext
    from client_statements_output_excel import data as wbdata, workbook_builder
    ctx = GateContext(_bootstrap.gate_connection(), _bootstrap.read_connection())
    wb, gap = ctx._build_workbook(
      workbook_builder.build_client_financial_model_workbook, wbdata.draft_data_from_row)
    assert not gap, gap
    type(self)._CTX = wb.build_context
    type(self)._SHEET = wb["Debt Schedule"]
    return type(self)._SHEET

  def test_lease_interest_formula_uses_cell_reference(self) -> None:
    # The lease interest write should reference local_ref(interest_rate, col)
    # (matching the debt interest formula pattern).
    pattern = re.compile(
      r"ws\.cell\(lease_interest, col, value=0 if stub\s+else\s+(f\"[^\"]+\")"
    )
    matches = pattern.findall(self._src)
    self.assertEqual(len(matches), 1, "Expected exactly one lease interest write")
    formula_template = matches[0]
    self.assertIn(
      "local_ref(rate, col)",
      formula_template,
      "Lease interest formula must reference the Interest Rate cell, not a Python literal",
    )
    self.assertNotIn(
      "rate_cell_value",
      formula_template,
      "Lease interest formula must not interpolate the rate_cell_value literal",
    )

  def test_lease_asset_depreciation_formula_uses_cell_reference(self) -> None:
    """Depreciation reads THIS quarter's asset base and the term row.

    Three shapes have now been wrong here, and the test has followed each:

      1. a Python literal interpolated into the string;
      2. MIN($D$27/term, opening) - a cell, but FROZEN to Q1, so a lease
         signed later raised the asset and never raised depreciation;
      3. a cumulative SUM of additions bolted onto a frozen seed.

    The corkscrew replaces all three: the base is the two rows directly above
    - this quarter's Asset Opening plus this quarter's additions - so the
    property to hold is that the formula reads THOSE cells, in THIS column,
    with no absolute reference anywhere in it.
    """
    rows = self._debt_rows()
    ws = self._debt_sheet()
    dep_row = rows["Lease Asset Depreciation"]
    opening, adds = rows["Right-of-Use Asset Opening"], rows["Lease Additions (asset)"]
    term = rows["Lease Life in quarters"]
    live = 0
    for i in range(1, 21):
      col = get_column_letter(3 + i)
      formula = ws.cell(dep_row, 3 + i).value
      if not isinstance(formula, str):
        continue
      live += 1
      self.assertIn(f"{col}{opening}", formula,
                    f"depreciation does not read THIS quarter's Asset Opening "
                    f"({col}{opening}): {formula!r}")
      self.assertIn(f"{col}{adds}", formula,
                    f"depreciation does not read THIS quarter's additions "
                    f"({col}{adds}): {formula!r}")
      self.assertIn(f"{col}{term}", formula,
                    f"depreciation does not read the lease term row "
                    f"({col}{term}): {formula!r}")
      # THE ORIGINAL COST ANCHOR IS REQUIRED, not forbidden. An earlier
      # version of this test banned absolute references outright, which was
      # right for the design it was written against and wrong for straight
      # line: cost/term needs the cost, and the cost is the opening book in
      # the first live quarter. What must NOT happen is depreciation running
      # off that anchor ALONE - the additions window and the per-quarter cap
      # asserted here and above are what stop it.
      first = get_column_letter(4)
      self.assertIn(f"${first}${opening}", formula,
                    f"depreciation does not read the original cost "
                    f"(${first}${opening}) - straight line is cost over term, "
                    f"and it cannot be computed without it: {formula!r}")
      self.assertIn(f"${first}${adds}", formula,
                    f"depreciation does not open its additions window at "
                    f"${first}${adds}, so a lease signed after Q1 never enters "
                    f"the charge: {formula!r}")
      self.assertNotIn(
        "MAX(", formula.split("SUMPRODUCT")[0],
        f"depreciation is dividing by a REMAINING term again - that writes a "
        f"late lease off by the horizon while its principal is still owed, "
        f"and it broke the balance sheet by the whole lease: {formula!r}")
    self.assertEqual(live, 20, "expected a depreciation formula in every live quarter")

  def test_lease_additions_reach_the_right_of_use_asset(self):
    """A capital lease creates an asset and a liability together.

    Right-of-Use Asset Closing was opening MINUS depreciation, with no
    additions term at all, so a lease added mid-model raised a liability
    against no asset. Measured on Falls City with 40,000 added at Q6: the
    liability ended at 40,000 and the asset at 0.
    """
    rows = self._debt_rows()
    ws = self._debt_sheet()
    close_row = rows["Right-of-Use Asset Closing"]
    opening, adds = rows["Right-of-Use Asset Opening"], rows["Lease Additions (asset)"]
    dep = rows["Lease Asset Depreciation"]
    for i in range(21):
      col = get_column_letter(3 + i)
      formula = ws.cell(close_row, 3 + i).value
      if not isinstance(formula, str):
        continue
      self.assertIn(f"+{col}{adds}", formula,
                    f"the asset closing balance does not ADD the additions row "
                    f"({col}{adds}) - a lease would create a liability with no "
                    f"asset: {formula!r}")
      self.assertIn(f"{col}{opening}", formula)
      self.assertIn(f"{col}{dep}", formula)

  def test_the_lease_is_entered_once_and_feeds_both_sides(self):
    """The asset block is not a second place to type.

    Both roll-forwards read the SAME input row, so the liability and the asset
    cannot drift apart - which is the whole reason the client never touches
    the asset block.
    """
    rows = self._debt_rows()
    ws = self._debt_sheet()
    source = rows["Lease Net Additions"]
    for key in ("Lease Additions (asset)", "Lease Additions (liability)"):
      mirror = rows[key]
      for i in range(21):
        col = get_column_letter(3 + i)
        formula = ws.cell(mirror, 3 + i).value
        self.assertEqual(
          formula, f"={col}{source}",
          f"{key} is not a straight link to the single additions input "
          f"({col}{source}) - two places to type is two numbers that disagree")

  def test_no_python_seed_literal_survives_in_the_generator(self):
    self.assertNotIn(
      "lease_seed_value = number(schedules.get(",
      self._src,
      "lease_seed_value local should be removed",
    )


def _latest_express_workbook() -> Path | None:
  base = Path("C:/dev/Cilient Plans")
  if not base.exists():
    return None
  matches = sorted(
    base.glob("ExpressLogix Shipping Services -- *.xlsx"),
    key=lambda p: p.stat().st_mtime,
    reverse=True,
  )
  return matches[0] if matches else None


class WorkbookLeaseFormulaOutputTests(unittest.TestCase):
  """If a recent ExpressLogix workbook exists AND was generated
  after the schedule_sheets.py source, load it and verify the
  Excel formulas use the cell-reference pattern."""

  def setUp(self) -> None:
    self._workbook_path = _latest_express_workbook()
    if self._workbook_path is None:
      self.skipTest("No ExpressLogix workbook present on disk")
    wb_mtime = self._workbook_path.stat().st_mtime
    src_mtime = _SCHEDULE_SHEETS_PATH.stat().st_mtime
    if wb_mtime < src_mtime:
      self.skipTest(
        f"Latest workbook {self._workbook_path.name} is older than "
        "schedule_sheets.py source; rerun an E2E to regenerate before this check is meaningful."
      )

  def test_lease_interest_formula_references_interest_rate_cell(self) -> None:
    import openpyxl

    wb = openpyxl.load_workbook(str(self._workbook_path), data_only=False)
    debt = wb["Debt Schedule"]
    # Find rows for Lease Interest Expense and Interest Rate
    lease_int_row = ir_row = None
    for r in range(1, 60):
      label = debt.cell(row=r, column=1).value
      if label == "Lease Interest Expense":
        lease_int_row = r
      elif label == "Interest Rate":
        ir_row = r
    self.assertIsNotNone(lease_int_row, "Debt Schedule must have Lease Interest Expense row")
    self.assertIsNotNone(ir_row, "Debt Schedule must have Interest Rate row")
    # Q1 = column D. Formula should reference D<ir_row>.
    q1_formula = debt.cell(row=lease_int_row, column=4).value
    self.assertIsNotNone(q1_formula, "Lease Interest Q1 cell should not be None/blank")
    expected_ref = f"D{ir_row}"
    self.assertIn(
      expected_ref, str(q1_formula),
      f"Lease Interest Q1 formula must reference {expected_ref} (Interest Rate Q1). Got: {q1_formula!r}",
    )
    # Confirm there's NO bare numeric literal (other than the rate cell ref) — heuristic
    self.assertNotRegex(
      str(q1_formula), r"\*\s*0\.\d+",
      f"Lease Interest Q1 formula should not contain a bare *0.XX numeric literal. Got: {q1_formula!r}",
    )

  def test_lease_asset_depreciation_formula_references_lease_opening_q0_cell(self) -> None:
    import openpyxl

    wb = openpyxl.load_workbook(str(self._workbook_path), data_only=False)
    debt = wb["Debt Schedule"]
    lease_dep_row = lease_open_row = None
    for r in range(1, 60):
      label = debt.cell(row=r, column=1).value
      if label == "Lease Asset Depreciation":
        lease_dep_row = r
      elif label == "Lease Opening Balance":
        lease_open_row = r
    self.assertIsNotNone(lease_dep_row, "Debt Schedule must have Lease Asset Depreciation row")
    self.assertIsNotNone(lease_open_row, "Debt Schedule must have Lease Opening Balance row")
    # Q0 = column C. Formula should reference C<lease_open_row>.
    q1_formula = debt.cell(row=lease_dep_row, column=4).value
    self.assertIsNotNone(q1_formula, "Lease Asset Depreciation Q1 cell should not be None")
    expected_ref = f"C{lease_open_row}"
    self.assertIn(
      expected_ref, str(q1_formula),
      f"Lease Asset Depreciation Q1 formula must reference {expected_ref} (Lease Opening Balance Q0). Got: {q1_formula!r}",
    )
    # Confirm there's no bare integer literal followed by /20 (the old pattern)
    self.assertNotRegex(
      str(q1_formula), r"\(\d{2,}/20\)",
      f"Lease Asset Depreciation Q1 formula should not contain a (NNNNN/20) literal. Got: {q1_formula!r}",
    )


class WorkbookModelStatusFailFastTests(unittest.TestCase):
  """Unit tests for assert_workbook_model_status_ok using a
  synthetic minimal workbook (no Excel recalc required since we
  pre-populate the Checks!B2 value)."""

  def _make_workbook(self, model_status_value, tmp_path: Path) -> Path:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Checks"
    ws.cell(row=2, column=1, value="Model Status")
    ws.cell(row=2, column=2, value=model_status_value)
    out = tmp_path / "synthetic_workbook.xlsx"
    wb.save(str(out))
    return out

  def setUp(self) -> None:
    self._tmp_dir = Path(_REPO_ROOT / "tmp" / "p3_20_model_status_tests")
    self._tmp_dir.mkdir(parents=True, exist_ok=True)

  def _patch_recalc_to_noop(self):
    # Monkey-patch the recalc helper to return success without
    # actually opening Excel; the test workbooks are pre-populated.
    from client_intake_and_finmo.post_intake_runtime_validation import (  # type: ignore
      workbook_model_status as wms,
    )
    wms._recalc_workbook_via_excel_com = lambda _path: None
    return wms

  def test_status_ok_passes_silently(self) -> None:
    wms = self._patch_recalc_to_noop()
    wb_path = self._make_workbook("OK", self._tmp_dir)
    # Should not raise
    wms.assert_workbook_model_status_ok(str(wb_path))

  def test_status_fail_raises(self) -> None:
    from client_intake_and_finmo.fail_fast.common import PostIntakePreconditionFailed  # type: ignore
    wms = self._patch_recalc_to_noop()
    wb_path = self._make_workbook("FAIL", self._tmp_dir)
    with self.assertRaises(PostIntakePreconditionFailed) as ctx:
      wms.assert_workbook_model_status_ok(str(wb_path))
    err = ctx.exception
    self.assertEqual(err.operation, "workbook_model_status_fail")
    self.assertEqual(err.actual, "FAIL")
    self.assertIn("app", err.details.get("guidance", "").lower())

  def test_status_warn_also_raises(self) -> None:
    """Anything other than the exact string 'OK' must fail."""
    from client_intake_and_finmo.fail_fast.common import PostIntakePreconditionFailed  # type: ignore
    wms = self._patch_recalc_to_noop()
    wb_path = self._make_workbook("WARN", self._tmp_dir)
    with self.assertRaises(PostIntakePreconditionFailed):
      wms.assert_workbook_model_status_ok(str(wb_path))

  def test_status_none_raises(self) -> None:
    """An empty Checks!B2 (None) should still fail since it's not 'OK'."""
    from client_intake_and_finmo.fail_fast.common import PostIntakePreconditionFailed  # type: ignore
    wms = self._patch_recalc_to_noop()
    wb_path = self._make_workbook(None, self._tmp_dir)
    with self.assertRaises(PostIntakePreconditionFailed):
      wms.assert_workbook_model_status_ok(str(wb_path))

  def test_missing_workbook_raises_precondition(self) -> None:
    from client_intake_and_finmo.fail_fast.common import PostIntakePreconditionFailed  # type: ignore
    from client_intake_and_finmo.post_intake_runtime_validation import (  # type: ignore
      workbook_model_status as wms,
    )
    bogus = self._tmp_dir / "definitely_not_present.xlsx"
    if bogus.exists():
      bogus.unlink()
    with self.assertRaises(PostIntakePreconditionFailed) as ctx:
      wms.assert_workbook_model_status_ok(str(bogus))
    self.assertEqual(ctx.exception.operation, "workbook_model_status_workbook_missing")


if __name__ == "__main__":
  unittest.main()
