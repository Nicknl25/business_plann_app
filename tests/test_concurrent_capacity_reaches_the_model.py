"""The concurrent-load mode the model has always had and the intake never reached.

MEASURED, 2026-09-13: of 3,127 contract-cadence product rows in the store,
**zero** carry `concurrent_capacity_units` or `annual_turns_per_year` - the two
fields `financials_year1._cadence_authoritative_field_names` names as
authoritative for that cadence - while 2,673 carry `units_per_week_capacity`,
which is not a meaningful quantity on a per-contract row.

That is why Thackeray & Nunes (53a7603f) went wrong. The client said "twenty-five
or thirty kitchens moving at any one time ... over a year that comes out around
540 of them": one concurrent load and one annual throughput. The router had only
the week/period pair to put them in, so it split the two ends of the concurrent
RANGE across two different fields - 30 as a weekly rate, 25 as a period capacity.
Every net downstream (the pair refusal, the row-less drop, the ask, the readback)
exists to catch what that missing field causes.

THE TRAP THIS FILE ALSO GUARDS: `_quarter_capacity_from_ops_product` converts
every capacity to a quarter - period x periods / 4, weekly x 13, monthly x 3 -
but returned the concurrent count RAW. Thirty in progress would have read as
thirty a quarter: 120 a year where the client said 540. It never fired because
nothing could write the field; adding the write is precisely what makes that
branch reachable, so it is converted here in the same change.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))


class TheConcurrentBranchConvertsToAQuarter(unittest.TestCase):
  def setUp(self):
    from client_intake_and_finmo.finmo_bridge import (  # type: ignore
      _quarter_capacity_from_ops_product,
    )

    self.q = _quarter_capacity_from_ops_product

  def _cap(self, **row):
    return self.q(product=row, ops_json={})

  def test_thackeray_concurrent_times_turns(self):
    """30 kitchens in progress, each slot turning over 18 times a year, is 540
    a year - the client's own figure - and so 135 a quarter."""
    self.assertAlmostEqual(
      self._cap(concurrent_capacity_units=30, annual_turns_per_year=18), 135.0, 6)

  def test_the_concurrent_route_agrees_with_the_throughput_route(self):
    """The identity that makes this safe: the same business described either
    way must price the same. 30 x 18 turns == 540 a year."""
    via_concurrent = self._cap(concurrent_capacity_units=30, annual_turns_per_year=18)
    via_throughput = self._cap(units_per_period_capacity=540, operating_periods_per_year=1)
    self.assertAlmostEqual(via_concurrent, via_throughput, 6)

  def test_a_concurrent_count_alone_is_not_asserted_as_throughput(self):
    """Without turns there is no honest conversion. A concurrent count is not
    a rate, so it must not be returned as one - the raw return was the defect."""
    self.assertEqual(self._cap(concurrent_capacity_units=30), 0.0)

  def test_the_conversion_is_the_arithmetic_not_a_proxy_for_it(self):
    """Asserting "the answer is not 30" looked like a test of the raw-return
    bug and was not one: at 4 turns a year, 30 slots really do finish 30 jobs
    a quarter, so the correct answer IS 30 and this pin failed on correct code
    the first time it ran. A coincidence between the right answer and the wrong
    one is not something to test around - assert the arithmetic itself.
    """
    for turns in (4, 12, 18, 52):
      got = self._cap(concurrent_capacity_units=30, annual_turns_per_year=turns)
      self.assertAlmostEqual(got, 30.0 * turns / 4.0, 6,
                             "wrong conversion at turns=%s" % turns)

  def test_the_other_branches_are_unchanged(self):
    """Forward-only: the 3,127 existing rows keep computing exactly as before."""
    self.assertAlmostEqual(self._cap(units_per_week_capacity=45), 585.0, 6)
    self.assertAlmostEqual(self._cap(units_per_month_capacity=60), 180.0, 6)
    self.assertAlmostEqual(
      self._cap(units_per_period_capacity=45, operating_periods_per_year=12), 135.0, 6)

  def test_the_period_route_still_wins_when_both_are_present(self):
    """An existing row that carries both must not change shape under us."""
    self.assertAlmostEqual(
      self._cap(units_per_period_capacity=540, operating_periods_per_year=1,
                concurrent_capacity_units=30, annual_turns_per_year=18),
      135.0, 6)


class TheIntakeCanReachTheseFields(unittest.TestCase):
  """A field the router cannot emit is a field the intake can never record -
  which is the whole reason this mode sat unused in 3,127 rows."""

  def test_the_router_schema_carries_the_pair(self):
    src = (ROOT / "python" / "client_intake_and_finmo" / "intent_router.py").read_text(
      encoding="utf-8-sig")
    for field in ("concurrent_capacity_units", "annual_turns_per_year"):
      self.assertIn('"%s": {"type": "number"}' % field, src,
                    "%s is not in the router's ops value schema" % field)
      self.assertIn('      "%s",' % field, src,
                    "%s is not in the router's allowed ops fields" % field)

  def test_the_router_is_told_which_kind_of_capacity_it_is(self):
    src = (ROOT / "python" / "client_intake_and_finmo" / "intent_router.py").read_text(
      encoding="utf-8-sig")
    self.assertIn("CONCURRENT LOAD", src,
                  "the schema allows the field but nothing tells the router when "
                  "to use it - the field would stay unwritten exactly as before")
    self.assertIn("A RANGE IS ONE MEASUREMENT", src,
                  "'twenty-five or thirty' split across two fields is the defect; "
                  "the rule against it must be stated")

  def test_they_land_on_the_product_row_like_any_driver(self):
    src = (ROOT / "python" / "api_handlers" / "intake_consult.py").read_text(
      encoding="utf-8-sig")
    i = src.index("_driver_write = field in (")
    block = src[i:i + 900]
    for field in ("concurrent_capacity_units", "annual_turns_per_year"):
      self.assertIn(field, block,
                    "%s is not a driver write, so it would be written flat and "
                    "never reach the product row" % field)


if __name__ == "__main__":
  unittest.main(verbosity=2)
