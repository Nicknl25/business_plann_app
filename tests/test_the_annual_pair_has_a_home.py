"""26 a year and 34 flat out have a home, and the six stays where it means "at once".

Vasquez-Lindqvist Timber Frames ec2da9c7, 2026-09-13. The client said: six at
once ("that's the building"), around 26 a year, 34 flat out. The store half -
six on the right row, no quarantine - was confirmed by Cowork at 21:14:34. The
annual pair had nowhere to go: Cowork would not call a run ready while "26 a
year" could still be settled into a slot that, on a per-contract row, means how
many AT ONCE.

THE DESTINATION (Cowork ruled it not known-bad and checked the arithmetic):
  ceiling  34 a year -> annual_turns_per_year = 34 / 6   = 5.667
  actual   26 a year -> utilization_rate      = 26 / 34  = 0.7647
  6 x 5.667 x 0.7647 = 26.0 - her stated actual comes back out exactly.

Which figure is the ceiling and which the actual is MEANING, so the router names
it (annual_capacity_units, annual_completed_units). The division is ARITHMETIC,
so code does it, at the row normaliser, and the two names do not survive.

THE HOME IS THE FIELD THAT MEANS "AT ONCE". An alias fold committed earlier the
same night moved concurrent_capacity_units into units_per_period_capacity as
soon as turns were known and deleted the key - so recording the turns would
have evicted the six from the only field that says what she said, failed
Cowork's key-presence check, and let the receipt label read it back as "how
much you can get through in a period". That fold is reversed here, deliberately:
a concurrent row keeps concurrent_capacity_units + annual_turns_per_year, and
the period/week/periods slots stay null. Both readers agree with that shape -
finmo_bridge uses concurrent x annual_turns / 4, financials_year1 resolves
annual_turns before operating_periods.

STANDING (Cowork): concurrent x turns x utilisation never comes out above the
stated ceiling. Utilisation is her headroom between 26 and 34, never past it.

Pins drive the real door in the live order (_apply_scoped_patch, then
_normalize_ops_capacity_compat) and read KEY PRESENCE.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

_LINE = "Custom residential timber frames"


def _ops():
  return {"lob_models": [{"lob_name": "Primary line of business", "products": [
    {"product_name": _LINE, "unit_cadence": "contract"},
    {"product_name": "Commercial timber structures", "unit_cadence": "contract"},
    {"product_name": "Shipped frame kits for builders", "unit_cadence": "contract"},
  ]}]}


class _Turn(unittest.TestCase):
  def setUp(self):
    from api_handlers.intake_consult import (  # type: ignore
      _apply_scoped_patch, _normalize_ops_capacity_compat,
    )

    self.patch = _apply_scoped_patch
    self.norm = _normalize_ops_capacity_compat

  def _turn(self, values, ops=None):
    _b, out, _m, _p, _f, _fu = self.patch(
      {"ops.product_overrides": {_LINE: values}},
      business_facts={}, ops_json=ops if ops is not None else _ops(),
      market_json={}, people_json={}, financials_json={}, fulfillment_json={},
      user_message="")
    out = self.norm(out)
    return out["lob_models"][0]["products"]


class TheAnnualPairLandsInTurnsAndUtilisation(_Turn):
  def test_ceiling_and_actual_become_turns_and_utilisation(self):
    row = self._turn({"concurrent_capacity_units": 6, "annual_capacity_units": 34,
                      "annual_completed_units": 26})[0]
    self.assertIn("concurrent_capacity_units", row, "the six left the field that means at once")
    self.assertEqual(row["concurrent_capacity_units"], 6)
    self.assertIn("annual_turns_per_year", row)
    self.assertAlmostEqual(row["annual_turns_per_year"], 34 / 6, 3)
    self.assertIn("utilization_rate", row)
    self.assertAlmostEqual(row["utilization_rate"], 26 / 34, 3)

  def test_her_stated_actual_comes_back_out_exactly(self):
    row = self._turn({"concurrent_capacity_units": 6, "annual_capacity_units": 34,
                      "annual_completed_units": 26})[0]
    produced = row["concurrent_capacity_units"] * row["annual_turns_per_year"] * row["utilization_rate"]
    self.assertAlmostEqual(produced, 26.0, 2)

  def test_the_product_never_exceeds_her_stated_ceiling(self):
    row = self._turn({"concurrent_capacity_units": 6, "annual_capacity_units": 34,
                      "annual_completed_units": 26})[0]
    ceiling = row["concurrent_capacity_units"] * row["annual_turns_per_year"]
    self.assertLessEqual(ceiling, 34.0 + 1e-6, "capacity above the 34 she said was flat out")

  def test_the_names_the_router_used_do_not_survive(self):
    row = self._turn({"concurrent_capacity_units": 6, "annual_capacity_units": 34,
                      "annual_completed_units": 26})[0]
    self.assertNotIn("annual_capacity_units", row)
    self.assertNotIn("annual_completed_units", row)
    self.assertNotIn("_capacity_pair_refused", row)

  def test_the_throughput_slots_do_not_restate_it(self):
    """One home. The period/week/periods slots do not carry a second copy."""
    row = self._turn({"concurrent_capacity_units": 6, "annual_capacity_units": 34,
                      "annual_completed_units": 26})[0]
    for slot in ("units_per_period_capacity", "units_per_week_capacity",
                 "operating_periods_per_year"):
      self.assertIsNone(row.get(slot), "%s carries a second copy" % slot)

  def test_the_other_lines_are_untouched(self):
    rows = self._turn({"concurrent_capacity_units": 6, "annual_capacity_units": 34,
                       "annual_completed_units": 26})
    for row in rows[1:]:
      for key in ("concurrent_capacity_units", "annual_turns_per_year", "utilization_rate"):
        self.assertNotIn(key, row)


class NothingIsDerivedWithoutWhatItNeeds(_Turn):
  def test_a_ceiling_without_the_concurrent_figure_derives_nothing(self):
    row = self._turn({"annual_capacity_units": 34})[0]
    self.assertNotIn("annual_turns_per_year", row, "turns derived with nothing to divide by")
    self.assertNotIn("utilization_rate", row)

  def test_an_actual_without_a_ceiling_sets_no_utilisation(self):
    row = self._turn({"concurrent_capacity_units": 6, "annual_completed_units": 26})[0]
    self.assertNotIn("utilization_rate", row, "utilisation derived with no ceiling")

  def test_an_actual_above_the_ceiling_is_never_utilisation_above_one(self):
    row = self._turn({"concurrent_capacity_units": 6, "annual_capacity_units": 34,
                      "annual_completed_units": 40})[0]
    util = row.get("utilization_rate")
    self.assertTrue(util is None or util <= 1.0,
                    "utilisation %r - an actual above her own ceiling is a question, "
                    "not headroom" % util)


class TheSixStaysWhereItMeansAtOnce(_Turn):
  """The reversal of the alias fold, pinned on its own."""

  def test_known_turns_do_not_evict_the_concurrent_figure(self):
    row = self._turn({"concurrent_capacity_units": 6, "annual_turns_per_year": 5.2})[0]
    self.assertIn("concurrent_capacity_units", row)
    self.assertEqual(row["concurrent_capacity_units"], 6)
    self.assertIn("annual_turns_per_year", row)
    self.assertIsNone(row.get("units_per_period_capacity"))
    self.assertIsNone(row.get("operating_periods_per_year"))

  def test_the_bridge_prices_the_concurrent_home(self):
    """Not a silent zero: the concurrent branch of the bridge reads this shape."""
    from client_intake_and_finmo.finmo_bridge import (  # type: ignore
      _quarter_capacity_from_ops_product,
    )

    row = self._turn({"concurrent_capacity_units": 6, "annual_capacity_units": 34,
                      "annual_completed_units": 26})[0]
    self.assertAlmostEqual(_quarter_capacity_from_ops_product(product=row, ops_json={}) * 4,
                           34.0, 2)


class TheNewNamesHaveWords(unittest.TestCase):
  """A field needs words before it ships (Nick, 2026-09-13)."""

  def test_neither_new_name_is_spoken_as_a_key(self):
    from api_handlers.intake_consult import (  # type: ignore
      _client_label_for_field, _humanize_field_for_ask,
    )

    for field in ("annual_capacity_units", "annual_completed_units"):
      self.assertTrue(_client_label_for_field(field), "%s has no words" % field)
      said = _humanize_field_for_ask("ops." + field)
      self.assertNotEqual(said, field.replace("_", " "))
      self.assertNotIn("_", said)


if __name__ == "__main__":
  unittest.main(verbosity=2)
