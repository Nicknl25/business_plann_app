"""R49 — the workbook TEXT-SURFACE pin, and the proof that it bites.

A golden master that cannot go red is a golden master that lies. R49 exists
because the Valuation "As of" header moved from column E to column L inside a
commit whose formula golden was re-blessed, and nothing in the gate could have
seen it: R32 hashes formulas, and a header is not a formula.

So the tests that matter here are the NEGATIVE controls. Each one injects a
real failure into a real built workbook and asserts the surface notices:

  MOVED     the exact failure that created the leg - same text, new address;
  CHANGED   a label reworded in place;
  GARBLED   mojibake, the way a UTF-8 string mangled through cp1252 arrives;
  DELETED   a label that simply vanishes.

And one control in the other direction, which is the point of Nick's ruling
that this be SEPARATE from R32: a formula-only edit must NOT move the text
digest, or every math change would churn the text golden and nobody would read
it before blessing.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (REPO, os.path.join(REPO, "python"), os.path.join(REPO, "tests")):
  if path not in sys.path:
    sys.path.insert(0, path)

from _p3_40_contract_2_fixtures import valid_workbook_payload_dict  # noqa: E402
from client_statements_output_excel.data import DraftWorkbookData  # noqa: E402
from client_statements_output_excel.workbook_builder import (  # noqa: E402
  build_client_financial_model_workbook,
)


def _workbook(business_name="Fixture Co", city="Madison"):
  payload = valid_workbook_payload_dict()
  return build_client_financial_model_workbook(DraftWorkbookData(
    draft_row={"business_name": business_name, "address_city": city, "address_state": "WI"},
    model_input_json=payload.get("model_input_json") or {},
    finmo_json=payload.get("finmo_json") or {},
    payroll_headcount=payload.get("payroll_headcount") or {},
    debt_schedule=payload.get("debt_schedule") or {},
    planning_run_json=payload.get("planning_run_json") or {},
    run_diagnostics=payload.get("run_diagnostics"),
  ))


def _text_cells(wb):
  """The same extraction the gate surface performs, over one workbook."""
  out = {}
  for ws in wb.worksheets:
    cells = {}
    for row in ws.iter_rows():
      for cell in row:
        val = cell.value
        if not isinstance(val, str):
          continue
        val = val.strip()
        if not val or val.startswith("="):
          continue
        cells[cell.coordinate] = val
    if cells:
      out[ws.title] = cells
  return out


def _digest(surface):
  return hashlib.sha256(json.dumps(
    surface, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class TextSurfaceStaticnessTests(unittest.TestCase):
  """What gets pinned must be structure, never the client's own data."""

  @classmethod
  def setUpClass(cls):
    a = _text_cells(_workbook("Fixture Co", "Madison"))
    b = _text_cells(_workbook("Thistledown Cycles", "Burlington"))
    cls.static = {
      sheet: {addr: txt for addr, txt in a[sheet].items() if b.get(sheet, {}).get(addr) == txt}
      for sheet in set(a) & set(b)
    }
    cls.flat = {t for cells in cls.static.values() for t in cells.values()}

  def test_the_business_name_is_never_pinned(self):
    """A golden master carrying a client's name is a golden master that goes
    red for the next client."""
    for probe in ("Fixture Co", "Thistledown", "Madison", "Burlington"):
      self.assertFalse(any(probe in t for t in self.flat),
                       f"{probe!r} survived into the static surface")

  def test_the_structure_is_pinned(self):
    """The other half: dropping the per-business text must not drop the chrome."""
    self.assertGreater(sum(len(c) for c in self.static.values()), 400)
    self.assertIn("Valuation", self.static)
    self.assertIn("As of", self.static["Valuation"].values())


class TextSurfaceNegativeControlTests(unittest.TestCase):
  """Each injects a real defect and asserts the digest moves."""

  def setUp(self):
    self.wb = _workbook()
    self.base = _text_cells(self.wb)
    self.base_digest = _digest(self.base)

  def _address_of(self, sheet, text):
    for addr, txt in self.base[sheet].items():
      if txt == text:
        return addr
    self.fail(f"{text!r} not found on {sheet}")

  def test_a_moved_label_is_caught(self):
    """THE failure that created this leg: same words, different cell."""
    ws = self.wb["Valuation"]
    addr = self._address_of("Valuation", "As of")
    ws[addr] = None
    ws["E5"] = "As of"
    self.assertNotEqual(_digest(_text_cells(self.wb)), self.base_digest,
                        "a header moving between columns left the digest identical - "
                        "this is exactly the As-of move that no golden master caught")

  def test_a_reworded_label_is_caught(self):
    ws = self.wb["Valuation"]
    ws[self._address_of("Valuation", "Enterprise value")] = "Enterprise Value"
    self.assertNotEqual(_digest(_text_cells(self.wb)), self.base_digest,
                        "a label reworded in place left the digest identical")

  def test_mojibake_is_caught(self):
    """How a UTF-8 en-dash arrives after a trip through cp1252. The workbook
    has shipped mojibake before; it must not be able to ship silently."""
    ws = self.wb["Valuation"]
    addr = self._address_of("Valuation", "Enterprise value")
    ws[addr] = "Enterprise valueâ€”"
    self.assertNotEqual(_digest(_text_cells(self.wb)), self.base_digest,
                        "a garbled label left the digest identical")

  def test_a_deleted_label_is_caught(self):
    ws = self.wb["Valuation"]
    ws[self._address_of("Valuation", "Enterprise value")] = None
    self.assertNotEqual(_digest(_text_cells(self.wb)), self.base_digest,
                        "a label vanishing left the digest identical")

  def test_a_formula_only_change_does_NOT_move_the_text_digest(self):
    """Nick's ruling made concrete. If the math surface bled into the text
    surface, every formula edit would churn this golden and nobody would read
    it before blessing - which is how a pin stops being a pin."""
    ws = self.wb["Valuation"]
    changed = 0
    for row in ws.iter_rows():
      for cell in row:
        if isinstance(cell.value, str) and cell.value.startswith("="):
          cell.value = cell.value + "+0"
          changed += 1
          if changed >= 5:
            break
      if changed >= 5:
        break
    self.assertGreaterEqual(changed, 5, "no formulas found to perturb")
    self.assertEqual(_digest(_text_cells(self.wb)), self.base_digest,
                     "editing formulas moved the TEXT digest - the two surfaces "
                     "are supposed to be independent")


if __name__ == "__main__":
  unittest.main()
