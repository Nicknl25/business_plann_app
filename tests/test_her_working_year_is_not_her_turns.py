"""CW-076 ASHGROVE BINDERY AND PRINT bf731ee4, killed 2026-09-18 at turn 17.

  app  (declared operating_periods_per_year): "about how many weeks a year are you
       actually operating... roughly - most of the year (around 50+ weeks)..."
  her: "Forty-eight. We close the last two weeks of December."
  app: "so you're running the business for 48 working weeks each year"

  the store, one turn apart, on the book binding & repair line:
    19:40   units_per_period_capacity 10 | operating_periods_per_year 110  -> 1,100 a year
    19:41   units_per_period_capacity 10 | operating_periods_per_year  48  ->   480 a year

Her stated 1,100 became 480. The number was ALREADY RIGHT - 110 turns had itself
been derived from her own "about eleven hundred" against a ceiling of ten - and a
truthful answer to a different question landed in the slot holding it.

The cause is not the conversion, which was correct. MEASURED across the whole
store: 0 of 4,459 contract rows had ever held operating_weeks_per_year, at row,
LOB or business level, across 9,144 drafts. The ops prompt has always asked for
her working year and there has never been a field to declare it or a schema to
carry it, so it was declared as the turns - on Perrin Row, and again here.

These pins are the two halves Cowork made binding in the amended 1c: STORED as
well as USED, demonstrated on a CONTRACT row, plus the 1d round trip - her own
figure coming back out, not merely the absence of a wrong one.
"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

import api_handlers.intake_consult as IC  # noqa: E402
from client_intake_and_finmo.intake_consultant import ASKABLE_OPS_FIELDS  # noqa: E402
from client_intake_and_finmo.intent_router import (  # noqa: E402
  _value_schema_by_consult_field as _schema,
)


def _ashgrove():
  """The store as it stood at 19:40, before the weeks turn: her ten at once and
  her 1,100 a year already homed as 110 turns."""
  return {"lob_models": [{"lob_name": "Primary line of business", "products": [
    {"product_name": "Book binding & repair job", "unit_cadence": "contract",
     "unit_name": "book", "unit_price": 110,
     "units_per_period_capacity": 10, "operating_periods_per_year": 110},
    {"product_name": "Short-run print job", "unit_cadence": "contract"},
  ]}]}


class TheStageThatAsksForHerYearCanNameIt(unittest.TestCase):
  """A question the stage must ask and cannot name gets declared as something
  else. That is the whole mechanism, and it is the same one as the 930."""

  def test_it_is_declarable_at_ops(self):
    self.assertIn("operating_weeks_per_year", ASKABLE_OPS_FIELDS)

  def test_the_router_can_carry_it_at_ops(self):
    self.assertIn("operating_weeks_per_year", _schema(consult_type="ops"))

  def test_financials_keeps_it_too(self):
    """It is not moved, it is shared - financials has always read it."""
    self.assertIn("operating_weeks_per_year", _schema(consult_type="financials_year1"))

  def test_the_actuals_did_not_come_back_with_it(self):
    """A3 adds one field. It must not quietly re-open the overlap that killed
    Harlow Street Cycles."""
    ops = _schema(consult_type="ops")
    for f in ("avg_units_per_week_year1", "avg_units_per_period_year1", "utilization_rate"):
      self.assertNotIn(f, ops, "%s is the financials stage's question" % f)
      self.assertNotIn(f, ASKABLE_OPS_FIELDS)


class HerWorkingYearIsStored(unittest.TestCase):
  """STORED - the half that had never once happened in 4,459 contract rows, and
  the half my earlier 1c pin faked by putting the value on the row by hand."""

  def _apply(self, patch, ops=None):
    return IC._apply_scoped_patch(
      patch, business_facts={}, ops_json=copy.deepcopy(ops if ops is not None else _ashgrove()),
      market_json={}, people_json={}, financials_json={}, fulfillment_json={},
      user_message="Forty-eight. We close the last two weeks of December.",
      consult_stage="ops")[1]

  def test_a_bare_weeks_write_lands_on_the_row(self):
    single = {"lob_models": [{"lob_name": "Bindery", "products": [
      {"product_name": "Book binding & repair job", "unit_cadence": "contract",
       "units_per_period_capacity": 10, "operating_periods_per_year": 110}]}]}
    out = self._apply({"ops.operating_weeks_per_year": 48}, ops=single)
    row = out["lob_models"][0]["products"][0]
    self.assertEqual(row.get("operating_weeks_per_year"), 48,
                     "her working year still has nowhere to land")

  def test_a_per_line_weeks_write_lands_on_the_line_she_named(self):
    out = self._apply({"ops.product_overrides": {
      "Book binding & repair job": {"operating_weeks_per_year": 48}}})
    rows = out["lob_models"][0]["products"]
    self.assertEqual(rows[0].get("operating_weeks_per_year"), 48)
    self.assertIsNone(rows[1].get("operating_weeks_per_year"),
                      "her year leaked onto a line she did not name")


class HerWorkingYearIsNotHerTurns(unittest.TestCase):
  """THE KILLING TURN. This is the assertion the run failed."""

  def _weeks_turn(self, weeks=48):
    ops = IC._apply_scoped_patch(
      {"ops.product_overrides": {"Book binding & repair job": {
        "operating_weeks_per_year": weeks}}},
      business_facts={}, ops_json=_ashgrove(), market_json={}, people_json={},
      financials_json={}, fulfillment_json={},
      user_message="Forty-eight. We close the last two weeks of December.",
      consult_stage="ops")[1]
    return IC._normalize_ops_capacity_compat(ops)["lob_models"][0]["products"][0]

  def test_her_forty_eight_does_not_become_her_turns(self):
    row = self._weeks_turn()
    self.assertEqual(row.get("operating_periods_per_year"), 110,
                     "her 48 weeks overwrote her 110 turns - this is the kill")
    self.assertEqual(row.get("operating_weeks_per_year"), 48)

  def test_the_round_trip_survives_the_weeks_question(self):
    """1d, Cowork's template: her own figure back out, not the absence of a wrong
    one. 10 at once x 110 turns = the 1,100 a year she stated."""
    row = self._weeks_turn()
    annual = row.get("units_per_period_capacity") * row.get("operating_periods_per_year")
    self.assertEqual(annual, 1100,
                     "she said about eleven hundred; the row says %s" % annual)

  def test_the_weekly_figure_uses_the_year_she_gave(self):
    """USED, on a contract row - the shape where operating_weeks_per_year had
    never been read. 10 x 110 / 48 = 22.9167, not 10 x 110 / 52 = 21.1538."""
    row = self._weeks_turn()
    self.assertAlmostEqual(row.get("units_per_week_capacity"), 10 * 110 / 48.0, 4)
    self.assertNotAlmostEqual(row.get("units_per_week_capacity"), 10 * 110 / 52.0, 4)

  def test_the_number_the_run_actually_produced_is_gone(self):
    """9.2308 was 10 x 48 / 52 - the weeks standing in for the turns AND the 52
    fallback still dividing. Both halves have to be gone."""
    row = self._weeks_turn()
    for wrong in (9.2308, 21.1538):
      self.assertNotAlmostEqual(row.get("units_per_week_capacity"), wrong, 3)

  def test_it_holds_for_any_business_and_any_year(self):
    """Not an Ashgrove fix. The property is: her year never displaces her turns."""
    for weeks in (40, 44, 48, 50, 52):
      with self.subTest(weeks=weeks):
        row = self._weeks_turn(weeks=weeks)
        self.assertEqual(row.get("operating_periods_per_year"), 110)
        self.assertEqual(row.get("operating_weeks_per_year"), weeks)
        self.assertAlmostEqual(row.get("units_per_week_capacity"), 10 * 110 / float(weeks), 4)


class AndThenTheLateYearIsRecomputed(unittest.TestCase):
  """3c could never be exercised while 3a was open: it recomputes against a year
  that was never stored. With her year homed, this is finally reachable - and
  22.9167 is the figure that proves it, which appeared nowhere on CW-076."""

  def test_a_year_that_arrives_after_the_derivation_still_counts(self):
    row = {"product_name": "Book binding & repair job", "unit_cadence": "contract",
           "units_per_period_capacity": 10, "operating_periods_per_year": 110}
    ops = IC._normalize_ops_capacity_compat({"lob_models": [{"products": [row]}]})
    first = ops["lob_models"][0]["products"][0].get("units_per_week_capacity")
    self.assertAlmostEqual(first, 10 * 110 / 52.0, 4, "turn one uses the fallback")

    ops["lob_models"][0]["products"][0]["operating_weeks_per_year"] = 48
    second = IC._normalize_ops_capacity_compat(ops)["lob_models"][0]["products"][0]
    self.assertAlmostEqual(second.get("units_per_week_capacity"), 22.9167, 3,
                           "her forty-eight never reached the derived figure")
    self.assertEqual(second.get("operating_periods_per_year"), 110)


class ThereWasMoreThanOneConversion(unittest.TestCase):
  """A FIX ON ONE OF TWO CONVERSIONS IS NOT A FIX.

  The hardcoded 52 was fixed in _normalize_ops_capacity_compat on the morning of
  2026-09-18 and the claim was made on that basis. The live turn runs a DIFFERENT
  derivation, and it was still dividing by 52. The tell was the rounding: CW-076
  stored 21.1538 and 9.2308 to four places (round(_, 4) in the per-row engine)
  while the normaliser writes six. Counting the sites afterwards found three.

  THIS IS A SOURCE GUARD, NOT A BEHAVIOUR PROOF - it reads our own text, so it
  can only catch a hardcoded divisor being written back in. The behaviour is
  pinned by the classes above, which drive the real door.
  """

  def test_no_weekly_capacity_is_derived_from_a_hardcoded_year(self):
    src = (ROOT / "python" / "api_handlers" / "intake_consult.py").read_text(
      encoding="utf-8-sig")
    offenders = [
      line.strip()
      for line in src.splitlines()
      if "units_per_week_capacity" in line and "=" in line and "/ 52" in line
    ]
    self.assertEqual(offenders, [],
                     "a weekly figure is being derived from a literal 52 again:\n  "
                     + "\n  ".join(offenders))

  def test_the_period_side_too(self):
    src = (ROOT / "python" / "api_handlers" / "intake_consult.py").read_text(
      encoding="utf-8-sig")
    offenders = [
      line.strip()
      for line in src.splitlines()
      if "units_per_period_capacity" in line and "=" in line and "* 52" in line
    ]
    self.assertEqual(offenders, [],
                     "a period figure is being derived from a literal 52 again:\n  "
                     + "\n  ".join(offenders))


class AFigureSheStatedIsNotOursToRecompute(unittest.TestCase):
  """mini, 2026-09-22, auditing the Ashgrove write path and proving this on a
  real row: a client who says SEVENTEEN A WEEK, on a row carrying period=10 and
  periods=119, had her seventeen silently replaced by 22.8846 - on contract AND
  on monthly. Only weekly survived, and only because the week figure is
  canonical there.

  The rule and the mark already existed one function away: the normaliser
  stamps what a derived weekly figure was derived FROM and recomputes only what
  carries that stamp. _derive_capacity_cells ignored both, so the unguarded
  writer could undo the guarded one - which is also why 3c looked redundant
  when it is in fact the site that is right.
  """

  def _row(self, cadence, **kw):
    row = {"product_name": "x", "unit_cadence": cadence,
           "units_per_period_capacity": 10, "operating_periods_per_year": 119}
    row.update(kw)
    ops = {"lob_models": [{"products": [row]}]}
    IC._derive_capacity_cells(ops)
    return ops["lob_models"][0]["products"][0]

  def test_her_seventeen_a_week_survives_on_every_cadence(self):
    for cadence in ("contract", "monthly", "weekly"):
      with self.subTest(cadence=cadence):
        self.assertEqual(self._row(cadence, units_per_week_capacity=17)
                         .get("units_per_week_capacity"), 17,
                         "her stated weekly figure was recomputed away")

  def test_a_figure_the_app_derived_is_still_refreshed(self):
    """The guard must not freeze a stale derived value - only her own."""
    row = self._row("contract", units_per_week_capacity=21.1538,
                    _units_per_week_derived_from_weeks=52.0)
    self.assertAlmostEqual(row.get("units_per_week_capacity"), 10 * 119 / 52.0, 3)

  def test_a_row_with_no_weekly_figure_still_gets_one(self):
    row = self._row("contract")
    self.assertAlmostEqual(row.get("units_per_week_capacity"), 10 * 119 / 52.0, 3)

  def test_what_it_was_derived_from_is_recorded_here_too(self):
    """Both sites must speak one language or a later stated year cannot repair
    what this one wrote."""
    self.assertIsNotNone(
      self._row("contract").get("_units_per_week_derived_from_weeks"))


if __name__ == "__main__":
  unittest.main(verbosity=2)
