from __future__ import annotations

from typing import Any, Dict


def apply_chat_patch_and_persist(  # type: ignore[unused-argument]
  *,
  conn,
  draft_id: str,
  consult_row: Dict[str, Any],
  patch: Dict[str, Any],
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  pricing_model_json: Dict[str, Any],
  revenue_model_json: Dict[str, Any],
  headcount_model_json: Dict[str, Any],
  fulfillment_model_json: Dict[str, Any],
  ops_concept_model_json: Dict[str, Any],
  milestones_model_json: Dict[str, Any],
  cogs_model_json: Dict[str, Any],
  gna_model_json: Dict[str, Any],
) -> Dict[str, Any]:
  """
  Minimal stub for legacy callers. The unified intake flow now persists full JSON
  objects directly, so this helper only applies flat patch keys to the provided
  model blobs and returns the updated snapshot.
  """

  def _apply(model: Dict[str, Any], key_prefix: str) -> Dict[str, Any]:
    for key, value in patch.items():
      if not isinstance(key, str):
        continue
      if not key.startswith(f"{key_prefix}."):
        continue
      field = key.split(".", 1)[1].strip()
      if field:
        model[field] = value
    return model

  ops_json = _apply(ops_json, "ops")
  market_json = _apply(market_json, "market")
  people_json = _apply(people_json, "people")
  financials_json = _apply(financials_json, "financials")
  marketing_model_json = _apply(marketing_model_json, "marketing")
  pricing_model_json = _apply(pricing_model_json, "pricing")
  revenue_model_json = _apply(revenue_model_json, "revenue")
  headcount_model_json = _apply(headcount_model_json, "headcount")
  fulfillment_model_json = _apply(fulfillment_model_json, "fulfillment")
  ops_concept_model_json = _apply(ops_concept_model_json, "ops_concept")
  milestones_model_json = _apply(milestones_model_json, "milestones")
  cogs_model_json = _apply(cogs_model_json, "cogs")
  gna_model_json = _apply(gna_model_json, "gna")

  return {
    "business_facts": dict(business_facts),
    "ops_json": dict(ops_json),
    "market_json": dict(market_json),
    "people_json": dict(people_json),
    "financials_json": dict(financials_json),
    "marketing_model_json": dict(marketing_model_json),
    "pricing_model_json": dict(pricing_model_json),
    "revenue_model_json": dict(revenue_model_json),
    "headcount_model_json": dict(headcount_model_json),
    "fulfillment_model_json": dict(fulfillment_model_json),
    "ops_concept_model_json": dict(ops_concept_model_json),
    "milestones_model_json": dict(milestones_model_json),
    "cogs_model_json": dict(cogs_model_json),
    "gna_model_json": dict(gna_model_json),
  }
