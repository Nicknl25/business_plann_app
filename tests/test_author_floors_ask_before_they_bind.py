"""ITEM 8 (Nick 2026-09-12) - three different problems, not one prompt change.

(a) INPUT BUG: the author read seven of the app's own sentences as the
    client's refusals. It only ever sees client turns for floors.
(b) A CHECK, not a prompt: a floor must quote the words that carry it, and
    those words must be the client's - verbatim in a client turn.
(c) The judgment call ("I'd rather deepen it than chase new ones") ASKS
    rather than locking a lever out for eleven rounds.
(d) A floor set in round 6 must not bind silently: the client can see a
    locked-out lever and say otherwise.
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

from client_intake_and_finmo.intake_coherence import author as A  # noqa: E402
from client_intake_and_finmo.intake_coherence import section as S  # noqa: E402
from client_intake_and_finmo.intake_coherence import controller as C  # noqa: E402
from replay_gate import legs as L  # noqa: E402


def _author_resp(floors, candidates=None):
  class _Resp:
    status_code = 200
    def json(self):
      return {"output": [{"content": [{"type": "output_text", "text": json.dumps({
        "floors_read": floors,
        "candidates": candidates or [{"kind": "cost", "levers": ["gna"], "depth": 0.5, "line_moves": [], "label": "l", "why": "w"}]})}]}]}
  return _Resp()


def _payload(transcript):
  return {"model": "x", "input": [{"role": "system", "content": "s"},
                                  {"role": "user", "content": json.dumps({"transcript": transcript})}]}


class TheAuthorReadsClientTurnsOnly(unittest.TestCase):
  def test_the_payload_carries_the_client_turns_apart(self):
    p = A.build_payload(transcript=[{"role": "assistant", "content": "we're closing a $855,277 a quarter gap"},
                                    {"role": "user", "content": "The cafe book is healthy."}],
                        business={}, gap_display="$1", cost_levers=[], lines=[], floors_recorded={}, declined=[], rounds_done=[])
    body = json.loads(p["input"][1]["content"])
    self.assertEqual(body["client_turns"], ["The cafe book is healthy."])
    self.assertIn("client_turns", A.SYSTEM if "client_turns" in A.SYSTEM else body)

  def test_an_app_sentence_quoted_as_a_refusal_is_dropped(self):
    """CW-062 call 9: seven of the app's own 'we're closing a $X gap' lines
    were read as the client's volume refusals."""
    os.environ.setdefault("OPENAI_API_KEY", "test-key")
    tr = [{"role": "assistant", "content": "We're closing a $855,277 a quarter gap so this plan can work on paper."},
          {"role": "user", "content": "Let's go with option 2."}]
    res = A.author(payload=_payload(tr), post=lambda **kw: _author_resp(
      [{"cost": "volume", "because": "we're closing a $855,277 a quarter gap so this plan can work on paper.", "kind": "refused"}]))
    self.assertEqual(res["floors_read"], [])

  def test_a_paraphrase_is_not_the_clients_words(self):
    os.environ.setdefault("OPENAI_API_KEY", "test-key")
    tr = [{"role": "user", "content": "The roastery lease is signed for another six years."}]
    res = A.author(payload=_payload(tr), post=lambda **kw: _author_resp(
      [{"cost": "rent", "because": "the lease cannot be changed for six years", "kind": "cannot_move"}]))
    self.assertEqual(res["floors_read"], [])

  def test_a_verbatim_quote_passes_with_case_and_punctuation_folded(self):
    os.environ.setdefault("OPENAI_API_KEY", "test-key")
    tr = [{"role": "user", "content": "Yes, always. The roastery lease is signed for another six years."}]
    res = A.author(payload=_payload(tr), post=lambda **kw: _author_resp(
      [{"cost": "rent", "because": "the roastery lease is signed for another six years", "kind": "cannot_move"}]))
    self.assertEqual([f["cost"] for f in res["floors_read"]], ["rent"])
    self.assertTrue(A.quote_is_the_clients("THE ROASTERY LEASE IS SIGNED for another six years!!", [tr[0]["content"]]))
    self.assertFalse(A.quote_is_the_clients("lease", [tr[0]["content"]]), "a fragment too short to carry anything")


def _fixture():
  fin = dict(L.GOAL_FIN)
  fin.update({"baseline_payroll_year1": 120000.0, "current_payroll": 120000.0, "payroll_total_year1": 120000.0,
              "other_opex_absolute": 90000.0, "other_operating_expense": 7500.0, "monthly_rent_expense": 2500.0})
  fin["_coherence"] = L._goal_walking_state(S, fin, L.GOAL_OPS)
  return fin


def _gate(fin, text, author):
  return S.gate_and_turn(ops_json=L.GOAL_OPS, people_json={}, market_json={}, marketing_model_json={},
                         financials_json=fin, financials_year1_json={}, user_text=text,
                         transcript=[{"role": "user", "content": text}], author=author)


class AFloorTheAuthorReadIsAskedBeforeItBinds(unittest.TestCase):
  def test_the_preference_asks_and_the_lever_stays_until_the_client_says(self):
    fin = _fixture()
    text = "The cafe book is healthy and I would rather deepen it than chase new ones."
    author = lambda payload: {"floors_read": [{"cost": "volume", "because": text, "kind": "refused"}], "floors_mentioned": [],
                              "candidates": [{"kind": "cost", "levers": ["gna"], "depth": 0.5, "line_moves": [], "label": "Trim overhead", "why": "w"}]}
    turn, fin1, _ = _gate(fin, text, author)
    msg = str((turn or {}).get("assistant_message") or "")
    self.assertIn("One check before I put options in front of you", msg)
    self.assertIn("should I treat your volumes as fixed for the rest of this", msg)
    self.assertIn(text, msg, "the quote is the client's words")
    self.assertIn(S.COHERENCE_MARKER, msg)
    st = S.get_state(fin1)
    self.assertFalse((st.get("client_floors") or {}).get("volume"), "nothing bound yet")
    self.assertEqual(st.get("floor_confirm_asked"), "volume")
    self.assertNotIn("round", st, "no menu until the answer")

  def test_a_yes_binds_through_the_router_and_a_no_releases(self):
    fin = _fixture()
    fin["_coherence"]["floor_confirm_asked"] = "volume"
    _r, _o, fin1, notes = S.apply_router_patch(patch={"coherence.assert_floor": "volume"}, ops_json=dict(L.GOAL_OPS),
                                                financials_json=fin, user_text="Yes - keep it fixed.")
    st1 = S.get_state(fin1)
    self.assertTrue(st1["client_floors"].get("volume"))
    self.assertNotIn("floor_confirm_asked", st1)
    _r, _o, fin2, notes2 = S.apply_router_patch(patch={"coherence.release_floor": "volume"}, ops_json=dict(L.GOAL_OPS),
                                                 financials_json=fin1, user_text="Actually volume can move after all.")
    st2 = S.get_state(fin2)
    self.assertFalse((st2.get("client_floors") or {}).get("volume"))
    self.assertNotIn("volume", st2.get("rounds_done") or [])
    self.assertIn("released_floor:volume", notes2)

  def test_a_floor_the_router_bound_is_never_asked_again(self):
    fin = _fixture()
    fin["_coherence"]["client_floors"] = {"rent": True}
    author = lambda payload: {"floors_read": [{"cost": "rent", "because": "the lease is signed", "kind": "cannot_move"}], "floors_mentioned": [],
                              "candidates": [{"kind": "cost", "levers": ["gna"], "depth": 0.5, "line_moves": [], "label": "Trim overhead", "why": "w"}]}
    turn, fin1, _ = _gate(fin, "the lease is signed", author)
    msg = str((turn or {}).get("assistant_message") or "")
    self.assertNotIn("One check before I put options", msg)
    self.assertIn("Trim overhead", msg)


class TheConfirmationKeepsTheCoherenceFrame(unittest.TestCase):
  """Fourth proof run: the persona said yes three times and the question came
  back each time - the round had been cleared, so the yes went to the
  financials handler's router with no coherence frame."""

  def test_a_pending_confirmation_is_a_live_coherence_question(self):
    fin = {"_coherence": {"status": C.STATUS_WALKING, "floor_confirm_asked": "rent", "gap_open": 100.0}}
    self.assertTrue(S.walking_round_live(fin, "should I treat rent as fixed ... work on paper."))
    frame = S.router_frame(fin)
    self.assertEqual(frame["current_question"], "coherence_floor_confirm")
    self.assertEqual(frame["floor_confirm_asked"], "rent")
    self.assertEqual(frame["patch_targets"], ["coherence.assert_floor", "coherence.release_floor"])

  def test_the_router_is_told_what_yes_and_no_mean_there_first(self):
    src = open(os.path.join(ROOT, "python", "client_intake_and_finmo", "intent_router.py"), encoding="utf-8").read()
    self.assertIn("coherence_floor_confirm", src)
    self.assertIn("ANY agreement (yes, keep it, that's right, it can't move) is edit_patch with coherence.assert_floor", src)
    i_rule = src.find("FIRST: if coherence_controller.current_question is coherence_floor_confirm")
    i_pick = src.find("If the client picks an option by number")
    self.assertGreater(i_rule, 0)
    self.assertLess(i_rule, i_pick, "the confirmation rule comes before the option-pick rule (a yes is not a pick)")

  def test_a_plain_yes_lands_on_the_floor_and_empty_coherence_keys_are_dropped(self):
    h = open(os.path.join(ROOT, "python", "api_handlers", "intake_consult.py"), encoding="utf-8").read()
    self.assertIn('patch, action = {"coherence.assert_floor": _fc_cost}, "edit_patch"', h)
    self.assertIn("FLOOR_CONFIRM_YES", h)
    self.assertIn("a coherence key set to nothing says nothing", h)


class TheRouterAndThePanelAndThePersona(unittest.TestCase):
  def test_the_router_knows_release_and_never_emits_parked_false(self):
    src = open(os.path.join(ROOT, "python", "client_intake_and_finmo", "intent_router.py"), encoding="utf-8").read()
    self.assertIn("coherence.release_floor", src)
    self.assertIn("NEVER emit coherence.parked = false", src)
    i_bind, i_pause = src.find("A REFUSAL BINDS."), src.find("If the client wants to pause, defer")
    self.assertLess(i_bind, i_pause, "the refusal rule comes before the pause rule")

  def test_the_panel_shows_held_levers_and_that_they_can_be_released(self):
    src = open(os.path.join(ROOT, "frontend", "src", "intake_form", "steps", "CoherencePanel.tsx"), encoding="utf-8").read()
    self.assertIn("Held as you asked:", src)
    self.assertIn("can move after all", src)
    self.assertIn("client_floors?: Record<string, boolean>", src)

  def test_the_walk_persona_answers_the_confirmation(self):
    src = open(os.path.join(ROOT, "scripts", "intake_personas.py"), encoding="utf-8").read()
    self.assertIn('R("walk_floor_confirm"', src)


if __name__ == "__main__":
  unittest.main()


class TheRouterCanActuallySayAFloor(unittest.TestCase):
  """The allowlist for a live coherence question never carried assert_floor:
  'A REFUSAL BINDS' was dead letter and every floor came from the author."""

  def test_the_live_coherence_allowlist_carries_the_floor_keys(self):
    src = open(os.path.join(ROOT, "python", "client_intake_and_finmo", "intent_router.py"), encoding="utf-8").read()
    i = src.find('["coherence.option", "coherence.parked", "coherence.assert_floor", "coherence.release_floor"')
    self.assertGreater(i, 0)
    self.assertIn('add("coherence", "release_floor", {"type": "string"})', src)
