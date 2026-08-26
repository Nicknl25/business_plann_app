"""The payroll chain lands on the engine's grid - the third time the ROUND guard earned itself.

Payroll Schedule part 2 (Nick, 2026-08-25). Starting FTE is chained to the
prior quarter's Ending FTE, Annual Wage and Benefits % to the prior quarter's
value with the engine's own delta at a bump. The engine authors FTE and hires
on a 2-dp grid (post_intake_headcount/schedule.py: round(..., 2)); in IEEE
doubles 6.06 + 0.35 is 6.409999999999999, and a bare chain carried that crumb
through Ending, Average, Wage Cost and the P&L - 28 detail cells and 116 FINMO
cells on Halbrook in the prototype. ROUND(prior Ending FTE, 6) lands it, the
same guard as the Debt Schedule payoff (test_cw043_payoff_residue) and the
equity chain. Pinned here rather than remembered.

Two layers:
  1. Offline, on Halbrook's real stored export row: the builder emits ROUND on
     every chained Starting FTE, and the exact emitted chain evaluated in
     doubles reproduces the engine's series bit for bit - while the bare
     chain (the control) does NOT on the class's own shape.
  2. With Excel: the recalculated schedule equals the engine's series bit for
     bit on every chained cell (skips, never passes, without Excel).
"""
from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for path in (ROOT, os.path.join(ROOT, "python")):
  if path not in sys.path:
    sys.path.insert(0, path)

FIXTURE = os.path.join(HERE, "fixtures", "cw043_halbrook_export_row.json.gz")
FIRST_DETAIL_ROW = 27


def _fixture():
  with gzip.open(FIXTURE, "rt", encoding="utf-8") as fh:
    return json.load(fh)


def _payroll_rows(fx):
  return [x for x in json.loads(fx["row"]["payroll_headcount"]).get("rows") or []
          if isinstance(x, dict)]


def _build_workbook(fx, out_dir):
  from client_statements_output_excel.export_client_workbook import export_workbook_for_row
  row = dict(fx["row"])
  row["business_name"] = "CW043 payroll chain probe"
  return export_workbook_for_row(row, output_dir=out_dir, run_diagnostics=fx.get("run_diagnostics"))


class TheChainIsOnTheGridTests(unittest.TestCase):
  """Offline - the builder's emitted formulas, evaluated exactly."""

  @classmethod
  def setUpClass(cls):
    import openpyxl
    cls.fx = _fixture()
    cls.tmp = tempfile.mkdtemp(prefix="cw043_payroll_chain_")
    path = _build_workbook(cls.fx, cls.tmp)
    cls.ws = openpyxl.load_workbook(str(path))["Payroll Schedule"]
    cls.rows = _payroll_rows(cls.fx)

  @classmethod
  def tearDownClass(cls):
    shutil.rmtree(cls.tmp, ignore_errors=True)

  def _cell(self, r, c):
    return self.ws.cell(FIRST_DETAIL_ROW + r, c).value

  def test_every_chained_starting_fte_is_rounded_to_the_grid(self):
    chained = [self._cell(i, 5) for i in range(len(self.rows))
               if isinstance(self._cell(i, 5), str)]
    self.assertTrue(chained, "no chained Starting FTE cells - the chain is not built")
    bad = [f for f in chained if not re.fullmatch(r"=ROUND\(G\d+,6\)", f)]
    self.assertFalse(bad, f"Starting FTE chained without the 6-dp grid: {bad[:5]}")

  def test_the_emitted_chain_reproduces_the_engine_bit_for_bit(self):
    """Evaluate the emitted formulas in doubles: ROUND(prior Ending,6);
    prev or ROUND(prev +/- delta, 6); Ending = Starting + Hires."""
    got = {}
    misses = []
    for i, item in enumerate(self.rows):
      r = FIRST_DETAIL_ROW + i
      for col, key in ((5, "starting_fte"), (9, "annual_wage"), (10, "payroll_taxes_benefits_percent")):
        v = self._cell(i, col)
        engine = float(item.get(key) or 0.0)
        if isinstance(v, str):
          m = re.fullmatch(r"=ROUND\(([A-Z])(\d+)([+-][0-9.eE+-]+)?,6\)|=([A-Z])(\d+)", v)
          self.assertIsNotNone(m, f"unexpected formula shape at row {r} col {col}: {v}")
          if m.group(1):
            ref_col, ref_row, delta = m.group(1), int(m.group(2)), m.group(3)
            base = got[(ref_row, ref_col)]
            val = round(base + float(delta), 6) if delta else round(base, 6)
          else:
            val = got[(int(m.group(5)), m.group(4))]
        else:
          val = float(v or 0.0)
        got[(r, {5: "E", 9: "I", 10: "J"}[col])] = val
        if val != engine:
          misses.append((r, key, engine, val))
      hires = float(self._cell(i, 6) or 0.0)
      got[(r, "G")] = got[(r, "E")] + hires
    self.assertFalse(misses, f"chain != engine: {misses[:6]}")

  def test_the_bare_chain_is_the_class_this_guard_exists_for(self):
    """CONTROL: prior Ending without the grid drifts off the engine's 2-dp
    values on this very fixture - which is why the ROUND is not optional."""
    prior = {}
    drift = 0
    for item in self.rows:
      key = (str(item.get("staffing_class") or ""), str(item.get("position_title") or item.get("person_name") or ""))
      q = int(item.get("quarter_index") or 0)
      s = float(item.get("starting_fte") or 0.0)
      h = float(item.get("hires") or 0.0)
      p = prior.get(key)
      if p and p[0] == q - 1 and p[1] != s:
        drift += 1
      prior[key] = (q, (p[1] if p and p[0] == q - 1 else s) + h)
    self.assertGreater(drift, 0, "fixture no longer exercises the 2-dp grid class - pick a draft that does")


def _excel_available() -> bool:
  try:
    import win32com.client as win32
    x = win32.gencache.EnsureDispatch("Excel.Application")
    x.Quit()
    return True
  except Exception:
    return False


@unittest.skipUnless(_excel_available(), "Excel is required to evaluate the workbook's formulas")
class TheRecalculatedChainEqualsTheEngineTests(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
    import openpyxl
    import win32com.client as win32
    cls.fx = _fixture()
    cls.tmp = tempfile.mkdtemp(prefix="cw043_payroll_chain_xl_")
    path = str(_build_workbook(cls.fx, cls.tmp))
    x = win32.gencache.EnsureDispatch("Excel.Application")
    x.Visible = False
    x.DisplayAlerts = False
    wb = x.Workbooks.Open(path)
    for _ in range(20):
      try:
        wb.Sheets(1).Name
        break
      except Exception:
        time.sleep(1.5)
    x.CalculateFullRebuild()
    wb.Save()
    wb.Close(False)
    x.Quit()
    cls.ws = openpyxl.load_workbook(path, data_only=True)["Payroll Schedule"]
    cls.rows = _payroll_rows(cls.fx)

  @classmethod
  def tearDownClass(cls):
    shutil.rmtree(cls.tmp, ignore_errors=True)

  def test_recalculated_inputs_equal_the_engine_bit_for_bit(self):
    misses = []
    for i, item in enumerate(self.rows):
      r = FIRST_DETAIL_ROW + i
      for col, key in ((5, "starting_fte"), (9, "annual_wage"), (10, "payroll_taxes_benefits_percent")):
        got = float(self.ws.cell(r, col).value or 0.0)
        engine = float(item.get(key) or 0.0)
        if got != engine:
          misses.append((r, key, engine, got))
    self.assertFalse(misses, f"Excel chain != engine: {misses[:6]}")


if __name__ == "__main__":
  unittest.main()
