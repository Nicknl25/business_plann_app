"""HER ANSWER RELEASES A HELD VALUE (Nick 2026-09-14, ruling 2: "Door A and door C
hold the turn and ask" - and an answer, or a correction, must land).

CW-070, 71d4e505: at turn 3 door C held 12 behind "Should I record 12 as how many
working weeks or months a year you run?" on an ops-only persist, stored no hold, and
at turn 5 her "Yes, twelve is right" had nothing to answer - 52 stayed. The hold now
carries every held path with the value asked about, wherever the ask happened; on her
next turn door A judges her words with the question in view and the path takes the
asked value, the figure she gave instead, or stays held. For any business.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python"), os.path.join(ROOT, "python", "client_intake_and_finmo")):
  if p not in sys.path:
    sys.path.insert(0, p)

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from client_intake_and_finmo.intake_guard import door_c as D  # noqa: E402
from client_intake_and_finmo.intake_guard import audit as A  # noqa: E402


def _door_a_says(hold_cleared=False, asks=None, rewrites=None, calls=None):
  class _Resp:
    status_code = 200
    def json(self):
      return {"output": [{"content": [{"type": "output_text", "text": json.dumps({
        "allowed": [], "rewrites": rewrites or [], "asks": asks or [], "hold_cleared": hold_cleared,
        "already_captured": []})}]}]}
  def fake_post(**kw):
    if calls is not None:
      calls.append(kw)
    return _Resp()
  return fake_post


def _ops(periods, price=9.5):
  return {"lob_models": [{"lob_name": "Main", "products": [
    {"product_name": "Jars", "unit_cadence": "monthly", "operating_periods_per_year": periods, "unit_price": price},
    {"product_name": "Boxes", "unit_cadence": "monthly", "operating_periods_per_year": periods, "unit_price": 30}]}]}


P0 = "ops.lob_models[0].products[0].operating_periods_per_year"
P1 = "ops.lob_models[0].products[1].operating_periods_per_year"

# (business, section, pre section, path, before, asked value, her answer, her different figure)
SHAPES = [
  ("kimchi maker", "ops", _ops(52.0), P0, 52.0, 12.0, "Yes, twelve is right - one run a month.", ("No - we run 11 months, August is off.", 11.0)),
  ("print shop", "financials", {"monthly_rent_expense": 3100.0}, "financials.monthly_rent_expense", 3100.0, 3400.0,
   "Yes, that's the rent now.", ("Actually it's 3,600 from March.", 3600.0)),
]


def _get(section, path):
  return D._get_path(section, path.partition(".")[2])


class DoorCReleasesByHerAnswer(unittest.TestCase):

  def _review(self, sec, pre_sec, path, asked, words, fake):
    pre = {"ops": {}, "market": {}, "people": {}, "financials": {}}
    pre[sec] = copy.deepcopy(pre_sec)
    post = {"ops": None, "market": None, "people": None, "financials": None}
    post[sec] = copy.deepcopy(pre_sec)
    D._set_path(post[sec], path.partition(".")[2], asked)
    hold = {"field": path, "question": "Should I record it?", "turn": 3, "asks": [{"key": path, "value": asked, "question": "q"}]}
    return D.review(pre=pre, post=post, user_text=words, messages=[{"role": "user", "content": words}], stage=sec,
                    post_fn=fake, hold=hold)

  def test_an_answer_writes_the_value_asked_about(self):
    for business, sec, pre_sec, path, before, asked, yes, _other in SHAPES:
      with self.subTest(business=business):
        calls = []
        v = self._review(sec, pre_sec, path, asked, yes, _door_a_says(hold_cleared=True, calls=calls))
        self.assertEqual(_get(v.sections[sec], path), asked)
        self.assertTrue(v.hold_cleared)
        self.assertEqual([r["key"] for r in v.released], [path])
        self.assertEqual(v.asks, [])
        self.assertEqual(len(calls), 1)
        body = json.dumps(calls[0]["payload"])
        self.assertIn("Should I record it?", body, "door A is shown the question it is judging an answer to")

  def test_no_answer_keeps_it_held_and_asks_nothing_new(self):
    for business, sec, pre_sec, path, before, asked, _yes, _other in SHAPES:
      with self.subTest(business=business):
        v = self._review(sec, pre_sec, path, asked, "What does that mean for my taxes?", _door_a_says(hold_cleared=False))
        self.assertEqual(_get(v.sections[sec], path), before)
        self.assertFalse(v.hold_cleared)
        self.assertEqual(v.released, [])
        self.assertEqual(v.asks, [])
        self.assertEqual(next(c for c in v.changes if c["path"] == path)["verdict"], "held")

  def test_a_different_figure_in_her_words_is_the_answer(self):
    for business, sec, pre_sec, path, before, asked, _yes, (words, figure) in SHAPES:
      with self.subTest(business=business):
        rw = [{"from_key": path, "to_key": path, "value_json": json.dumps(figure), "client_words": words,
               "receipt": "", "why": "she gave the figure"}]
        v = self._review(sec, pre_sec, path, asked, words, _door_a_says(hold_cleared=True, rewrites=rw))
        self.assertEqual(_get(v.sections[sec], path), figure)
        self.assertEqual(v.released[0]["value"], figure)

  def test_an_unreachable_model_keeps_it_held(self):
    def boom(**kw):
      raise TimeoutError("no model")
    for business, sec, pre_sec, path, before, asked, yes, _other in SHAPES:
      with self.subTest(business=business):
        v = self._review(sec, pre_sec, path, asked, yes, boom)
        self.assertEqual(_get(v.sections[sec], path), before)

  def test_a_bookkeeping_classification_never_lets_a_held_path_through(self):
    # a cadence default moving would classify as app_arithmetic without the hold
    v = self._review("ops", _ops(52.0), P0, 12.0, "Hmm, not sure.", _door_a_says(hold_cleared=False))
    self.assertEqual(_get(v.sections["ops"], P0), 52.0)


class ThePersistDoorStoresAndReleasesTheHold(unittest.TestCase):
  """The real _guard_writes_before_persist, on the CW-070 shape: an ops-only persist."""

  def _call(self, *, row_fin, row_ops, post_ops, post_fin, words, fake, existing=5):
    import intake_consult_draft as icd  # type: ignore
    row = {"operating_model_json": json.dumps(row_ops), "target_market_json": "{}", "people_json": "{}",
           "financials_json": json.dumps(row_fin), "active_focus": "ops"}
    msgs = [{"role": "user", "content": words}, {"role": "assistant", "content": "ok"}]
    with mock.patch("client_intake_and_finmo.openai_http.post_openai_with_retries", side_effect=fake), \
         mock.patch.object(D, "record", return_value=None), mock.patch.object(A, "record", return_value=None):
      return icd._guard_writes_before_persist(
        None, draft_id="d", row=row, new_messages=msgs, existing_messages=[{"role": "user", "content": "x"}] * existing,
        operating_model_json=post_ops, target_market_json=None, people_json=None, financials_json=post_fin)

  def test_an_ask_on_an_ops_only_persist_stores_every_ask_with_its_value(self):
    # a stated price moved on both rows (a moving cadence default would be bookkeeping, never asked)
    U0, U1 = "ops.lob_models[0].products[0].unit_price", "ops.lob_models[0].products[1].unit_price"
    ask = lambda k: {"key": k, "client_words": "ten dollars a jar", "question": "Should I record 10 as the price?", "why": "w"}
    post_ops = _ops(12.0, price=10.0)
    post_ops["lob_models"][0]["products"][1]["unit_price"] = 10.0
    ops, _m, _p, fin = self._call(row_fin={}, row_ops=_ops(12.0), post_ops=post_ops, post_fin=None,
                                  words="Ten dollars a jar, and the same for the boxes.",
                                  fake=_door_a_says(asks=[ask(U0), ask(U1)]), existing=3)
    self.assertEqual(_get(ops, U0), 9.5)
    self.assertEqual(_get(ops, U1), 30)
    hold = A.get_hold(fin)
    self.assertIsNotNone(hold, "the hold is stored though the persist carried no financials")
    self.assertEqual(D.held_values(hold), {U0: 10.0, U1: 10.0})
    self.assertEqual(hold["turn"], 3)

  def test_her_yes_on_the_next_turn_lands_the_value_and_clears_the_hold(self):
    held = {"_guard": {"hold": {"field": P0, "question": "Should I record 12?", "turn": 3,
                                "asks": [{"key": P0, "value": 12.0}, {"key": P1, "value": 12.0}]}}}
    handler_ops = _ops(52.0)
    snapshot = copy.deepcopy(handler_ops)
    ops, _m, _p, fin = self._call(row_fin=held, row_ops=_ops(52.0), post_ops=handler_ops, post_fin=None,
                                  words="Yes, twelve is right - one production run a month.",
                                  fake=_door_a_says(hold_cleared=True))
    self.assertEqual(_get(ops, P0), 12.0)
    self.assertEqual(_get(ops, P1), 12.0)
    self.assertIsNone(A.get_hold(fin))
    self.assertEqual(handler_ops, snapshot, "the handler's object is never mutated")

  def test_the_release_needs_no_section_from_the_handler(self):
    held = {"_guard": {"hold": {"field": P0, "question": "q", "turn": 3, "asks": [{"key": P0, "value": 12.0}]}}}
    ops, _m, _p, fin = self._call(row_fin=held, row_ops=_ops(52.0), post_ops=None, post_fin=None,
                                  words="Yes, that's right.", fake=_door_a_says(hold_cleared=True))
    self.assertEqual(_get(ops, P0), 12.0)
    self.assertIsNone(A.get_hold(fin))

  def test_no_answer_keeps_52_and_counts_the_try(self):
    held = {"_guard": {"hold": {"field": P0, "question": "q", "turn": 3, "asks": [{"key": P0, "value": 12.0}]}}}
    ops, _m, _p, fin = self._call(row_fin=held, row_ops=_ops(52.0), post_ops=_ops(52.0), post_fin=None,
                                  words="Can we talk about pricing first?", fake=_door_a_says(hold_cleared=False))
    self.assertEqual(_get(ops, P0), 52.0)
    self.assertEqual(A.get_hold(fin)["release_tries"], 1)

  def test_the_question_turn_itself_never_releases(self):
    calls = []
    held = {"_guard": {"hold": {"field": P0, "question": "q", "turn": 5, "asks": [{"key": P0, "value": 12.0}]}}}
    ops, _m, _p, _fin = self._call(row_fin=held, row_ops=_ops(52.0), post_ops=_ops(52.0), post_fin=None,
                                   words="treat it as monthly", fake=_door_a_says(hold_cleared=True, calls=calls), existing=5)
    self.assertEqual(_get(ops, P0), 52.0)
    self.assertEqual(calls, [])

  def test_a_stale_copy_later_in_the_same_turn_never_restores_the_hold(self):
    import flask
    app = flask.Flask("t")
    hold = {"field": P0, "question": "q", "turn": 3, "asks": [{"key": P0, "value": 12.0}]}
    calls = []
    with app.test_request_context():
      ops, _m, _p, fin = self._call(row_fin={"_guard": {"hold": hold}}, row_ops=_ops(52.0), post_ops=_ops(52.0), post_fin=None,
                                    words="Yes.", fake=_door_a_says(hold_cleared=True, calls=calls))
      self.assertIsNone(A.get_hold(fin))
      stale_fin = {"_guard": {"hold": copy.deepcopy(hold)}}
      _o2, _m2, _p2, fin2 = self._call(row_fin=fin, row_ops=ops, post_ops=ops, post_fin=stale_fin,
                                       words="Yes.", fake=_door_a_says(hold_cleared=True, calls=calls))
      self.assertIsNone(A.get_hold(fin2))
      self.assertEqual(_get(_o2, P0), 12.0)
      self.assertEqual(len(calls), 1, "one release attempt per client turn")


if __name__ == "__main__":
  unittest.main()
