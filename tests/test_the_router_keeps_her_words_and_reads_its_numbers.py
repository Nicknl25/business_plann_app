"""The router keeps her words whole, and reads its own numbers.

Nick, 2026-09-14, ruled first before the one-reader build - two defects whose
failure modes feed each other:

1. unresolved_figures.client_words was cut to 160 characters. It is the only
   surface form of her sentence that survives the router, and a 160-character
   cut lands before the ceiling and the reason in both sentences that killed
   runs that week (Isadora, CW-068: "...34 would be flat out ... that's the
   building"; Marchetti, CW-069: "...The accreditation caps us at 480"). Door C
   read the same words back to her through the same 160 cut.

2. intent_router.py:829, the parser for a number-like value_json that is not
   pure JSON ("$504", "18.5k", "504/month"), had every "?" replaced by an
   apostrophe and could never match. The field then failed coercion, the turn
   became a clarify, and every valid field beside it was discarded.

MEASURED BEFORE FIXING, said plainly: in 7,839 stored router responses the cap
cut her words once, and no patch value needed the broken path - the router
quotes short phrases and the strict schema keeps values parseable. The defects
are real; the damage in the stores so far is small. These pins state the
behaviour for any sentence and any number format, not for one draft.
"""
from __future__ import annotations

import itertools
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

ISADORA = ("Six. That's the most the shop will hold, and we're usually running five or six. A frame takes about "
           "ten weeks from design through to raising it. Over a year that works out around 26 of them, and 34 would "
           "be flat out. We can't go past six at once whatever the demand, that's the building.")
MARCHETTI = ("Four hundred and eighty a week is what the lab can take when everything's running properly. In practice "
             "we're doing about three hundred and forty most weeks. The accreditation caps us at 480, we can't just "
             "decide to do more.")


class HerWordsSurviveTheRouterWhole(unittest.TestCase):
  def setUp(self):
    from client_intake_and_finmo.intent_router import _clean_unresolved_figures  # type: ignore

    self.clean = _clean_unresolved_figures

  def test_any_length_of_words_is_kept_verbatim(self):
    for n in (1, 40, 159, 160, 161, 287, 600, 5000):
      words = ("é" + "a figure she said, with its reason " * 200)[:n]
      out = self.clean([{"value_json": "40", "client_words": words, "candidate_fields": ["unit_price"]}],
                       ["unit_price"])
      self.assertEqual(out[0]["client_words"], words, "length %d was altered" % n)

  def test_the_two_sentences_that_killed_runs_keep_their_ceiling_and_reason(self):
    for sentence, tail in ((ISADORA, "that's the building."), (ISADORA, "34 would be flat out"),
                           (MARCHETTI, "The accreditation caps us at 480")):
      self.assertGreater(len(sentence), 160)
      out = self.clean([{"value_json": "6", "client_words": sentence, "candidate_fields": []}], [])
      self.assertIn(tail, out[0]["client_words"])

  def test_the_other_limits_are_unchanged(self):
    raw = [{"value_json": str(i), "client_words": "w%d" % i, "candidate_fields": list("abcdef")} for i in range(8)]
    out = self.clean(raw, list("abcdef"))
    self.assertEqual(len(out), 5)
    self.assertTrue(all(len(f["candidate_fields"]) == 4 for f in out))

  def test_door_c_reads_her_words_back_whole(self):
    from client_intake_and_finmo.intake_guard.door_c import _capacity_or_field_question  # type: ignore

    for sentence in (ISADORA, MARCHETTI, "about 40 a week"):
      for keys in (("ops.a", "ops.a"), ("ops.a", "ops.b")):
        q = _capacity_or_field_question(keys[0], keys[1], 6.0, {"client_words": sentence})
        self.assertIn('you said "%s"' % sentence, q)


class TheRouterHasNoFallbackNumberParser(unittest.TestCase):
  """CHANGED 2026-09-14 (Nick ruled): the line-829 parser was restored this
  morning and is now DELETED. It re-parsed a number-like value_json that was not
  valid JSON - a fallback parser behind the interpretation, which R3 rules out.
  Measured first: 7,839 stored router responses never needed it. A number now
  arrives as valid JSON or it does not arrive."""

  def setUp(self):
    from client_intake_and_finmo import intent_router as IR  # type: ignore

    self.IR = IR

  def test_the_fallback_parser_does_not_exist(self):
    self.assertFalse(hasattr(self.IR, "_parse_number_value_json"))
    src = (ROOT / "python" / "client_intake_and_finmo" / "intent_router.py").read_text(encoding="utf-8-sig")
    self.assertNotIn("def _parse_number_value_json", src)

  def test_a_number_that_is_not_valid_json_is_refused_whatever_its_format(self):
    for raw in ("$504", "18.5k", "504/month", "$1.2M", "about 40", "1,250", "40 a week", "five"):
      self.assertEqual(self.IR._coerce_value_json(value_json_raw=raw, allowed_types=["number"]), (False, None), raw)

  def test_a_number_that_is_valid_json_still_arrives(self):
    for raw, want in (("504", 504), ("18.5", 18.5), ("0", 0), ("1250000", 1250000)):
      self.assertEqual(self.IR._coerce_value_json(value_json_raw=raw, allowed_types=["number"]), (True, want), raw)


if __name__ == "__main__":
  unittest.main(verbosity=2)
