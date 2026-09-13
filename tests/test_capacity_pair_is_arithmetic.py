"""units_per_week_capacity and units_per_period_capacity are conversions of
one another, so code refuses a pair that disagrees - no model involved.

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


class TheImpossiblePairIsRefused(unittest.TestCase):
  def test_the_alderman_and_fitch_pair_is_refused(self):
    """The exact shape that killed the run."""
    out = _normalize({
      "unit_cadence": "contract",
      "operating_periods_per_year": None,
      "units_per_week_capacity": 4,
      "units_per_period_capacity": 4,
      "unit_description": "A full custom wooden boat build for a single owner",
    })
    self.assertIsNone(out["units_per_week_capacity"],
                      "four hulls a week stood - 208 a year for a yard that builds six")
    self.assertIsNone(out["units_per_period_capacity"])

  def test_the_refusal_keeps_what_it_refused(self):
    """The client's numbers are not thrown away silently - the refusal records
    both values so the turn can ask which was meant."""
    out = _normalize({"unit_cadence": "contract", "units_per_week_capacity": 4,
                      "units_per_period_capacity": 4})
    refused = out.get("_capacity_pair_refused")
    self.assertIsNotNone(refused, "the refusal left no trace")
    self.assertEqual(refused["units_per_week_capacity"], 4)
    self.assertEqual(refused["units_per_period_capacity"], 4)

  def test_a_pair_that_disagrees_with_a_known_cadence_is_refused(self):
    """12 a month is not 12 a week."""
    out = _normalize({"unit_cadence": "monthly", "operating_periods_per_year": 12,
                      "units_per_week_capacity": 12, "units_per_period_capacity": 12})
    self.assertIsNone(out["units_per_week_capacity"])
    self.assertIsNone(out["units_per_period_capacity"])


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


if __name__ == "__main__":
  unittest.main(verbosity=2)
