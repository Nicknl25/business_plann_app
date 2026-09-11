"""The intake persona gate's own pins: the matcher answers only what it is
scripted to answer, and every check goes red on the real defect shape and
green on a clean one (Nick 2026-09-11: "build the equivalent for intake").
Synthetic records - no app, no DB, no GPT."""
from __future__ import annotations

import copy
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "scripts"), os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

import intake_persona_gate as G  # noqa: E402
import intake_personas as PS  # noqa: E402


def _rules(*rs):
  return [dict(r, used=0) for r in rs]


def _snap(full=None, bath=None, people=None, pool=None, payroll=None, focus="ops", confirmed=False, fin=None):
  products = []
  if full is not None:
    products.append(dict(product_name="Full groom", **full))
  if bath is not None:
    products.append(dict(product_name="Bath and tidy", **bath))
  f = dict(fin or {})
  if payroll is not None:
    f["current_payroll"] = payroll
  return {"status": "in_progress", "focus": focus, "financials_confirmed": confirmed,
          "ops": {"lob_models": [{"products": products}]},
          "people": {"people": people or [], "rest_of_team_payroll_year1": pool}, "fin": f}


def _rec(*turns):
  rec = G.Record()
  for i, (rule, sent, reply, snap, done) in enumerate(turns):
    rec.turns.append({"i": i, "rule": rule, "sent": sent, "reply": reply, "snap": snap,
                      "done": done, "focus": snap["focus"]})
  return rec


class MatcherTests(unittest.TestCase):
  def test_a_receipt_never_answers_for_the_question(self):
    rules = _rules(PS.R("rent", "financials", r"\brent\b", "$4,500 a month."),
                   PS.R("other", "financials", r"other regular business bills", "$1,500 a month."))
    msg = ("Got it - I'll use $4,500 for monthly rent.\n\nAbout how much goes to other regular "
           "business bills in a typical month?")
    self.assertEqual(G.pick_rule(rules, msg, "financials")["id"], "other")

  def test_stage_used_count_and_order(self):
    rules = _rules(PS.R("a1", "people", r"add another", "Dana."),
                   PS.R("a2", "people", r"add another", "No one else."))
    self.assertIsNone(G.pick_rule(rules, "Add another person?", "ops"))
    first = G.pick_rule(rules, "Add another person?", "people")
    first["used"] += 1
    self.assertEqual((first["id"], G.pick_rule(rules, "Add another person?", "people")["id"]), ("a1", "a2"))

  def test_an_unscripted_question_gets_no_answer(self):
    self.assertIsNone(G.pick_rule(_rules(*PS.BASE_RULES), "Do you have a favourite breed to work on?", "ops"))

  def test_the_first_real_unscripted_question_is_now_a_confirmation(self):
    msg = "Is that an accurate high-level description of how the business works?"
    self.assertEqual(G.pick_rule(_rules(*PS.BASE_RULES), msg, "ops")["id"], "confirm")


class UniversalCheckTests(unittest.TestCase):
  def test_u1_green_on_a_token_the_frontend_fills(self):
    """{{fact:business.name}} is by design - renderFactTemplate.ts fills it.
    The first version of U1 called it a leak; that was wrong."""
    s = _snap()
    rec = _rec(("seed", "", "Describe it?", s, False),
               ("describe", "x", "Here's how I'm understanding {{fact:business.name}} operationally.", s, False))
    rec.business = dict(PS.BOOTSTRAP)
    self.assertTrue(PS.u1_every_token_fills(rec)[0])

  def test_u1_red_on_a_hole_and_on_a_non_fact_token(self):
    s = _snap(full={"unit_price": 85})
    for reply, why in (("Your {{fact:ops.no_such_field}} is set.", "fills with nothing"),
                       ("Hi {{client_name}}, next question?", "not a fact token")):
      rec = _rec(("seed", "", "q?", s, False), ("describe", "x", reply, s, False))
      rec.business = dict(PS.BOOTSTRAP)
      ok, detail = PS.u1_every_token_fills(rec)
      self.assertFalse(ok, reply)
      self.assertIn(why, detail)

  def test_u1_fills_an_ops_product_field_from_the_first_product(self):
    s = _snap(full={"unit_price": 85})
    rec = _rec(("seed", "", "q?", s, False), ("describe", "x", "At {{fact:ops.unit_price}} a groom?", s, False))
    rec.business = dict(PS.BOOTSTRAP)
    self.assertTrue(PS.u1_every_token_fills(rec)[0])

  def test_u3_red_on_every_real_bounce_shape_green_on_a_real_question(self):
    s = _snap()
    for bounced in (
        "The About 80 percent of the full-groom slots are booked on average. - is that your "
        "financials summary, or your weekly capacity?",
        "You also mentioned 80 percent on wellness - which figure is that, so I record it in the right place?",
        "The six or seven weeks each - is that your time?"):
      rec = _rec(("seed", "", "q?", s, False), ("util_full", "80 percent", bounced, s, False))
      self.assertFalse(PS.u3_no_figure_bounced(rec)[0], bounced)
    rec = _rec(("seed", "", "q?", s, False),
               ("util_full", "80 percent", "Got it, 80%. What's your average price for a full groom?", s, False))
    self.assertTrue(PS.u3_no_figure_bounced(rec)[0])


class CapacityReaskTests(unittest.TestCase):
  REASK = ("Just so I'm clear on your capacity, when you're fully booked, about how many units can "
           "you realistically handle-what's the one number you have in mind?")

  def test_u4_red_when_the_app_asks_again_for_a_stored_capacity(self):
    s = _snap(full={"units_per_week_capacity": 120}, bath={"units_per_week_capacity": 150})
    rec = _rec(("seed", "", "q?", s, False),
               ("util_any", "About 80 percent on full grooms and about 70 on baths.", self.REASK, s, False))
    ok, detail = PS.u4_stored_capacity_never_reasked(rec)
    self.assertFalse(ok)
    self.assertIn("full/bath", detail)

  def test_u4_green_when_no_capacity_is_stored_yet(self):
    s = _snap(full={}, bath={})
    rec = _rec(("seed", "", "q?", s, False), ("describe", "x", self.REASK, s, False))
    self.assertTrue(PS.u4_stored_capacity_never_reasked(rec)[0])

  def test_a_booking_level_question_is_utilization_not_channel(self):
    """Baseline 2026-09-11 turn 10 - the channel rule answered this."""
    msg = ("Thanks for clarifying.\n\nJust to confirm the other service: for bath-and-tidies, you "
           "mentioned about 70% earlier-does that still sound like the right average booking level "
           "for that service over a typical week?")
    self.assertEqual(G.pick_rule(_rules(*PS.BASE_RULES), msg, "ops")["id"], "util_bath")

  def test_the_three_unscripted_questions_of_the_1536_run_are_scripted(self):
    for msg, focus, want in (
        ("Perfect, $85 per dog for a full groom.\n\nFor the bath-and-tidy service, what does a typical "
         "visit average per dog right now?", "ops", "price_bath"),
        ("Concretely, does it feel accurate to say your main service area is east-side Portland "
         "neighborhoods?", "ops", "confirm"),
        ("One quick thing I want to make sure I have right: in a typical appointment, are the grooms done "
         "by you and any grooming staff on-site, with dogs picked up the same day once they're finished?",
         "ops", "fulfillment")):
      rules = _rules(*PS.BASE_RULES)
      if want == "confirm":  # the geography rule is spent by then
        for r in rules:
          if r["id"] == "geography":
            r["used"] = 1
      self.assertEqual(G.pick_rule(rules, msg, focus)["id"], want, msg)

  def test_the_improvised_questions_of_the_1540_round_are_scripted(self):
    spent = {"geography", "key_person_1", "add_another_1"}
    for msg, focus, want in (
        ("Just to keep this clean: what do you think truly sets Larkspur Dog Grooming apart from other "
         "groomers on Portland's east side?", "ops", "advantage"),
        ("I'd summarize your main service area as Portland's east side. Does that match how you think "
         "about your coverage?", "ops", "confirm"),
        ("Is there another individual you'd like to add as a key person? If so, please share their full "
         "name and what they're currently paid per year.", "people", "add_another_2")):
      rules = _rules(*PS.BASE_RULES)
      for r in rules:
        if r["id"] in spent:
          r["used"] = 1
      self.assertEqual(G.pick_rule(rules, msg, focus)["id"], want, msg)

  def test_the_add_another_wordings_of_the_1548_round_are_scripted(self):
    for msg in (
        "Would you like to add any other specific key individuals (for example, a salon manager), or are "
        "Jess and Dana the only people you want treated as key people for now?",
        "Is there a specific individual (like Dana or any other named person) who plays a key, ongoing "
        "role in running the salon that you'd like to include?",
        "Do you have any other named key people you'd like to add (another senior groomer, manager, or "
        "similar), or are you all set with people for now?"):
      rules = _rules(*PS.BASE_RULES)
      for r in rules:
        if r["id"] == "key_person_1":
          r["used"] = 1
      self.assertEqual(G.pick_rule(rules, msg, "people")["id"], "add_another_1", msg)

  def test_the_inventory_question_is_not_answered_with_cogs(self):
    """stated_total 2026-09-11 turn 45 - 'supplies kept in stock' matched cogs."""
    msg = ("Got it - I'll use $3,000 for accounts payable.\n\nAbout how much inventory do you have on hand "
           "right now, like products or supplies kept in stock to use or sell?")
    self.assertEqual(G.pick_rule(_rules(*PS.BASE_RULES), msg, "financials")["id"], "inventory")

  def test_the_other_bills_question_is_not_answered_with_marketing(self):
    msg = ("About how much goes to other regular business bills in a typical month, besides payroll, "
           "marketing, and rent - things like utilities, software, insurance, accounting, phone, and internet?")
    self.assertEqual(G.pick_rule(_rules(*PS.BASE_RULES), msg, "financials")["id"], "other_opex")


class LineCheckTests(unittest.TestCase):
  def test_c3_red_when_a_capacity_answer_writes_the_price(self):
    """Issue 578's shape: one capacity figure landed as capacity AND unit_price."""
    before = _snap(full={}, bath={})
    after = _snap(full={"units_per_week_capacity": 120, "unit_price": 120}, bath={})
    rec = _rec(("seed", "", "q?", before, False), ("cap_full", "About 120 a week.", "ok?", after, False))
    ok, detail = PS.c3_figure_stays_on_its_line(rec)
    self.assertFalse(ok)
    self.assertIn("unit_price", detail)

  def test_c3_red_when_a_figure_lands_on_the_other_line(self):
    """Ardenwald's shape: a price on a line the conversation had not reached."""
    before = _snap(full={}, bath={})
    after = _snap(full={"unit_price": 85}, bath={"unit_price": 85})
    rec = _rec(("seed", "", "q?", before, False), ("price_full", "$85.", "ok?", after, False))
    self.assertFalse(PS.c3_figure_stays_on_its_line(rec)[0])

  def test_c3_green_when_each_figure_lands_where_it_was_said(self):
    s0 = _snap(full={}, bath={})
    s1 = _snap(full={"units_per_week_capacity": 120}, bath={})
    s2 = _snap(full={"units_per_week_capacity": 120}, bath={"units_per_week_capacity": 150})
    rec = _rec(("seed", "", "q?", s0, False), ("cap_full", "120", "ok?", s1, False), ("cap_bath", "150", "ok?", s2, False))
    ok, _detail = PS.c3_figure_stays_on_its_line(rec)
    self.assertIsNot(ok, False)


class PayrollCheckTests(unittest.TestCase):
  PEOPLE = [{"full_name": "Jess Harlow", "annual_wage": 62000.0}, {"full_name": "Dana Okafor", "annual_wage": 52000.0}]

  def _on_file(self, **kw):
    return _snap(people=copy.deepcopy(self.PEOPLE), pool=150000.0, payroll=264000.0, focus="financials", **kw)

  def test_c2_holds_open_red_when_the_intake_completes_with_the_question_open(self):
    s = self._on_file()
    done = self._on_file(confirmed=True)
    done["focus"] = "done"
    rec = _rec(("seed", "", "q?", s, False),
               ("headcount_with_total", "7, total $300,000", "I've recorded $264,000 ... $300,000 ...?", s, False),
               ("funding", "Equity.", "Thanks - the intake is complete.", done, True))
    ok, detail = PS.c2_holds_open(rec)
    self.assertFalse(ok)
    self.assertIn("completed at turn 2", detail)

  def test_c2_holds_open_green_when_the_last_answer_does_not_complete(self):
    s = self._on_file()
    rec = _rec(("seed", "", "q?", s, False),
               ("headcount_with_total", "7, total $300,000", "I've recorded $264,000 ... $300,000 ...?", s, False),
               ("funding", "Equity.", "I've recorded $264,000 across your named people ... on file?", s, False),
               ("hold_deflect", "Later.", "I've recorded $264,000 across your named people ... on file?", s, False))
    self.assertTrue(PS.c2_holds_open(rec)[0])

  def test_c4_red_on_the_monthly_round_trip(self):
    """CW-026's 33,999.96: a monthly figure multiplied back to an annual one."""
    people = [{"full_name": "Dana Okafor", "annual_wage": 51999.96}]
    s = _snap(people=people)
    rec = _rec(("seed", "", "q?", s, False), ("restate_monthly", "$4,333.33 a month", "Got it.", s, False))
    ok, detail = PS.c4_wage_survives_monthly(rec)
    self.assertFalse(ok)
    self.assertIn("51999.96", detail)

  def test_u2_red_when_the_pool_was_plugged(self):
    """The plug: a pool nobody said, written to make a total reconcile."""
    s = _snap(people=copy.deepcopy(self.PEOPLE), pool=186000.0, payroll=300000.0, focus="done", confirmed=True)
    rec = _rec(("seed", "", "q?", s, False), ("funding", "Equity.", "Complete.", s, True))
    ok, detail = PS.u2_stated_figures_exact(rec)
    self.assertFalse(ok)
    self.assertIn("rest of team", detail)


if __name__ == "__main__":
  unittest.main()
