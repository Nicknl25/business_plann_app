"""Nothing the app computed from the client's figures is read back - any business.

CW-068 (timber frames): her six at once and 34 flat out came back as "5.67
times a year". CW-069 (environmental lab, 2031efa2 turn 11): her 340 and 480
came back as "about 70% of that 480-sample weekly capacity", offered for her
to plan on. Same move in two trades with different numbers - arithmetic on two
figures she gave, returned as a third she did not.

What let it through, and what these pins state for ANY figures:
  - a derived percentage or decimal is caught by what it IS - a ratio of two
    figures the client said, at the precision the reply states it - including
    one that rounds to a figure she said (5.67 beside her six);
  - her own figures are never caught, whether written in digits or SPELLED
    OUT ("about three hundred and forty" read as nothing, her 340 looked
    invented, and door B's rewrite deleted it while keeping the 70%);
  - a percentage she said herself, a stored rate, and market context are
    not derived read-backs;
  - the consultant prompt no longer instructs it to propose a utilisation or
    translate an annual total into turns.
  - the same derived figure written in WORDS by the reply - "about seventy
    percent", "three-quarters full" - is caught too (Cowork 1023: the CW-069
    blindness with the arrow reversed), and an ordinal ("a third line") or a
    proportion the client said herself is not.
Known gap, named: a whole number the reply spells out ("twenty-four thousand").
"""
from __future__ import annotations

import itertools
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
         "sixteen seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _spell(n: int) -> str:
  if n < 20:
    return _ONES[n]
  if n < 100:
    return _TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else "")
  if n < 1000:
    return _ONES[n // 100] + " hundred" + (" and " + _spell(n % 100) if n % 100 else "")
  return _spell(n // 1000) + " thousand" + (" " + _spell(n % 1000) if n % 1000 else "")


def _check(reply, client, store=None):
  from client_intake_and_finmo.intake_guard.door_b import find_disagreements  # type: ignore
  return find_disagreements(reply, store or {}, None, client, [client])


def _derived(dis, value):
  return any(d.get("kind") == "derived_figure_read_back" and abs(d["value"] - value) < 1e-9 for d in dis)


class ADerivedFigureIsCaughtForAnyFigures(unittest.TestCase):
  def test_a_share_of_capacity_as_a_percentage(self):
    cases = 0
    for a, b in itertools.product((12, 26, 90, 340, 610), (34, 120, 480, 975, 2600)):
      if a >= b:
        continue
      p = round(100 * a / b)
      if p in (0, a, b):
        continue                    # a genuine coincidence: the percentage IS a figure she said
      client = "We could do %d flat out, and we actually do about %d." % (b, a)
      dis = _check("So you are running at about %d%% of capacity." % p, client)
      self.assertTrue(_derived(dis, p), "%d%% from %d/%d went out: %s" % (p, a, b, dis))
      cases += 1
    self.assertGreater(cases, 15)

  def test_a_share_as_a_decimal(self):
    for a, b in ((26, 34), (340, 480), (90, 120), (7, 45)):
      v = round(a / b, 2)
      client = "%d is the most, we do about %d." % (b, a)
      dis = _check("That puts you at about %.2f of capacity." % v, client)
      self.assertTrue(_derived(dis, v), "%.2f from %d/%d went out: %s" % (v, a, b, dis))

  def test_a_turns_figure_even_when_it_rounds_to_one_she_said(self):
    cases = 0
    for c, k in itertools.product((3, 4, 6, 8), (10, 31, 34, 50)):
      t = round(k / c, 2)
      if abs(t - round(t)) < 1e-9:
        continue                    # a whole number of turns is left to the explanation check
      client = "%d at once is the limit, and %d a year would be flat out." % (c, k)
      dis = _check("So each slot turns over %.2f times a year." % t, client)
      self.assertTrue(_derived(dis, t), "%.2f turns from %d/%d went out: %s" % (t, k, c, dis))
      cases += 1
    self.assertGreater(cases, 8)


class ADerivedFigureInWordsIsCaught(unittest.TestCase):
  def test_a_spelled_percentage(self):
    cases = 0
    for a, b in itertools.product((12, 26, 90, 340, 610), (34, 120, 480, 975)):
      if a >= b:
        continue
      p = round(100 * a / b)
      if p in (0, a, b) or p > 99:
        continue
      client = "We could do %d flat out, and we actually do about %d." % (b, a)
      dis = _check("So you are running at about %s percent of capacity." % _spell(p), client)
      self.assertTrue(any(d.get("kind") == "derived_figure_read_back" and d.get("value") == p for d in dis),
                      "about %s percent from %d/%d went out: %s" % (_spell(p), a, b, dis))
      cases += 1
    self.assertGreater(cases, 10)

  def test_a_proportion_word(self):
    for a, b, words in ((26, 34, "three-quarters full"), (90, 120, "three quarters of capacity"),
                        (340, 510, "two-thirds of what you could do"), (12, 36, "a third of capacity"),
                        (95, 480, "a fifth of capacity")):
      client = "%d is the most, and we do about %d." % (b, a)
      dis = _check("So you are about %s." % words, client)
      self.assertTrue(any(d.get("basis") == "proportion_in_words" for d in dis), (words, a, b, dis))

  def test_an_ordinal_or_her_own_proportion_is_not_derived(self):
    client = "We run about three-quarters full most weeks; 26 done, 34 would be flat out."
    for reply in ("So you are about three-quarters full, as you said.", "Tell me about a third line of business."):
      dis = _check(reply, client if "as you said" in reply else "26 done, 34 would be flat out.")
      self.assertFalse(any(d.get("basis") == "proportion_in_words" for d in dis), (reply, dis))

  def test_her_own_spelled_percentage_is_not_derived(self):
    client = "We can take 480 a week and we run at about seventy-one percent of that, so about 340."
    dis = _check("Running at about seventy-one percent, then.", client)
    self.assertFalse(any(d.get("kind") == "derived_figure_read_back" for d in dis), dis)


class AProductOfHerFiguresIsNeverExplained(unittest.TestCase):
  """Cowork 1017 / 1019: "480, which works out to 24,960 a year" is not a
  ratio - it is 480 x 52, and 52 is a stored constant, not something she said.
  Products are caught by the explanation check, not the ratio rule: no product
  of two figures is in the set a reply may state. Pinned here as a property,
  whatever kind the disagreement is filed under.

  DELIBERATE CARVE-OUT, disclosed: a stated figure restated x12 / x4 / x3 or
  divided by them (monthly <-> annual <-> quarterly) is still explained - that
  is the financial walk's basis rule, shared with every other door B check."""

  def _caught(self, dis, value):
    return any(d.get("value") is not None and abs(float(d["value"]) - value) < 1e-6 for d in dis)

  def test_a_product_of_two_figures_she_said(self):
    from client_intake_and_finmo.intake_watcher.checks import _close, _equivalents  # type: ignore

    cases = 0
    for a, b in itertools.product((7, 26, 95, 340, 480), (5, 34, 52, 610)):
      prod = a * b
      if any(_close(s, e) for s in (a, b) for e in _equivalents(prod)):
        continue                    # a genuine coincidence with a figure she said
      client = "About %d dollars a job, and we do %d of them." % (b, a)
      dis = _check("So that works out to %s in total." % format(prod, ","), client)
      self.assertTrue(self._caught(dis, prod), "%d x %d = %d went out: %s" % (a, b, prod, dis))
      cases += 1
    self.assertGreater(cases, 15)

  def test_her_figure_times_a_stored_constant(self):
    for a in (14, 95, 340, 480, 2600):
      store = {"ops": {"lob_models": [{"products": [
        {"product_name": "x", "unit_cadence": "weekly", "units_per_week_capacity": a,
         "operating_periods_per_year": 52}]}]}}
      client = "We can take %d a week." % a
      dis = _check("That is %d a week, which works out to %s a year." % (a, format(a * 52, ",")), client, store)
      self.assertTrue(self._caught(dis, a * 52), "%d x 52 went out: %s" % (a, dis))
      self.assertFalse(self._caught(dis, a), "her own %d was flagged" % a)


class HerOwnFiguresAreNeverCaught(unittest.TestCase):
  def test_a_figure_she_spelled_out_is_hers(self):
    for n in (14, 26, 95, 340, 480, 1250, 24000):
      client = "In practice we're doing about %s a week." % _spell(n)
      dis = _check("About %s a week - got it." % format(n, ","), client)
      self.assertEqual(dis, [], "her spelled %r (%d) was called unsaid: %s" % (_spell(n), n, dis))

  def test_the_spelled_parser_reads_every_generated_number(self):
    from client_intake_and_finmo.intake_guard.door_a import numbers_in_words  # type: ignore

    for n in list(range(10, 120)) + [199, 340, 480, 999, 1001, 1250, 24000, 250000]:
      self.assertIn(float(n), numbers_in_words("about %s most weeks" % _spell(n)), _spell(n))

  def test_a_percentage_she_said_is_hers(self):
    for said in ("about 85 percent", "about 85%", "about eighty-five percent"):
      client = "We can take 480 a week and we run at %s of that." % said
      dis = _check("Running at 85% of capacity, then.", client)
      self.assertFalse(any(d.get("kind") == "derived_figure_read_back" for d in dis), (said, dis))

  def test_a_stored_rate_and_market_context_are_not_derived(self):
    client = "480 a week flat out, about 340 actually, 95 dollars a sample."
    store = {"financials": {"cogs_rate_stated": 0.35}}
    for reply in ("Materials run about 35% of revenue.", "Labs like yours often run 3%-6% margins."):
      dis = _check(reply, client, store)
      self.assertFalse(any(d.get("kind") == "derived_figure_read_back" for d in dis), (reply, dis))


class TheCw069TurnAsItWasWritten(unittest.TestCase):
  """The regression record. The client's message is verbatim; the reply is the
  consultant's draft as door B's audit rows quote it (three fragments, joined)."""
  _CLIENT = ("Four hundred and eighty a week is what the lab can take when everything's running properly. "
             "In practice we're doing about three hundred and forty most weeks. The accreditation caps us "
             "at 480, we can't just decide to do more.")
  _REPLY = ("Got it—so I’ll note that your lab testing job’s official weekly capacity is 480, which works "
            "out to 24,960 a year.\n\nThat’s helpful context, including the accreditation cap at 480 samples per "
            "week and the reality of about 340 in a typical week.\n\nFor planning the year ahead, would you be "
            "comfortable using “about 70% of that 480‑sample weekly capacity” as the typical load?")
  _STORE = {"ops": {"lob_models": [{"lob_name": "Lab testing services", "products": [
    {"product_name": "Lab testing job", "unit_cadence": "weekly", "units_per_week_capacity": 480,
     "units_per_period_capacity": 480, "operating_periods_per_year": 52, "unit_price": 95}]}]}}

  def test_the_seventy_is_derived_her_340_is_hers_and_the_annual_conversion_is_unsaid(self):
    dis = _check(self._REPLY, self._CLIENT, self._STORE)
    self.assertTrue(_derived(dis, 70.0), dis)
    self.assertFalse(any(d.get("value") == 340 for d in dis), "her own 340 was flagged: %s" % dis)
    self.assertTrue(any(d.get("kind") == "claimed_figure_not_in_store" and d.get("value") == 24960 for d in dis),
                    dis)


class AWordAfterHerFigureIsNotAMultiplier(unittest.TestCase):
  """CW-069 replay, turn 13, on the fixed build: door B read "about 340 most
  weeks" as 340 MILLION - the m of "most" taken for a multiplier - so her own
  figure was unexplained and the rewrite deleted it again. Any business says
  "12 months", "5 miles", "40 more", "3 kits"."""

  def test_no_word_starting_with_k_or_m_scales_a_figure(self):
    from client_intake_and_finmo.intake_guard.door_b import _dollar_figures  # type: ignore

    for n, word in itertools.product((3, 12, 340, 2600),
                                     ("most weeks", "months", "miles", "members", "more", "kits", "kilos",
                                      "mornings", "kids", "metres")):
      self.assertEqual([f["value"] for f in _dollar_figures("about %d %s" % (n, word))], [float(n)],
                       "%d %s was scaled" % (n, word))

  def test_no_other_number_reader_scales_on_a_following_word(self):
    """Cowork 1025: how many places carry that pattern. Three more did - the
    compact-number readers the intake uses on client answers."""
    from api_handlers.intake_consult import (  # type: ignore
      _extract_compact_numbers, _extract_single_compact_number,
      _extract_single_compact_number_allow_zero,
    )
    for n, word in itertools.product((3, 12, 340, 2600), ("most weeks", "months", "miles", "more", "kits")):
      text = "about %d %s" % (n, word)
      self.assertEqual(_extract_compact_numbers(text), [float(n)], text)
      self.assertEqual(_extract_single_compact_number(text), float(n), text)
      self.assertEqual(_extract_single_compact_number_allow_zero(text), float(n), text)
    # a real multiplier WORD still scales - the first boundary fix broke "3 million
    # packages" (16 stored capacities on three parcel drafts read it right by the
    # old accident); found by counting, not by these pins
    for text, value in (("12k", 12000.0), ("$1.2M.", 1.2e6), ("5 m", 5e6),
                        ("about 3 million packages per week", 3e6), ("1.2 million parcels", 1.2e6),
                        ("40 thousand a year", 40000.0), ("$2 Million", 2e6)):
      self.assertEqual(_extract_single_compact_number(text), value, text)
      self.assertEqual(_extract_compact_numbers(text), [value], text)
    from client_intake_and_finmo.intent_router import _extract_compact_numbers as _router_numbers  # type: ignore
    for n, word in itertools.product((3, 60, 340), ("most weeks", "months", "more")):
      self.assertEqual(_router_numbers("about %d %s" % (n, word)), [float(n)], "router: %d %s" % (n, word))
    self.assertEqual(_router_numbers("60k to 120k"), [60000.0, 120000.0])
    self.assertEqual(_router_numbers("about 3 million a year"), [3e6])
    self.assertEqual(_router_numbers("40 thousand to 1.2 million"), [40000.0, 1.2e6])

  def test_a_real_multiplier_still_scales(self):
    from client_intake_and_finmo.intake_guard.door_b import _dollar_figures  # type: ignore

    for text, value in (("about 4.6 million a year", 4.6e6), ("12k a month", 12000.0),
                        ("$5m in sales", 5e6), ("40 thousand a year", 40000.0)):
      self.assertEqual([f["value"] for f in _dollar_figures(text)], [value], text)

  def test_the_replay_sentence_as_it_was_written(self):
    reply = ("Thanks—that’s really clear: 480 samples per week is your accredited ceiling, and in practice "
             "you’re running about 340 most weeks.")
    self.assertEqual(_check(reply, TheCw069TurnAsItWasWritten._CLIENT, TheCw069TurnAsItWasWritten._STORE), [])


class TheRewriteIsShownTheOwnersWords(unittest.TestCase):
  """Told never to remove a figure the owner stated, door B's rewrite model was
  never sent what the owner stated. Twice on CW-069 it removed her 340 as "not
  in the store". Whatever the owner said is in what the model is given."""

  class _Resp:
    status_code = 200
    text = ""

    def __init__(self, obj):
      self._obj = obj

    def json(self):
      import json
      return {"output": [{"content": [{"type": "output_text", "text": json.dumps(self._obj)}]}]}

  def test_the_model_receives_every_recent_owner_message(self):
    import json
    import os
    from client_intake_and_finmo.intake_guard import door_b as B  # type: ignore

    saved = {k: os.environ.get(k) for k in ("OPENAI_API_KEY", "INTAKE_GUARD_ENABLED")}
    os.environ["OPENAI_API_KEY"] = saved["OPENAI_API_KEY"] or "test-key"
    os.environ["INTAKE_GUARD_ENABLED"] = "1"
    try:
      # each reply carries a percentage that IS a ratio of that owner's figures,
      # so a disagreement exists and the model is called
      for earlier, latest, reply in (
          ("We started nine years ago.", "We could do 480 flat out and actually do about 340.",
           "That is about 71% of capacity."),
          ("Two vans, twelve staff.", "Six at once, 34 a year flat out, about 26 in a year.",
           "That is about 76% of what you could do.")):
        seen = []

        def fake_post(**kw):
          seen.append(json.loads(kw["payload"]["input"][1]["content"]))
          return self._Resp({"reply": "", "changed": False, "why": "x"})

        B.review(text=reply, store={}, post=fake_post, user_text=latest, recent_user_texts=[earlier])
        self.assertEqual(len(seen), 1, "the derived percent did not reach the model")
        self.assertIn(latest, seen[0].get("owner_words") or [])
        self.assertIn(earlier, seen[0].get("owner_words") or [])
    finally:
      for k, v in saved.items():
        if v is None:
          os.environ.pop(k, None)
        else:
          os.environ[k] = v


class ThePromptNoLongerAsksForADerivedFigure(unittest.TestCase):
  def test_the_consultant_is_not_told_to_propose_one(self):
    src = (ROOT / "python" / "client_intake_and_finmo" / "intake_consultant.py").read_text(encoding="utf-8-sig")
    for instruction in ("Propose a practical utilization assumption",
                        "translate that annual total into an implied turns",
                        "propose the most likely annual turns assumption"):
      self.assertNotIn(instruction, src)
    self.assertIn("NEVER propose a utilization percentage", src)
    self.assertIn("whether you asked for it or they volunteered it", src)


if __name__ == "__main__":
  unittest.main(verbosity=2)
