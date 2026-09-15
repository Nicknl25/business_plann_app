"""THE APP SAYS WHAT IT ASKED, AND A WEEKLY BUSINESS HAS NO ANNUAL OR TURNS FIELDS
(Nick 2026-09-15, CW-072 Marley Lane Barbers 598802b8).

1. The annual and turns fields went in on 09-13 for businesses running several jobs at
   once. On a weekly barbershop the router computed 2,600 a year and 3,120 at most from
   figures Dale never said, and wrote 52 turns on one replay and 0.83 on another from the
   same message. For a business whose rows all run weekly or monthly the router cannot
   write them, is not taught them, and the per-line door does not land them.

2. The app asked for a typical week; she said "About fifty."; the router read it as a
   capacity question. The consultant now declares the field when it asks, the persist door
   stores it on the message, and the router is told it with her reply - "I asked for her
   typical week, she said fifty", not "she said fifty, what might fifty be". The readback's
   question field is the app's, whatever the router guessed.
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python"), os.path.join(ROOT, "python", "client_intake_and_finmo")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo.intent_router import (  # noqa: E402
  CONCURRENT_ONLY_FIELDS, _allowed_fields_for_cadence, _app_asked_field, _clean_unresolved_figures,
  _ops_rows_all_rate_cadence,
)
from client_intake_and_finmo.intake_consultant import ASKABLE_OPS_FIELDS  # noqa: E402
from api_handlers.intake_consult import _apply_ops_product_overrides  # noqa: E402


def _shared(*cadences, top=None):
  return {"operating_model": {"unit_cadence": top, "lob_models": [
    {"lob_name": "Main", "products": [{"product_name": "Line %d" % i, "unit_cadence": c} for i, c in enumerate(cadences)]}]}}


ROUTER_OPS = ["unit_price", "units_per_week_capacity", "units_per_period_capacity", "avg_units_per_week_year1",
              "avg_units_per_period_year1", "concurrent_capacity_units", "annual_turns_per_year",
              "annual_capacity_units", "annual_completed_units", "product_overrides"]


class AWeeklyOrMonthlyBusinessHasNoConcurrentFields(unittest.TestCase):

  def test_which_businesses_are_weekly_or_monthly(self):
    cases = [
      ("barbershop, one weekly line", _shared("weekly"), True),
      ("kimchi maker, two monthly lines", _shared("monthly", "monthly"), True),
      ("print shop, weekly and monthly lines", _shared("weekly", "monthly"), True),
      ("boat yard, contract", _shared("contract"), False),
      ("stoneworks, weekly plus contract", _shared("weekly", "contract"), False),
      ("no rows, business said weekly", {"operating_model": {"unit_cadence": "weekly"}}, True),
      ("nothing known yet", {"operating_model": {}}, False),
      ("unknown cadence on a row", _shared(""), False),
    ]
    for name, shared, want in cases:
      with self.subTest(business=name):
        self.assertEqual(_ops_rows_all_rate_cadence(shared), want)

  def test_the_router_field_list_loses_them_only_on_a_rate_business(self):
    for prefix in ("", "ops."):
      allowed = [prefix + f for f in ROUTER_OPS]
      with self.subTest(naming=prefix or "bare"):
        weekly = _allowed_fields_for_cadence(allowed, _shared("weekly"))
        self.assertFalse({f.split(".")[-1] for f in weekly} & CONCURRENT_ONLY_FIELDS, weekly)
        self.assertIn(prefix + "avg_units_per_week_year1", weekly)
        self.assertIn(prefix + "units_per_week_capacity", weekly)
        contract = _allowed_fields_for_cadence(allowed, _shared("contract"))
        self.assertEqual(contract, allowed)

  def test_the_per_line_door_does_not_land_them_on_a_rate_row(self):
    for cadence in ("weekly", "monthly"):
      with self.subTest(cadence=cadence):
        ops = {"lob_models": [{"lob_name": "Haircuts", "products": [
          {"product_name": "Haircut", "unit_cadence": cadence, "units_per_week_capacity": 60}]}]}
        receipt = _apply_ops_product_overrides(ops, {"Haircut": {
          "annual_completed_units": 2600, "annual_turns_per_year": 0.83, "annual_capacity_units": 3120,
          "avg_units_per_week_year1": 50}})
        row = ops["lob_models"][0]["products"][0]
        for k in CONCURRENT_ONLY_FIELDS:
          self.assertNotIn(k, row, (cadence, k))
        self.assertEqual(row.get("avg_units_per_week_year1") if cadence == "weekly" else True, 50 if cadence == "weekly" else True)
        self.assertEqual(receipt["unplaced"], [], "a removed field is not asked about")

  def test_a_contract_row_still_takes_them(self):
    ops = {"lob_models": [{"lob_name": "Frames", "products": [{"product_name": "Frame", "unit_cadence": "contract"}]}]}
    _apply_ops_product_overrides(ops, {"Frame": {"concurrent_capacity_units": 6, "annual_completed_units": 26}})
    row = ops["lob_models"][0]["products"][0]
    self.assertEqual(row.get("concurrent_capacity_units"), 6)
    self.assertEqual(row.get("annual_completed_units"), 26)


class TheRouterIsToldWhatTheAppAsked(unittest.TestCase):

  def test_the_asked_field_is_read_off_the_last_assistant_message(self):
    msgs = [{"role": "assistant", "content": "What is your capacity?", "asked_field": "units_per_week_capacity"},
            {"role": "user", "content": "Sixty."},
            {"role": "assistant", "content": "In a typical week, how many do you actually do?", "asked_field": "avg_units_per_week_year1"}]
    self.assertEqual(_app_asked_field(msgs, ROUTER_OPS), "avg_units_per_week_year1")
    self.assertEqual(_app_asked_field(msgs, ["ops." + f for f in ROUTER_OPS]), "ops.avg_units_per_week_year1")

  def test_no_declared_field_or_one_the_router_cannot_write_is_empty(self):
    self.assertEqual(_app_asked_field([{"role": "assistant", "content": "Does that sound right?", "asked_field": ""}], ROUTER_OPS), "")
    self.assertEqual(_app_asked_field([{"role": "assistant", "content": "x"}], ROUTER_OPS), "")
    self.assertEqual(_app_asked_field([{"role": "assistant", "content": "x", "asked_field": "annual_completed_units"}],
                                      _allowed_fields_for_cadence(ROUTER_OPS, _shared("weekly"))), "")

  def test_the_apps_field_leads_the_readback_whatever_the_router_guessed(self):
    out = _clean_unresolved_figures(
      [{"value_json": "50", "client_words": "About fifty.", "question_field": "units_per_period_capacity",
        "candidate_fields": ["units_per_period_capacity", "units_per_week_capacity"]}],
      ROUTER_OPS, asked_field="avg_units_per_week_year1")
    self.assertEqual(out[0]["question_field"], "avg_units_per_week_year1")
    self.assertEqual(out[0]["candidate_fields"][0], "avg_units_per_week_year1")

  def test_every_field_the_consultant_asks_about_is_one_the_router_can_write(self):
    """The live Ops path builds its field list from the ops value schema. Marley Lane's
    typical-week question named avg_units_per_week_year1, which that schema did not hold, so
    the router could neither write her fifty nor be told what was asked."""
    from client_intake_and_finmo.intent_router import _value_schema_by_consult_field
    ops_fields = set(_value_schema_by_consult_field(consult_type="ops").keys())
    unified = set(_value_schema_by_consult_field(consult_type="unified").keys())
    for f in ASKABLE_OPS_FIELDS:
      if not f:
        continue
      with self.subTest(field=f):
        self.assertIn(f, ops_fields)
        self.assertIn("ops." + f, unified)

  def test_the_consultant_can_declare_every_field_it_asks_about(self):
    for f in ("", "unit_price", "units_per_week_capacity", "units_per_period_capacity", "utilization_rate",
              "avg_units_per_week_year1", "avg_units_per_period_year1"):
      self.assertIn(f, ASKABLE_OPS_FIELDS)


if __name__ == "__main__":
  unittest.main()
