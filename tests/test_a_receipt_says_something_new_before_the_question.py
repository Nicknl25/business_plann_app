"""A receipt that adds nothing is not said, and one that does comes before the question.

Vasquez-Lindqvist Timber Frames ec2da9c7, replay turn 19, 2026-09-13. The store
was right and every figure the client heard was hers - and the reply still read
badly. It said her figures three times, and the third time came AFTER the next
question:

    ...in a strong year you might complete around 26 homes, with 34 as an
       absolute flat-out limit.
    ...what's a good average all-in price you charge for the full frame package?

    You told me six at once is the most the building will hold, ... so I'm
    recording six at once, about 26 over a year, and 34 as flat out.

Door B appends door A's receipts at the END of the reply. Two consequences, both
pinned here on the text the client receives:

1. REDUNDANT. When every figure in the receipt is already stated in the reply,
   the receipt tells her nothing she has not just read. It is withheld.

2. MISPLACED. When a receipt does carry something new, it is the record of what
   was done - it belongs before the question the turn is waiting on, so the
   message still ends on that question.

Driven through door_b.review with the model disabled.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

_CLIENT = ("Six. That's the most the shop will hold, and we're usually running five "
           "or six. A frame takes about ten weeks from design through to raising it. "
           "Over a year that works out around 26 of them, and 34 would be flat out.")

_READBACK = ("Thanks, that's very clear: the hard cap is 6 active home frame projects at "
             "any one time, and in a strong year you might complete around 26 homes, with "
             "34 as an absolute flat-out limit.")

_QUESTION = ("Next, what's a good average all-in price you charge for the full frame "
             "package from design through raising?")

_REDUNDANT_RECEIPT = ("You told me six at once is the most the building will hold, and that "
                      "over a year that works out around 26 of them with 34 flat out, so I'm "
                      "recording six at once, about 26 over a year, and 34 as flat out.")

_NEW_RECEIPT = ("You told me you're usually running five or six, so I'm recording that "
                "you're usually running five or six at once.")


class _Door(unittest.TestCase):
  def setUp(self):
    self._was = os.environ.get("INTAKE_GUARD_ENABLED")
    os.environ["INTAKE_GUARD_ENABLED"] = "0"
    from client_intake_and_finmo.intake_guard import door_b  # type: ignore

    self.door_b = door_b

  def tearDown(self):
    if self._was is None:
      os.environ.pop("INTAKE_GUARD_ENABLED", None)
    else:
      os.environ["INTAKE_GUARD_ENABLED"] = self._was

  def _sent(self, text, receipts):
    return self.door_b.review(text=text, store={}, receipts=receipts,
                              user_text=_CLIENT, recent_user_texts=[_CLIENT]).text


class AReceiptThatAddsNothingIsNotSaid(_Door):
  def test_the_turn_19_receipt_is_withheld(self):
    reply = _READBACK + "\n\n" + _QUESTION
    sent = self._sent(reply, [_REDUNDANT_RECEIPT])
    self.assertNotIn("so I'm recording six at once", sent,
                     "her figures were read back a third time, after the question")

  def test_a_receipt_with_something_new_is_still_said(self):
    """The check must not silence the guard. 'five or six' is hers and the
    reply did not state it, so the receipt carries something."""
    reply = _READBACK + "\n\n" + _QUESTION
    sent = self._sent(reply, [_NEW_RECEIPT])
    self.assertIn("usually running five or six at once", sent)


class AReceiptComesBeforeTheQuestion(_Door):
  def test_the_message_still_ends_on_its_question(self):
    reply = _READBACK + "\n\n" + _QUESTION
    sent = self._sent(reply, [_NEW_RECEIPT])
    self.assertTrue(sent.rstrip().endswith("?"),
                    "the receipt landed after the question the turn is waiting on: %r"
                    % sent[-160:])
    self.assertLess(sent.index("usually running five or six at once"),
                    sent.index("good average all-in price"))

  def test_a_reply_with_no_question_still_gets_its_receipt_at_the_end(self):
    sent = self._sent(_READBACK, [_NEW_RECEIPT])
    self.assertTrue(sent.startswith(_READBACK))
    self.assertIn("usually running five or six at once", sent)


if __name__ == "__main__":
  unittest.main(verbosity=2)
