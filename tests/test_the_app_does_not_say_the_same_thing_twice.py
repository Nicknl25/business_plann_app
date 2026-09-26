"""THE APP DOES NOT SAY THE SAME THING TWICE (Nick 2026-09-26).

  "A question that cannot be answered was asked 71 times. Nothing gave up,
   nothing escalated, nothing noticed it had said the same thing twice.
   That's universal and it's the worse of the two, because it turns any
   unanswerable state into a dead run."

Three consecutive runs, three DIFFERENT sites, the client answering every
time:

  * the coherence anchor hold      - 71 repeats
  * "I couldn't tell which line"   - 24 repeats
  * a retention price confirm      - 80 repeats, 57% of a whole run

Each site had its own escalation ladder or none at all, so fixing them one
at a time only moved the dead end to the next site. The rule therefore
lives at the ONE DOOR every reply passes through, and covers sites nobody
has hit yet.

It never rewrites meaning and never drops a turn - it appends one line
saying the app is stuck and inviting anything at all, so the text differs,
the identical question is not put again, and the conversation can leave a
state nobody anticipated.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "python",
                             "client_intake_and_finmo"))

from client_intake_and_finmo.intake_consult_draft import (  # noqa: E402
    _break_repeat_reply,
    _reply_fingerprint,
    _REPEAT_STUCK_NOTE,
)

# the three real loops, verbatim in shape
COHERENCE = ("Let's cut through this: name the stored number that's wrong "
             "and the figure it should be - for example 'capacity is 80 a "
             "month' or 'the price is $2,400' - and I'll set it everywhere.")
WHICH_LINE = ("One thing I couldn't place: that sounds like a capacity "
              "change, but I couldn't tell which line you meant. Tell me "
              "the line and the number and I'll set it.")
RETENTION = ("Quick check on the new price before we lean on it: at "
             "Fabrication jobs at $2,400.00, Repair and maintenance "
             "callouts at $1,100.00, what share of customers stay?")


def _asst(text):
  return {"role": "assistant", "content": text}


def _said_before(text):
  return [_asst(text), {"role": "user", "content": "I already told you"}]


class TheAppDoesNotSayTheSameThingTwice(unittest.TestCase):

  def test_each_of_the_three_real_loops_is_broken(self):
    for q in (COHERENCE, WHICH_LINE, RETENTION):
      out = _break_repeat_reply([_asst(q)], _said_before(q))
      self.assertNotEqual(q, out[0]["content"],
                          "this question would have repeated: %r" % q[:60])
      self.assertIn(_REPEAT_STUCK_NOTE, out[0]["content"])

  def test_the_question_itself_is_never_lost(self):
    """It appends; it does not replace. She must still see what was asked."""
    out = _break_repeat_reply([_asst(RETENTION)], _said_before(RETENTION))
    self.assertIn(RETENTION.strip(), out[0]["content"])

  def test_a_different_question_is_untouched(self):
    other = "What do you pay each month for the space you use?"
    out = _break_repeat_reply([_asst(other)], _said_before(RETENTION))
    self.assertEqual(other, out[0]["content"])

  def test_the_same_question_with_new_numbers_is_still_a_repeat(self):
    """Deliberate: the coherence hold moved its numbers while going
    nowhere. One extra sentence costs nothing; a dead run costs the lot."""
    moved = RETENTION.replace("2,400.00", "1,750.00")
    self.assertEqual(_reply_fingerprint(RETENTION),
                     _reply_fingerprint(moved))
    out = _break_repeat_reply([_asst(moved)], _said_before(RETENTION))
    self.assertIn(_REPEAT_STUCK_NOTE, out[0]["content"])

  def test_it_never_fires_twice_on_itself(self):
    """The note must not accumulate turn after turn."""
    once = _break_repeat_reply([_asst(RETENTION)], _said_before(RETENTION))
    twice = _break_repeat_reply(once, _said_before(RETENTION) + once)
    self.assertEqual(1, twice[0]["content"].count(_REPEAT_STUCK_NOTE))

  def test_a_short_reply_is_not_matched(self):
    """'Got it.' recurring is not a loop."""
    for short in ("Got it.", "Understood.", "Thanks."):
      out = _break_repeat_reply([_asst(short)], _said_before(short))
      self.assertEqual(short, out[0]["content"])

  def test_an_old_question_outside_the_window_is_not_a_loop(self):
    """A question legitimately revisited much later is allowed."""
    old = _said_before(RETENTION) + [_asst("A") for _ in range(8)]
    out = _break_repeat_reply([_asst(RETENTION)], old)
    self.assertEqual(RETENTION, out[0]["content"])

  def test_an_empty_or_missing_assistant_turn_is_safe(self):
    self.assertEqual([], _break_repeat_reply([], _said_before(RETENTION)))
    user_only = [{"role": "user", "content": "hello"}]
    self.assertEqual(user_only,
                     _break_repeat_reply(user_only, _said_before(RETENTION)))
    blank = [_asst("   ")]
    self.assertEqual(blank, _break_repeat_reply(blank, _said_before("   ")))

  def test_a_receipt_placeholder_does_not_defeat_the_match(self):
    """Two replies differing only by a random receipt token are the same
    question."""
    a = RETENTION + " [[app-receipt:abcdefghijkl]]"
    b = RETENTION + " [[app-receipt:mnopqrstuvwx]]"
    self.assertEqual(_reply_fingerprint(a), _reply_fingerprint(b))


if __name__ == "__main__":
  unittest.main()
