"""THE REASON GATE (Nick 2026-09-10): the completeness gate tests the
absence REASON, not just its presence.

"It checks whether a reason EXISTS, not whether it's TRUE. So a figure
can omit itself, write a note, and the gate accepts it. [...] Make the
gate test the reason, not just its presence."

The Bright Smiles pair that proved it: revenue_by_line omitted as
'single line of business' on a practice with three priced service lines
($150/$120/$85 modeled as products inside one lob), and
wage_positioning omitted as 'no roster role could be matched to an
occupation' when two roster rows carried occupation stamps (the real
failure was the OEWS area join, 'IL' vs 'Illinois'). Both audited FALSE
against the live artifacts.

Fail-closed: a reason string no validator recognizes fails the gate -
an excuse nobody can test is not a reason.
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

from writing_phase_v2.completeness import audit_absences  # noqa: E402

THREE_LINE_BUNDLE = {
  "record": {"financials_year1": {"lobs": [{
    "lob_name": "Primary line of business",
    "products": [
      {"product_name": "General dentistry patient visit", "unit_price": 150,
       "revenue_total_year1": 519693},
      {"product_name": "Preventive dental care services", "unit_price": 120,
       "revenue_total_year1": 415754},
      {"product_name": "Dental imaging services", "unit_price": 85,
       "revenue_total_year1": 264553},
    ]}]}},
  "warehouse": {}, "model": {},
}

ONE_LINE_BUNDLE = {
  "record": {"financials_year1": {"lobs": [{
    "lob_name": "Consulting", "products": [
      {"product_name": "Consulting engagement", "unit_price": 5000,
       "revenue_total_year1": 250000}]}]}},
  "warehouse": {}, "model": {},
}

# The Sunny Glaze shape: financials_year1 EMPTY (an early draft), the
# two priced streams live only in the operating model - exactly Table 1
# on the delivered page (5.0 x 1200 x 0.75 x 52 = 234,000 donuts;
# 3.0 x 400 x 0.75 x 52 = 46,800 beverages).
OPS_ONLY_BUNDLE = {
  "record": {"financials_year1": {}, "operating_model": {"lob_models": [{
    "lob_name": "Primary line of business", "products": [
      {"product_name": "donut", "unit_price": 5.0,
       "units_per_week_capacity": 1200.0, "utilization_rate": 0.75,
       "operating_periods_per_year": 52},
      {"product_name": "beverage", "unit_price": 3.0,
       "units_per_week_capacity": 400.0, "utilization_rate": 0.75,
       "operating_periods_per_year": 52},
    ]}]}},
  "warehouse": {}, "model": {},
}

STAMPED_DRAFT = {
  "payroll_headcount": {"rows": [
    {"quarter_index": 1, "person_name": "Emily Carter",
     "base_annual_wage": 70000, "oews_occ_code": "11-1021",
     "wage_source": "client_override", "staffing_class": "key_person"},
    {"quarter_index": 1, "position_title": "Dental Assistants",
     "base_annual_wage": 46270, "oews_occ_code": "31-9091",
     "wage_source": "oews_title_catalog:oews_median",
     "staffing_class": "supporting_staff"},
  ]},
  "people_json": "{}", "operating_model_json": "{}",
}

UNMATCHABLE_DRAFT = {
  "payroll_headcount": {"rows": [
    {"quarter_index": 1, "position_title": "Mystery role",
     "base_annual_wage": 40000, "oews_occ_code": "",
     "staffing_class": "supporting_staff"}]},
  "people_json": "{}", "operating_model_json": "{}",
}


def _absent(fid, reason):
  return {fid: {"id": fid, "kind": "figure", "placed": False,
                "reason": reason}}


class ReasonGateTests(unittest.TestCase):
  def test_single_line_reason_false_on_three_streams(self):
    out = audit_absences(
      _absent("revenue_by_line",
              "single line of business - the figure would repeat the "
              "revenue chart"),
      bundle=THREE_LINE_BUNDLE)
    self.assertEqual(len(out), 1)
    self.assertIn("3 priced revenue streams", out[0])
    self.assertIn("519693", out[0])

  def test_sunny_shape_ops_only_streams_fail_the_reason(self):
    """financials_year1 empty, two priced products in the operating
    model: 'single line of business' is FALSE - the validator counts
    what the page's own product table carries."""
    out = audit_absences(
      _absent("revenue_by_line", "single line of business - the figure "
              "would repeat the revenue chart"),
      bundle=OPS_ONLY_BUNDLE)
    self.assertEqual(len(out), 1)
    self.assertIn("234000", out[0].replace(",", ""))

  def test_sunny_shape_capacity_reason_is_false_too(self):
    out = audit_absences(
      _absent("capacity_vs_plan_y1", "no line carries weekly capacity "
              "and utilisation"),
      bundle=OPS_ONLY_BUNDLE)
    self.assertEqual(len(out), 1)

  def test_single_line_reason_holds_on_one_stream(self):
    out = audit_absences(
      _absent("revenue_by_line", "single line of business - the figure "
              "would repeat the revenue chart"),
      bundle=ONE_LINE_BUNDLE)
    self.assertEqual(out, [])

  def test_no_occupation_match_false_on_stamped_roster(self):
    out = audit_absences(
      _absent("wage_positioning",
              "no roster role could be matched to an occupation"),
      bundle=ONE_LINE_BUNDLE, draft=STAMPED_DRAFT)
    self.assertEqual(len(out), 1)
    self.assertIn("11-1021", out[0])
    self.assertIn("31-9091", out[0])

  def test_no_occupation_match_holds_when_nothing_matches(self):
    out = audit_absences(
      _absent("wage_positioning",
              "no roster role could be matched to an occupation"),
      bundle=ONE_LINE_BUNDLE, draft=UNMATCHABLE_DRAFT)
    self.assertEqual(out, [])

  def test_unknown_reason_fails_closed(self):
    out = audit_absences(
      _absent("revenue_by_line", "the intern was tired"),
      bundle=ONE_LINE_BUNDLE)
    self.assertEqual(len(out), 1)
    self.assertIn("NO validator", out[0])

  def test_unregistered_figure_fails_closed(self):
    out = audit_absences(
      _absent("brand_new_figure", "some fresh excuse"),
      bundle=ONE_LINE_BUNDLE)
    self.assertEqual(len(out), 1)
    self.assertIn("NO validator", out[0])

  def test_placed_and_renderer_error_rows_skipped(self):
    rep = {
      "a": {"id": "a", "kind": "figure", "placed": True},
      "b": {"id": "b", "kind": "figure", "placed": False,
            "reason": "RENDERER ERROR: boom"},
    }
    self.assertEqual(audit_absences(rep, bundle=ONE_LINE_BUNDLE), [])

  def test_firm_size_reasons(self):
    b = dict(ONE_LINE_BUNDLE)
    b["warehouse"] = {"bds_firm_size_2023": {"firms_by_size":
                                             {"a) 1 to 4": 100}}}
    out = audit_absences(
      _absent("competitor_size_bands", "no bds_firm_size slice in the "
              "bundle"), bundle=b)
    self.assertEqual(len(out), 1)
    out2 = audit_absences(
      _absent("competitor_size_bands", "no bds_firm_size slice in the "
              "bundle"), bundle=ONE_LINE_BUNDLE)
    self.assertEqual(out2, [])

  def test_marketing_period_reasons(self):
    rd = {"marketing_periods": [
      {"period_index": i, "is_stub": False} for i in range(1, 5)]}
    out = audit_absences(
      _absent("marketing_customers", "no marketing-schedule periods in "
              "the renderer data"),
      bundle=ONE_LINE_BUNDLE, render_data=rd)
    self.assertEqual(len(out), 1)
    out2 = audit_absences(
      _absent("marketing_customers", "marketing schedule has fewer than "
              "four projected quarters"),
      bundle=ONE_LINE_BUNDLE, render_data=rd)
    self.assertEqual(len(out2), 1)
    self.assertIn("4 quarters", out2[0])


if __name__ == "__main__":
  unittest.main()
