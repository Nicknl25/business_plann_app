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



class TheSixStaysInTheFieldThatMeansAtOnce(unittest.TestCase):
  """REVERSED, deliberately, 2026-09-13.

  This class used to pin a fold: concurrent_capacity_units moved into
  units_per_period_capacity, and annual_turns_per_year into
  operating_periods_per_year, on the reading that financials_year1 aliases
  them - "one slot under two vocabularies". The arithmetic is equal either way.

  The meaning is not. Once turns were known the fold deleted the only field
  that says what the client said, Cowork's key-presence check read it as gone,
  and the receipt label for the period slot would have read six at once back
  as "how much you can get through in a period". A concurrent row now keeps
  concurrent_capacity_units + annual_turns_per_year, and the period triple
  stays empty. Both readers take that shape (finmo_bridge concurrent x turns /
  4; financials_year1 resolves annual_turns first).
  """

  def setUp(self):
    from api_handlers.intake_consult import (  # type: ignore
      _normalize_ops_capacity_compat,
    )

    self.norm = _normalize_ops_capacity_compat

  def _row(self, **kw):
    row = {"unit_cadence": "contract", "product_name": "countertops"}
    row.update(kw)
    out = self.norm({"lob_models": [{"products": [row]}]})
    return out["lob_models"][0]["products"][0]

  def test_known_turns_leave_the_concurrent_figure_in_place(self):
    r = self._row(concurrent_capacity_units=30, annual_turns_per_year=18)
    self.assertIn("concurrent_capacity_units", r)
    self.assertEqual(r["concurrent_capacity_units"], 30)
    self.assertIn("annual_turns_per_year", r)
    self.assertEqual(r["annual_turns_per_year"], 18)

  def test_the_period_triple_carries_no_second_copy(self):
    r = self._row(concurrent_capacity_units=30, annual_turns_per_year=18)
    self.assertIsNone(r.get("units_per_period_capacity"))
    self.assertIsNone(r.get("operating_periods_per_year"))

  def test_both_shapes_still_price_the_same(self):
    """The arithmetic the fold existed to protect still holds."""
    from client_intake_and_finmo.finmo_bridge import (  # type: ignore
      _quarter_capacity_from_ops_product,
    )

    concurrent = self._row(concurrent_capacity_units=30, annual_turns_per_year=18)
    period = self._row(units_per_period_capacity=30, operating_periods_per_year=18)
    self.assertAlmostEqual(
      _quarter_capacity_from_ops_product(product=concurrent, ops_json={}),
      _quarter_capacity_from_ops_product(product=period, ops_json={}), 6)

  def test_a_conflicting_period_never_evicts_the_concurrent_figure(self):
    r = self._row(concurrent_capacity_units=30, units_per_period_capacity=540,
                  annual_turns_per_year=18)
    self.assertIn("concurrent_capacity_units", r)
    self.assertEqual(r["concurrent_capacity_units"], 30)


class AConcurrentRowWithNoTurnsIsAsked(unittest.TestCase):
  """A silent zero is worse than a wrong number, because nothing says why.

  Mini, auditing acea5bb9: with no turns figure there is no honest conversion,
  so the bridge returns 0.0. Zero is safer than a wrong scale but it is not
  safe - the demand-inference path fires only when no driver row matches at
  all, never because a capacity is zero, so the line builds at
  Capacity x Price x Utilization = 0: a whole revenue line silently worth
  nothing. The pair gets completed where it is recoverable - in the
  conversation, from the person who knows.
  """

  def setUp(self):
    from client_intake_and_finmo.intake_coherence.section import (  # type: ignore
      concurrent_turns_hold_question,
    )

    self.q = concurrent_turns_hold_question

  def _ops(self, **prod):
    row = {"product_name": "kitchen countertops", "unit_cadence": "contract"}
    row.update(prod)
    return {"lob_models": [{"products": [row]}]}

  def test_a_concurrent_row_with_no_turns_asks(self):
    q = self.q(self._ops(concurrent_capacity_units=30))
    self.assertTrue(q, "a row that would build at zero must ask, not build")
    self.assertIn("30", q)
    for raw in ("concurrent_capacity_units", "annual_turns_per_year",
                "units_per", "_capacity"):
      self.assertNotIn(raw, q, "a raw field name reached the client")

  def test_a_complete_pair_is_not_asked_about(self):
    self.assertIsNone(
      self.q(self._ops(concurrent_capacity_units=30, annual_turns_per_year=18)))

  def test_a_row_that_already_has_a_throughput_is_not_asked_about(self):
    """Those branches are tried first, so the row never builds on zero."""
    self.assertIsNone(
      self.q(self._ops(concurrent_capacity_units=30, units_per_period_capacity=540,
                       operating_periods_per_year=1)))
    self.assertIsNone(
      self.q(self._ops(concurrent_capacity_units=30, units_per_week_capacity=45)))

  def test_it_is_let_go_after_two_asks(self):
    self.assertIsNone(
      self.q(self._ops(concurrent_capacity_units=30, _concurrent_turns_asked=2)))



class TheFoldWaitsUntilTheTurnsAreKnown(unittest.TestCase):
  """Found by re-firing, not by a test - the fix reintroducing its own bug.

  Three lines came back 30, 5 and 12 concurrent. The one that already carried
  operating_periods_per_year = 18 folded correctly. The two WITHOUT a turns
  figure had concurrent folded into units_per_period_capacity anyway, which
  asserts a throughput the client never gave; the pair rule then refused the
  result and nulled it. The client said 5 and 12 and the store held nothing -
  precisely the failure this whole piece of work exists to end.

  `concurrent -> units_per_period_capacity` is only true under the alias
  semantics, where the periods field IS the turns. Without turns there is no
  conversion, so the value stays as itself and waits for the question.
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

  def _row(self, **kw):
    row = {"unit_cadence": "contract", "product_name": "countertops"}
    row.update(kw)
    out = self.norm({"lob_models": [{"products": [row]}]})
    return out["lob_models"][0]["products"][0]

  def test_without_turns_it_is_kept_not_converted(self):
    r = self._row(concurrent_capacity_units=5)
    self.assertEqual(r.get("concurrent_capacity_units"), 5,
                     "the client's figure was thrown away")
    self.assertIsNone(r.get("units_per_period_capacity"),
                      "a throughput was asserted that the client never gave")

  def test_without_turns_nothing_is_refused(self):
    """The refusal was firing on a value the fold itself invented."""
    r = self._row(concurrent_capacity_units=5)
    self.assertFalse(r.get("_capacity_pair_refused"))

  def test_the_kept_value_is_what_the_question_asks_about(self):
    r = self._row(concurrent_capacity_units=5)
    q = self.ask({"lob_models": [{"products": [r]}]})
    self.assertTrue(q, "kept but never asked about is the silent-zero path")
    self.assertIn("5", q)

  def test_with_turns_it_stays_in_the_concurrent_home(self):
    """Reversed 2026-09-13 - see TheSixStaysInTheFieldThatMeansAtOnce."""
    r = self._row(concurrent_capacity_units=30, annual_turns_per_year=18)
    self.assertIn("concurrent_capacity_units", r)
    self.assertEqual(r["concurrent_capacity_units"], 30)
    self.assertIsNone(r.get("units_per_period_capacity"))

  def test_existing_periods_do_not_evict_the_concurrent_figure(self):
    r = self._row(concurrent_capacity_units=30, operating_periods_per_year=18)
    self.assertIn("concurrent_capacity_units", r)
    self.assertEqual(r["concurrent_capacity_units"], 30)


if __name__ == "__main__":
  unittest.main(verbosity=2)
