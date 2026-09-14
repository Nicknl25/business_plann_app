"""Every reader of her words is counted, and counting changes nothing it reads.

One-reader build, STEP 1b (Nick ruled 2026-09-14; he asked for the real reader
count when the shadow data is in). Last night's search found about 45 places
that pull meaning from a client's words besides the router; Nick said to assume
more. Each such function now carries @reads_client_words, and inside a live
request every read is noted - reader, call site, whether the text was her
message, what it concluded - and written once at the end of the request.

These pins state, for any reader:
  - the decorated reader returns exactly what the undecorated one returns, on
    generated inputs, and raises what it raises;
  - nothing is noted outside a request (unit tests, preflight, the shadow thread);
  - notes accumulate across the turn, identical reads counted, and are written
    once, then cleared;
  - "was this her message" is decided by string equality with the turn's text;
  - the per-turn cap reports what it dropped instead of dropping it silently;
  - every reader on the required list is registered and wrapped;
  - the request end writes the notes and the endpoint returns them.
"""
from __future__ import annotations

import itertools
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "python" / "client_intake_and_finmo"))

DRAFT = "f" * 32

REQUIRED = {
  "api_handlers.intake_consult": {
    "_extract_single_compact_number": "compact_single_number", "_row_named_in_message": "row_named_in_message",
    "_message_states_headcount": "headcount_stated", "_figure_stated_in_message": "figure_stated_in_message",
    "_message_figures": "message_figures", "_basis_bound_figures": "basis_bound_figures",
    "_capex_carveout_figure": "capex_carveout_figure", "_capex_answer_expresses_none": "capex_expresses_none",
    "_commitment_answer_door": "commitment_answer_door", "_stated_limits_from_words": "stated_limits_from_words",
    "_stated_capacity_cadence": "stated_capacity_cadence", "_parse_retention_answer": "retention_answer",
    "_is_guardrail_acknowledgement": "guardrail_acknowledgement",
    "_classify_restatement_response": "restatement_classifier_model",
    "_fallback_ops_pending_milestone_from_text": "milestone_regex_fallback",
    "_extract_ops_pending_milestone_via_openai": "milestone_extractor_model",
    "_detect_people_done_adding_via_openai": "people_done_adding_model",
    "_stated_annual_figures": "stated_annual_figures", "_resolve_ops_product_line": "line_resolver",
    "_infer_figure_landing": "figure_landing_inference", "_unlanded_figures_disclosure": "unlanded_figures_disclosure",
    "_apply_forward_move": "forward_move", "_apply_cross_section_driver_correction": "cross_section_driver_correction",
    "_reconcile_driver_correction": "driver_correction_reconcile",
  },
  "client_intake_and_finmo.intake_guard.door_a": {
    "drop_unsaid_zeros": "door_a_unsaid_zeros", "numbers_in_words": "door_a_numbers_in_words",
    "_number_is_said": "door_a_number_is_said", "drop_unsaid_numbers": "door_a_unsaid_numbers",
    "_value_in_words": "door_a_value_in_words",
  },
  "client_intake_and_finmo.intake_guard.door_b": {
    "said_numbers": "door_b_said_numbers", "explained_figures": "door_b_explained_figures",
    "derived_read_backs": "door_b_derived_read_backs",
  },
  "client_intake_and_finmo.intake_guard.door_c": {
    "numbers_in_words": "door_c_numbers_in_words", "classify": "door_c_classify",
  },
  "client_intake_and_finmo.field_basis": {
    "stated_basis_in_text": "field_basis_stated_basis", "reconcile_stated_basis": "field_basis_reconcile",
  },
}


class _Cursor:
  def __init__(self, sink):
    self.sink = sink

  def execute(self, sql, params=None):
    self.sink.append(("execute", sql, params))

  def executemany(self, sql, seq):
    self.sink.append(("executemany", sql, list(seq)))

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


class _Harness(unittest.TestCase):
  def setUp(self):
    import importlib
    from flask import Flask  # type: ignore
    from client_intake_and_finmo import reader_log as RL  # type: ignore
    from client_intake_and_finmo import openai_http as OH  # type: ignore

    self.RL, self.OH = RL, OH
    self.mods = {name: importlib.import_module(name) for name in REQUIRED}
    self.app = Flask("pin")
    self.sink = []
    self._saved = (RL._connect, RL._ensured)
    RL._connect = lambda: _Conn(self.sink)
    RL._ensured = True
    self._tok = OH._GPT_RUN_IDENTITY.set({})

  def tearDown(self):
    self.RL._connect, self.RL._ensured = self._saved
    self.OH._GPT_RUN_IDENTITY.reset(self._tok)


class CountingChangesNothing(_Harness):
  def test_decorated_readers_return_what_the_undecorated_ones_return(self):
    ic = self.mods["api_handlers.intake_consult"]
    da = self.mods["client_intake_and_finmo.intake_guard.door_a"]
    fb = self.mods["client_intake_and_finmo.field_basis"]
    texts = ["Six at once, 34 a year flat out.", "About three hundred and forty most weeks.",
             "Rent is $2,400 a month and we keep about 80% of clients.", "No, we have never borrowed.", "", "1.2 million a year"]
    for text, (fn, extra) in itertools.product(texts, (
        (ic._message_figures, ()), (ic._parse_retention_answer, ()), (ic._stated_capacity_cadence, ()),
        (ic._is_guardrail_acknowledgement, ()), (da.numbers_in_words, ()), (fb.stated_basis_in_text, (2400.0,)))):
      with self.app.test_request_context():
        self.assertEqual(fn(text, *extra), fn.__wrapped__(text, *extra), "%s(%r)" % (fn.__name__, text))

  def test_an_exception_passes_through_untouched(self):
    @self.RL.reads_client_words("pin_raises")
    def boom(text):
      raise KeyError(text)
    with self.app.test_request_context():
      with self.assertRaises(KeyError):
        boom("her words")

  def test_nothing_is_noted_outside_a_request(self):
    ic = self.mods["api_handlers.intake_consult"]
    ic._message_figures("Six at once.")
    self.assertEqual(self.RL.flush(), 0)
    self.assertEqual(self.sink, [])


class EveryReadIsNotedAndWrittenOnce(_Harness):
  def test_reads_accumulate_count_and_flush_once(self):
    ic = self.mods["api_handlers.intake_consult"]
    her = "We could do 480 a week and actually do about 340."
    with self.app.test_request_context():
      from flask import g  # type: ignore
      g._turn_user_text, g._turn_index = her, 11
      self.OH.set_gpt_run_identity(draft_id=DRAFT)
      for _ in range(3):
        ic._message_figures(her)
      ic._message_figures("The app's own reply: 480 a week.")
      written = self.RL.flush()
      self.assertEqual(self.RL.flush(), 0, "a second flush wrote the same notes again")
    batches = [s for s in self.sink if s[0] == "executemany"]
    self.assertEqual(len(batches), 1)
    rows = batches[0][2]
    self.assertEqual(written, len(rows))
    by_client = {r[4]: r for r in rows if r[2] == "message_figures"}
    self.assertEqual(by_client[1][5], 3, "identical reads of her message were not counted together")
    self.assertEqual(by_client[0][5], 1)
    self.assertTrue(all(r[0] == DRAFT and r[1] == 11 for r in rows))

  def test_a_note_records_what_the_reader_was_given_without_copying_her_words(self):
    """Cowork 1064: door_a_number_is_said came back true and false with no way to
    tell which number was judged unsaid."""
    import json as _json

    @self.RL.reads_client_words("pin_is_said")
    def is_said(value, words):
      return value in (480.0, 340.0)
    her = "We could do 480 a week and actually do about 340."
    with self.app.test_request_context():
      from flask import g  # type: ignore
      g._turn_user_text, g._turn_index = her, 7
      self.OH.set_gpt_run_identity(draft_id=DRAFT)
      for value in (480.0, 100.0, 4.0):
        is_said(value, her)
      is_said(55.0, "The app's own reply mentions 55 samples a week and a great deal more besides that.")
      self.RL.flush()
    rows = [r for s in self.sink if s[0] == "executemany" for r in s[2] if r[2] == "pin_is_said"]
    by_input = {}
    for r in rows:
      args = _json.loads(r[8])["args"]
      by_input[args[0]] = (args[1], _json.loads(r[6]))
    self.assertEqual(by_input[480.0], ("<her message>", True))
    self.assertEqual(by_input[100.0], ("<her message>", False))
    self.assertEqual(by_input[4.0], ("<her message>", False))
    self.assertEqual(len(by_input[55.0][0]), 80, "other text is cut short")
    self.assertNotIn("about 340", " ".join(r[8] for r in rows), "a note copied her message")

  def test_the_cap_reports_what_it_dropped(self):
    @self.RL.reads_client_words("pin_many")
    def reader(text):
      return text
    with self.app.test_request_context(), self.assertLogs(level="WARNING") as logs:
      from flask import g  # type: ignore
      g._turn_user_text, g._turn_index = "x", 1
      self.OH.set_gpt_run_identity(draft_id=DRAFT)
      for i in range(self.RL.MAX_PER_TURN + 7):
        reader("distinct %d" % i)
      self.RL.flush()
    self.assertTrue(any("READER_EXTRACTS_CAPPED" in line and "dropped=7" in line for line in logs.output))


class EveryRequiredReaderIsCounted(_Harness):
  def test_every_reader_on_the_list_is_registered_and_wrapped(self):
    missing = []
    for mod_name, funcs in REQUIRED.items():
      mod = self.mods[mod_name]
      for fn_name, label in funcs.items():
        fn = getattr(mod, fn_name, None)
        if getattr(fn, "__reads_client_words__", None) != label:
          missing.append("%s.%s" % (mod_name, fn_name))
        if label not in self.RL.REGISTERED:
          missing.append("registry:" + label)
    self.assertEqual(missing, [])
    self.assertGreaterEqual(len(self.RL.REGISTERED), sum(len(v) for v in REQUIRED.values()))

  def test_the_request_end_writes_and_the_endpoint_returns(self):
    src = (ROOT / "python" / "api.py").read_text(encoding="utf-8-sig")
    self.assertIn("_reader_log.flush()", src)
    self.assertIn('"readers": _reader_log.for_draft(conn, draft_id)', src)


if __name__ == "__main__":
  unittest.main(verbosity=2)
