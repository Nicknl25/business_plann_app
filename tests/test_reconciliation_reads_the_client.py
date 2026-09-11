"""The payroll reconciliation compares the client's number to the
author's roster - and runs whether or not a rest-of-team pool was stated
(Nick 2026-09-10/11).

Last night's gate read the anchor's own `named + rest_of_team`, which
only exists when a pool was stated. Two consequences:

1. BLIND WITHOUT A POOL. A client who said "just us" and had staff
   authored onto them (Bramblewood 2f71e20d: 744,640 authored against
   454,000 stated, 1.64x) or who was never asked (Ferriday & Blythe
   73a71cfe: two vets recorded against a $3.1M practice) got no
   reconciliation at all - the anchor returns None and the gate stood
   aside.
2. AN IDENTITY, NOT A FACT. Ruling: "the reconciliation compares two
   independently sourced numbers instead of an identity". The stated side
   is now the payroll the intake RECORDED (financials current_payroll),
   the authored side is the capacity author's Q1 roster.

Structural half: every caller of the payload builder passes
financials_json - read from the source, so a new caller that forgets it
fails here rather than silently reconciling against nothing.
"""
from __future__ import annotations

import ast
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo.post_intake_headcount import schedule as S  # noqa: E402


def _row(wage, fte=1.0, cls="key_person", q=1):
  return {"quarter_index": q, "staffing_class": cls, "annual_wage": wage,
          "ending_fte": fte, "starting_fte": fte}


BRAMBLEWOOD_NAMED = [_row(154000), _row(150000), _row(150000)]  # 454,000
BRAMBLEWOOD_INVENTED = [_row(96880, 3.0, "supporting_staff")]    # +290,640


class NoPoolStillReconcilesTests(unittest.TestCase):
  def test_just_us_plus_invented_staff_fails(self):
    """THE BRAMBLEWOOD SHAPE: no pool (anchor None), client's recorded
    payroll 454,000, author added three FTE. Must stop and say so."""
    payload = {"rows": BRAMBLEWOOD_NAMED + BRAMBLEWOOD_INVENTED}
    with self.assertRaises(Exception) as cm:
      S._stamp_stated_payroll_reconciliation(
        payload, None, financials_json={"current_payroll": 454000})
    self.assertIn("payroll_authored_off_stated_payroll",
                  repr(cm.exception) + str(cm.exception))

  def test_just_us_with_no_invented_staff_passes_and_is_stamped(self):
    payload = {"rows": list(BRAMBLEWOOD_NAMED)}
    S._stamp_stated_payroll_reconciliation(
      payload, None, financials_json={"current_payroll": 454000})
    rec = payload["stated_payroll_reconciliation"]
    self.assertTrue(rec["reconciled"])
    self.assertEqual(rec["stated_source"], "financials.current_payroll")
    self.assertIsNone(rec["anchor_disposition"])

  def test_payroll_total_year1_is_the_second_source(self):
    payload = {"rows": list(BRAMBLEWOOD_NAMED)}
    S._stamp_stated_payroll_reconciliation(
      payload, None, financials_json={"payroll_total_year1": 454000})
    self.assertEqual(payload["stated_payroll_reconciliation"]["stated_source"],
                     "financials.payroll_total_year1")


class StatedSideIsTheClientTests(unittest.TestCase):
  def test_recorded_payroll_wins_over_the_anchor_sum(self):
    """When both exist, the client's recorded number is the stated side -
    the anchor's arithmetic is only a fallback."""
    payload = {"rows": [_row(201000), _row(62250, 4.0, "supporting_staff")]}
    S._stamp_stated_payroll_reconciliation(
      payload, {"stated_total_payroll": 999999.0,
                "anchor_disposition": "launch_in_band"},
      financials_json={"current_payroll": 450000})
    rec = payload["stated_payroll_reconciliation"]
    self.assertEqual(rec["stated_total_payroll"], 450000.0)
    self.assertEqual(rec["stated_source"], "financials.current_payroll")

  def test_anchor_is_the_fallback_when_nothing_was_recorded(self):
    payload = {"rows": [_row(201000), _row(62250, 4.0, "supporting_staff")]}
    S._stamp_stated_payroll_reconciliation(
      payload, {"stated_total_payroll": 450000.0,
                "anchor_disposition": "launch_in_band"},
      financials_json={})
    self.assertEqual(payload["stated_payroll_reconciliation"]["stated_source"],
                     "anchor.stated_total_payroll")

  def test_nothing_recorded_anywhere_stands_aside(self):
    payload = {"rows": list(BRAMBLEWOOD_NAMED)}
    S._stamp_stated_payroll_reconciliation(payload, None, financials_json={})
    self.assertNotIn("stated_payroll_reconciliation", payload)


class EveryBuilderCallPassesTheClientNumberTests(unittest.TestCase):
  """Read from the SOURCE: every call of the payroll payload builder
  passes financials_json. This is how 'I found them all' is checked
  rather than asserted - a new caller that omits it fails here."""

  CALLERS = [
    "python/client_intake_and_finmo/post_intake_headcount/schedule.py",
    "python/client_intake_and_finmo/post_intake_headcount/feasibility_repair.py",
    "python/client_intake_and_finmo/post_intake_amalgamated/tools/set_payroll_schedule.py",
  ]
  NAMES = {"build_payroll_headcount_payload_from_contract",
           "_build_payroll_headcount_payload_from_contract", "builder"}

  def test_every_call_passes_financials_json(self):
    seen = 0
    for rel in self.CALLERS:
      tree = ast.parse(open(os.path.join(ROOT, rel), encoding="utf-8").read())
      for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
          continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else (
          fn.attr if isinstance(fn, ast.Attribute) else None)
        if name not in self.NAMES:
          continue
        kws = {k.arg for k in node.keywords}
        if "payroll_headcount_contract" not in kws and not node.args:
          continue  # not a payload-builder call
        seen += 1
        self.assertIn("financials_json", kws,
                      "%s:%d calls %s without financials_json"
                      % (rel, node.lineno, name))
    self.assertEqual(seen, 3, "expected exactly 3 builder calls, saw %d" % seen)

  def test_no_other_module_calls_the_builder(self):
    """Enumerate the whole package: the three files above are the only
    callers. A fourth caller must be added to CALLERS on purpose."""
    hits = []
    pkg = os.path.join(ROOT, "python")
    for dirpath, _dirs, files in os.walk(pkg):
      if "__pycache__" in dirpath:
        continue
      for fn in files:
        if not fn.endswith(".py"):
          continue
        path = os.path.join(dirpath, fn)
        src = open(path, encoding="utf-8", errors="replace").read()
        if "build_payroll_headcount_payload_from_contract(" in src:
          hits.append(os.path.relpath(path, ROOT).replace(os.sep, "/"))
    expected = {c for c in self.CALLERS if not c.endswith("set_payroll_schedule.py")}
    self.assertEqual(set(hits), expected)


if __name__ == "__main__":
  unittest.main()
