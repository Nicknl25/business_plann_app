"""Nick's payroll directive (2026-09-09), fixes 1 and 2, pinned.

Live evidence: Marchetti & Fen (draft 3201a64c), an architecture practice
with two named partners and a nine-person team.

1. THE PEOPLE WRITE GUARD - a people.people patch merges by row identity,
   never replaces the roster wholesale. Rasheed Fennimore (second partner,
   $142,000) was deleted when the close-out patch carried only Ottoline;
   removal happens only through the explicit remove_role door. Within a
   merged row an incoming null/absent field is "no statement", never
   "erase" (the per-line COGS carry-forward doctrine, applied to people).

2. THE FALSE-RECEIPT CLASS - a patch write to a recalc-derived financials
   field must never be dropped in silence at _apply_scoped_patch. A
   payroll-total statement REDIRECTS to payroll_stated_total_target (the
   CW-024 stated-total door the Recalc folds); every other derived field
   is dropped WITH a receipt (_derived_patch_receipt) the caller must
   surface. "The app said it recorded a correction and didn't" is the
   worst class of defect we have and it has now appeared twice.
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
  _apply_scoped_patch,
  _merge_people_rows,
)
from client_intake_and_finmo.capture_receipt import (  # noqa: E402
  numeric_receipt,
  receipt_summary,
)


def _scoped(patch, people=None, financials=None):
  _bf, _ops, _mk, next_people, next_financials, _ff = _apply_scoped_patch(
    patch,
    business_facts={}, ops_json={}, market_json={},
    people_json=people or {}, financials_json=financials or {},
    fulfillment_json={},
  )
  return next_people, next_financials


MARCHETTI_PEOPLE = {"people": [
  {"full_name": "Ottoline Marchetti", "role_title": "Principal Architect",
   "annual_wage": 155000},
  {"full_name": "Rasheed Fennimore", "role_title": "Partner",
   "annual_wage": 142000},
]}


class PeopleWriteGuardTests(unittest.TestCase):
  def test_named_person_absent_from_incoming_is_restored(self):
    """The Marchetti deletion: a close-out patch carrying only Ottoline
    must not erase Rasheed - the roster merges, never replaces."""
    next_people, _ = _scoped(
      {"people.people": [
        {"full_name": "Ottoline Marchetti",
         "role_title": "Principal Architect", "annual_wage": 155000},
      ]},
      people=dict(MARCHETTI_PEOPLE),
    )
    names = [r.get("full_name") for r in next_people["people"]]
    self.assertIn("Rasheed Fennimore", names)
    self.assertIn("Ottoline Marchetti", names)
    rasheed = next(r for r in next_people["people"]
                   if r.get("full_name") == "Rasheed Fennimore")
    self.assertEqual(rasheed.get("annual_wage"), 142000)

  def test_incoming_null_field_never_erases(self):
    """Null against a standing value is 'no statement' - the wage rides
    forward (the per-line COGS doctrine at the people payload)."""
    next_people, _ = _scoped(
      {"people.people": [
        {"full_name": "Ottoline Marchetti", "role_title": None,
         "annual_wage": None},
        {"full_name": "Rasheed Fennimore", "role_title": "Partner",
         "annual_wage": 142000},
      ]},
      people=dict(MARCHETTI_PEOPLE),
    )
    ottoline = next(r for r in next_people["people"]
                    if r.get("full_name") == "Ottoline Marchetti")
    self.assertEqual(ottoline.get("annual_wage"), 155000)
    self.assertEqual(ottoline.get("role_title"), "Principal Architect")

  def test_incoming_stated_field_wins(self):
    next_people, _ = _scoped(
      {"people.people": [
        {"full_name": "Ottoline Marchetti", "annual_wage": 160000},
      ]},
      people=dict(MARCHETTI_PEOPLE),
    )
    ottoline = next(r for r in next_people["people"]
                    if r.get("full_name") == "Ottoline Marchetti")
    self.assertEqual(ottoline.get("annual_wage"), 160000)

  def test_new_person_appends(self):
    next_people, _ = _scoped(
      {"people.people": [
        {"full_name": "Priya Venkataraman", "role_title": "Project Architect",
         "annual_wage": 98000},
      ]},
      people=dict(MARCHETTI_PEOPLE),
    )
    self.assertEqual(len(next_people["people"]), 3)

  def test_unnamed_role_row_is_restored_too(self):
    """Absence from incoming never erases - removal has its own door."""
    people = {"people": [
      {"full_name": "Ottoline Marchetti", "annual_wage": 155000},
      {"role_title": "Drafting Technician", "annual_wage": 62000},
    ]}
    next_people, _ = _scoped(
      {"people.people": [
        {"full_name": "Ottoline Marchetti", "annual_wage": 155000},
      ]},
      people=people,
    )
    titles = [r.get("role_title") for r in next_people["people"]]
    self.assertIn("Drafting Technician", titles)

  def test_explicit_remove_role_door_still_removes(self):
    """The remove path is the ONE legal removal - the guard must not
    swallow it."""
    next_people, _ = _scoped(
      {"people.remove_role": "Rasheed Fennimore"},
      people=dict(MARCHETTI_PEOPLE),
    )
    names = [r.get("full_name") for r in next_people["people"]]
    self.assertNotIn("Rasheed Fennimore", names)
    self.assertIn("Ottoline Marchetti", names)

  def test_merge_report_names_the_restored(self):
    merged, report = _merge_people_rows(
      MARCHETTI_PEOPLE["people"],
      [{"full_name": "Ottoline Marchetti", "annual_wage": 155000}],
    )
    self.assertEqual(report["restored"], ["Rasheed Fennimore"])
    self.assertEqual(report["merged"], ["Ottoline Marchetti"])
    self.assertEqual(len(merged), 2)

  def test_named_and_unnamed_rows_never_cross_match(self):
    """'Partner' with no name is not Rasheed - a guessed identity is a
    silent rename."""
    merged, report = _merge_people_rows(
      MARCHETTI_PEOPLE["people"],
      [{"role_title": "Partner", "annual_wage": 90000}],
    )
    self.assertIn("Rasheed Fennimore", report["restored"])
    rasheed = next(r for r in merged
                   if r.get("full_name") == "Rasheed Fennimore")
    self.assertEqual(rasheed.get("annual_wage"), 142000)


class DerivedFieldDoorReceiptTests(unittest.TestCase):
  def test_payroll_total_redirects_to_stated_total_target(self):
    """The client's payroll correction lands at its one real door (the
    CW-024 target the Recalc folds) instead of evaporating."""
    _, fin = _scoped(
      {"financials.payroll_total_year1": 720000},
      financials={"payroll_total_year1": 678000, "current_payroll": 678000},
    )
    self.assertEqual(fin.get("payroll_stated_total_target"), 720000.0)
    # the derived twin itself is untouched - the fold owns it
    self.assertEqual(fin.get("payroll_total_year1"), 678000)
    receipt = fin.get("_derived_patch_receipt")
    self.assertEqual(receipt[0]["disposition"], "redirected_stated_total")
    self.assertEqual(receipt[0]["field"], "payroll_total_year1")

  def test_current_payroll_redirects_the_same_way(self):
    _, fin = _scoped(
      {"financials.current_payroll": 720000},
      financials={"current_payroll": 678000},
    )
    self.assertEqual(fin.get("payroll_stated_total_target"), 720000.0)

  def test_other_derived_field_drops_with_a_receipt(self):
    """No silent drop: the door records what it refused so the caller's
    say-do accounting can speak it."""
    _, fin = _scoped(
      {"financials.owner_compensation": 12000},
      financials={"owner_compensation": 10000},
    )
    self.assertEqual(fin.get("owner_compensation"), 10000)
    receipt = fin.get("_derived_patch_receipt")
    self.assertEqual(receipt[0]["disposition"], "derived_dropped")
    self.assertEqual(receipt[0]["field"], "owner_compensation")

  def test_total_team_payroll_door_leaves_a_receipt(self):
    """Door-smoke finding (482b870f turn 1): the stated-total door landed
    the write and folded, but no receipt reached the flow - the reply
    said 'I wasn't able to apply that change' over a landed write. The
    door now leaves the same redirect receipt as the financials remap."""
    _, fin = _scoped(
      {"people.total_team_payroll": 200000},
      financials={"current_payroll": 183322.5},
    )
    self.assertEqual(fin.get("payroll_stated_total_target"), 200000.0)
    receipt = fin.get("_derived_patch_receipt")
    self.assertEqual(receipt[0]["disposition"], "redirected_stated_total")
    self.assertEqual(receipt[0]["field"], "total_team_payroll")

  def test_non_derived_field_still_lands_directly(self):
    _, fin = _scoped(
      {"financials.cash_on_hand": 52000},
      financials={},
    )
    self.assertEqual(fin.get("cash_on_hand"), 52000)
    self.assertNotIn("_derived_patch_receipt", fin)

  def test_stated_total_target_never_renders_in_receipt_summary(self):
    """The target is transport to the fold - the door's own deterministic
    sentence speaks it; the numeric receipt must not."""
    receipt = numeric_receipt(
      before={"financials": {"current_payroll": 678000}},
      after={"financials": {"current_payroll": 678000,
                            "payroll_stated_total_target": 720000}},
      requested_fields=["financials.current_payroll"],
    )
    self.assertEqual(receipt_summary(receipt), "")


if __name__ == "__main__":
  unittest.main()
