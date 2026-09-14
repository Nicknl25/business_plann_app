"""A figure the app derived cannot explain itself when the reply says it.

Door B checks every number a reply states against what it is entitled to say:
the store in any common basis, the client's own words, the walk's record. A
derived figure lives in the store - Vasquez-Lindqvist ec2da9c7 holds
annual_turns_per_year = 5.666666666666667 and utilization_rate =
0.7647058823529411, computed from her 34 flat out and 26 a year - so a reply
reading "turning over 5.67 times a year" back would be EXPLAINED BY ITSELF and
go straight to the client. Cowork's standing rule: nothing derived is read back.

So a derived capacity leaf no longer counts as an explanation. A figure the
client actually said is still explained - by her words, which door B already
reads - so a client-stated turns or utilisation figure is not caught by this.

KNOWN GAP, NAMED NOT HIDDEN: door B treats a PERCENTAGE as an operator rather
than a claim (a reply's "4%" is applied to stored figures instead of checked in
its own right), so a derived "76%" is not reached by this check at all, and a
proportion said in WORDS ("roughly three-quarters full") is not a number. Both
are left to the consultant's prompt rule, and Cowork has said plainly that its
own run-time check is sampling, not coverage.

These pins drive find_disagreements - the deterministic decider - directly.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

_CLIENT = ("Six. That's the most the shop will hold, and we're usually running five or six. "
           "A frame takes about ten weeks from design through to raising it. Over a year that "
           "works out around 26 of them, and 34 would be flat out.")


def _store(turns=34 / 6, util=26 / 34):
  return {"ops": {"lob_models": [{"lob_name": "Primary line of business", "products": [
    {"product_name": "Custom residential timber frames", "unit_cadence": "contract",
     "concurrent_capacity_units": 6, "annual_turns_per_year": turns, "utilization_rate": util},
  ]}]}}


class ADerivedFigureReadBackIsADisagreement(unittest.TestCase):
  def setUp(self):
    from client_intake_and_finmo.intake_guard.door_b import find_disagreements  # type: ignore

    self.check = find_disagreements

  def test_derived_leaves_are_not_in_the_explanation_set(self):
    """The guarantee itself, on the decider's input: the values the app derived
    are gone from what may explain a figure, and hers remain."""
    from client_intake_and_finmo.intake_guard.door_b import explained_figures  # type: ignore

    vals = explained_figures(_store(), None, _CLIENT, reply_text="", recent_user_texts=[_CLIENT])
    for derived in (34 / 6, 26 / 34):
      self.assertFalse(any(abs(v - derived) < 1e-9 for v in vals),
                       "derived %r still explains a figure" % derived)
    for hers in (6.0, 26.0, 34.0):
      self.assertTrue(any(abs(v - hers) < 1e-9 for v in vals),
                      "her own %r stopped explaining figures" % hers)

  def test_a_derived_figure_not_near_hers_is_caught(self):
    reply = "That puts you at about 0.76 of your capacity."
    self.assertTrue(self.check(reply, _store(), None, _CLIENT, [_CLIENT]),
                    "a derived utilisation read back as a decimal went out")

  def test_a_derived_figure_that_rounds_to_hers_is_caught_by_what_it_is(self):
    """WAS A NAMED GAP, CLOSED 2026-09-13 (after CW-069). "turning over 5.67
    times a year" is within door B's rounding tolerance of her SIX, so her six
    explained it, and changing the tolerance would have been the wrong fix.
    It is now caught by what it IS: 34 / 6 at the two decimals the reply
    states, and not a figure she said at that precision. The tolerance is
    untouched."""
    dis = self.check("So that is six at once, each slot turning over 5.67 times a year.",
                     _store(), None, _CLIENT, [_CLIENT])
    self.assertTrue(any(d.get("kind") == "derived_figure_read_back" and abs(d["value"] - 5.67) < 1e-9
                        for d in dis), dis)

  def test_her_own_figures_are_not_caught(self):
    reply = "Six at once, around 26 in a typical year, and 34 flat out."
    self.assertEqual(self.check(reply, _store(), None, _CLIENT, [_CLIENT]), [],
                     "the backstop flagged figures the client actually said")

  def test_a_turns_figure_she_stated_is_not_caught(self):
    """Derived-ness is about who said it. A client who says 18 turns a year has
    said it, and her words explain it."""
    client = "Each bay turns over about 18 times a year."
    reply = "Got it - 18 times a year per bay."
    self.assertEqual(self.check(reply, _store(turns=18.0), None, client, [client]), [])


if __name__ == "__main__":
  unittest.main(verbosity=2)
