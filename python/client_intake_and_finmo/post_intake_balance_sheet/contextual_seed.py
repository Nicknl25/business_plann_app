"""Business-context balance-sheet driver seeding.

This module owns the deterministic side of the balance-sheet seed contract:
mapping-table candidates, payload validation, and model_input application.
GPT decides business-specific seed values; Python applies them.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
  post_intake_driver_formula_contract_rows,
)


BALANCE_SHEET_CONTEXTUAL_SEED_CONTRACT_NAME = "balance_sheet_contextual_seed"
BALANCE_SHEET_CONTEXTUAL_SEED_POLICY_KEY = "balance_sheet_contextual_seed"
HORIZON = 20


def _clean(value: Any) -> str:
  return str(value or "").strip()


def _lower(value: Any) -> str:
  return _clean(value).lower()


def _safe_float(value: Any) -> Optional[float]:
  try:
    if value is None or value == "":
      return None
    number = float(value)
  except Exception:
    return None
  if number != number:
    return None
  return number


def _clean_list(value: Any) -> List[str]:
  if not isinstance(value, list):
    return []
  return [
    _clean(item).lower()
    for item in value
    if _clean(item)
  ]


def _live_values(row: Dict[str, Any], *, horizon: int = HORIZON) -> List[Any]:
  values = list(row.get("values") or [])
  if len(values) >= horizon + 1:
    return values[1 : horizon + 1]
  return values[:horizon]


def _compose_period_values(*, stub_value: Any, live_values: List[float]) -> List[float]:
  return [float(_safe_float(stub_value) or 0.0), *[round(float(value), 6) for value in live_values[:HORIZON]]]


def _iter_model_input_rows(model_input_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  rows: List[Dict[str, Any]] = []
  for section_name in ("revenue", "expenses", "balance_sheet"):
    section_rows = sections.get(section_name)
    if isinstance(section_rows, list):
      rows.extend(row for row in section_rows if isinstance(row, dict))
  return rows


def _find_row_for_lever(model_input_json: Optional[Dict[str, Any]], lever_id: str) -> Optional[Dict[str, Any]]:
  for row in _iter_model_input_rows(model_input_json):
    if _clean(row.get("lever_id")) == lever_id:
      return row
  return None


def balance_sheet_contextual_seed_candidate_rows() -> List[Dict[str, Any]]:
  """Return mapping-table rows that require contextual seeding when applicable."""
  rows: List[Dict[str, Any]] = []
  for row in post_intake_driver_formula_contract_rows():
    if not isinstance(row, dict):
      continue
    lever_id = _clean(row.get("lever_id"))
    if not lever_id.startswith("balance_sheet::"):
      continue
    if _lower(row.get("driver_bundle")) != "working_capital_bundle":
      continue
    if _lower(row.get("forecast_presence_rule_key")) != "positive_driver_when_applicable":
      continue
    rows.append(copy.deepcopy(row))
  if not rows:
    raise RuntimeError(
      "balance_sheet_contextual_seed_candidates_missing: "
      "sql.post_intak_mapping_lookup must define active balance-sheet seed candidate rows."
    )
  return rows


def _candidate_by_lever() -> Dict[str, Dict[str, Any]]:
  return {
    _clean(row.get("lever_id")): row
    for row in balance_sheet_contextual_seed_candidate_rows()
    if _clean(row.get("lever_id"))
  }


def _bounds_for_row(row: Dict[str, Any]) -> tuple[float, float]:
  minimum = _safe_float(row.get("minimum_live_value"))
  maximum = _safe_float(row.get("maximum_live_value"))
  if minimum is None:
    raise RuntimeError(f"balance_sheet_contextual_seed_min_bound_missing: {row.get('lever_id')}")
  if maximum is None:
    raise RuntimeError(f"balance_sheet_contextual_seed_max_bound_missing: {row.get('lever_id')}")
  if float(maximum) < float(minimum):
    raise RuntimeError(
      f"balance_sheet_contextual_seed_bounds_invalid: {row.get('lever_id')} min={minimum} max={maximum}"
    )
  return float(minimum), float(maximum)


def validate_balance_sheet_contextual_seed_payload(
  payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  """Validate GPT's contextual balance-sheet seed contract against mapping table."""
  candidate_map = _candidate_by_lever()
  source = payload if isinstance(payload, dict) else {}
  rows = [row for row in (source.get("balance_sheet_seed_grid") or []) if isinstance(row, dict)]
  if not rows:
    raise RuntimeError("balance_sheet_contextual_seed_contract_empty: balance_sheet_seed_grid is required.")
  seen: set[str] = set()
  normalized_rows: List[Dict[str, Any]] = []
  errors: List[str] = []
  for item in rows:
    lever_id = _clean(item.get("lever_id"))
    if lever_id not in candidate_map:
      errors.append(f"unsupported_lever_id={lever_id}")
      continue
    if lever_id in seen:
      errors.append(f"duplicate_lever_id={lever_id}")
      continue
    seen.add(lever_id)
    mapping_row = candidate_map[lever_id]
    applicable = bool(item.get("applicable"))
    seed_value = _safe_float(item.get("seed_value"))
    mapping_value_kind = _lower(mapping_row.get("value_kind"))
    value_kind = _lower(item.get("value_kind")) or mapping_value_kind
    minimum, maximum = _bounds_for_row(mapping_row)
    if value_kind != mapping_value_kind:
      errors.append(f"{lever_id}:value_kind_mismatch expected={mapping_value_kind} actual={value_kind}")
    if applicable:
      if seed_value is None:
        errors.append(f"{lever_id}:seed_value_missing_when_applicable")
      elif float(seed_value) < minimum or float(seed_value) > maximum:
        errors.append(f"{lever_id}:seed_value_out_of_bounds value={seed_value} min={minimum} max={maximum}")
    else:
      seed_value = 0.0
    normalized_rows.append(
      {
        "lever_id": lever_id,
        "target_driver": _clean(mapping_row.get("target_driver")),
        "value_kind": value_kind,
        "input_semantics": _lower(mapping_row.get("input_semantics")),
        "business_applicability_key": _lower(mapping_row.get("business_applicability_key")),
        "applicability_positive_tokens": _clean_list(mapping_row.get("applicability_positive_tokens")),
        "applicability_negative_tokens": _clean_list(mapping_row.get("applicability_negative_tokens")),
        "applicable": bool(applicable),
        "seed_value": round(float(seed_value or 0.0), 6),
        "minimum_live_value": minimum,
        "maximum_live_value": maximum,
        "rationale": _clean(item.get("rationale")),
        "source_of_truth": "sql.post_intak_mapping_lookup + sql.post_intake_gpt_contract_lookup",
      }
    )
  missing = sorted(set(candidate_map.keys()) - seen)
  if missing:
    errors.append(f"missing_candidate_rows={missing}")
  if errors:
    raise RuntimeError(
      "balance_sheet_contextual_seed_contract_invalid: " + "; ".join(errors[:20])
    )
  return {
    "contract_version": _clean(source.get("contract_version")) or "balance_sheet_contextual_seed_v1",
    "balance_sheet_seed_grid": normalized_rows,
    "rationale": _clean(source.get("rationale")),
    "source_of_truth": "sql.post_intake_gpt_contract_lookup",
  }


def apply_balance_sheet_contextual_seed_to_model_input(
  model_input_json: Optional[Dict[str, Any]],
  payload: Optional[Dict[str, Any]],
  *,
  live_count: int = HORIZON,
) -> Dict[str, Any]:
  """Apply validated contextual seed values to balance-sheet model-input rows."""
  validated = validate_balance_sheet_contextual_seed_payload(payload)
  next_payload = copy.deepcopy(model_input_json if isinstance(model_input_json, dict) else {})
  sections = next_payload.get("sections") if isinstance(next_payload.get("sections"), dict) else {}
  if not isinstance(sections, dict):
    raise RuntimeError("balance_sheet_contextual_seed_model_input_sections_missing")
  applied_rows: List[Dict[str, Any]] = []
  for seed_row in validated["balance_sheet_seed_grid"]:
    lever_id = _clean(seed_row.get("lever_id"))
    model_row = _find_row_for_lever(next_payload, lever_id)
    if not isinstance(model_row, dict):
      raise RuntimeError(f"balance_sheet_contextual_seed_model_input_row_missing: {lever_id}")
    values = list(model_row.get("values") or [])
    stub_value = values[0] if values else 0.0
    existing_live = _live_values(model_row, horizon=live_count)
    seed_value = float(_safe_float(seed_row.get("seed_value")) or 0.0)
    live_values: List[float] = []
    for idx in range(max(0, live_count)):
      existing = _safe_float(existing_live[idx]) if idx < len(existing_live) else None
      if bool(seed_row.get("applicable")):
        live_values.append(round(seed_value, 6))
      else:
        live_values.append(round(float(existing or 0.0), 6))
    model_row["values"] = _compose_period_values(stub_value=stub_value, live_values=live_values)
    model_row["derived_driver"] = BALANCE_SHEET_CONTEXTUAL_SEED_POLICY_KEY
    model_row["balance_sheet_contextual_seed"] = copy.deepcopy(seed_row)
    applied_rows.append(
      {
        "lever_id": lever_id,
        "applicable": bool(seed_row.get("applicable")),
        "seed_value": round(seed_value, 6),
      }
    )
  next_payload.setdefault("derived_driver_policies", {})
  if isinstance(next_payload.get("derived_driver_policies"), dict):
    next_payload["derived_driver_policies"][BALANCE_SHEET_CONTEXTUAL_SEED_POLICY_KEY] = validated
  next_payload.setdefault("derived_driver_runtime", {})
  if isinstance(next_payload.get("derived_driver_runtime"), dict):
    next_payload["derived_driver_runtime"][BALANCE_SHEET_CONTEXTUAL_SEED_POLICY_KEY] = {
      "source_contract": BALANCE_SHEET_CONTEXTUAL_SEED_CONTRACT_NAME,
      "applied_rows": applied_rows,
    }
  return next_payload
