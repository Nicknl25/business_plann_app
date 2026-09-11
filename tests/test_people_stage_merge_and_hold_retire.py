"""Item 5 of Nick's payroll rulings (2026-09-09): R1 people-stage merge
discipline + the owner-wage-hold retire rider. Pinned offline.

R1 - "the ops door taught us a guard on one write path doesn't cover the
other." Every people-stage roster write built from a MODEL OUTPUT goes
through the same guard as the people.people door (_merge_people_rows):

  S1 collection_extractor        extract_people_collection_progress ->
                                 next_people_json["people"]
  S2 people_finalize_done_adding people_capability_finalize (done-adding
                                 detector) -> _build_people_review_payload
  S3 people_finalize_review      people_capability_finalize (review_ready)
                                 -> OEWS enrichment -> append_messages
  S4 people_finalize_ready       people_capability_finalize (finalize_ready
                                 close-out) -> OEWS enrichment -> people_json

Per site: a BEHAVIOR pin (two-person stored roster meets a one-person model
output -> both survive, the client-stated wage rides, the PEOPLE_PATCH
trace names the site) and a SOURCE-STRUCTURAL pin (the model call at the
site is followed by _merge_model_roster, with that site name, before the
next append_messages) - the sites live inside the 5,000-line handler and
cannot be driven offline, so the structure is what proves the call is
wired. Red on the pre-fix baseline: the helper is absent, so the behavior
pins fail on "helper missing" and the structural pins fail on "no merge
call after the site".

Rider - THE RECALC (_sync_financials_consult_persistence_state) retires a
STALE _owner_wage_conflict_hold: when the roster carries two or more
distinct NAMED owner-titled humans and this pass raised no hold, the
hold's premise (two figures for ONE owner) is contradicted by the roster
and it retires. A hold on a one-owner roster (the Sumac shape) is GENUINE
and stays for the gate. Nothing else in financials moves.

Rider 5b (mini's turn-10 finding, the two-pass hole): roster shape alone
cannot tell a stale hold from a genuine one on a two-owner business - a
genuine same-human conflict raised on pass 1 was retired by the NEXT
turn's preamble recalc (pass 2) before section.py's popper could ask.
So the raise STAMPS the hold with the human it was raised for
("human": the normalized full name the pass grouped on), and the recalc
retires ONLY an unstamped hold (the legacy class, raised by the old
per-title-regex pass while deleting a second human). A stamped hold is
never retired by the recalc; only the section.py popper consumes it, and
the popper reads kept/other only, so the extra key is inert there.
"""
from __future__ import annotations

import copy
import io
import logging
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from api_handlers import intake_consult as IC  # noqa: E402

SRC_PATH = os.path.join(ROOT, "python", "api_handlers", "intake_consult.py")


def _capture(fn):
  """Run fn() with the module logger captured; return (result, log_text)."""
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


MARCHETTI = {
  "people": [
    {"full_name": "Ottoline Marchetti",
     "role_title": "Principal Architect and Co-Owner",
     "annual_wage": 155000, "wage_source": "client_override",
     "relevant_background": "Twenty years in practice."},
    {"full_name": "Rasheed Fennimore",
     "role_title": "Design Director and Co-Owner",
     "annual_wage": 142000, "wage_source": "client_override",
     "relevant_background": "Design lead."},
  ],
  "rest_of_team_payroll_year1": 523000,
}

# A model output that carries ONLY Ottoline (the turn-79 / close-out shape),
# with a null background - "no statement", never "erase".
MODEL_ONLY_OTTOLINE = [
  {"full_name": "Ottoline Marchetti",
   "role_title": "Principal Architect and Co-Owner",
   "annual_wage": 155000, "relevant_background": None},
]


class _Helper(unittest.TestCase):
  def _helper(self):
    fn = getattr(IC, "_merge_model_roster", None)
    self.assertIsNotNone(
      fn, "the R1 model-roster merge helper is missing from intake_consult")
    return fn

  def _both_survive(self, site):
    fn = self._helper()
    (merged, report), log = _capture(
      lambda: fn(copy.deepcopy(MARCHETTI), copy.deepcopy(MODEL_ONLY_OTTOLINE),
                 site=site))
    names = [r.get("full_name") for r in merged]
    self.assertEqual(names, ["Ottoline Marchetti", "Rasheed Fennimore"])
    rasheed = merged[1]
    self.assertEqual(rasheed["annual_wage"], 142000)
    self.assertEqual(rasheed["wage_source"], "client_override")
    ottoline = merged[0]
    # null against a standing value = no statement
    self.assertEqual(ottoline["relevant_background"], "Twenty years in practice.")
    self.assertEqual(ottoline["wage_source"], "client_override")
    self.assertEqual(report["site"], site)
    self.assertEqual(report["restored"], ["Rasheed Fennimore"])
    line = [l for l in log.splitlines() if "PEOPLE_PATCH" in l]
    self.assertEqual(len(line), 1, log)
    self.assertIn(f"site={site}", line[0])
    self.assertIn("restored=['Rasheed Fennimore']", line[0])
    return merged, report


class PeopleStageMergeBehavior(_Helper):
  def test_s1_collection_extractor_restores_dropped_person(self):
    self._both_survive("collection_extractor")

  def test_s2_people_finalize_done_adding_restores_dropped_person(self):
    self._both_survive("people_finalize_done_adding")

  def test_s3_people_finalize_review_restores_dropped_person(self):
    self._both_survive("people_finalize_review")

  def test_s4_people_finalize_ready_restores_dropped_person(self):
    self._both_survive("people_finalize_ready")

  def test_model_output_without_a_people_list_keeps_the_roster(self):
    """A finalize that returns no people list at all must not wipe the
    stored roster: merges as an empty incoming list, everyone restored."""
    fn = self._helper()
    (merged, report), log = _capture(
      lambda: fn(copy.deepcopy(MARCHETTI), None, site="people_finalize_review"))
    self.assertEqual([r["full_name"] for r in merged],
                     ["Ottoline Marchetti", "Rasheed Fennimore"])
    self.assertEqual(report["incoming"], 0)
    self.assertIn("restored=['Ottoline Marchetti', 'Rasheed Fennimore']", log)

  def test_model_output_carrying_everyone_leaves_no_trace(self):
    """The unchanged case: a model roster that carries every standing
    person, field for field, merges to itself and logs nothing."""
    fn = self._helper()
    rows = copy.deepcopy(MARCHETTI["people"])
    (merged, report), log = _capture(
      lambda: fn(copy.deepcopy(MARCHETTI), rows, site="collection_extractor"))
    self.assertEqual(merged, MARCHETTI["people"])
    self.assertEqual(report["restored"], [])
    self.assertEqual(report["field_kept"], [])
    self.assertNotIn("PEOPLE_PATCH", log)

  def test_new_person_from_the_model_appends(self):
    fn = self._helper()
    rows = copy.deepcopy(MARCHETTI["people"]) + [
      {"full_name": "Priya Nair", "role_title": "Project Architect",
       "annual_wage": 98000, "wage_source": "client_override"}]
    (merged, _), _ = _capture(
      lambda: fn(copy.deepcopy(MARCHETTI), rows, site="collection_extractor"))
    self.assertEqual([r["full_name"] for r in merged],
                     ["Ottoline Marchetti", "Rasheed Fennimore", "Priya Nair"])


class PeopleStageMergeStructure(unittest.TestCase):
  """The three model-output sites are wired to the helper: the model call
  is followed by _merge_model_roster(... site="<name>") before the next
  append_messages( in the source. Fails on the pre-fix baseline with
  'no merge call after the site'."""

  SITES = (
    ("extracted_people = extract_people_collection_progress(",
     "collection_extractor"),
    ("final_obj = people_capability_finalize(\n        intake_context=intake_context_people,",
     "people_finalize_done_adding"),
    ("review_people = people_capability_finalize(",
     "people_finalize_review"),
    ("final_obj = people_capability_finalize(intake_context=intake_context, conversation_messages=final_messages)",
     "people_finalize_ready"),
  )

  @classmethod
  def setUpClass(cls):
    with open(SRC_PATH, encoding="utf-8-sig") as fh:
      cls.src = fh.read()

  def _assert_site_guarded(self, anchor, site):
    starts = [m.start() for m in re.finditer(re.escape(anchor), self.src)]
    self.assertEqual(len(starts), 1, f"expected exactly one site anchor {anchor!r}, got {len(starts)}")
    tail = self.src[starts[0]:]
    next_persist = tail.find("append_messages(")
    self.assertGreater(next_persist, 0, "no persist after the site")
    window = tail[:next_persist]
    self.assertIn("_merge_model_roster(", window,
                  f"no merge call after the site {site} before its persist")
    self.assertIn(f'site="{site}"', window,
                  f"the merge after {anchor!r} does not name site {site}")

  def test_s1_collection_extractor_is_guarded(self):
    self._assert_site_guarded(*self.SITES[0])

  def test_s2_people_finalize_done_adding_is_guarded(self):
    self._assert_site_guarded(*self.SITES[1])

  def test_s3_people_finalize_review_is_guarded(self):
    self._assert_site_guarded(*self.SITES[2])

  def test_s4_people_finalize_ready_is_guarded(self):
    self._assert_site_guarded(*self.SITES[3])

  def test_every_model_roster_call_in_the_handler_is_one_of_the_four_sites(self):
    """A fifth model-output roster call cannot appear unguarded: the count
    of extractor + finalize CALLS in the source equals the four anchors
    (the import line is not a call)."""
    calls = len(re.findall(r"people_capability_finalize\(", self.src)) \
      + len(re.findall(r"extract_people_collection_progress\(", self.src))
    self.assertEqual(calls, len(self.SITES),
                     f"{calls} model roster calls vs {len(self.SITES)} guarded sites")
    guards = len(re.findall(r"_merge_model_roster\(", self.src))
    self.assertEqual(guards, len(self.SITES) + 1, "def + one call per site")

  def test_people_people_door_still_uses_the_row_merge(self):
    """The original door is untouched: people.people still merges through
    _merge_people_rows (the helper reuses it, never a second merge)."""
    self.assertIn("value, _pp_guard = _merge_people_rows(", self.src)
    helper = self.src.find("def _merge_model_roster(")
    self.assertGreater(helper, 0)
    body = self.src[helper:helper + 2500]
    self.assertIn("_merge_people_rows(existing_rows, rows)", body)


def _recalc(fin, ppl):
  fin_c, ppl_c = copy.deepcopy(fin), copy.deepcopy(ppl)
  out, _y1 = IC._sync_financials_consult_persistence_state(
    financials_json=fin_c, financials_year1_json={}, marketing_model_json={},
    people_json=ppl_c, ops_json={})
  return out, ppl_c


class OwnerWageHoldRetire(unittest.TestCase):
  STALE_HOLD = {"kept": 155000.0, "other": 142000.0}

  def test_stale_hold_on_two_human_roster_retires_and_nothing_else_moves(self):
    """Marchetti after R3: both partners on the roster, the old hold still
    stored. THE RECALC retires it; every other financials key equals the
    same recalc run without the hold."""
    fin_with = {"_owner_wage_conflict_hold": dict(self.STALE_HOLD),
                "current_payroll": 678000.0}
    fin_without = {"current_payroll": 678000.0}
    (out_with, ppl_with), log = _capture(
      lambda: _recalc(fin_with, MARCHETTI))
    out_without, ppl_without = _recalc(fin_without, MARCHETTI)
    self.assertNotIn("_owner_wage_conflict_hold", out_with)
    self.assertEqual(out_with, out_without)
    self.assertEqual(ppl_with, ppl_without)
    self.assertEqual([p["full_name"] for p in ppl_with["people"]],
                     ["Ottoline Marchetti", "Rasheed Fennimore"])
    self.assertEqual(out_with.get("current_payroll"), 820000.0)
    self.assertIn("OWNER_WAGE_HOLD_RETIRED", log)

  def test_genuine_hold_on_one_owner_roster_is_kept(self):
    """The Sumac shape: the duplicate owner row already merged into Delia,
    the hold carries two figures for the SAME human - it stays for the
    gate, never a silent pick."""
    fin = {"_owner_wage_conflict_hold": {"kept": 48000.0, "other": 33999.96}}
    ppl = {"people": [
      {"full_name": "Delia Rennick", "role_title": "Owner / Crew Lead",
       "annual_wage": 48000, "wage_source": "client_override"},
      {"full_name": "Marcus Bell", "role_title": "Crew Member",
       "annual_wage": 38000, "wage_source": "client_override"},
    ]}
    (out, _), log = _capture(lambda: _recalc(fin, ppl))
    self.assertEqual(out.get("_owner_wage_conflict_hold"),
                     {"kept": 48000.0, "other": 33999.96})
    self.assertNotIn("OWNER_WAGE_HOLD_RETIRED", log)

  def test_genuine_same_human_conflict_raises_and_keeps_the_hold(self):
    """Two client_override rows for the same normalized human, >5% apart,
    with a second named owner also present: the pass merges the duplicate,
    raises the hold, and the retire rider must NOT pop what this pass
    raised."""
    fin = {}
    ppl = {"people": [
      {"full_name": "Ottoline Marchetti",
       "role_title": "Principal Architect and Co-Owner",
       "annual_wage": 155000, "wage_source": "client_override",
       "relevant_background": "Twenty years in practice."},
      {"full_name": "Rasheed Fennimore",
       "role_title": "Design Director and Co-Owner",
       "annual_wage": 142000, "wage_source": "client_override"},
      {"full_name": "ottoline marchetti", "role_title": "Owner",
       "annual_wage": 120000, "wage_source": "client_override"},
    ]}
    (out, ppl_out), log = _capture(lambda: _recalc(fin, ppl))
    # 5b: the raise stamps the hold with the human it was raised for.
    self.assertEqual(out.get("_owner_wage_conflict_hold"),
                     {"kept": 155000.0, "other": 120000.0,
                      "human": "ottoline marchetti"})
    self.assertEqual([p["full_name"] for p in ppl_out["people"]],
                     ["Ottoline Marchetti", "Rasheed Fennimore"])
    self.assertNotIn("OWNER_WAGE_HOLD_RETIRED", log)

  def test_no_hold_means_no_retire_line(self):
    (out, _), log = _capture(lambda: _recalc({}, MARCHETTI))
    self.assertNotIn("_owner_wage_conflict_hold", out)
    self.assertNotIn("OWNER_WAGE_HOLD_RETIRED", log)


TWO_OWNERS_WITH_DUP = {"people": [
  {"full_name": "Ottoline Marchetti",
   "role_title": "Principal Architect and Co-Owner",
   "annual_wage": 155000, "wage_source": "client_override",
   "relevant_background": "Twenty years in practice."},
  {"full_name": "Rasheed Fennimore",
   "role_title": "Design Director and Co-Owner",
   "annual_wage": 142000, "wage_source": "client_override"},
  {"full_name": "ottoline marchetti", "role_title": "Owner",
   "annual_wage": 120000, "wage_source": "client_override"},
]}

SECTION_PATH = os.path.join(
  ROOT, "python", "client_intake_and_finmo", "intake_coherence", "section.py")


class OwnerWageHoldProvenance(unittest.TestCase):
  """Item 5b: the hold carries its human; the recalc retires only an
  UNSTAMPED hold. Red at 19f69ef: the raise stored {kept, other} only, so
  pass 2 of the two-pass case saw a two-owner roster with no raise and
  retired the genuine hold (mini_r5_twopass.py case A)."""

  def test_genuine_two_owner_conflict_survives_the_next_preamble_recalc(self):
    """Pass 1 = the raise turn; pass 2 = the next turn's preamble recalc,
    which runs before every _coherence_gate call and therefore before
    the section.py popper can ask. The hold must still be there."""
    out1, ppl1 = _recalc({}, TWO_OWNERS_WITH_DUP)
    hold1 = out1.get("_owner_wage_conflict_hold")
    self.assertIsInstance(hold1, dict)
    self.assertEqual(hold1.get("kept"), 155000.0)
    self.assertEqual(hold1.get("other"), 120000.0)
    self.assertEqual([p["full_name"] for p in ppl1["people"]],
                     ["Ottoline Marchetti", "Rasheed Fennimore"])
    (out2, ppl2), log = _capture(lambda: _recalc(out1, ppl1))
    self.assertEqual(out2.get("_owner_wage_conflict_hold"), hold1,
                     "the genuine hold was retired before the gate asked")
    self.assertNotIn("OWNER_WAGE_HOLD_RETIRED", log)
    self.assertEqual([p["full_name"] for p in ppl2["people"]],
                     ["Ottoline Marchetti", "Rasheed Fennimore"])
    # and nothing else moved between the two passes
    o1 = {k: v for k, v in out1.items() if k != "_owner_wage_conflict_hold"}
    o2 = {k: v for k, v in out2.items() if k != "_owner_wage_conflict_hold"}
    self.assertEqual(o1, o2)

  def test_raise_stamps_the_hold_with_the_grouped_human(self):
    out, _ = _recalc({}, TWO_OWNERS_WITH_DUP)
    self.assertEqual(out.get("_owner_wage_conflict_hold"),
                     {"kept": 155000.0, "other": 120000.0,
                      "human": "ottoline marchetti"})

  def test_stamped_hold_is_never_retired_by_the_recalc(self):
    """A stamped hold stored on a two-owner roster with no raise this
    pass (the pass-2 shape after the duplicate is gone): kept as is, no
    RETIRED line, everything else equal to the same recalc without it."""
    hold = {"kept": 155000.0, "other": 120000.0, "human": "ottoline marchetti"}
    fin_with = {"_owner_wage_conflict_hold": dict(hold),
                "current_payroll": 678000.0}
    (out_with, ppl_with), log = _capture(lambda: _recalc(fin_with, MARCHETTI))
    out_without, ppl_without = _recalc({"current_payroll": 678000.0}, MARCHETTI)
    self.assertEqual(out_with.get("_owner_wage_conflict_hold"), hold)
    self.assertNotIn("OWNER_WAGE_HOLD_RETIRED", log)
    rest = {k: v for k, v in out_with.items() if k != "_owner_wage_conflict_hold"}
    self.assertEqual(rest, out_without)
    self.assertEqual(ppl_with, ppl_without)

  def test_unstamped_legacy_hold_still_retires_and_says_so(self):
    """The only stale class: a hold with NO human stamp on a roster that
    now carries two named owner humans (Marchetti after R3)."""
    fin = {"_owner_wage_conflict_hold": {"kept": 155000.0, "other": 142000.0}}
    (out, _), log = _capture(lambda: _recalc(fin, MARCHETTI))
    self.assertNotIn("_owner_wage_conflict_hold", out)
    line = [l for l in log.splitlines() if "OWNER_WAGE_HOLD_RETIRED" in l]
    self.assertEqual(len(line), 1, log)
    self.assertIn("unstamped", line[0])

  def test_the_gate_never_drops_the_owner_hold(self):
    """Option B (Nick 2026-09-11) replaced the ask-once popper: the gate
    asks and blocks, and only the client's answer clears the hold (the
    handler's _resolve_owner_wage_hold). An extra human key is still inert
    to the question - it reads kept/other only."""
    with open(SECTION_PATH, encoding="utf-8-sig") as fh:
      src = fh.read()
    self.assertNotIn('pop("_owner_wage_conflict_hold"', src)
    start = src.find("def open_hold_questions(")
    self.assertGreater(start, 0)
    block = src[start:src.find("\ndef ", start + 10)]
    self.assertIn('owner.get("kept")', block)
    self.assertIn('owner.get("other")', block)
    self.assertNotIn("human", block)


if __name__ == "__main__":
  unittest.main()
