"""SHE SAID A SECOND THING AND IT WENT NOWHERE.

Ashworth and Delacroix Conservatory, draft d5b77aae, turn 97:

    app: "Is there a ceiling on how many people you'll employ over the plan -
          a number you won't go past? Give me the number, or tell me there
          isn't one."
    her: "No ceiling, but I WON'T CUT THE INSTRUCTORS. They are the school."
    app: "Got it. No ceiling on headcount - the plan can hire as the work
          calls for it."   <- and moved straight on

Taking "no ceiling" is right: that is the answer to the question asked. But
Nick's rule is that the REST is noted and confirmed at its own turn, never
discarded - and her second clause was a CONSTRAINT, not conversation. Thirty
turns later the coherence solve proposed "other operating costs down to
$168,000 a year" with no record anywhere that the instructors are untouchable.

There is nowhere to put it. A commitment stage holds one scalar, the extras
queue holds FIGURES and explicitly drops anything with no digits in it ("a few
contracts a year" holds no number to misplace), and no field means "a group she
will not cut". Storing it needs a field with a name Nick has agreed, so nothing
here invents one.

What this does is make the drop VISIBLE and countable - the same move CW-041
made for the misroute class before that shape was understood well enough to
guard: "until now it left no trace anywhere: only the guard's REVERTS were
logged, never the writes it let through." A commitment stage that keeps dropping
clauses now says so in the log instead of only in a transcript nobody reads.

This module pins WHAT COUNTS as a dropped clause, because a detector that fires
on everything is as useless as one that fires on nothing: a client says "signed,
eight years and three months left" and that is one answer, not two.
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python"),
          os.path.join(ROOT, "python", "client_intake_and_finmo")):
  if p not in sys.path:
    sys.path.insert(0, p)

import api_handlers.intake_consult as IC  # noqa: E402

#: Verbatim, from the two live drafts.
ASHWORTH_CEILING = ("No ceiling, but I won't cut the instructors. "
                    "They are the school.")
GRANTLEY_LEASE = "Signed, eight years left. The rent can't move."


class HerSecondClauseIsSeen(unittest.TestCase):

  def test_the_live_one(self):
    extra = IC._commitment_extra_clause(ASHWORTH_CEILING)
    self.assertTrue(extra, "her protected group was dropped without a trace")
    self.assertIn("instructors", extra)

  def test_a_constraint_on_the_lease_turn_too(self):
    """She said the rent cannot move. That is a commitment, and it is the same
    shape - an answer plus a limit."""
    self.assertIn("rent", IC._commitment_extra_clause(GRANTLEY_LEASE))

  def test_a_floor_she_states_counts(self):
    extra = IC._commitment_extra_clause(
      "No more than 20, and I won't go below 12 either.")
    self.assertIn("12", extra)

  def test_the_answer_to_the_question_asked_still_lands(self):
    """The rule is take the answer and note the rest - not hold the turn."""
    self.assertEqual(
      {"financials.staffing_ceiling": 0},
      IC._commitment_answer_door("staffing_ceiling", ASHWORTH_CEILING, {}))
    self.assertEqual(
      True,
      IC._commitment_answer_door("lease_commitment", GRANTLEY_LEASE, {})
      .get("financials.lease_signed"))


class ADetectorThatFiresOnEverythingIsUseless(unittest.TestCase):

  def test_a_plain_answer_has_no_second_clause(self):
    for words in ("Signed, fourteen years left.",
                  "No ceiling.",
                  "17.",
                  "About 26 people.",
                  "Yes, fixed by contract.",
                  "They are not fixed, we can reprice at any time."):
      self.assertEqual("", IC._commitment_extra_clause(words), words)

  def test_a_sentence_with_and_in_the_middle_of_one_fact(self):
    """"eight years and three months" is one answer, not two - the tail has to
    state something she will or will not do."""
    self.assertEqual(
      "", IC._commitment_extra_clause("Signed, eight years and three months left."))
    self.assertEqual(
      "", IC._commitment_extra_clause("About 26 people, and that is the whole team."))

  def test_a_reason_is_not_a_constraint(self):
    """"we hire as the sites come" explains her answer; it does not limit
    anything, and treating every aside as a constraint would bury the ones that
    matter."""
    self.assertEqual(
      "", IC._commitment_extra_clause("No ceiling, we hire as the sites come."))

  def test_rubbish_in_is_nothing_out(self):
    for words in ("", "   ", None, ".", "but"):
      self.assertEqual("", IC._commitment_extra_clause(words), repr(words))


class TheDropIsOnTheRecord(unittest.TestCase):

  def test_the_door_logs_it(self):
    """Counted, not lost - which is what makes the ruling on where to STORE it
    an evidence question rather than a guess.

    assertLogs, not a hand-rolled handler: the first version added a handler
    without setting a level, so logger.info was filtered out and the test
    reported "the drop left no trace" about working code."""
    with self.assertLogs(IC.logger, level="INFO") as caught:
      IC._commitment_answer_door("staffing_ceiling", ASHWORTH_CEILING, {})
    hits = [m for m in caught.output if "COMMITMENT_ANSWER_EXTRA_DROPPED" in m]
    self.assertTrue(hits, "the drop left no trace: %r" % caught.output)
    self.assertIn("instructors", hits[0])

  def test_it_names_the_stage_and_what_it_kept(self):
    with self.assertLogs(IC.logger, level="INFO") as caught:
      IC._commitment_answer_door("staffing_ceiling", ASHWORTH_CEILING, {})
    line = [m for m in caught.output
            if "COMMITMENT_ANSWER_EXTRA_DROPPED" in m][0]
    self.assertIn("staffing_ceiling", line)
    self.assertIn("No ceiling", line, "the answer it DID take")

  def test_nothing_is_logged_for_a_plain_answer(self):
    """A log line on every commitment turn would be noise nobody reads, which
    is the same as no log line at all."""
    with self.assertLogs(IC.logger, level="INFO") as caught:
      IC.logger.info("a plain answer produces only this line")
      IC._commitment_answer_door("staffing_ceiling", "No ceiling.", {})
    self.assertEqual(
      [], [m for m in caught.output if "COMMITMENT_ANSWER_EXTRA_DROPPED" in m])


class WhatThisDoesNotFixYet(unittest.TestCase):
  """Said plainly so nobody reads this module as more than instrumentation."""

  def test_there_is_still_nowhere_to_STORE_a_stated_constraint(self):
    """Her protected group and her stated hall ceiling are the same gap: a
    limit she states in words has no cell to live in, so it is acknowledged in
    prose and dropped. Both need a field with a name Nick has agreed."""
    import inspect
    from client_intake_and_finmo import intake_required_fields as rf
    self.assertNotIn("protected", " ".join(rf.FINANCIALS_COMMITMENTS_REQUIRED))
    src = inspect.getsource(IC._commitment_answer_door)
    self.assertIn("COMMITMENT_ANSWER_EXTRA_DROPPED", src,
                  "if this becomes a real write, replace this test with the "
                  "one that proves the constraint reaches the solver")


if __name__ == "__main__":
  unittest.main()
