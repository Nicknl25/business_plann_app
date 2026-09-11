"""A headcount the client did not say is not a headcount (Nick 2026-09-11,
Ferriday & Blythe Veterinary 73a71cfe).

At turn 77 the client said, verbatim: "Yes - Dr. Abasi Blythe. He is my
partner in the practice. 19 years in, DVM with a surgical residency behind
him. He takes 198,000." The router's raw output (response store,
19:09:49) wrote financials.current_num_employees = 2 - a count of the two
named rows. On a People turn nothing narrows router writes, so it landed.
The rest-of-team gate then saw headcount 2 against 2 waged roles and never
asked; the question fired zero times in 123 turns, and a nineteen-person
practice went to the model as two vets at 13.3% of revenue.

The two other businesses that night had no headcount inferred, so the gate
saw "unknown", asked, and captured a pool - one inferred number was the
whole difference.
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from api_handlers.intake_consult import (  # noqa: E402
  _drop_inferred_headcount,
  _message_states_headcount,
  _rest_of_team_payroll_pending,
)

FERRIDAY_TURN_77 = (
  "Yes - Dr. Abasi Blythe. He is my partner in the practice. 19 years in, "
  "DVM with a surgical residency behind him. He takes 198,000."
)
FERRIDAY_ROUTER_PATCH = {
  "people.people": [{"full_name": "Dr. Corinne Ferriday"},
                    {"full_name": "Dr. Abasi Blythe"}],
  "financials.current_payroll": 413000,
  "financials.current_num_employees": 2,
  "people.total_team_payroll": 413000,
}
TWO_VETS = {"people": [
  {"full_name": "Dr. Corinne Ferriday", "role_title": "Managing Veterinarian",
   "annual_wage": 215000.0},
  {"full_name": "Dr. Abasi Blythe", "role_title": "Partner Veterinarian",
   "annual_wage": 198000.0},
]}


class FerridayShapeTests(unittest.TestCase):
  def test_the_counted_headcount_is_dropped(self):
    patch, dropped = _drop_inferred_headcount(
      FERRIDAY_ROUTER_PATCH, focus="people", user_message=FERRIDAY_TURN_77)
    self.assertEqual(dropped, 2)
    self.assertNotIn("financials.current_num_employees", patch)

  def test_everything_else_in_the_patch_still_lands(self):
    patch, _ = _drop_inferred_headcount(
      FERRIDAY_ROUTER_PATCH, focus="people", user_message=FERRIDAY_TURN_77)
    for key in ("people.people", "financials.current_payroll",
                "people.total_team_payroll"):
      self.assertIn(key, patch)

  def test_the_original_patch_is_not_mutated(self):
    before = dict(FERRIDAY_ROUTER_PATCH)
    _drop_inferred_headcount(
      FERRIDAY_ROUTER_PATCH, focus="people", user_message=FERRIDAY_TURN_77)
    self.assertEqual(FERRIDAY_ROUTER_PATCH, before)

  def test_with_the_headcount_gone_the_gate_asks(self):
    """The consequence that matters: no stated headcount, two named people,
    no pool recorded -> the rest-of-team question fires."""
    self.assertTrue(_rest_of_team_payroll_pending(
      TWO_VETS, {}, None, {"current_payroll": 413000}))

  def test_with_the_inferred_headcount_the_gate_was_silenced(self):
    """What happened last night, pinned so the mechanism stays visible."""
    self.assertFalse(_rest_of_team_payroll_pending(
      TWO_VETS, {}, None, {"current_num_employees": 2}))

  def test_nineteen_years_is_not_nineteen_people(self):
    self.assertFalse(_message_states_headcount(FERRIDAY_TURN_77, 19))


class StatedCountsStillLandTests(unittest.TestCase):
  CASES = [
    ("There are nineteen of us altogether, not just the two of us.", 19),
    ("We have 19 people on staff.", 19),
    ("Just the two of us by name, but a team of 12 overall.", 12),
    ("It's just the two of us.", 2),
    ("Both of us work here full time.", 2),
    ("It's just me.", 1),
    ("Headcount is 7.", 7),
    ("We run with 5 full-time and a couple of part-timers.", 5),
  ]

  def test_stated_counts_are_recognised(self):
    for text, n in self.CASES:
      self.assertTrue(_message_states_headcount(text, n), (text, n))

  def test_a_stated_count_survives_the_guard(self):
    msg = "There are nineteen of us altogether."
    patch, dropped = _drop_inferred_headcount(
      {"financials.current_num_employees": 19}, focus="people", user_message=msg)
    self.assertIsNone(dropped)
    self.assertEqual(patch["financials.current_num_employees"], 19)

  def test_money_and_durations_are_not_headcounts(self):
    for text, n in (("He takes 198,000.", 198), ("$19 per visit", 19),
                    ("about 12 jobs a month", 12), ("12k a year", 12),
                    ("26 years practising", 26)):
      self.assertFalse(_message_states_headcount(text, n), (text, n))


class ScopeTests(unittest.TestCase):
  def test_financials_stage_is_untouched(self):
    """The financials stage asks the headcount question itself and its own
    narrowing owns that write - a bare "19" answer must still land."""
    patch, dropped = _drop_inferred_headcount(
      {"financials.current_num_employees": 19}, focus="financials",
      user_message="19")
    self.assertIsNone(dropped)
    self.assertIn("financials.current_num_employees", patch)

  def test_unscoped_key_is_guarded_too(self):
    patch, dropped = _drop_inferred_headcount(
      {"current_num_employees": 2}, focus="people",
      user_message=FERRIDAY_TURN_77)
    self.assertEqual(dropped, 2)
    self.assertNotIn("current_num_employees", patch)


if __name__ == "__main__":
  unittest.main()
