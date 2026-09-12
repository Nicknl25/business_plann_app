"""An open payroll disagreement keeps the intake open (Nick 2026-09-11, Option B).

"An open payroll disagreement keeps the intake open until the client changes
a wage, changes the pool, or says use the figure on file." The old shape -
ask once, then carry on with the figure on file - let the client's own
number disappear at submit because they did not read carefully: "the plug
with a disclosure attached". The same rule applies to the owner-pay conflict
hold, which had the same shape.

Fixture: the replay gate's I02 roster - named 34,000 + 37,000, rest-of-team
62,000, so 133,000 on file; the client states a total of 120,000.
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)
_EXTRA = os.path.join(ROOT, "python", "client_intake_and_finmo")
if _EXTRA not in sys.path:
  sys.path.append(_EXTRA)

import api_handlers.intake_consult as IC  # noqa: E402
from client_intake_and_finmo.intake_coherence import section as S  # noqa: E402

PAYROLL_HOLD = {"_payroll_fold_hold": {"unapplied": -13000.0}, "current_payroll": 133000.0}
SPOKEN = {"_payroll_fold_hold_spoken": {"unapplied": -13000.0, "turns": 1, "fresh": False,
                                        "stated": 120000.0}}
OWNER_HOLD = {"_owner_wage_conflict_hold": {"kept": 48000.0, "other": 34000.0,
                                            "human": "delia rennick"}}
ASKED = {"_owner_wage_hold_asked": {"kept": 48000.0, "other": 34000.0}}


def _people(delia=48000.0, rosalie=37000.0):
  return {"people": [
    {"full_name": "Delia Rennick", "role_title": "Owner / Crew Lead", "annual_wage": delia},
    {"full_name": "Rosalie Fenn", "role_title": "Crew Lead", "annual_wage": rosalie},
  ], "rest_of_team_payroll_year1": 62000.0}


def _gate(fin):
  return S.gate_and_turn(ops_json={}, people_json=_people(), market_json={},
                         marketing_model_json={}, financials_json=dict(fin),
                         financials_year1_json={})


class TheQuestionTests(unittest.TestCase):
  def test_it_names_both_figures_and_asks(self):
    text = S.payroll_disagreement_text(133000.0, -13000.0)
    for part in ("$133,000", "$120,000", "$13,000", "?", "rest-of-team", "on file"):
      self.assertIn(part, text)
    self.assertNotIn("otherwise the plan runs", text)

  def test_a_stated_total_above_the_roster_is_asked_too(self):
    text = S.payroll_disagreement_text(282042.5, 17957.5)
    for part in ("$282,042.50", "$300,000", "$17,957.50", "?"):
      self.assertIn(part, text)

  def test_the_receipt_is_the_same_question(self):
    self.assertEqual(IC._payroll_hold_receipt_text(landed=133000.0, unapplied=-13000.0),
                     S.payroll_disagreement_text(133000.0, -13000.0))
    self.assertTrue(IC._payroll_hold_receipt_text(landed=1.0, unapplied=-1.0)
                    .startswith(IC._PAYROLL_HOLD_RECEIPT_LEADS))

  def test_the_asked_marker_key_is_one_key(self):
    self.assertEqual(IC._OWNER_HOLD_ASKED_KEY, S.OWNER_HOLD_ASKED_KEY)


class TheGateKeepsTheIntakeOpenTests(unittest.TestCase):
  def test_an_open_payroll_hold_blocks_completion_and_is_kept(self):
    turn, fin, suffix = _gate(PAYROLL_HOLD)
    self.assertIsNotNone(turn, "the completion gate let the intake close over an open question")
    msg = turn["assistant_message"]
    self.assertIn("$120,000", msg)
    self.assertIn("$133,000", msg)
    self.assertEqual(fin.get("_payroll_fold_hold"), {"unapplied": -13000.0})
    self.assertEqual(suffix, "")

  def test_an_open_owner_hold_blocks_completion_and_is_marked_asked(self):
    turn, fin, _ = _gate(OWNER_HOLD)
    self.assertIsNotNone(turn)
    self.assertIn("$48,000", turn["assistant_message"])
    self.assertIn("$34,000", turn["assistant_message"])
    self.assertIn("_owner_wage_conflict_hold", fin)
    self.assertIsInstance(fin.get(S.OWNER_HOLD_ASKED_KEY), dict)

  def test_both_open_both_asked(self):
    turn, _fin, _ = _gate({**PAYROLL_HOLD, **OWNER_HOLD})
    self.assertIn("$120,000", turn["assistant_message"])
    self.assertIn("$34,000", turn["assistant_message"])

  def test_no_hold_means_no_hold_question(self):
    self.assertEqual(S.open_hold_questions({"current_payroll": 133000.0}), [])

  def test_the_gate_never_drops_either_hold(self):
    src = inspect.getsource(S)
    self.assertNotIn('pop("_payroll_fold_hold"', src)
    self.assertNotIn('pop("_owner_wage_conflict_hold"', src)


class PayrollHoldAnswersTests(unittest.TestCase):
  def _follow(self, message, patch=None, fin=None):
    return IC._payroll_hold_followup(dict(fin or {**PAYROLL_HOLD, **SPOKEN}),
                                     user_message=message, patch=patch)

  def test_use_the_figure_on_file_clears(self):
    for message in ("Use the figure on file.", "Just use the numbers you have.",
                    "Go with what you have.", "Use $133,000.", "133k is right"):
      fin, text = self._follow(message)
      self.assertNotIn("_payroll_fold_hold", fin, message)
      self.assertIn("$133,000", text)

  def test_changing_the_pool_or_a_wage_clears(self):
    for key in ("people.rest_of_team_payroll_year1", "people.people"):
      fin, _ = self._follow("Here you go.", patch={key: 1})
      self.assertNotIn("_payroll_fold_hold", fin, key)

  def test_anything_else_keeps_it_open_and_asks_again(self):
    fin, text = self._follow("Okay.")
    self.assertIn("_payroll_fold_hold", fin)
    self.assertIn("$120,000", text)
    self.assertIn("?", text)

  def test_restating_the_disputed_total_is_not_using_the_figure_on_file(self):
    fin, _ = self._follow("Use $120,000.")
    self.assertIn("_payroll_fold_hold", fin)

  def test_a_question_about_the_figure_is_not_an_answer(self):
    fin, _ = self._follow("Is 133,000 what you have?")
    self.assertIn("_payroll_fold_hold", fin)


class OwnerHoldAnswersTests(unittest.TestCase):
  def _resolve(self, message, fin, people=None):
    return IC._resolve_owner_wage_hold(dict(fin), user_message=message,
                                       people_json=people or _people())

  def test_before_it_is_asked_a_passing_remark_does_not_clear_it(self):
    fin = self._resolve("That's fine.", OWNER_HOLD)
    self.assertIn("_owner_wage_conflict_hold", fin)

  def test_once_asked_confirming_the_figure_on_file_clears(self):
    for message in ("That's fine.", "Use the figure on file.", "48,000 is right."):
      fin = self._resolve(message, {**OWNER_HOLD, **ASKED})
      self.assertNotIn("_owner_wage_conflict_hold", fin, message)
      self.assertNotIn(IC._OWNER_HOLD_ASKED_KEY, fin)

  def test_the_owner_giving_a_different_wage_clears(self):
    fin = self._resolve("It's 34,000.", OWNER_HOLD, people=_people(delia=34000.0))
    self.assertNotIn("_owner_wage_conflict_hold", fin)

  def test_someone_else_s_wage_is_not_an_answer(self):
    fin = self._resolve("Rosalie makes 40,000.", {**OWNER_HOLD, **ASKED},
                        people=_people(rosalie=40000.0))
    self.assertIn("_owner_wage_conflict_hold", fin)

  def test_a_question_is_not_an_answer(self):
    fin = self._resolve("Is 48,000 what you have?", {**OWNER_HOLD, **ASKED})
    self.assertIn("_owner_wage_conflict_hold", fin)

  def test_every_hold_reader_call_passes_the_people(self):
    """The owner answer is read from the roster - a reader call without
    people_json could never see the owner change their wage."""
    src = inspect.getsource(IC)
    calls = src.split("_payroll_hold_followup(")[2:]   # [0] precedes the def, [1] is the def
    self.assertGreaterEqual(len(calls), 4)
    for call in calls:
      self.assertIn("people_json=", call[:400])


class CompletedTurnTests(unittest.TestCase):
  def test_the_completed_turn_checks_for_open_holds_before_completing(self):
    src = inspect.getsource(IC._run_financials_turn_and_sync_inner)
    guard = src.find("_open_intake_holds(next_financials, never_traded=")
    complete = src.find("_build_financials_completion_turn(acknowledgement=_receipt)")
    self.assertGreater(guard, 0)
    self.assertLess(guard, complete)


if __name__ == "__main__":
  unittest.main()
