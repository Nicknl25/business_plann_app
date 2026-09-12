"""A-162 - NEVER A DEAD DRAFT (Nick 2026-09-12).

"Four routes to a dead draft, one cause. The reply box is never disabled.
Not when the walk runs out of options, not on a park, not on a failed
build, not on a 400. And Submit is never locked behind a condition that
can never become true. A walk that runs out of options with a cash-positive
quarter and 75% closed must offer something: submit as it stands, park, or
say plainly what's left. Never nothing."

CW-062 (Dunmore & Tate, 4949cdb4): twelve rounds, 75% closed, the walk
exhausted its attempts and left the client with no buttons, a template that
said nothing had moved, and a Submit that could never unlock.
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

from client_intake_and_finmo.intake_coherence import section as S  # noqa: E402
from client_intake_and_finmo.intake_coherence import controller as C  # noqa: E402
from replay_gate import legs as L  # noqa: E402  (the gate's own walking fixture)


def _walking_with_terminal(gap=196203.33):
  state = {"status": C.STATUS_WALKING, "digest_hash": "d", "gap_open": gap, "gap_initial": 774250.68,
           "client_floors": {"rent": True, "volume": True}, "rounds_done": ["volume"],
           "_lever_writes": {"marketing_total_year1": {"from": 145000.0, "to": 103500.0},
                             "other_opex_absolute": {"from": 2520000.0, "to": 407286.36},
                             "current_revenue": {"from": 4600000.0, "to": 3450000.0}}}
  state["round"] = S._terminal_round(state, gap)
  return {"monthly_rent_expense": 26000, "other_operating_expense": 33940.53, "_coherence": state}


def _apply(patch, fin, text=""):
  return S.apply_router_patch(patch=dict(patch), ops_json={}, financials_json=fin, user_text=text)


def _exhausted_fixture():
  """The gate's own end-of-walk fixture with every authored attempt spent."""
  fin = dict(L.GOAL_FIN)
  st = L._goal_walking_state(S, fin, L.GOAL_OPS)
  st["authored_attempts"] = 12
  fin["_coherence"] = st
  return fin


def _gate(fin, text="ok, what's next?"):
  return S.gate_and_turn(ops_json=L.GOAL_OPS, people_json={}, market_json={}, marketing_model_json={},
                         financials_json=fin, financials_year1_json={}, user_text=text,
                         transcript=[{"role": "user", "content": text}])


class TheEndOfTheWalkIsARoundWithDoors(unittest.TestCase):
  def test_the_terminal_round_has_the_three_doors(self):
    rnd = S._terminal_round({"client_floors": {}}, 196203.33)
    self.assertEqual(rnd["key"], C.ROUND_TERMINAL)
    self.assertTrue(rnd["terminal"])
    self.assertEqual([o["id"] for o in rnd["options"]], ["submit_as_is", "park", "rerun"])
    for o in rnd["options"]:
      self.assertTrue(o.get("label") and o.get("why"), o)

  def test_the_statement_reads_the_store_never_a_template(self):
    fin = _walking_with_terminal()
    st = S.get_state(fin)
    text = S._terminal_statement(st, 196203.33, {"q11": {"ebitda": 89547.0}})
    self.assertIn("$196,203 a quarter is still open", text)
    self.assertIn("keeps about $89,547", text)
    self.assertIn("annual revenue $4,600,000 to $3,450,000 (-25%)", text)
    self.assertIn("other operating costs a year $2,520,000 to $407,286 (-84%)", text)
    self.assertNotIn("Nothing you set has been moved", text)
    self.assertNotIn("Nothing you told me has been moved", text)
    # the cumulative sentence is the same one every round can use
    self.assertIn("the marketing budget $145,000 to $103,500 (-29%)", S.cumulative_effect_sentence(st))

  def test_nothing_moved_is_said_only_when_nothing_moved(self):
    text = S._terminal_statement({"client_floors": {}, "_lever_writes": {}}, 1000.0, {"q11": {}})
    self.assertIn("Nothing you told me has been moved", text)

  def test_the_question_names_every_door_and_keeps_the_marker(self):
    rnd = S._terminal_round({}, 196203.33)
    q = S._round_question(rnd, "$196,203")
    for label in ("Submit the plan as it stands", "Save it for now", "A number I have isn't right"):
      self.assertIn(label, q)
    self.assertIn(S.COHERENCE_MARKER, q)

  def test_the_real_gate_ends_the_exhausted_walk_with_doors_not_a_wall(self):
    fin = _exhausted_fixture()
    turn, fin1, _sfx = _gate(fin)
    self.assertIsNotNone(turn)
    st1 = S.get_state(fin1)
    self.assertEqual((st1.get("round") or {}).get("key"), C.ROUND_TERMINAL)
    msg = str(turn.get("assistant_message") or "")
    for label in ("Submit the plan as it stands", "Save it for now", "A number I have isn't right"):
      self.assertIn(label, msg)
    self.assertNotIn("Nothing you set has been moved", msg)
    self.assertIn(S.COHERENCE_MARKER, msg)
    # the doors stay on the table on the next turn - never a wall, never a loop of the same line
    turn2, fin2, _ = _gate(fin1, "hmm")
    self.assertEqual((S.get_state(fin2).get("round") or {}).get("key"), C.ROUND_TERMINAL)
    self.assertIn("Submit the plan as it stands", str(turn2.get("assistant_message") or ""))


class EveryDoorMovesTheDraft(unittest.TestCase):
  def test_submit_as_it_stands_accepts_and_the_gate_completes_with_the_gap_stated(self):
    fin = _walking_with_terminal()
    _r, _o, fin1, notes = _apply({"coherence.option": "submit_as_is"}, fin, "Let's go with option 1 - Submit the plan as it stands.")
    st1 = S.get_state(fin1)
    self.assertIn("accepted_as_is", notes)
    self.assertEqual(st1["status"], C.STATUS_ACCEPTED)
    self.assertAlmostEqual(st1["accepted_with_gap"], 196203.33)
    self.assertNotIn("round", st1)
    # through the REAL gate: an accepted draft completes, and the readback says what is open
    fin2 = _exhausted_fixture()
    fin2["_coherence"]["status"] = C.STATUS_ACCEPTED
    turn, fin3, suffix = _gate(fin2, "go ahead")
    self.assertIsNone(turn, "an accepted draft must complete, never be held")
    self.assertIn("submit the plan as it stands", suffix)
    self.assertIn("short of the lender test", suffix)
    self.assertIn("the marketing budget $23,850 to $12,000", suffix)
    self.assertEqual(S.get_state(fin3)["status"], C.STATUS_ACCEPTED)

  def test_save_it_for_now_parks_and_keeps_the_doors(self):
    fin = _walking_with_terminal()
    _r, _o, fin1, notes = _apply({"coherence.option": "park"}, fin, "Save it for now.")
    st1 = S.get_state(fin1)
    self.assertIn("parked", notes)
    self.assertEqual(st1["status"], C.STATUS_PARKED)
    self.assertEqual((st1.get("round") or {}).get("key"), C.ROUND_TERMINAL, "the doors stay through a park")

  def test_a_number_is_wrong_asks_which_and_keeps_the_doors(self):
    fin = _walking_with_terminal()
    _r, _o, fin1, notes = _apply({"coherence.option": "rerun"}, fin, "A number I have isn't right.")
    st1 = S.get_state(fin1)
    self.assertIn("rerun_requested", notes)
    self.assertTrue(st1.get("rerun_requested"))
    fin2 = _exhausted_fixture()
    fin2["_coherence"]["round"] = S._terminal_round(fin2["_coherence"], 9000.0)
    fin2["_coherence"]["rerun_requested"] = True
    turn, fin3, _ = _gate(fin2, "A number I have isn't right.")
    self.assertIn("Which figure isn't right?", str(turn.get("assistant_message") or ""))
    st3 = S.get_state(fin3)
    self.assertFalse(st3.get("rerun_requested"))
    self.assertEqual((st3.get("round") or {}).get("key"), C.ROUND_TERMINAL)


class TheRouterAndThePanelKnowTheDoors(unittest.TestCase):
  def test_finish_with_the_numbers_as_they_stand_is_submit_not_park(self):
    src = open(os.path.join(ROOT, "python", "client_intake_and_finmo", "intent_router.py"), encoding="utf-8").read()
    self.assertIn('coherence.option = \\"submit_as_is\\"', src)
    self.assertIn("If they pick 'Save it for now' return coherence.parked = true", src)
    self.assertIn('coherence.option = \\"rerun\\"', src)

  def test_the_reply_box_is_never_disabled(self):
    src = open(os.path.join(ROOT, "frontend", "src", "intake_form", "steps", "UnifiedConsultStep.tsx"), encoding="utf-8").read()
    i = src.find("<Input\n            ref={chatInputRef}")
    self.assertGreater(i, 0)
    block = src[i:src.find("/>", i)]
    self.assertNotIn("disabled=", block, "the reply INPUT carries no disabled prop - only Send waits for a request in flight")
    self.assertIn("disabled={composerLocked || !inputValue.trim()}", src)

  def test_the_panel_shows_the_doors_in_every_status_that_carries_a_round(self):
    src = open(os.path.join(ROOT, "frontend", "src", "intake_form", "steps", "CoherencePanel.tsx"), encoding="utf-8").read()
    self.assertEqual(src.count("{doors}"), 2, "walking/parked AND roadmap render the round's doors")
    self.assertIn('status === "accepted_as_is"', src)
    self.assertIn("Where to from here", src)


if __name__ == "__main__":
  unittest.main()


class AFailedBuildNeverLeavesADeadDraft(unittest.TestCase):
  """Castellane: a terminal build failure left a 'submitted' draft where every
  later turn was a 409 and Submit read 'Submitted' forever."""

  def test_a_terminal_failure_is_recognised_and_only_that(self):
    from client_intake_and_finmo import intake_consult_draft as D
    for st in ("failed", "FAILED", "error", "stopped", "cancelled"):
      self.assertTrue(D.run_is_terminal_failure(st), st)
    for st in ("completed", "running", "queued", "", None):
      self.assertFalse(D.run_is_terminal_failure(st), st)
    self.assertTrue(D.latest_run_failed(None, {"planning_run_status": "failed"}))
    self.assertFalse(D.latest_run_failed(None, {"planning_run_status": "completed", "planning_run_id": ""}))

  def test_the_turn_and_the_submit_reopen_on_a_failed_build(self):
    h = open(os.path.join(ROOT, "python", "api_handlers", "intake_consult.py"), encoding="utf-8").read()
    i = h.find('if draft_status == "submitted":')
    block = h[i:i + 1600]
    self.assertIn("_a162_failed(conn, consult) and _a162_reopen(conn", block)
    self.assertIn("A162_REOPEN_RECEIPT", block)
    self.assertIn("duplicate_submit", block, "a run that did NOT fail keeps the refusal")
    f = open(os.path.join(ROOT, "python", "api_handlers", "financials.py"), encoding="utf-8").read()
    j = f.find('if draft_status == "submitted":')
    self.assertIn("_a162_failed(_reopen_conn, draft) and _a162_reopen(_reopen_conn", f[j:j + 1200])

  def test_reopen_only_takes_the_submitted_flag_off(self):
    from client_intake_and_finmo import intake_consult_draft as D
    import inspect
    src = inspect.getsource(D.reopen_after_failed_build)
    self.assertIn("SET status = 'completed'", src)
    self.assertIn("submitted_at = NULL", src)
    self.assertNotIn("operating_model_json", src, "the intake is untouched; only the submitted flag comes off")

  def test_the_submit_button_offers_submit_again_after_a_failed_build(self):
    ss = open(os.path.join(ROOT, "frontend", "src", "intake_form", "steps", "SubmitStep.tsx"), encoding="utf-8").read()
    self.assertIn('"Submit again"', ss)
    self.assertIn("(!consultDone && !buildFailed)", ss)
    self.assertIn("(Boolean(submitSuccess) && !buildFailed)", ss)
    u = open(os.path.join(ROOT, "frontend", "src", "intake_form", "steps", "UnifiedConsultStep.tsx"), encoding="utf-8").read()
    self.assertIn("setBuildFailed(", u)
    self.assertIn("planning_run_status", u)
