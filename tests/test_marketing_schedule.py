"""The marketing schedule's four class rules, and the tie-back.

R-MKTG-03 phase 1. These import the production module — they never restate its
arithmetic — so an edit to the real decomposition is felt here.

The rules exist because all four shapes are real: measured across 400 drafts,
production carries consumer, b2b and mixed businesses, a business whose stated
marketing is zero, and pre-revenue businesses. A Harrow-shaped test would pass
while three of those shapes broke.
"""
from __future__ import annotations

import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (REPO, os.path.join(REPO, "python")):
  if path not in sys.path:
    sys.path.insert(0, path)

from client_intake_and_finmo.post_intake_marketing.schedule import (  # noqa: E402
  EPSILON_NEW_CUSTOMERS,
  compute_marketing_schedule,
)

RETENTION_OK = {"ok": True, "retention_rate": 0.72, "rationale": "test",
                "confidence_tier": "low", "model": "test"}


def _finmo(revenue, marketing):
  return {"pl": [{"label": "Revenue", "values": list(revenue)},
                 {"label": "Marketing", "values": list(marketing)}]}


def _model_input(percents):
  return {"sections": {"expenses": [
    {"lever_id": "expenses::Marketing", "label": "Marketing",
     "value_kind": "ratio", "values": list(percents)},
  ]}}


def _ops(capacity=150.0, utilisation=0.7, periods=52.0, price=86.0):
  return {"lob_models": [{"lob_name": "Primary", "products": [{
    "product_name": "service", "unit_price": price,
    "units_per_period_capacity": capacity, "utilization_rate": utilisation,
    "operating_periods_per_year": periods}]}]}


def _audience(units=7053.0, customers=650.0, basis="consumer"):
  return {"expected_units_year1": units,
          "expected_customers_or_clients_year1": customers,
          "market_basis_type": basis, "reachable_market": 8500.0}


def _flat_plan(percent=0.018, revenue=125000.0, n=21):
  rev = [revenue] * n
  pct = [percent] * n
  mkt = [round(revenue * percent, 6)] * n
  return _finmo(rev, mkt), _model_input(pct), mkt


class TieBackTests(unittest.TestCase):
  """The whole design rests on this: the percent is decomposed, never
  recomputed, so it cannot drift."""

  def test_the_payload_carries_the_settled_percent_verbatim(self):
    fin, mi, _ = _flat_plan(percent=0.0177777777777)
    out = compute_marketing_schedule(
      finmo_json=fin, model_input_json=mi, operating_model_json=_ops(),
      marketing_model_json=_audience(), retention_judgment=RETENTION_OK)
    for row in out["periods"]:
      self.assertEqual(row["marketing_percent_of_revenue"], 0.0177777777777,
                       "the settled value must be carried, not re-derived")

  def test_the_dollars_are_consistent_with_the_settled_percent(self):
    fin, mi, _ = _flat_plan()
    out = compute_marketing_schedule(
      finmo_json=fin, model_input_json=mi, operating_model_json=_ops(),
      marketing_model_json=_audience(), retention_judgment=RETENTION_OK)
    self.assertTrue(out["tie_back"]["exact"])
    self.assertLess(out["tie_back"]["max_abs_delta"], 1e-9)


class ClassRuleTests(unittest.TestCase):

  def test_R1_retention_of_one_never_divides_by_zero(self):
    """A client typing 100% retention on a flat plan makes new customers zero.
    That is not exotic and it must not produce #DIV/0! or an absurd CAC."""
    fin, mi, _ = _flat_plan()
    out = compute_marketing_schedule(
      finmo_json=fin, model_input_json=mi, operating_model_json=_ops(),
      marketing_model_json=_audience(),
      retention_judgment={"ok": True, "retention_rate": 1.0, "rationale": "t",
                          "confidence_tier": "low", "model": "t"})
    offenders = [p for p in out["periods"]
                 if p["new_customers"] is not None
                 and p["new_customers"] < EPSILON_NEW_CUSTOMERS
                 and p["customer_acquisition_cost"] is not None]
    self.assertEqual(offenders, [], "divided into a ~zero new-customer count")

  def test_R1_a_NEARLY_zero_new_customer_count_is_also_refused(self):
    """The one that matters, and the one a weaker test misses.

    Retention of exactly 1.0 makes new customers exactly 0.0, which even a
    naive `!= 0` guard survives — I wrote that weaker test first and a tamper
    proved it toothless. The real hazard is a count that is TINY BUT POSITIVE:
    retention 0.999 on a flat plan leaves ~0.16 new customers a quarter, and
    dividing marketing into that produces a CAC in the tens of thousands —
    a number a client would quote. The epsilon floor exists for this case.
    """
    fin, mi, _ = _flat_plan()
    out = compute_marketing_schedule(
      finmo_json=fin, model_input_json=mi, operating_model_json=_ops(),
      marketing_model_json=_audience(),
      retention_judgment={"ok": True, "retention_rate": 0.999, "rationale": "t",
                          "confidence_tier": "low", "model": "t"})
    live = [p for p in out["periods"] if p["is_stub"] is False]
    tiny = [p for p in live if 0 < (p["new_customers"] or 0) < EPSILON_NEW_CUSTOMERS]
    self.assertTrue(tiny, "fixture no longer produces a tiny new-customer count")
    for row in tiny:
      self.assertIsNone(
        row["customer_acquisition_cost"],
        f"CAC computed on {row['new_customers']:.4f} new customers — "
        f"that is an absurd number in a client's hands")

  def test_R2_zero_marketing_yields_no_cac(self):
    fin, mi, _ = _flat_plan()
    for row in fin["pl"]:
      if row["label"] == "Marketing":
        row["values"] = [0.0] * len(row["values"])
    out = compute_marketing_schedule(
      finmo_json=fin, model_input_json=_model_input([0.0] * 21),
      operating_model_json=_ops(), marketing_model_json=_audience(),
      retention_judgment=RETENTION_OK)
    self.assertEqual(out["schedule_class"], "zero_marketing")
    self.assertTrue(all(p["customer_acquisition_cost"] is None for p in out["periods"]))

  def test_R3_pre_revenue_stub_needs_no_special_case(self):
    """Stub revenue 0 means stub customers 0, so Q1's new customers equal its
    customers and CAC is simply first-quarter CAC. It must not crash and must
    not be mistaken for a defect."""
    rev = [0.0] + [125000.0] * 20
    pct = [0.018] * 21
    mkt = [r * 0.018 for r in rev]
    out = compute_marketing_schedule(
      finmo_json=_finmo(rev, mkt), model_input_json=_model_input(pct),
      operating_model_json=_ops(), marketing_model_json=_audience(),
      retention_judgment=RETENTION_OK)
    self.assertEqual(out["status"], "ok")
    stub, q1 = out["periods"][0], out["periods"][1]
    self.assertEqual(stub["customers"], 0.0)
    self.assertEqual(q1["new_customers"], q1["customers"],
                     "with a zero stub, every Q1 customer is new")

  def test_R4_no_entity_count_degrades_to_the_exact_half(self):
    """A referral-dominant business has no usable audience. The schedule must
    show what it knows and say the rest is not modelled — never invent one."""
    fin, mi, _ = _flat_plan()
    out = compute_marketing_schedule(
      finmo_json=fin, model_input_json=mi, operating_model_json=_ops(),
      marketing_model_json={}, retention_judgment=RETENTION_OK)
    self.assertEqual(out["schedule_class"], "not_modelled")
    for row in out["periods"]:
      self.assertIsNotNone(row["marketing_dollars"], "exact lines must survive")
      self.assertIsNone(row["customer_acquisition_cost"])

  def test_a_failed_gpt_call_degrades_rather_than_defaulting(self):
    """A wrong retention would propagate into four of eight lines. Better to
    show the exact half than to substitute a silent default."""
    fin, mi, _ = _flat_plan()
    out = compute_marketing_schedule(
      finmo_json=fin, model_input_json=mi, operating_model_json=_ops(),
      marketing_model_json=_audience(),
      retention_judgment={"ok": False, "error": "openai_api_key_unset"})
    self.assertEqual(out["schedule_class"], "not_modelled")
    self.assertFalse(out["assumptions"]["retention"]["available"])
    self.assertTrue(all(p["revenue"] is not None for p in out["periods"]))


class DisclosureTests(unittest.TestCase):
  """Nick's ruling: a GPT estimate is not a citation and must not wear one."""

  def test_retention_is_labelled_an_expert_estimate_not_a_source(self):
    fin, mi, _ = _flat_plan()
    out = compute_marketing_schedule(
      finmo_json=fin, model_input_json=mi, operating_model_json=_ops(),
      marketing_model_json=_audience(), retention_judgment=RETENTION_OK)
    meta = out["assumptions"]["retention"]
    self.assertEqual(meta["basis"], "ASSUMPTION")
    self.assertEqual(meta["basis_detail"], "expert_estimate")
    self.assertNotIn("source_citation", meta)
    self.assertNotIn("as_of", meta)

  def test_cac_is_marked_assumed_and_the_exact_lines_are_marked_exact(self):
    fin, mi, _ = _flat_plan()
    out = compute_marketing_schedule(
      finmo_json=fin, model_input_json=mi, operating_model_json=_ops(),
      marketing_model_json=_audience(), retention_judgment=RETENTION_OK)
    ex = out["exactness"]
    self.assertEqual(ex["customer_acquisition_cost"], "assumed")
    self.assertEqual(ex["new_customers"], "assumed")
    for line in ("revenue", "marketing_dollars", "marketing_percent_of_revenue", "units"):
      self.assertEqual(ex[line], "exact")


class BasisAgnosticTests(unittest.TestCase):
  """market_basis_type changes the noun, never the arithmetic."""

  def test_b2b_and_consumer_produce_identical_numbers(self):
    fin, mi, _ = _flat_plan()
    kw = dict(finmo_json=fin, model_input_json=mi, operating_model_json=_ops(),
              retention_judgment=RETENTION_OK)
    consumer = compute_marketing_schedule(marketing_model_json=_audience(basis="consumer"), **kw)
    b2b = compute_marketing_schedule(marketing_model_json=_audience(basis="b2b"), **kw)
    self.assertEqual([p["customer_acquisition_cost"] for p in consumer["periods"]],
                     [p["customer_acquisition_cost"] for p in b2b["periods"]])
    self.assertEqual(consumer["context"]["entity_noun"], "customers")
    self.assertEqual(b2b["context"]["entity_noun"], "firms")


if __name__ == "__main__":
  unittest.main()
