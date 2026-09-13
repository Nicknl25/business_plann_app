"""A filter that is written but never called is not a fix.

THE DEFECT THIS PINS (2026-09-13, Thackeray & Nunes 53a7603f).

`_figures_the_reply_already_placed` was written to stop the app interrogating
figures its own reply had already understood. It was unit-tested against a
hand-built list of figures, it passed, and it was called from NOWHERE. The live
path never ran a line of it. The one clean turn it appeared to produce actually
came from `_already_asked_recently` suppressing a repeat of a question that had
been asked the turn before.

Nick's sentence for this shape: *the check was shaped like verification and
wasn't verification*. A test that constructs the input, calls the function and
asserts on the output proves the function works. It says nothing at all about
whether the product calls it.

So this pin asks the only question that would have caught it: at every place the
app decides to ask about an unresolved figure, has it first dropped the figures
its reply already placed?
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

SRC = (ROOT / "python" / "api_handlers" / "intake_consult.py").read_text(
  encoding="utf-8-sig")


class EveryAskSiteDropsWhatTheReplyAlreadyPlaced(unittest.TestCase):
  def test_the_filter_is_called_at_all(self):
    """The literal defect: defined once, called zero times."""
    calls = SRC.count("_figures_the_reply_already_placed(")
    self.assertGreater(
      calls, 1,
      "_figures_the_reply_already_placed appears only as a definition - it is "
      "dead code, and the live path still asks about figures the reply placed")

  def test_every_merge_site_filters_first(self):
    """Each place that composes the ask into the reply must filter first.

    Both sites matter. There are two, they were added at different times for
    different branches, and fixing one leaves the defect live on the other -
    which is how the original field-name bug survived its first fix.
    """
    # the merge is "assistant_text = f"{assistant_text} {_unresolved_ask}""
    merges = [m.start() for m in re.finditer(
      r'assistant_text = f"\{assistant_text\} \{_unresolved_ask\}"', SRC)]
    self.assertEqual(len(merges), 2,
                     "the number of ask-merge sites changed - re-read this pin")
    for start in merges:
      # look back over the block that decided this ask
      window = SRC[max(0, start - 1600):start]
      self.assertIn(
        "_figures_the_reply_already_placed(", window,
        "an ask is merged into the reply without first dropping the figures "
        "the reply already places - the Thackeray defect, on this branch")

  def test_the_filter_is_given_the_text_that_will_be_sent(self):
    """Filtering against anything but the outgoing reply is theatre.

    The whole claim is "our own words already said this". That is only true of
    the text about to be sent, so the argument must be `assistant_text`.
    """
    for m in re.finditer(r"_figures_the_reply_already_placed\(\s*\n?\s*([A-Za-z_]\w*)",
                         SRC):
      if m.group(1) == "assistant_text":
        continue
      # the definition itself takes the parameter name
      self.assertEqual(
        m.group(1), "assistant_text",
        "the filter was handed %r instead of the reply that is about to be "
        "sent" % m.group(1))


class ARowlessWriteIsRecordedAndAsked(unittest.TestCase):
  """The other half of the same run: a capacity answer that landed nowhere.

  On a multi-line model the router's bare `ops.units_per_week_capacity` has no
  row to land on. Dropping it is correct. Dropping it SILENTLY meant Thackeray
  answered the capacity question three times and the store held nothing.
  """

  def test_the_drop_records_the_discarded_answer(self):
    i = SRC.index("OPS_DRIVER_WRITE_UNROUTED")
    block = SRC[max(0, i - 1400):i + 400]
    self.assertIn('next_ops["_unrouted_driver_writes"]', block,
                  "a discarded client answer must be recorded, not only logged")

  def test_the_drop_is_not_whispered_at_info(self):
    i = SRC.index("OPS_DRIVER_WRITE_UNROUTED")
    self.assertIn("logger.warning(", SRC[max(0, i - 200):i],
                  "losing a client's answer is not an INFO-level event")

  def test_the_record_is_cleared_once_the_field_has_a_home(self):
    self.assertIn("def _clear_unrouted_writes_that_landed(", SRC)
    self.assertGreater(SRC.count("_clear_unrouted_writes_that_landed("), 1,
                       "the sweep is defined but never called - the same "
                       "dead-code shape this file exists to catch")

  def test_the_question_never_names_a_field(self):
    from client_intake_and_finmo.intake_coherence.section import (  # type: ignore
      unrouted_driver_hold_question,
    )

    # THE REAL THACKERAY SHAPE. Every row carries unit_name "job"; the
    # name that tells the lines apart is product_name. A question built off
    # unit_name asks "is that the job, the job, or the job?".
    ops = {
      "lob_models": [{"lob_name": "Stone fabrication and installation",
                      "products": [
        {"product_name": "Residential countertops and vanities", "unit_name": "job"},
        {"product_name": "Commercial architectural stonework", "unit_name": "job"},
        {"product_name": "Memorials and headstones", "unit_name": "job"},
      ]}],
      "_unrouted_driver_writes": [
        {"field": "units_per_week_capacity", "value": 30, "asked": 0, "rows": 3},
      ],
    }
    q = unrouted_driver_hold_question(ops)
    self.assertTrue(q)
    for raw in ("units_per_week_capacity", "units_per_period_capacity",
                "unit_name", "lob_models", "_unrouted"):
      self.assertNotIn(raw, q, "a raw field name reached the client")
    self.assertIn("30", q, "the client's own number must be read back")
    for name in ("Residential countertops and vanities",
                 "Commercial architectural stonework",
                 "Memorials and headstones"):
      self.assertIn(name, q, "the lines must be named in the client's words")
    self.assertNotIn(
      "the job, ", q,
      "unit_name is 'job' on every row - a question built off it names nothing")

  def test_it_is_let_go_after_two_asks(self):
    from client_intake_and_finmo.intake_coherence.section import (  # type: ignore
      unrouted_driver_hold_question,
    )

    ops = {
      "lob_models": [{"products": [{"product_name": "countertops"},
                                   {"product_name": "vanities"}]}],
      "_unrouted_driver_writes": [
        {"field": "units_per_week_capacity", "value": 30, "asked": 2, "rows": 2},
      ],
    }
    self.assertIsNone(unrouted_driver_hold_question(ops),
                      "asked twice and unanswered, it is let go - nothing loops")



class TheClientsOwnWordsSettleTheCadence(unittest.TestCase):
  """The 45 that was asked about after the client said "a week".

  Turn 13 of 53a7603f, on a build that already had the reply-placed filter:

      client: "Countertops run about 45 a week when we are flat out."
      app:    "The 45 - is that your weekly capacity, or your capacity per period?"

  The reply-placed filter could not help - the reply never states 45, and there
  are three ask sites, one of which REPLACES the reply rather than appending to
  it, so there is no reply to read. The fix belongs upstream, where a figure is
  judged open at all, and it fixes all three sites at once.

  This is arithmetic, not judgment: the two fields are conversions of one
  another, and "a week" is the word "week".
  """

  def setUp(self):
    from api_handlers.intake_consult import (  # type: ignore
      _candidates_the_words_already_settle,
    )

    self.settle = _candidates_the_words_already_settle
    self.pair = ["ops.units_per_week_capacity", "ops.units_per_period_capacity"]

  def _leaf(self, cands):
    return [c.split(".")[-1] for c in cands]

  def test_a_week_settles_it_weekly(self):
    cands, settled = self.settle(
      self.pair, "Countertops run about 45 a week when we are flat out.")
    self.assertTrue(settled)
    self.assertEqual(self._leaf(cands), ["units_per_week_capacity"])

  def test_a_year_settles_it_per_period(self):
    cands, settled = self.settle(self.pair, "around 540 a year")
    self.assertTrue(settled)
    self.assertEqual(self._leaf(cands), ["units_per_period_capacity"])

  def test_at_once_is_genuinely_open(self):
    """"25 to 30 going at once" is concurrent work in progress - NEITHER
    reading. This is the pair that was actually ambiguous, and the run asked
    about the wrong one."""
    _cands, settled = self.settle(self.pair, "we keep 25 to 30 going at once")
    self.assertFalse(settled, "a figure with no stated cadence must stay open")

  def test_saying_both_cadences_stays_open(self):
    """"40 a week or so, maybe 500 a year" states two - the words settle
    nothing and the question is the honest response."""
    _cands, settled = self.settle(self.pair, "40 a week or so, maybe 500 a year")
    self.assertFalse(settled)

  def test_a_non_cadence_pair_is_left_alone(self):
    cands, settled = self.settle(
      ["ops.unit_price", "financials.current_revenue"], "about 45 a week")
    self.assertFalse(settled)
    self.assertEqual(len(cands), 2, "only a week/period pair is narrowed")

  def test_the_rule_is_applied_where_a_figure_is_judged_open(self):
    """Wired, not merely written - the defect this whole file exists for."""
    i = SRC.index("def _unresolved_figures_open(")
    body = SRC[i:SRC.index(chr(10) + "def ", i + 10)]
    self.assertIn("_candidates_the_words_already_settle(", body,
                  "the cadence rule is not applied where openness is decided, "
                  "so the ask sites that replace the reply are still unfixed")


class TheQuestionSaysWhyItIsAsking(unittest.TestCase):
  """Nick, taking Cowork's wording, 2026-09-13: 'So that I record it the right
  way round - is 700 the most kitchens you could finish in a year, or the most
  you could have going at once?'

  "The 45 - is that your weekly capacity, or your capacity per period?" reads
  like a form rejecting an entry. The client is being asked to stop the app
  filing their number wrongly; saying so is what makes it answerable.
  """

  def test_a_two_way_ask_leads_with_the_reason(self):
    from api_handlers.intake_consult import _unresolved_figures_ask  # type: ignore

    q = _unresolved_figures_ask([{
      "value": 700,
      "client_words": "700 at the ceiling",
      "candidate_fields": ["ops.units_per_week_capacity",
                           "ops.units_per_period_capacity"],
    }])
    self.assertTrue(q)
    self.assertIn("So that I record it the right way round", q)
    self.assertNotIn("units_per", q, "a raw field name reached the client")


if __name__ == "__main__":
  unittest.main(verbosity=2)


class NoQuestionWhoseSubjectIsAPastedSentence(unittest.TestCase):
  """Issue 589, pinned at last - the fourth sighting, third by DELETION.

  The template is "The {shown} - is that your X?". When {shown} is the client's
  phrase rather than their figure, and the phrase does not START with the
  figure, the result is a sentence no person would say:

      "The maybe six or eight of them - is that your selections?"   (a88dae18)
      "The The shed holds four hulls at once - is that your capacity per period?"

  A rule for this was written at 6b14fa44 and deleted at 4f166370 by a scripted
  block edit that replaced the surrounding lines and took it along. Nothing
  replaced it. The deletion was silent because no test named the shape - so
  the same garbled question reached a client again.

  The newer "So that I record it the right way round - is {shown} your X, or
  your Y?" form has the identical failure ("is Around 540 a year your capacity
  per period"), which is why this pins the RENDERED question, not the rule.
  """

  def setUp(self):
    from api_handlers.intake_consult import _unresolved_figures_ask  # type: ignore

    self.ask = _unresolved_figures_ask

  def _q(self, value, words, cands):
    return self.ask([{"value": value, "client_words": words,
                      "candidate_fields": cands}])

  def test_a_phrase_that_does_not_start_with_the_figure_is_not_pasted(self):
    for value, words in (
      (4, "The shed holds four hulls at once"),
      (6, "maybe six or eight of them"),
      (540, "Around 540 a year"),
      (30, "we keep 25 to 30 going at once"),
    ):
      q = self._q(value, words, ["ops.units_per_period_capacity"])
      self.assertNotIn(words, q,
                       "the client's sentence was pasted in as a noun: %r" % q)
      self.assertNotIn("The The", q)
      self.assertNotIn("is that your", q.replace("- is that your", ""))

  def test_a_phrase_that_starts_with_the_figure_is_kept(self):
    """The rule must not throw away good phrasing - "40 a week" reads
    correctly after both templates and the router pin requires it."""
    q = self._q(40, "40 a week",
                ["ops.units_per_week_capacity", "ops.unit_price"])
    self.assertIn("40 a week", q)

  def test_a_spelled_out_number_at_the_front_is_kept(self):
    q = self._q(4, "four hulls at once", ["ops.units_per_period_capacity"])
    self.assertIn("four hulls at once", q)

  def test_both_templates_read_as_english(self):
    """Whatever the branch, the question must not contain "is <Capitalised
    hedge>" or "The The" - the two shapes that told us it was garbled."""
    cases = [
      (540, "Around 540 a year",
       ["ops.units_per_period_capacity", "financials.current_revenue"]),
      (4, "The shed holds four hulls at once", ["ops.units_per_period_capacity"]),
    ]
    for value, words, cands in cases:
      q = self._q(value, words, cands)
      self.assertTrue(q.endswith("?"), q)
      self.assertNotIn("is Around", q)
      self.assertNotIn("The The", q)


class TheCadenceRuleIsTestedThroughTheCallSite(unittest.TestCase):
  """Mini's caveat, 2026-09-13, and it is the right one.

  `_candidates_the_words_already_settle` runs inside `_unresolved_figures_open`,
  not inside `_unresolved_figures_ask`. A probe that calls the ask builder
  directly still shows the weekly-or-period question and looks like a live
  defect; a probe that calls the settler directly shows it working and looks
  like a fix. Neither is the product.

  So this drives the function that actually DECIDES whether a figure is open -
  the same reason this file exists. It is the exact trap the hand-built fixture
  fell into on 6da05129.
  """

  def setUp(self):
    from api_handlers.intake_consult import _unresolved_figures_open  # type: ignore

    self.open = _unresolved_figures_open
    self.ops = {"lob_models": [{"products": [
      {"product_name": "countertops"}, {"product_name": "vanities"}]}]}

  def _open(self, value, words):
    return self.open(
      [{"value": value, "client_words": words,
        "candidate_fields": ["ops.units_per_week_capacity",
                             "ops.units_per_period_capacity"]}],
      ops_json=self.ops, people_json={}, financials_json={})

  def test_a_week_is_not_open_through_the_real_decider(self):
    self.assertEqual(
      self._open(45, "Countertops run about 45 a week when we are flat out."), [],
      "the client said 'a week' - the decider must not leave this open")

  def test_a_year_is_not_open_through_the_real_decider(self):
    self.assertEqual(self._open(540, "around 540 a year"), [])

  def test_at_once_stays_open_through_the_real_decider(self):
    """The genuinely ambiguous one must survive - a rule that closes
    everything is as wrong as one that closes nothing."""
    self.assertTrue(self._open(30, "we keep 25 to 30 going at once"),
                    "concurrent work-in-progress states no cadence; it is open")
