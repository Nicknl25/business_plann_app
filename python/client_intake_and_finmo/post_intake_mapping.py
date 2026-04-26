from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


_MAPPING_TABLE_PATH = Path(__file__).resolve().parent / "config" / "post_intake_driver_target_mapping.csv"
_FINMO_ROW_PREFIX = "finmo_json.quarter_rows[*]."
_REVENUE_PATTERN_PREFIX = "revenue::*::*::"


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


def _normalized_metric_id_from_field(financial_model_field: Any) -> str:
  field = _clean_text(financial_model_field)
  if not field.startswith(_FINMO_ROW_PREFIX):
    return ""
  metric_name = field[len(_FINMO_ROW_PREFIX):].strip().lower()
  return metric_name


def _normalized_lookup_key(lever_id: Any) -> str:
  raw = _clean_text(lever_id)
  if raw.startswith("revenue::"):
    if raw.endswith("::Capacity"):
      return f"{_REVENUE_PATTERN_PREFIX}Capacity"
    if raw.endswith("::Unit Price"):
      return f"{_REVENUE_PATTERN_PREFIX}Unit Price"
    if raw.endswith("::Utilization"):
      return f"{_REVENUE_PATTERN_PREFIX}Utilization"
  return raw


@lru_cache(maxsize=1)
def load_post_intake_driver_target_mapping_rows() -> List[Dict[str, Any]]:
  rows: List[Dict[str, Any]] = []
  with _MAPPING_TABLE_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
    reader = csv.DictReader(handle)
    for raw_row in reader:
      if not isinstance(raw_row, dict):
        continue
      lever_id = _clean_text(raw_row.get("lever_id"))
      if not lever_id:
        continue
      row = {
        "lever_id": lever_id,
        "driver_category": _clean_text(raw_row.get("driver_category")).lower(),
        "target_driver": _clean_text(raw_row.get("target_driver")),
        "model_input_field": _clean_text(raw_row.get("model_input_field")),
        "financial_model_field": _clean_text(raw_row.get("financial_model_field")),
        "impact_type": _clean_text(raw_row.get("impact_type")).lower(),
        "notes": _clean_text(raw_row.get("notes")),
        "milestone_category": _clean_text(raw_row.get("milestone_category")).lower(),
      }
      row["target_metric_name"] = _normalized_metric_id_from_field(row.get("financial_model_field"))
      row["lookup_lever_id"] = _normalized_lookup_key(lever_id)
      rows.append(row)
  return rows


@lru_cache(maxsize=1)
def post_intake_driver_target_mapping_by_lever() -> Dict[str, Dict[str, Any]]:
  mapping: Dict[str, Dict[str, Any]] = {}
  for row in load_post_intake_driver_target_mapping_rows():
    lookup_key = str(row.get("lookup_lever_id") or "").strip()
    if lookup_key and lookup_key not in mapping:
      mapping[lookup_key] = dict(row)
  return mapping


def post_intake_driver_target_mapping_entry(lever_id: Any) -> Optional[Dict[str, Any]]:
  lookup_key = _normalized_lookup_key(lever_id)
  entry = post_intake_driver_target_mapping_by_lever().get(lookup_key)
  return dict(entry) if isinstance(entry, dict) else None


def post_intake_direct_target_metric_for_lever(lever_id: Any) -> str:
  entry = post_intake_driver_target_mapping_entry(lever_id)
  return _clean_text((entry or {}).get("target_metric_name")).lower()


def post_intake_direct_target_metric_names_for_levers(lever_ids: Optional[Iterable[Any]]) -> List[str]:
  ordered: List[str] = []
  for lever_id in (lever_ids or []):
    metric_name = post_intake_direct_target_metric_for_lever(lever_id)
    if metric_name and metric_name not in ordered:
      ordered.append(metric_name)
  return ordered


def post_intake_driver_target_metric_ids() -> List[str]:
  ordered: List[str] = []
  for row in load_post_intake_driver_target_mapping_rows():
    metric_name = _clean_text(row.get("target_metric_name")).lower()
    if metric_name and metric_name not in ordered:
      ordered.append(metric_name)
  return ordered


def post_intake_lever_ids_for_milestone_category(
  category: Any,
  *,
  available_lever_ids: Optional[Iterable[Any]] = None,
) -> List[str]:
  normalized_category = _clean_text(category).lower()
  if not normalized_category:
    return []
  available_by_lookup_key: Dict[str, List[str]] = {}
  for item in (available_lever_ids or []):
    lever_id = _clean_text(item)
    lookup_key = _normalized_lookup_key(lever_id)
    if lever_id and lookup_key:
      available_by_lookup_key.setdefault(lookup_key, []).append(lever_id)
  available_lookup_keys = set(available_by_lookup_key.keys())
  ordered: List[str] = []
  for row in load_post_intake_driver_target_mapping_rows():
    raw_categories = _clean_text(row.get("milestone_category")).lower()
    categories = {
      item.strip()
      for item in raw_categories.replace("|", ";").split(";")
      if item.strip()
    }
    if normalized_category not in categories:
      continue
    lookup_key = _clean_text(row.get("lookup_lever_id"))
    if available_lookup_keys and lookup_key not in available_lookup_keys:
      continue
    lever_ids = available_by_lookup_key.get(lookup_key) or [_clean_text(row.get("lever_id"))]
    for lever_id in lever_ids:
      if lever_id and lever_id not in ordered:
        ordered.append(lever_id)
  return ordered


def post_intake_driver_target_mapping_errors(expected_lever_ids: Optional[Iterable[Any]] = None) -> List[str]:
  errors: List[str] = []
  rows = load_post_intake_driver_target_mapping_rows()
  seen_lookup_keys: set[str] = set()
  for row in rows:
    lookup_key = _clean_text(row.get("lookup_lever_id"))
    if not lookup_key:
      errors.append("mapping row is missing lookup_lever_id")
      continue
    if lookup_key in seen_lookup_keys:
      errors.append(f"duplicate mapping row for {lookup_key}")
    seen_lookup_keys.add(lookup_key)
    metric_name = _clean_text(row.get("target_metric_name")).lower()
    if not metric_name:
      errors.append(
        f"{_clean_text(row.get('lever_id'))} has unsupported financial_model_field "
        f"{_clean_text(row.get('financial_model_field'))}"
      )
    if not _clean_text(row.get("model_input_field")):
      errors.append(f"{_clean_text(row.get('lever_id'))} is missing model_input_field")
    impact_type = _clean_text(row.get("impact_type")).lower()
    if impact_type not in {"direct", "derived"}:
      errors.append(
        f"{_clean_text(row.get('lever_id'))} has unsupported impact_type "
        f"{_clean_text(row.get('impact_type'))}"
      )
  expected_lookup_keys = {
    _normalized_lookup_key(item)
    for item in (expected_lever_ids or [])
    if _clean_text(item)
  }
  missing_lookup_keys = sorted(key for key in expected_lookup_keys if key and key not in seen_lookup_keys)
  for lookup_key in missing_lookup_keys:
    errors.append(f"missing driver-target mapping for writable lever {lookup_key}")
  return errors
