"""Turn 18 of Nick's payroll directive (2026-09-10): the people-row
CANONICALIZATION fix, pinned on the verbatim rows of the item-8 failure.

Item 8 run 1 (draft a9db48dd, Bramblewood Physical Therapy, two named
co-owners 118,000 / 104,000) died at the INTAKE->POST_INTAKE boundary:
IntakeDraftContract, 56 errors, rows 4..11 of people_json.people in the
intent ROUTER's own shape ({name, title, years_experience,
education_credentials, annual_pay, wage_source: client_provided}). The
router's value_json is a string, so its row schema is unenforced;
_person_row_identity is None for a row with neither full_name nor
role_title, so _merge_people_rows could never match a raw row - two raw
patches appended and restored them, the finalize restored them beside the
model's canonical rows, the correction echoed them back: 2 -> 3 (bare Owner
row from the owner-pay door, which finds owners by role_title) -> 5 -> 9 ->
8 (OWNER_ROW_UNIQUENESS fold) -> 12. Same root, second consequence: the
client-stated wages sat in the unmatched raw rows, so the finalize showed
OEWS medians as the client's own wages.

THE FIX lives inside the ONE helper every people write funnels through
(_merge_people_rows: the people.people door and the four model-output
doors): every row - incoming AND standing - is canonicalized before
matching (_canonicalize_person_row), a row with no identity after that is
DROPPED WITH A RECEIPT, and a healed row echoing a name already on the
roster folds fill-only into it.

Red-proof at HEAD 79b7fb4: the replay ends with TWELVE rows and 56 contract
errors (test_replay_ends_with_four_rows / ..._passes_the_boundary), and the
helper is missing (AttributeError) for the rest.

The verbatim rows come from _api5050_server.err.log lines 103 / 107 / 117
(TURN_INTENT turns 45, 47, 51), extracted unchanged to
replay_gate/_payroll_directive_audit/r9_people_canonicalize/verbatim_turn_intent_rows.json.
"""
from __future__ import annotations

import copy
import io
import json
import logging
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python"),
          os.path.join(ROOT, "python", "client_intake_and_finmo")):
  if p not in sys.path:
    sys.path.insert(0, p)

from api_handlers import intake_consult as IC  # noqa: E402
from client_intake_and_finmo.post_intake_contracts.people_json_contract import (  # noqa: E402
  PeopleJsonContract, PersonContract,
)
from pydantic import ValidationError  # noqa: E402

EVID = os.path.join(ROOT, "replay_gate", "_payroll_directive_audit")
VERBATIM = os.path.join(EVID, "r9_people_canonicalize", "verbatim_turn_intent_rows.json")
STORED_PEOPLE = os.path.join(EVID, "r8_final_acceptance", "people_json_a9db48dd.json")


def _capture(fn):
  buf = io.StringIO()
  h = logging.StreamHandler(buf)
  h.setLevel(logging.INFO)
  lg = logging.getLogger("api_handlers.intake_consult")
  old_level = lg.level
  lg.addHandler(h)
  lg.setLevel(logging.INFO)
  try:
    out = fn()
  finally:
    lg.removeHandler(h)
    lg.setLevel(old_level)
  return out, buf.getvalue()


def _verbatim():
  with open(VERBATIM, encoding="utf-8") as fh:
    return json.load(fh)


def _stored_envelope():
  with open(STORED_PEOPLE, encoding="utf-8") as fh:
    return json.load(fh)


def _contract_errors(rows):
  """PeopleJsonContract on the stored a9db48dd envelope with `rows` as its
  people - the boundary's own people contract; 0 when it passes."""
  env = _stored_envelope()
  env["people"] = copy.deepcopy(rows)
  try:
    PeopleJsonContract.model_validate(env)
    return 0
  except ValidationError as e:
    return len(e.errors())


def _door(patch, ppl, fin):
  """The REAL people.people door: _apply_scoped_patch with the verbatim
  TURN_INTENT patch (people.people first, then owner_pay_monthly when the
  turn carried it - the log's own key order)."""
  _bf, _ops, _mk, next_people, next_fin, _ff = IC._apply_scoped_patch(
    copy.deepcopy(patch), business_facts={}, ops_json={}, market_json={},
    people_json=ppl, financials_json=fin, fulfillment_json={})
  return next_people, next_fin


def _replay():
  """The four people-stage patches of a9db48dd, in log order, through the
  REAL doors: the people.people door with the verbatim turn-45 patch (its
  owner_pay_monthly rides the same call, as it did live) -> the verbatim
  turn-47 patch -> the finalize merge (site people_finalize_done_adding,
  the model's four canonical rows without wages) -> THE RECALC
  (OWNER_ROW_UNIQUENESS) -> the verbatim turn-51 correction. Returns
  (roster, steps, fin) where steps is the list of (name, row_count)."""
  v = _verbatim()
  t45 = copy.deepcopy(v["turn45"]["patch"])
  t47 = copy.deepcopy(v["turn47"]["patch"])
  t51 = copy.deepcopy(v["turn51"]["patch"])
  steps = []
  ppl, fin = _door(t45, {}, {})
  steps.append(("turn45_people_and_owner_pay_doors", len(ppl["people"])))
  ppl, fin = _door(t47, ppl, fin)
  steps.append(("turn47_people_door", len(ppl["people"])))
  model_rows = []
  for r in t51["people.people"]:
    if "full_name" in r:
      m = dict(r)
      m["annual_wage"] = None
      m.pop("wage_source", None)
      model_rows.append(m)
  roster, _rep = IC._merge_model_roster(
    ppl, model_rows, site="people_finalize_done_adding")
  ppl = dict(ppl)
  ppl["people"] = roster
  steps.append(("finalize_done_adding", len(roster)))
  fin, _y1 = IC._sync_financials_consult_persistence_state(
    financials_json=fin, financials_year1_json={}, marketing_model_json={},
    people_json=ppl, ops_json={})
  steps.append(("recalc_owner_row_uniqueness", len(ppl["people"])))
  ppl, fin = _door(t51, ppl, fin)
  steps.append(("turn51_correction", len(ppl["people"])))
  return ppl["people"], steps, fin


class VerbatimReplay(unittest.TestCase):
  """The red-proof pair: at HEAD 79b7fb4 the replay ends with 12 rows and
  56 contract errors."""

  def test_replay_ends_with_four_rows(self):
    (roster, steps, _fin), _log = _capture(_replay)
    self.assertEqual(
      len(roster), 4,
      f"roster ended with {len(roster)} rows, steps={[(s[0], s[1]) for s in steps]}")
    self.assertEqual(
      [r.get("full_name") for r in roster],
      ["Dr. Ingrid Solvang", "Dr. Marcus Abernathy",
       "Staff Physical Therapists (2)", "Front-Desk Staff (2)"])

  def test_replay_passes_the_boundary(self):
    (roster, _steps, _fin), _log = _capture(_replay)
    n = _contract_errors(roster)
    self.assertEqual(n, 0, f"PeopleJsonContract errors={n} on {len(roster)} rows")
    for r in roster:
      PersonContract.model_validate(r)

  def test_replay_keeps_the_client_stated_owner_wages(self):
    (roster, _steps, fin), _log = _capture(_replay)
    by = {r["full_name"]: r for r in roster}
    ingrid = by["Dr. Ingrid Solvang"]
    marcus = by["Dr. Marcus Abernathy"]
    self.assertEqual(ingrid["annual_wage"], 118000.0)
    self.assertEqual(ingrid["wage_source"], "client_override")
    self.assertEqual(marcus["annual_wage"], 104000.0)
    self.assertEqual(marcus["wage_source"], "client_override")
    self.assertEqual(ingrid["experience_years"], "15")
    self.assertEqual(marcus["experience_years"], "12")
    self.assertEqual(by["Staff Physical Therapists (2)"]["annual_wage"], 78000.0)
    self.assertEqual(by["Front-Desk Staff (2)"]["annual_wage"], 38000.0)
    # the item-7 mirror on this roster: the SUM of both owners / 12
    self.assertEqual(fin.get("owner_compensation"), 18500.0)
    for r in roster:
      for raw_key in ("name", "title", "annual_pay", "years_experience",
                      "education_credentials"):
        self.assertNotIn(raw_key, r, f"{r.get('full_name')} still carries {raw_key}")

  def test_replay_steps_and_traces(self):
    """The path, step by step: no '?' label anywhere, no bare Owner row
    appended by the owner-pay door (it finds Ingrid by role_title now - the
    F3 first-owner landing, carried), the turn-47 echoes merge into their
    rows, the finalize keeps the stated wages against the model's nulls,
    the recalc folds the verbatim bare Owner row of turn 47, and the
    correction's four raw echoes dedupe."""
    (roster, steps, _fin), log = _capture(_replay)
    counts = {s[0]: s[1] for s in steps}
    self.assertEqual(counts["turn45_people_and_owner_pay_doors"], 2,
                     "the owner-pay door appended a bare Owner row")
    self.assertEqual(counts["turn47_people_door"], 3, "turn 47 carries the verbatim bare Owner row; it appends")
    self.assertEqual(counts["finalize_done_adding"], 5)
    self.assertEqual(counts["recalc_owner_row_uniqueness"], 4)
    self.assertEqual(counts["turn51_correction"], 4)
    pp = [l for l in log.splitlines() if "PEOPLE_PATCH" in l]
    self.assertEqual(len(pp), 4, log)
    # turn 45: two raw rows canonicalized at the door, nothing restored
    self.assertIn("PEOPLE_PATCH incoming=2 restored=[] field_kept=[] "
                  "aliased=['Dr. Ingrid Solvang', 'Dr. Marcus Abernathy']", pp[0])
    # turn 47: the two echoes merge into their rows, the bare Owner row appends
    self.assertTrue(pp[1].startswith("PEOPLE_PATCH incoming=3 restored=[]"), pp[1])
    self.assertIn("aliased=['Dr. Ingrid Solvang', 'Dr. Marcus Abernathy']", pp[1])
    # finalize: the model's null wages keep the stated ones; the bare Owner row is restored
    self.assertIn("PEOPLE_PATCH site=people_finalize_done_adding incoming=4 restored=['Owner'] "
                  "field_kept=['Dr. Ingrid Solvang.annual_wage', 'Dr. Marcus Abernathy.annual_wage']", pp[2])
    # the recalc folds the bare Owner row into a named owner
    self.assertIn("OWNER_ROW_UNIQUENESS merged=1 groups=2 named_owners_kept=['Dr. Ingrid Solvang', 'Dr. Marcus Abernathy']", log)
    # turn 51: four canonical rows merge, the four raw echoes dedupe, nothing restored
    self.assertTrue(pp[3].startswith("PEOPLE_PATCH incoming=8 restored=[]"), pp[3])
    self.assertIn("deduped=['Dr. Ingrid Solvang', 'Dr. Marcus Abernathy', "
                  "'Dr. Ingrid Solvang', 'Dr. Marcus Abernathy']", pp[3])
    self.assertNotIn("'?'", log)
    self.assertNotIn("dropped=", log)


class Canonicalizer(unittest.TestCase):
  def _fn(self):
    fn = getattr(IC, "_canonicalize_person_row", None)
    self.assertIsNotNone(fn, "the turn-18 canonicalizer is missing from intake_consult")
    return fn

  def test_raw_router_row_maps_onto_the_contract_keys(self):
    row, aliased = self._fn()({
      "name": "Dr. Ingrid Solvang", "title": "Clinical Director and Co-owner",
      "years_experience": 15,
      "education_credentials": "Doctor of Physical Therapy (DPT)",
      "annual_pay": 118000, "wage_source": "client_provided"})
    self.assertTrue(aliased)
    self.assertEqual(row, {
      "full_name": "Dr. Ingrid Solvang",
      "role_title": "Clinical Director and Co-owner",
      "experience_years": "15",
      "relevant_background": "Doctor of Physical Therapy (DPT)",
      "annual_wage": 118000.0, "wage_source": "client_override"})

  def test_legacy_row_with_name_beside_full_name_keeps_full_name(self):
    row, aliased = self._fn()({
      "full_name": "Ottoline Marchetti", "name": "O. Marchetti",
      "role_title": "Principal Architect", "title": "Architect",
      "annual_wage": 155000, "annual_pay": 1, "wage_source": "client_override"})
    self.assertTrue(aliased)
    self.assertEqual(row["full_name"], "Ottoline Marchetti")
    self.assertEqual(row["role_title"], "Principal Architect")
    self.assertEqual(row["annual_wage"], 155000)
    self.assertEqual(row["wage_source"], "client_override")
    for k in ("name", "title", "annual_pay"):
      self.assertNotIn(k, row)

  def test_empty_canonical_value_takes_the_alias(self):
    row, _ = self._fn()({"full_name": "", "name": "Priya Nair", "role_title": None,
                         "title": "Project Architect", "annual_wage": None,
                         "annual_pay": "98000"})
    self.assertEqual(row["full_name"], "Priya Nair")
    self.assertEqual(row["role_title"], "Project Architect")
    self.assertEqual(row["annual_wage"], 98000.0)
    self.assertEqual(row["wage_source"], "client_override")

  def test_null_alias_values_map_nothing(self):
    row, aliased = self._fn()({"name": "Dr. Marcus Abernathy", "title": "Managing Partner",
                               "years_experience": None, "education_credentials": None,
                               "annual_pay": 104000, "wage_source": "client_provided",
                               "annual_wage": None})
    self.assertTrue(aliased)
    self.assertNotIn("experience_years", row)
    self.assertNotIn("relevant_background", row)
    self.assertEqual(row["annual_wage"], 104000.0)

  def test_canonical_row_passes_through_untouched(self):
    src = {"full_name": "Rasheed Fennimore", "role_title": "Design Director and Co-Owner",
           "annual_wage": 142000, "wage_source": "client_override"}
    row, aliased = self._fn()(dict(src))
    self.assertFalse(aliased)
    self.assertEqual(row, src)

  def test_bare_owner_row_is_canonical_and_unnamed(self):
    """The Sumac F5 class (55 drafts + Halbrook): the owner-pay door's bare
    Owner row has identity ('title', 'owner') - canonical, never dropped."""
    src = {"role_title": "Owner", "annual_wage": 48000.0, "wage_source": "client_override"}
    row, aliased = self._fn()(dict(src))
    self.assertFalse(aliased)
    self.assertEqual(row, src)
    self.assertEqual(IC._person_row_identity(row), ("title", "owner"))


SUMAC = {"people": [
  {"full_name": "Delia Rennick", "role_title": "Owner / Crew Lead",
   "annual_wage": 48000, "wage_source": "client_override"},
  {"full_name": "Marcus Bell", "role_title": "Crew Member",
   "annual_wage": 38000, "wage_source": "client_override"},
]}

MARCHETTI = {"people": [
  {"full_name": "Ottoline Marchetti", "role_title": "Principal Architect and Co-Owner",
   "annual_wage": 155000, "wage_source": "client_override",
   "relevant_background": "Twenty years in practice."},
  {"full_name": "Rasheed Fennimore", "role_title": "Design Director and Co-Owner",
   "annual_wage": 142000, "wage_source": "client_override"},
]}


class MergeDiscipline(unittest.TestCase):
  def test_identity_less_row_is_dropped_and_reported(self):
    (merged, rep), log = _capture(lambda: IC._merge_people_rows(
      copy.deepcopy(SUMAC["people"]),
      [{"years_experience": 3, "annual_pay": 50000, "wage_source": "client_provided"}]))
    self.assertEqual([r["full_name"] for r in merged], ["Delia Rennick", "Marcus Bell"])
    self.assertEqual(rep["dropped"], [["annual_wage", "experience_years", "wage_source"]])
    self.assertEqual(rep["restored"], ["Delia Rennick", "Marcus Bell"])

  def test_bare_owner_row_incoming_appends_and_standing_restores(self):
    bare = {"role_title": "Owner", "annual_wage": 48000.0, "wage_source": "client_override"}
    merged, rep = IC._merge_people_rows(copy.deepcopy(SUMAC["people"]), [dict(bare)])
    self.assertEqual(len(merged), 3)
    self.assertEqual(merged[0], bare)
    self.assertEqual(rep["dropped"], [])
    self.assertEqual(rep["aliased"], [])
    merged2, rep2 = IC._merge_people_rows(
      copy.deepcopy(SUMAC["people"]) + [dict(bare)], [])
    self.assertEqual(len(merged2), 3)
    self.assertEqual(rep2["restored"], ["Delia Rennick", "Marcus Bell", "Owner"])
    self.assertEqual(rep2["dropped"], [])

  def test_stored_raw_rows_heal_on_the_next_write(self):
    """The twelve rows stored on a9db48dd (people_json_a9db48dd.json) meet
    an empty people write: the eight raw copies canonicalize and fold into
    the four named rows - four rows, the contract passes."""
    stored = _stored_envelope()["people"]
    self.assertEqual(len(stored), 12)
    (merged, rep), log = _capture(lambda: IC._merge_people_rows(copy.deepcopy(stored), []))
    self.assertEqual([r["full_name"] for r in merged],
                     ["Dr. Ingrid Solvang", "Dr. Marcus Abernathy",
                      "Staff Physical Therapists (2)", "Front-Desk Staff (2)"])
    self.assertEqual(len(rep["healed"]), 8)
    self.assertEqual(rep["dropped"], [])
    self.assertEqual(_contract_errors(merged), 0)
    by = {r["full_name"]: r for r in merged}
    # fill-only: the finalize's richer background stands, the raw echo fills nothing over it
    self.assertEqual(by["Dr. Ingrid Solvang"]["annual_wage"], 118000.0)
    self.assertTrue(by["Dr. Ingrid Solvang"]["relevant_background"].startswith("Doctor of Physical Therapy"))
    self.assertEqual(by["Dr. Ingrid Solvang"]["primary_responsibilities"],
                     stored[0]["primary_responsibilities"])

  def test_canonical_duplicates_are_not_folded(self):
    """Rows canonical to begin with follow today's path byte for byte: a
    model output naming the same person twice still appends the second."""
    rows = [dict(MARCHETTI["people"][0]), dict(MARCHETTI["people"][0])]
    merged, rep = IC._merge_people_rows([], rows)
    self.assertEqual(len(merged), 2)
    self.assertEqual(rep["deduped"], [])
    self.assertEqual(rep["healed"], [])

  def test_healed_echo_of_a_standing_person_merges_not_appends(self):
    merged, rep = IC._merge_people_rows(
      copy.deepcopy(MARCHETTI["people"]),
      [{"name": "Rasheed Fennimore", "title": "Design Director and Co-Owner",
        "annual_pay": 142000, "wage_source": "client_provided",
        "education_credentials": "M.Arch"}])
    self.assertEqual([r["full_name"] for r in merged],
                     ["Rasheed Fennimore", "Ottoline Marchetti"])
    self.assertEqual(merged[0]["annual_wage"], 142000.0)
    self.assertEqual(merged[0]["wage_source"], "client_override")
    self.assertEqual(merged[0]["relevant_background"], "M.Arch")
    self.assertEqual(rep["merged"], ["Rasheed Fennimore"])
    self.assertEqual(rep["restored"], ["Ottoline Marchetti"])

  def test_trace_line_for_canonical_rows_is_the_item5_shape(self):
    (merged, rep), log = _capture(lambda: IC._merge_model_roster(
      copy.deepcopy(MARCHETTI), [dict(MARCHETTI["people"][0])], site="collection_extractor"))
    lines = [l for l in log.splitlines() if "PEOPLE_PATCH" in l]
    self.assertEqual(len(lines), 1)
    self.assertTrue(lines[0].endswith("restored=['Rasheed Fennimore'] field_kept=[]"), lines[0])


class ModelOutputDoors(unittest.TestCase):
  """The four model-output doors share the helper: one raw-row case each
  through _merge_model_roster - the raw Ottoline echo merges into her
  standing row, Rasheed restored, the trace names the site and the alias."""
  SITES = ("collection_extractor", "people_finalize_done_adding",
           "people_finalize_review", "people_finalize_ready")

  def _raw_case(self, site):
    (merged, rep), log = _capture(lambda: IC._merge_model_roster(
      copy.deepcopy(MARCHETTI),
      [{"name": "Ottoline Marchetti", "title": "Principal Architect and Co-Owner",
        "annual_pay": 155000, "years_experience": 20, "education_credentials": None}],
      site=site))
    self.assertEqual([r["full_name"] for r in merged],
                     ["Ottoline Marchetti", "Rasheed Fennimore"])
    self.assertEqual(merged[0]["annual_wage"], 155000.0)
    self.assertEqual(merged[0]["wage_source"], "client_override")
    self.assertEqual(merged[0]["relevant_background"], "Twenty years in practice.")
    self.assertEqual(merged[0]["experience_years"], "20")
    self.assertEqual(merged[1]["annual_wage"], 142000)
    self.assertEqual(rep["site"], site)
    self.assertEqual(rep["aliased"], ["Ottoline Marchetti"])
    line = [l for l in log.splitlines() if "PEOPLE_PATCH" in l]
    self.assertEqual(len(line), 1, log)
    self.assertIn(f"site={site}", line[0])
    self.assertIn("aliased=['Ottoline Marchetti']", line[0])

  def test_s1_collection_extractor_raw_row(self):
    self._raw_case(self.SITES[0])

  def test_s2_people_finalize_done_adding_raw_row(self):
    self._raw_case(self.SITES[1])

  def test_s3_people_finalize_review_raw_row(self):
    self._raw_case(self.SITES[2])

  def test_s4_people_finalize_ready_raw_row(self):
    self._raw_case(self.SITES[3])

  def test_model_output_identity_less_row_is_dropped_with_trace(self):
    (merged, rep), log = _capture(lambda: IC._merge_model_roster(
      copy.deepcopy(MARCHETTI), [{"annual_pay": 1, "years_experience": 2}],
      site="people_finalize_review"))
    self.assertEqual(len(merged), 2)
    self.assertEqual(rep["dropped"], [["annual_wage", "experience_years", "wage_source"]])
    self.assertIn("dropped=[['annual_wage', 'experience_years', 'wage_source']]", log)


class OewsAfterFinalizeMerge(unittest.TestCase):
  """Triage item 2 (rides in this fix): after the finalize merge keeps the
  client-stated wage against the model's null, the OEWS pass that follows
  at the review / ready doors leaves a client_override wage untouched."""

  def test_oews_pass_leaves_client_override_wages(self):
    from client_intake_and_finmo import people_roles as PR
    (roster, _steps, _fin), _log = _capture(_replay)
    with mock.patch.object(PR, "_fetch_oews_rows_with_fallback", return_value=[]):
      enriched = PR.apply_oews_wages_to_people(
        None, people=copy.deepcopy(roster), business_type="physical therapy",
        business_stage="existing", address_state="NC", business_naics_6="621340")
    by = {r["full_name"]: r for r in enriched}
    self.assertEqual(by["Dr. Ingrid Solvang"]["annual_wage"], 118000.0)
    self.assertEqual(by["Dr. Ingrid Solvang"]["wage_source"], "client_override")
    self.assertEqual(by["Dr. Marcus Abernathy"]["annual_wage"], 104000.0)
    self.assertEqual(by["Dr. Marcus Abernathy"]["wage_source"], "client_override")
    self.assertEqual(by["Staff Physical Therapists (2)"]["annual_wage"], 78000.0)
    self.assertEqual(by["Front-Desk Staff (2)"]["annual_wage"], 38000.0)


class DropReceipt(unittest.TestCase):
  """Never a silent drop: the people.people door leaves the receipt on the
  derived-patch rail, the edit path turns it into the say-do note, and the
  stage people door speaks it in its own ack."""

  RAW_NO_IDENTITY = [{"years_experience": 3, "annual_pay": 50000, "wage_source": "client_provided"}]

  def test_people_door_leaves_the_receipt(self):
    (_bf, _ops, _mk, ppl, fin, _ff), log = _capture(lambda: IC._apply_scoped_patch(
      {"people.people": copy.deepcopy(self.RAW_NO_IDENTITY)},
      business_facts={}, ops_json={}, market_json={},
      people_json=copy.deepcopy(SUMAC), financials_json={}, fulfillment_json={}))
    self.assertEqual([r["full_name"] for r in ppl["people"]], ["Delia Rennick", "Marcus Bell"])
    receipt = fin.get("_derived_patch_receipt")
    self.assertEqual(receipt, [{
      "field": "people.people", "value": [["annual_wage", "experience_years", "wage_source"]],
      "disposition": "people_row_dropped"}])
    self.assertIn("dropped=[['annual_wage', 'experience_years', 'wage_source']]", log)

  def test_people_door_leaves_no_receipt_for_named_rows(self):
    _bf, _ops, _mk, ppl, fin, _ff = IC._apply_scoped_patch(
      {"people.people": [{"name": "Priya Nair", "title": "Project Architect", "annual_pay": 98000}]},
      business_facts={}, ops_json={}, market_json={},
      people_json=copy.deepcopy(SUMAC), financials_json={}, fulfillment_json={})
    self.assertEqual([r["full_name"] for r in ppl["people"]],
                     ["Priya Nair", "Delia Rennick", "Marcus Bell"])
    self.assertNotIn("_derived_patch_receipt", fin)

  def test_unapplied_note_speaks_the_dropped_person(self):
    note = IC._unapplied_fields_note(["people"])
    self.assertEqual(note, IC._PEOPLE_ROW_DROPPED_NOTE)
    self.assertNotIn("we'll get to that", note)
    both = IC._unapplied_fields_note(["people", "monthly_rent_expense"])
    self.assertIn(IC._PEOPLE_ROW_DROPPED_NOTE, both)
    self.assertIn("recorded rent yet", both)

  def test_stage_people_door_ack_carries_the_note(self):
    patch, fin, ctx, ack = IC._apply_stage_people_door_keys(
      patch={"people.people": copy.deepcopy(self.RAW_NO_IDENTITY)},
      stage_shared_context={"people_capability": copy.deepcopy(SUMAC)},
      next_financials={}, conn=None, intake_context={"draft_id": "test-turn18"})
    self.assertEqual(ack, IC._PEOPLE_ROW_DROPPED_NOTE)
    self.assertNotIn("_derived_patch_receipt", fin)
    self.assertEqual([r["full_name"] for r in ctx["people_capability"]["people"]],
                     ["Delia Rennick", "Marcus Bell"])

  def test_stage_people_door_ack_is_silent_without_a_drop(self):
    patch, fin, ctx, ack = IC._apply_stage_people_door_keys(
      patch={"people.people": [{"name": "Priya Nair", "title": "Project Architect", "annual_pay": 98000}]},
      stage_shared_context={"people_capability": copy.deepcopy(SUMAC)},
      next_financials={}, conn=None, intake_context={"draft_id": "test-turn18"})
    self.assertEqual(ack, "")
    self.assertEqual(len(ctx["people_capability"]["people"]), 3)


if __name__ == "__main__":
  unittest.main()
