"""Two stored copies of one fact must agree - arithmetic on the store, no interpretation.

Nick ruled 2026-09-14: of the checks that may block, arithmetic is the one that had no
implementation and the one to build. Cowork 1185 read it off the store: Green Meadow's
ops row holds her 40 visits a week while financials_year1 holds 426.8986827126362; Alder
& Vine's weekly ops row holds her 185 a week beside a period capacity of 2.

These pins state, for any business, any cadence and any values:
  - a weekly row's period capacity IS its week capacity;
  - any other row's week capacity is period x periods-per-year / 52 (the app's own rule);
  - the ops row and its financials_year1 copy agree on capacity, price and periods;
  - agreement within the app's own derivation rounding is agreement;
  - a zero in one copy against a figure in the other is a disagreement, named apart;
  - a missing value is not a disagreement - there is no second copy to compare;
  - nothing here reads a client's words.
"""
from __future__ import annotations

import itertools
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from client_intake_and_finmo.store_arithmetic import twin_disagreements  # noqa: E402


def _ops(**p):
  row = {"product_name": "Visit", "unit_cadence": "weekly"}
  row.update(p)
  return {"lob_models": [{"lob_name": "Clinic", "products": [row]}]}


def _y1(**p):
  row = {"product_name": "Visit", "unit_cadence": "weekly"}
  row.update(p)
  return {"lobs": [{"lob_name": "Clinic", "products": [row]}]}


class WithinOneRow(unittest.TestCase):
  def test_a_weekly_rows_period_is_its_week(self):
    for wk, per, want in ((40, 40, 0), (185, 2, 1), (40.0, 40.00001, 0), (40, 426.8986827126362, 1)):
      got = twin_disagreements(_ops(units_per_week_capacity=wk, units_per_period_capacity=per), {})
      self.assertEqual(len(got), want, (wk, per, got))

  def test_any_other_cadence_converts_by_its_periods(self):
    # a monthly row runs at most 12 periods a year (the bound below); a contract row has no calendar bound
    for cadence, periods in [("contract", p) for p in (12, 13, 35, 50)] + [("monthly", p) for p in (6, 10, 12)]:
      per = 5.0
      right = per * periods / 52.0
      ok = twin_disagreements(_ops(unit_cadence=cadence, operating_periods_per_year=periods,
                                   units_per_period_capacity=per, units_per_week_capacity=round(right, 4)), {})
      self.assertEqual(ok, [], (cadence, periods))
      bad = twin_disagreements(_ops(unit_cadence=cadence, operating_periods_per_year=periods,
                                    units_per_period_capacity=per * 1.0012, units_per_week_capacity=round(right, 4)), {})
      self.assertEqual([d["fact"] for d in bad], ["capacity"], (cadence, periods))
    self.assertEqual(twin_disagreements(_ops(unit_cadence="contract", units_per_period_capacity=5,
                                             units_per_week_capacity=1.25), {}), [],
                     "no periods, no rule - nothing is guessed")


class ARefusalIsNotADisagreement(unittest.TestCase):
  """Cowork 1228, CW-070 clone e7120169: the guard refused a capacity pair it could not
  make true - the ops row holds null for both and _capacity_pair_refused says why - while
  year-one still holds 1200. That is a refusal, not two copies disagreeing."""

  def test_refused_facts_are_not_compared_and_the_rest_still_are(self):
    refused = {"units_per_week_capacity": 1200, "units_per_period_capacity": 1200, "cadence": "monthly",
               "operating_periods_per_year": 12, "why": "conversions of one another cannot hold values that disagree"}
    ops = _ops(unit_cadence="monthly", units_per_week_capacity=None, units_per_period_capacity=None, unit_price=9.5,
               _capacity_pair_refused=refused)
    y1 = _y1(unit_cadence="monthly", units_per_week_capacity=1200, units_per_period_capacity=1200, unit_price=10.0)
    got = twin_disagreements(ops, y1)
    self.assertEqual([d["fact"] for d in got if d["where"] == "operating_model_json vs financials_year1_json"], ["unit_price"],
                     "capacity was refused on purpose; the price still disagrees and is still named")
    # the same pair with no refusal on record is a disagreement again - once ops holds a figure
    ops2 = _ops(unit_cadence="monthly", units_per_period_capacity=1100, unit_price=9.5)
    self.assertIn("units_per_period_capacity", [d["fact"] for d in twin_disagreements(ops2, y1)])


class AYearHoldsOnlySoManyPeriods(unittest.TestCase):
  """Cowork 1215, CW-070 draft 71d4e505: a monthly row held 52 periods a year and its
  year-one copy 52 operating months. A bound on arithmetic, whatever she said."""

  def test_cw070_shape_and_every_cadence(self):
    got = twin_disagreements(_ops(unit_cadence="monthly", operating_periods_per_year=52),
                             _y1(unit_cadence="monthly", operating_periods_per_year=52, operating_months_per_year=52))
    impossible = [d for d in got if d["shape"] == "impossible"]
    self.assertEqual(sorted((d["where"], d["a"]["field"]) for d in impossible),
                     [("financials_year1_json", "operating_months_per_year"),
                      ("financials_year1_json", "operating_periods_per_year"),
                      ("operating_model_json", "operating_periods_per_year")])
    for cadence, ok, bad in (("monthly", (1, 10, 12), (13, 52)), ("weekly", (1, 48, 52, 53), (54, 365))):
      for v in ok:
        self.assertEqual([d for d in twin_disagreements(_ops(unit_cadence=cadence, operating_periods_per_year=v), {})
                          if d["shape"] == "impossible"], [], (cadence, v))
      for v in bad:
        self.assertTrue([d for d in twin_disagreements(_ops(unit_cadence=cadence, operating_periods_per_year=v), {})
                         if d["shape"] == "impossible"], (cadence, v))
    self.assertEqual([d for d in twin_disagreements(_ops(unit_cadence="contract", operating_periods_per_year=200), {})
                      if d["shape"] == "impossible"], [], "a contract row's periods have no calendar bound")


class BetweenTheTwoCopies(unittest.TestCase):
  def test_green_meadow_shape(self):
    got = twin_disagreements(_ops(units_per_week_capacity=40, units_per_period_capacity=40, unit_price=60),
                             _y1(units_per_week_capacity=426.8986827126362, units_per_period_capacity=426.8986827126362,
                                 unit_price=60))
    self.assertEqual(sorted(d["fact"] for d in got), ["units_per_period_capacity", "units_per_week_capacity"])
    for d in got:
      self.assertEqual((d["a"]["value"], d["b"]["value"], d["shape"]), (40.0, 426.8986827126362, "disagree"))
      self.assertAlmostEqual(d["ratio"], 10.672467, places=5)

  def test_every_fact_in_every_direction(self):
    for fact in ("units_per_week_capacity", "units_per_period_capacity", "unit_price", "operating_periods_per_year"):
      for a, b in ((100.0, 100.0), (100.0, 100.04), (100.0, 101.0), (101.0, 100.0), (4.0, 0.0), (0.0, 4.0)):
        extra = {} if fact.startswith("units_per") else {"units_per_week_capacity": 7, "units_per_period_capacity": 7}
        got = [d for d in twin_disagreements(_ops(**{fact: a}, **extra), _y1(**{fact: b}, **extra)) if d["fact"] == fact]
        agrees = abs(a - b) <= 0.0005 * max(abs(a), abs(b))
        self.assertEqual(bool(got), not agrees, (fact, a, b))
        if got:
          self.assertEqual(got[0]["shape"], "zero_in_copy" if (a == 0) != (b == 0) else "disagree", (fact, a, b))

  def test_a_missing_copy_is_not_a_disagreement(self):
    self.assertEqual(twin_disagreements(_ops(unit_price=60), _y1()), [])
    self.assertEqual(twin_disagreements(_ops(unit_price=60), {"lobs": [{"lob_name": "Other", "products": [
      {"product_name": "Visit", "unit_price": 99}]}]}), [], "a different row is not a copy")
    self.assertEqual(twin_disagreements(None, None), [])
    self.assertEqual(twin_disagreements({"lob_models": "junk"}, {"lobs": [None, {"products": ["x"]}]}), [])

  def test_it_reads_no_words(self):
    src = (ROOT / "python" / "client_intake_and_finmo" / "store_arithmetic.py").read_text(encoding="utf-8")
    for forbidden in ("messages_json", "user_message", "_message_figures", "re.compile", "import re"):
      self.assertNotIn(forbidden, src)


if __name__ == "__main__":
  unittest.main(verbosity=2)
