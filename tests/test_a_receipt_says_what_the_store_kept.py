"""A RECEIPT SAYS WHAT THE STORE KEPT AFTER THE GUARDS RUN, OR SAYS NOTHING ABOUT A
HELD FIELD (Nick 2026-09-14, ruling 2, answer 1).

CW-070 turn 5 (draft 71d4e505): "(Noted: ... -> 12.)" was sent while door C held 12
back and the store kept 52. The receipt was composed from the handler's object
before the persist door ran. It is now composed inside append_messages, after door
C, from the sections that persist - for any business, any section.
"""
from __future__ import annotations

import copy
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python"), os.path.join(ROOT, "python", "client_intake_and_finmo")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo import receipt_after_guard as rag  # noqa: E402


def _ops(rows):
  return {"lob_models": [{"lob_name": "Main", "products": [dict(r) for r in rows]}]}


SHAPES = [
  # (business, before rows, handler rows (pre-guard), stored rows (door C held field 0's periods))
  ("jam maker", [{"product_name": "Jars", "unit_price": 9.5, "operating_periods_per_year": 52},
                 {"product_name": "Gift boxes", "unit_price": 30, "operating_periods_per_year": 52}],
   "operating_periods_per_year", 12, "unit_price", 11.0),
  ("boat yard", [{"product_name": "Hulls", "unit_price": 185000, "units_per_period_capacity": 6}],
   "units_per_period_capacity", 4, "unit_price", 190000),
  ("dental clinic", [{"product_name": "Cleanings", "unit_price": 120, "avg_units_per_period_year1": 40},
                     {"product_name": "Whitening", "unit_price": 300, "avg_units_per_period_year1": 5}],
   "avg_units_per_period_year1", 400, "unit_price", 125),
]


class AReceiptNamesOnlyWhatTheStoreKept(unittest.TestCase):

  def test_a_held_field_is_never_named_and_a_kept_one_is(self):
    for business, rows, held_key, held_to, kept_key, kept_to in SHAPES:
      with self.subTest(business=business):
        before = _ops(rows)
        handler = copy.deepcopy(before)
        handler["lob_models"][0]["products"][0][held_key] = held_to
        handler["lob_models"][0]["products"][0][kept_key] = kept_to
        stored = copy.deepcopy(handler)
        stored["lob_models"][0]["products"][0][held_key] = rows[0][held_key]    # door C held it back
        # the old composition (handler object) names the held value: the defect
        self.assertIn(str(held_to), rag.echo_line(before, handler, "ops").replace(",", ""))
        text = "Thanks." + rag.placeholder("ops", before, with_echo="\n\n(Noted: {echo}.)")
        out = rag.resolve(text, {"ops": stored})
        self.assertNotIn(str(held_to) + ".", out.replace(",", "") + ".")
        self.assertNotIn("[[app-receipt", out)
        self.assertIn("(Noted:", out, out)

  def test_everything_held_says_nothing(self):
    for business, rows, held_key, held_to, _k, _v in SHAPES:
      with self.subTest(business=business):
        before = _ops(rows)
        text = "Understood." + rag.placeholder("ops", before, with_echo="\n\n(Noted: {echo}.)")
        self.assertEqual(rag.resolve(text, {"ops": copy.deepcopy(before)}), "Understood.")

  def test_the_quiet_wording_is_used_when_nothing_was_kept(self):
    before = {"people": [{"role": "Owner", "annual_wage": 62000}]}
    lead = rag.placeholder("people", before, with_echo="Got it - {echo}.", without_echo="Got it - updated.")
    self.assertEqual(rag.resolve(lead + "\n\nNext.", {"people": copy.deepcopy(before)}), "Got it - updated.\n\nNext.")
    lead = rag.placeholder("people", before, with_echo="Got it - {echo}.", without_echo="Got it - updated.")
    kept = {"people": {"people": [{"role": "Owner", "annual_wage": 70000}]}}
    out = rag.resolve(lead, kept)
    self.assertNotEqual(out, "Got it - updated.")
    self.assertIn("70,000", out)

  def test_a_placeholder_is_never_a_figure_and_never_leaks(self):
    tok = rag.placeholder("ops", {}, with_echo="(Noted: {echo}.)")
    self.assertFalse(any(ch.isdigit() for ch in tok))
    self.assertEqual(rag.strip("Hello " + tok), "Hello")
    self.assertEqual(rag.resolve("Hi [[app-receipt:zzzzzzzzzzzz]]", {"ops": {}}), "Hi")
    self.assertEqual(rag.resolve("Hi " + rag.placeholder("market", {}, with_echo="x {echo}"), {}), "Hi")


class ThePersistDoorComposesItAfterDoorC(unittest.TestCase):
  """The real append_messages: door C (stubbed) holds a field; door B must receive
  a reply that does not name it. Stops before any SQL."""

  def test_door_b_sees_the_receipt_of_the_guarded_sections(self):
    import intake_consult_draft as icd  # type: ignore
    rows = SHAPES[0][1]
    before = _ops(rows)
    handler = copy.deepcopy(before)
    handler["lob_models"][0]["products"][0]["operating_periods_per_year"] = 12
    handler["lob_models"][0]["products"][1]["unit_price"] = 32
    guarded = copy.deepcopy(handler)
    guarded["lob_models"][0]["products"][0]["operating_periods_per_year"] = 52

    text = "Monthly it is." + rag.placeholder("ops", before, with_echo="\n\n(Noted: {echo}.)")
    seen = {}

    class _Stop(Exception):
      pass

    def _door_b(conn, **kw):
      seen["text"] = kw["new_messages"][-1]["content"]
      raise _Stop()

    row = {"messages_json": "[]", "operating_model_json": icd.json.dumps(before), "active_focus": "ops"}
    with mock.patch.object(icd, "get_draft", return_value=row), \
         mock.patch.object(icd, "_guard_writes_before_persist", return_value=(guarded, None, None, None)), \
         mock.patch.object(icd, "_guard_reply_before_persist", side_effect=_door_b):
      with self.assertRaises(_Stop):
        icd.append_messages(object(), draft_id="d", new_messages=[{"role": "user", "content": "treat it as monthly"},
                                                                   {"role": "assistant", "content": text}],
                            operating_model_json=handler)
    self.assertNotIn("[[app-receipt", seen["text"])
    self.assertIn("(Noted:", seen["text"])
    self.assertNotIn("12", seen["text"])
    self.assertIn("32", seen["text"])


if __name__ == "__main__":
  unittest.main()
