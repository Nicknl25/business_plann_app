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


class TheRouterReadsItsOwnNumberFormats(unittest.TestCase):
  def setUp(self):
    from client_intake_and_finmo.intent_router import _coerce_value_json, _parse_number_value_json  # type: ignore

    self.parse = _parse_number_value_json
    self.coerce = _coerce_value_json

  def test_every_generated_format_reads_its_value(self):
    suffixes = (("", 1), ("k", 1e3), ("K", 1e3), ("m", 1e6), ("M", 1e6), ("b", 1e9),
                (" thousand", 1e3), (" million", 1e6), (" Million", 1e6), (" billion", 1e9))
    cases = 0
    for (base_txt, base), (sfx, mult), prefix, tail in itertools.product(
        (("504", 504.0), ("18.5", 18.5), ("1,250", 1250.0), ("0.75", 0.75)),
        suffixes, ("", "$", "USD "), ("", "/month", " per week", " units")):
      if "," in base_txt and sfx:
        continue                    # "1,250k" is not a format anyone writes
      raw = "%s%s%s%s" % (prefix, base_txt, sfx, tail)
      got = self.parse(raw)
      self.assertIsNotNone(got, raw)
      self.assertAlmostEqual(got, base * mult, delta=1e-6 * max(1.0, base * mult), msg=raw)
      cases += 1
    self.assertGreater(cases, 300)

  def test_a_word_after_the_number_is_not_a_suffix(self):
    for raw, want in (("5 months", 5.0), ("12 mornings", 12.0), ("3 kits", 3.0), ("40 more", 40.0),
                      ("2 boats", 2.0), ("7 bays", 7.0)):
      self.assertEqual(self.parse(raw), want, raw)

  def test_nothing_is_not_a_number(self):
    for raw in ("", "none", "N/A", "null", "unknown", "about some", "abc"):
      self.assertIsNone(self.parse(raw), raw)

  def test_the_router_path_accepts_a_number_that_is_not_pure_json(self):
    """The regression record: before the fix every one of these failed coercion,
    and the turn became a clarify that discarded the fields beside it."""
    for raw, want in (("$504", 504.0), ("18.5k", 18500.0), ("504/month", 504.0), ("$1.2M", 1.2e6)):
      ok, val = self.coerce(value_json_raw=raw, allowed_types=["number"])
      self.assertTrue(ok, raw)
      self.assertAlmostEqual(val, want, delta=1e-6 * want, msg=raw)
    self.assertEqual(self.coerce(value_json_raw="504", allowed_types=["number"]), (True, 504))


if __name__ == "__main__":
  unittest.main(verbosity=2)
