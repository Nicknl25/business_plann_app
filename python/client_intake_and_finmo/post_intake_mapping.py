from __future__ import annotations

import os
import threading
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Set


try:
  from .intake_submission import get_mysql_connection
except Exception:  # pragma: no cover - supports legacy sys.path imports
  from intake_submission import get_mysql_connection  # type: ignore


_MAPPING_TABLE_NAME = "post_intak_mapping_lookup"
_FINMO_ROW_PREFIX = "finmo_json.quarter_rows[*]."
_REVENUE_PATTERN_PREFIX = "revenue::*::*::"
_ENSURE_MAPPING_TABLE_READY = False
_ENSURE_MAPPING_TABLE_LOCK = threading.Lock()


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


def _clean_bool(value: Any, *, default: bool = False) -> bool:
  raw = _clean_text(value).lower()
  if not raw:
    return bool(default)
  return raw in {"1", "true", "yes", "y", "active"}


def _split_tokens(value: Any) -> List[str]:
  raw = _clean_text(value).lower()
  if not raw:
    return []
  normalized = raw.replace(";", "|").replace(",", "|")
  return [item.strip() for item in normalized.split("|") if item.strip()]


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


def _ensure_env_loaded() -> None:
  if os.getenv("MYSQL_HOST") and os.getenv("MYSQL_USER") and (os.getenv("MYSQL_DB") or os.getenv("MYSQL_DATABASE")):
    return
  env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
  if not os.path.exists(env_path):
    return
  try:
    with open(env_path, "r", encoding="utf-8") as handle:
      for line in handle:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
          continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
  except Exception:
    return


def _ensure_mapping_lookup_table(conn) -> None:
  global _ENSURE_MAPPING_TABLE_READY
  if _ENSURE_MAPPING_TABLE_READY:
    return
  with _ENSURE_MAPPING_TABLE_LOCK:
    if _ENSURE_MAPPING_TABLE_READY:
      return
    cur = conn.cursor()
    try:
      cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_MAPPING_TABLE_NAME} (
          id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
          lever_id VARCHAR(255) NOT NULL,
          driver_category VARCHAR(64) NOT NULL,
          target_driver VARCHAR(128) NOT NULL,
          model_input_field LONGTEXT NOT NULL,
          financial_model_field VARCHAR(255) NOT NULL,
          impact_type VARCHAR(32) NOT NULL,
          post_intake_issue_codes LONGTEXT NULL,
          post_intake_phase VARCHAR(32) NOT NULL,
          control_owner VARCHAR(32) NOT NULL,
          value_kind VARCHAR(32) NOT NULL,
          input_semantics VARCHAR(64) NOT NULL,
          driver_bundle VARCHAR(64) NULL,
          cash_strategy_role VARCHAR(64) NULL,
          targeting_allowed TINYINT(1) NOT NULL DEFAULT 0,
          diagnostic_only TINYINT(1) NOT NULL DEFAULT 0,
          mapping_status VARCHAR(32) NOT NULL DEFAULT 'active',
          notes LONGTEXT NULL,
          created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
          UNIQUE KEY uniq_post_intak_mapping_lookup_lever (lever_id),
          KEY idx_post_intak_mapping_lookup_target_driver (target_driver),
          KEY idx_post_intak_mapping_lookup_phase (post_intake_phase),
          KEY idx_post_intak_mapping_lookup_status (mapping_status),
          KEY idx_post_intak_mapping_lookup_cash_role (cash_strategy_role)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
      )
      conn.commit()
      _ENSURE_MAPPING_TABLE_READY = True
    finally:
      try:
        cur.close()
      except Exception:
        pass


@lru_cache(maxsize=1)
def load_post_intake_driver_target_mapping_rows() -> List[Dict[str, Any]]:
  rows: List[Dict[str, Any]] = []
  _ensure_env_loaded()
  conn = get_mysql_connection()
  try:
    _ensure_mapping_lookup_table(conn)
    cur = conn.cursor(dictionary=True)
    try:
      cur.execute(
        f"""
        SELECT
          lever_id,
          driver_category,
          target_driver,
          model_input_field,
          financial_model_field,
          impact_type,
          post_intake_issue_codes,
          post_intake_phase,
          control_owner,
          value_kind,
          input_semantics,
          driver_bundle,
          cash_strategy_role,
          targeting_allowed,
          diagnostic_only,
          mapping_status,
          notes
        FROM {_MAPPING_TABLE_NAME}
        ORDER BY id ASC
        """
      )
      raw_rows = cur.fetchall() or []
    finally:
      try:
        cur.close()
      except Exception:
        pass
  finally:
    try:
      conn.close()
    except Exception:
      pass
  for raw_row in raw_rows:
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
      "post_intake_issue_codes": _split_tokens(raw_row.get("post_intake_issue_codes")),
      "post_intake_phase": _clean_text(raw_row.get("post_intake_phase")).lower(),
      "control_owner": _clean_text(raw_row.get("control_owner")).lower(),
      "value_kind": _clean_text(raw_row.get("value_kind")).lower(),
      "input_semantics": _clean_text(raw_row.get("input_semantics")).lower(),
      "driver_bundle": _clean_text(raw_row.get("driver_bundle")).lower(),
      "cash_strategy_role": _clean_text(raw_row.get("cash_strategy_role")).lower(),
      "targeting_allowed": _clean_bool(raw_row.get("targeting_allowed")),
      "diagnostic_only": _clean_bool(raw_row.get("diagnostic_only")),
      "mapping_status": _clean_text(raw_row.get("mapping_status")).lower() or "active",
      "notes": _clean_text(raw_row.get("notes")),
    }
    row["target_metric_name"] = _normalized_metric_id_from_field(row.get("financial_model_field"))
    row["lookup_lever_id"] = _normalized_lookup_key(lever_id)
    rows.append(row)
  if not rows:
    raise RuntimeError(f"{_MAPPING_TABLE_NAME}_empty: post-intake mapping lookup table has no rows")
  return rows


def _active_mapping_rows() -> List[Dict[str, Any]]:
  return [
    dict(row)
    for row in load_post_intake_driver_target_mapping_rows()
    if _clean_text(row.get("mapping_status")).lower() == "active"
  ]


def _phase_matches(row: Dict[str, Any], phase: Any = None) -> bool:
  requested = _clean_text(phase).lower()
  if not requested:
    return True
  row_phase = _clean_text(row.get("post_intake_phase")).lower()
  return row_phase in {requested, "both"}


@lru_cache(maxsize=1)
def post_intake_driver_target_mapping_by_lever() -> Dict[str, Dict[str, Any]]:
  mapping: Dict[str, Dict[str, Any]] = {}
  for row in _active_mapping_rows():
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


def post_intake_driver_target_metric_ids(
  *,
  phase: Any = "convergence",
  targeting_allowed_only: bool = True,
) -> List[str]:
  ordered: List[str] = []
  for row in _active_mapping_rows():
    if not _phase_matches(row, phase):
      continue
    if targeting_allowed_only and not bool(row.get("targeting_allowed")):
      continue
    if bool(row.get("diagnostic_only")):
      continue
    metric_name = _clean_text(row.get("target_metric_name")).lower()
    if metric_name and metric_name not in ordered:
      ordered.append(metric_name)
  return ordered


def post_intake_driver_target_mapping_rows_for_issue(
  issue_code: Any,
  *,
  phase: Any = None,
) -> List[Dict[str, Any]]:
  normalized_issue = _clean_text(issue_code).lower()
  if not normalized_issue:
    return []
  return [
    dict(row)
    for row in _active_mapping_rows()
    if normalized_issue in set(row.get("post_intake_issue_codes") or [])
    and _phase_matches(row, phase)
    and not bool(row.get("diagnostic_only"))
  ]


def post_intake_driver_target_lever_ids_for_issue(
  issue_code: Any,
  *,
  phase: Any = None,
) -> List[str]:
  ordered: List[str] = []
  for row in post_intake_driver_target_mapping_rows_for_issue(issue_code, phase=phase):
    lever_id = _clean_text(row.get("lever_id"))
    if lever_id and lever_id not in ordered:
      ordered.append(lever_id)
  return ordered


def post_intake_driver_target_lever_ids_for_target_drivers(
  target_drivers: Iterable[Any],
  *,
  phase: Any = None,
) -> List[str]:
  targets: Set[str] = {
    _clean_text(item).lower()
    for item in (target_drivers or [])
    if _clean_text(item)
  }
  ordered: List[str] = []
  for row in _active_mapping_rows():
    target_driver = _clean_text(row.get("target_driver")).lower()
    lever_id = _clean_text(row.get("lever_id"))
    if target_driver in targets and lever_id and _phase_matches(row, phase) and lever_id not in ordered:
      ordered.append(lever_id)
  return ordered


def post_intake_driver_target_single_lever_id_for_target_driver(
  target_driver: Any,
  *,
  phase: Any = None,
) -> str:
  target = _clean_text(target_driver).lower()
  lever_ids = post_intake_driver_target_lever_ids_for_target_drivers({target}, phase=phase)
  if len(lever_ids) != 1:
    raise RuntimeError(
      "post_intake_driver_target_mapping_single_lever_required: "
      f"target_driver={target or 'missing'} matched {len(lever_ids)} rows."
    )
  return lever_ids[0]


def post_intake_driver_target_lever_ids_for_cash_roles(
  cash_strategy_roles: Iterable[Any],
) -> List[str]:
  roles: Set[str] = {
    _clean_text(item).lower()
    for item in (cash_strategy_roles or [])
    if _clean_text(item)
  }
  ordered: List[str] = []
  for row in _active_mapping_rows():
    role = _clean_text(row.get("cash_strategy_role")).lower()
    lever_id = _clean_text(row.get("lever_id"))
    if role in roles and lever_id and _phase_matches(row, "cash_pass") and lever_id not in ordered:
      ordered.append(lever_id)
  return ordered


def post_intake_driver_target_mapping_errors(expected_lever_ids: Optional[Iterable[Any]] = None) -> List[str]:
  errors: List[str] = []
  rows = load_post_intake_driver_target_mapping_rows()
  seen_lookup_keys: set[str] = set()
  valid_phases = {"convergence", "cash_pass", "both", "derived_only"}
  valid_control_owners = {"gpt_editable", "python_derived", "cash_pass", "locked"}
  valid_statuses = {"active", "retired", "review"}
  for row in rows:
    status = _clean_text(row.get("mapping_status")).lower()
    if status not in valid_statuses:
      errors.append(f"{_clean_text(row.get('lever_id'))} has unsupported mapping_status {status}")
    if status != "active":
      continue
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
    phase = _clean_text(row.get("post_intake_phase")).lower()
    if phase not in valid_phases:
      errors.append(f"{_clean_text(row.get('lever_id'))} has unsupported post_intake_phase {phase}")
    owner = _clean_text(row.get("control_owner")).lower()
    if owner not in valid_control_owners:
      errors.append(f"{_clean_text(row.get('lever_id'))} has unsupported control_owner {owner}")
    if not _clean_text(row.get("value_kind")):
      errors.append(f"{_clean_text(row.get('lever_id'))} is missing value_kind")
    if not _clean_text(row.get("input_semantics")):
      errors.append(f"{_clean_text(row.get('lever_id'))} is missing input_semantics")
    if phase == "cash_pass" and owner not in {"cash_pass", "locked"}:
      errors.append(f"{_clean_text(row.get('lever_id'))} cash_pass row must be owned by cash_pass or locked")
    if phase == "derived_only" and owner != "python_derived":
      errors.append(f"{_clean_text(row.get('lever_id'))} derived_only row must be owned by python_derived")
  expected_lookup_keys = {
    _normalized_lookup_key(item)
    for item in (expected_lever_ids or [])
    if _clean_text(item)
  }
  missing_lookup_keys = sorted(key for key in expected_lookup_keys if key and key not in seen_lookup_keys)
  for lookup_key in missing_lookup_keys:
    errors.append(f"missing driver-target mapping for writable lever {lookup_key}")
  return errors
