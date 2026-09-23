"""THE SAME DOOR MUST NOT GIVE TWO ANSWERS ON ONE DRAFT.

CW-076 ASHGROVE BINDERY bf731ee4, from mini's write-path audit 2026-09-22 and
made the priority by Nick: "TURN C IS THE PRIORITY - the routed-by-the-question
door. That's the Ashgrove root and everything else has been downstream of it."

A bare driver write (a figure with no line attached) on a multi-line model is
routed by reading OUR OWN previous message: if it names exactly one line, that
is the row. The rule is sound. The IMPLEMENTATION asked whether the row's
product_name appeared VERBATIM as a substring, and on Ashgrove that decided two
turns opposite ways with nothing about the client changing:

  turn 10  "how many individual binding/repair jobs (books) do you actually
           complete"        -> no verbatim hit -> her "About eleven hundred"
           was recorded as UNROUTED and never reached a field. Her stated annual
           count is in no field in the final model.
  turn 16  "For those book binding & repair jobs, about how many weeks a year
           are you actually operating"  -> verbatim hit -> her "Forty-eight"
           LANDED, into operating_periods_per_year, and 10 x 48 = 480 replaced
           the 1,100 a year she had stated.

Same door, same draft, same two rows, opposite outcomes - decided by whether the
app had happened to spell its own line name that turn rather than paraphrase it.
Her 1,100 is missing because of a slash.

So a line is identified by what makes it DISTINCTIVE - the words of its name no
other line shares and that are not generic trade words - and plurals are folded,
so "binding/repair jobs (books)" names the book binding line as surely as
"book binding & repair job" does. Two candidates still refuse: ambiguity is
never resolved by picking, and a PARTIAL mention of a second line is ambiguity.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

import api_handlers.intake_consult as IC  # noqa: E402


def _ops(*names, lob="Primary line of business"):
  return {"lob_models": [{"lob_name": lob, "products": [
    {"product_name": n, "unit_cadence": "contract"} for n in names]}]}


def _routed(ops, sentence):
  rows = IC._rows_our_question_named(ops, sentence)
  return rows[0]["product_name"] if len(rows) == 1 else None


ASHGROVE = _ops("Book binding & repair job", "Short-run print job")

# The two sentences verbatim from the killed run.
T10 = ("Got it, we'll use 10 as the number of projects you have going at once. "
       "Got it, about ten active books at once is your practical limit for "
       "binding and repair. In a typical year, about how many individual "
       "binding/repair jobs (books) do you actually complete, start to finish?")
T16 = ("Got it, I've updated your unit price to $110. Thanks, we'll use $110 as "
       "the price per finished binding/repair book. For those book binding & "
       "repair jobs, about how many weeks a year are you actually operating?")


class TheTwoAshgroveTurnsAgree(unittest.TestCase):
  """Nick's acceptance test for this fix, in his words: whatever the fix is, it
  must make those two turns agree."""

  def test_the_turn_that_lost_her_eleven_hundred_now_routes(self):
    self.assertEqual(_routed(ASHGROVE, T10), "Book binding & repair job",
                     "her stated annual count still has no row to land on")

  def test_the_turn_that_landed_her_forty_eight_still_routes(self):
    self.assertEqual(_routed(ASHGROVE, T16), "Book binding & repair job")

  def test_they_agree(self):
    self.assertEqual(_routed(ASHGROVE, T10), _routed(ASHGROVE, T16),
                     "the same door still gives two answers on one draft")

  def test_the_other_line_is_reachable_too(self):
    self.assertEqual(
      _routed(ASHGROVE, "For the short-run printing work, when you think about "
                        "one job, what do you mean?"),
      "Short-run print job")


class AmbiguityStillRefuses(unittest.TestCase):
  """The rule this branch was built on does not move: a number put on the wrong
  line is a wrong number that reads as a real one."""

  def test_a_sentence_naming_both_lines_asks(self):
    """Only the print line matches in FULL here - "book" is missing from the
    binding line's name - so a rule that looked only at full matches would put
    a figure about both lines silently onto one."""
    self.assertIsNone(_routed(
      ASHGROVE, "Thinking about your binding, repair and short-run print work "
                "overall, how many do you get through?"))

  def test_a_sentence_naming_no_line_asks(self):
    self.assertIsNone(_routed(
      ASHGROVE, "Before we wrap up, what legal structure are you using?"))

  def test_a_generic_capacity_question_asks(self):
    """Thackeray & Nunes 53a7603f - the open-ask path this falls through to.
    Three lines, a question naming none of them, answered three times into
    nothing. It must still reach the ask."""
    stone = _ops("Residential countertops and vanities",
                 "Commercial architectural stonework", "Memorials and headstones")
    self.assertIsNone(_routed(stone, "About how many can you get through in a "
                                     "typical week?"))

  def test_two_lines_that_cannot_be_told_apart_ask(self):
    same = _ops("Countertops", "Countertops")
    self.assertIsNone(_routed(same, "About the countertops - how many at once?"))

  def test_a_line_whose_name_is_entirely_generic_never_routes_alone(self):
    """"Primary line of business / job" tells nothing apart. Refusing is the
    honest answer, not a fallback onto the first row."""
    generic = _ops("Job", "Short-run print job")
    self.assertIsNone(_routed(generic, "About the job - how many a week?"))


class TheNeighboursMiniNamed(unittest.TestCase):
  """Confirmed because this branch is shared, high-fan-out code: the case it was
  built for must keep working, and the path it falls through to must still be
  reachable."""

  TIMBER = _ops("Custom residential timber frames", "Commercial timber structures",
                "Shipped frame kits for builders", lob="Timber frames")

  def test_vasquez_lindqvist_turn_eleven_still_routes(self):
    """The case the branch exists for: "Six. That is the most the shop will
    hold", answered to a question about one named line."""
    self.assertEqual(
      _routed(self.TIMBER, "For the custom residential timber frames, about how "
                           "many can you have in progress at the same time?"),
      "Custom residential timber frames")

  def test_the_plural_fold_is_what_makes_that_work(self):
    """Without folding frames/frame, "frame" reads as distinctive to the KITS
    line, the timber-frames question reads as a partial mention of the kits, and
    a clear routing becomes a needless question. This is the pin for that."""
    self.assertEqual(
      _routed(self.TIMBER, "For the shipped frame kits for builders, how many do "
                           "you send out in a year?"),
      "Shipped frame kits for builders")

  def test_a_named_line_on_the_thackeray_shape_routes(self):
    stone = _ops("Residential countertops and vanities",
                 "Commercial architectural stonework", "Memorials and headstones")
    self.assertEqual(
      _routed(stone, "On the memorials and headstones, how many can you have "
                     "going at once?"),
      "Memorials and headstones")


class ItHoldsForAnyBusiness(unittest.TestCase):
  """Not an Ashgrove fix (Nick's standing rule). The property is: a paraphrase
  of a line's name identifies it as surely as its exact spelling, and a sentence
  that does not single one out never picks."""

  SHAPES = (
    (("Mobile dog grooming", "Salon dog grooming"),
     "for the mobile grooming side, how many dogs a day?", "Mobile dog grooming"),
    (("Wedding cakes", "Celebration cupcakes"),
     "thinking about the wedding cake work, how many can you make at once?",
     "Wedding cakes"),
    (("Roof repairs", "Full roof replacements"),
     "on the full replacements, how many a month?", "Full roof replacements"),
    (("Engine servicing", "Bodywork and paint"),
     "for bodywork and painting, how many cars at a time?", "Bodywork and paint"),
  )

  def test_a_paraphrase_identifies_the_line(self):
    for names, sentence, want in self.SHAPES:
      with self.subTest(sentence=sentence):
        self.assertEqual(_routed(_ops(*names), sentence), want)

  def test_a_sentence_about_the_business_in_general_never_picks(self):
    for names, _s, _w in self.SHAPES:
      with self.subTest(names=names):
        self.assertIsNone(_routed(_ops(*names),
                                  "How many do you do in a typical week overall?"))


if __name__ == "__main__":
  unittest.main(verbosity=2)
