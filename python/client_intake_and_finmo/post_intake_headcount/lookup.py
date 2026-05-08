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
    "decision_source_required": True,
    "required_decision_source": "payroll_headcount_schedule.payroll_headcount_grid",
    "schedule_horizon_quarters": 20,
    "schedule_required": True,
    "quarter_totals_required": True,
    "model_input_driver": "expenses::Payroll",
    "financial_model_field": "finmo_json.quarter_rows[*].payroll",
    "headcount_source_priority_json": [
      "gpt_oews_title_fte_grid",
    ],
    "headcount_economic_basis": "capacity_units_per_supporting_fte",
    "min_capacity_coverage_ratio": 1.0,
    "utilization_pressure_threshold": 0.85,
    "annual_wage_inflation_rate": 0.03,
    "capacity_labor_model_values_json": [
      "labor_driven",
      "hybrid",
      "system_driven",
      "expert_driven",
    ],
    "labor_intensity_class_values_json": [
      "low",
      "medium",
      "high",
      "expert",
    ],
    "wage_positioning_multiplier_json": {
      "floor": {"min": 1.00, "max": 1.10},
      "market": {"min": 1.10, "max": 1.40},
      "premium": {"min": 1.35, "max": 1.80},
      "specialized": {"min": 1.70, "max": 2.50},
    },
    "wage_source_priority_json": [
      "oews_title_catalog_exact_naics_state",
      "oews_title_catalog_exact_naics_us",
    ],
    "generic_oews_fallback_allowed": False,
    "generic_oews_fallback_code": "000001",
    "salary_basis": "oews_title_catalog_selected_title",
    "min_wage_benchmark_ratio": 0.75,
    "min_payroll_tax_benefits_pct": 0.12,
    "default_payroll_tax_benefits_pct": 0.22,
    "max_payroll_tax_benefits_pct": 0.35,
    "min_annual_wage": 25000,
    "max_oews_title_rows_per_quarter": 20,
    "revenue_driver_context_required": True,
    "min_payroll_percent_of_revenue": 0.08,
    "max_payroll_percent_of_revenue": 0.80,
    "payroll_revenue_sanity_bounds_json": {
      "low": {"min_pct": 0.06, "max_pct": 0.45},
      "medium": {"min_pct": 0.10, "max_pct": 0.55},
      "high": {"min_pct": 0.16, "max_pct": 0.70},
      "expert": {"min_pct": 0.18, "max_pct": 0.80},
    },
    "payroll_revenue_sanity_tolerance_pct": 0.03,
    "payroll_revenue_sanity_relative_tolerance": 0.20,
    "payroll_trend_rules_json": {
      "capacity_primary": True,
      "use_revenue_as_sanity_not_driver": True,
      "average_fte_cannot_decline_when_capacity_increases": True,
      "average_fte_cannot_decline_when_utilization_increases": True,
      "payroll_dollars_cannot_decline_when_revenue_increases": True,
    },
    "fte_math_required": True,
    "currency_rounding": "nearest_dollar",
    "ratio_rounding": "two_decimal_places",
    "notes": (
      "Payroll is schedule-driven and capacity-primary. GPT decides labor model, "
      "intensity, wage positioning, capacity utilization, and exact OEWS-title/FTE rows "
      "inside payroll_headcount_schedule. Python calculates OEWS-grounded wages, "
      "3 percent annual wage inflation, FTE floors from capacity/utilization, and "
      "FINMO consumes only the Payroll model-input driver. Reasonableness is checked against "
      "GPT's own payroll/revenue sanity target, not universal capacity-per-FTE bounds."
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
  "decision_source",
  "source",
  "source_table",
  "source_column",
  "staffing_class",
  "headcount_economic_basis",
  "capacity_labor_model",
  "labor_intensity_class",
  "wage_positioning_tier",
  "position_title",
  "person_name",
  "oews_occ_title",
  "oews_occ_code",
  "oews_matched_title",
  "oews_match_basis",
  "wage_source",
  "wage_source_code",
  "policy_code",
  "source_context",
  "adjustment_kind",
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
  "capacity_units_per_supporting_fte",
  "wage_positioning_multiplier",
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


def _contract_forecast_horizon_quarters() -> int:
  try:
    from client_intake_and_finmo.post_intake_mapping import post_intake_contract_forecast_horizon_quarter_count  # type: ignore
    value = int(
      post_intake_contract_forecast_horizon_quarter_count(
        contract_name="payroll_headcount_schedule",
      )
      or 0
    )
  except Exception:
    value = 0
  return value if value > 0 else 20


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
          decision_source_required TINYINT(1) NOT NULL DEFAULT 1,
          required_decision_source VARCHAR(128) NOT NULL DEFAULT 'payroll_headcount_schedule.payroll_headcount_grid',
          schedule_horizon_quarters INT NOT NULL DEFAULT 20,
          schedule_required TINYINT(1) NOT NULL DEFAULT 1,
          quarter_totals_required TINYINT(1) NOT NULL DEFAULT 1,
          model_input_driver VARCHAR(255) NOT NULL,
          financial_model_field VARCHAR(255) NOT NULL,
          headcount_source_priority_json LONGTEXT NOT NULL,
          headcount_economic_basis VARCHAR(128) NOT NULL DEFAULT 'capacity_units_per_supporting_fte',
          min_capacity_coverage_ratio DECIMAL(10,4) NOT NULL DEFAULT 1.0000,
          utilization_pressure_threshold DECIMAL(10,4) NOT NULL DEFAULT 0.8500,
          annual_wage_inflation_rate DECIMAL(10,4) NOT NULL DEFAULT 0.0300,
          capacity_labor_model_values_json LONGTEXT NOT NULL,
          labor_intensity_class_values_json LONGTEXT NOT NULL,
          wage_positioning_multiplier_json LONGTEXT NOT NULL,
          wage_source_priority_json LONGTEXT NOT NULL,
          generic_oews_fallback_allowed TINYINT(1) NOT NULL DEFAULT 0,
          generic_oews_fallback_code VARCHAR(64) NULL,
          salary_basis VARCHAR(128) NOT NULL DEFAULT 'oews_all_occupations_mean',
          min_wage_benchmark_ratio DECIMAL(10,4) NOT NULL DEFAULT 0.7500,
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
      for ddl in [
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN min_payroll_tax_benefits_pct DECIMAL(10,4) NOT NULL DEFAULT 0.1200 AFTER generic_oews_fallback_code",
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN default_payroll_tax_benefits_pct DECIMAL(10,4) NOT NULL DEFAULT 0.2200 AFTER min_payroll_tax_benefits_pct",
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN max_payroll_tax_benefits_pct DECIMAL(10,4) NOT NULL DEFAULT 0.3500 AFTER default_payroll_tax_benefits_pct",
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN min_annual_wage DECIMAL(14,2) NOT NULL DEFAULT 25000.00 AFTER max_payroll_tax_benefits_pct",
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN max_oews_title_rows_per_quarter INT NOT NULL DEFAULT 20 AFTER min_annual_wage",
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN revenue_driver_context_required TINYINT(1) NOT NULL DEFAULT 1 AFTER max_oews_title_rows_per_quarter",
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN min_payroll_percent_of_revenue DECIMAL(10,4) NOT NULL DEFAULT 0.0800 AFTER revenue_driver_context_required",
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN max_payroll_percent_of_revenue DECIMAL(10,4) NOT NULL DEFAULT 0.8000 AFTER min_payroll_percent_of_revenue",
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN payroll_revenue_sanity_bounds_json LONGTEXT NULL AFTER max_payroll_percent_of_revenue",
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN payroll_revenue_sanity_tolerance_pct DECIMAL(10,4) NOT NULL DEFAULT 0.0300 AFTER payroll_revenue_sanity_bounds_json",
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN payroll_revenue_sanity_relative_tolerance DECIMAL(10,4) NOT NULL DEFAULT 0.2000 AFTER payroll_revenue_sanity_tolerance_pct",
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN payroll_trend_rules_json LONGTEXT NULL AFTER payroll_revenue_sanity_relative_tolerance",
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN decision_source_required TINYINT(1) NOT NULL DEFAULT 1 AFTER schedule_contract_version",
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN required_decision_source VARCHAR(128) NOT NULL DEFAULT 'payroll_headcount_schedule.payroll_headcount_grid' AFTER decision_source_required",
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN headcount_economic_basis VARCHAR(128) NOT NULL DEFAULT 'capacity_units_per_supporting_fte' AFTER headcount_source_priority_json",
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN min_capacity_coverage_ratio DECIMAL(10,4) NOT NULL DEFAULT 1.0000 AFTER headcount_economic_basis",
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN utilization_pressure_threshold DECIMAL(10,4) NOT NULL DEFAULT 0.8500 AFTER min_capacity_coverage_ratio",
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN annual_wage_inflation_rate DECIMAL(10,4) NOT NULL DEFAULT 0.0300 AFTER utilization_pressure_threshold",
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN capacity_labor_model_values_json LONGTEXT NULL AFTER annual_wage_inflation_rate",
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN labor_intensity_class_values_json LONGTEXT NULL AFTER capacity_labor_model_values_json",
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN wage_positioning_multiplier_json LONGTEXT NULL AFTER labor_intensity_class_values_json",
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN salary_basis VARCHAR(128) NOT NULL DEFAULT 'oews_all_occupations_mean' AFTER generic_oews_fallback_code",
        f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} ADD COLUMN min_wage_benchmark_ratio DECIMAL(10,4) NOT NULL DEFAULT 0.7500 AFTER salary_basis",
      ]:
        try:
          cur.execute(ddl)
        except Exception as exc:
          if "Duplicate column" not in str(exc):
            raise
      try:
        cur.execute(f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} DROP COLUMN aggregate_staff_max_fte")
      except Exception as exc:
        if "check that column/key exists" not in str(exc).lower() and "can't drop" not in str(exc).lower() and "unknown column" not in str(exc).lower():
          raise
      for legacy_column in ("default_revenue_per_employee", "min_fte_coverage_ratio"):
        try:
          cur.execute(f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} DROP COLUMN {legacy_column}")
        except Exception as exc:
          if "check that column/key exists" not in str(exc).lower() and "can't drop" not in str(exc).lower() and "unknown column" not in str(exc).lower():
            raise
      for legacy_column in (
        "role_rows_required",
        "max_role_rows_per_quarter",
        "role_family_values_json",
        "role_family_coverage_rules_json",
        "role_family_oews_title_rules_json",
        "role_family_soc_prefix_rules_json",
        "role_category_required",
        "capacity_units_per_supporting_fte_min",
        "capacity_units_per_supporting_fte_max",
        "capacity_productivity_bounds_json",
      ):
        try:
          cur.execute(f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} DROP COLUMN {legacy_column}")
        except Exception as exc:
          if "check that column/key exists" not in str(exc).lower() and "can't drop" not in str(exc).lower() and "unknown column" not in str(exc).lower():
            raise
      try:
        cur.execute(f"ALTER TABLE {HEADCOUNT_POLICY_TABLE_NAME} DROP COLUMN default_avg_annual_wage")
      except Exception as exc:
        if "check that column/key exists" not in str(exc).lower() and "can't drop" not in str(exc).lower() and "unknown column" not in str(exc).lower():
          raise
      for row in _DEFAULT_HEADCOUNT_POLICY_ROWS:
        cur.execute(
          f"""
          INSERT INTO {HEADCOUNT_POLICY_TABLE_NAME} (
            policy_code,
            policy_status,
            schedule_storage_table,
            schedule_storage_column,
            schedule_contract_version,
            decision_source_required,
            required_decision_source,
            schedule_horizon_quarters,
            schedule_required,
            quarter_totals_required,
            model_input_driver,
            financial_model_field,
            headcount_source_priority_json,
            headcount_economic_basis,
            min_capacity_coverage_ratio,
            utilization_pressure_threshold,
            annual_wage_inflation_rate,
            capacity_labor_model_values_json,
            labor_intensity_class_values_json,
            wage_positioning_multiplier_json,
            wage_source_priority_json,
            generic_oews_fallback_allowed,
            generic_oews_fallback_code,
            min_payroll_tax_benefits_pct,
            default_payroll_tax_benefits_pct,
            max_payroll_tax_benefits_pct,
            min_annual_wage,
            max_oews_title_rows_per_quarter,
            revenue_driver_context_required,
            min_payroll_percent_of_revenue,
            max_payroll_percent_of_revenue,
            payroll_revenue_sanity_bounds_json,
            payroll_revenue_sanity_tolerance_pct,
            payroll_revenue_sanity_relative_tolerance,
            payroll_trend_rules_json,
            fte_math_required,
            currency_rounding,
            ratio_rounding,
            notes
          ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
          ON DUPLICATE KEY UPDATE
            policy_status = VALUES(policy_status),
            schedule_storage_table = VALUES(schedule_storage_table),
            schedule_storage_column = VALUES(schedule_storage_column),
            schedule_contract_version = VALUES(schedule_contract_version),
            decision_source_required = VALUES(decision_source_required),
            required_decision_source = VALUES(required_decision_source),
            schedule_horizon_quarters = VALUES(schedule_horizon_quarters),
            schedule_required = VALUES(schedule_required),
            quarter_totals_required = VALUES(quarter_totals_required),
            model_input_driver = VALUES(model_input_driver),
            financial_model_field = VALUES(financial_model_field),
            headcount_source_priority_json = VALUES(headcount_source_priority_json),
            headcount_economic_basis = VALUES(headcount_economic_basis),
            min_capacity_coverage_ratio = VALUES(min_capacity_coverage_ratio),
            utilization_pressure_threshold = VALUES(utilization_pressure_threshold),
            annual_wage_inflation_rate = VALUES(annual_wage_inflation_rate),
            capacity_labor_model_values_json = VALUES(capacity_labor_model_values_json),
            labor_intensity_class_values_json = VALUES(labor_intensity_class_values_json),
            wage_positioning_multiplier_json = VALUES(wage_positioning_multiplier_json),
            wage_source_priority_json = VALUES(wage_source_priority_json),
            generic_oews_fallback_allowed = VALUES(generic_oews_fallback_allowed),
            generic_oews_fallback_code = VALUES(generic_oews_fallback_code),
            min_payroll_tax_benefits_pct = VALUES(min_payroll_tax_benefits_pct),
            default_payroll_tax_benefits_pct = VALUES(default_payroll_tax_benefits_pct),
            max_payroll_tax_benefits_pct = VALUES(max_payroll_tax_benefits_pct),
            min_annual_wage = VALUES(min_annual_wage),
            max_oews_title_rows_per_quarter = VALUES(max_oews_title_rows_per_quarter),
            revenue_driver_context_required = VALUES(revenue_driver_context_required),
            min_payroll_percent_of_revenue = VALUES(min_payroll_percent_of_revenue),
            max_payroll_percent_of_revenue = VALUES(max_payroll_percent_of_revenue),
            payroll_revenue_sanity_bounds_json = VALUES(payroll_revenue_sanity_bounds_json),
            payroll_revenue_sanity_tolerance_pct = VALUES(payroll_revenue_sanity_tolerance_pct),
            payroll_revenue_sanity_relative_tolerance = VALUES(payroll_revenue_sanity_relative_tolerance),
            payroll_trend_rules_json = VALUES(payroll_trend_rules_json),
            fte_math_required = VALUES(fte_math_required),
            currency_rounding = VALUES(currency_rounding),
            ratio_rounding = VALUES(ratio_rounding),
            notes = VALUES(notes)
          """,
          (
            _clean_text(row.get("policy_code")).lower(),
            _clean_text(row.get("policy_status")).lower() or "active",
            _clean_text(row.get("schedule_storage_table")),
            _clean_text(row.get("schedule_storage_column")),
            _clean_text(row.get("schedule_contract_version")),
            1 if row.get("decision_source_required") else 0,
            _clean_text(row.get("required_decision_source")) or "payroll_headcount_schedule.payroll_headcount_grid",
            int(row.get("schedule_horizon_quarters") or 20),
            1 if row.get("schedule_required") else 0,
            1 if row.get("quarter_totals_required") else 0,
            _clean_text(row.get("model_input_driver")),
            _clean_text(row.get("financial_model_field")),
            _json_dumps_value(row.get("headcount_source_priority_json") or []),
            _clean_text(row.get("headcount_economic_basis")) or "capacity_units_per_supporting_fte",
            float(row.get("min_capacity_coverage_ratio") or 1.0),
            float(row.get("utilization_pressure_threshold") or 0.85),
            float(row.get("annual_wage_inflation_rate") or 0.03),
            _json_dumps_value(row.get("capacity_labor_model_values_json") or []),
            _json_dumps_value(row.get("labor_intensity_class_values_json") or []),
            _json_dumps_value(row.get("wage_positioning_multiplier_json") or {}),
            _json_dumps_value(row.get("wage_source_priority_json") or []),
            1 if row.get("generic_oews_fallback_allowed") else 0,
            _clean_text(row.get("generic_oews_fallback_code")) or None,
            float(row.get("min_payroll_tax_benefits_pct") or 0.12),
            float(row.get("default_payroll_tax_benefits_pct") or 0.22),
            float(row.get("max_payroll_tax_benefits_pct") or 0.35),
            float(row.get("min_annual_wage") or 25000),
            int(row.get("max_oews_title_rows_per_quarter") or 20),
            1 if row.get("revenue_driver_context_required") else 0,
            float(row.get("min_payroll_percent_of_revenue") or 0.08),
            float(row.get("max_payroll_percent_of_revenue") or 0.80),
            _json_dumps_value(row.get("payroll_revenue_sanity_bounds_json") or {}),
            float(row.get("payroll_revenue_sanity_tolerance_pct") or 0.03),
            float(row.get("payroll_revenue_sanity_relative_tolerance") or 0.20),
            _json_dumps_value(row.get("payroll_trend_rules_json") or {}),
            1 if row.get("fte_math_required") else 0,
            _clean_text(row.get("currency_rounding")) or "nearest_dollar",
            _clean_text(row.get("ratio_rounding")) or "two_decimal_places",
            _clean_text(row.get("notes")),
          ),
        )
      cur.execute(
        f"""
        UPDATE {HEADCOUNT_POLICY_TABLE_NAME}
        SET required_decision_source = 'payroll_headcount_schedule.payroll_headcount_grid',
            notes = 'Payroll is schedule-driven through its own payroll_headcount_schedule contract. Stage/ramp is context only and must not own payroll rows.'
        WHERE policy_code = 'default'
          AND required_decision_source = 'stage_ramp_contract.payroll_headcount_grid'
        """
      )
      cur.execute(
        f"""
        UPDATE {HEADCOUNT_POLICY_TABLE_NAME}
        SET headcount_economic_basis = 'capacity_units_per_supporting_fte',
            min_capacity_coverage_ratio = 1.0000,
            utilization_pressure_threshold = 0.8500,
            annual_wage_inflation_rate = 0.0300,
            capacity_labor_model_values_json = %s,
            labor_intensity_class_values_json = %s,
            wage_positioning_multiplier_json = %s,
            wage_source_priority_json = %s,
            salary_basis = 'oews_title_catalog_selected_title',
            min_wage_benchmark_ratio = 0.7500,
            max_oews_title_rows_per_quarter = %s,
            payroll_revenue_sanity_bounds_json = %s,
            payroll_revenue_sanity_tolerance_pct = %s,
            payroll_revenue_sanity_relative_tolerance = %s,
            payroll_trend_rules_json = %s
        WHERE policy_code = 'default'
        """,
        (
          _json_dumps_value(_DEFAULT_HEADCOUNT_POLICY_ROWS[0].get("capacity_labor_model_values_json") or []),
          _json_dumps_value(_DEFAULT_HEADCOUNT_POLICY_ROWS[0].get("labor_intensity_class_values_json") or []),
          _json_dumps_value(_DEFAULT_HEADCOUNT_POLICY_ROWS[0].get("wage_positioning_multiplier_json") or {}),
          _json_dumps_value(_DEFAULT_HEADCOUNT_POLICY_ROWS[0].get("wage_source_priority_json") or []),
          int(_DEFAULT_HEADCOUNT_POLICY_ROWS[0].get("max_oews_title_rows_per_quarter") or 20),
          _json_dumps_value(_DEFAULT_HEADCOUNT_POLICY_ROWS[0].get("payroll_revenue_sanity_bounds_json") or {}),
          float(_DEFAULT_HEADCOUNT_POLICY_ROWS[0].get("payroll_revenue_sanity_tolerance_pct") or 0.03),
          float(_DEFAULT_HEADCOUNT_POLICY_ROWS[0].get("payroll_revenue_sanity_relative_tolerance") or 0.20),
          _json_dumps_value(_DEFAULT_HEADCOUNT_POLICY_ROWS[0].get("payroll_trend_rules_json") or {}),
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
          decision_source_required,
          required_decision_source,
          schedule_horizon_quarters,
          schedule_required,
          quarter_totals_required,
          model_input_driver,
          financial_model_field,
          headcount_source_priority_json,
          headcount_economic_basis,
          min_capacity_coverage_ratio,
          utilization_pressure_threshold,
          annual_wage_inflation_rate,
          capacity_labor_model_values_json,
          labor_intensity_class_values_json,
          wage_positioning_multiplier_json,
          wage_source_priority_json,
          generic_oews_fallback_allowed,
          generic_oews_fallback_code,
          salary_basis,
          min_wage_benchmark_ratio,
          fte_math_required,
          currency_rounding,
          ratio_rounding,
          min_payroll_tax_benefits_pct,
          default_payroll_tax_benefits_pct,
          max_payroll_tax_benefits_pct,
          min_annual_wage,
          max_oews_title_rows_per_quarter,
          revenue_driver_context_required,
          min_payroll_percent_of_revenue,
          max_payroll_percent_of_revenue,
          payroll_revenue_sanity_bounds_json,
          payroll_revenue_sanity_tolerance_pct,
          payroll_revenue_sanity_relative_tolerance,
          payroll_trend_rules_json,
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
        "decision_source_required": _clean_bool(raw_row.get("decision_source_required"), default=True),
        "required_decision_source": _clean_text(raw_row.get("required_decision_source")) or "payroll_headcount_schedule.payroll_headcount_grid",
        "schedule_horizon_quarters": int(float(raw_row.get("schedule_horizon_quarters") or 0)),
        "schedule_required": _clean_bool(raw_row.get("schedule_required"), default=True),
        "quarter_totals_required": _clean_bool(raw_row.get("quarter_totals_required"), default=True),
        "model_input_driver": _clean_text(raw_row.get("model_input_driver")),
        "financial_model_field": _clean_text(raw_row.get("financial_model_field")),
        "headcount_source_priority": _json_value(raw_row.get("headcount_source_priority_json"), []),
        "headcount_economic_basis": _clean_text(raw_row.get("headcount_economic_basis")).lower() or "capacity_units_per_supporting_fte",
        "min_capacity_coverage_ratio": float(raw_row.get("min_capacity_coverage_ratio") or 1.0),
        "utilization_pressure_threshold": float(raw_row.get("utilization_pressure_threshold") or 0.85),
        "annual_wage_inflation_rate": float(raw_row.get("annual_wage_inflation_rate") or 0.03),
        "capacity_labor_model_values": _json_value(raw_row.get("capacity_labor_model_values_json"), []),
        "labor_intensity_class_values": _json_value(raw_row.get("labor_intensity_class_values_json"), []),
        "wage_positioning_multiplier": _json_value(raw_row.get("wage_positioning_multiplier_json"), {}),
        "wage_source_priority": _json_value(raw_row.get("wage_source_priority_json"), []),
        "generic_oews_fallback_allowed": _clean_bool(raw_row.get("generic_oews_fallback_allowed")),
        "generic_oews_fallback_code": _clean_text(raw_row.get("generic_oews_fallback_code")),
        "salary_basis": _clean_text(raw_row.get("salary_basis")).lower() or "oews_all_occupations_mean",
        "min_wage_benchmark_ratio": float(raw_row.get("min_wage_benchmark_ratio") or 0.75),
        "min_payroll_tax_benefits_pct": float(raw_row.get("min_payroll_tax_benefits_pct") or 0.12),
        "default_payroll_tax_benefits_pct": float(raw_row.get("default_payroll_tax_benefits_pct") or 0.22),
        "max_payroll_tax_benefits_pct": float(raw_row.get("max_payroll_tax_benefits_pct") or 0.35),
        "min_annual_wage": float(raw_row.get("min_annual_wage") or 25000.0),
        "max_oews_title_rows_per_quarter": int(float(raw_row.get("max_oews_title_rows_per_quarter") or 20)),
        "revenue_driver_context_required": _clean_bool(raw_row.get("revenue_driver_context_required"), default=True),
        "min_payroll_percent_of_revenue": float(raw_row.get("min_payroll_percent_of_revenue") or 0.08),
        "max_payroll_percent_of_revenue": float(raw_row.get("max_payroll_percent_of_revenue") or 0.80),
        "payroll_revenue_sanity_bounds": _json_value(raw_row.get("payroll_revenue_sanity_bounds_json"), {}),
        "payroll_revenue_sanity_tolerance_pct": float(raw_row.get("payroll_revenue_sanity_tolerance_pct") or 0.03),
        "payroll_revenue_sanity_relative_tolerance": float(raw_row.get("payroll_revenue_sanity_relative_tolerance") or 0.20),
        "payroll_trend_rules": _json_value(raw_row.get("payroll_trend_rules_json"), {}),
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
      expected_horizon = _contract_forecast_horizon_quarters()
      if int(row.get("schedule_horizon_quarters") or 0) != expected_horizon:
        errors.append(f"{policy_code}_schedule_horizon_must_match_contract:{expected_horizon}")
      if not _clean_text(row.get("model_input_driver")):
        errors.append(f"{policy_code}_missing_model_input_driver")
      if not _clean_text(row.get("financial_model_field")):
        errors.append(f"{policy_code}_missing_financial_model_field")
      if _clean_bool(row.get("decision_source_required"), default=True) and not _clean_text(row.get("required_decision_source")):
        errors.append(f"{policy_code}_missing_required_decision_source")
      if not isinstance(row.get("headcount_source_priority"), list) or not row.get("headcount_source_priority"):
        errors.append(f"{policy_code}_missing_headcount_source_priority")
      if _clean_text(row.get("headcount_economic_basis")).lower() != "capacity_units_per_supporting_fte":
        errors.append(f"{policy_code}_unsupported_headcount_economic_basis")
      min_capacity_coverage_ratio = float(row.get("min_capacity_coverage_ratio") or 0.0)
      if min_capacity_coverage_ratio <= 0.0 or min_capacity_coverage_ratio > 2.0:
        errors.append(f"{policy_code}_min_capacity_coverage_ratio_invalid")
      utilization_threshold = float(row.get("utilization_pressure_threshold") or 0.0)
      if utilization_threshold <= 0.0 or utilization_threshold > 1.0:
        errors.append(f"{policy_code}_utilization_pressure_threshold_invalid")
      wage_inflation = float(row.get("annual_wage_inflation_rate") or 0.0)
      if wage_inflation < 0.0 or wage_inflation > 0.10:
        errors.append(f"{policy_code}_annual_wage_inflation_rate_invalid")
      if not isinstance(row.get("capacity_labor_model_values"), list) or not row.get("capacity_labor_model_values"):
        errors.append(f"{policy_code}_missing_capacity_labor_model_values")
      if not isinstance(row.get("labor_intensity_class_values"), list) or not row.get("labor_intensity_class_values"):
        errors.append(f"{policy_code}_missing_labor_intensity_class_values")
      wage_multipliers = row.get("wage_positioning_multiplier")
      if not isinstance(wage_multipliers, dict) or not wage_multipliers:
        errors.append(f"{policy_code}_missing_wage_positioning_multiplier")
      else:
        for tier, bounds in wage_multipliers.items():
          if not isinstance(bounds, dict):
            errors.append(f"{policy_code}_wage_positioning_multiplier_bounds_invalid:{tier}")
            continue
          min_multiplier = float(bounds.get("min") or 0.0)
          max_multiplier = float(bounds.get("max") or 0.0)
          if min_multiplier < 1.0 or max_multiplier < min_multiplier or max_multiplier > 3.0:
            errors.append(f"{policy_code}_wage_positioning_multiplier_bounds_invalid:{tier}")
      wage_source_priority = row.get("wage_source_priority")
      if not isinstance(wage_source_priority, list) or not wage_source_priority:
        errors.append(f"{policy_code}_missing_wage_source_priority")
      elif "policy_default_wage" in {_clean_text(item).lower() for item in wage_source_priority}:
        errors.append(f"{policy_code}_policy_default_wage_legacy_source_forbidden")
      if _clean_bool(row.get("generic_oews_fallback_allowed")):
        errors.append(f"{policy_code}_generic_oews_fallback_forbidden")
      min_wage_benchmark_ratio = float(row.get("min_wage_benchmark_ratio") or 0.0)
      if min_wage_benchmark_ratio <= 0.0 or min_wage_benchmark_ratio > 1.0:
        errors.append(f"{policy_code}_min_wage_benchmark_ratio_invalid")
      min_benefits = float(row.get("min_payroll_tax_benefits_pct") or 0.0)
      default_benefits = float(row.get("default_payroll_tax_benefits_pct") or 0.0)
      max_benefits = float(row.get("max_payroll_tax_benefits_pct") or 0.0)
      if min_benefits <= 0.0:
        errors.append(f"{policy_code}_min_payroll_tax_benefits_pct_must_be_positive")
      if default_benefits < min_benefits or default_benefits > max_benefits:
        errors.append(f"{policy_code}_default_payroll_tax_benefits_pct_invalid")
      if max_benefits < min_benefits or max_benefits > 1.0:
        errors.append(f"{policy_code}_max_payroll_tax_benefits_pct_invalid")
      if float(row.get("min_annual_wage") or 0.0) <= 0.0:
        errors.append(f"{policy_code}_min_annual_wage_must_be_positive")
      max_title_rows = int(row.get("max_oews_title_rows_per_quarter") or 0)
      if max_title_rows < 1:
        errors.append(f"{policy_code}_max_oews_title_rows_per_quarter_must_be_positive")
      min_payroll_pct = float(row.get("min_payroll_percent_of_revenue") or 0.0)
      max_payroll_pct = float(row.get("max_payroll_percent_of_revenue") or 0.0)
      if min_payroll_pct <= 0.0:
        errors.append(f"{policy_code}_min_payroll_percent_of_revenue_must_be_positive")
      if max_payroll_pct < min_payroll_pct or max_payroll_pct > 1.0:
        errors.append(f"{policy_code}_max_payroll_percent_of_revenue_invalid")
      sanity_bounds = row.get("payroll_revenue_sanity_bounds")
      if not isinstance(sanity_bounds, dict) or not sanity_bounds:
        errors.append(f"{policy_code}_missing_payroll_revenue_sanity_bounds")
      else:
        for intensity in row.get("labor_intensity_class_values") or []:
          intensity_key = _clean_text(intensity).lower()
          current = sanity_bounds.get(intensity_key)
          if not isinstance(current, dict):
            errors.append(f"{policy_code}_missing_payroll_revenue_sanity_bound:{intensity_key}")
            continue
          min_pct = float(current.get("min_pct") or 0.0)
          max_pct = float(current.get("max_pct") or 0.0)
          if min_pct <= 0.0 or max_pct < min_pct or max_pct > 1.0:
            errors.append(f"{policy_code}_invalid_payroll_revenue_sanity_bound:{intensity_key}")
      trend_rules = row.get("payroll_trend_rules")
      if not isinstance(trend_rules, dict) or not bool(trend_rules.get("capacity_primary")):
        errors.append(f"{policy_code}_missing_capacity_primary_payroll_trend_rules")
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


def headcount_wage_positioning_options(policy: Dict[str, Any]) -> List[Dict[str, Any]]:
  """Table-backed wage multiplier option rows GPT may choose."""
  bounds = policy.get("wage_positioning_multiplier") if isinstance(policy, dict) else {}
  options: List[Dict[str, Any]] = []
  if not isinstance(bounds, dict):
    return options
  for tier, current in sorted(bounds.items()):
    if not isinstance(current, dict):
      continue
    min_value = _float_or_none(current.get("min"))
    max_value = _float_or_none(current.get("max"))
    if min_value is None or max_value is None or min_value <= 0.0 or max_value < min_value:
      continue
    options.append(
      {
        "wage_positioning_tier": _clean_text(tier).lower(),
        "wage_positioning_multiplier_min": round(float(min_value), 4),
        "wage_positioning_multiplier_max": round(float(max_value), 4),
      }
    )
  return options


def headcount_payroll_revenue_sanity_bounds(
  policy: Dict[str, Any],
  *,
  labor_intensity_class: Any,
) -> Dict[str, float]:
  bounds = policy.get("payroll_revenue_sanity_bounds") if isinstance(policy, dict) else {}
  intensity_key = _clean_text(labor_intensity_class).lower()
  current = bounds.get(intensity_key) if isinstance(bounds, dict) else None
  if not isinstance(current, dict):
    raise RuntimeError(f"payroll_headcount_revenue_sanity_lookup_missing:intensity={intensity_key or 'missing'}")
  min_pct = _float_or_none(current.get("min_pct"))
  max_pct = _float_or_none(current.get("max_pct"))
  if min_pct is None or max_pct is None or min_pct <= 0.0 or max_pct < min_pct or max_pct > 1.0:
    raise RuntimeError(f"payroll_headcount_revenue_sanity_lookup_invalid:intensity={intensity_key}")
  return {"min_pct": float(min_pct), "max_pct": float(max_pct)}


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
    "decision_source": _clean_text((policy or {}).get("required_decision_source")) or "payroll_headcount_schedule.payroll_headcount_grid",
    "draft_id": _clean_text(draft_id),
    "client_id": _clean_text(client_id),
    "policy_code": _clean_text(policy_code).lower() or "default",
    "source_table": "intake_consult_drafts",
    "source_column": PAYROLL_HEADCOUNT_DRAFT_COLUMN,
    "schedule_horizon_quarters": horizon,
    "capacity_labor_model": "",
    "labor_intensity_class": "",
    "wage_positioning_tier": "",
    "wage_positioning_multiplier": 0.0,
    "capacity_units_per_supporting_fte": 0.0,
    "target_payroll_percent_of_revenue": 0.0,
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


def _validate_schedule_row(row: Any, *, path: str, errors: List[str], max_quarter: int) -> None:
  if not isinstance(row, dict):
    errors.append(f"payroll_headcount_row_not_object:{path}")
    return
  quarter_index = _int_or_none(row.get("quarter_index"))
  if quarter_index is None or quarter_index < 1 or quarter_index > max_quarter:
    errors.append(f"payroll_headcount_invalid_quarter_index:{path}")
  staffing_class = _clean_text(row.get("staffing_class")).lower() or "supporting_staff"
  oews_occ_title = _clean_text(row.get("oews_occ_title") or row.get("oews_matched_title"))
  if staffing_class != "key_person" and not oews_occ_title:
    errors.append(f"payroll_headcount_missing_oews_occ_title:{path}")
  annual_wage = _float_or_none(row.get("annual_wage"))
  if annual_wage is None or annual_wage <= 0:
    errors.append(f"payroll_headcount_missing_resolved_annual_wage:{path}")
  wage_source = _clean_text(row.get("wage_source"))
  if not wage_source:
    errors.append(f"payroll_headcount_missing_wage_source:{path}")
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


def _validate_supporting_title_lifecycle(rows: List[Any], *, errors: List[str], max_quarter: int) -> None:
  rows_by_title: Dict[str, Dict[int, Dict[str, Any]]] = {}
  labels: Dict[str, str] = {}
  for row in rows:
    if not isinstance(row, dict):
      continue
    staffing_class = _clean_text(row.get("staffing_class")).lower() or "supporting_staff"
    if staffing_class == "key_person":
      continue
    oews_title = _clean_text(row.get("oews_occ_title") or row.get("oews_matched_title"))
    if not oews_title:
      continue
    title_key = oews_title.lower()
    quarter_index = _int_or_none(row.get("quarter_index"))
    if quarter_index is None or quarter_index < 1 or quarter_index > max_quarter:
      continue
    labels[title_key] = oews_title
    rows_by_title.setdefault(title_key, {})[quarter_index] = row
  for title_key, quarter_rows in rows_by_title.items():
    label = labels.get(title_key) or title_key
    active_quarters: List[int] = []
    for quarter_index, row in sorted(quarter_rows.items()):
      starting = _float_or_none(row.get("starting_fte")) or 0.0
      hires = _float_or_none(row.get("hires")) or 0.0
      ending = _float_or_none(row.get("ending_fte")) or 0.0
      if max(starting, hires, ending) > 0.0:
        active_quarters.append(quarter_index)
    if not active_quarters:
      errors.append(f"payroll_headcount_dead_support_title:{label}")
      continue
    first_active = min(active_quarters)
    for quarter_index in range(first_active, max_quarter + 1):
      row = quarter_rows.get(quarter_index)
      if not isinstance(row, dict):
        errors.append(f"payroll_headcount_support_title_missing_after_start:{label}:q{quarter_index}")
        continue
      ending = _float_or_none(row.get("ending_fte")) or 0.0
      if ending <= 0.0:
        errors.append(f"payroll_headcount_support_title_stops_after_start:{label}:q{quarter_index}")


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
  if _clean_bool((policy or {}).get("decision_source_required"), default=True):
    expected_source = _clean_text((policy or {}).get("required_decision_source"))
    if expected_source and _clean_text(payload.get("decision_source")) != expected_source:
      errors.append(f"payroll_headcount_decision_source_mismatch:expected={expected_source}")
  expected_basis = _clean_text((policy or {}).get("headcount_economic_basis")).lower()
  actual_basis = _clean_text(payload.get("headcount_economic_basis")).lower()
  if expected_basis and actual_basis and actual_basis != expected_basis:
    errors.append(f"payroll_headcount_economic_basis_mismatch:expected={expected_basis}:actual={actual_basis}")
  expected_horizon = int((policy or {}).get("schedule_horizon_quarters") or 20)
  allowed_labor_models = {
    _clean_text(item).lower()
    for item in ((policy or {}).get("capacity_labor_model_values") or [])
    if _clean_text(item)
  }
  labor_model = _clean_text(payload.get("capacity_labor_model")).lower()
  if allowed_labor_models and labor_model not in allowed_labor_models:
    errors.append(f"payroll_headcount_capacity_labor_model_invalid:{labor_model or 'missing'}")
  allowed_intensity_classes = {
    _clean_text(item).lower()
    for item in ((policy or {}).get("labor_intensity_class_values") or [])
    if _clean_text(item)
  }
  intensity = _clean_text(payload.get("labor_intensity_class")).lower()
  if allowed_intensity_classes and intensity not in allowed_intensity_classes:
    errors.append(f"payroll_headcount_labor_intensity_class_invalid:{intensity or 'missing'}")
  wage_multipliers = (policy or {}).get("wage_positioning_multiplier")
  wage_tier = _clean_text(payload.get("wage_positioning_tier")).lower()
  if isinstance(wage_multipliers, dict) and wage_multipliers and wage_tier not in {
    _clean_text(key).lower() for key in wage_multipliers.keys()
  }:
    errors.append(f"payroll_headcount_wage_positioning_tier_invalid:{wage_tier or 'missing'}")
  wage_multiplier = _float_or_none(payload.get("wage_positioning_multiplier"))
  tier_bounds = wage_multipliers.get(wage_tier) if isinstance(wage_multipliers, dict) else None
  if wage_multiplier is None or wage_multiplier <= 0:
    errors.append("payroll_headcount_wage_positioning_multiplier_missing")
  elif isinstance(tier_bounds, dict):
    min_multiplier = float(tier_bounds.get("min") or 0.0)
    max_multiplier = float(tier_bounds.get("max") or 0.0)
    if wage_multiplier < min_multiplier or wage_multiplier > max_multiplier:
      errors.append(
        "payroll_headcount_wage_positioning_multiplier_out_of_tier_bounds:"
        f"value={wage_multiplier}:tier={wage_tier}:min={min_multiplier}:max={max_multiplier}"
      )
  productivity = _float_or_none(payload.get("capacity_units_per_supporting_fte"))
  if productivity is None or productivity <= 0:
    errors.append("payroll_headcount_capacity_units_per_supporting_fte_missing")
  target_payroll_pct = _float_or_none(payload.get("target_payroll_percent_of_revenue"))
  if target_payroll_pct is None or target_payroll_pct <= 0:
    errors.append("payroll_headcount_target_payroll_percent_of_revenue_missing")
  elif intensity:
    try:
      sanity_bounds = headcount_payroll_revenue_sanity_bounds(policy or {}, labor_intensity_class=intensity)
      min_pct = float(sanity_bounds.get("min_pct") or 0.0)
      max_pct = float(sanity_bounds.get("max_pct") or 0.0)
      if target_payroll_pct < min_pct or target_payroll_pct > max_pct:
        errors.append(
          "payroll_headcount_target_payroll_percent_of_revenue_out_of_policy_range:"
          f"value={target_payroll_pct}:min={min_pct}:max={max_pct}"
        )
    except RuntimeError as exc:
      errors.append(str(exc))
  if int(payload.get("schedule_horizon_quarters") or 0) != expected_horizon:
    errors.append("payroll_headcount_horizon_mismatch")
  rows = payload.get("rows")
  if not isinstance(rows, list):
    errors.append("payroll_headcount_rows_not_array")
    rows = []
  for index, row in enumerate(rows):
    _validate_schedule_row(row, path=f"rows[{index}]", errors=errors, max_quarter=expected_horizon)
  _validate_supporting_title_lifecycle(rows, errors=errors, max_quarter=expected_horizon)
  quarter_totals = payload.get("quarter_totals")
  if not isinstance(quarter_totals, list):
    errors.append("payroll_headcount_quarter_totals_not_array")
    quarter_totals = []
  if len(quarter_totals) != expected_horizon:
    errors.append(f"payroll_headcount_quarter_totals_must_cover_contract_horizon:{expected_horizon}")
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
      # Phase 8: relax exact-integer check to a $0.01 tolerance.
      # Float arithmetic during cash-pass debt-schedule application
      # introduces sub-cent drift (e.g. 240000.0000000001) that the
      # legacy GPT loop's authority reapplication used to round away.
      # Anything within a cent is conceptually integer; larger drift
      # is a real schedule corruption that the acceptance gate will
      # surface via the integrity checks downstream.
      if field == "payroll" and abs(number - round(number)) > 0.01:
        errors.append(f"payroll_headcount_quarter_total_payroll_not_integer:{index}")
  if seen_quarters != set(range(1, expected_horizon + 1)):
    errors.append("payroll_headcount_quarter_totals_missing_required_quarters")
  return errors
