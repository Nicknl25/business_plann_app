from __future__ import annotations

import copy
import json
import os
import threading
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional

from client_intake_and_finmo.intake_submission import get_mysql_connection


HEADCOUNT_POLICY_TABLE_NAME = "post_intake_headcount_policy_lookup"
PAYROLL_HEADCOUNT_DRAFT_COLUMN = "payroll_headcount"

_ENSURE_HEADCOUNT_POLICY_TABLE_READY = False
_ENSURE_HEADCOUNT_POLICY_TABLE_LOCK = threading.Lock()

_DEFAULT_HEADCOUNT_POLICY_ROWS: List[Dict[str, Any]] = [
  {
    "policy_code": "default",
    "policy_status": "active",
    "schedule_storage_table": "intake_consult_drafts",
    "schedule_storage_column": PAYROLL_HEADCOUNT_DRAFT_COLUMN,
    "schedule_contract_version": "payroll_headcount_schedule_v1",
    "schedule_horizon_quarters": 20,
    "schedule_required": True,
    "quarter_totals_required": True,
    "role_rows_required": True,
    "model_input_driver": "expenses::Payroll",
    "financial_model_field": "finmo_json.quarter_rows[*].payroll",
    "headcount_source_priority_json": [
      "client_current_num_employees",
      "gpt_role_headcount_grid",
    ],
    "wage_source_priority_json": [
      "oews_role_match",
      "oews_naics_role_fallback",
      "gpt_business_role_wage",
    ],
    "generic_oews_fallback_allowed": False,
    "generic_oews_fallback_code": "000001",
    "role_category_required": True,
    "fte_math_required": True,
    "currency_rounding": "nearest_dollar",
    "ratio_rounding": "two_decimal_places",
    "notes": (
      "Payroll is schedule-driven: GPT decides staffing rows, Python calculates "
      "quarter payroll from FTE and wage assumptions, and FINMO consumes the "
      "Payroll model-input driver. The draft column stores numeric schedule data only."
    ),
  },
]

_PAYROLL_HEADCOUNT_FORBIDDEN_TEXT_FIELDS = {
  "business_reason",
  "commentary",
  "description",
  "explanation",
  "narrative",
  "notes",
  "rationale",
  "why",
}

_PAYROLL_HEADCOUNT_ALLOWED_TEXT_FIELDS = {
  "contract_version",
  "draft_id",
  "client_id",
  "source",
  "source_table",
  "source_column",
  "role_category",
  "wage_source",
  "wage_source_code",
  "policy_code",
}

_PAYROLL_HEADCOUNT_INTEGER_CURRENCY_FIELDS = {
  "annual_wage",
  "quarterly_wage_cost",
  "quarterly_taxes_benefits",
  "total_quarterly_payroll",
  "payroll",
}

_PAYROLL_HEADCOUNT_NUMERIC_FIELDS = {
  "quarter_index",
  "starting_fte",
  "hires",
  "ending_fte",
  "payroll_taxes_benefits_percent",
  *_PAYROLL_HEADCOUNT_INTEGER_CURRENCY_FIELDS,
}


def _ensure_env_loaded() -> None:
  if os.getenv("MYSQL_HOST") and os.getenv("MYSQL_USER") and (os.getenv("MYSQL_DB") or os.getenv("MYSQL_DATABASE")):
    return
  env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))
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


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


def _clean_bool(value: Any, *, default: bool = False) -> bool:
  raw = _clean_text(value).lower()
  if not raw:
    return bool(default)
  return raw in {"1", "true", "yes", "y", "active"}


def _json_dumps_value(value: Any) -> str:
  return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _json_value(value: Any, default: Any = None) -> Any:
  if isinstance(value, (dict, list)):
    return copy.deepcopy(value)
  raw = str(value or "").strip()
  if not raw:
    return copy.deepcopy(default)
  try:
    return json.loads(raw)
  except Exception:
    return copy.deepcopy(default)


def _float_or_none(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  try:
    return float(value)
  except Exception:
    return None


def _int_or_none(value: Any) -> Optional[int]:
  number = _float_or_none(value)
  if number is None:
    return None
  try:
    return int(round(number))
  except Exception:
    return None


def _ensure_post_intake_headcount_policy_lookup_table(conn) -> None:
  global _ENSURE_HEADCOUNT_POLICY_TABLE_READY
  if _ENSURE_HEADCOUNT_POLICY_TABLE_READY:
    return
  with _ENSURE_HEADCOUNT_POLICY_TABLE_LOCK:
    if _ENSURE_HEADCOUNT_POLICY_TABLE_READY:
      return
    cur = conn.cursor()
    try:
      cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {HEADCOUNT_POLICY_TABLE_NAME} (
          id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
          policy_code VARCHAR(64) NOT NULL,
          policy_status VARCHAR(32) NOT NULL DEFAULT 'active',
          schedule_storage_table VARCHAR(128) NOT NULL,
          schedule_storage_column VARCHAR(128) NOT NULL,
          schedule_contract_version VARCHAR(128) NOT NULL,
          schedule_horizon_quarters INT NOT NULL DEFAULT 20,
          schedule_required TINYINT(1) NOT NULL DEFAULT 1,
          quarter_totals_required TINYINT(1) NOT NULL DEFAULT 1,
          role_rows_required TINYINT(1) NOT NULL DEFAULT 1,
          model_input_driver VARCHAR(255) NOT NULL,
          financial_model_field VARCHAR(255) NOT NULL,
          headcount_source_priority_json LONGTEXT NOT NULL,
          wage_source_priority_json LONGTEXT NOT NULL,
          generic_oews_fallback_allowed TINYINT(1) NOT NULL DEFAULT 0,
          generic_oews_fallback_code VARCHAR(64) NULL,
          role_category_required TINYINT(1) NOT NULL DEFAULT 1,
          fte_math_required TINYINT(1) NOT NULL DEFAULT 1,
          currency_rounding VARCHAR(64) NOT NULL DEFAULT 'nearest_dollar',
          ratio_rounding VARCHAR(64) NOT NULL DEFAULT 'two_decimal_places',
          notes LONGTEXT NULL,
          created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
          UNIQUE KEY uniq_post_intake_headcount_policy (policy_code),
          KEY idx_post_intake_headcount_policy_status (policy_status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
      )
      cur.execute(f"SELECT COUNT(*) AS row_count FROM {HEADCOUNT_POLICY_TABLE_NAME}")
      row_count = int((cur.fetchone() or [0])[0] or 0)
      bootstrap_defaults = row_count == 0
      for row in (_DEFAULT_HEADCOUNT_POLICY_ROWS if bootstrap_defaults else []):
        cur.execute(
          f"""
          INSERT INTO {HEADCOUNT_POLICY_TABLE_NAME} (
            policy_code,
            policy_status,
            schedule_storage_table,
            schedule_storage_column,
            schedule_contract_version,
            schedule_horizon_quarters,
            schedule_required,
            quarter_totals_required,
            role_rows_required,
            model_input_driver,
            financial_model_field,
            headcount_source_priority_json,
            wage_source_priority_json,
            generic_oews_fallback_allowed,
            generic_oews_fallback_code,
            role_category_required,
            fte_math_required,
            currency_rounding,
            ratio_rounding,
            notes
          ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
          ON DUPLICATE KEY UPDATE
            id = id
          """,
          (
            _clean_text(row.get("policy_code")).lower(),
            _clean_text(row.get("policy_status")).lower() or "active",
            _clean_text(row.get("schedule_storage_table")),
            _clean_text(row.get("schedule_storage_column")),
            _clean_text(row.get("schedule_contract_version")),
            int(row.get("schedule_horizon_quarters") or 20),
            1 if row.get("schedule_required") else 0,
            1 if row.get("quarter_totals_required") else 0,
            1 if row.get("role_rows_required") else 0,
            _clean_text(row.get("model_input_driver")),
            _clean_text(row.get("financial_model_field")),
            _json_dumps_value(row.get("headcount_source_priority_json") or []),
            _json_dumps_value(row.get("wage_source_priority_json") or []),
            1 if row.get("generic_oews_fallback_allowed") else 0,
            _clean_text(row.get("generic_oews_fallback_code")) or None,
            1 if row.get("role_category_required") else 0,
            1 if row.get("fte_math_required") else 0,
            _clean_text(row.get("currency_rounding")) or "nearest_dollar",
            _clean_text(row.get("ratio_rounding")) or "two_decimal_places",
            _clean_text(row.get("notes")),
          ),
        )
      conn.commit()
      _ENSURE_HEADCOUNT_POLICY_TABLE_READY = True
    finally:
      try:
        cur.close()
      except Exception:
        pass


def ensure_post_intake_headcount_policy_lookup_table(conn: Any = None) -> None:
  if conn is not None:
    _ensure_post_intake_headcount_policy_lookup_table(conn)
    return
  _ensure_env_loaded()
  owned_conn = get_mysql_connection()
  try:
    _ensure_post_intake_headcount_policy_lookup_table(owned_conn)
  finally:
    try:
      owned_conn.close()
    except Exception:
      pass


@lru_cache(maxsize=1)
def load_post_intake_headcount_policy_rows() -> List[Dict[str, Any]]:
  rows: List[Dict[str, Any]] = []
  _ensure_env_loaded()
  conn = get_mysql_connection()
  try:
    _ensure_post_intake_headcount_policy_lookup_table(conn)
    cur = conn.cursor(dictionary=True)
    try:
      cur.execute(
        f"""
        SELECT
          policy_code,
          policy_status,
          schedule_storage_table,
          schedule_storage_column,
          schedule_contract_version,
          schedule_horizon_quarters,
          schedule_required,
          quarter_totals_required,
          role_rows_required,
          model_input_driver,
          financial_model_field,
          headcount_source_priority_json,
          wage_source_priority_json,
          generic_oews_fallback_allowed,
          generic_oews_fallback_code,
          role_category_required,
          fte_math_required,
          currency_rounding,
          ratio_rounding,
          notes
        FROM {HEADCOUNT_POLICY_TABLE_NAME}
        ORDER BY policy_code ASC
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
    policy_code = _clean_text(raw_row.get("policy_code")).lower()
    if not policy_code:
      continue
    rows.append(
      {
        "policy_code": policy_code,
        "policy_status": _clean_text(raw_row.get("policy_status")).lower() or "active",
        "schedule_storage_table": _clean_text(raw_row.get("schedule_storage_table")),
        "schedule_storage_column": _clean_text(raw_row.get("schedule_storage_column")),
        "schedule_contract_version": _clean_text(raw_row.get("schedule_contract_version")),
        "schedule_horizon_quarters": int(float(raw_row.get("schedule_horizon_quarters") or 0)),
        "schedule_required": _clean_bool(raw_row.get("schedule_required"), default=True),
        "quarter_totals_required": _clean_bool(raw_row.get("quarter_totals_required"), default=True),
        "role_rows_required": _clean_bool(raw_row.get("role_rows_required"), default=True),
        "model_input_driver": _clean_text(raw_row.get("model_input_driver")),
        "financial_model_field": _clean_text(raw_row.get("financial_model_field")),
        "headcount_source_priority": _json_value(raw_row.get("headcount_source_priority_json"), []),
        "wage_source_priority": _json_value(raw_row.get("wage_source_priority_json"), []),
        "generic_oews_fallback_allowed": _clean_bool(raw_row.get("generic_oews_fallback_allowed")),
        "generic_oews_fallback_code": _clean_text(raw_row.get("generic_oews_fallback_code")),
        "role_category_required": _clean_bool(raw_row.get("role_category_required"), default=True),
        "fte_math_required": _clean_bool(raw_row.get("fte_math_required"), default=True),
        "currency_rounding": _clean_text(raw_row.get("currency_rounding")).lower(),
        "ratio_rounding": _clean_text(raw_row.get("ratio_rounding")).lower(),
        "notes": _clean_text(raw_row.get("notes")),
      }
    )
  if not rows:
    raise RuntimeError(f"{HEADCOUNT_POLICY_TABLE_NAME}_empty: headcount policy lookup table has no rows")
  return rows


class PostIntakeHeadcountPolicyLookup:
  def __init__(self, rows: Iterable[Dict[str, Any]]):
    self._rows = [dict(row) for row in rows if isinstance(row, dict)]

  def rows(self, *, active_only: bool = True) -> List[Dict[str, Any]]:
    out = [dict(row) for row in self._rows]
    if active_only:
      out = [row for row in out if _clean_text(row.get("policy_status")).lower() == "active"]
    return out

  def policy_for(self, policy_code: Any = "default", *, required: bool = True) -> Optional[Dict[str, Any]]:
    normalized = _clean_text(policy_code).lower() or "default"
    for row in self.rows(active_only=True):
      if _clean_text(row.get("policy_code")).lower() == normalized:
        return dict(row)
    if required:
      raise RuntimeError(f"{HEADCOUNT_POLICY_TABLE_NAME}_missing_policy:{normalized}")
    return None

  def validation_errors(self) -> List[str]:
    errors: List[str] = []
    rows = self.rows(active_only=False)
    active = [row for row in rows if _clean_text(row.get("policy_status")).lower() == "active"]
    if not active:
      errors.append(f"{HEADCOUNT_POLICY_TABLE_NAME}_has_no_active_rows")
    seen: set[str] = set()
    for row in rows:
      policy_code = _clean_text(row.get("policy_code")).lower()
      if not policy_code:
        errors.append(f"{HEADCOUNT_POLICY_TABLE_NAME}_row_missing_policy_code")
        continue
      if policy_code in seen:
        errors.append(f"{HEADCOUNT_POLICY_TABLE_NAME}_duplicate_policy_code:{policy_code}")
      seen.add(policy_code)
      if _clean_text(row.get("schedule_storage_table")) != "intake_consult_drafts":
        errors.append(f"{policy_code}_invalid_schedule_storage_table")
      if _clean_text(row.get("schedule_storage_column")) != PAYROLL_HEADCOUNT_DRAFT_COLUMN:
        errors.append(f"{policy_code}_invalid_schedule_storage_column")
      if int(row.get("schedule_horizon_quarters") or 0) != 20:
        errors.append(f"{policy_code}_schedule_horizon_must_be_20")
      if not _clean_text(row.get("model_input_driver")):
        errors.append(f"{policy_code}_missing_model_input_driver")
      if not _clean_text(row.get("financial_model_field")):
        errors.append(f"{policy_code}_missing_financial_model_field")
      if not isinstance(row.get("headcount_source_priority"), list) or not row.get("headcount_source_priority"):
        errors.append(f"{policy_code}_missing_headcount_source_priority")
      if not isinstance(row.get("wage_source_priority"), list) or not row.get("wage_source_priority"):
        errors.append(f"{policy_code}_missing_wage_source_priority")
    return errors


@lru_cache(maxsize=1)
def post_intake_headcount_policy_lookup() -> PostIntakeHeadcountPolicyLookup:
  return PostIntakeHeadcountPolicyLookup(load_post_intake_headcount_policy_rows())


def post_intake_headcount_policy_for(
  policy_code: Any = "default",
  *,
  required: bool = True,
) -> Optional[Dict[str, Any]]:
  return post_intake_headcount_policy_lookup().policy_for(policy_code, required=required)


def post_intake_headcount_policy_rows(*, active_only: bool = True) -> List[Dict[str, Any]]:
  return post_intake_headcount_policy_lookup().rows(active_only=active_only)


def post_intake_headcount_policy_errors() -> List[str]:
  return post_intake_headcount_policy_lookup().validation_errors()


def build_empty_payroll_headcount_payload(
  *,
  draft_id: Any = "",
  client_id: Any = "",
  policy_code: Any = "default",
) -> Dict[str, Any]:
  policy = post_intake_headcount_policy_for(policy_code=policy_code)
  horizon = int((policy or {}).get("schedule_horizon_quarters") or 20)
  return {
    "contract_version": str((policy or {}).get("schedule_contract_version") or "payroll_headcount_schedule_v1"),
    "draft_id": _clean_text(draft_id),
    "client_id": _clean_text(client_id),
    "policy_code": _clean_text(policy_code).lower() or "default",
    "source_table": "intake_consult_drafts",
    "source_column": PAYROLL_HEADCOUNT_DRAFT_COLUMN,
    "schedule_horizon_quarters": horizon,
    "rows": [],
    "quarter_totals": [
      {
        "quarter_index": quarter_index,
        "ending_fte": 0.0,
        "payroll": 0,
      }
      for quarter_index in range(1, horizon + 1)
    ],
  }


def _validate_no_prose_fields(value: Any, *, path: str, errors: List[str]) -> None:
  if isinstance(value, dict):
    for key, child in value.items():
      normalized_key = _clean_text(key).lower()
      child_path = f"{path}.{normalized_key}" if path else normalized_key
      if normalized_key in _PAYROLL_HEADCOUNT_FORBIDDEN_TEXT_FIELDS:
        errors.append(f"payroll_headcount_forbidden_text_field:{child_path}")
      if isinstance(child, str) and normalized_key not in _PAYROLL_HEADCOUNT_ALLOWED_TEXT_FIELDS:
        errors.append(f"payroll_headcount_unapproved_text_field:{child_path}")
      _validate_no_prose_fields(child, path=child_path, errors=errors)
  elif isinstance(value, list):
    for index, child in enumerate(value):
      _validate_no_prose_fields(child, path=f"{path}[{index}]", errors=errors)


def _validate_schedule_row(row: Any, *, path: str, errors: List[str]) -> None:
  if not isinstance(row, dict):
    errors.append(f"payroll_headcount_row_not_object:{path}")
    return
  quarter_index = _int_or_none(row.get("quarter_index"))
  if quarter_index is None or quarter_index < 1 or quarter_index > 20:
    errors.append(f"payroll_headcount_invalid_quarter_index:{path}")
  role_category = _clean_text(row.get("role_category"))
  if not role_category:
    errors.append(f"payroll_headcount_missing_role_category:{path}")
  for field in _PAYROLL_HEADCOUNT_NUMERIC_FIELDS:
    if field not in row:
      continue
    number = _float_or_none(row.get(field))
    if number is None:
      errors.append(f"payroll_headcount_non_numeric_{field}:{path}")
      continue
    if number < 0:
      errors.append(f"payroll_headcount_negative_{field}:{path}")
    if field in _PAYROLL_HEADCOUNT_INTEGER_CURRENCY_FIELDS and abs(number - round(number)) > 0:
      errors.append(f"payroll_headcount_currency_not_integer_{field}:{path}")
  starting = _float_or_none(row.get("starting_fte"))
  hires = _float_or_none(row.get("hires"))
  ending = _float_or_none(row.get("ending_fte"))
  if starting is not None and hires is not None and ending is not None:
    if abs((starting + hires) - ending) > 0.01:
      errors.append(f"payroll_headcount_fte_math_mismatch:{path}")


def validate_payroll_headcount_payload(
  payload: Any,
  *,
  policy_code: Any = "default",
) -> List[str]:
  policy = post_intake_headcount_policy_for(policy_code=policy_code)
  errors: List[str] = []
  if not isinstance(payload, dict):
    return ["payroll_headcount_payload_not_object"]
  _validate_no_prose_fields(payload, path="payroll_headcount", errors=errors)
  expected_version = _clean_text((policy or {}).get("schedule_contract_version"))
  if expected_version and _clean_text(payload.get("contract_version")) != expected_version:
    errors.append("payroll_headcount_contract_version_mismatch")
  expected_horizon = int((policy or {}).get("schedule_horizon_quarters") or 20)
  if int(payload.get("schedule_horizon_quarters") or 0) != expected_horizon:
    errors.append("payroll_headcount_horizon_mismatch")
  rows = payload.get("rows")
  if not isinstance(rows, list):
    errors.append("payroll_headcount_rows_not_array")
    rows = []
  for index, row in enumerate(rows):
    _validate_schedule_row(row, path=f"rows[{index}]", errors=errors)
  quarter_totals = payload.get("quarter_totals")
  if not isinstance(quarter_totals, list):
    errors.append("payroll_headcount_quarter_totals_not_array")
    quarter_totals = []
  if len(quarter_totals) != expected_horizon:
    errors.append("payroll_headcount_quarter_totals_must_cover_20q")
  seen_quarters: set[int] = set()
  for index, item in enumerate(quarter_totals):
    if not isinstance(item, dict):
      errors.append(f"payroll_headcount_quarter_total_not_object:{index}")
      continue
    quarter_index = _int_or_none(item.get("quarter_index"))
    if quarter_index is None or quarter_index < 1 or quarter_index > expected_horizon:
      errors.append(f"payroll_headcount_quarter_total_invalid_quarter:{index}")
    else:
      seen_quarters.add(quarter_index)
    for field in ("ending_fte", "payroll"):
      number = _float_or_none(item.get(field))
      if number is None:
        errors.append(f"payroll_headcount_quarter_total_missing_{field}:{index}")
        continue
      if number < 0:
        errors.append(f"payroll_headcount_quarter_total_negative_{field}:{index}")
      if field == "payroll" and abs(number - round(number)) > 0:
        errors.append(f"payroll_headcount_quarter_total_payroll_not_integer:{index}")
  if seen_quarters != set(range(1, expected_horizon + 1)):
    errors.append("payroll_headcount_quarter_totals_missing_required_quarters")
  return errors
