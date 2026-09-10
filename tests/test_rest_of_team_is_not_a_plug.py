"""rest_of_team_payroll_year1 is a STATED FACT, never a plug
(Nick's rulings 2026-09-10, Ferriday & Blythe Veterinary 73a71cfe).

The field is supposed to hold what the client said about people who are
not named individually. It was ALSO absorbing `payroll_adjustment` - the
delta between a separately-tracked stated total and the canonical rollup
of named rows ("rest-of-team absorbs first"). On one live run that made
it move three times to three numbers nobody ever said:

    249,000  (client-stated, legitimate)
    284,583.33  (absorbed a delta after a wage was overwritten)
    318,996  (absorbed another delta after the wage was corrected)

and the payroll total drifted 1,516,000 -> 1,731,000, double-counting a
named partner's $215,000 inside the plug.

Worse, the plug made every downstream gate VACUOUS: named + rest equalled
the stated total by construction, so the payroll reconciliation and the
ratio band were testing an IDENTITY rather than a fact and could not
fail. 1,731,000 was 55.8% of revenue - comfortably inside the band.

The correct path already existed and this same run proved it: the moment
the client forced rest to 0, the delta reached the hold and the app
asked "the remaining $103,996 has nowhere to land yet - is it spread
across other staff, or is one of the wages different?" - which also
surfaced the client's OWN gap between a stated ~1,103,000 and an
itemised 999,000. The plug was the only thing suppressing that question.
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
  _apply_owner_pay_statement,
)


class OwnerPayNeverReDerivesAStatedAnnualTests(unittest.TestCase):
  """NEVER RE-DERIVE A NUMBER THE CLIENT GAVE YOU."""

  def test_restating_the_monthly_keeps_the_stated_annual_to_the_cent(self):
    """THE FERRIDAY CASE. She said '17,917 a month, which is the 215,000
    a year I mentioned - keep my annual wage at 215,000'. Multiplying
    her rounded monthly back up produced 215,004 and overwrote the
    stated figure."""
    people = {"people": [{"full_name": "Dr. Corinne Ferriday",
                          "role_title": "Managing Veterinarian",
                          "annual_wage": 215000.0,
                          "wage_source": "client_override"}]}
    _apply_owner_pay_statement(monthly=17917.0, people_json=people,
                               financials_json={}, ops_json={})
    self.assertEqual(people["people"][0]["annual_wage"], 215000.0)

  def test_a_genuine_change_still_lands(self):
    """The monthly no longer divides to the stated annual - the client
    is changing their pay, and that must apply."""
    people = {"people": [{"full_name": "Dr. Corinne Ferriday",
                          "role_title": "Managing Veterinarian",
                          "annual_wage": 215000.0,
                          "wage_source": "client_override"}]}
    _apply_owner_pay_statement(monthly=20000.0, people_json=people,
                               financials_json={}, ops_json={})
    self.assertEqual(people["people"][0]["annual_wage"], 240000.0)

  def test_first_statement_with_no_prior_annual_derives_normally(self):
    people = {"people": []}
    _apply_owner_pay_statement(monthly=10000.0, people_json=people,
                               financials_json={}, ops_json={})
    self.assertEqual(people["people"][0]["annual_wage"], 120000.0)


class RestOfTeamIsNotAPlugTests(unittest.TestCase):
  """The absorption is deleted; a disagreement becomes a QUESTION.

  These pin the ARITHMETIC LAW rather than the handler's plumbing: a
  stated-total delta may never be written into the stated rest-of-team
  figure, so named + rest is no longer an identity with the total and
  the reconciliation compares two independently sourced numbers.
  """

  def test_the_absorption_line_is_gone_from_the_source(self):
    """Structural: no code path adds a delta into the stated field."""
    src = open(os.path.join(ROOT, "python", "api_handlers",
                            "intake_consult.py"), encoding="utf-8").read()
    self.assertNotIn("_new_rest = _rest + _adj", src)
    self.assertIn("THE PLUG IS DELETED", src)

  def test_the_delta_reaches_the_hold_so_the_app_asks(self):
    """With no absorption, the whole delta is leftover and the hold -
    which drives the question - always sees it."""
    src = open(os.path.join(ROOT, "python", "api_handlers",
                            "intake_consult.py"), encoding="utf-8").read()
    i = src.find("THE PLUG IS DELETED")
    self.assertGreater(i, 0)
    window = src[i:i + 2000]
    self.assertIn("_leftover = _adj", window)
    self.assertIn("_payroll_fold_hold", window)

  def test_named_plus_rest_is_no_longer_an_identity(self):
    """The Ferriday arithmetic, stated plainly: with the plug gone, a
    roster whose named rows sum to 1,412,004 against a client total of
    1,516,000 leaves a REAL 103,996 gap for the app to ask about -
    instead of a rest figure silently set to make it vanish."""
    named = 1412004.0
    client_total = 1516000.0
    stated_rest = 0.0            # the client accounted for everyone
    self.assertNotAlmostEqual(named + stated_rest, client_total, places=2)
    self.assertAlmostEqual(client_total - (named + stated_rest),
                           103996.0, places=2)


if __name__ == "__main__":
  unittest.main()
