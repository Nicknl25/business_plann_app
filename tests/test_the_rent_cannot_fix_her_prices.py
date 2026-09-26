"""A RENT COMMITMENT IS NOT A PRICE COMMITMENT.

Two live Cowork runs, 2026-09-26. Drafts 4f949292 (Grantley and Foss
Printworks) and d5b77aae (Ashworth and Delacroix Conservatory). The log, once
per run:

    COMPLETED_FIELD_WRITE field=price_contracted stage=lease_commitment
                          outcome=admitted before=False after=True
                          guard_armed=False field_guarded=False

At the LEASE question both clients answered:

    Grantley: "Signed, eight years left. The rent can't move."
    Ashworth: "Signed, fourteen years left. The rent can't move."

and "can't move" - a price-fixed signal - set `price_contracted = True` from a
sentence about RENT. Their real answers to the actual price question could then
never correct it, because the price door was guarded by
`not has("price_contracted")`, so the first value to appear won:

    Grantley: "The catalogue contracts are priced for the term and can't move
               until renewal. Wide format and digital I can raise."
    Ashworth: "I can raise tuition somewhat. Families expect a small increase
               each year."

Both times the app SAID "Got it. Prices can move if the numbers call for it."
while the store held True, and each closing summary then reported back "What you
told me is fixed: ... prices fixed by contract" - attributing to her a
constraint she never stated and the app itself had denied.

WHAT IT COST ASHWORTH: the coherence solve told her "I can't find a path to a
profit inside five years" while treating price as contractually frozen, moments
after she said she can raise tuition. A lever she offered was locked out of the
solve, so the verdict she received about her own business may have been wrong.

THE GUARD FOR THIS ALREADY EXISTED and was not wired for these fields. Its own
CW-041 comment names the ancestor - "the shape that overwrote Halbrook's
confirmed $5,200 rent with a figure from the lease answer" - and the log shows
both of its preconditions failing: it arms only when the message names the
ACTIVE stage's family, and the lease fields had no keyword entry, so on that
stage it stood down entirely; and `price_contracted` had no entry either, so an
armed guard would still have left it alone.
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

#: What each client actually typed, verbatim from the two drafts.
GRANTLEY_LEASE = "Signed, eight years left. The rent can't move."
ASHWORTH_LEASE = "Signed, fourteen years left. The rent can't move."
GRANTLEY_PRICE = ("The catalogue contracts are priced for the term and can't "
                  "move until renewal. Wide format and digital I can raise.")
ASHWORTH_PRICE = ("I can raise tuition somewhat. Families expect a small "
                  "increase each year.")


def _drive(stage, message, *, patch=None, financials=None):
  """One turn through the real normalizer, which is where the guard lives."""
  report = {}
  out = IC._normalize_financials_router_patch(
    patch=dict(patch or {}),
    active_stage=stage,
    financials_json=dict(financials or {}),
    financials_year1_json={},
    last_assistant="",
    user_message=message,
    report=report,
  )
  return (out or {}), report


class HerRentAnswerCannotFixHerPrices(unittest.TestCase):

  def test_the_live_defect_on_both_runs(self):
    for message in (GRANTLEY_LEASE, ASHWORTH_LEASE):
      out, report = _drive(
        "lease_commitment", message,
        patch={"financials.price_contracted": True},
        financials={"price_contracted": False})
      self.assertEqual(False, out.get("price_contracted"),
                       "a rent sentence set a price commitment: %r" % message)
      outcomes = [(d.get("field"), d.get("outcome"))
                  for d in report.get("completed_field_writes", [])]
      self.assertIn(("price_contracted", "reverted_by_guard"), outcomes,
                    "the revert must be on the record, not silent: %r" % outcomes)

  def test_the_guard_can_arm_on_the_lease_stage_at_all(self):
    """guard_armed=False in the live log: the guard arms only when the message
    names the ACTIVE stage's family, and the lease fields had no entry, so on
    that stage it never armed for any field."""
    kw = IC._FINANCIALS_FAMILY_KEYWORDS_BY_FIELD_GUARD
    for field in ("lease_signed", "lease_term_months"):
      self.assertTrue(kw.get(field), "%s has no keyword family" % field)
    for message in (GRANTLEY_LEASE, ASHWORTH_LEASE):
      low = message.lower()
      self.assertTrue(
        any(k in low for f in ("lease_signed", "lease_term_months")
            for k in kw.get(f, ())),
        "her lease answer does not name the lease family: %r" % message)

  def test_and_price_contracted_is_a_guarded_field(self):
    """field_guarded=False in the live log."""
    self.assertTrue(
      IC._FINANCIALS_FAMILY_KEYWORDS_BY_FIELD_GUARD.get("price_contracted"))

  def test_price_is_named_by_price_words_not_by_the_word_contract(self):
    """The price question itself asks "are your prices fixed by contract", so a
    lease answer that happens to say "contract" must not read as naming the
    price family."""
    kw = IC._FINANCIALS_FAMILY_KEYWORDS_BY_FIELD_GUARD["price_contracted"]
    self.assertNotIn("contract", kw)
    for message in (GRANTLEY_LEASE, ASHWORTH_LEASE):
      low = message.lower()
      self.assertFalse(any(k in low for k in kw),
                       "a rent sentence reads as naming the price family: %r"
                       % message)
    for message in (GRANTLEY_PRICE, ASHWORTH_PRICE):
      low = message.lower()
      self.assertTrue(any(k in low for k in kw),
                      "her PRICE answer does not name the price family: %r"
                      % message)


class HerAnswerAtItsOwnStageIsAuthoritative(unittest.TestCase):

  def test_a_plain_movable_answer_lands(self):
    """ASHWORTH'S REAL ANSWER. It matched nothing before, so the value taken
    from her rent sentence stood unchallenged. Raising a price is the clearest
    possible evidence it can move."""
    out, _ = _drive("price_commitment", ASHWORTH_PRICE)
    self.assertEqual(False, out.get("price_contracted"))

  def test_every_plain_shape_reads_correctly(self):
    for message, want in (
      ("Yes, fixed by contract for the whole term.", True),
      ("Everything is locked for three years.", True),
      ("They are not fixed, we can reprice at any time.", False),
      ("We can put them up if costs go up.", False),
      ("No.", False),
    ):
      out, _ = _drive("price_commitment", message)
      self.assertEqual(want, out.get("price_contracted"), message)

  def test_an_earlier_wrong_value_is_correctable_at_its_own_stage(self):
    """`not has("price_contracted")` meant the FIRST value to appear won, so her
    answer to the actual question could never correct it."""
    out, _ = _drive("price_commitment",
                    "They are not fixed, we can reprice at any time.",
                    financials={"price_contracted": True})
    self.assertEqual(False, out.get("price_contracted"))
    import inspect
    self.assertNotIn('not has("price_contracted")',
                     inspect.getsource(IC._commitment_answer_door))


class AMixedAnswerIsNotFlattened(unittest.TestCase):
  """GRANTLEY said both, because both are true of different lines:

      "The catalogue contracts are priced for the term and can't move until
       renewal. Wide format and digital I can raise."

  Checking fixed-first flattened that to "everything is fixed" and discarded
  the flexibility she had just offered on two of her three lines. One boolean
  cannot hold a per-line answer, so it stops guessing: the field stays unset,
  its stage asks again, and the ambiguity is on the record.
  """

  def test_her_mixed_answer_writes_nothing(self):
    out, _ = _drive("price_commitment", GRANTLEY_PRICE)
    self.assertIsNone(out.get("price_contracted"),
                      "a per-line answer must not be flattened to a boolean")

  def test_it_does_not_silently_pick_the_fixed_reading(self):
    """The specific harm: the old order took the fixed clause and threw the
    movable one away, and a withheld price lever is what let the other run's
    solve report that a business had no path to profit."""
    out, _ = _drive("price_commitment", GRANTLEY_PRICE)
    self.assertNotEqual(True, out.get("price_contracted"))

  def test_both_signals_present_is_what_makes_it_ambiguous(self):
    low = GRANTLEY_PRICE.lower()
    self.assertTrue(IC._PRICE_FIXED_RE.search(low), "names a fixed line")
    self.assertTrue(IC._PRICE_FREE_RE.search(low), "and a movable one")

  def test_an_unambiguous_answer_is_still_decided(self):
    """The hold is only for genuinely mixed answers - it must not turn every
    answer into another question."""
    for message, want in (("Yes, all fixed by contract.", True),
                          ("Not fixed at all.", False)):
      out, _ = _drive("price_commitment", message)
      self.assertEqual(want, out.get("price_contracted"), message)


if __name__ == "__main__":
  unittest.main()
