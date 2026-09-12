"""THE INTAKE WATCHER (Nick 2026-09-12): "Don't split it. Build the whole
watcher. Where code gives a certain answer, use code. Where it needs the
transcript read, the model reads it. Both run on every turn, always.
Per-turn placement. Read-only."

These pins drive the checks on the shapes from the 12 September batch and
the classes designed for what has not happened yet, drive the model read
through a fake transport under the real schema, and prove the wiring: the
one persistence door notifies the watcher, the watcher never writes the
draft, and the gate runs it inline.
"""
from __future__ import annotations

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo.intake_watcher import checks as C  # noqa: E402
from client_intake_and_finmo.intake_watcher import judgment as J  # noqa: E402
from client_intake_and_finmo.intake_watcher import vocabulary as V  # noqa: E402
from client_intake_and_finmo.intake_watcher.observe import MemoryStore, observe_draft_turn, diff_of  # noqa: E402


def _turn(user, assistant, before, after, prior_user=(), prior_assistant=(), turn=10):
  return C.Turn(draft_id="d1", turn=turn, user_text=user, assistant_text=assistant, before=before, after=after,
                prior_user_texts=list(prior_user), prior_assistant_texts=list(prior_assistant))


def _kinds(obs):
  return sorted(o["kind"] for o in obs)


class TheVocabularyIsClosed(unittest.TestCase):
  def test_every_kind_has_a_severity_a_detector_and_a_meaning(self):
    for k, (sev, det, meaning) in V.KINDS.items():
      self.assertIn(sev, (V.BLOCKER, V.MAJOR, V.MINOR), k)
      self.assertIn(det, (V.CODE, V.MODEL, V.BOTH), k)
      self.assertGreater(len(meaning), 20, k)

  def test_an_unknown_kind_cannot_be_filed(self):
    with self.assertRaises(ValueError):
      V.observation("made_up", draft_id="d", turn=1)

  def test_the_model_may_only_file_model_kinds(self):
    self.assertIn("refusal_violated", V.MODEL_KINDS)
    self.assertNotIn("roster_not_in_basis", V.MODEL_KINDS)
    self.assertEqual(J.SCHEMA["properties"]["observations"]["items"]["properties"]["kind"]["enum"], list(V.MODEL_KINDS))


class TheTwelveSeptemberShapes(unittest.TestCase):
  def test_sablecreek_107_unit_copied(self):
    before = {"financials": {"other_operating_expense": 340000, "monthly_rent_expense": 22000}}
    after = {"financials": {"other_operating_expense": 633312, "monthly_rent_expense": 22000}}
    obs = C.check_unit_copied(_turn("My other operating expense should go to 633,312 a year and my monthly rent stays at 22,000.",
                                    "Got it, updated to $633,312 per month just as you specified.", before, after))
    self.assertEqual(_kinds(obs), ["unit_copied"])
    self.assertEqual(obs[0]["expected"], 52776.0)

  def test_sablecreek_kwabena_roster_not_in_basis(self):
    after = {"people": {"people": [{"full_name": "Perrine Sablecreek", "annual_wage": 190000}, {"full_name": "Kwabena Osei-Tutu", "annual_wage": 165000}]},
             "financials": {"payroll_basis_people_roles": [{"source": "person", "full_name": "Perrine Sablecreek", "annual_wage": 190000, "year1_payroll_amount": 190000}],
                            "payroll_total_year1": 190000}}
    obs = C.check_roster_not_in_basis(_turn("Yes. Kwabena Osei-Tutu is my engineering lead. He is on 165,000.", "Noted.", {}, after))
    self.assertEqual(_kinds(obs), ["roster_not_in_basis"])
    self.assertEqual(obs[0]["expected"], "Kwabena Osei-Tutu")

  def test_sablecreek_93_refusal_violated_by_a_move(self):
    before = {"financials": {"monthly_rent_expense": 22000, "_coherence": {"client_floors": {"rent": True}}}}
    after = {"financials": {"monthly_rent_expense": 13333.33, "_coherence": {"client_floors": {"rent": True}}}}
    obs = C.check_refusal_violated(_turn("Take the overhead down where it genuinely can come down.", "Your numbers clear every test.", before, after))
    self.assertEqual(_kinds(obs), ["refusal_violated"])

  def test_a_clients_own_restatement_of_a_floored_figure_is_not_a_violation(self):
    before = {"financials": {"monthly_rent_expense": 13333.33, "_coherence": {"client_floors": {"rent": True}}}}
    after = {"financials": {"monthly_rent_expense": 22000, "_coherence": {"client_floors": {"rent": True}}}}
    obs = C.check_refusal_violated(_turn("my rent is 22,000 a month on a signed lease", "Got it.", before, after))
    self.assertEqual(obs, [])

  def test_sablecreek_92_recommendation_not_largest(self):
    after = {"financials": {"_coherence": {"gap_open": 904510.27, "round": {"options": [
      {"id": "costs_all", "closes_quarterly": 904510.0, "deep_cut": True, "lease_unknown": True},
      {"id": "costs_cogs", "closes_quarterly": 9893.0, "recommended": True},
      {"id": "costs_gna_rent", "closes_quarterly": 880000.0, "deep_cut": True, "lease_unknown": True},
    ]}}}}
    obs = C.check_recommendation_not_largest(_turn("", "", {}, after))
    self.assertEqual(_kinds(obs), ["recommendation_not_largest"])

  def test_an_offered_option_that_moves_a_refused_cost(self):
    after = {"financials": {"_coherence": {"client_floors": {"rent": True}, "round": {"options": [
      {"id": "costs_gna_rent", "patch": {"kind": "financials_fields", "fields": [{"group": "financials", "field": "monthly_rent_expense", "value": 1}]}}]}}}}
    obs = C.check_option_touches_refusal(_turn("", "", {}, after))
    self.assertEqual(_kinds(obs), ["option_touches_refusal"])

  def test_halloran_verbatim_paragraph(self):
    para = "Another lever you can realistically pull is volume - serving more of the demand that already exists in your market. Right now, branded sets are at about 63,000 a year."
    obs = C.check_reply_repeated(_turn("The private-label figure is wrong. It is eight.", para, {}, {}, prior_assistant=[para, "ok"]))
    self.assertEqual(_kinds(obs), ["reply_repeated"])

  def test_sablecreek_growth_lever_empty_at_wrap(self):
    ops = {"shipping_method": "on site", "sales_modality": "hybrid", "geographic_scope": "regional", "geographic_coverage": "ID",
           "countries": ["US"], "capacity_driver": "labor", "primary_growth_lever": "", "legal_entity": "LLC"}
    obs = C.check_required_field_empty_at_wrap(_turn("thirty installs", "Great, let's move on to Target Market.",
                                                     {"active_focus": "ops", "ops": ops}, {"active_focus": "market", "ops": ops}))
    self.assertEqual(_kinds(obs), ["required_field_empty_at_wrap"])
    self.assertEqual(obs[0]["stored_value"], ["primary_growth_lever"])

  def test_sablecreek_94_the_apps_own_number_quoted_back_is_not_a_stated_figure(self):
    """'ten thousand of a nine hundred thousand gap' quotes 904,510 back; the
    app asked which line the $900 belongs to. figure_unplaced must not file
    on the quote; the misread itself is the model's kind."""
    after = {"financials": {"monthly_rent_expense": 22000}}
    t = _turn("option two only closes about ten thousand of a nine hundred thousand gap",
              "you gave me $900 and I couldn't tell where it belongs",
              after, after, prior_assistant=["That's the gap: about $904,510 per quarter."])
    self.assertEqual(C.check_figure_unplaced(t), [])

  def test_raw_field_name_shown_to_the_client(self):
    obs = C.check_raw_field_name_shown(_turn("", "primary_growth_lever: primary_growth_lever is required", {}, {}))
    self.assertEqual(_kinds(obs), ["raw_field_name_shown"])
    self.assertEqual(C.check_raw_field_name_shown(_turn("", "What is the main lever you'll push first to grow?", {}, {})), [])


class TheClassesForWhatHasNotHappenedYet(unittest.TestCase):
  def test_a_value_that_moved_with_no_message_causing_it(self):
    before = {"financials": {"monthly_rent_expense": 22000, "other_operating_expense": 340000}}
    after = {"financials": {"monthly_rent_expense": 15000, "other_operating_expense": 340000}}
    obs = C.check_value_moved_without_cause(_turn("Please wrap up the intake.", "Understood, let's move on.", before, after))
    self.assertEqual(_kinds(obs), ["value_moved_without_cause"])
    self.assertEqual(obs[0]["field"], "financials.monthly_rent_expense")

  def test_a_move_the_reply_accounts_for_is_not_without_cause(self):
    before = {"financials": {"monthly_rent_expense": 22000}}
    after = {"financials": {"monthly_rent_expense": 15000}}
    obs = C.check_value_moved_without_cause(_turn("option one", "With your agreement rent moves to $15,000 a month.", before, after))
    self.assertEqual(obs, [])

  def test_a_derived_leaf_moving_is_not_a_cause_of_its_own(self):
    before = {"financials": {"payroll_total_year1": 190000}}
    after = {"financials": {"payroll_total_year1": 355000}}
    self.assertEqual(C.check_value_moved_without_cause(_turn("no", "ok", before, after)), [])

  def test_a_receipt_that_disagrees_with_the_store(self):
    after = {"financials": {"monthly_rent_expense": 22000}}
    obs = C.check_receipt_disagrees_with_store(_turn("", "rent → $13,333 per month", {}, after))
    self.assertEqual(_kinds(obs), ["receipt_disagrees_with_store"])
    self.assertEqual(C.check_receipt_disagrees_with_store(_turn("", "rent → $22,000 per month ($264,000 a year)", {}, after)), [])

  def test_an_intake_completing_with_a_hold_open(self):
    before = {"status": "in_progress", "financials": {"_payroll_fold_hold": {"unapplied": 5000}}}
    after = {"status": "completed", "financials": {"_payroll_fold_hold": {"unapplied": 5000}}}
    obs = C.check_completed_with_hold_open(_turn("done", "the intake is complete", before, after))
    self.assertEqual(_kinds(obs), ["completed_with_hold_open"])

  def test_a_figure_the_client_stated_that_appears_nowhere(self):
    after = {"financials": {"monthly_rent_expense": 22000}}
    obs = C.check_figure_unplaced(_turn("Marketing is 165,000 a year.", "Great, let's talk about volume.", after, after))
    self.assertEqual(_kinds(obs), ["figure_unplaced"])
    self.assertEqual(obs[0]["expected"], 165000.0)

  def test_a_stated_figure_the_app_asked_about_is_placed_enough(self):
    after = {"financials": {}}
    obs = C.check_figure_unplaced(_turn("Marketing is 165,000 a year.", "Is 165,000 your annual marketing budget or a monthly figure?", after, after))
    self.assertEqual(obs, [])

  def test_a_correction_restated_and_still_nowhere(self):
    after = {"ops": {"lob_models": [{"products": [{"operating_periods_per_year": 12}]}]}}
    t = _turn("periods a year should be 1, not 12. Set periods a year to 1 on that line, the fee is 252,000.", "name the stored number that's wrong",
              after, after, prior_user=["The 252,000 is what one programme is worth for a whole year"])
    self.assertEqual(_kinds(C.check_correction_ignored(t)), ["correction_ignored"])

  def test_a_basis_that_does_not_sum(self):
    after = {"financials": {"payroll_basis_people_roles": [{"year1_payroll_amount": 100000}, {"year1_payroll_amount": 50000}], "payroll_total_year1": 200000}}
    self.assertEqual(_kinds(C.check_basis_sum_mismatch(_turn("", "", {}, after))), ["basis_sum_mismatch"])

  def test_the_same_question_three_times_is_a_loop(self):
    q = "Which of those stored numbers is wrong? Name the field and the figure it should be?"
    obs = C.check_loop(_turn("it is eight", q, {}, {}, prior_assistant=[q, "ok", q]))
    self.assertEqual(_kinds(obs), ["loop"])

  def test_a_broken_check_is_an_observation_not_a_crash(self):
    def boom(t):
      raise RuntimeError("x")
    saved = C.CHECKS
    C.CHECKS = (boom,)
    try:
      obs = C.run_checks(_turn("", "", {}, {}))
    finally:
      C.CHECKS = saved
    self.assertEqual(obs[0]["kind"], "watcher_check_error")


class TheModelReadIsLockedAndSchemaBound(unittest.TestCase):
  class _Resp:
    def __init__(self, data, status=200):
      self._d, self.status_code, self.text = data, status, json.dumps(data)

    def json(self):
      return self._d

  def test_the_payload_carries_the_evidence_and_asserts_no_numbers(self):
    p = J.build_payload(transcript=[{"role": "user", "content": "the lease is signed"}], user_text="u", assistant_text="a",
                        diff={"financials.monthly_rent_expense": {"before": 22000, "after": 13333}},
                        floors={"rent": True}, options=[{"id": "x", "label": "y", "closes_display": "$1"}])
    body = json.loads(p["input"][1]["content"])
    self.assertEqual(body["client_refusals_recorded"], {"rent": True})
    self.assertIn("financials.monthly_rent_expense", body["store_diff_this_turn"])
    self.assertTrue(p["text"]["format"]["strict"])
    self.assertIn("never invent a number", J.SYSTEM)
    self.assertIn("You never speak to the client and you never change anything", J.SYSTEM)

  def test_observations_come_back_typed_and_unknown_kinds_are_dropped(self):
    os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY") or "test-key"
    data = {"output": [{"content": [{"type": "output_json", "json": {"observations": [
      {"kind": "refusal_violated", "client_words": "the lease is signed", "field": "financials.monthly_rent_expense",
       "stored_value": "13333", "expected": "22000", "why": "rent moved after the refusal"},
      {"kind": "roster_not_in_basis", "client_words": "", "field": "", "stored_value": "", "expected": "", "why": "not the model's kind"},
    ]}}]}]}
    calls = []
    def fake_post(**kw):
      calls.append(kw)
      return self._Resp(data)
    obs = J.judge_turn(draft_id="d1", turn=5, transcript=[], user_text="u", assistant_text="a", diff={}, floors={}, options=[], post=fake_post)
    self.assertEqual([o["kind"] for o in obs], ["refusal_violated"])
    self.assertEqual(obs[0]["detector"], "model")
    self.assertEqual(calls[0]["url"], J.OPENAI_RESPONSES_URL)

  def test_a_transport_failure_is_visible_never_silent(self):
    os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY") or "test-key"
    def fake_post(**kw):
      return self._Resp({"error": "boom"}, status=500)
    obs = J.judge_turn(draft_id="d1", turn=5, transcript=[], user_text="u", assistant_text="a", diff={}, floors={}, options=[], post=fake_post)
    self.assertEqual(obs[0]["kind"], "watcher_model_unavailable")


class TheWatcherObservesEveryTurnAndWritesOnlyItsOwnTables(unittest.TestCase):
  def test_end_to_end_on_a_turn_with_the_store_diffed_against_the_last_snapshot(self):
    store = MemoryStore()
    draft1 = {"draft_id": "d1", "status": "in_progress", "active_focus": "financials",
              "financials_json": json.dumps({"monthly_rent_expense": 22000, "_coherence": {"client_floors": {"rent": True}}}),
              "people_json": "{}", "operating_model_json": "{}",
              "messages_json": json.dumps([{"role": "user", "content": "The lease is signed, rent cannot move."}, {"role": "assistant", "content": "Understood."}])}
    obs1 = observe_draft_turn(draft=draft1, store=store, run_model=False)
    self.assertEqual(obs1, [])
    draft2 = dict(draft1)
    draft2["financials_json"] = json.dumps({"monthly_rent_expense": 13333.33, "_coherence": {"client_floors": {"rent": True}}})
    draft2["messages_json"] = json.dumps(json.loads(draft1["messages_json"]) + [
      {"role": "user", "content": "Take the overhead down where it can."},
      {"role": "assistant", "content": "Your numbers clear every structural test."}])
    obs2 = observe_draft_turn(draft=draft2, store=store, run_model=False)
    self.assertIn("refusal_violated", _kinds(obs2))
    self.assertIn("value_moved_without_cause", _kinds(obs2))
    self.assertEqual(store.snapshots["d1"]["_turn"], 4)
    self.assertEqual(len(store.list_observations("d1")), len(obs2))
    self.assertEqual(draft2["financials_json"], json.dumps({"monthly_rent_expense": 13333.33, "_coherence": {"client_floors": {"rent": True}}}),
                     "the watcher never touches the draft")

  def test_the_diff_names_every_leaf_that_moved(self):
    d = diff_of({"financials": {"a": 1, "b": 2}, "status": "in_progress"}, {"financials": {"a": 1, "b": 3}, "status": "completed"})
    self.assertEqual(d, {"financials.b": {"before": 2.0, "after": 3.0}, "status": {"before": "in_progress", "after": "completed"}})

  def test_the_one_persistence_door_notifies_the_watcher(self):
    src = open(os.path.join(ROOT, "python", "client_intake_and_finmo", "intake_consult_draft.py"), encoding="utf-8").read()
    i = src.find("def append_messages(")
    body = src[i:src.find("\ndef ", i + 10)]
    self.assertIn("notify_turn_persisted(str(draft_id))", body)
    self.assertIn("if commit and new_messages:", body)

  def test_the_watcher_has_no_write_path_to_the_draft(self):
    for rel in ("observe.py", "checks.py", "judgment.py", "vocabulary.py"):
      src = open(os.path.join(ROOT, "python", "client_intake_and_finmo", "intake_watcher", rel), encoding="utf-8").read()
      self.assertNotIn("append_messages(", src, rel)
      self.assertNotIn("UPDATE intake_consult_drafts", src, rel)
      self.assertNotIn("_apply_scoped_patch", src, rel)

  def test_the_gate_runs_it_inline_and_the_route_exists(self):
    gate = open(os.path.join(ROOT, "scripts", "intake_persona_gate.py"), encoding="utf-8").read()
    self.assertIn('os.environ["INTAKE_WATCHER_SYNC"] = "1"', gate)
    api = open(os.path.join(ROOT, "python", "api.py"), encoding="utf-8").read()
    self.assertIn('@app.route("/api/intake-watch/<draft_id>", methods=["GET", "OPTIONS"])', api)


if __name__ == "__main__":
  unittest.main()
