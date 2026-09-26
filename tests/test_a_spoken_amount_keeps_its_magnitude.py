"""Keir & Halloway 2026-09-25: a spoken amount keeps its magnitude.

Rosalind Keir said her nine fabricators earn "about six hundred and twenty
thousand dollars a year total". The app READ it right - one turn later it
asked "is Dev ($95,000) inside that $620,000?" - and then wrote **$620**.

The figure parser was the cause, at two sites:

  1. `_normalize_word_numbers` only ever reached "<one..nine> hundred", so
     every other spoken amount arrived with NO digits at all and the parser
     fell back to a fragment: "eighteen thousand a month" -> 18, "about
     ninety-five thousand" -> 95, "six hundred and twenty thousand" -> 620.
  2. `_message_figures` then ran two passes over "340 thousand" and emitted
     BOTH 340 and 340000, with the BARE figure FIRST - so any consumer
     taking the first figure took the wrong one.

The consequences in one run: her rest-of-team pay became $620, then the
open payroll hold swallowed her next two answers at the same 1/1000 scale
(accounts payable $340,000 -> $340, inventory $280,000 -> $280). The hold
could never close, and the app re-asked one question for 85 of 140 turns.
The intake never completed.

These are properties over the ways people say money, not Keir's sentences.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "python",
                             "client_intake_and_finmo"))

from api_handlers.intake_consult import (  # noqa: E402
    _message_figures,
    _normalize_word_numbers,
)

# (what a person says, what they mean)
SPOKEN_AMOUNTS = [
    ("about six hundred and twenty thousand dollars a year total", 620000),
    ("we've got about three hundred and forty thousand dollars in supplier "
     "invoices outstanding", 340000),
    ("about two hundred and eighty thousand dollars worth of steel", 280000),
    ("about a hundred and forty thousand a year", 140000),
    ("about ninety-five thousand", 95000),
    ("eighteen thousand dollars a month", 18000),
    ("nine thousand dollars a month", 9000),
    ("about sixty thousand a year", 60000),
    ("two hundred and ten thousand in the bank", 210000),
    ("four hundred thousand of my own", 400000),
    ("one thousand one hundred dollars a job", 1100),
    ("two thousand four hundred dollars a tonne", 2400),
    ("eight hundred and fifty dollars a unit", 850),
    ("twelve hundred a week", 1200),
    ("twenty-five thousand", 25000),
    ("twenty five thousand", 25000),
    ("about one point six million", 1600000),
    ("about three point eight million", 3800000),
    ("three million eight hundred thousand", 3800000),
    ("one point four five million", 1450000),
    ("about 45k a year", 45000),
    ("we did 2.5 million last year", 2500000),
    ("one hundred and eighty-five", 185),
    ("forty-two percent", 42),
    ("about seventy percent", 70),
    ("about forty tonnes a week", 40),
]

# A YEAR IS NOT AN AMOUNT, and a bare count is not a compound.
NOT_JOINED = [
    ("since April twenty sixteen", 36),
    ("we started in twenty nineteen", 39),
    ("nine fabricators and fitters", 9000),
    ("we have eleven people on payroll", 11000),
]


# SENTENCE-FINAL PUNCTUATION (mini 2026-09-25). The first version of this pin
# had 26 rows and NOT ONE of them ended in a full stop - a check shaped like
# verification. Keeping "." inside a word token made "hundred." unknown to the
# scale table, so a spoken amount that ended a sentence misread, and
# "Three million eight hundred thousand." became 3,000,800,000 - which the
# unlanded backstop then offered as her current revenue. These rows are real
# client messages from the 4,460-message corpus.
SENTENCE_FINAL = [
    ("About five hundred.", 500),
    ("Six thousand eight hundred.", 6800),
    ("Thirty-eight thousand four hundred.", 38400),
    ("Three million eight hundred thousand.", 3800000),
    ("About one million one hundred and eighty thousand.", 1180000),
    ("About three point eight million.", 3800000),
    ("About twenty thousand.", 20000),
    ("About a hundred eighty-five thousand.", 185000),
    ("About a hundred forty-five thousand.", 145000),
    ("about four hundred twenty thousand.", 420000),
    ("We're at about thirty-five hundred.", 3500),
    ("it lands right around eleven thousand five hundred.", 11500),
    ("About forty-six thousand.", 46000),
]

# A RANGE IS NOT A SUM, and a fraction is not "one of it".
NEVER_SUMMED = [
    ("between five and six thousand", 11000),
    ("half a million", 1000000),
    ("a quarter of a million", 1000000),
]


class ASpokenAmountKeepsItsMagnitude(unittest.TestCase):

  def test_the_amount_she_said_is_in_the_figures(self):
    for said, meant in SPOKEN_AMOUNTS:
      figs = _message_figures(said)
      self.assertTrue(
          any(abs(f - meant) < 0.01 for f in figs),
          "%r means %s; the parser saw %s" % (said, meant, figs))

  def test_the_wrong_scale_is_not_offered_first(self):
    """The bug was not that 620000 was missing - it was that 620 came
    out FIRST, so a consumer taking figures[0] took the wrong one."""
    for said, meant in SPOKEN_AMOUNTS:
      if meant < 1000:
        continue
      figs = _message_figures(said)
      self.assertTrue(figs, "%r produced no figures" % said)
      for wrong in (meant / 1000.0, meant / 100.0):
        if wrong < 1 or abs(wrong - round(wrong)) > 1e-9:
          continue
        if abs(figs[0] - wrong) < 0.01:
          self.fail("%r: the parser offers %s before %s"
                    % (said, figs[0], meant))

  def test_a_year_is_never_added_up(self):
    for said, never in NOT_JOINED:
      figs = _message_figures(said)
      self.assertFalse(
          any(abs(f - never) < 0.01 for f in figs),
          "%r must not produce %s; got %s" % (said, never, figs))

  def test_a_spoken_amount_that_ends_a_sentence_still_reads(self):
    """Real client messages, with the punctuation they were typed with."""
    for said, meant in SENTENCE_FINAL:
      figs = _message_figures(said)
      self.assertTrue(
          any(abs(f - meant) < 0.01 for f in figs),
          "%r means %s; the parser saw %s" % (said, meant, figs))

  def test_every_row_also_reads_with_a_question_or_exclamation(self):
    for said, meant in SENTENCE_FINAL + SPOKEN_AMOUNTS:
      for end in (".", "?", "!"):
        probe = said.rstrip(".?! ") + end
        figs = _message_figures(probe)
        self.assertTrue(
            any(abs(f - meant) < 0.01 for f in figs),
            "%r means %s; the parser saw %s" % (probe, meant, figs))

  def test_no_spoken_amount_is_ever_read_as_a_billion(self):
    """The failure mode that reached a client-facing proposal: a scale word
    swallowed by punctuation multiplied the whole run."""
    for said, meant in SENTENCE_FINAL + SPOKEN_AMOUNTS:
      for end in ("", ".", "?", "!"):
        figs = _message_figures(said.rstrip(".?! ") + end)
        for f in figs:
          self.assertLess(
              f, max(meant * 100, 1e9),
              "%r produced %s, far above the %s she said" % (said, f, meant))

  def test_a_range_is_not_summed_and_a_fraction_is_not_one_of_it(self):
    for said, never in NEVER_SUMMED:
      figs = _message_figures(said)
      self.assertFalse(
          any(abs(f - never) < 0.01 for f in figs),
          "%r must not produce %s; got %s" % (said, never, figs))

  def test_a_bare_count_word_stays_a_word(self):
    """Pre-2026-09-25 behaviour: a lone unit word is not digitised, so
    "nine fabricators" does not start emitting new figures into the
    guards that never saw them before."""
    for said in ("nine fabricators and fitters", "one of our customers",
                 "we have eleven people on payroll"):
      self.assertEqual(_normalize_word_numbers(said), said,
                       "%r was rewritten" % said)

  def test_her_whole_intake_reads(self):
    """Every money sentence Rosalind Keir spoke, in one pass - the run
    that died. Each must yield its own amount and nothing 1000x off."""
    for said, meant in SPOKEN_AMOUNTS[:14]:
      figs = _message_figures(said)
      self.assertIn(True, [abs(f - meant) < 0.01 for f in figs],
                    "%r -> %s" % (said, figs))
      self.assertNotIn(True, [abs(f - meant / 1000.0) < 0.01 for f in figs
                              if meant >= 1000],
                       "%r still offers the 1/1000 reading: %s"
                       % (said, figs))


if __name__ == "__main__":
  unittest.main()
