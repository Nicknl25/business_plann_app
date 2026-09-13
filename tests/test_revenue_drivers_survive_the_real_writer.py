"""The pin that was missing, and whose absence let a non-fix ship.

The revenue-driver contract compares FINMO's revenue against the Capacity /
Unit Price / Utilization rows in model_input. There were pins on the CHECKER -
they built a model_input by hand and asserted the comparison behaved - and none
on the WRITER. So a fix that changed the source dataclasses and the read side
passed twenty-five green tests, was pushed, and Sorrel & Dunne 691a4763 died
again with byte-identical deltas: the row writer that actually produces those
rows still rounded every driver to 6dp.

These tests build through the REAL writer - FinancialModelInputs
.to_model_input_json() - and read back what a client's workbook would carry.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

#: Sorrel & Dunne: 21,000 cans a week at $1.48, 70% utilisation. The unit price
#: is the whole point - a 6dp round is 3.4e-7 RELATIVE on $1.48, and that rides
#: the entire product.
CAPACITY = 21_000.0 / 7.0 * 91.0          # a quarter of weeks, not a round number
UNIT_PRICE = 1.48
UTILIZATION = 0.7000000003                # derived from a stated revenue; does not divide cleanly


def _inputs_with_one_product(capacity, unit_price, utilization):
  from financial_model_engine.model_inputs import (  # type: ignore
    FinancialModelInputs, FinancialModelQuarter, QuarterRevenueProduct,
    QuarterRevenueProductGroup, RevenueDriverSet,
  )

  model = FinancialModelInputs()
  model.quarters = []
  for index in range(1, model.quarter_count + 1):
    product = QuarterRevenueProduct(
      lob_name="Cold brew", product_name="Canned cold brew",
      revenue_slot_key="cold_brew::canned",
      drivers=RevenueDriverSet(capacity_units=capacity, unit_price=unit_price,
                               utilization=utilization),
    )
    group = QuarterRevenueProductGroup(lob_name="Cold brew", products=[product])
    quarter = FinancialModelQuarter(quarter_index=index, revenue_groups=[group])
    model.quarters.append(quarter)
  return model


def _driver_rows(payload):
  rows = (payload.get("sections") or {}).get("revenue") or []
  return {str(r.get("driver")): r for r in rows if isinstance(r, dict)}


class TheRealWriterKeepsDriverPrecisionTests(unittest.TestCase):
  """model_inputs.py 857-859 - the row writer the contract reads."""

  @classmethod
  def setUpClass(cls):
    cls.model = _inputs_with_one_product(CAPACITY, UNIT_PRICE, UTILIZATION)
    cls.payload = cls.model.to_model_input_json()
    cls.rows = _driver_rows(cls.payload)

  def test_the_three_driver_rows_exist(self):
    for driver in ("Capacity", "Unit Price", "Utilization"):
      self.assertIn(driver, self.rows, f"no {driver} row in sections.revenue")

  def test_a_driver_beyond_six_decimals_survives_the_writer(self):
    """The exact regression: round(0.7000000003, 6) == 0.7, and that lost
    3e-10 relative on every quarter."""
    live = list(self.rows["Utilization"]["values"])[1:]   # [0] is the stub column
    self.assertTrue(live, "no live utilization values")
    for idx, value in enumerate(live, start=1):
      self.assertEqual(value, UTILIZATION,
                       f"Q{idx} utilization was rounded by the writer: {value!r}")

  def test_capacity_and_unit_price_survive_too(self):
    for driver, expected in (("Capacity", CAPACITY), ("Unit Price", UNIT_PRICE)):
      for idx, value in enumerate(list(self.rows[driver]["values"])[1:], start=1):
        self.assertEqual(value, expected, f"Q{idx} {driver} was rounded: {value!r}")

  def test_the_contract_reader_reproduces_the_engine_exactly(self):
    """End to end across the seam that broke: the engine's revenue on one
    side, the contract's reader on the other, no tolerance in between."""
    from client_intake_and_finmo.finmo_bridge import (  # type: ignore
      revenue_live_series_from_model_input,
    )

    live_count = self.model.quarter_count
    series = revenue_live_series_from_model_input(self.payload, live_count=live_count)
    # BOTH sides round the PRODUCT at 6dp - that is the convention and it is
    # symmetric, so the comparison is exact. What must never happen is a side
    # rounding a FACTOR, which is asymmetric and is the whole defect.
    drivers = self.model.quarters[0].revenue_groups[0].products[0].drivers
    expected = round(drivers.revenue, 6)
    self.assertEqual(expected, drivers.to_dict()["revenue"],
                     "the engine persists its revenue at 6dp; this pin must compare that")
    for idx, value in enumerate(series, start=1):
      self.assertEqual(
        value, expected,
        f"Q{idx}: contract reader {value!r} != engine revenue {expected!r}")

  def test_the_contract_itself_passes_on_this_product(self):
    from client_intake_and_finmo import finmo_bridge as fb  # type: ignore

    exact = round(self.model.quarters[0].revenue_groups[0].products[0].drivers.revenue, 6)
    rows = [{"revenue": exact} for _ in range(self.model.quarter_count)]
    fb._enforce_revenue_driver_formula_contract(
      model_input_json=self.payload, quarter_rows_raw=rows)

  def test_products_still_round_at_six_decimals(self):
    """The rule is drivers precise, PRODUCTS rounded. If units stopped
    rounding, the convention has drifted rather than been fixed."""
    drivers = self.model.quarters[0].revenue_groups[0].products[0].drivers
    stored = drivers.to_dict()
    self.assertEqual(stored["units"], round(drivers.units, 6))
    self.assertEqual(stored["revenue"], round(drivers.revenue, 6))
    self.assertEqual(stored["capacity_units"], CAPACITY)
    self.assertEqual(stored["unit_price"], UNIT_PRICE)

  def test_the_controller_product_carries_the_same_numbers(self):
    """Anything consuming products[] must see what the contract compares."""
    product = self.model.quarters[0].revenue_groups[0].products[0]
    payload = product.to_controller_product()
    self.assertEqual(payload["capacity_units"], CAPACITY)
    self.assertEqual(payload["price"], UNIT_PRICE)
    self.assertEqual(payload["utilization"], UTILIZATION)


class UtilizationSnapTests(unittest.TestCase):
  """The one thing full precision could have BROKEN.

  Utilization is derived - stated revenue / (capacity x price) - so a quotient
  that should be exactly 100% lands at 1.0000004. The 6dp round on storage used
  to snap that to 1.0 as a side effect; without it, fail_fast's
  `utilization > 1.0 + 1e-9` starts hard-failing utilization_above_100_percent
  on arithmetic noise, and a different client's build dies on my fix.

  The snap is calibrated to where round(value, 6) used to land, so it restores
  the old boundary rather than relaxing it."""

  def test_the_snap_matches_the_old_rounding_at_every_boundary(self):
    from financial_model_engine.model_inputs import snap_utilization  # type: ignore

    for value in (1.0, 1.0000000000000002, 1.0000004, 1.0000005, 1.0000008,
                  1.000002, 1.05, 1.3, 0.7000000003, 0.5):
      old_passes = round(value, 6) <= 1.0 + 1e-9
      new_passes = snap_utilization(value) <= 1.0 + 1e-9
      self.assertEqual(old_passes, new_passes,
                       f"{value!r} changed the over-capacity verdict: "
                       f"was {old_passes}, now {new_passes}")

  def test_real_over_capacity_still_fails(self):
    from financial_model_engine.model_inputs import snap_utilization  # type: ignore

    for value in (1.05, 1.3, 2.0):
      self.assertEqual(snap_utilization(value), value,
                       "a figure a person would call over 100% must pass through")

  def test_values_away_from_one_are_untouched(self):
    from financial_model_engine.model_inputs import snap_utilization  # type: ignore

    for value in (0.0, 0.5, 0.7000000003, 0.999999, 1.0):
      self.assertEqual(snap_utilization(value), value)

  def test_the_driver_set_snaps_at_construction(self):
    """One door - nothing downstream has to remember."""
    from financial_model_engine.model_inputs import RevenueDriverSet  # type: ignore

    drivers = RevenueDriverSet(capacity_units=100.0, unit_price=2.0, utilization=1.0000004)
    self.assertEqual(drivers.utilization, 1.0)
    self.assertEqual(drivers.to_dict()["utilization"], 1.0)

  def test_the_snap_does_not_reintroduce_rounding_elsewhere(self):
    """It must touch ONLY the band just above 1.0 - not become a 6dp round by
    another door."""
    from financial_model_engine.model_inputs import RevenueDriverSet  # type: ignore

    drivers = RevenueDriverSet(capacity_units=273000.000000123,
                               unit_price=1.4800000007, utilization=0.7000000003)
    self.assertEqual(drivers.utilization, 0.7000000003)
    self.assertEqual(drivers.capacity_units, 273000.000000123)
    self.assertEqual(drivers.unit_price, 1.4800000007)


if __name__ == "__main__":
  unittest.main(verbosity=2)
