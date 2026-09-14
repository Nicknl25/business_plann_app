"""The v1 interpretation reads every client turn in shadow, and changes nothing.

One-reader build, STEP 1 (Nick ruled R5, 2026-09-14): a bounded shadow window in
which the v1 contract reads each client sentence beside the app, recorded and
never used, so its cost and what it reads are measured rather than assumed.

These pins state, for any turn:
  - it is off unless the window switch is on;
  - on, it records one row per client turn with exactly what the model returned,
    its token counts and time, and a quote check (R2, string equality) that is
    recorded, not enforced;
  - it reads a SNAPSHOT taken before the turn mutates anything;
  - the per-run identity reaches the model call inside the thread (so the
    response cache and usage ledger attribute it to the draft);
  - a model failure is recorded and never raised;
  - the schema is strict everywhere (every object closed, every property required);
  - the prompt carries the rules that matter: the quote span by rule, decline as
    an answer, a no as a fact, never compute;
  - the handler starts it before its first save.
"""
from __future__ import annotations

import itertools
import json
import os
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "python" / "client_intake_and_finmo"))

DRAFT = "e" * 32
ISADORA = ("Six. That's the most the shop will hold, and we're usually running five or six. A frame takes about ten "
           "weeks from design through to raising it. Over a year that works out around 26 of them, and 34 would be "
           "flat out. We can't go past six at once whatever the demand, that's the building.")


class _Resp:
  def __init__(self, obj, status=200):
    self._obj, self.status_code, self.text = obj, status, json.dumps(obj)

  def json(self):
    return self._obj


class _Cursor:
  def __init__(self, sink):
    self.sink = sink

  def execute(self, sql, params=None):
    self.sink.append((" ".join(str(sql).split()), params))

  def close(self):
    pass


class _Conn:
  def __init__(self, sink):
    self.sink = sink

  def cursor(self, dictionary=False):
    return _Cursor(self.sink)

  def commit(self):
    pass

  def close(self):
    pass


def _claim(surface, **over):
  base = {"id": "c1", "subject": "ops.capacity", "line": None, "kind": "concurrent", "value_number": 6,
          "value_low": None, "value_high": None, "value_text": None, "per": "at_once", "currency": None,
          "is_percent": False, "precision": "exact", "surface": surface, "polarity": "affirm",
          "firmness": "unknown", "firmness_direction": "none", "firmness_reason_surface": None,
          "provenance": "stated", "role": "answered", "supersedes": None, "refers_to": []}
  base.update(over)
  return base


class _Harness(unittest.TestCase):
  def setUp(self):
    from client_intake_and_finmo import interpretation_contract as S  # type: ignore
    from client_intake_and_finmo import openai_http as OH  # type: ignore

    self.S, self.OH = S, OH
    self.sink, self.calls = [], []
    self._saved = {"post": S._post, "connect": S._connect, "env": os.environ.get("INTAKE_SHADOW_INTERPRETATION"),
                   "key": os.environ.get("OPENAI_API_KEY")}
    S._connect = lambda: _Conn(self.sink)
    S._ensured = True
    os.environ["OPENAI_API_KEY"] = self._saved["key"] or "test-key"
    self._tok = OH._GPT_RUN_IDENTITY.set({})

  def tearDown(self):
    self.S._post, self.S._connect = self._saved["post"], self._saved["connect"]
    self.OH._GPT_RUN_IDENTITY.reset(self._tok)
    for k, v in (("INTAKE_SHADOW_INTERPRETATION", self._saved["env"]), ("OPENAI_API_KEY", self._saved["key"])):
      if v is None:
        os.environ.pop(k, None)
      else:
        os.environ[k] = v

  def model_returns(self, interp, status=200, usage=None):
    def post(**kw):
      self.calls.append({"payload": kw["payload"], "identity": self.OH.get_gpt_run_identity()})
      return _Resp({"output": [{"content": [{"type": "output_json", "json": interp}]}],
                    "usage": usage or {"input_tokens": 9000, "output_tokens": 250}}, status)
    self.S._post = post

  def start(self, message, sections=None, turn=5):
    return self.S.start(draft_id=DRAFT, turn=turn, message=message,
                        messages=[{"role": "assistant", "content": "How many can the shop hold at once?"}],
                        sections=sections if sections is not None else {"ops": {}}, focus="ops",
                        confirm_question="")

  def rows(self):
    return [p for sql, p in self.sink if sql.startswith("INSERT INTO intake_turn_interpretations_shadow")]


class TheWindowIsBoundedBySwitch(_Harness):
  def test_off_unless_switched_on(self):
    self.model_returns({"claims": [], "answers": [], "unresolved": [], "client_questions": []})
    for value in (None, "", "0", "off", "false"):
      if value is None:
        os.environ.pop("INTAKE_SHADOW_INTERPRETATION", None)
      else:
        os.environ["INTAKE_SHADOW_INTERPRETATION"] = value
      self.assertIsNone(self.start("Six."), value)
    self.assertEqual(self.calls, [])
    self.assertEqual(self.sink, [])

  def test_no_message_no_call(self):
    os.environ["INTAKE_SHADOW_INTERPRETATION"] = "1"
    self.model_returns({"claims": [], "answers": [], "unresolved": [], "client_questions": []})
    for message in ("", "   "):
      self.assertIsNone(self.start(message))
    self.assertEqual(self.calls, [])


class EveryTurnIsRecordedAsRead(_Harness):
  def test_any_interpretation_is_recorded_whole_with_its_cost_and_quote_check(self):
    os.environ["INTAKE_SHADOW_INTERPRETATION"] = "1"
    shapes = (
      ({"claims": [_claim("Six.")], "answers": [], "unresolved": [], "client_questions": []}, []),
      ({"claims": [_claim("34 would be flat out", kind="ceiling", value_number=34, per="year"),
                   _claim("usually running five or six", kind="typical", value_number=None, value_low=5,
                          value_high=6, precision="approximate")],
        "answers": [], "unresolved": [], "client_questions": []}, []),
      ({"claims": [_claim("six frames at once", firmness="fixed", firmness_direction="down_only",
                          firmness_reason_surface="that's the building")],
        "answers": [], "unresolved": [], "client_questions": []}, ["claims[0]"]),
      ({"claims": [], "answers": [{"question_quote": "How many?", "outcome": "decline", "option": None,
                                   "surface": "We can't go past six"}],
        "unresolved": [], "client_questions": []}, []),
    )
    for (interp, bad), turn in itertools.product(shapes, (0, 11)):
      self.sink.clear()
      self.calls.clear()
      self.model_returns(interp)
      self.OH.set_gpt_run_identity(draft_id=DRAFT)
      th = self.start(ISADORA, turn=turn)
      th.join(10)
      rows = self.rows()
      self.assertEqual(len(rows), 1)
      (draft, t, sha, chars, version, model, status, err, elapsed, tin, tout, interp_json, qf_json) = rows[0]
      self.assertEqual((draft, t, chars, version, status), (DRAFT, turn, len(ISADORA), "v1", "ok"), err)
      self.assertEqual(json.loads(interp_json), interp)
      self.assertEqual((tin, tout), (9000, 250))
      self.assertEqual(json.loads(qf_json), bad)
      self.assertEqual(self.calls[0]["identity"].get("draft_id"), DRAFT, "identity lost in the thread")

  def test_the_input_is_a_snapshot_taken_before_the_turn_changes_anything(self):
    os.environ["INTAKE_SHADOW_INTERPRETATION"] = "1"
    release = threading.Event()
    seen = {}

    def post(**kw):
      release.wait(5)
      seen["input"] = json.loads(kw["payload"]["input"][1]["content"])
      return _Resp({"output": [{"content": [{"type": "output_json", "json":
                     {"claims": [], "answers": [], "unresolved": [], "client_questions": []}}]}], "usage": {}})
    self.S._post = post
    ops = {"lob_models": [{"lob_name": "Lab", "products": [{"product_name": "Sample", "units_per_week_capacity": None}]}]}
    th = self.start("480 a week flat out.", sections={"ops": ops})
    ops["lob_models"][0]["products"][0]["units_per_week_capacity"] = 480     # the turn writes after the start
    release.set()
    th.join(10)
    self.assertIsNone(seen["input"]["known_facts"]["ops"]["lob_models"][0]["products"][0]["units_per_week_capacity"])
    self.assertEqual(seen["input"]["lines"], [{"line_of_business": "Lab", "product": "Sample", "cadence": None}])

  def test_the_shadow_sees_the_same_history_as_the_live_router(self):
    """Cowork 1055: the router is given the app's last message only. A shadow with
    more history would make a disagreement about context, not the contract."""
    history = [{"role": "user", "content": "An older message she sent - about the rent."},
               {"role": "assistant", "content": "An older question about rent?"},
               {"role": "user", "content": "It is 2,400 a month."},
               {"role": "assistant", "content": "How many samples can the lab take in a busy week?"}]
    for n in (1, 2, 4):
      body = json.loads(self.S.build_input(message="480 a week.", messages=history[-n:], sections={"ops": {}},
                                           focus="ops", confirm_question=""))
      self.assertEqual(body["last_assistant_message"], "How many samples can the lab take in a busy week?")
      self.assertNotIn("recent_turns", body)
      self.assertNotIn("rent", json.dumps(body), "older turns reached the shadow")

  def test_a_model_failure_is_recorded_and_never_raised(self):
    os.environ["INTAKE_SHADOW_INTERPRETATION"] = "1"
    for status in (500, 429):
      self.sink.clear()
      self.model_returns({"error": "boom"}, status=status)
      th = self.start("Six.")
      th.join(10)
      rows = self.rows()
      self.assertEqual(len(rows), 1)
      self.assertEqual(rows[0][6], "error")
      self.assertTrue(rows[0][7])


class TheContractIsStrictAndSaysTheRules(_Harness):
  def test_every_object_in_the_schema_is_closed_and_fully_required(self):
    def walk(node, path="root"):
      if isinstance(node, dict):
        if node.get("type") == "object":
          self.assertIs(node.get("additionalProperties"), False, path)
          self.assertEqual(sorted(node.get("required") or []), sorted(node.get("properties") or {}), path)
        for k, v in node.items():
          walk(v, path + "." + str(k))
      elif isinstance(node, list):
        for i, v in enumerate(node):
          walk(v, "%s[%d]" % (path, i))
    walk(self.S.SCHEMA)

  def test_the_prompt_carries_the_rules_that_matter(self):
    p = self.S.SYSTEM
    for rule in ("SURFACE, BY RULE", "smallest contiguous span", "DECLINE", "A no is a fact", "NEVER COMPUTE",
                 "never 5.5", "copied character for character"):
      self.assertIn(rule, p)
    self.assertIn("decline", self.S.OUTCOMES)

  def test_the_quote_check_is_string_equality(self):
    msg = "We do about 340 most weeks."
    self.assertEqual(self.S.quote_failures({"claims": [_claim("about 340 most weeks")]}, msg), [])
    self.assertEqual(self.S.quote_failures({"claims": [_claim("About 340 most weeks")]}, msg), ["claims[0]"])
    self.assertEqual(self.S.quote_failures({"claims": [_claim("about three hundred and forty")]}, msg), ["claims[0]"])

  def test_the_handler_starts_it_before_its_first_save(self):
    src = (ROOT / "python" / "api_handlers" / "intake_consult.py").read_text(encoding="utf-8-sig")
    begin = src.index("TURN_BEGIN draft=%s")
    shadow = src.index("_shadow.start(", begin)
    first_save = src.index("append_messages(", begin)
    self.assertLess(shadow, first_save, "the shadow must read the sentence before the turn saves anything")

  def test_the_endpoint_returns_the_shadow(self):
    src = (ROOT / "python" / "api.py").read_text(encoding="utf-8-sig")
    self.assertIn('"shadow": _shadow.for_draft(conn, draft_id)', src)


if __name__ == "__main__":
  unittest.main(verbosity=2)
