"""A period count follows its cadence; a count the cadence cannot hold is not a fact;
a default the app wrote is never held back as if she had said it.

CW-070 (Bellwether Ferments, draft 71d4e505, 2026-09-14). Turn 1 wrote the weekly default
of 52 working periods before she had said anything about rhythm. Turn 3 she said "monthly"
and the cadence moved; the app re-derived 12, and door C sent that to its model as a stated
fact with no origin, which judged it an overwrite and held the old 52 back. Nothing released
it. The store ended with monthly rows holding 52 periods and year-one holding 52 operating
months - and once her 800 jars a month landed, the plan sold 41,600 a year (Cowork 1224).

These pins state, for any cadence switch, any number of rows and any figures:
  - a default the normaliser writes is marked with the cadence it was written for;
  - when the cadence moves, a marked default moves with it; a figure someone stated drops the
    mark and stays;
  - a count its cadence cannot hold (more than 12 months, more than 53 weeks) is cleared;
  - door C treats a marked default as the app's own arithmetic - never reviewed, never held -
    and still reviews a period count nobody marked.
"""
from __future__ import annotations

import itertools
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))


def _norm(ops):
  from api_handlers.intake_consult import _normalize_ops_capacity_compat  # type: ignore
  return _normalize_ops_capacity_compat(ops)


def _rows(n, cadence, **extra):
  return {"lob_models": [{"lob_name": "Main", "products": [
    dict({"product_name": "Line %d" % i, "unit_cadence": cadence}, **extra) for i in range(n)]}]}


class APeriodCountFollowsItsCadence(unittest.TestCase):
  def test_a_default_is_marked_and_moves_with_the_cadence(self):
    for n, (first, second, want) in itertools.product((1, 2, 3), (("weekly", "monthly", 12), ("monthly", "weekly", 52),
                                                                  ("weekly", "annual", 1), ("annual", "monthly", 12))):
      ops = _norm(_rows(n, first))
      for p in ops["lob_models"][0]["products"]:
        self.assertEqual(p.get("_periods_default_for"), first, (n, first))
        p["unit_cadence"] = second
      ops = _norm(ops)
      for p in ops["lob_models"][0]["products"]:
        self.assertEqual(p.get("operating_periods_per_year"), want, (n, first, second))
        self.assertEqual(p.get("_periods_default_for"), second, (n, first, second))

  def test_a_stated_count_drops_the_mark_and_stays(self):
    for cadence, stated in (("weekly", 48), ("monthly", 10), ("weekly", 50)):
      ops = _norm(_rows(2, cadence))
      for p in ops["lob_models"][0]["products"]:
        p["operating_periods_per_year"] = stated
      ops = _norm(ops)
      for p in ops["lob_models"][0]["products"]:
        self.assertEqual(p.get("operating_periods_per_year"), stated, (cadence, stated))
        self.assertIsNone(p.get("_periods_default_for"), (cadence, stated))

  def test_a_count_the_cadence_cannot_hold_is_cleared(self):
    for cadence, bad, want in (("monthly", 52, 12), ("monthly", 13, 12), ("weekly", 365, 52)):
      ops = _norm(_rows(2, cadence, operating_periods_per_year=bad))
      for p in ops["lob_models"][0]["products"]:
        self.assertEqual(p.get("operating_periods_per_year"), want, (cadence, bad))
    kept = _norm(_rows(1, "contract", operating_periods_per_year=200))
    self.assertEqual(kept["lob_models"][0]["products"][0].get("operating_periods_per_year"), 200,
                     "a contract row's periods have no calendar bound")


class ARestatementKeepsTheMark(unittest.TestCase):
  """CW-070 clone e7120169: the consultant restated lob_models, the rebuilt rows lost
  the default's mark, and the 52 -> 12 move went to door C's model as an unmarked fact."""

  def test_the_mark_survives_a_restatement_and_still_moves_with_the_cadence(self):
    from api_handlers.intake_consult import _carry_forward_per_line_drivers  # type: ignore
    for n in (1, 2, 3):
      existing = _norm(_rows(n, "weekly"))["lob_models"]
      restated = [{"lob_name": "Main", "products": [{"product_name": "Line %d" % i, "unit_cadence": "monthly"}
                                                    for i in range(n)]}]
      carried = _carry_forward_per_line_drivers(existing=existing, incoming=restated)
      for p in carried[0]["products"]:
        self.assertEqual(p.get("_periods_default_for"), "weekly", n)
      out = _norm({"lob_models": carried})
      for p in out["lob_models"][0]["products"]:
        self.assertEqual((p.get("operating_periods_per_year"), p.get("_periods_default_for")), (12, "monthly"), n)


class DoorCNeverHoldsADefault(unittest.TestCase):
  def test_a_marked_default_is_app_arithmetic_and_an_unmarked_count_is_reviewed(self):
    from client_intake_and_finmo.intake_guard import door_c  # type: ignore
    for rows, (mark, to) in itertools.product((1, 2), (("monthly", 12.0), ("weekly", 52.0), ("annual", 1.0))):
      post = {"ops": _rows(rows, mark, operating_periods_per_year=to, _periods_default_for=mark)}
      changes = [{"path": "ops.lob_models[0].products[%d].operating_periods_per_year" % i, "from": 52.0, "to": to,
                  "verdict": "unreviewed"} for i in range(rows)]
      got = door_c.mark_cadence_defaults([dict(c) for c in changes], post)
      self.assertEqual([c["verdict"] for c in got], ["app_arithmetic"] * rows, (rows, mark))
    # no mark, or a value that is not the mark's default: still reviewed
    for post_row in ({"operating_periods_per_year": 12.0}, {"operating_periods_per_year": 10.0, "_periods_default_for": "monthly"}):
      post = {"ops": _rows(1, "monthly", **post_row)}
      c = [{"path": "ops.lob_models[0].products[0].operating_periods_per_year", "from": 52.0,
            "to": post_row["operating_periods_per_year"], "verdict": "unreviewed"}]
      self.assertEqual(door_c.mark_cadence_defaults(c, post)[0]["verdict"], "unreviewed", post_row)

  def test_review_applies_it_before_anything_is_sent_to_a_model(self):
    src = (ROOT / "python" / "client_intake_and_finmo" / "intake_guard" / "door_c.py").read_text(encoding="utf-8")
    body = src[src.index("def review("):]
    self.assertLess(body.index("mark_cadence_defaults("), body.index('unreviewed = [c for c in classified'))


class AnEmptyValueIsNotAWrite(unittest.TestCase):
  """CW-070 clone e7120169: the router emitted ops.geographic_coverage "" where nothing
  was stored; door C diffed it as a write, its model reviewed it, and the client was
  asked about it with her capacity sentence quoted. Absent, null and blank are one."""

  def test_blank_absent_and_null_never_differ(self):
    from client_intake_and_finmo.intake_guard import door_c  # type: ignore
    blanks = (None, "", "   ")
    for before, after in itertools.product(blanks, blanks):
      pre = {"ops": {} if before is None else {"geographic_coverage": before}}
      post = {"ops": {"geographic_coverage": after}}
      self.assertEqual([c for c in door_c.diff_sections(pre, post) if c["path"] == "ops.geographic_coverage"], [],
                       (before, after))
    for before, after in (("", "Tulsa metro"), (None, "Tulsa metro"), ("Tulsa metro", "")):
      got = [c for c in door_c.diff_sections({"ops": {"geographic_coverage": before}}, {"ops": {"geographic_coverage": after}})
             if c["path"] == "ops.geographic_coverage"]
      self.assertEqual(len(got), 1, (before, after))


if __name__ == "__main__":
  unittest.main(verbosity=2)
