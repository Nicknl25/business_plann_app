"""Issue 138's artifact probe, applicability gate (Nick, 2026-09-10).

"Both halves of issue 138's artifact probe need the same applicability
rule - one line means not_applicable, the way the ops half already
handles it. A check that fails on every single-line business is noise,
and noise teaches everyone to skip the report."

Live evidence: the probe re-filed the same false reopen on every
single-line acceptance run (Bramblewood d8cdfd1e and 2f71e20d, occ 717+),
its workbook half failing "Model Inputs carries 0 per-line COGS driver
row(s), expected >= 2" on a business with ONE product row - where the
blended model is the designed layout.

Pinned: applicability comes from the DRAFT's line count for BOTH halves;
a multi-line draft still reaches the workbook checks (the real defect -
a two-line business whose workbook lacks the breakout - stays caught).
"""
from __future__ import annotations

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo.issue_registry import (  # noqa: E402
  _assert_ops_per_line_cogs,
  _assert_workbook_cogs_rows,
)


class _FakeCur:
  """Serves operating_model_json for _load_ops_model; explodes if the
  check reaches any other query (the gate must answer first)."""

  def __init__(self, ops):
    self._ops = ops
    self._pending = None

  def execute(self, sql, params=None):
    if "operating_model_json" in sql:
      self._pending = (json.dumps(self._ops),) if self._ops is not None else None
    else:
      raise AssertionError(f"unexpected query past the gate: {sql[:80]}")

  def fetchone(self):
    return self._pending


def _ops(n_products):
  return {"lob_models": [{"lob_name": "Primary", "products": [
    {"product_name": f"line {i}", "cogs_percent_of_line_revenue": None}
    for i in range(n_products)
  ]}]}


class Issue138ApplicabilityGateTests(unittest.TestCase):
  def test_workbook_half_single_line_is_not_applicable(self):
    """The fix: one product row -> not_applicable BEFORE any workbook or
    delivery-record lookup (the fake cursor forbids further queries)."""
    out = _assert_workbook_cogs_rows(_FakeCur(_ops(1)), "d" * 32, {})
    self.assertEqual(out["verdict"], "not_applicable")
    self.assertIn("min_lines=2", out["detail"])
    self.assertIn("single-line", out["detail"])

  def test_workbook_half_zero_lines_is_not_applicable(self):
    out = _assert_workbook_cogs_rows(_FakeCur(_ops(0)), "d" * 32, {})
    self.assertEqual(out["verdict"], "not_applicable")

  def test_workbook_half_missing_ops_is_not_applicable(self):
    out = _assert_workbook_cogs_rows(_FakeCur(None), "d" * 32, {})
    self.assertEqual(out["verdict"], "not_applicable")

  def test_workbook_half_two_lines_passes_the_gate(self):
    """A two-line draft must reach the workbook resolution - the real
    defect class stays checkable. With no delivery record the verdict is
    workbook-side not_applicable, but the GATE's detail must not appear."""
    class _Cur(_FakeCur):
      def execute(self, sql, params=None):
        if "operating_model_json" in sql:
          self._pending = (json.dumps(self._ops),)
        else:
          # workbook_delivery_record lookups run past the gate: fine.
          self._pending = None

    out = _assert_workbook_cogs_rows(_Cur(_ops(2)), "d" * 32, {})
    self.assertNotIn("single-line", str(out.get("detail") or ""))

  def test_both_halves_share_the_rule_on_one_line(self):
    ops_out = _assert_ops_per_line_cogs(_FakeCur(_ops(1)), "d" * 32, {})
    wb_out = _assert_workbook_cogs_rows(_FakeCur(_ops(1)), "d" * 32, {})
    self.assertEqual(ops_out["verdict"], "not_applicable")
    self.assertEqual(wb_out["verdict"], "not_applicable")


if __name__ == "__main__":
  unittest.main()
