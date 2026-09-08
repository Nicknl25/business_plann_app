"""Nick's three Ardenwald rulings (2026-09-08), pinned.

1. The rest-of-team payroll trigger is ARITHMETIC - stated headcount vs waged
   roles - with the stage gate gone. Ardenwald (pre-revenue, 21-person
   day-one crew, 3 waged roles) is the shape the old gate suppressed; without
   the client's figure the payroll anchor floats (measured counterfactual:
   class high->low, Q1 supporting budget $227K -> $0).
2. A-113 at the interview write: one patch changing the same per-line numeric
   to the same value on 2+ rows is the broadcast signature; unnamed rows are
   restored (Ardenwald's 1,400 landed as unit_price on blast freezing AND the
   untouched outbound line).
3. Every ops patch write is logged - the fan-out left no trace.
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from api_handlers.intake_consult import (  # noqa: E402
  _apply_model_ops_patch,
  _guard_multiline_ops_rows,
  _rest_of_team_payroll_pending,
  _stated_headcount_for_rest_check,
  _waged_role_count,
)


class RestOfTeamTriggerTests(unittest.TestCase):
  ARDENWALD_PEOPLE = {"people": [
    {"role_title": "Founder and General Manager", "annual_wage": 135000},
    {"role_title": "Operations Director", "annual_wage": 118000},
    {"role_title": "Maintenance Lead", "annual_wage": 96000},
  ]}
  ARDENWALD_FULFILLMENT = {
    "personnel": "warehouse team of 21 staff from opening day handling trucks"}

  def test_ardenwald_shape_asks_despite_pre_revenue(self):
    """The defect: the old stage gate returned False here and $986K of wages
    survived only because the client volunteered them."""
    self.assertTrue(_rest_of_team_payroll_pending(
      self.ARDENWALD_PEOPLE, {"business_stage": "pre-revenue"},
      fulfillment_json=self.ARDENWALD_FULFILLMENT))

  def test_captured_figure_never_reasks(self):
    people = dict(self.ARDENWALD_PEOPLE, rest_of_team_payroll_year1=986000)
    self.assertFalse(_rest_of_team_payroll_pending(
      people, {"business_stage": "pre-revenue"},
      fulfillment_json=self.ARDENWALD_FULFILLMENT))

  def test_zero_is_a_captured_answer(self):
    """The router records 'no one else' as 0 - that must satisfy the gate."""
    people = dict(self.ARDENWALD_PEOPLE, rest_of_team_payroll_year1=0)
    self.assertFalse(_rest_of_team_payroll_pending(
      people, {}, fulfillment_json=self.ARDENWALD_FULFILLMENT))

  def test_proven_covered_headcount_skips(self):
    solo = {"people": [{"role_title": "Owner", "annual_wage": 80000}]}
    self.assertFalse(_rest_of_team_payroll_pending(
      solo, {"business_stage": "operating"},
      financials_json={"current_num_employees": 1}))

  def test_unknown_headcount_asks(self):
    """The question tolerates 'it's just me'; silence does not."""
    solo = {"people": [{"role_title": "Owner", "annual_wage": 80000}]}
    self.assertTrue(_rest_of_team_payroll_pending(solo, {}))

  def test_headcount_extracted_from_fulfillment_prose(self):
    self.assertEqual(_stated_headcount_for_rest_check(
      {}, {"personnel": "a 4-person crew plus the owner"}), 4)
    self.assertEqual(_stated_headcount_for_rest_check(
      {}, self.ARDENWALD_FULFILLMENT), 21)
    self.assertIsNone(_stated_headcount_for_rest_check(
      {}, {"personnel": "a big crew of seasoned hands"}))
    # the financials number outranks prose
    self.assertEqual(_stated_headcount_for_rest_check(
      {"current_num_employees": 9}, self.ARDENWALD_FULFILLMENT), 9)

  def test_waged_role_count_spans_people_and_inferred_roles(self):
    self.assertEqual(_waged_role_count({
      "people": [{"annual_wage": 1}, {"annual_wage": 0}, {}],
      "inferred_roles": [{"annual_wage": 50000}],
    }), 2)


class OpsRowScopingGuardTests(unittest.TestCase):
  PREV = {"lob_models": [{"lob_name": "Cold storage", "products": [
    {"product_name": "storage", "unit_price": 38, "units_per_period_capacity": 6000},
    {"product_name": "blast freezing"},
    {"product_name": "outbound"}]}]}

  def _rows(self, ops):
    return {p["product_name"]: p for lm in ops["lob_models"] for p in lm["products"]}

  def test_ardenwald_fan_out_is_restored(self):
    """The exact live defect: 1,400 as unit_price on blast AND untouched
    outbound in one snapshot; the client's words named neither line."""
    patch = {"lob_models": [{"lob_name": "Cold storage", "products": [
      {"product_name": "storage", "unit_price": 38, "units_per_period_capacity": 6000},
      {"product_name": "blast freezing", "unit_price": 1400},
      {"product_name": "outbound", "unit_price": 1400}]}]}
    out = _apply_model_ops_patch(
      dict(self.PREV), patch,
      user_message="1,400 pallets in a month before the tunnels are the constraint.")
    rows = self._rows(out)
    self.assertNotIn("unit_price", rows["blast freezing"])
    self.assertNotIn("unit_price", rows["outbound"])
    self.assertEqual(rows["storage"]["unit_price"], 38)

  def test_named_row_keeps_its_change_in_a_broadcast(self):
    patch = {"lob_models": [{"lob_name": "Cold storage", "products": [
      {"product_name": "storage", "unit_price": 38, "units_per_period_capacity": 6000},
      {"product_name": "blast freezing", "unit_price": 62},
      {"product_name": "outbound", "unit_price": 62}]}]}
    out = _apply_model_ops_patch(
      dict(self.PREV), patch, user_message="blast freezing is 62 a pallet")
    rows = self._rows(out)
    self.assertEqual(rows["blast freezing"]["unit_price"], 62)
    self.assertNotIn("unit_price", rows["outbound"])

  def test_single_row_change_passes(self):
    patch = {"lob_models": [{"lob_name": "Cold storage", "products": [
      {"product_name": "storage", "unit_price": 38, "units_per_period_capacity": 6000},
      {"product_name": "blast freezing", "unit_price": 62},
      {"product_name": "outbound"}]}]}
    out = _apply_model_ops_patch(dict(self.PREV), patch, user_message="x")
    self.assertEqual(self._rows(out)["blast freezing"]["unit_price"], 62)

  def test_distinct_values_are_a_real_multi_edit(self):
    patch = {"lob_models": [{"lob_name": "Cold storage", "products": [
      {"product_name": "storage", "unit_price": 40, "units_per_period_capacity": 6000},
      {"product_name": "blast freezing", "unit_price": 62},
      {"product_name": "outbound", "unit_price": 340}]}]}
    out = _apply_model_ops_patch(
      dict(self.PREV), patch, user_message="storage 40, blast 62, outbound 340")
    rows = self._rows(out)
    self.assertEqual(rows["storage"]["unit_price"], 40)
    self.assertEqual(rows["blast freezing"]["unit_price"], 62)
    self.assertEqual(rows["outbound"]["unit_price"], 340)

  def test_flat_per_line_numeric_never_lands_at_root_on_multiline(self):
    out = _apply_model_ops_patch(dict(self.PREV), {"unit_price": 999},
                                 user_message="x")
    self.assertNotEqual(out.get("unit_price"), 999)

  def test_single_line_model_is_untouched_by_the_guard(self):
    prev = {"lob_models": [{"lob_name": "Bakery", "products": [
      {"product_name": "donuts", "unit_price": 3}]}]}
    out = _apply_model_ops_patch(
      dict(prev), {"unit_price": 4,
                   "lob_models": [{"lob_name": "Bakery", "products": [
                     {"product_name": "donuts", "unit_price": 4}]}]},
      user_message="four dollars now")
    self.assertEqual(out.get("unit_price"), 4)
    self.assertEqual(out["lob_models"][0]["products"][0]["unit_price"], 4)

  def test_guard_reports_its_restores(self):
    patch = {"lob_models": [{"lob_name": "Cold storage", "products": [
      {"product_name": "storage", "unit_price": 38, "units_per_period_capacity": 6000},
      {"product_name": "blast freezing", "unit_price": 1400},
      {"product_name": "outbound", "unit_price": 1400}]}]}
    restored = _guard_multiline_ops_rows(dict(self.PREV), patch, "1,400 pallets")
    self.assertEqual(len(restored), 2)
    self.assertEqual({r["field"] for r in restored}, {"unit_price"})


if __name__ == "__main__":
  unittest.main()
