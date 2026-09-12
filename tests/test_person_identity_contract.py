"""PERSON IDENTITY AND WAGE PROVENANCE (Nick 2026-09-11), pinned.

"A person's identity is a free-text string a model picks per turn, and
payroll sums rows keyed by that string. Every fix so far has been a guard on
top of that, and we've been back here four times. Assign a stable person id
at capture... Then a renamed row cannot become a second human and payroll
cannot double-count. That's the contract change. Do that, not another door."

THE THREE FACES, one mechanism, both plans shipped to a client:

  Halvorsen Tide 836c2ca2 - "Bartholomew" and "Bartholomew Ndiaye" stored as
  two humans at 94,000 each. Stored payroll 856,000; the client said 762,000
  in his own words and the intake completed anyway.

  Pelletier Orthotics 8bb68a68 - a nameless {role_title: "Owner"} row
  carrying the owner's whole salary a second time (15,500 x 12 = 186,000
  exactly), because the owner-pay door recognises an owner only by title
  regex and "Certified Prosthetist-Orthotist" matches none of
  owner/principal/founder/managing/partner. Stored payroll 1,139,000 against
  a true 953,000.

  Pelletier again - his stated 186,000 replaced by 102,870, the OEWS 75th
  percentile for occupation 29-2091, because his row carried wage_source
  "client_reported": a token NO python in this repo writes, invented by the
  model that turn, and absent from the three-spelling whitelist that
  protects a stated wage.

WHAT THESE PINS PROTECT. Every assertion below is a case that actually
occurred or a case where merging WOULD DELETE A HUMAN. The refusals matter
as much as the folds: the Rasheed Fennimore class (a second named partner
erased by a too-eager merge, his 142,000 gone from the delivered payroll) is
the failure mode on the other side of this line.
"""
from __future__ import annotations

import copy
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

import api_handlers.intake_consult as IC  # noqa: E402
from client_intake_and_finmo.person_identity import (  # noqa: E402
  is_client_stated, names_are_same_human, normalize_wage_source,
)


def _payroll(people_json):
  b = IC._compute_payroll_baseline(shared_context={
    "people_capability": people_json, "operating_model": {}})
  return float(b.get("baseline_payroll_year1") or 0.0)


# The two rosters exactly as they sat in the database when the plans shipped.
HALVORSEN = {
  "people": [
    {"full_name": "Annika Halvorsen", "role_title": "Owner and Farm Manager",
     "annual_wage": 128000.0, "wage_source": "client_override"},
    {"full_name": "Bartholomew Ndiaye", "role_title": "Harvest Lead",
     "annual_wage": 94000.0, "wage_source": "client_override"},
    {"full_name": "Bartholomew", "role_title": "Harvest Lead",
     "annual_wage": 94000.0, "wage_source": "client_override"},
  ],
  "rest_of_team_payroll_year1": 540000,
}

PELLETIER = {
  "people": [
    {"full_name": "Dr. Tobias Pelletier",
     "role_title": "Certified Prosthetist-Orthotist",
     "annual_wage": 186000.0, "wage_source": "client_override"},
    {"full_name": "Nadira Oyelaran",
     "role_title": "Clinical Lead, Certified Prosthetist-Orthotist",
     "annual_wage": 152000.0, "wage_source": "client_override"},
    {"role_title": "Owner", "annual_wage": 186000.0,
     "wage_source": "client_override"},
  ],
  "rest_of_team_payroll_year1": 615000,
}


class TheDuplicateHuman(unittest.TestCase):
  def test_a_surname_supplied_later_is_the_same_person(self):
    """Halvorsen: the finalize returned "Bartholomew Ndiaye" while
    "Bartholomew" stood on file. Two identity strings, one man, 94,000
    billed twice on a delivered plan."""
    merged, rep = IC._merge_people_rows(
      [{"full_name": "Bartholomew", "role_title": "Harvest Lead",
        "annual_wage": 94000.0}],
      [{"full_name": "Bartholomew Ndiaye", "role_title": "Harvest Lead",
        "annual_wage": 94000.0}])
    self.assertEqual(len(merged), 1)
    self.assertEqual(merged[0]["full_name"], "Bartholomew Ndiaye")
    self.assertTrue(rep["name_resolved"])

  def test_a_duplicate_ALREADY_ON_FILE_heals(self):
    """The stored Halvorsen roster. _match only compares INCOMING rows
    against standing ones, so without the standing-row pass this roster
    stayed split through every later turn - which is what happened."""
    work = copy.deepcopy(HALVORSEN)
    self.assertEqual(_payroll(work), 856000.0)
    merged, rep = IC._merge_people_rows(work["people"], [])
    work["people"] = merged
    self.assertEqual(len(merged), 2)
    self.assertEqual(_payroll(work), 762000.0)  # what the client said
    self.assertTrue(rep["name_resolved"])

  def test_the_fuller_name_survives_and_nothing_is_lost(self):
    merged, _ = IC._merge_people_rows(
      [{"full_name": "Bartholomew", "role_title": "Harvest Lead",
        "annual_wage": 94000.0, "relevant_background": "twelve years"}],
      [{"full_name": "Bartholomew Ndiaye", "role_title": "Harvest Lead"}])
    self.assertEqual(merged[0]["full_name"], "Bartholomew Ndiaye")
    self.assertEqual(merged[0]["annual_wage"], 94000.0)
    self.assertEqual(merged[0]["relevant_background"], "twelve years")

  def test_a_title_prefix_is_the_same_person(self):
    merged, _ = IC._merge_people_rows(
      [{"full_name": "Tobias Pelletier", "annual_wage": 186000.0}],
      [{"full_name": "Dr. Tobias Pelletier", "role_title": "CPO"}])
    self.assertEqual(len(merged), 1)


class MergingMustRefuseToGuess(unittest.TestCase):
  """The other side of the line. A wrong fold DELETES A HUMAN and their
  wage vanishes from the delivered payroll while the roster looks healthy
  (Rasheed Fennimore, Rajan Mehta)."""

  def test_an_ambiguous_first_name_folds_nothing(self):
    rows = [
      {"full_name": "Bartholomew", "annual_wage": 94000.0},
      {"full_name": "Bartholomew Ndiaye", "annual_wage": 94000.0},
      {"full_name": "Bartholomew Smith", "annual_wage": 51000.0},
    ]
    merged, rep = IC._merge_people_rows(copy.deepcopy(rows), [])
    self.assertEqual(len(merged), 3)
    self.assertEqual(rep["name_resolved"], [])

  def test_two_co_owners_are_two_people(self):
    rows = [
      {"full_name": "Ottoline Marchetti",
       "role_title": "Principal Architect and Co-Owner", "annual_wage": 155000},
      {"full_name": "Rasheed Fennimore",
       "role_title": "Design Director and Co-Owner", "annual_wage": 142000},
    ]
    merged, _ = IC._merge_people_rows(copy.deepcopy(rows), [])
    self.assertEqual([r["full_name"] for r in merged],
                     ["Ottoline Marchetti", "Rasheed Fennimore"])

  def test_different_people_sharing_a_forename_never_fold(self):
    merged, _ = IC._merge_people_rows(
      [{"full_name": "John Smith", "annual_wage": 50000}],
      [{"full_name": "John Jones", "annual_wage": 60000}])
    self.assertEqual(len(merged), 2)


class ThePhantomOwnerRow(unittest.TestCase):
  def test_the_door_lands_on_the_named_owner_the_regex_cannot_see(self):
    """Pelletier. The client stated 186,000 a year AND 15,500 a month about
    himself; 15,500 x 12 = 186,000 exactly. That is one human stating one
    figure twice, not two salaries."""
    ppl = {"people": [
      {"full_name": "Dr. Tobias Pelletier",
       "role_title": "Certified Prosthetist-Orthotist",
       "annual_wage": 186000.0, "wage_source": "client_override"},
      {"full_name": "Nadira Oyelaran", "role_title": "Clinical Lead",
       "annual_wage": 152000.0, "wage_source": "client_override"},
    ]}
    fin = IC._apply_owner_pay_statement(
      monthly=15500.0, people_json=ppl, financials_json={}, ops_json={},
      user_message="")
    self.assertEqual(len(ppl["people"]), 2)
    self.assertTrue(ppl["people"][0].get("is_owner"))
    self.assertEqual(float(fin["current_payroll"]), 338000.0)

  def test_the_stored_pelletier_roster_reconciles_to_what_he_said(self):
    """The phantom already on file: the recalc's owner set now sees a lone
    UNNAMED owner row and one named person on the identical stated wage."""
    ppl = copy.deepcopy(PELLETIER)
    self.assertEqual(_payroll(ppl), 1139000.0)
    fin, _ = IC._sync_financials_consult_persistence_state(
      financials_json={}, financials_year1_json={}, marketing_model_json={},
      people_json=ppl, ops_json={})
    self.assertEqual(float(fin["current_payroll"]), 953000.0)

  def test_a_roster_with_no_named_person_still_gets_its_bare_owner_row(self):
    """The Sumac F5 class, 55 drafts + Halbrook: when there is no human to
    land on, the bare row IS the owner's pay and must still be created."""
    ppl = {"people": []}
    IC._apply_owner_pay_statement(
      monthly=4000.0, people_json=ppl, financials_json={}, ops_json={},
      user_message="")
    self.assertEqual(len(ppl["people"]), 1)
    self.assertEqual(ppl["people"][0]["role_title"], "Owner")

  def test_two_people_on_one_salary_are_not_one_owner(self):
    """A coincidence is not an identity. Exactly one candidate, or the
    bare row stands."""
    ppl = {"people": [
      {"full_name": "A Person", "role_title": "Tech", "annual_wage": 186000.0},
      {"full_name": "B Person", "role_title": "Tech", "annual_wage": 186000.0},
      {"role_title": "Owner", "annual_wage": 186000.0,
       "wage_source": "client_override"},
    ]}
    fin, _ = IC._sync_financials_consult_persistence_state(
      financials_json={}, financials_year1_json={}, marketing_model_json={},
      people_json=ppl, ops_json={})
    self.assertEqual(len(ppl["people"]), 3)
    self.assertEqual(float(fin["current_payroll"]), 558000.0)


class WageProvenanceIsAnEnum(unittest.TestCase):
  def test_the_invented_token_is_recognised_as_the_clients_word(self):
    """"client_reported" is what the router emitted. Nothing wrote it,
    nothing rejected it, and a stated wage was replaced by a percentile."""
    self.assertEqual(normalize_wage_source("client_reported"),
                     ("client_override", True))
    self.assertTrue(is_client_stated("client_reported"))

  def test_a_benchmark_is_never_mistaken_for_a_statement(self):
    for tok in ("oews_pct75", "oews_median", "gpt_estimate"):
      self.assertFalse(is_client_stated(tok), tok)
    self.assertFalse(is_client_stated("unknown"))

  def test_unknown_means_nobody_stated_it_not_the_client_did(self):
    """The consultant is INSTRUCTED to emit "unknown" (prompt :223). It
    must stay distinguishable from a client statement or an unstated wage
    would be protected from the benchmark that is supposed to fill it."""
    self.assertEqual(normalize_wage_source("unknown")[0], "unknown")
    self.assertEqual(normalize_wage_source("")[0], "unknown")

  def test_an_unrecognised_token_protects_the_clients_number(self):
    """The two failure directions are not symmetric: guessing "estimate"
    ships a benchmark over a fact; guessing "stated" only declines to
    upgrade an estimate."""
    token, recognised = normalize_wage_source("some_new_spelling_v4")
    self.assertEqual(token, "client_override")
    self.assertFalse(recognised)

  def test_a_token_that_looks_like_a_benchmark_is_read_as_one(self):
    self.assertEqual(normalize_wage_source("bls_median_2023")[0],
                     "gpt_estimate")


class IdentityIsStampedAtCapture(unittest.TestCase):
  def test_every_row_entering_the_roster_gets_one_id(self):
    merged, rep = IC._merge_people_rows(
      [], [{"full_name": "Annika Halvorsen", "role_title": "Owner"}])
    self.assertTrue(merged[0].get("person_id"))
    self.assertEqual(rep["identified"], ["Annika Halvorsen"])

  def test_the_id_survives_a_rename(self):
    first, _ = IC._merge_people_rows(
      [], [{"full_name": "Annika Halvorsen", "role_title": "Owner"}])
    pid = first[0]["person_id"]
    again, _ = IC._merge_people_rows(
      copy.deepcopy(first),
      [{"full_name": "Annika Halvorsen", "role_title": "Farm Manager"}])
    self.assertEqual(len(again), 1)
    self.assertEqual(again[0]["person_id"], pid)
    self.assertEqual(again[0]["role_title"], "Farm Manager")

  def test_ids_are_unique_per_human(self):
    merged, _ = IC._merge_people_rows([], copy.deepcopy(HALVORSEN["people"]))
    ids = [r["person_id"] for r in merged]
    self.assertEqual(len(set(ids)), len(ids))

  def test_an_id_is_never_reminted_over_an_existing_one(self):
    rows = [{"full_name": "Annika Halvorsen", "person_id": "p_fixed0000001"}]
    merged, rep = IC._merge_people_rows(copy.deepcopy(rows), [])
    self.assertEqual(merged[0]["person_id"], "p_fixed0000001")
    self.assertEqual(rep["identified"], [])


class NamesAreSameHumanUnit(unittest.TestCase):
  def test_subset_both_directions(self):
    self.assertTrue(names_are_same_human("Bartholomew", "Bartholomew Ndiaye"))
    self.assertTrue(names_are_same_human("Bartholomew Ndiaye", "Bartholomew"))

  def test_punctuation_and_case_do_not_matter(self):
    self.assertTrue(names_are_same_human("dr. tobias pelletier",
                                         "Dr Tobias Pelletier"))

  def test_disjoint_names_are_two_people(self):
    self.assertFalse(names_are_same_human("John Smith", "John Jones"))
    self.assertFalse(names_are_same_human("", "Anyone"))


if __name__ == "__main__":
  unittest.main()
