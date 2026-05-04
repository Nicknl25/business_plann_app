"""Table-selected deterministic formulas for post-intake model drivers.

The SQL mapping table owns which formula key applies to each lever. This module
owns the tiny approved implementation registry for those keys.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, Iterable, List, Optional


SEED_FORMULA_KEYS = {
  "annual_source_value_divided_by_annual_revenue",
  "runtime_revenue_driver_from_stage_ramp",
  "runtime_quarter_currency_direct",
  "runtime_ratio_direct",
  "python_derived_schedule",
  "cash_strategy_schedule",
  "none",
}

FINMO_FORMULA_KEYS = {
  "revenue_times_model_input_ratio",
  "finmo_revenue_equals_capacity_price_utilization_bundle",
  "finmo_direct_quarter_currency",
  "finmo_debt_schedule_interest",
  "finmo_prior_ppe_times_model_input_ratio",
  "finmo_working_capital_days",
  "finmo_cash_strategy_driver",
  "finmo_python_derived_schedule",
  "none",
}

VALIDATION_FORMULA_KEYS = {
  "finmo_equals_revenue_times_model_input_ratio",
  "finmo_revenue_equals_capacity_price_utilization_bundle",
  "finmo_equals_model_input_value",
  "finmo_working_capital_days",
  "finmo_short_term_debt_percent_of_ltd",
  "semantic_presence_only",
  "schedule_marker_validation",
  "none",
}

REQUIRED_WHEN_KEYS = {
  "always",
  "revenue_positive",
  "business_applicable",
  "debt_outstanding",
  "debt_policy_or_existing_debt",
  "prior_ppe_positive",
  "cash_strategy_requires",
  "optional",
}

BUSINESS_APPLICABILITY_KEYS = {
  "always",
  "revenue_positive",
  "revenue_positive_ar_applicable",
  "operating_expense_positive_ap_applicable",
  "inventory_business_or_seed",
  "revenue_positive_prepaid_applicable",
  "deferred_revenue_business",
  "debt_policy_or_existing_debt",
  "cash_strategy_requires",
  "optional",
}

FORECAST_PRESENCE_RULE_KEYS = {
  "positive_driver_when_applicable",
  "nonnegative_driver",
  "schedule_reconciles_when_applicable",
  "optional_zero_allowed",
}


def clean_text(value: Any) -> str:
  return str(value or "").strip()


def json_list(value: Any) -> List[str]:
  if isinstance(value, list):
    return [clean_text(item) for item in value if clean_text(item)]
  raw = clean_text(value)
  if not raw:
    return []
  try:
    parsed = json.loads(raw)
  except Exception:
    return [raw]
  if isinstance(parsed, list):
    return [clean_text(item) for item in parsed if clean_text(item)]
  return []


def mapping_formula_defaults(row: Dict[str, Any]) -> Dict[str, Any]:
  """Return deterministic formula metadata defaults for a mapping row."""
  lever_id = clean_text(row.get("lever_id"))
  input_semantics = clean_text(row.get("input_semantics")).lower()
  driver_bundle = clean_text(row.get("driver_bundle")).lower()
  owner = clean_text(row.get("control_owner")).lower()
  financial_field = clean_text(row.get("financial_model_field")).lower()

  seed_source_paths: List[str] = []
  seed_formula_key = "runtime_ratio_direct"
  finmo_formula_key = "none"
  validation_formula_key = "semantic_presence_only"
  required_when_key = "always"
  business_applicability_key = "always"
  forecast_presence_rule_key = "nonnegative_driver"
  zero_allowed_reason_key = "not_applicable_or_table_optional"
  missing_seed_default_value: Optional[float] = None
  minimum_live_value: Optional[float] = None
  maximum_live_value: Optional[float] = None
  allow_zero = True

  if owner in {"cash_pass"} and driver_bundle not in {"working_capital_bundle", "debt_schedule_bundle"}:
    seed_formula_key = "cash_strategy_schedule"
    finmo_formula_key = "finmo_cash_strategy_driver"
    validation_formula_key = "semantic_presence_only"
    required_when_key = "cash_strategy_requires"
    business_applicability_key = "cash_strategy_requires"
    forecast_presence_rule_key = "schedule_reconciles_when_applicable"
  elif owner == "python_derived":
    seed_formula_key = "python_derived_schedule"
    finmo_formula_key = "finmo_python_derived_schedule"
    validation_formula_key = "schedule_marker_validation"
    forecast_presence_rule_key = "schedule_reconciles_when_applicable"
  elif driver_bundle == "revenue_formula_bundle":
    seed_formula_key = "runtime_revenue_driver_from_stage_ramp"
    finmo_formula_key = "finmo_revenue_equals_capacity_price_utilization_bundle"
    validation_formula_key = "finmo_revenue_equals_capacity_price_utilization_bundle"
    allow_zero = False
    business_applicability_key = "revenue_positive"
    forecast_presence_rule_key = "positive_driver_when_applicable"
  elif input_semantics == "percent_of_revenue":
    seed_formula_key = "annual_source_value_divided_by_annual_revenue"
    finmo_formula_key = "revenue_times_model_input_ratio"
    validation_formula_key = "finmo_equals_revenue_times_model_input_ratio"
    required_when_key = "revenue_positive"
    business_applicability_key = "revenue_positive"
    if lever_id == "expenses::Cost of Goods Sold":
      seed_source_paths = ["financials.current_cogs", "financials.cogs", "financials.cogs_absolute"]
    elif lever_id == "expenses::Marketing":
      seed_source_paths = ["financials.marketing_total_year1", "financials.marketing_expense", "financials.marketing"]
      allow_zero = False
    elif lever_id == "expenses::Research & Development":
      seed_source_paths = ["financials.r_and_d_total_year1", "financials.research_and_development"]
      allow_zero = True
    elif lever_id == "expenses::General & Administrative":
      seed_source_paths = ["financials.other_opex_absolute", "financials.other_operating_expense"]
      allow_zero = False
    elif lever_id == "balance_sheet::Prepaid Expenses (% of Revenue)":
      seed_formula_key = "cash_strategy_schedule"
      finmo_formula_key = "revenue_times_model_input_ratio"
      validation_formula_key = "finmo_equals_revenue_times_model_input_ratio"
      required_when_key = "business_applicable"
      business_applicability_key = "revenue_positive_prepaid_applicable"
      forecast_presence_rule_key = "positive_driver_when_applicable"
      zero_allowed_reason_key = "revenue_not_positive"
    elif lever_id == "balance_sheet::Deferred Revenue (% of Revenue)":
      seed_formula_key = "cash_strategy_schedule"
      finmo_formula_key = "revenue_times_model_input_ratio"
      validation_formula_key = "finmo_equals_revenue_times_model_input_ratio"
      required_when_key = "business_applicable"
      business_applicability_key = "deferred_revenue_business"
      forecast_presence_rule_key = "positive_driver_when_applicable"
      zero_allowed_reason_key = "no_upfront_or_deferred_revenue_model"
  elif input_semantics == "quarter_currency":
    seed_formula_key = "runtime_quarter_currency_direct"
    finmo_formula_key = "finmo_direct_quarter_currency"
    validation_formula_key = "finmo_equals_model_input_value" if lever_id == "expenses::Lease" else "semantic_presence_only"
    allow_zero = lever_id not in {"expenses::Payroll"}
    if lever_id == "expenses::Lease":
      seed_source_paths = ["financials.monthly_rent_expense"]
  elif input_semantics == "interest_rate":
    seed_formula_key = "python_derived_schedule"
    finmo_formula_key = "finmo_debt_schedule_interest"
    validation_formula_key = "semantic_presence_only"
    required_when_key = "debt_outstanding"
  elif input_semantics == "percent_of_prior_ppe":
    seed_formula_key = "python_derived_schedule"
    finmo_formula_key = "finmo_prior_ppe_times_model_input_ratio"
    validation_formula_key = "schedule_marker_validation"
    required_when_key = "prior_ppe_positive"
  elif input_semantics in {"days", "percent_of_long_term_debt"}:
    seed_formula_key = "cash_strategy_schedule"
    finmo_formula_key = "finmo_working_capital_days" if input_semantics == "days" else "finmo_cash_strategy_driver"
    validation_formula_key = "finmo_working_capital_days" if input_semantics == "days" else "finmo_short_term_debt_percent_of_ltd"
    required_when_key = "business_applicable" if input_semantics == "days" else "debt_policy_or_existing_debt"
    forecast_presence_rule_key = "positive_driver_when_applicable"
    if lever_id == "balance_sheet::Accounts Receivable Days":
      business_applicability_key = "revenue_positive_ar_applicable"
      zero_allowed_reason_key = "revenue_not_positive"
      minimum_live_value = 1.0
      maximum_live_value = 90.0
    elif lever_id == "balance_sheet::Accounts Payable Days":
      business_applicability_key = "operating_expense_positive_ap_applicable"
      zero_allowed_reason_key = "no_vendor_payables_model"
      minimum_live_value = 1.0
      maximum_live_value = 90.0
    elif lever_id == "balance_sheet::Inventory Days":
      business_applicability_key = "inventory_business_or_seed"
      zero_allowed_reason_key = "inventory_not_applicable"
      minimum_live_value = 1.0
      maximum_live_value = 180.0
    else:
      business_applicability_key = "debt_policy_or_existing_debt"
      forecast_presence_rule_key = "schedule_reconciles_when_applicable"
      zero_allowed_reason_key = "no_debt_policy_or_existing_debt"
      minimum_live_value = 0.0
      maximum_live_value = 1.0
  if lever_id == "balance_sheet::Prepaid Expenses (% of Revenue)":
    minimum_live_value = 0.01
    maximum_live_value = 0.20
  elif lever_id == "balance_sheet::Deferred Revenue (% of Revenue)":
    minimum_live_value = 0.01
    maximum_live_value = 0.75

  if "capital_expenditures" in financial_field:
    seed_formula_key = "python_derived_schedule"
    finmo_formula_key = "finmo_python_derived_schedule"
    validation_formula_key = "schedule_marker_validation"

  return {
    "seed_source_paths": seed_source_paths,
    "seed_formula_key": seed_formula_key,
    "finmo_formula_key": finmo_formula_key,
    "validation_formula_key": validation_formula_key,
    "required_when_key": required_when_key,
    "business_applicability_key": business_applicability_key,
    "forecast_presence_rule_key": forecast_presence_rule_key,
    "zero_allowed_reason_key": zero_allowed_reason_key,
    "missing_seed_default_value": missing_seed_default_value,
    "minimum_live_value": minimum_live_value,
    "maximum_live_value": maximum_live_value,
    "allow_zero": bool(allow_zero),
  }


def normalize_formula_metadata(row: Dict[str, Any]) -> Dict[str, Any]:
  defaults = mapping_formula_defaults(row)
  return {
    "seed_source_paths": json_list(row.get("seed_source_paths_json")) or list(defaults["seed_source_paths"]),
    "seed_formula_key": clean_text(row.get("seed_formula_key")).lower() or defaults["seed_formula_key"],
    "finmo_formula_key": clean_text(row.get("finmo_formula_key")).lower() or defaults["finmo_formula_key"],
    "validation_formula_key": clean_text(row.get("validation_formula_key")).lower() or defaults["validation_formula_key"],
    "required_when_key": clean_text(row.get("required_when_key")).lower() or defaults["required_when_key"],
    "business_applicability_key": clean_text(row.get("business_applicability_key")).lower() or defaults["business_applicability_key"],
    "forecast_presence_rule_key": clean_text(row.get("forecast_presence_rule_key")).lower() or defaults["forecast_presence_rule_key"],
    "zero_allowed_reason_key": clean_text(row.get("zero_allowed_reason_key")).lower() or defaults["zero_allowed_reason_key"],
    "missing_seed_default_value": row.get("missing_seed_default_value") if row.get("missing_seed_default_value") is not None else defaults["missing_seed_default_value"],
    "minimum_live_value": row.get("minimum_live_value") if row.get("minimum_live_value") is not None else defaults["minimum_live_value"],
    "maximum_live_value": row.get("maximum_live_value") if row.get("maximum_live_value") is not None else defaults["maximum_live_value"],
    "allow_zero": bool(row.get("allow_zero")) if row.get("allow_zero") is not None else bool(defaults["allow_zero"]),
    "formula_status": clean_text(row.get("formula_status")).lower() or "active",
  }


def formula_metadata_errors(row: Dict[str, Any]) -> List[str]:
  lever_id = clean_text(row.get("lever_id")) or clean_text(row.get("lookup_lever_id")) or "unknown"
  metadata = normalize_formula_metadata(row)
  errors: List[str] = []
  if metadata["formula_status"] not in {"active", "retired", "review"}:
    errors.append(f"{lever_id} has unsupported formula_status {metadata['formula_status']}")
  if metadata["formula_status"] != "active":
    return errors
  if metadata["seed_formula_key"] not in SEED_FORMULA_KEYS:
    errors.append(f"{lever_id} has unsupported seed_formula_key {metadata['seed_formula_key']}")
  if metadata["finmo_formula_key"] not in FINMO_FORMULA_KEYS:
    errors.append(f"{lever_id} has unsupported finmo_formula_key {metadata['finmo_formula_key']}")
  if metadata["validation_formula_key"] not in VALIDATION_FORMULA_KEYS:
    errors.append(f"{lever_id} has unsupported validation_formula_key {metadata['validation_formula_key']}")
  if metadata["required_when_key"] not in REQUIRED_WHEN_KEYS:
    errors.append(f"{lever_id} has unsupported required_when_key {metadata['required_when_key']}")
  if metadata["business_applicability_key"] not in BUSINESS_APPLICABILITY_KEYS:
    errors.append(f"{lever_id} has unsupported business_applicability_key {metadata['business_applicability_key']}")
  if metadata["forecast_presence_rule_key"] not in FORECAST_PRESENCE_RULE_KEYS:
    errors.append(f"{lever_id} has unsupported forecast_presence_rule_key {metadata['forecast_presence_rule_key']}")
  if metadata["seed_formula_key"] == "annual_source_value_divided_by_annual_revenue" and not metadata["seed_source_paths"]:
    errors.append(f"{lever_id} needs seed_source_paths_json for {metadata['seed_formula_key']}")
  contextual_seed_candidate = (
    lever_id.startswith("balance_sheet::")
    and metadata["forecast_presence_rule_key"] == "positive_driver_when_applicable"
  )
  if contextual_seed_candidate and metadata["minimum_live_value"] is None:
    errors.append(f"{lever_id} needs minimum_live_value for table-backed applicability validation")
  if contextual_seed_candidate and metadata["maximum_live_value"] is None:
    errors.append(f"{lever_id} needs maximum_live_value for table-backed applicability validation")
  return errors


def get_path(payload: Any, dotted_path: str) -> Any:
  current = payload
  for part in clean_text(dotted_path).split("."):
    if not part:
      continue
    if isinstance(current, dict):
      current = current.get(part)
    else:
      return None
  return current


def first_numeric_from_paths(payload: Dict[str, Any], paths: Iterable[str]) -> Optional[float]:
  for path in paths:
    value = get_path(payload, path)
    if value is None or value == "":
      continue
    try:
      number = float(value)
    except Exception:
      continue
    return number
  return None


def apply_seed_formula(
  *,
  formula_contract: Dict[str, Any],
  context: Dict[str, Any],
  default_value: Any = 0.0,
) -> float:
  """Execute an approved table-selected seed formula."""
  key = clean_text(formula_contract.get("seed_formula_key")).lower()
  if key not in SEED_FORMULA_KEYS:
    raise RuntimeError(f"post_intake_seed_formula_key_unsupported: {key or 'missing'}")
  if key == "annual_source_value_divided_by_annual_revenue":
    annual_revenue = float(context.get("annual_revenue") or 0.0)
    if annual_revenue <= 0:
      return 0.0
    source = first_numeric_from_paths(context, formula_contract.get("seed_source_paths") or [])
    return max(0.0, float(source or 0.0)) / annual_revenue
  try:
    return float(default_value or 0.0)
  except Exception:
    return 0.0


def formula_contract_for_mapping_row(row: Dict[str, Any]) -> Dict[str, Any]:
  metadata = normalize_formula_metadata(row)
  return {
    **copy.deepcopy(row),
    **metadata,
    "formula_source_of_truth": "sql.post_intak_mapping_lookup",
    "formula_registry": "post_intake_driver_formulas",
  }
