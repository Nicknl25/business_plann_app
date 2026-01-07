from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple


def _run() -> int:
  os.environ.setdefault("INTAKE_LANGUAGE_MODE", "off")

  # Ensure local imports resolve (expects PYTHONPATH=python/client_intake_and_finmo when running from repo root).
  from unified_intake.draft_service import apply_chat_patch_and_persist  # type: ignore

  import intake_consult_draft  # type: ignore

  writes: List[Dict[str, Any]] = []

  def fake_append_messages(conn, *, draft_id: str, new_messages: List[Dict[str, str]], **kwargs):  # type: ignore
    writes.append({"draft_id": draft_id, "new_messages": list(new_messages), "kwargs": dict(kwargs)})

  intake_consult_draft.append_messages = fake_append_messages  # type: ignore

  consult_row: Dict[str, Any] = {
    "fact_revision_nonce": 0,
    "fact_revisions_json": "[]",
    "driver_revision_nonce": 0,
    "driver_events_json": "[]",
  }

  base_business = {"name": "Tithe Financial Growth LLC", "address": "", "start_date": "2026-03"}
  ops_json: Dict[str, Any] = {"unit_name": "Business plan package", "consumer_type": "consumer"}
  market_json: Dict[str, Any] = {}
  people_json: Dict[str, Any] = {}
  financials_json: Dict[str, Any] = {}

  # 1) Marketing driver -> concept_summary updates immediately.
  marketing_model_json: Dict[str, Any] = {}
  pricing_model_json: Dict[str, Any] = {}
  revenue_model_json: Dict[str, Any] = {}
  headcount_model_json: Dict[str, Any] = {}
  fulfillment_model_json: Dict[str, Any] = {}
  ops_concept_model_json: Dict[str, Any] = {}
  milestones_model_json: Dict[str, Any] = {}
  cogs_model_json: Dict[str, Any] = {}
  gna_model_json: Dict[str, Any] = {}

  out1 = apply_chat_patch_and_persist(
    conn=None,
    draft_id="d1",
    consult_row=consult_row,
    patch={"marketing.monthly_marketing_budget": 1000},
    business_facts=dict(base_business),
    ops_json=dict(ops_json),
    market_json=dict(market_json),
    people_json=dict(people_json),
    financials_json=dict(financials_json),
    marketing_model_json=dict(marketing_model_json),
    pricing_model_json=dict(pricing_model_json),
    revenue_model_json=dict(revenue_model_json),
    headcount_model_json=dict(headcount_model_json),
    fulfillment_model_json=dict(fulfillment_model_json),
    ops_concept_model_json=dict(ops_concept_model_json),
    milestones_model_json=dict(milestones_model_json),
    cogs_model_json=dict(cogs_model_json),
    gna_model_json=dict(gna_model_json),
  )
  mk1 = out1.get("marketing_model_json") if isinstance(out1, dict) else {}
  s1 = str((mk1 or {}).get("concept_summary") or "").strip()
  if not s1:
    raise RuntimeError("marketing_model_json.concept_summary was not generated on first update.")
  if "1000" not in s1:
    # Deterministic fallback should mention the budget value.
    raise RuntimeError("marketing_model_json.concept_summary did not reflect the updated budget value.")
  if not writes or not isinstance(writes[-1].get("kwargs"), dict):
    raise RuntimeError("append_messages was not called for marketing update.")
  persisted_mk = (writes[-1]["kwargs"].get("marketing_model_json") or {})
  if not str((persisted_mk or {}).get("concept_summary") or "").strip():
    raise RuntimeError("marketing_model_json.concept_summary was not persisted in the same turn.")

  out2 = apply_chat_patch_and_persist(
    conn=None,
    draft_id="d1",
    consult_row=consult_row,
    patch={"marketing.monthly_marketing_budget": 2000},
    business_facts=dict(base_business),
    ops_json=dict(out1.get("ops_json") or ops_json),
    market_json=dict(market_json),
    people_json=dict(people_json),
    financials_json=dict(financials_json),
    marketing_model_json=dict(mk1),
    pricing_model_json=dict(pricing_model_json),
    revenue_model_json=dict(revenue_model_json),
    headcount_model_json=dict(headcount_model_json),
    fulfillment_model_json=dict(fulfillment_model_json),
    ops_concept_model_json=dict(ops_concept_model_json),
    milestones_model_json=dict(milestones_model_json),
    cogs_model_json=dict(cogs_model_json),
    gna_model_json=dict(gna_model_json),
  )
  mk2 = out2.get("marketing_model_json") if isinstance(out2, dict) else {}
  s2 = str((mk2 or {}).get("concept_summary") or "").strip()
  if not s2 or s2 == s1:
    raise RuntimeError("marketing_model_json.concept_summary did not change after budget update.")
  if "2000" not in s2:
    raise RuntimeError("marketing_model_json.concept_summary did not reflect the updated budget value (2000).")

  # 2) Ops unit_price -> pricing sync -> concept_summary updates immediately.
  out3 = apply_chat_patch_and_persist(
    conn=None,
    draft_id="d1",
    consult_row=consult_row,
    patch={"ops.unit_price": 750},
    business_facts=dict(base_business),
    ops_json=dict(out2.get("ops_json") or ops_json),
    market_json=dict(market_json),
    people_json=dict(people_json),
    financials_json=dict(financials_json),
    marketing_model_json=dict(mk2),
    pricing_model_json=dict(pricing_model_json),
    revenue_model_json=dict(revenue_model_json),
    headcount_model_json=dict(headcount_model_json),
    fulfillment_model_json=dict(fulfillment_model_json),
    ops_concept_model_json=dict(ops_concept_model_json),
    milestones_model_json=dict(milestones_model_json),
    cogs_model_json=dict(cogs_model_json),
    gna_model_json=dict(gna_model_json),
  )
  pr3 = out3.get("pricing_model_json") if isinstance(out3, dict) else {}
  ps = str((pr3 or {}).get("concept_summary") or "").strip()
  if not ps:
    raise RuntimeError("pricing_model_json.concept_summary was not generated after ops.unit_price update.")
  if "750" not in ps:
    raise RuntimeError("pricing_model_json.concept_summary did not reflect unit price 750.")

  return 0


if __name__ == "__main__":
  raise SystemExit(_run())
