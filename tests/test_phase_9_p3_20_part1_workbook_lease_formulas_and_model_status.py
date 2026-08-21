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
    """Every Debt Schedule row label mapped to its row number."""
    ws = self._debt_sheet()
    return {str(ws.cell(r, 1).value or "").strip(): r
            for r in range(1, ws.max_row + 1)
            if str(ws.cell(r, 1).value or "").strip()}

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
    type(self)._SHEET = wb["Debt Schedule"]
    return type(self)._SHEET

  def test_lease_interest_formula_uses_cell_reference(self) -> None:
    # The lease interest write should reference local_ref(interest_rate, col)
    # (matching the debt interest formula pattern).
    pattern = re.compile(
      r"ws\.cell\(lease_interest,\s*col,\s*value=0 if idx == 0 else\s*(f\"[^\"]+\")"
    )
    matches = pattern.findall(self._src)
    self.assertEqual(len(matches), 1, "Expected exactly one lease interest write")
    formula_template = matches[0]
    self.assertIn(
      "local_ref(interest_rate, col)",
      formula_template,
      "Lease interest formula must reference the Interest Rate cell (local_ref(interest_rate, col)), not a Python literal",
    )
    self.assertNotIn(
      "rate_cell_value",
      formula_template,
      "Lease interest formula must not interpolate the rate_cell_value literal",
    )

  def test_lease_asset_depreciation_formula_uses_cell_reference(self) -> None:
    """The seed must be a CELL, never a Python literal baked into the string.

    This used to assert the formula's exact source text, which made it a guard
    on one spelling rather than on the property. R-DEBT-02 moved the anchor off
    the stub column (now hidden) onto the first LIVE quarter's right-of-use
    opening, and turned the hard-coded 20 into a "Lease Life in quarters" row -
    both of which the property survives and the string did not. Asserted
    against the BUILT sheet now, so it holds however the formula is spelled.
    """
    rows = self._debt_rows()
    dep = self._row_formulas(rows, "Lease Asset Depreciation")
    live = [f for f in dep[1:] if isinstance(f, str)]
    self.assertTrue(live, "no depreciation formulas were built")
    # The first attempt at this test asserted "no 4-digit literal", which the
    # gate fixture cannot fail: its lease seed is 0, so baking the seed in
    # produced "(0/D24)" and the test stayed green through the tamper. Assert
    # the STRUCTURE instead - the two rows the formula must read.
    rou = rows["Right-of-Use Asset Opening"]
    life = rows["Lease Life in quarters"]
    for formula in live:
      # ABSOLUTE, and that precision is the point. A relaxed "mentions row 27"
      # is satisfied by the MIN's second argument - the cap - so baking the
      # seed into the numerator still passed: =MIN((0/D24),D27). The BASE is
      # the anchored $D$27; the cap is the relative D27. Assert the anchor.
      self.assertRegex(
        formula, rf"\$[A-Z]{{1,2}}\${rou}(?![0-9])",
        f"the depreciation BASE is not the anchored Right-of-Use Asset Opening "
        f"cell (row {rou}) - a seed has been baked into the numerator, which "
        f"the row-{rou} cap would otherwise disguise: {formula!r}")
      self.assertRegex(
        formula, rf"\$?[A-Z]{{1,2}}\$?{life}(?![0-9])",
        f"depreciation does not read the Lease Life row ({life}) - the life is "
        f"hard-coded again: {formula!r}")

  def test_lease_additions_reach_the_right_of_use_asset(self):
    """A capital lease creates an asset and a liability together.

    Right-of-Use Asset Closing was opening MINUS depreciation, with no
    additions term, while Lease Closing Balance was opening PLUS additions
    minus principal. So a lease added mid-model raised a liability against no
    asset at all. Measured on Falls City with one 40,000 lease added at Q6:
    the liability ended at 40,000 and the asset at 0.

    Nick's ruling, 2026-08-21: there is no version where one arrives without
    the other. Zero exposure today does not change it.
    """
    rows = self._debt_rows()
    close = self._row_formulas(rows, "Right-of-Use Asset Closing")
    adds = rows["Lease Net Additions"]
    live = [f for f in close if isinstance(f, str)]
    self.assertTrue(live, "no right-of-use closing formulas were built")
    for formula in live:
      self.assertRegex(
        formula, rf"\+\$?[A-Z]{{1,2}}\$?{adds}(?![0-9])",
        f"the right-of-use asset does not ADD the Lease Net Additions row "
        f"({adds}) - a lease would create a liability with no asset: "
        f"{formula!r}")

  def test_depreciation_base_includes_additions_already_on_the_books(self):
    """The companion half. Additions reaching the asset without reaching the
    depreciation base would strand them on the balance sheet forever - the
    opposite error, arrived at from the other side."""
    rows = self._debt_rows()
    dep = self._row_formulas(rows, "Lease Asset Depreciation")
    adds = rows["Lease Net Additions"]
    # quarter 1 has no prior additions, so the base is the seed alone; every
    # later quarter must sum what has landed since
    later = [f for f in dep[2:] if isinstance(f, str)]
    self.assertTrue(later, "no later-quarter depreciation formulas were built")
    for formula in later:
      self.assertIn(
        "SUM(", formula,
        f"depreciation does not accumulate lease additions: {formula!r}")
      self.assertRegex(
        formula, rf"SUM\(\$?[A-Z]{{1,2}}\$?{adds}(?![0-9])",
        f"depreciation's SUM does not run over the Lease Net Additions row "
        f"({adds}): {formula!r}")

    # The old literal should NOT be present in the generator anymore
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
