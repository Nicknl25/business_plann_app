"""Group rows count per person (Nick's ruling 2026-09-10).

"A row that says '3 project architects at 88,000 each' is three people.
If the stored total reads $239k against $311k stated, we're dropping two
of them. Same class as the co-owner collapse: a human disappearing
because a row was read as one thing."

Live evidence: Green Meadow Veterinary Clinic (e8206880) stored 'Two
Veterinary Technicians' at 40,000 EACH and 'Two Receptionists' at 32,000
EACH, counted each row once - 238,999.96 stored vs 311,000 stated.

The census that shaped the detector (17,870 person rows): 59/63 count
hits are the Sumac 'Crew (4) / Grounds crew (4 people)' rows whose
136,000 is the GROUP TOTAL - those match _GROUP_ROW_RE, belong to the
CW-024 fold, and MUST NOT multiply (they return headcount 1 here). Zero
false positives (no ordinals, no years).
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
  _compute_payroll_baseline,
  _person_row_headcount,
  _waged_role_count,
)

VET_PEOPLE = {"people": [
  {"full_name": "Alex Carter", "role_title": "Co-owner & Veterinarian",
   "annual_wage": 85000.0},
  {"full_name": "Jamie Lee", "role_title": "Co-owner & Veterinarian",
   "annual_wage": 82000.0},
  {"full_name": "Two Veterinary Technicians",
   "role_title": "Veterinary Technicians", "annual_wage": 40000.0},
  {"full_name": "Two Receptionists", "role_title": "Receptionists",
   "annual_wage": 32000.0},
]}


class GroupRowsCountPerPersonTests(unittest.TestCase):
  def test_vet_clinic_rollup_matches_what_the_client_said(self):
    out = _compute_payroll_baseline(
      shared_context={"people_capability": VET_PEOPLE, "operating_model": {}})
    self.assertAlmostEqual(out["baseline_payroll_year1"],
                           85000 + 82000 + 2 * 40000 + 2 * 32000, places=2)

  def test_nicks_example_three_project_architects(self):
    self.assertEqual(_person_row_headcount(
      {"full_name": "3 project architects", "role_title": "Project Architects",
       "annual_wage": 88000}), 3)

  def test_sumac_crew_total_wage_never_multiplies(self):
    """The fold-owned shape: '(4 people)' carries a GROUP-TOTAL wage."""
    row = {"full_name": "Crew (4)", "role_title": "Grounds crew (4 people)",
           "annual_wage": 136000.0}
    self.assertEqual(_person_row_headcount(row), 1)
    out = _compute_payroll_baseline(
      shared_context={"people_capability": {"people": [row]},
                      "operating_model": {}})
    self.assertAlmostEqual(out["baseline_payroll_year1"], 136000.0, places=2)

  def test_ordinals_and_singles_do_not_count(self):
    self.assertEqual(_person_row_headcount(
      {"full_name": "2nd Street Bakery Manager", "role_title": "Manager"}), 1)
    self.assertEqual(_person_row_headcount(
      {"full_name": "Jordan Lee", "role_title": "Owner"}), 1)

  def test_waged_role_count_counts_humans(self):
    """The rest-of-team trigger compares stated heads against HUMANS:
    the vet roster is 6 waged people in 4 rows - stated headcount 6 must
    NOT fire the question."""
    self.assertEqual(_waged_role_count(VET_PEOPLE), 6)

  def test_paren_count_on_a_non_fold_title(self):
    self.assertEqual(_person_row_headcount(
      {"full_name": "Front Desk Staff (2)", "role_title": "Front Desk",
       "annual_wage": 38000}), 2)


if __name__ == "__main__":
  unittest.main()
