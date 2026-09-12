"""A RECEIPT MUST NOT LIE ABOUT A FIELD ITS OWN DOOR JUST LANDED (Nick
2026-09-12: "that's a receipt lying to a client and it's the same family we
just spent a day on").

Every intake gate transcript since 2026-09-11 15:19 carried, in ONE reply:

  "I have updated your info to show an annual wage of $62,000 ... and total
   owner pay of $5,167 per month. (One note: I haven't recorded owner pay
   monthly yet - we'll get to that in a moment.)"

people.owner_pay_monthly is a pseudo-field the scoped apply CONSUMES: it
lands on the owner's row (annual_wage) and the owner_compensation mirror and
is never stored under its own name. numeric_receipt diffs written and stored
leaves against the requested fields, saw neither, and called it dropped -
the door's own receipt one sentence earlier said the opposite. A
door-consumed field is landed by definition; its door speaks for it.
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

from client_intake_and_finmo.capture_receipt import numeric_receipt, receipt_summary  # noqa: E402


def _owner_pay_turn():
  """The Larkspur turn 25 shape: owner_pay_monthly consumed, the wage
  landing on the owner's row and the mirror - no leaf named owner_pay_monthly
  anywhere after."""
  before = {"people": {"people": [{"full_name": "Jess Harlow", "role_title": "Owner", "annual_wage": None}]},
            "financials": {}}
  after = {"people": {"people": [{"full_name": "Jess Harlow", "role_title": "Owner", "annual_wage": 62000.0,
                                  "wage_source": "client_override", "is_owner": True}]},
           "financials": {"owner_compensation": 5166.67}}
  return before, after


class ADoorConsumedFieldIsNeverDropped(unittest.TestCase):
  def test_owner_pay_monthly_is_not_reported_as_unrecorded(self):
    before, after = _owner_pay_turn()
    rec = numeric_receipt(before=before, after=after,
                          requested_fields=["people.owner_pay_monthly", "people.people"])
    self.assertNotIn("people.owner_pay_monthly", rec["dropped"])
    self.assertEqual([d for d in rec["dropped"] if d.endswith("owner_pay_monthly")], [])

  def test_the_other_door_consumed_fields_are_never_dropped_either(self):
    before = {"people": {"people": []}, "financials": {}}
    after = {"people": {"people": []}, "financials": {}}
    rec = numeric_receipt(
      before=before, after=after,
      requested_fields=["people.total_team_payroll", "people.remove_role", "people.phase_planned_hires"])
    self.assertEqual(rec["dropped"], [])

  def test_a_genuinely_dropped_field_is_still_dropped(self):
    """The exclusion is exact: a field the door does NOT own and that
    landed nowhere is still owed a note."""
    before = {"financials": {"monthly_rent_expense": 12000.0}}
    after = {"financials": {"monthly_rent_expense": 12000.0}}
    rec = numeric_receipt(before=before, after=after,
                          requested_fields=["financials.other_operating_expense"])
    self.assertEqual(rec["dropped"], ["financials.other_operating_expense"])

  def test_a_consumed_field_is_never_rendered_raw(self):
    """The summary must not speak 'owner pay monthly -> $5,167' either -
    the owner-pay door composes its own deterministic receipt."""
    before, after = _owner_pay_turn()
    rec = numeric_receipt(before=before, after=after, requested_fields=["people.owner_pay_monthly"])
    text = receipt_summary(rec) or ""
    self.assertNotIn("owner pay monthly", text.lower())


if __name__ == "__main__":
  unittest.main()
