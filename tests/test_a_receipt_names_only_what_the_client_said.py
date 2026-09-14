"""A receipt names only figures the client said, and never a field.

Vasquez-Lindqvist Timber Frames ec2da9c7, 2026-09-13. Door A caught a real
defect - the router was about to write 2.6, a number the client never said, into
the wrong field - and wrote a receipt the consultant said back:

    "You told me you can run up to six home frame projects at once and can't go
     past six whatever the demand, so I'm recording 6 as your concurrent
     capacity and not as 2.6 annual turns per year."

The first half is exactly right. The tail tells the owner a number she never
said and names a slot while doing it.

WHY IT GOT OUT: door B appends door A's receipts to the reply verbatim, and the
raw-field-name detector reads the consultant's text BEFORE the receipts are
added - so it never saw them. A readback rule that lives only in a prompt is not
enforced.

Cowork's rule (standing): a readback names the figures the client can check -
here six, 26 and 34 - or it names nothing. Derived figures may live in the
store; they are never read back.

These pins drive door_b.review itself, with the model disabled, and read the
text the client would receive.
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
           "Over a year that works out around 26 of them, and 34 would be flat out. "
           "We can't go past six at once whatever the demand, that's the building.")

# The reply deliberately states NONE of her figures. This pin proves a receipt
# in her own figures is not withheld FOR ITS FIGURES. Its first fixture said
# "six home frame projects at once", which made the good receipt redundant
# under the later rule that a receipt adding nothing is not said - so the pin
# would have gone red while testing something else (2026-09-13).
_REPLY = "Got it - thanks for walking me through how the shop runs."

_BAD_RECEIPT = ("You told me you can run up to six home frame projects at once and "
                "can't go past six whatever the demand, so I'm recording 6 as your "
                "concurrent capacity and not as 2.6 annual turns per year.")

_GOOD_RECEIPT = ("You told me six at once is the most the building will hold, so I'm "
                 "recording six frames in the shop at once.")


class AReceiptIsCheckedBeforeItReachesTheClient(unittest.TestCase):
  def setUp(self):
    self._was = os.environ.get("INTAKE_GUARD_ENABLED")
    os.environ["INTAKE_GUARD_ENABLED"] = "0"     # no model: the append is deterministic
    from client_intake_and_finmo.intake_guard import door_b  # type: ignore

    self.door_b = door_b

  def tearDown(self):
    if self._was is None:
      os.environ.pop("INTAKE_GUARD_ENABLED", None)
    else:
      os.environ["INTAKE_GUARD_ENABLED"] = self._was

  def _sent(self, receipts):
    return self.door_b.review(text=_REPLY, store={}, receipts=receipts,
                              user_text=_CLIENT, recent_user_texts=[_CLIENT]).text

  def test_a_receipt_naming_a_number_she_never_said_does_not_go_out(self):
    sent = self._sent([_BAD_RECEIPT])
    self.assertNotIn("2.6", sent, "a derived number was read back to the client")

  def test_a_receipt_naming_a_field_does_not_go_out(self):
    sent = self._sent([_BAD_RECEIPT])
    self.assertNotIn("annual turns per year", sent.lower(),
                     "a field name reached the client inside a receipt")

  def test_a_receipt_in_her_own_figures_still_goes_out(self):
    """The check must not silence the guard: a receipt that names only what
    she said is the catch working, and it is appended."""
    sent = self._sent([_GOOD_RECEIPT])
    self.assertIn("recording six frames in the shop at once", sent)

  def test_the_derived_destination_is_never_read_back(self):
    """Turns and utilisation are derived. They may be stored; never said."""
    for derived in ("5.67", "5.667", "0.765", "0.7647", "76.5%", "76%"):
      receipt = "So I'm recording six at once, turning over %s times a year." % derived
      self.assertNotIn(derived, self._sent([receipt]),
                       "derived figure %s was read back" % derived)

  def test_the_consultants_own_reply_is_untouched(self):
    """This checks RECEIPTS. The reply body has its own door."""
    self.assertTrue(self._sent([_BAD_RECEIPT]).startswith(_REPLY))


if __name__ == "__main__":
  unittest.main(verbosity=2)
