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



class TheConcurrentNamesFoldIntoTheSlotThatMeansThem(unittest.TestCase):
  """RESTORED 2026-09-18 on Nick's ruling, reversing e47c93bc.

  This class pinned a second home: concurrent_capacity_units and
  annual_turns_per_year kept their own keys and the period triple stayed empty.
  The arithmetic was equal either way; the cost was that EVERY OTHER COMPONENT
  still spoke the canonical vocabulary. The ops finalize re-author - unchanged
  since before 09-12 - must emit units_per_period_capacity and
  operating_periods_per_year, found them empty, and refilled them from the
  conversation: Harlow Street Cycles d866978b, killed 2026-09-16, recorded a
  shop doing 25 repairs a week as able to do 150.

  financials_year1 renames the canonical triple for cadence "contract" -
  concurrent_capacity_units IS units_per_period_capacity, annual_turns_per_year
  IS operating_periods_per_year. One slot, two vocabularies. The alias folds in
  and does not survive beside it.
  """

  def setUp(self):
    from api_handlers.intake_consult import (  # type: ignore
      _normalize_ops_capacity_compat,
    )

    self.norm = _normalize_ops_capacity_compat

  def _row(self, cadence="contract", **kw):
    row = {"unit_cadence": cadence, "product_name": "countertops"}
    row.update(kw)
    out = self.norm({"lob_models": [{"products": [row]}]})
    return out["lob_models"][0]["products"][0]

  def test_the_alias_lands_in_the_canonical_slot(self):
    r = self._row(concurrent_capacity_units=30, annual_turns_per_year=18)
    self.assertEqual(r.get("units_per_period_capacity"), 30)
    self.assertEqual(r.get("operating_periods_per_year"), 18)

  def test_no_second_home_survives(self):
    r = self._row(concurrent_capacity_units=30, annual_turns_per_year=18)
    self.assertNotIn("concurrent_capacity_units", r)
    self.assertNotIn("annual_turns_per_year", r)

  def test_both_shapes_still_price_the_same(self):
    """The arithmetic the fold existed to protect still holds."""
    from client_intake_and_finmo.finmo_bridge import (  # type: ignore
      _quarter_capacity_from_ops_product,
    )

    folded = self._row(concurrent_capacity_units=30, annual_turns_per_year=18)
    period = self._row(units_per_period_capacity=30, operating_periods_per_year=18)
    self.assertAlmostEqual(
      _quarter_capacity_from_ops_product(product=folded, ops_json={}),
      _quarter_capacity_from_ops_product(product=period, ops_json={}), 6)

  def test_the_figure_she_said_this_turn_wins_a_disagreement(self):
    """One slot read two ways. The alias is the router's reading of the words she
    said THIS turn; the value already in the slot came from an earlier turn or a
    restatement. Keeping the old one would discard what she just said."""
    r = self._row(concurrent_capacity_units=30, units_per_period_capacity=540,
                  annual_turns_per_year=18)
    self.assertEqual(r.get("units_per_period_capacity"), 30)
    self.assertNotIn("concurrent_capacity_units", r)

  def test_a_rate_row_never_takes_a_concurrent_count(self):
    """The fold is the contract cadence's rename. On a weekly row the period slot
    is a RATE, so a concurrent count there would be a different quantity - it is
    dropped rather than folded. Better no figure than one meaning something else."""
    r = self._row(cadence="weekly", concurrent_capacity_units=8)
    self.assertNotIn("concurrent_capacity_units", r)
    self.assertIsNone(r.get("units_per_period_capacity"))

  def test_harlow_the_killing_shape(self):
    """Her own figures: six on stands at once, contract cadence, nothing else."""
    r = self._row(concurrent_capacity_units=6, unit_price=80)
    self.assertEqual(r.get("units_per_period_capacity"), 6)
    self.assertIsNone(r.get("operating_periods_per_year"),
                      "her annual count must never reach the periods slot")
    self.assertNotEqual(r.get("units_per_week_capacity"), 150.0)
    self.assertIsNone(r.get("units_per_week_capacity"),
                      "with no turns there is no honest weekly rate to state")


class AConcurrentRowWithNoTurnsIsStillAsked(unittest.TestCase):
  """The silent zero, in the folded shape (2026-09-18).

  df405289's finding stands and is the reason this ask exists: a concurrent
  capacity with no turns has no honest conversion, the bridge returns 0.0, and
  the line builds at Capacity x Price x Utilization = 0 - a whole revenue line
  silently worth nothing. The fold does not change that; it changes only WHERE
  the pair lives. On a contract row the concurrent load IS
  units_per_period_capacity and the turns ARE operating_periods_per_year, so
  the ask reads those. Reading the alias keys would mean it could never fire
  again, because the normaliser folds them away.

  Harlow Street Cycles is exactly this row: six on stands at once, no turns.
  The app now asks her how long a repair takes instead of inventing 150.
  """

  def setUp(self):
    from api_handlers.intake_consult import (  # type: ignore
      _normalize_ops_capacity_compat,
    )
    from client_intake_and_finmo.intake_coherence.section import (  # type: ignore
      concurrent_turns_hold_question,
    )

    self.norm = _normalize_ops_capacity_compat
    self.ask = concurrent_turns_hold_question

  def _ops(self, **kw):
    row = {"unit_cadence": "contract", "product_name": "countertops"}
    row.update(kw)
    return self.norm({"lob_models": [{"products": [row]}]})

  def _row(self, **kw):
    return self._ops(**kw)["lob_models"][0]["products"][0]

  def test_the_figure_is_kept_in_the_slot_that_means_it(self):
    r = self._row(concurrent_capacity_units=5)
    self.assertEqual(r.get("units_per_period_capacity"), 5,
                     "the client's figure was thrown away")
    self.assertIsNone(r.get("operating_periods_per_year"),
                      "turns were asserted that the client never gave")

  def test_no_weekly_rate_is_invented_without_turns(self):
    """150 repairs a week for a shop doing 25 came from exactly this gap."""
    r = self._row(concurrent_capacity_units=5)
    self.assertIsNone(r.get("units_per_week_capacity"))

  def test_nothing_is_refused(self):
    r = self._row(concurrent_capacity_units=5)
    self.assertFalse(r.get("_capacity_pair_refused"))

  def test_the_incomplete_pair_asks(self):
    q = self.ask(self._ops(concurrent_capacity_units=5))
    self.assertTrue(q)
    self.assertIn("5", q)
    for raw in ("units_per_period_capacity", "operating_periods_per_year",
                "concurrent_capacity_units", "annual_turns_per_year"):
      self.assertNotIn(raw, q, "a raw field name reached the client")

  def test_a_complete_pair_is_not_asked_about(self):
    self.assertIsNone(
      self.ask(self._ops(concurrent_capacity_units=30, annual_turns_per_year=18)))

  def test_a_rate_row_is_never_asked_this(self):
    """The question belongs to the contract cadence; a weekly row is not it."""
    self.assertIsNone(
      self.ask(self._ops(unit_cadence="weekly", units_per_week_capacity=40)))
