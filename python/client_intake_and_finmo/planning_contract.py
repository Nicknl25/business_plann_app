from __future__ import annotations

from typing import Any, Dict, List, Tuple


PLANNING_CONTRACT_VERSION = "planning-contract/v1"

PERSISTED_ENGINE_FIELDS: Tuple[str, ...] = (
  "normalized_traits_json",
  "benchmark_payload_json",
  "constraint_engine_state_json",
  "forecast_engine_state_json",
  "forecast_quarters_json",
  "engine_versions_json",
)

SOLVER_MUTABLE_LEVERS: Tuple[str, ...] = (
  "unit_price",
  "utilization_rate",
  "product_unit_price",
  "product_utilization_rate",
  "product_avg_units_per_period_year1",
  "marketing_total_year1",
  "other_operating_expense",
  "cogs_total_year1",
  "planned_hire_timing",
  "planned_role_wage",
  "milestone_timing",
)

SOLVER_PROTECTED_FACTS: Tuple[str, ...] = (
  "business_stage",
  "geographic_scope",
  "unit_cadence",
  "current_staff",
  "fixed_rent",
  "fixed_debt",
  "capacity_driver",
  "customer_type",
)

VIOLATION_CODES: Tuple[str, ...] = (
  "capacity_unsupported",
  "demand_unsupported",
  "revenue_out_of_range",
  "marketing_too_high",
  "marketing_too_low",
  "gross_margin_too_high",
  "gross_margin_too_low",
  "ebitda_margin_too_high",
  "ebitda_margin_too_low",
  "payroll_too_light",
  "payroll_too_heavy",
  "opex_too_light",
  "opex_too_heavy",
  "working_capital_inconsistent",
  "utilization_too_high",
  "utilization_too_low",
  "growth_too_fast",
  "benchmark_low_confidence",
)

FALLBACK_LEVELS: Tuple[str, ...] = (
  "naics_6",
  "naics_5",
  "naics_4",
  "naics_3",
  "naics_2",
  "trait_based",
  "generic",
)

CONSTRAINT_CLASSES: Tuple[str, ...] = (
  "hard",
  "soft",
  "context",
)


def normalized_traits_schema() -> Dict[str, Any]:
  return {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "contract_version": {"type": "string"},
      "traits_version": {"type": ["string", "null"]},
      "naics_6": {"type": ["string", "null"]},
      "business_type": {"type": ["string", "null"]},
      "industry": {"type": ["string", "null"]},
      "sector": {"type": ["string", "null"]},
      "classification_source": {
        "type": ["string", "null"],
        "enum": [None, "persisted_business_type", "none"],
      },
      "customer_type": {"type": ["string", "null"], "enum": [None, "b2b", "b2c", "mixed"]},
      "sales_modality": {
        "type": ["string", "null"],
        "enum": [None, "local_service", "retail", "online", "project_based", "manufacturing", "hybrid"],
      },
      "capacity_driver": {
        "type": ["string", "null"],
        "enum": [None, "labor", "system", "space", "equipment", "demand"],
      },
      "unit_cadence": {
        "type": ["string", "null"],
        "enum": [None, "one_time", "recurring", "seasonal", "project", "contract"],
      },
      "geographic_scope": {
        "type": ["string", "null"],
        "enum": [None, "local", "regional", "national", "international"],
      },
      "business_stage": {
        "type": ["string", "null"],
        "enum": [None, "pre_revenue", "startup", "operating", "growth", "mature"],
      },
      "fulfillment_shape": {"type": ["string", "null"]},
    },
    "required": [
      "contract_version",
      "traits_version",
      "naics_6",
      "business_type",
      "industry",
      "sector",
      "classification_source",
      "customer_type",
      "sales_modality",
      "capacity_driver",
      "unit_cadence",
      "geographic_scope",
      "business_stage",
      "fulfillment_shape",
    ],
  }


def alpha_benchmark_payload_schema() -> Dict[str, Any]:
  metric_band = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "min": {"type": ["number", "null"]},
      "max": {"type": ["number", "null"]},
    },
    "required": ["min", "max"],
  }
  metric_scalar = {"type": ["number", "null"]}
  return {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "contract_version": {"type": "string"},
      "benchmark_resolver_version": {"type": ["string", "null"]},
      "matched_naics_code": {"type": ["string", "null"]},
      "matched_naics_level": {"type": ["integer", "null"]},
      "fallback_source": {"type": ["string", "null"]},
      "fallback_level": {"type": "string", "enum": list(FALLBACK_LEVELS)},
      "confidence_score": {"type": "number"},
      "benchmark_recency": {"type": ["string", "null"]},
      "revenue_growth_path": {
        "type": ["array", "null"],
        "items": {"type": "number"},
      },
      "gross_margin_band": metric_band,
      "ebitda_margin_band": metric_band,
      "opex_intensity": metric_band,
      "payroll_intensity": metric_band,
      "capex_percent_revenue": metric_band,
      "depreciation_percent_revenue": metric_band,
      "working_capital": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
          "dso": metric_band,
          "dpo": metric_band,
          "inventory_days": metric_band,
        },
        "required": ["dso", "dpo", "inventory_days"],
      },
    },
    "required": [
      "contract_version",
      "benchmark_resolver_version",
      "matched_naics_code",
      "matched_naics_level",
      "fallback_source",
      "fallback_level",
      "confidence_score",
      "benchmark_recency",
      "revenue_growth_path",
      "gross_margin_band",
      "ebitda_margin_band",
      "opex_intensity",
      "payroll_intensity",
      "capex_percent_revenue",
      "depreciation_percent_revenue",
      "working_capital",
    ],
  }


def constraint_engine_output_schema() -> Dict[str, Any]:
  bound = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "min": {"type": ["number", "null"]},
      "max": {"type": ["number", "null"]},
    },
    "required": ["min", "max"],
  }
  constraint = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "constraint_id": {"type": "string"},
      "metric": {"type": "string"},
      "bound_type": {"type": "string", "enum": ["hard", "soft", "prior"]},
      "constraint_class": {"type": "string", "enum": list(CONSTRAINT_CLASSES)},
      "source_type": {"type": "string", "enum": ["fact", "trait", "naics", "alpha", "generic"]},
      "confidence_score": {"type": "number"},
      "explanation": {"type": "string"},
      "engine_version": {"type": "string"},
    },
    "required": [
      "constraint_id",
      "metric",
      "bound_type",
      "constraint_class",
      "source_type",
      "confidence_score",
      "explanation",
      "engine_version",
    ],
  }
  working_capital = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "dso": bound,
      "dpo": bound,
      "inventory_days": bound,
    },
    "required": ["dso", "dpo", "inventory_days"],
  }
  return {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "contract_version": {"type": "string"},
      "engine_version": {"type": "string"},
      "constraint_confidence_score": {"type": "number"},
      "fallback_level": {"type": "string", "enum": list(FALLBACK_LEVELS)},
      "supportable_unit_range": bound,
      "supportable_revenue_range": bound,
      "gross_margin_band": bound,
      "ebitda_margin_band": bound,
      "payroll_intensity_band": bound,
      "opex_intensity_band": bound,
      "working_capital_band": working_capital,
      "utilization_range": bound,
      "demand_supported_units": {"type": ["number", "null"]},
      "solver_mutable_levers": {"type": "array", "items": {"type": "string"}},
      "solver_protected_facts": {"type": "array", "items": {"type": "string"}},
      "violations": {"type": "array", "items": {"type": "string", "enum": list(VIOLATION_CODES)}},
      "hard_violation_codes": {"type": "array", "items": {"type": "string", "enum": list(VIOLATION_CODES)}},
      "soft_violation_codes": {"type": "array", "items": {"type": "string", "enum": list(VIOLATION_CODES)}},
      "context_violation_codes": {"type": "array", "items": {"type": "string", "enum": list(VIOLATION_CODES)}},
      "constraints": {"type": "array", "items": constraint},
      "findings": {"type": "array", "items": {"type": "object"}},
      "current_metrics": {"type": ["object", "null"]},
      "summary": {"type": ["object", "null"]},
    },
    "required": [
      "contract_version",
      "engine_version",
      "constraint_confidence_score",
      "fallback_level",
      "supportable_unit_range",
      "supportable_revenue_range",
      "gross_margin_band",
      "ebitda_margin_band",
      "payroll_intensity_band",
      "opex_intensity_band",
      "working_capital_band",
      "utilization_range",
      "demand_supported_units",
      "solver_mutable_levers",
      "solver_protected_facts",
      "violations",
      "hard_violation_codes",
      "soft_violation_codes",
      "context_violation_codes",
      "constraints",
      "findings",
    ],
  }


def forecast_quarter_state_schema() -> Dict[str, Any]:
  return {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "quarter_index": {"type": "integer"},
      "period_label": {"type": "string"},
      "revenue": {"type": ["number", "null"]},
      "units": {"type": ["number", "null"]},
      "price": {"type": ["number", "null"]},
      "utilization": {"type": ["number", "null"]},
      "payroll": {"type": ["number", "null"]},
      "marketing": {"type": ["number", "null"]},
      "opex": {"type": ["number", "null"]},
      "cogs": {"type": ["number", "null"]},
      "ebitda": {"type": ["number", "null"]},
      "net_income": {"type": ["number", "null"]},
      "working_capital": {"type": ["object", "null"]},
      "capex": {"type": ["number", "null"]},
      "depreciation": {"type": ["number", "null"]},
      "realism_check_status": {"type": "string", "enum": ["within_band", "above", "below", "insufficient_data"]},
      "constraint_violations": {"type": "array", "items": {"type": "string", "enum": list(VIOLATION_CODES)}},
      "convergence_progress": {"type": ["number", "null"]},
    },
    "required": [
      "quarter_index",
      "period_label",
      "revenue",
      "units",
      "price",
      "utilization",
      "payroll",
      "marketing",
      "opex",
      "cogs",
      "ebitda",
      "net_income",
      "working_capital",
      "capex",
      "depreciation",
      "realism_check_status",
      "constraint_violations",
      "convergence_progress",
    ],
  }


def engine_versions_payload() -> Dict[str, Any]:
  return {
    "contract_version": PLANNING_CONTRACT_VERSION,
    "constraint_traits_version": None,
    "constraint_engine_version": None,
    "forecast_engine_version": None,
    "convergence_policy_version": None,
    "benchmark_resolver_version": None,
  }


def planning_contract_payload() -> Dict[str, Any]:
  return {
    "contract_version": PLANNING_CONTRACT_VERSION,
    "solver_mutable_levers": list(SOLVER_MUTABLE_LEVERS),
    "solver_protected_facts": list(SOLVER_PROTECTED_FACTS),
    "violation_codes": list(VIOLATION_CODES),
    "fallback_levels": list(FALLBACK_LEVELS),
    "schemas": {
      "normalized_traits": normalized_traits_schema(),
      "alpha_benchmark_payload": alpha_benchmark_payload_schema(),
      "constraint_engine_output": constraint_engine_output_schema(),
      "forecast_quarter_state": forecast_quarter_state_schema(),
    },
  }
