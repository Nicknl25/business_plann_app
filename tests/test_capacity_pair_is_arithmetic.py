"""units_per_week_capacity and units_per_period_capacity are conversions of one
another. THE REFUSALS WERE REMOVED (Nick 2026-09-15, reset): their tests are gone;
what stays pins that consistent pairs, fills and the readback still work.

Alderman & Fitch Boatworks a88dae18 (2026-09-13). The client said: "The shed
holds four hulls at once, and a build runs anywhere from eight months to a year
and a half. In practice we finish about six a year. Nine would be us flat out."

Three clear numbers. What landed was units_per_week_capacity=4 AND
units_per_period_capacity=4 on a per-contract cadence - four hulls a WEEK, 208
a year, for a yard that builds six. Door C diagnosed it exactly right and
recorded an opinion; the number went in anyway.

week = period x periods_per_year / 52, so the two can only hold the same value
when the period IS a week. That is arithmetic, not judgment, and it is checked
before anything else runs.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))


def _normalize(unit: dict) -> dict:
  from api_handlers.intake_consult import _normalize_ops_capacity_compat  # type: ignore

  ops = {"lob_models": [{"products": [dict(unit)]}]}
  _normalize_ops_capacity_compat(ops)
  return ops["lob_models"][0]["products"][0]


class ConsistentPairsSurvive(unittest.TestCase):
  """The refusal must not become a blunt instrument - a pair that IS a correct
  conversion has to stand, or every weekly business breaks."""

  def test_a_weekly_cadence_may_hold_equal_values(self):
    """When the period IS a week, week == period is correct."""
    out = _normalize({"unit_cadence": "weekly", "operating_periods_per_year": 52,
                      "units_per_week_capacity": 9, "units_per_period_capacity": 9})
    self.assertEqual(out["units_per_week_capacity"], 9)
    self.assertEqual(out["units_per_period_capacity"], 9)
    self.assertNotIn("_capacity_pair_refused", out)

  def test_a_correct_monthly_conversion_stands(self):
    """13 a month is 3 a week; that pair is arithmetic, not a collision."""
    period, periods = 13.0, 12.0
    out = _normalize({"unit_cadence": "monthly", "operating_periods_per_year": periods,
                      "units_per_week_capacity": period * periods / 52.0,
                      "units_per_period_capacity": period})
    self.assertIsNotNone(out["units_per_week_capacity"])
    self.assertNotIn("_capacity_pair_refused", out)

  def test_one_value_alone_is_still_converted(self):
    """The fill path is untouched - only a disagreeing PAIR is refused."""
    out = _normalize({"unit_cadence": "annual", "operating_periods_per_year": 1,
                      "units_per_period_capacity": 6, "units_per_week_capacity": None})
    self.assertAlmostEqual(out["units_per_week_capacity"], 6 * 1 / 52.0, places=6)
    self.assertEqual(out["units_per_period_capacity"], 6)
    self.assertNotIn("_capacity_pair_refused", out)

  def test_an_empty_unit_is_left_alone(self):
    out = _normalize({"unit_cadence": "contract"})
    self.assertNotIn("_capacity_pair_refused", out)




class TheReadbackShowsTheCollision(unittest.TestCase):
  """Ruling 2: read the capture back in terms the owner can check.

  Alderman & Fitch were shown "(Noted: weekly capacity -> 4; capacity -> 4.)"
  That is field bookkeeping. It hides that 4 a week is 208 hulls a year for a
  yard that builds six, and that the two fields cannot both be 4. Carrying the
  annual equivalent puts both readings in the SAME unit - the same door the
  monthly-money twin goes through, and for the same reason.
  """

  def _fmt(self, path, value, periods=None):
    from client_intake_and_finmo.capture_receipt import _fmt  # type: ignore

    return _fmt(path, value, periods or {}).replace("→", "->")

  def test_a_weekly_capacity_is_read_back_with_its_year(self):
    out = self._fmt("ops.lob_models[0].products[0].units_per_week_capacity", 4.0)
    self.assertIn("208 a year", out,
                  "the client cannot check 'weekly capacity -> 4' against 'we build six a year'")

  def test_a_period_capacity_is_read_back_with_its_year_when_the_cadence_is_known(self):
    out = self._fmt("ops.lob_models[0].products[0].units_per_period_capacity", 6.0,
                    {"ops.lob_models[0].products[0]": 1.0})
    self.assertIn("6", out)

  def test_the_monthly_money_twin_is_untouched(self):
    """The precedent this follows must keep working."""
    out = self._fmt("financials.monthly_rent_expense", 2400.0)
    self.assertIn("$28,800 a year", out)

  def test_a_plain_count_gains_nothing(self):
    """Only capacity and monthly money carry a twin - not every number."""
    out = self._fmt("people.current_num_employees", 33.0)
    self.assertNotIn("a year", out)




class RoundingIsNotACollision(unittest.TestCase):
  """Real clients round. "40 a week, about 2,000 a year" is 4% apart and BOTH
  are facts they stated - a 1e-6 tolerance threw both away (mini, 2026-09-13).
  Only a gap no rounding explains is impossible."""

  def test_a_client_rounding_survives(self):
    out = _normalize({"unit_cadence": "annual", "operating_periods_per_year": 1,
                      "units_per_week_capacity": 40, "units_per_period_capacity": 2000})
    self.assertEqual(out["units_per_week_capacity"], 40,
                     "a 4% rounding gap threw away two figures the client stated")
    self.assertEqual(out["units_per_period_capacity"], 2000)
    self.assertNotIn("_capacity_pair_refused", out)





class TheRefusalOpensAHold(unittest.TestCase):
  """A refused pair must ASK, not just leave the field empty.

  Without a consumer the fields simply read unanswered, the stage re-asks
  capacity generically, the router writes the weekly field again on a
  per-contract row, the fill rule mints the twin and the refusal fires again -
  a loop (mini, 2026-09-13).
  """

  def _ops(self, asked=None):
    refused = {"units_per_week_capacity": 4, "units_per_period_capacity": 4, "cadence": "contract"}
    if asked is not None:
      refused["asked"] = asked
    return {"lob_models": [{"products": [{"unit_description": "A custom boat build",
                                          "_capacity_pair_refused": refused}]}]}

  def test_a_refused_pair_is_an_open_hold(self):
    from client_intake_and_finmo.intake_coherence.section import open_hold_questions  # type: ignore

    holds = open_hold_questions({}, ops_json=self._ops())
    self.assertEqual([k for k, _q in holds], ["capacity"])
    question = holds[0][1]
    self.assertIn("4", question)
    self.assertIn("at any one time", question, "the question must offer both readings")
    self.assertNotIn("units_per", question, "field names mean nothing to a client")

  def test_it_is_let_go_after_two_asks_so_nothing_loops(self):
    from client_intake_and_finmo.intake_coherence.section import open_hold_questions  # type: ignore

    self.assertEqual(open_hold_questions({}, ops_json=self._ops(asked=2)), [])

  def test_no_refusal_means_no_hold(self):
    from client_intake_and_finmo.intake_coherence.section import open_hold_questions  # type: ignore

    self.assertEqual(open_hold_questions({}, ops_json={"lob_models": [{"products": [{}]}]}), [])


class APerContractRowHasNoWeeklyRate(unittest.TestCase):
  """THE SOURCE of the Alderman & Fitch bug (Nick 2026-09-13).

  "The shed holds four hulls at once" is a concurrency. The router wrote it to
  units_per_week_capacity on a row whose cadence is per CONTRACT - four hulls a
  week, 208 a year, for a yard that builds six. Which reading the client meant
  is intent and the intake asks; that the row HAS no weekly rate is structure,
  and structure is refused in code before anything else runs.
  """

  def test_a_weekly_row_keeps_its_weekly_capacity(self):
    """The refusal must not become a blunt instrument."""
    out = _normalize({"unit_cadence": "weekly", "operating_periods_per_year": 52,
                      "units_per_week_capacity": 9})
    self.assertEqual(out["units_per_week_capacity"], 9)
    self.assertNotIn("_capacity_pair_refused", out)

  def test_the_converted_fill_still_stands(self):
    """week = period x periods / 52 is arithmetic, not a claim - it is what
    keeps the legacy reader identical to the canonical one."""
    out = _normalize({"unit_cadence": "annual", "operating_periods_per_year": 1,
                      "units_per_period_capacity": 6})
    self.assertAlmostEqual(out["units_per_week_capacity"], 6 / 52.0, places=6)
    self.assertNotIn("_capacity_pair_refused", out)

  def test_an_unknown_cadence_is_left_alone(self):
    """Refuse what is structurally impossible, not what is merely unknown."""
    out = _normalize({"units_per_week_capacity": 40})
    self.assertEqual(out["units_per_week_capacity"], 40)
    self.assertNotIn("_capacity_pair_refused", out)


class TheRefusalActuallyAsks(unittest.TestCase):
  """The refusal is only half of it without the question.

  Clearing the field and keeping the figure leaves the stage to re-ask capacity
  generically; the router writes the same thing again and the refusal fires
  again - a loop, which is worse than the bug it catches (mini, 2026-09-13).
  The question is asked on the OPS path, which is where ops_json is in scope.
  """

  def _ops(self):
    return {"lob_models": [{"products": [{
      "unit_description": "A full custom wooden boat build",
      "_capacity_pair_refused": {"units_per_week_capacity": 4,
                                 "units_per_period_capacity": None,
                                 "cadence": "contract"}}]}]}

  def test_it_asks_in_the_clients_terms(self):
    from client_intake_and_finmo.intake_coherence.section import (  # type: ignore
      capacity_pair_hold_question,
    )

    q = capacity_pair_hold_question(self._ops())
    self.assertIn("4", q)
    self.assertIn("at any one time", q, "both readings must be offered")
    self.assertNotIn("units_per", q, "field names mean nothing to a client")

  def test_it_is_let_go_after_two_asks(self):
    from client_intake_and_finmo.intake_coherence.section import (  # type: ignore
      capacity_pair_hold_question,
    )
    from api_handlers.intake_consult import _mark_capacity_refusals_asked  # type: ignore

    ops = self._ops()
    self.assertTrue(capacity_pair_hold_question(ops))
    _mark_capacity_refusals_asked(ops)
    self.assertTrue(capacity_pair_hold_question(ops), "a second ask is allowed")
    _mark_capacity_refusals_asked(ops)
    self.assertIsNone(capacity_pair_hold_question(ops),
                      "asked twice and unanswered, it must be let go - nothing loops")

  def test_the_ops_path_is_where_it_is_asked(self):
    """Source-level: the question is raised where ops_json is in scope. Wiring
    it on the financials path is what shipped a NameError on the live path."""
    src = (ROOT / "python" / "api_handlers" / "intake_consult.py").read_text(encoding="utf-8-sig")
    i = src.index('if focus == "ops":')
    body = src[i:i + 4000]
    self.assertIn("capacity_pair_hold_question", body)
    self.assertIn("_mark_capacity_refusals_asked", body)


if __name__ == "__main__":
  unittest.main(verbosity=2)
