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



class TheConcurrentNamesAreAliasesNotASecondHome(unittest.TestCase):
  """Found while auditing what else woke up (Nick, 2026-09-13).

  `financials_year1` renames the generic period triple for cadence "contract":
  `out["concurrent_capacity_units"] = units_per_period_capacity` and
  `out["annual_turns_per_year"] = operating_periods_per_year`. They are ONE
  slot under two vocabularies - which means a contract row's
  units_per_period_capacity has always MEANT concurrent load, and Thackeray's
  row already carried operating_periods_per_year = 18 (its turns).

  So storing the router's concurrent keys beside the canonical pair would build
  a second home for one quantity - deliberately constructing the twin that the
  pair refusal exists to catch. They fold instead. The vocabulary is new; the
  slot is not.
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

  def test_the_alias_lands_in_the_canonical_slot(self):
    r = self._row(concurrent_capacity_units=30, annual_turns_per_year=18)
    self.assertEqual(r.get("units_per_period_capacity"), 30)
    self.assertEqual(r.get("operating_periods_per_year"), 18)

  def test_the_alias_key_does_not_survive_beside_it(self):
    """Two homes for one number is the defect, not the fix."""
    r = self._row(concurrent_capacity_units=30, annual_turns_per_year=18)
    self.assertNotIn("concurrent_capacity_units", r)
    self.assertNotIn("annual_turns_per_year", r)

  def test_both_vocabularies_produce_the_identical_row(self):
    """The whole claim: a client described either way prices the same."""
    via_alias = self._row(concurrent_capacity_units=30, annual_turns_per_year=18)
    via_canon = self._row(units_per_period_capacity=30, operating_periods_per_year=18)
    for field in ("units_per_period_capacity", "operating_periods_per_year",
                  "units_per_week_capacity"):
      self.assertEqual(via_alias.get(field), via_canon.get(field), field)

  def test_an_alias_that_disagrees_with_the_slot_is_refused(self):
    """30 concurrent and 540 a period cannot both be that slot."""
    r = self._row(concurrent_capacity_units=30, units_per_period_capacity=540,
                  annual_turns_per_year=18)
    self.assertIsNone(r.get("units_per_period_capacity"))
    self.assertTrue(r.get("_capacity_pair_refused"))


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


if __name__ == "__main__":
  unittest.main(verbosity=2)
