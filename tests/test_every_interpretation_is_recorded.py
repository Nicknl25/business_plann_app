"""Every interpretation of a client turn is recorded, exactly as it was returned.

One-reader build, STEP 0 (Nick ruled 2026-09-14). What the router understood
from a sentence was stored nowhere readable, so nothing - not a door, not
Cowork - could read the understanding beside what was written. Every
route_intent call now leaves one row in intake_turn_interpretations: the action,
the patch, the unresolved figures with the client's words, the reply, the call
site, and whether the sentence it read was the client's message this turn (the
proposal extractor hands the router the app's own previous reply).

No behaviour changes: nothing reads the table yet. These pins state, for any
action, any patch and any call site:
  - the row holds what the caller got back, nothing reshaped;
  - a sentence that is not this turn's client message is marked as not hers;
  - nothing is written outside a live request (unit tests and preflight stay
    read-only);
  - a failed write never breaks the turn, and says so at ERROR;
  - a router failure is recorded and still raised;
  - no code reaches the router body except through the recording door.
"""
from __future__ import annotations

import ast
import itertools
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "python" / "client_intake_and_finmo"))

DRAFT = "d" * 32


class _Resp:
  def __init__(self, obj, status=200):
    self._obj = obj
    self.status_code = status
    self.text = json.dumps(obj)

  def json(self):
    return self._obj


class _Cursor:
  def __init__(self, sink, rows=None):
    self.sink = sink
    self.rows = rows or []

  def execute(self, sql, params=None):
    self.sink.append((" ".join(str(sql).split()), params))

  def fetchall(self):
    return list(self.rows)

  def close(self):
    pass


class _Conn:
  def __init__(self, sink, rows=None, fail=False):
    self.sink, self.rows, self.fail = sink, rows, fail

  def cursor(self, dictionary=False):
    if self.fail:
      raise RuntimeError("database unavailable")
    return _Cursor(self.sink, self.rows)

  def commit(self):
    pass

  def close(self):
    pass


class _Harness(unittest.TestCase):
  def setUp(self):
    from flask import Flask  # type: ignore
    from client_intake_and_finmo import intent_router as IR  # type: ignore
    from client_intake_and_finmo import openai_http as OH  # type: ignore
    from client_intake_and_finmo import turn_interpretations as TI  # type: ignore

    self.IR, self.OH, self.TI = IR, OH, TI
    self.app = Flask("pin")
    self.sink = []
    self._saved = {"post": IR._post_openai, "connect": TI._connect, "ensured": TI._ensured,
                   "key": os.environ.get("OPENAI_API_KEY")}
    os.environ["OPENAI_API_KEY"] = self._saved["key"] or "test-key"
    TI._connect = lambda: _Conn(self.sink)
    self._ident_token = OH._GPT_RUN_IDENTITY.set({})

  def tearDown(self):
    self.IR._post_openai = self._saved["post"]
    self.TI._connect = self._saved["connect"]
    self.TI._ensured = self._saved["ensured"]
    self.OH._GPT_RUN_IDENTITY.reset(self._ident_token)
    if self._saved["key"] is None:
      os.environ.pop("OPENAI_API_KEY", None)
    else:
      os.environ["OPENAI_API_KEY"] = self._saved["key"]

  def model_says(self, out, status=200):
    body = {"output": [{"content": [{"type": "output_json", "json": out}]}]}
    self.IR._post_openai = lambda **kw: _Resp(body, status)

  def route(self, message, **extra):
    kw = dict(consult_type="ops", user_message=message, baseline_json={}, shared_context={}, recent_messages=[])
    kw.update(extra)
    return self.IR.route_intent(**kw)

  def inserts(self):
    return [p for sql, p in self.sink if sql.startswith("INSERT INTO intake_turn_interpretations")]


class EveryResultIsRecordedAsReturned(_Harness):
  def test_any_action_patch_and_figures_leave_one_row_equal_to_the_result(self):
    shapes = (
      ("confirm_proceed", [], []),
      ("continue_chat", [], [{"value_json": "340", "client_words": "about three hundred and forty most weeks",
                              "candidate_fields": ["unit_price"]}]),
      ("answer_readonly", [], []),
      ("edit_patch", [{"field": "unit_price", "value_json": "95"}], []),
      ("edit_patch", [{"field": "unit_price", "value_json": "$504"}],
       [{"value_json": "34", "client_words": "34 would be flat out. We can't go past six at once whatever the demand, "
                                             "that's the building - and the words run well past a hundred and sixty "
                                             "characters so nothing may cut them", "candidate_fields": []}]),
    )
    for (action, patch, figs), turn, message in itertools.product(shapes, (0, 7, 41),
                                                                  ("Six.", "We charge $504 a sample.")):
      self.sink.clear()
      self.model_says({"action": action, "assistant_message": "noted", "patch": patch, "unresolved_figures": figs})
      with self.app.test_request_context():
        from flask import g  # type: ignore
        g._turn_index = turn
        g._turn_user_text = message
        self.OH.set_gpt_run_identity(draft_id=DRAFT)
        result = self.route(message)
      rows = self.inserts()
      label = "%s turn=%d" % (action, turn)
      self.assertEqual(len(rows), 1, label)
      p = rows[0]
      (draft, t, site, consult, focus, is_client, sha, chars, status, act, patch_json, unres_json,
       reply, err, elapsed) = p
      self.assertEqual((draft, t, consult, status, act), (DRAFT, turn, "ops", "ok", result["action"]), label)
      self.assertEqual(json.loads(patch_json) if patch_json else None, result.get("patch"), label)
      self.assertEqual(json.loads(unres_json), result.get("unresolved_figures") or [], label)
      self.assertEqual(reply, result.get("assistant_message"), label)
      self.assertEqual(is_client, 1, label)
      self.assertEqual(chars, len(message))
      self.assertIn("test_every_interpretation_is_recorded.py", site)
      self.assertIsNone(err)

  def test_a_sentence_that_is_not_the_client_message_is_marked_not_hers(self):
    """The proposal extractor hands the router the app's previous reply."""
    self.model_says({"action": "edit_patch", "assistant_message": "", "unresolved_figures": [],
                     "patch": [{"field": "unit_price", "value_json": "95"}]})
    with self.app.test_request_context():
      from flask import g  # type: ignore
      g._turn_index = 12
      g._turn_user_text = "Yes, that works."
      self.OH.set_gpt_run_identity(draft_id=DRAFT)
      self.route("I'd suggest we plan on $95 a sample - does that work?")
    self.assertEqual(self.inserts()[0][5], 0)


class RecordingNeverChangesATurn(_Harness):
  def test_nothing_is_written_outside_a_request(self):
    self.model_says({"action": "confirm_proceed", "assistant_message": "", "patch": [], "unresolved_figures": []})
    self.OH.set_gpt_run_identity(draft_id=DRAFT)
    self.route("Yes.")
    self.assertEqual(self.sink, [], "a unit test or preflight wrote to the database")

  def test_a_failed_write_returns_the_result_and_says_so(self):
    self.model_says({"action": "confirm_proceed", "assistant_message": "ok", "patch": [], "unresolved_figures": []})
    self.TI._connect = lambda: _Conn(self.sink, fail=True)
    self.TI._ensured = False
    with self.app.test_request_context(), self.assertLogs(level="ERROR") as logs:
      from flask import g  # type: ignore
      g._turn_index = 3
      g._turn_user_text = "Yes."
      self.OH.set_gpt_run_identity(draft_id=DRAFT)
      result = self.route("Yes.")
    self.assertEqual(result["action"], "confirm_proceed")
    self.assertTrue(any("TURN_INTERPRETATION_WRITE_FAILED" in line for line in logs.output))

  def test_a_router_failure_is_recorded_and_still_raised(self):
    self.model_says({"error": "boom"}, status=500)
    with self.app.test_request_context():
      from flask import g  # type: ignore
      g._turn_index = 5
      g._turn_user_text = "Six."
      self.OH.set_gpt_run_identity(draft_id=DRAFT)
      with self.assertRaises(RuntimeError):
        self.route("Six.")
    rows = self.inserts()
    self.assertEqual(len(rows), 1)
    self.assertEqual(rows[0][8], "error")
    self.assertTrue(rows[0][13])


class TheRecordIsReadableAndNothingBypassesIt(_Harness):
  def test_the_reader_parses_what_was_stored(self):
    stored = [{"id": 1, "turn": 11, "call_site": "intake_consult.py:21650", "consult_type": "unified",
               "active_focus": "ops", "is_client_message": 1, "message_chars": 224, "status": "ok",
               "action": "edit_patch",
               "patch_json": json.dumps({"ops.product_overrides": {"Lab testing job": {"avg_units_per_week_year1": 340}}}),
               "unresolved_json": "[]", "assistant_message": "", "error": None, "elapsed_ms": 2890, "created_at": None}]
    self.TI._ensured = True
    rows = self.TI.for_draft(_Conn(self.sink, rows=stored), DRAFT)
    self.assertEqual(rows[0]["patch"]["ops.product_overrides"]["Lab testing job"]["avg_units_per_week_year1"], 340)
    self.assertEqual(rows[0]["unresolved_figures"], [])
    self.assertIs(rows[0]["is_client_message"], True)

  def test_the_endpoint_exists(self):
    src = (ROOT / "python" / "api.py").read_text(encoding="utf-8-sig")
    self.assertIn('"/api/intake-interpretations/<draft_id>"', src)

  def test_no_code_calls_the_router_body_directly(self):
    offenders = []
    for path in (ROOT / "python").rglob("*.py"):
      try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
      except (SyntaxError, UnicodeDecodeError):
        continue
      for node in ast.walk(tree):
        if isinstance(node, ast.Call):
          fn = node.func
          name = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
          if name == "_route_intent_body":
            offenders.append("%s:%d" % (path.name, node.lineno))
    self.assertEqual([o for o in offenders if not o.startswith("intent_router.py:")], [], offenders)
    self.assertEqual(len([o for o in offenders if o.startswith("intent_router.py:")]), 1,
                     "only the recording door may call the router body")


if __name__ == "__main__":
  unittest.main(verbosity=2)
