from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

from unified_intake.parsing import parse_json_dict as _parse_json_dict
from unified_intake.proposals import build_proposals_from_patch


_DEPENDENCY_RULES: Tuple[Tuple[str, Set[str], Set[str]], ...] = (
  ("ops", {"unit_name", "unit_price", "units_per_week_capacity", "starting_revenue"}, {"revenue", "cogs"}),
  ("pricing", {"unit_price"}, {"revenue", "cogs"}),
  (
    "revenue",
    {"units_per_week_capacity", "avg_units_per_week_year1", "utilization_rate", "operating_weeks_per_year", "unit_price"},
    {"cogs"},
  ),
  ("fulfillment", {"fulfillment_model", "who_fulfills", "lead_time"}, {"revenue", "cogs"}),
  ("headcount", {"roles"}, {"revenue"}),
)

_DEPENDENT_PROPOSAL_KEYS: Dict[str, Tuple[str, ...]] = {
  "revenue": ("units_per_week_capacity", "avg_units_per_week_year1", "operating_weeks_per_year", "unit_price"),
  "fulfillment": ("fulfillment_model", "who_fulfills", "lead_time"),
  "ops_concept": ("operating_unit", "primary_constraint", "process_overview"),
  "milestones": ("milestones",),
  "cogs": (
    "cost_per_unit",
    "materials_cost_per_unit",
    "direct_fulfillment_cost_per_unit",
    "other_variable_cost_per_unit",
    "cogs_percent_of_revenue",
    "production",
  ),
  "gna": (
    "monthly_rent_expense",
    "monthly_software_expense",
    "monthly_insurance_expense",
    "monthly_utilities_expense",
    "monthly_admin_expense",
    "other_operating_expense",
    "other_monthly_debt_payments",
  ),
  "marketing": ("monthly_marketing_budget", "primary_channels"),
  "headcount": ("roles",),
  "pricing": ("unit_price",),
}


def _collect_dependents(patch: Dict[str, Any]) -> Set[str]:
  dependents: Set[str] = set()
  for raw_key in (patch or {}).keys():
    key = str(raw_key or "").strip()
    if key.count(".") != 1:
      continue
    group, field = key.split(".", 1)
    group = group.strip().lower()
    field = field.strip()
    for src, fields, targets in _DEPENDENCY_RULES:
      if group != src:
        continue
      if fields and field not in fields:
        continue
      dependents.update(targets)
  return dependents


def _driver_patch_from_card(model: str, card: Dict[str, Any]) -> Dict[str, Any]:
  keys = _DEPENDENT_PROPOSAL_KEYS.get(model, ())
  if not keys:
    return {}
  lobs = card.get("lobs")
  if not isinstance(lobs, list) or not lobs:
    return {}
  lob = next((l for l in lobs if isinstance(l, dict) and str(l.get("lob_key") or "") == "company_total"), None)
  if not isinstance(lob, dict):
    return {}
  drivers = lob.get("drivers") if isinstance(lob.get("drivers"), dict) else {}
  patch: Dict[str, Any] = {}
  for key in keys:
    entry = drivers.get(key) if isinstance(drivers, dict) else None
    if not isinstance(entry, dict):
      continue
    if entry.get("value") is None:
      continue
    patch[f"{model}.{key}"] = {
      "lob_key": "company_total",
      "value": entry.get("value"),
      "unit": entry.get("unit"),
      "time_basis": entry.get("time_basis"),
      "rationale": entry.get("rationale"),
    }
  return patch


def dependency_proposals_for_patch(
  *,
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
) -> List[Dict[str, Any]]:
  dependents = _collect_dependents(patch)
  if not dependents:
    return []

  cards_by_model: Dict[str, Dict[str, Any]] = {
    "marketing": _parse_json_dict(marketing_model_json),
    "pricing": _parse_json_dict(pricing_model_json),
    "revenue": _parse_json_dict(revenue_model_json),
    "headcount": _parse_json_dict(headcount_model_json),
    "fulfillment": _parse_json_dict(fulfillment_model_json),
    "ops_concept": _parse_json_dict(ops_concept_model_json),
    "milestones": _parse_json_dict(milestones_model_json),
    "cogs": _parse_json_dict(cogs_model_json),
    "gna": _parse_json_dict(gna_model_json),
  }

  proposals: List[Dict[str, Any]] = []
  for model in sorted(dependents):
    card = cards_by_model.get(model) if isinstance(cards_by_model.get(model), dict) else {}
    patch_from_card = _driver_patch_from_card(model, card)
    if not patch_from_card:
      continue
    proposals.extend(
      build_proposals_from_patch(
        patch=patch_from_card,
        business_facts=business_facts,
        ops_json=ops_json,
        market_json=market_json,
        people_json=people_json,
        financials_json=financials_json,
        marketing_model_json=marketing_model_json,
        pricing_model_json=pricing_model_json,
        revenue_model_json=revenue_model_json,
        headcount_model_json=headcount_model_json,
        fulfillment_model_json=fulfillment_model_json,
        ops_concept_model_json=ops_concept_model_json,
        milestones_model_json=milestones_model_json,
        cogs_model_json=cogs_model_json,
        gna_model_json=gna_model_json,
        source="dependency",
      )
    )
  return proposals
