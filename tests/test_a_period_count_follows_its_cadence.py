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
      # from a count the row CAN hold (11), so only the mark could make it arithmetic
      c = [{"path": "ops.lob_models[0].products[0].operating_periods_per_year", "from": 11.0,
            "to": post_row["operating_periods_per_year"], "verdict": "unreviewed"}]
      self.assertEqual(door_c.mark_cadence_defaults(c, post)[0]["verdict"], "unreviewed", post_row)

  def test_nothing_impossible_is_held_back(self):
    """CW-070 clone 703dd03f: a monthly row held 52; the turn wrote 12; door C questioned
    it and restored the 52 - a count the cadence cannot hold - until answered."""
    from client_intake_and_finmo.intake_guard import door_c  # type: ignore
    for cadence, frm, to, want in (("monthly", 52.0, 12.0, "app_arithmetic"), ("monthly", 52.0, 10.0, "app_arithmetic"),
                                   ("weekly", 365.0, 50.0, "app_arithmetic"), ("monthly", 10.0, 12.0, "unreviewed"),
                                   ("weekly", 48.0, 52.0, "unreviewed"), ("contract", 200.0, 12.0, "unreviewed")):
      post = {"ops": _rows(1, cadence, operating_periods_per_year=to)}
      c = [{"path": "ops.lob_models[0].products[0].operating_periods_per_year", "from": frm, "to": to, "verdict": "unreviewed"}]
      self.assertEqual(door_c.mark_cadence_defaults(c, post)[0]["verdict"], want, (cadence, frm, to))

  def test_review_applies_it_before_anything_is_sent_to_a_model(self):
    src = (ROOT / "python" / "client_intake_and_finmo" / "intake_guard" / "door_c.py").read_text(encoding="utf-8")
    body = src[src.index("def review("):]
    self.assertLess(body.index("mark_cadence_defaults("), body.index('unreviewed = [c for c in classified'))


class YearOnePersistsWhatTheRecalcChanged(unittest.TestCase):
  """CW-070 clone 7dd0a4e3: ops held 12 periods after her correction, the top-of-turn
  rebuild made year-one agree in memory, and on an ops turn nothing saved it - the store
  kept 52 months a year. The recalc persists what it changed, year-one included, on
  every turn, not only when a financials reply path saves it."""

  def test_the_turn_recalc_saves_a_changed_year_one(self):
    src = (ROOT / "python" / "api_handlers" / "intake_consult.py").read_text(encoding="utf-8")
    at = src.index("base_year1 = assemble_financials_year1(shared_context, None)")
    block = src[src.rfind("_y1_before_recalc = ", 0, at):src.index("CW-027 (Nick-ruled one-shot)", at)]
    self.assertIn("_y1_before_recalc = copy.deepcopy(financials_year1_json)", block)
    self.assertIn("financials_year1_json != _y1_before_recalc", block)
    self.assertIn("financials_year1_json=financials_year1_json", block)
    self.assertNotIn('focus == "financials"', block, "saved whatever the turn's focus")


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


class AReadbackNeverAsksAboutAFigureItDoesNotName(unittest.TestCase):
  """Cowork 1228: "Should I record  here, or have I put it in the wrong place?" - door C
  built its question around an empty value. She cannot confirm or refuse a number she is
  not shown. A rewrite with no value to name holds nothing back and asks nothing; a
  rewrite with a value still holds and asks, naming it."""

  def _review(self, value):
    from types import SimpleNamespace
    from unittest import mock
    from client_intake_and_finmo.intake_guard import door_a, door_c  # type: ignore
    path = "ops.lob_models[0].products[0].unit_price"
    pre = {"ops": {"lob_models": [{"lob_name": "Main", "products": [{"product_name": "Jar", "unit_price": None}]}]}}
    post = {"ops": {"lob_models": [{"lob_name": "Main", "products": [{"product_name": "Jar", "unit_price": 9.5}]}]}}
    stub = SimpleNamespace(ran=True, error="", asks=[], receipts=[], questions=[],
                           rewrites=[{"from_key": path, "to_key": path, "value": value,
                                      "client_words": "Nine dollars fifty a jar.", "why": "stub"}])
    with mock.patch.object(door_a, "review", return_value=stub), mock.patch.dict("os.environ", {"INTAKE_GUARD_ENABLED": "1"}):
      return door_c.review(pre=pre, post=post, user_text="Nine dollars fifty a jar.", messages=[], stage="ops",
                           allowed_patch={}, guard_rewrites=[])

  def test_no_value_no_question_and_nothing_held(self):
    for blank in ("", "   ", None):
      v = self._review(blank)
      self.assertEqual(v.questions, [], repr(blank))
      self.assertEqual(v.sections["ops"]["lob_models"][0]["products"][0]["unit_price"], 9.5, "nothing held back")
    v = self._review(12)
    self.assertEqual(len(v.questions), 1)
    # Cowork 1231: the question names WHAT it asks about, in her terms, on its row - never "here"
    self.assertIn("Should I record 12 as your price for Jar", v.questions[0])
    self.assertNotIn("here,", v.questions[0])
    self.assertNotIn("unit_price", v.questions[0])
    self.assertIsNone(v.sections["ops"]["lob_models"][0]["products"][0]["unit_price"], "a named value is still held")


class OneQuestionPerThingSheSaid(unittest.TestCase):
  """CW-070 turn 5 (draft 71d4e505): her one sentence wrote the same 12 to two products
  and door C asked the identical question twice in one message. For any number of rows:
  one question per (her words, value, field), naming every row; every field still held."""

  def _review(self, values):
    from types import SimpleNamespace
    from unittest import mock
    from client_intake_and_finmo.intake_guard import door_a, door_c  # type: ignore
    names = ["Jarred kimchi", "Kimchi brine concentrate", "Gochujang"][:len(values)]
    pre = {"ops": {"lob_models": [{"lob_name": "Main", "products": [
      {"product_name": n, "unit_price": None} for n in names]}]}}
    post = {"ops": {"lob_models": [{"lob_name": "Main", "products": [
      {"product_name": n, "unit_price": 9.5} for n in names]}]}}
    words = "please treat the whole thing as monthly, not weekly"
    rewrites = [{"from_key": "ops.lob_models[0].products[%d].unit_price" % i,
                 "to_key": "ops.lob_models[0].products[%d].unit_price" % i,
                 "value": v, "client_words": words, "why": "stub"} for i, v in enumerate(values)]
    stub = SimpleNamespace(ran=True, error="", asks=[], receipts=[], questions=[], rewrites=rewrites)
    with mock.patch.object(door_a, "review", return_value=stub), mock.patch.dict("os.environ", {"INTAKE_GUARD_ENABLED": "1"}):
      return door_c.review(pre=pre, post=post, user_text=words, messages=[], stage="ops", allowed_patch={}, guard_rewrites=[]), names

  def test_the_same_value_from_one_sentence_is_asked_once_naming_every_row(self):
    for n in (2, 3):
      v, names = self._review([12] * n)
      self.assertEqual(len(v.questions), 1, n)
      for name in names:
        self.assertIn(name, v.questions[0], (n, name))
      self.assertEqual(len(v.asks), n, "every field is still held")
      self.assertTrue(all(a["question"] == v.questions[0] for a in v.asks))
      for p in v.sections["ops"]["lob_models"][0]["products"]:
        self.assertIsNone(p["unit_price"], "each held back until answered")

  def test_different_values_are_different_questions(self):
    v, names = self._review([12, 10])
    self.assertEqual(len(v.questions), 2)
    self.assertIn("12", v.questions[0]); self.assertIn("10", v.questions[1])


if __name__ == "__main__":
  unittest.main(verbosity=2)
