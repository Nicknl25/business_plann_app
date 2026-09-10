"""The key-person occupation matcher, fixed as a CLASS (Nick 2026-09-10).

The census that sized it: of 27 key-person Q1 rows on the last ten
drafts, 7 carried no SOC and at least 9 a plainly wrong one. Three
universal doors, none profession-specific:

1. Bare substring preference triggers: 'coo' inside 'coordinate' (and
   'hr' inside 'three') stamped a Lead hygienist as a General and
   Operations Manager.
2. Notes-derived management preferences ran BEFORE the role title could
   be matched, so prose duties outranked the person's own title.
3. No singular/plural normalization + a flat >=2 token threshold left
   'Co-owner and practicing dentist' unmatchable against 'Dentists,
   General' - and let '...Physical Therapist Assistants and Aides' (six
   tokens) beat 'Physical Therapists' (two) for a licensed PT.

The fix: word-boundary triggers; role-title-first resolution order;
normalized tokens; rarity-weighted scoring (the catalog itself says
which tokens are distinctive) with candidate-coverage tiebreak. No
profession word list anywhere.
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

from client_intake_and_finmo.post_intake_headcount.schedule import (  # noqa: E402
  _preference_titles_from_text,
  _resolve_key_person_oews_wage,
)

TITLES = [
  ("Dentists, General", "29-1021"),
  ("Dentists, All Other Specialists", "29-1029"),
  ("Dental Hygienists", "29-1292"),
  ("Dental Assistants", "31-9091"),
  ("Physical Therapists", "29-1123"),
  ("Occupational Therapy and Physical Therapist Assistants and Aides",
   "31-2000"),
  ("General and Operations Managers", "11-1021"),
  ("Financial Managers", "11-3031"),
  ("Human Resources Managers", "11-3121"),
  ("Bakers", "51-3011"),
]
OEWS_ROWS = [{"occ_title": t, "occ_code": c, "a_median": 60000,
              "tot_emp": 1000} for t, c in TITLES]
CATALOG = {"title_candidates": [{"occ_title": t, "occ_code": c}
                                for t, c in TITLES]}


def _match(role, notes=""):
  return _resolve_key_person_oews_wage(
    {"role_title": role, "primary_responsibilities": notes},
    oews_rows=OEWS_ROWS, catalog=CATALOG, min_wage=25000)


class OccupationMatcherTests(unittest.TestCase):
  def test_practicing_dentist_matches_dentists(self):
    """The Bright Smiles co-owners: singular 'dentist' must reach the
    plural catalog title."""
    r = _match("Co-owner and practicing dentist",
               "Provide general and family dental care, oversee clinical "
               "quality and treatment planning.")
    self.assertIsNotNone(r)
    self.assertTrue(r["matched_occ_code"].startswith("29-102"),
                    r["matched_occ_title"])

  def test_lead_hygienist_is_not_a_manager(self):
    """'coo' inside 'coordinate' must never fire the COO preference,
    and the role title must be tried before any notes inference."""
    r = _match("Lead hygienist",
               "Provide dental hygiene care, support preventive dentistry, "
               "and help coordinate clinical flow as the lead hygienist.")
    self.assertIsNotNone(r)
    self.assertEqual(r["matched_occ_code"], "29-1292")

  def test_physical_therapist_beats_the_aides_group(self):
    """Coverage tiebreak: the exact two-token occupation wins over the
    six-token assistants-and-aides group."""
    r = _match("Staff Physical Therapist")
    self.assertIsNotNone(r)
    self.assertEqual(r["matched_occ_code"], "29-1123")

  def test_hr_does_not_fire_inside_three(self):
    """'hr' in 'three' stamped Human Resources Managers at HEAD."""
    r = _match("Baker", "Baking lead with three years at the shop.")
    self.assertIsNotNone(r)
    self.assertEqual(r["matched_occ_code"], "51-3011")

  def test_cfo_preference_still_works_from_the_role_title(self):
    r = _match("CFO")
    self.assertIsNotNone(r)
    self.assertEqual(r["matched_occ_code"], "11-3031")

  def test_notes_preference_survives_for_titleless_roles(self):
    """A bare co-owner whose duties are financial still lands Financial
    Managers - notes preferences are a fallback, not deleted."""
    r = _match("Co-owner", "Oversees all finance and bookkeeping.")
    self.assertIsNotNone(r)
    self.assertEqual(r["matched_occ_code"], "11-3031")

  def test_role_title_outranks_notes_preferences(self):
    r = _match("Lead hygienist", "Also oversees daily operations.")
    self.assertIsNotNone(r)
    self.assertEqual(r["matched_occ_code"], "29-1292")

  def test_unplaceable_role_stays_unstamped(self):
    """Better no chart than a wrong one: nothing here may invent a
    match for a role the catalog cannot place."""
    self.assertIsNone(_match("Mascot", "Wears the tooth costume."))

  def test_clinical_director_is_not_a_psychologist(self):
    """Census catch: a lone shared ADJECTIVE ('clinical') must not carry
    a match - the candidate's own head noun has to be claimed."""
    rows = OEWS_ROWS + [{"occ_title": "Clinical and Counseling "
                         "Psychologists", "occ_code": "19-3033",
                         "a_median": 90000, "tot_emp": 500}]
    cat = {"title_candidates": [{"occ_title": r["occ_title"],
                                 "occ_code": r["occ_code"]} for r in rows]}
    r = _resolve_key_person_oews_wage(
      {"role_title": "Clinical Director and Co-owner"},
      oews_rows=rows, catalog=cat, min_wage=25000)
    if r is not None:
      self.assertNotEqual(r["matched_occ_code"], "19-3033")

  def test_patient_coordinator_is_not_instructional(self):
    """Census catch: a generic organizational noun ('coordinator')
    shared alone proves nothing."""
    rows = OEWS_ROWS + [{"occ_title": "Instructional Coordinators",
                         "occ_code": "25-9031", "a_median": 70000,
                         "tot_emp": 500}]
    cat = {"title_candidates": [{"occ_title": r["occ_title"],
                                 "occ_code": r["occ_code"]} for r in rows]}
    r = _resolve_key_person_oews_wage(
      {"role_title": "Front Desk / Patient Coordinator"},
      oews_rows=rows, catalog=cat, min_wage=25000)
    self.assertIsNone(r)

  def test_aides_group_is_structurally_unreachable(self):
    """The aides group's head noun is 'aides' - a Physical Therapist
    never claims it, so the group is excluded outright, not merely
    out-tiebroken."""
    rows = [r for r in OEWS_ROWS if r["occ_code"] != "29-1123"]
    cat = {"title_candidates": [{"occ_title": r["occ_title"],
                                 "occ_code": r["occ_code"]} for r in rows]}
    r = _resolve_key_person_oews_wage(
      {"role_title": "Staff Physical Therapist"},
      oews_rows=rows, catalog=cat, min_wage=25000)
    self.assertIsNone(r)

  def test_preference_trigger_boundaries(self):
    self.assertEqual(_preference_titles_from_text("help coordinate flow"), [])
    self.assertEqual(_preference_titles_from_text("three years"), [])
    self.assertIn("General and Operations Managers",
                  _preference_titles_from_text("COO of the practice"))
    self.assertIn("Human Resources Managers",
                  _preference_titles_from_text("HR lead"))


if __name__ == "__main__":
  unittest.main()
