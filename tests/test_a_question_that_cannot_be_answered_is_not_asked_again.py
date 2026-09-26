"""Two class defects from the 2026-09-25 Keir run, which died at the turn cap.

SHE ANSWERED EVERY TIME. She named the line, the price and the utilisation.
The app asked "name the stored number that's wrong" SEVENTY-ONE TIMES and
the intake never completed.

  1. A CORRECTION TO A MERGED LINE WAS UNANSWERABLE. Both her products sat
     under one line of business, "Metal fabrication and service". The
     resolver bagged product-name tokens together with LOB-name tokens, so
     the word "fabrication" in her sentence scored for EVERY product in
     that LOB and the resolver refused as ambiguous - even though one row
     also matched "structural" and "steel" and the other matched nothing
     else. Her SHORTER sentence resolved and her more specific one did not.

  2. NO TOP RUNG ON THE LADDER. The coherence hold escalates - repeat,
     then expose its operands, then offer the direct set - and then
     repeated the direct set forever. Nothing noticed it had said the same
     thing twice.

Both are general. Neither is about steel.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "python",
                             "client_intake_and_finmo"))

from api_handlers.intake_consult import _resolve_ops_product_line as resolve  # noqa: E402


def _ops(lob_name, *product_names):
  return {"lob_models": [{
      "lob_name": lob_name,
      "products": [{"product_name": n, "unit_price": 100} for n in product_names],
  }]}


# The shape that died: the LOB name repeats a word one product owns.
KEIR = _ops("Metal fabrication and service",
            "Fabrication jobs (structural steel, sheet metal, ducting)",
            "Repair & maintenance callouts")

# Same shape, nothing to do with metal - a salon, a clinic, a studio.
SALON = _ops("Hair and beauty services",
             "Hair cutting and colouring",
             "Beauty treatments and nails")
CLINIC = _ops("Veterinary care and boarding",
              "Veterinary consultations and care",
              "Boarding and daycare")


class AQuestionThatCannotBeAnsweredIsNotAskedAgain(unittest.TestCase):

  def test_a_word_the_line_of_business_shares_does_not_blind_the_resolver(self):
    """The exact deadlock, on three unrelated businesses."""
    for ops, said, want in (
        (KEIR, "Structural steel fabrication price is two thousand four "
               "hundred dollars a tonne", 0),
        (KEIR, "the repair callouts are 1100 a job", 1),
        (SALON, "the hair colouring price is 95", 0),
        (SALON, "beauty treatments are 60", 1),
        (CLINIC, "veterinary consultations are 85", 0),
        (CLINIC, "boarding is 40 a night", 1),
    ):
      got, why = resolve(ops, said)
      self.assertIsNotNone(
          got, "%r was refused as %r - she named the line" % (said, why))
      self.assertEqual(want, got[1],
                       "%r resolved to the wrong line" % said)

  def test_being_more_specific_never_makes_it_worse(self):
    """Her short sentence resolved and her precise one did not. A longer,
    more specific sentence must never resolve to less."""
    short = "structural steel is 2400 a tonne"
    longer = ("The price per tonne for structural steel fabrication is "
              "wrong - it's about two thousand four hundred dollars a "
              "tonne, not two thousand five hundred.")
    a, _ = resolve(KEIR, short)
    b, _ = resolve(KEIR, longer)
    self.assertIsNotNone(a)
    self.assertIsNotNone(b, "the more specific sentence was refused")
    self.assertEqual(a[:2], b[:2])

  def test_a_real_tie_still_refuses(self):
    """The law that must survive the fix: naming TWO lines refuses, because
    a wrong line written is the one unacceptable outcome."""
    for ops, said in ((KEIR, "fix the fabrication and repair lines capacity"),
                      (KEIR, "set the structural and the repair prices"),
                      (SALON, "put the hair and beauty prices up"),
                      (CLINIC, "veterinary and boarding both go up")):
      got, why = resolve(ops, said)
      self.assertIsNone(got, "%r picked a line on a tie" % said)
      self.assertEqual("ambiguous", why)

  def test_a_bare_figure_names_nothing(self):
    got, why = resolve(KEIR, "the price is 2400")
    self.assertIsNone(got)
    self.assertEqual("none", why)

  def test_one_product_can_still_be_named_by_its_line_of_business(self):
    """With a single row there is nothing to tell apart, so the LOB name is
    a legitimate way for a client to point at it."""
    one = _ops("Dog grooming", "Full groom")
    got, _ = resolve(one, "the dog grooming price is 85")
    self.assertIsNotNone(got)


if __name__ == "__main__":
  unittest.main()


class TheLadderHasATopRung(unittest.TestCase):
  """Defect 2: the coherence hold escalated and then repeated forever."""

  def test_the_escalation_terminates_in_the_source(self):
    """The release rung exists, above the direct-set rung, and lets the
    intake proceed instead of holding. Read from the source so the rung
    cannot be quietly removed."""
    import inspect
    from client_intake_and_finmo.intake_coherence import section

    src = inspect.getsource(section)
    self.assertIn("_anchor_hold_released", src,
                  "the hold has no release - it can repeat forever again")
    cut = src.index("Let's cut through this")
    rel = src.index("_anchor_hold_released")
    self.assertLess(rel, cut,
                    "the release must be checked BEFORE the direct-set "
                    "message, or the direct set still wins every time")

  def test_the_release_is_reached_after_a_bounded_number_of_asks(self):
    import inspect
    from client_intake_and_finmo.intake_coherence import section

    src = inspect.getsource(section)
    self.assertIn("_reps >= 3", src,
                  "the release must trigger on a bounded repeat count")
    self.assertLess(src.index("_reps >= 3"),
                    src.index("_anchor_hold_released"),
                    "the repeat count must gate the release, not follow it")
