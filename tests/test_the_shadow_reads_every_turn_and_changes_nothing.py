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
      ({"claims": [], "answers": [{"question_quote": "How many can the shop hold at once?", "outcome": "decline",
                                   "option": None,
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
      (draft, t, sha, chars, version, model, status, err, elapsed, tin, tout, interp_json, qf_json,
       checks_json, context_mode, claims_total, claims_blocked) = rows[0]
      self.assertEqual((draft, t, chars, version, status), (DRAFT, turn, len(ISADORA), "v1.3", "ok"), err)
      self.assertEqual(json.loads(interp_json), interp)
      self.assertEqual((tin, tout), (9000, 250))
      self.assertEqual(json.loads(qf_json), bad)
      checks = json.loads(checks_json)
      self.assertEqual(checks["quote_failures"], bad)
      # v1.2 (Cowork 1078): the context is on the row, and so is the block count
      self.assertEqual(context_mode, "parity_last_assistant_only")
      self.assertEqual((claims_total, claims_blocked), (len(interp["claims"]), checks["claims_blocked"]))
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

  def test_the_contract_checks_its_own_output_by_position_and_presence(self):
    """Cowork 1062, measured rather than eyeballed, for any claim shape."""
    msg = "In practice we're doing about three hundred and forty most weeks. The accreditation caps us at 480."
    # span excess: the parts span 40 characters of a 65-character surface -> 25
    c2 = _claim("In practice we're doing about three hundred and forty most weeks.", kind="actual", value_number=340,
                per="week", value_surface="three hundred and forty", unit_surface="most weeks",
                qualifier_surface="about")
    checks = self.S.contract_checks({"claims": [c2]}, msg)
    self.assertEqual(checks["span_excess_chars"], {"claims[0]": 25})
    self.assertEqual(checks["subspan_failures"], [])
    tight = dict(c2, surface="about three hundred and forty most weeks")
    self.assertEqual(self.S.contract_checks({"claims": [tight]}, msg)["span_excess_chars"], {})
    # a part not inside its surface
    wrong = dict(tight, unit_surface="a week")
    self.assertEqual(self.S.contract_checks({"claims": [wrong]}, msg)["subspan_failures"], ["claims[0].unit_surface"])
    # a figure loose in a text claim, and a reason stored as a claim
    for value, text in itertools.product((480, 340, 1250), ("The accreditation caps us at %s", "about %s a week")):
      shown = format(value, ",") if value >= 1000 else str(value)
      numeric = _claim("x", kind="ceiling", value_number=value, firmness="fixed",
                       firmness_reason_surface="The accreditation caps us")
      loose = _claim("y", kind="text", value_number=None, value_text=text % shown)
      got = self.S.contract_checks({"claims": [numeric, loose]}, "x y")
      self.assertEqual(got["figure_in_text_claim"], ["claims[1]"], text % shown)
    reason = _claim("z", kind="text", value_number=None, value_text="The accreditation caps us")
    numeric = _claim("x", kind="ceiling", value_number=480, firmness="fixed",
                     firmness_reason_surface="The accreditation caps us")
    self.assertEqual(self.S.contract_checks({"claims": [numeric, reason]}, "x z")["reason_as_claim"], ["claims[1]"])
    clean = _claim("w", kind="text", value_number=None, value_text="Environmental testing lab")
    got = self.S.contract_checks({"claims": [numeric, clean]}, "x w")
    self.assertEqual((got["figure_in_text_claim"], got["reason_as_claim"]), ([], []))

  def test_a_claim_addresses_a_row_and_the_prompt_forbids_guessing_the_product(self):
    props = self.S.SCHEMA["properties"]["claims"]["items"]["properties"]
    for key in ("line", "product", "value_surface", "unit_surface", "qualifier_surface"):
      self.assertIn(key, props)
    for rule in ("the ROW it is about", "do NOT pick one", "A REASON IS NEVER A CLAIM OF ITS OWN",
                 "never repeats a figure"):
      self.assertIn(rule, self.S.SYSTEM)

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


# v1.2 (Nick ruled 2026-09-14; Cowork 1078) ------------------------------------
LAB_MSG = ("The lab takes 480 a week when everything’s running — in practice about three hundred and forty "
           "most weeks. The accreditation caps us at 480. Our back‑office is small.")
APP_MSG = "Is it option one or option two? How many can the lab take in a week?"
LAB_LINES = [{"line_of_business": "Lab", "product": "A-110", "cadence": "week"}]


def _good_claims():
  return [
    _claim("480 a week", kind="ceiling", value_number=480, per="week", value_surface="480", unit_surface="a week",
           line="Lab", product="A-110"),
    _claim("about three hundred and forty most weeks", kind="actual", value_number=340, per="week",
           value_surface="three hundred and forty", unit_surface="most weeks", qualifier_surface="about",
           line="Lab", product="A-110", refers_to=["A-110"]),
    _claim("caps us at 480", kind="ceiling", value_number=480, per="week", value_surface="480", firmness="fixed",
           firmness_direction="up_only", firmness_reason_surface="The accreditation caps us", refers_to=["Lab"],
           line="Lab", product="A-110"),
  ]


_ROW = {"line": "Lab", "product": "A-110"}
_DEFECTS = {
  "quote_failures": lambda: _claim("five hundred a week", value_number=500, per="week", **_ROW),
  "subspan_failures": lambda: _claim("480 a week", value_number=480, per="week", unit_surface="per week", **_ROW),
  "figure_in_text_claim": lambda: _claim("caps us at 480", kind="text", value_number=None, value_text="caps us at 480"),
  "reason_as_claim": lambda: _claim("The accreditation caps us", kind="text", value_number=None,
                                    value_text="The accreditation caps us"),
  "row_outside_lines": lambda: _claim("480 a week", value_number=480, per="week", line="Bakery", product="A-110"),
  "row_missing": lambda: _claim("480 a week", kind="ceiling", value_number=480, per="week", line=None, product=None),
  "refers_to_outside_closed_set": lambda: _claim("480 a week", value_number=480, per="week",
                                                 refers_to=["the other one"], **_ROW),
  "figure_in_machine_field": lambda: _claim("480 a week", value_number=480, per="week", subject="ops.capacity 480",
                                            **_ROW),
  "bad_ids": lambda: _claim("480 a week", value_number=480, per="week", id="capacity-claim", **_ROW),
  "bad_currency": lambda: _claim("480 a week", value_number=480, per="week", currency="dollars", **_ROW),
  "number_with_range": lambda: _claim("480 a week", kind="typical", value_number=5.5, value_low=5, value_high=6,
                                      per="week", **_ROW),
}


class TheContractClassifiesEveryStringAndNamesWhatBlocks(_Harness):
  def test_every_string_field_in_the_schema_is_classified(self):
    found = {}
    for group, node in self.S.SCHEMA["properties"].items():
      for prop, spec in node["items"]["properties"].items():
        types = spec.get("type") if isinstance(spec.get("type"), list) else [spec.get("type")]
        if "string" in types:
          found["%s.%s" % (group, prop)] = "enum" if "enum" in spec else "free"
        elif "array" in types and (spec.get("items") or {}).get("type") == "string":
          found["%s.%s[]" % (group, prop)] = "free"
    self.assertEqual(set(found), set(self.S.STRING_FIELDS), "a string field is unclassified, or a class names nothing")
    for path, shape in found.items():
      cls = self.S.STRING_FIELDS[path]
      self.assertIn(cls, ("quote_her", "quote_app", "closed_set", "machine", "enum"), path)
      self.assertEqual(cls == "enum", shape == "enum", path)
    self.assertEqual(set(self.S.BLOCKING), set(_DEFECTS), "every blocking check has a defect that proves it blocks")
    self.assertFalse(set(self.S.BLOCKING) & set(self.S.RECORD_ONLY))

  def test_every_quoted_field_is_checked_against_its_own_source(self):
    invented = "words nobody wrote"
    for path, cls in self.S.STRING_FIELDS.items():
      if cls not in ("quote_her", "quote_app"):
        continue
      group, field = path.split(".")
      if group == "claims":
        item = _claim("480 a week", value_number=480, per="week", value_surface="480")
      elif group == "answers":
        item = {"question_quote": "How many can the lab take in a week?", "outcome": "choose",
                "option": "option one", "surface": "480 a week"}
      elif group == "unresolved":
        item = {"surface": "480 a week", "value_number": 480, "why": "which_line", "candidates": ["ops.capacity"]}
      else:
        item = {"surface": "480 a week"}
      clean = {group: [dict(item)]}
      self.assertEqual(self.S.quote_failures(clean, LAB_MSG, APP_MSG), [], path)
      item[field] = invented
      want = "%s[0]" % group if field == "surface" else "%s[0].%s" % (group, field)
      self.assertEqual(self.S.quote_failures({group: [item]}, LAB_MSG, APP_MSG), [want], path)
      # a quote from the app's message is not hers, and hers is not the app's
      item[field] = "How many can the lab take in a week?" if cls == "quote_her" else "480 a week"
      self.assertEqual(self.S.quote_failures({group: [item]}, LAB_MSG, APP_MSG), [want], path)

  def test_the_normal_form_rescues_typography_and_nothing_else(self):
    exact = ("back‑office", "everything’s running — in practice", "caps us at 480")
    typographic = ("back-office", "back‐office", "everything's running - in practice",
                   "everything’s running – in practice", "back‑office is small",
                   "everything’s  running — in practice", "“caps us at 480”"[1:-1])
    invented = ("Back-office", "backoffice", "back office", "everything is running", "three hundred and fourty",
                "4800 a week", "480 a Week", "480, a week", "caps us at 48O", "running in practice")
    for s in exact:
      self.assertEqual(self.S.quote_grade(s, LAB_MSG), "exact", s)
    for s in typographic:
      self.assertEqual(self.S.quote_grade(s, LAB_MSG), "normalised" if s not in LAB_MSG else "exact", s)
    for s in invented:
      self.assertEqual(self.S.quote_grade(s, LAB_MSG), "invented", s)
    self.assertEqual(self.S.quote_grade("", LAB_MSG), "invented")
    # a normalised quote passes and is recorded apart from a failure - never alike
    c = _claim("everything's running - in practice about three hundred and forty most weeks", kind="actual",
               value_number=340, per="week", value_surface="three hundred and forty", unit_surface="most weeks",
               qualifier_surface="about", line="Lab", product="A-110")
    checks = self.S.contract_checks({"claims": [c]}, LAB_MSG, APP_MSG, LAB_LINES)
    self.assertEqual((checks["quote_failures"], checks["quote_normalised"]), ([], ["claims[0]"]))
    self.assertEqual(checks["blocked"], [], "a normalised quote or a wide span must not block")
    self.assertTrue(checks["span_excess_chars"])
    # the surface normalised, its parts still carrying her typography: not a broken span, not a block
    for surface, part in (("everything's running - in practice", "everything’s running — in practice"),
                          ("back-office is small", "back‑office"), ("back‑office is small", "back-office")):
      c = _claim(surface, kind="text", value_number=None, value_text=None, qualifier_surface=part)
      got = self.S.contract_checks({"claims": [c]}, LAB_MSG, APP_MSG, LAB_LINES)
      self.assertEqual((got["subspan_failures"], got["blocked"], got["quote_failures"]), ([], [], []), (surface, part))
    broken = _claim("back-office is small", kind="text", value_number=None, qualifier_surface="front-office")
    self.assertEqual(self.S.contract_checks({"claims": [broken]}, LAB_MSG)["subspan_failures"],
                     ["claims[0].qualifier_surface"], "the normal form must not rescue different words")

  def test_a_blocked_claim_goes_unresolved_and_the_claims_beside_it_stand(self):
    for (name, make), at in itertools.product(_DEFECTS.items(), (0, 1, 3)):
      claims = _good_claims()
      claims.insert(at, make())
      for k, c in enumerate(claims):
        if not (name == "bad_ids" and k == at):
          c["id"] = "c%d" % (k + 1)
      checks = self.S.contract_checks({"claims": claims}, LAB_MSG, APP_MSG, LAB_LINES)
      self.assertTrue(checks[name], "%s did not fire" % name)
      self.assertEqual(checks["blocked"], ["claims[%d]" % at], "%s at %d blocked %s" % (name, at, checks["blocked"]))
      self.assertEqual((checks["claims_total"], checks["claims_blocked"]), (4, 1), name)
    good = _good_claims()
    for k, c in enumerate(good):
      c["id"] = "c%d" % (k + 1)
    self.assertEqual(self.S.contract_checks({"claims": good}, LAB_MSG, APP_MSG, LAB_LINES)["blocked"], [])

  def test_a_referent_is_a_claim_id_or_a_supplied_row_and_nothing_else(self):
    base = _good_claims()
    for k, c in enumerate(base):
      c["id"] = "c%d" % (k + 1)
    for ref, ok in (("c1", True), ("c3", True), ("Lab", True), ("A-110", True), ("c9", False), ("the other one", False),
                    ("lab", False), ("ops.capacity", False)):
      claims = [dict(c) for c in base]
      claims[1]["refers_to"] = [ref]
      got = self.S.contract_checks({"claims": claims}, LAB_MSG, APP_MSG, LAB_LINES)["refers_to_outside_closed_set"]
      self.assertEqual(got, [] if ok else ["claims[1].refers_to[0]"], ref)
    # a product identity from the app's own rows is not a figure; a figure in a machine field is
    self.assertEqual(self.S.contract_checks({"claims": base}, LAB_MSG, APP_MSG, LAB_LINES)["figure_in_machine_field"], [])
    for subject in ("ops.capacity_480", "three a week", "half the capacity", "financials.rent 2400",
                    "market.customer_retention_if_price_34", "financials.payroll_unlabeled_144k"):
      c = dict(base[0], subject=subject)
      self.assertEqual(self.S.contract_checks({"claims": [c]}, LAB_MSG)["figure_in_machine_field"],
                       ["claims[0].subject"], subject)
    # the app's own identifiers are not figures (55 of 59 flags on the archive were these)
    for subject in ("financials.marketing_total_year1", "financials.q1_revenue", "people.owner_1.annual_wage",
                    "ops.avg_units_per_week_year1", "people.key_person_2_compensation"):
      c = dict(base[0], subject=subject)
      self.assertEqual(self.S.contract_checks({"claims": [c]}, LAB_MSG)["figure_in_machine_field"], [], subject)
    # an empty row is not a right row - for a ROW QUANTITY (by kind); business-wide figures carry none
    for subject, kind, value, want in (("ops.capacity", "ceiling", 480, ["claims[0]"]),
                                       ("ops.price", "price", 480, ["claims[0]"]),
                                       ("ops.running_costs", "cost", 480, []),
                                       ("ops.cost_structure_option", "choice", 2, []),
                                       ("financials.rent", "cost", 2400, []),
                                       ("ops.milestones", "text", None, [])):
      c = _claim("480 a week", subject=subject, value_number=value, kind=kind,
                 value_text=None if value else "480 a week")
      self.assertEqual(self.S.contract_checks({"claims": [c]}, LAB_MSG, APP_MSG, LAB_LINES)["row_missing"], want, subject)
    # a row is addressed by its pair, by a product unique among the rows, or by a line with one product
    two = LAB_LINES + [{"line_of_business": "Field", "product": "Soil kit", "cadence": "week"},
                       {"line_of_business": "Field", "product": "Water kit", "cadence": "week"}]
    for line, product, outside, missing in (("Lab", "A-110", [], []), (None, "A-110", [], []), ("Lab", None, [], []),
                                            ("Field", None, [], ["claims[0]"]), (None, None, [], ["claims[0]"]),
                                            (None, "Nope", ["claims[0]"], []), ("Field", "A-110", ["claims[0]"], [])):
      c = _claim("480 a week", kind="ceiling", value_number=480, line=line, product=product)
      got = self.S.contract_checks({"claims": [c]}, LAB_MSG, APP_MSG, two)
      self.assertEqual((got["row_outside_lines"], got["row_missing"]), (outside, missing), (line, product))
    # a claim is never a copy of its OWN reason
    own = _claim("I do not want them added on top", kind="choice", value_number=None,
                 value_text="I do not want them added on top", firmness_reason_surface="I do not want them added on top")
    self.assertEqual(self.S.contract_checks({"claims": [own]}, LAB_MSG)["reason_as_claim"], [])
    self.assertEqual(self.S.contract_checks({"claims": [_claim("480 a week", value_number=480)]}, LAB_MSG)["row_missing"],
                     [], "with no rows supplied there is no row to miss")
    unresolved = [{"surface": "480 a week", "value_number": 480, "why": "earlier_referent", "candidates": ["ops.capacity"]},
                  {"surface": "480 a week", "value_number": 480, "why": "which_line", "candidates": ["ops.capacity"]}]
    self.assertEqual(self.S.contract_checks({"unresolved": unresolved}, LAB_MSG)["unexpressible_referents"], 1)
    self.assertIn("earlier_referent", self.S.UNRESOLVED_WHY)

  def test_the_prompt_carries_the_v12_rules(self):
    for rule in ("value_text is HER WORDS, copied character for character", "ONLY a claim id from this interpretation",
                 "why earlier_referent", "NEVER carries a figure", "copied verbatim from the app's last message",
                 "for a range value_number stays null"):
      self.assertIn(rule, self.S.SYSTEM)


if __name__ == "__main__":
  unittest.main(verbosity=2)
