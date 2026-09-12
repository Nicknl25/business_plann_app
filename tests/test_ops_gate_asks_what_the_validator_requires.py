"""A VALIDATOR MAY NOT REQUIRE A FIELD THE CONVERSATION DOESN'T ASK FOR
(Nick 2026-09-12). And a client never sees a raw field name - fourth time.

Sablecreek Microgrid Systems, draft 3d57edc6: intake complete, lender test
converged, submit refused with "primary_growth_lever: primary_growth_lever
is required". The ops interview never asked the growth-lever question on
that run - it asked the 12-month goal in that slot. Readiness had been
judged on the consultant's proposed object (every stored finalize object
carried the lever as null, the last at 02:31:44), the persisted ops held
an empty string, the fallback question existed and was never asked, and
the validator required the result.

Now: one list (intake_required_fields) feeds the readiness check, the
follow-up question, the wrap guard at the hand-over to Target Market, and
the submission validator; the guard judges the object about to be
persisted; every validator message speaks the client's name for the field.
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo import intake_required_fields as rf  # noqa: E402
from client_intake_and_finmo import intake_submit_service as svc  # noqa: E402
import api_handlers.intake_consult as ic  # noqa: E402


def _sablecreek_ops(**over):
  ops = {
    "consumer_type": "b2b", "business_type": "Systems Integration Services",
    "shipping_method": "on site", "sales_modality": "hybrid", "geographic_scope": "regional",
    "geographic_coverage": "Idaho, Washington, Oregon, Nevada, Utah, and Montana",
    "countries": ["United States"], "capacity_driver": "labor",
    "primary_growth_lever": "",          # the hole that reached the submit gate
    "legal_entity": "LLC",
    "lob_models": [{"lob_name": "Installations", "products": [{
      "unit_name": "install", "unit_cadence": "contract", "unit_price": 150000, "units_per_period_capacity": 30,
      "utilization_rate": 0.8, "operating_periods_per_year": 1}]}],
  }
  ops.update(over)
  return ops


class OneListFeedsEveryGate(unittest.TestCase):
  def test_every_required_field_has_a_question_and_a_name(self):
    for f in rf.OPS_BUSINESS_WIDE_REQUIRED:
      self.assertTrue(rf.followup_question_for(f), f)
      self.assertIn(f, rf.FIELD_LABELS, f)
      self.assertNotIn("_", rf.FIELD_LABELS[f], f)

  def test_readiness_reads_the_shared_list(self):
    self.assertFalse(ic._ops_ready_for_wrap_from_gate_obj(_sablecreek_ops()))
    self.assertTrue(ic._ops_ready_for_wrap_from_gate_obj(_sablecreek_ops(primary_growth_lever="win more demand")))

  def test_the_fallback_asks_the_growth_lever_when_it_is_the_hole(self):
    q = ic._fallback_ops_followup_question(_sablecreek_ops())
    self.assertIn("main lever", q)
    self.assertEqual(ic._fallback_ops_followup_question(_sablecreek_ops(primary_growth_lever="demand")), "")

  def test_missing_is_judged_on_the_object_given_never_on_a_proposal(self):
    self.assertEqual(rf.missing_ops_fields(_sablecreek_ops()), ["primary_growth_lever"])
    self.assertEqual(rf.missing_ops_fields(_sablecreek_ops(primary_growth_lever="demand")), [])
    self.assertEqual(rf.missing_ops_fields(None), list(rf.OPS_BUSINESS_WIDE_REQUIRED))

  def test_the_wrap_guard_stands_at_both_hand_over_sites(self):
    src = open(os.path.join(ROOT, "python", "api_handlers", "intake_consult.py"), encoding="utf-8").read()
    self.assertEqual(src.count("OPS_WRAP_HELD"), 2)
    for m in re.finditer(r'next_focus = "market"\n', src):
      before = src[max(0, m.start() - 1600):m.start()]
      self.assertIn("_rf.missing_ops_fields(ops_json)", before)

  def test_the_validators_business_wide_list_is_the_shared_list(self):
    src = open(svc.__file__, encoding="utf-8").read()
    self.assertIn("operating_required = [*_rf.OPS_BUSINESS_WIDE_REQUIRED]", src)


class AClientNeverSeesARawFieldName(unittest.TestCase):
  def _payload(self, **over):
    p = {
      "draft_id": "3d57edc661fa414b959c7302a3a28d32", "client_id": "MBBIGXZ97234549600",
      "consumer_type": "b2b", "business_type": "Systems Integration Services",
      "business_name": "Sablecreek Microgrid Systems", "address": "3000 S Federal Way, Boise, ID 83706, USA",
      "first_name": "Perrine", "last_name": "Sablecreek", "email_address": "perrine@sablecreekmicrogrid.test",
      "business_start_date": "2027-02-15", "current_revenue": 5584514.4,
      "target_market_b2b_industry": "493110", "target_market_b2b_size": "100-499", "target_market_b2b_age": "0,1,2",
      "target_market_summary": "warehouses", "key_people_summary": "Perrine and Kwabena",
      "business_description_summary": "microgrids",
      "milestones": [{"description": "thirty installs", "timing": "Within the next 12 months"}],
      "lob_models": [{"lob_name": "A", "products": [{"unit_name": "x"}]}, {"lob_name": "B", "products": [{"unit_name": "y"}]}],
      "shipping_method": "on site", "sales_modality": "hybrid", "geographic_scope": "regional",
      "geographic_coverage": "Idaho", "countries": ["United States"], "capacity_driver": "labor",
      "legal_entity": "LLC",
      # primary_growth_lever deliberately absent: the Sablecreek submit
    }
    p.update(over)
    return p

  def test_the_sablecreek_submit_is_refused_in_the_clients_words(self):
    with mock.patch.object(svc, "get_mysql_connection", side_effect=AssertionError("write reached")):
      with self.assertRaises(svc.IntakeValidationError) as ctx:
        svc.process_intake_submission(self._payload())
    errors = ctx.exception.errors
    self.assertIn("primary_growth_lever", errors)
    self.assertEqual(errors["primary_growth_lever"], "the main lever you'll push first to grow is required")
    for key, msg in errors.items():
      self.assertNotIn("_", str(msg), (key, msg))

  def test_no_validator_message_carries_a_field_key(self):
    src = open(svc.__file__, encoding="utf-8").read()
    self.assertNotIn('f"{key} is required"', src)
    for m in re.finditer(r'errors\["([a-z_]+)"\] = "([^"]+)"', src):
      key, msg = m.group(1), m.group(2)
      self.assertNotIn(key, msg, (key, msg))

  def test_the_client_sentence_names_things_not_keys(self):
    s = rf.describe_missing({"primary_growth_lever": "x"})
    self.assertIn("the main lever you'll push first to grow", s)
    self.assertNotIn("_", s)
    s2 = rf.describe_missing({"primary_growth_lever": "x", "legal_entity": "y", "countries": "z"})
    self.assertIn(", and ", s2)
    self.assertNotIn("_", s2)

  def test_the_handler_returns_that_sentence_as_detail(self):
    src = open(os.path.join(ROOT, "python", "api_handlers", "financials.py"), encoding="utf-8").read()
    self.assertIn('"detail": _rf.describe_missing(exc.errors)', src)


if __name__ == "__main__":
  unittest.main()
