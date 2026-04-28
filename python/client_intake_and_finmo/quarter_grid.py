from __future__ import annotations

import json
import math
import os
import re
import time
import copy
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests
try:
  from openai_http import post_openai_with_retries  # type: ignore
except Exception:
  from client_intake_and_finmo.openai_http import post_openai_with_retries  # type: ignore
from financial_model_engine.finmo_model import calculate_finmo_model
from financial_model_engine.model_inputs import FinancialModelInputs, QUARTER_COUNT

try:
  from realism_memo import load_realism_memo_grid_advisory_prompt, normalize_realism_memo_payload  # type: ignore
except Exception:
  try:
    from client_intake_and_finmo.realism_memo import load_realism_memo_grid_advisory_prompt, normalize_realism_memo_payload  # type: ignore
  except Exception:
    def load_realism_memo_grid_advisory_prompt() -> str:
      return "The realism memo is additional context only."

    def normalize_realism_memo_payload(payload: Any) -> Dict[str, Any]:
      return {"status": "not_generated", "issues": []}

try:
  from post_intake_mapping import stage_planning_ramp_policy  # type: ignore
except Exception:
  from client_intake_and_finmo.post_intake_mapping import stage_planning_ramp_policy  # type: ignore

_PLANNING_MODE_DEFAULTS: Dict[str, str] = {
  "turnaround": (
    "Assume you are allowed to use every listed variable as part of one coherent repair plan for this actual company. "
    "Realistically, what would make this business profitable as soon as it can become profitable without breaking business reality? "
    "Use the full company context and behave like an operator trying to make the company truly work, not just cosmetically improve."
  ),
  "normalize": (
    "This case may be over-optimistic or commercially overstated rather than distressed. "
    "Your job is to normalize the plan to something believable for the company's stage and business model. "
    "Dial back unrealistic pricing, utilization, capacity, margins, cash build, or timing when needed, but do not force a turnaround story if the business is not truly broken. "
    "Business stage matters. Preserve real upside where believable, but remove fantasy."
  ),
  "rebalance": (
    "This case appears directionally sound but misbalanced. "
    "Your job is to rebalance the model to a more believable operating path for the company's stage, tightening weak assumptions without forcing an unnecessary rescue or overcorrection."
  ),
}

_GRID_EXCLUDED_LEVER_IDS = {
  "balance_sheet::PPE $ (Excluding Capital Leases)",
  "balance_sheet::Accumulated Depreciation",
}

_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


def _safe_float(value: Any) -> float:
  try:
    num = float(value)
  except Exception:
    return 0.0
  if num != num:
    return 0.0
  return num


def _safe_ratio(value: Any) -> Optional[float]:
  try:
    ratio = float(value)
  except Exception:
    return None
  if ratio != ratio:
    return None
  if ratio > 1.0 and ratio <= 100.0:
    ratio = ratio / 100.0
  return ratio


def _cogs_dollars_from_financials(financials: Dict[str, Any], year1: Dict[str, Any], revenue: float) -> float:
  for key in ("cogs_percent_of_revenue", "cogs_percent", "estimated_cogs_percent"):
    ratio = _safe_ratio(financials.get(key))
    if ratio is not None and ratio > 0.0:
      return max(0.0, float(revenue) * float(ratio))
  cogs_value = _safe_float(
    financials.get("cogs_total_year1")
    or year1.get("company_cogs_total_year1")
    or year1.get("cogs_total_year1")
    or financials.get("current_cogs")
  )
  implied_ratio = (cogs_value / revenue) if revenue > 0.0 else 0.0
  if 1.0 < cogs_value <= 100.0 and implied_ratio < 0.05:
    return max(0.0, revenue * (cogs_value / 100.0))
  return max(0.0, cogs_value)


def _build_baseline_financial_summary(
  *,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Dict[str, Any]:
  financials = financials_json if isinstance(financials_json, dict) else {}
  year1 = financials_year1_json if isinstance(financials_year1_json, dict) else {}
  revenue = _safe_float(year1.get("company_revenue_total_year1") or financials.get("current_revenue"))
  cogs = _cogs_dollars_from_financials(financials, year1, revenue)
  gross_profit = revenue - cogs
  payroll = _safe_float(
    financials.get("current_payroll")
    or financials.get("payroll_total_year1")
    or year1.get("company_payroll_total_year1")
    or year1.get("payroll_total_year1")
  )
  marketing = _safe_float(
    financials.get("marketing_total_year1")
    or year1.get("company_marketing_total_year1")
    or year1.get("marketing_total_year1")
  )
  rent_annualized = _safe_float(financials.get("monthly_rent_expense")) * 12.0
  other_opex_non_rent = _safe_float(
    financials.get("other_operating_expense")
    or year1.get("other_operating_expense_total_year1")
    or year1.get("other_operating_expense")
  )
  other_opex = other_opex_non_rent + rent_annualized
  ebitda = gross_profit - payroll - marketing - other_opex
  interest = _safe_float(financials.get("annual_interest_payment"))
  taxes = 0.0
  net_income = ebitda - interest - taxes
  return {
    "revenue": revenue,
    "cogs": cogs,
    "gross_profit": gross_profit,
    "payroll": payroll,
    "marketing": marketing,
    "other_opex": other_opex,
    "other_opex_non_rent": other_opex_non_rent,
    "rent_annualized": rent_annualized,
    "ebitda": ebitda,
    "interest": interest,
    "taxes": taxes,
    "net_income": net_income,
    "taxes_assumed_zero": True,
  }


def _require_openai_key() -> str:
  key = (os.getenv("OPENAI_API_KEY") or "").strip()
  if not key:
    raise RuntimeError("OPENAI_API_KEY is not configured.")
  return key


def _openai_model() -> str:
  return (
    os.getenv("GRID_STRATEGY_MODEL")
    or os.getenv("OPENAI_MODEL")
    or "gpt-5.1"
  ).strip() or "gpt-5.1"


def _timeout_env_int(name: str, default: int) -> int:
  raw = (os.getenv(name) or "").strip()
  if not raw:
    return default
  try:
    return max(15, int(raw))
  except Exception:
    return default


def _openai_timeout_seconds(kind: str = "default") -> Optional[int]:
  normalized_kind = str(kind or "default").strip().lower()
  if normalized_kind == "strategy":
    return _timeout_env_int("GRID_STRATEGY_TIMEOUT_SECONDS", _timeout_env_int("OPENAI_TIMEOUT_SECONDS", 90))
  return _timeout_env_int("OPENAI_TIMEOUT_SECONDS", 90)


def _post_openai(
  *,
  url: str,
  headers: Dict[str, str],
  payload: Dict[str, Any],
  timeout_seconds: Optional[int] = None,
  max_attempts: int = 3,
) -> requests.Response:
  timeout = timeout_seconds if timeout_seconds is not None else _openai_timeout_seconds()
  return post_openai_with_retries(
    url=url,
    headers=headers,
    payload=payload,
    timeout_seconds=timeout,
    retryable_status=_RETRYABLE_STATUS,
    max_attempts=max(1, int(max_attempts or 1)),
  )


def _parse_json_response(data: Dict[str, Any]) -> Dict[str, Any]:
  for item in data.get("output") or []:
    if not isinstance(item, dict):
      continue
    for part in item.get("content") or []:
      if not isinstance(part, dict):
        continue
      parsed = part.get("parsed")
      if isinstance(parsed, dict):
        return parsed
      raw = str(part.get("text") or "").strip()
      if not raw:
        continue
      try:
        parsed = json.loads(raw)
      except Exception:
        continue
      if isinstance(parsed, dict):
        return parsed
  return {}


def _sanitize_canonical_live_payload(value: Any) -> Any:
  if isinstance(value, dict):
    return {str(raw_key or ""): _sanitize_canonical_live_payload(raw_val) for raw_key, raw_val in value.items()}
  if isinstance(value, list):
    return [_sanitize_canonical_live_payload(item) for item in value]
  return value


def _baseline_summary_from_finmo_json(finmo_json: Dict[str, Any]) -> Dict[str, Any]:
  quarter_rows = [item for item in ((finmo_json.get("quarter_rows") or []) if isinstance(finmo_json, dict) else []) if isinstance(item, dict)]
  active_rows = [row for row in quarter_rows if int(row.get("quarter_index") or 0) >= 1]
  first_year = active_rows[:4]
  if first_year:
    revenue = sum(float_or_none(item.get("revenue")) or 0.0 for item in first_year)
    cogs = sum(float_or_none(item.get("cost_of_goods_sold")) or 0.0 for item in first_year)
    gross_profit = sum(float_or_none(item.get("gross_profit")) or 0.0 for item in first_year)
    payroll = sum(float_or_none(item.get("payroll")) or 0.0 for item in first_year)
    marketing = sum(float_or_none(item.get("marketing")) or 0.0 for item in first_year)
    other_opex = sum(
      (float_or_none(item.get("lease_rent")) or 0.0)
      + (float_or_none(item.get("general_and_administrative")) or 0.0)
      + (float_or_none(item.get("research_and_development")) or 0.0)
      for item in first_year
    )
    ebitda = sum(float_or_none(item.get("ebitda")) or 0.0 for item in first_year)
    net_income = sum(float_or_none(item.get("net_income")) or 0.0 for item in first_year)
    return {
      "revenue": revenue,
      "cogs": cogs,
      "gross_profit": gross_profit,
      "payroll": payroll,
      "marketing": marketing,
      "other_opex": other_opex,
      "ebitda": ebitda,
      "net_income": net_income,
    }
  return {}


def _diagnose_planning_case(
  *,
  baseline_summary: Dict[str, Any],
) -> Dict[str, Any]:
  revenue = max(1.0, float_or_none((baseline_summary or {}).get("revenue")) or 0.0)
  ebitda = float_or_none((baseline_summary or {}).get("ebitda")) or 0.0
  payroll = float_or_none((baseline_summary or {}).get("payroll")) or 0.0
  marketing = float_or_none((baseline_summary or {}).get("marketing")) or 0.0
  other_opex = float_or_none((baseline_summary or {}).get("other_opex")) or 0.0
  ebitda_margin = ebitda / revenue if revenue > 0 else 0.0
  if payroll >= marketing and payroll >= other_opex:
    primary_cause = "payroll-driven"
  elif marketing >= payroll and marketing >= other_opex:
    primary_cause = "marketing-driven"
  else:
    primary_cause = "mixed"
  if ebitda < -0.10 * revenue:
    severity = "severe"
  elif ebitda < 0:
    severity = "moderate"
  else:
    severity = "mild"
  preferred: List[str] = []
  if ebitda > 0 and ebitda_margin > 0.30:
    preferred.append("reality_normalization_strategy")
  elif ebitda < 0:
    preferred.extend(["demand_supported_growth", "staffing_ramp_adjustment"])
  else:
    preferred.extend(["operational_balance_strategy", "pricing_adjustment"])
  return {
    "primary_cause": primary_cause,
    "severity_class": severity,
    "preferred_strategy_ids": preferred,
  }


def _prompt_library_dir() -> Path:
  return Path(__file__).resolve().parent / "prompts" / "quarter_grid"


def available_planning_modes() -> List[str]:
  names = set(_PLANNING_MODE_DEFAULTS.keys())
  prompt_dir = _prompt_library_dir()
  if prompt_dir.exists():
    for path in prompt_dir.glob("*.md"):
      if path.stem.strip():
        names.add(path.stem.strip().lower())
  preferred_order = ["turnaround", "normalize", "rebalance"]
  ordered = [name for name in preferred_order if name in names]
  ordered.extend(sorted(name for name in names if name not in preferred_order))
  return ordered


def resolve_planning_mode(planning_mode: str) -> str:
  mode = str(planning_mode or "").strip().lower()
  if mode in available_planning_modes():
    return mode
  return "turnaround"


def _load_planning_mode_prompt_file(planning_mode: str) -> str:
  mode = resolve_planning_mode(planning_mode)
  path = _prompt_library_dir() / f"{mode}.md"
  try:
    text = path.read_text(encoding="utf-8").strip()
  except Exception:
    text = ""
  return text


def planning_mode_text(planning_mode: str) -> str:
  mode = resolve_planning_mode(planning_mode)
  prompt_file_text = _load_planning_mode_prompt_file(mode)
  if prompt_file_text:
    return prompt_file_text
  return _PLANNING_MODE_DEFAULTS.get(mode) or _PLANNING_MODE_DEFAULTS["turnaround"]


def planning_mode_prompt_file(planning_mode: str) -> str:
  mode = resolve_planning_mode(planning_mode)
  return str((_prompt_library_dir() / f"{mode}.md").resolve())


def classify_planning_mode(
  *,
  baseline_summary: Dict[str, Any],
  diagnosis: Dict[str, Any],
) -> Dict[str, str]:
  severity = str((diagnosis or {}).get("severity_class") or "").strip().lower()
  primary = str((diagnosis or {}).get("primary_cause") or "").strip().lower()
  preferred = [str(item or "").strip().lower() for item in ((diagnosis or {}).get("preferred_strategy_ids") or [])]
  revenue = max(1.0, float_or_none((baseline_summary or {}).get("revenue")) or 0.0)
  ebitda = float_or_none((baseline_summary or {}).get("ebitda")) or 0.0
  ebitda_margin = ebitda / revenue if revenue > 0 else 0.0

  if "reality_normalization_strategy" in preferred or (ebitda > 0 and ebitda_margin > 0.30):
    return {
      "planning_mode": "normalize",
      "planning_mode_reason": "app_classified_overstated_or_overoptimistic_case",
    }
  if severity == "severe" or ebitda < 0:
    return {
      "planning_mode": "turnaround",
      "planning_mode_reason": (
        "app_classified_turnaround_case"
        if severity == "severe"
        else f"app_classified_loss_making_case:{primary or 'mixed'}"
      ),
    }
  return {
    "planning_mode": "rebalance",
    "planning_mode_reason": "app_classified_misaligned_but_salvageable_case",
  }


def determine_planning_mode(
  *,
  ops_json: Dict[str, Any],
  target_market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  fulfillment_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  business_facts: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  del ops_json, target_market_json, people_json, fulfillment_json, marketing_model_json, business_facts
  baseline_summary = _baseline_summary_from_finmo_json(finmo_json) or _build_baseline_financial_summary(
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
  )
  diagnosis = _diagnose_planning_case(baseline_summary=baseline_summary)
  classification = classify_planning_mode(
    baseline_summary=baseline_summary,
    diagnosis=diagnosis,
  )
  planning_mode = resolve_planning_mode(str(classification.get("planning_mode") or ""))
  return {
    "planning_mode": planning_mode,
    "planning_mode_reason": str(classification.get("planning_mode_reason") or "").strip(),
    "prompt_file": planning_mode_prompt_file(planning_mode),
    "baseline_summary": _sanitize_canonical_live_payload(baseline_summary or {}),
    "diagnosis": _sanitize_canonical_live_payload(diagnosis or {}),
    "fixed_facts": {
      "model_input_json": _sanitize_canonical_live_payload(model_input_json or {}),
      "finmo_json": _sanitize_canonical_live_payload(finmo_json or {}),
    },
  }


def _ops_lob_product_summary(ops_json: Dict[str, Any]) -> List[Dict[str, Any]]:
  summary: List[Dict[str, Any]] = []
  lob_models = ops_json.get("lob_models") if isinstance((ops_json or {}).get("lob_models"), list) else []
  for lob in lob_models:
    if not isinstance(lob, dict):
      continue
    products = []
    for product in (lob.get("products") or []):
      if not isinstance(product, dict):
        continue
      products.append(
        {
          "product_name": str(product.get("product_name") or "").strip(),
          "unit_name": str(product.get("unit_name") or "").strip(),
          "unit_cadence": str(product.get("unit_cadence") or "").strip(),
          "unit_description": str(product.get("unit_description") or "").strip(),
        }
      )
    if products:
      summary.append(
        {
          "lob_name": str(lob.get("lob_name") or "").strip() or "Primary line of business",
          "product_count": len(products),
          "products": products,
        }
      )
  return summary


def _shared_capacity_lobs(
  *,
  ops_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> List[Dict[str, Any]]:
  groups: List[Dict[str, Any]] = []
  ops_lobs = ops_json.get("lob_models") if isinstance((ops_json or {}).get("lob_models"), list) else []
  year1_lobs = {
    str(item.get("lob_name") or "").strip() or "Primary line of business": item
    for item in (financials_year1_json.get("lobs") or [])
    if isinstance(item, dict)
  }
  for lob in ops_lobs:
    if not isinstance(lob, dict):
      continue
    lob_name = str(lob.get("lob_name") or "").strip() or "Primary line of business"
    ops_products = [item for item in (lob.get("products") or []) if isinstance(item, dict)]
    if len(ops_products) < 2:
      continue
    year1_lob = year1_lobs.get(lob_name) if isinstance(year1_lobs.get(lob_name), dict) else {}
    year1_products = {
      str(item.get("product_name") or "").strip(): item
      for item in (year1_lob.get("products") or [])
      if isinstance(item, dict) and str(item.get("product_name") or "").strip()
    }
    product_names = [str(item.get("product_name") or "").strip() for item in ops_products if str(item.get("product_name") or "").strip()]
    if len(product_names) < 2:
      continue
    quarter_caps: List[float] = []
    for product_name in product_names:
      year1_product = year1_products.get(product_name) if isinstance(year1_products.get(product_name), dict) else {}
      units_per_period = float_or_none(year1_product.get("units_per_period_capacity")) or 0.0
      periods_per_year = float_or_none(year1_product.get("operating_periods_per_year")) or 0.0
      quarter_cap = units_per_period * (periods_per_year / 4.0) if units_per_period > 0 and periods_per_year > 0 else 0.0
      if quarter_cap > 0:
        quarter_caps.append(quarter_cap)
    capacity_ceiling = max(quarter_caps) if quarter_caps else 0.0
    if capacity_ceiling <= 0:
      continue
    groups.append(
      {
        "lob_name": lob_name,
        "product_names": product_names,
        "capacity_ceiling": capacity_ceiling,
      }
    )
  return groups


def quarter_label(quarter_index: int) -> str:
  return f"Q{int(quarter_index)}"


def float_or_none(value: Any) -> Optional[float]:
  if value in {None, ""}:
    return None
  try:
    return float(value)
  except Exception:
    return None


def has_material_values(values: Sequence[Any]) -> bool:
  for raw_value in values or []:
    number = float_or_none(raw_value)
    if number is not None and abs(number) > 1e-12:
      return True
  return False


def _row_driver_name(item: Dict[str, Any]) -> str:
  return str(item.get("driver") or item.get("label") or "").strip().lower()


def _row_value_kind(item: Dict[str, Any]) -> str:
  return str(item.get("value_kind") or item.get("input_semantics") or "").strip().lower()


def _is_ratio_like_row(item: Dict[str, Any]) -> bool:
  value_kind = _row_value_kind(item)
  label = str(item.get("label") or "").strip().lower()
  return (
    "ratio" in value_kind
    or "percent" in value_kind
    or "% of" in label
    or _row_driver_name(item) in {"utilization"}
  )


def extract_quarter_grid_rows(
  *,
  model_input_json: Dict[str, Any],
  baseline_outputs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  sections = model_input_json.get("sections") if isinstance(model_input_json.get("sections"), dict) else {}
  rows: List[Dict[str, Any]] = []

  for item in sections.get("revenue") or []:
    if not isinstance(item, dict):
      continue
    lever_id = str(item.get("lever_id") or "").strip()
    if not lever_id:
      continue
    values = list(item.get("values") or [])
    if len(values) == QUARTER_COUNT + 1:
      values = values[1:]
    if not has_material_values(values):
      continue
    rows.append(
      {
        "row_id": lever_id,
        "row_type": "lever",
        "section": "revenue",
        "label": str(item.get("label") or lever_id),
        "driver": str(item.get("driver") or item.get("label") or "").strip(),
        "value_kind": str(item.get("value_kind") or "").strip(),
        "input_semantics": str(item.get("input_semantics") or "").strip(),
        "revenue_slot_key": str(item.get("revenue_slot_key") or "").strip(),
        "baseline_values": values[:QUARTER_COUNT],
      }
    )

  for section_name in ("expenses", "balance_sheet"):
    for item in sections.get(section_name) or []:
      if not isinstance(item, dict):
        continue
      if not bool(item.get("controller_write")):
        continue
      lever_id = str(item.get("lever_id") or "").strip()
      if not lever_id:
        continue
      if lever_id in _GRID_EXCLUDED_LEVER_IDS:
        continue
      values = list(item.get("values") or [])
      if len(values) == QUARTER_COUNT + 1:
        values = values[1:]
      rows.append(
        {
          "row_id": lever_id,
          "row_type": "lever",
          "section": section_name,
          "label": str(item.get("label") or lever_id),
          "driver": str(item.get("driver") or item.get("label") or "").strip(),
          "value_kind": str(item.get("value_kind") or "").strip(),
          "input_semantics": str(item.get("input_semantics") or "").strip(),
          "baseline_values": values[:QUARTER_COUNT],
        }
      )

  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  for item in schedules.get("rows") or []:
    if not isinstance(item, dict):
      continue
    if not bool(item.get("controller_write")):
      continue
    lever_id = str(item.get("lever_id") or "").strip()
    if not lever_id:
      continue
    if lever_id in _GRID_EXCLUDED_LEVER_IDS:
      continue
    values = list(item.get("values") or [])
    if len(values) == QUARTER_COUNT + 1:
      values = values[1:]
    rows.append(
      {
        "row_id": lever_id,
        "row_type": "lever",
        "section": "schedules",
        "label": str(item.get("label") or lever_id),
        "driver": str(item.get("driver") or item.get("label") or "").strip(),
        "value_kind": str(item.get("value_kind") or "").strip(),
        "input_semantics": str(item.get("input_semantics") or "").strip(),
        "baseline_values": values[:QUARTER_COUNT],
      }
    )

  for metric in ("Revenue", "EBITDA", "Cash"):
    metric_key = {"Revenue": "revenue", "EBITDA": "ebitda", "Cash": "ending_cash"}[metric]
    rows.append(
      {
        "row_id": metric,
        "row_type": "output",
        "section": "output",
        "label": metric,
        "baseline_values": [row.get(metric_key) for row in baseline_outputs[:QUARTER_COUNT]],
      }
    )

  return rows


def build_real_governor_payload(
  *,
  source_row: Dict[str, Any],
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  parse_json_object,
) -> Dict[str, Any]:
  ops_json = parse_json_object(source_row.get("operating_model_json"))
  target_market_json = parse_json_object(source_row.get("target_market_json"))
  people_json = parse_json_object(source_row.get("people_json"))
  financials_json = parse_json_object(source_row.get("financials_json"))
  financials_year1_json = parse_json_object(source_row.get("financials_year1_json"))
  fulfillment_json = parse_json_object(source_row.get("fulfillment_json"))
  marketing_model_json = parse_json_object(source_row.get("marketing_model_json"))

  return build_governor_payload_from_context(
    ops_json=ops_json,
    target_market_json=target_market_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    fulfillment_json=fulfillment_json,
    marketing_model_json=marketing_model_json,
    model_input_json=model_input_json,
    finmo_json=finmo_json,
    business_facts={},
  )


def _cash_strategy_context(financials_json: Dict[str, Any]) -> Dict[str, Any]:
  financials = financials_json if isinstance(financials_json, dict) else {}
  raw_strategy = str(financials.get("cash_strategy") or "").strip().lower()
  strategy = re.sub(r"[^a-z0-9]+", "_", raw_strategy).strip("_")
  if strategy not in {"preserve_cash", "shareholder_return", "balanced"}:
    if "preserve" in raw_strategy or "conservative" in raw_strategy or "cushion" in raw_strategy:
      strategy = "preserve_cash"
    elif "shareholder" in raw_strategy or "distribution" in raw_strategy or "payout" in raw_strategy or "return capital" in raw_strategy:
      strategy = "shareholder_return"
    elif "reinvest" in raw_strategy or "growth" in raw_strategy or "expansion" in raw_strategy:
      strategy = "balanced"
    elif "balanced" in raw_strategy or "mixed" in raw_strategy:
      strategy = "balanced"
  option_map = {
    "preserve_cash": {
      "value": "preserve_cash",
      "label": "Preserve cash",
      "description": "The client would generally prefer a thicker cash cushion and a more conservative liquidity posture.",
      "capital_allocation_posture": "Favor retaining more liquidity and deploying capital more cautiously unless the operating case clearly justifies faster use of cash.",
      "timing_expectation": "Let cash cushions build earlier and keep deployment pacing more measured across capex, hiring, marketing, and debt choices.",
      "alignment_test": "A preserve-cash plan should not look overly aggressive in capital deployment while still claiming a conservative cash posture.",
      "visual_goal": "The grid and resulting cash path should usually show stronger retained buffers and fewer sharp deployments than balanced or shareholder-return cases.",
    },
    "shareholder_return": {
      "value": "shareholder_return",
      "label": "Shareholder return",
      "description": "The client would generally prefer excess cash to be available for owner or shareholder distributions rather than simply accumulating on the balance sheet.",
      "capital_allocation_posture": "Avoid plans where excess cash piles up indefinitely with no believable use; allow the plan to read like management is willing to extract excess capital when appropriate.",
      "timing_expectation": "Use existing planning choices to avoid unnecessary cash accumulation and support a posture where excess cash is not always retained inside the business.",
      "alignment_test": "A shareholder-return plan should not look like a pure cash-hoarding or growth-at-all-costs plan unless the economics truly leave no better option.",
      "visual_goal": "The grid and resulting cash path should usually look flatter or less accumulation-heavy than preserve-cash or balanced cases when the business is throwing off excess cash.",
    },
    "balanced": {
      "value": "balanced",
      "label": "Balanced",
      "description": "The client wants a mix of cash preservation, debt discipline, and selective capital return rather than pushing to either extreme.",
      "capital_allocation_posture": "Blend healthy retained liquidity with measured debt and equity behavior when the business case supports it.",
      "timing_expectation": "Allow some buildup and some deployment, but keep both the narrative and the grid from leaning too far toward hoarding or aggressive distributions.",
      "alignment_test": "A balanced plan should not collapse into an extreme cash-hoarding or extreme redeployment posture without a strong business reason.",
      "visual_goal": "The grid and resulting cash path should sit between preserve-cash and shareholder-return behavior, with visible but measured capital discipline.",
    },
  }
  selected = dict(option_map.get(strategy) or {})
  if not selected:
    return {}
  selected["planning_role"] = "required planning dimension"
  selected["advisory_only"] = True
  selected["non_override_rule"] = (
    "Do not override core business drivers like revenue realism, operating capacity, or baseline feasibility. "
    "Instead, use the selected cash strategy to shape capital timing and allocation decisions within the existing planning system."
  )
  selected["required_alignment_dimensions"] = [
    "capex timing",
    "hiring pace",
    "marketing intensity",
    "debt behavior",
    "liquidity posture",
  ]
  selected["narrative_requirement"] = (
    "Explicitly explain how the selected cash strategy is reflected in the quarter plan so the narrative and the grid tell the same capital allocation story."
  )
  return selected


def _parse_date(value: Any) -> Optional[date]:
  if value is None:
    return None
  if isinstance(value, datetime):
    return value.date()
  if isinstance(value, date):
    return value
  raw = str(value).strip()
  if not raw:
    return None
  try:
    return datetime.fromisoformat(raw).date()
  except ValueError:
    pass
  for fmt in ("%m/%d/%Y", "%m-%d-%Y"):
    try:
      return datetime.strptime(raw, fmt).date()
    except ValueError:
      continue
  return None


def _whole_months_between(start_date: date, end_date: date) -> int:
  months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
  if end_date.day < start_date.day:
    months -= 1
  return int(months)


def _stage_family(stage: Any) -> str:
  normalized = str(stage or "").strip().lower().replace("_", "-")
  if normalized in {"pre-revenue", "pre revenue", "startup", "start-up", "new", "launch"}:
    return "startup"
  if normalized in {"early", "early-stage", "early stage", "growth"}:
    return "early"
  return "operational"


def _stage_governance_context(
  *,
  ops_json: Dict[str, Any],
  business_facts: Optional[Dict[str, Any]],
  planning_mode: str,
  stage_ramp_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  facts = business_facts if isinstance(business_facts, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  start_date = (
    _parse_date(facts.get("start_date"))
    or _parse_date(facts.get("business_start_date"))
    or _parse_date(ops.get("business_start_date"))
    or _parse_date(ops.get("start_date"))
  )
  today = datetime.utcnow().date()
  explicit_stage = str(ops.get("business_stage") or facts.get("business_stage") or "").strip().lower()
  if explicit_stage:
    stage = explicit_stage
  elif start_date is not None and start_date > today:
    stage = "pre-revenue"
  elif start_date is not None and (today - start_date).days <= 365:
    stage = "early-stage"
  else:
    stage = "operating"
  age_months = _whole_months_between(start_date, today) if start_date is not None else None
  if not isinstance(stage_ramp_contract, dict) or not stage_ramp_contract:
    raise RuntimeError(
      "quarter_grid_missing_gpt_stage_ramp_contract: GPT stage ramp contract is required before quarter-grid planning."
    )
  ramp_contract = copy.deepcopy(stage_ramp_contract)
  expected_stage_family = _stage_family(stage)
  contract_stage_family = str(ramp_contract.get("stage_family") or "").strip().lower()
  if contract_stage_family != expected_stage_family:
    raise RuntimeError(
      "quarter_grid_stage_ramp_contract_mismatch: GPT stage ramp contract does not match resolved business stage. "
      + json.dumps(
        {
          "business_stage": stage,
          "expected_stage_family": expected_stage_family,
          "contract_stage_family": contract_stage_family or None,
          "planning_mode": str(planning_mode or "").strip().lower(),
        },
        ensure_ascii=False,
      )
    )
  policy = stage_planning_ramp_policy(
    stage_family=expected_stage_family,
    planning_mode=planning_mode,
    planning_mode_reason=(ramp_contract.get("stage_profitability_policy") or {}).get("planning_mode_reason")
    if isinstance(ramp_contract.get("stage_profitability_policy"), dict)
    else "",
    business_stage=stage,
  )
  context = {
    "contract_version": "quarter_grid_lifecycle_governance_v1",
    "business_stage": stage,
    "stage_family": expected_stage_family,
    "business_start_date": start_date.isoformat() if start_date is not None else None,
    "business_age_months_at_run": age_months,
    "planning_mode": policy.get("planning_mode"),
    "binding": True,
    "stage_is_reality_limiter": True,
    "planning_mode_is_operating_posture": True,
    "planning_mode_stage_ramp_consistency_required": True,
    "fail_fast_if_ignored": True,
    "stage_planning_ramp_policy": policy,
    "stage_ramp_contract": ramp_contract,
  }
  context["stage_rules"] = copy.deepcopy(policy.get("stage_rules") or [])
  if isinstance(policy.get("early_revenue_share_ceiling_of_late_run_rate"), dict):
    context["early_revenue_share_ceiling_of_late_run_rate"] = copy.deepcopy(policy["early_revenue_share_ceiling_of_late_run_rate"])
  return context


def _stage_governance_prompt_block(governor_payload: Dict[str, Any]) -> str:
  context = governor_payload.get("stage_governance_context") if isinstance(governor_payload, dict) else None
  if not isinstance(context, dict) or not context:
    return ""
  stage = str(context.get("business_stage") or "").strip().lower()
  rules = context.get("stage_rules") if isinstance(context.get("stage_rules"), list) else []
  lines = [
    "Business-stage governance is binding:",
    "- read `stage_governance_context` as a hard operating contract, not narrative color",
    "- planning mode and business stage must shape the grid before any profitability goal",
    "- do not create a forecast that violates the lifecycle stage just to make outputs look clean",
    "- apply `stage_ramp_contract` to every adjacent quarter pair Q1->Q2 through Q19->Q20",
    "- do not allow unchecked growth; spikes are only valid inside the contract's window and support rules",
    "- use stage_ramp_contract cost maturity caps for COGS, Marketing, R&D, G&A, and Lease before trying to make profit look clean",
    "- use net_income_margin_floor as a maturity guardrail, not as permission to fake instant mature profitability",
  ]
  if str(context.get("stage_family") or "").strip().lower() == "startup":
    lines.extend(
      [
        "- pre-revenue businesses must not begin Q1 at mature run-rate revenue, utilization, capacity deployment, staffing support, or profitability",
        "- use a launch/ramp curve in Q1-Q4 unless explicit operating facts prove an already-contracted backlog",
        "- revenue may become strong later, but Q1 must look like a launch period rather than an established mature business",
        "- keep revenue growth paced enough that the OEWS/FTE-derived Payroll row can staff it under the stage_ramp_contract",
      ]
    )
  elif str(context.get("stage_family") or "").strip().lower() == "early":
    lines.extend(
      [
        "- early-stage businesses should show absorption and ramp behavior in Q1-Q4",
        "- do not jump instantly to mature run-rate unless the facts prove existing operating traction",
      ]
    )
  for rule in rules:
    text = str(rule or "").strip()
    if text:
      lines.append(f"- {text}")
  lines.append("Compact stage governance payload:")
  lines.append(json.dumps(_compact_stage_governance_context_for_prompt(context), ensure_ascii=False))
  return "\n".join(lines) + "\n\n"


def _compact_stage_ramp_contract_for_prompt(contract: Dict[str, Any]) -> Dict[str, Any]:
  payload = contract if isinstance(contract, dict) else {}
  grid_rows = [
    {
      "q": int(row.get("quarter_index") or 0),
      "rev_target": row.get("revenue_qoq_target"),
      "rev_max": row.get("revenue_qoq_max"),
      "rev_spike": row.get("revenue_qoq_spike_allowed"),
      "rev_spike_max": row.get("revenue_qoq_spike_max"),
      "fte_max": row.get("fte_qoq_max"),
      "util_cap": row.get("utilization_cap"),
      "cogs_target": row.get("cogs_percent_of_revenue_target"),
      "cogs_max": row.get("cogs_percent_of_revenue_max"),
      "marketing_max": row.get("marketing_percent_of_revenue_max"),
      "rd_max": row.get("rd_percent_of_revenue_max"),
      "g_and_a_max": row.get("g_and_a_percent_of_revenue_max"),
      "lease_max": row.get("lease_percent_of_revenue_max"),
      "ni_margin_floor": row.get("net_income_margin_floor"),
      "profitability_posture": row.get("profitability_posture"),
    }
    for row in (payload.get("quarter_ramp_grid") or [])
    if isinstance(row, dict) and int(row.get("quarter_index") or 0) >= 1
  ]
  return {
    "contract_version": payload.get("contract_version"),
    "stage_family": payload.get("stage_family"),
    "quarter_grid_is_binding": bool(payload.get("quarter_grid_is_binding") or payload.get("composite_revenue_ramp_is_binding")),
    "revenue_qoq_growth_target_max": payload.get("revenue_qoq_growth_target_max"),
    "revenue_qoq_max_spike": payload.get("revenue_qoq_max_spike"),
    "fte_qoq_max": payload.get("fte_qoq_max"),
    "fte_qoq_max_spike": payload.get("fte_qoq_max_spike"),
    "utilization_high_watermark": payload.get("utilization_high_watermark"),
    "cost_maturity_caps": copy.deepcopy(payload.get("cost_maturity_caps") or {}),
    "profitability_floor_by_quarter": copy.deepcopy(payload.get("profitability_floor_by_quarter") or {}),
    "cost_maturity_ramp_is_binding": bool(payload.get("cost_maturity_ramp_is_binding")),
    "profitability_maturity_floor_is_binding": bool(payload.get("profitability_maturity_floor_is_binding")),
    "max_spike_count": payload.get("max_spike_count"),
    "quarter_ramp_grid": grid_rows,
    "composite_revenue_formula": payload.get("composite_revenue_formula"),
  }


def _compact_stage_governance_context_for_prompt(context: Dict[str, Any]) -> Dict[str, Any]:
  payload = context if isinstance(context, dict) else {}
  ramp_contract = payload.get("stage_ramp_contract") if isinstance(payload.get("stage_ramp_contract"), dict) else {}
  return {
    "contract_version": payload.get("contract_version"),
    "business_stage": payload.get("business_stage"),
    "stage_family": payload.get("stage_family"),
    "business_age_months_at_run": payload.get("business_age_months_at_run"),
    "planning_mode": payload.get("planning_mode"),
    "binding": bool(payload.get("binding")),
    "stage_is_reality_limiter": bool(payload.get("stage_is_reality_limiter")),
    "fail_fast_if_ignored": bool(payload.get("fail_fast_if_ignored")),
    "stage_ramp_contract": _compact_stage_ramp_contract_for_prompt(ramp_contract),
    "stage_rules": [
      str(item).strip()
      for item in (payload.get("stage_rules") or [])
      if str(item).strip()
    ][:8],
    "early_revenue_share_ceiling_of_late_run_rate": copy.deepcopy(payload.get("early_revenue_share_ceiling_of_late_run_rate") or {}),
  }


def _compact_governor_payload_for_prompt(governor_payload: Dict[str, Any]) -> Dict[str, Any]:
  payload = governor_payload if isinstance(governor_payload, dict) else {}
  compact: Dict[str, Any] = {}
  if isinstance(payload.get("stage_governance_context"), dict):
    compact["stage_governance_context"] = _compact_stage_governance_context_for_prompt(payload["stage_governance_context"])
  for key in ("planning_mode", "planning_mode_reason", "selected_cash_strategy"):
    if key in payload:
      compact[key] = payload.get(key)
  cash_strategy_context = payload.get("cash_strategy_context")
  if isinstance(cash_strategy_context, dict):
    compact["cash_strategy_context"] = {
      key: cash_strategy_context.get(key)
      for key in ("selected_cash_strategy", "strategy_policy", "required_cash_buffer_policy")
      if key in cash_strategy_context
    }
  return compact


def _quarter_grid_stage_family(governor_payload: Dict[str, Any]) -> str:
  context = governor_payload.get("stage_governance_context") if isinstance(governor_payload, dict) else {}
  return str((context or {}).get("stage_family") or "operational").strip().lower()


def _quarter_grid_stage_growth_bounds(governor_payload: Dict[str, Any]) -> Dict[str, float]:
  context = governor_payload.get("stage_governance_context") if isinstance(governor_payload, dict) else {}
  contract = (context or {}).get("stage_ramp_contract") if isinstance((context or {}).get("stage_ramp_contract"), dict) else {}
  return {
    "min": float(contract.get("revenue_qoq_growth_target_min") or 0.05),
    "max": float(contract.get("revenue_qoq_growth_target_max") or 0.20),
    "default": float(contract.get("revenue_qoq_default") or 0.10),
  }


def _quarter_grid_stage_maturity_row(governor_payload: Dict[str, Any], quarter_index: int) -> Dict[str, Any]:
  context = governor_payload.get("stage_governance_context") if isinstance(governor_payload, dict) else {}
  contract = (context or {}).get("stage_ramp_contract") if isinstance((context or {}).get("stage_ramp_contract"), dict) else {}
  target_quarter = int(quarter_index or 0)
  for row in (contract.get("quarter_ramp_grid") or []):
    if not isinstance(row, dict):
      continue
    if int(float_or_none(row.get("quarter_index")) or 0) == target_quarter:
      return row
  return {}


def _maturity_cap_for_expense_row(label: str, maturity_row: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
  lowered = str(label or "").strip().lower()
  if not isinstance(maturity_row, dict) or not maturity_row:
    return None, None
  if "cost of goods" in lowered or "cogs" in lowered:
    return float_or_none(maturity_row.get("cogs_percent_of_revenue_max")), "stage_maturity_cogs_percent_cap"
  if "marketing" in lowered:
    return float_or_none(maturity_row.get("marketing_percent_of_revenue_max")), "stage_maturity_marketing_percent_cap"
  if "research" in lowered or "r&d" in lowered or "rd " in f"{lowered} ":
    return float_or_none(maturity_row.get("rd_percent_of_revenue_max")), "stage_maturity_rd_percent_cap"
  if "general" in lowered or "administrative" in lowered or "g&a" in lowered:
    return float_or_none(maturity_row.get("g_and_a_percent_of_revenue_max")), "stage_maturity_g_and_a_percent_cap"
  if "lease" in lowered or "rent" in lowered:
    return float_or_none(maturity_row.get("lease_percent_of_revenue_max")), "stage_maturity_lease_percent_cap"
  return None, None


def _bounded(value: float, lower: float, upper: float) -> float:
  return max(float(lower), min(float(upper), float(value)))


def _quarter_grid_cell_envelopes_for_row(
  row: Dict[str, Any],
  *,
  governor_payload: Dict[str, Any],
) -> List[Dict[str, Any]]:
  if str(row.get("row_type") or "").strip().lower() != "lever":
    return []
  section = str(row.get("section") or "").strip().lower()
  driver = _row_driver_name(row)
  label = str(row.get("label") or row.get("row_id") or "").strip().lower()
  baseline_values = [
    float_or_none(value) if float_or_none(value) is not None else 0.0
    for value in (row.get("baseline_values") or [])
  ]
  padded = [float(value or 0.0) for value in (baseline_values + [0.0] * QUARTER_COUNT)[:QUARTER_COUNT]]
  stage_family = _quarter_grid_stage_family(governor_payload)
  growth = _quarter_grid_stage_growth_bounds(governor_payload)
  stage_contract = (
    ((governor_payload.get("stage_governance_context") or {}).get("stage_ramp_contract") or {})
    if isinstance(governor_payload, dict) and isinstance(governor_payload.get("stage_governance_context"), dict)
    else {}
  )
  envelopes: List[Dict[str, Any]] = []
  previous_min: Optional[float] = None
  previous_max: Optional[float] = None
  for idx, baseline in enumerate(padded, start=1):
    base = max(0.0, float(baseline or 0.0))
    min_value = 0.0
    max_value = max(base * 2.0, 1.0)
    reason = "generic_nonnegative_driver_bound"
    if _is_ratio_like_row(row):
      min_value = 0.0
      max_value = 1.0
      reason = "ratio_like_driver_bound"
    if driver == "utilization":
      stage_caps_raw = (
        stage_contract.get("utilization_launch_caps_by_quarter")
        if isinstance(stage_contract.get("utilization_launch_caps_by_quarter"), dict)
        else {}
      )
      stage_caps = {
        int(float(key)): float(value)
        for key, value in stage_caps_raw.items()
        if int(float(key or 0)) >= 1
      }
      if stage_caps:
        cap_value = stage_caps.get(idx)
        if cap_value is not None:
          min_value = float(cap_value)
          max_value = float(cap_value)
        else:
          max_value = 0.85
      else:
        max_value = 0.85
      reason = f"structural_utilization_{stage_family}_lifecycle_bound"
    elif driver == "capacity":
      if stage_family == "startup":
        min_value = max(0.0, base)
        max_value = max(0.0, base)
        reason = "startup_structural_capacity_fixed_until_absorption_bound"
      elif previous_min is None:
        min_value = max(0.0, base * 0.90)
        max_value = max(base * 1.10, base + 1.0)
        reason = "structural_capacity_non_decreasing_bound"
      else:
        min_value = max(0.0, previous_min)
        capacity_growth_ceiling = 1.05 if stage_family == "early" else 1.03
        max_value = max(previous_max or 0.0, (previous_max or 0.0) * capacity_growth_ceiling, base)
        reason = "structural_capacity_stage_growth_bound"
    elif driver == "unit price":
      anchor = max(base, padded[0], 1.0)
      if previous_min is None:
        min_value = max(0.0, anchor * 0.98)
        max_value = anchor * 1.02
      else:
        min_value = max(0.0, (previous_min or anchor) * 0.99)
        max_value = (previous_max or anchor) * 1.02
      reason = "unit_price_lifecycle_pricing_bound"
    elif section == "expenses" and _is_ratio_like_row(row):
      if "cost of goods" in label:
        min_value, max_value = 0.20, 0.85
        reason = "cogs_percent_operating_bound"
      elif "marketing" in label:
        min_value, max_value = 0.0, 0.35
        reason = "marketing_percent_operating_bound"
      elif "research" in label:
        min_value, max_value = 0.0, 0.35
        reason = "research_percent_operating_bound"
      elif "general" in label:
        min_value, max_value = 0.0, 0.40
        reason = "g_and_a_percent_operating_bound"
      else:
        min_value, max_value = 0.0, 0.60
        reason = "expense_percent_operating_bound"
      maturity_cap, maturity_reason = _maturity_cap_for_expense_row(
        label,
        _quarter_grid_stage_maturity_row(governor_payload, idx),
      )
      if maturity_cap is not None:
        max_value = min(float(max_value), max(float(min_value), float(maturity_cap)))
        reason = str(maturity_reason or reason)
    elif section == "balance_sheet" and _is_ratio_like_row(row):
      min_value, max_value = 0.0, 1.0
      reason = "balance_sheet_ratio_bound"
    elif section == "schedules":
      if "debt issuance" in label or "owner" in label or "equity" in label:
        max_value = max(base * 4.0, 1_000_000.0)
        reason = "capital_flow_driver_bound"
      elif "debt repayment" in label:
        max_value = max(base * 4.0, 1_000_000.0)
        reason = "debt_repayment_driver_bound"
      else:
        max_value = max(base * 3.0, 1000.0)
        reason = "schedule_driver_bound"
    if section == "revenue" and driver in {"capacity", "unit price", "utilization"} and idx > 1:
      # Do not let the grid silently freeze all revenue drivers forever. This is
      # an input-envelope rule, not a post-hoc issue repair.
      if driver == "capacity":
        min_value = max(min_value, previous_min or 0.0)
      elif driver == "unit price":
        min_value = max(min_value, previous_min or min_value)
      elif driver == "utilization":
        min_value = max(min_value, min(0.85, (previous_min or 0.0)))
    if driver == "unit price":
      min_value = math.floor(float(min_value) * 100.0) / 100.0
      max_value = math.ceil(float(max_value) * 100.0) / 100.0
    else:
      min_value = round(float(min_value), 6)
      max_value = round(float(max_value), 6)
    max_value = round(max(float(max_value), float(min_value)), 6)
    envelopes.append(
      {
        "quarter_index": idx,
        "min_value": min_value,
        "max_value": max_value,
        "basis": reason,
      }
    )
    previous_min = min_value
    previous_max = max_value
  return envelopes


def attach_quarter_grid_cell_envelopes(
  *,
  grid_rows: List[Dict[str, Any]],
  governor_payload: Dict[str, Any],
) -> List[Dict[str, Any]]:
  next_rows: List[Dict[str, Any]] = []
  for row in grid_rows:
    copied = json.loads(json.dumps(row if isinstance(row, dict) else {}))
    copied["cell_envelopes"] = _quarter_grid_cell_envelopes_for_row(
      copied,
      governor_payload=governor_payload,
    )
    if copied.get("cell_envelopes"):
      copied["grid_contract"] = (
        "Every returned quarter value for this row must be inside the matching "
        "cell_envelopes min_value/max_value. Python will reject values outside the grid."
      )
    next_rows.append(copied)
  return next_rows


def build_governor_payload_from_context(
  *,
  ops_json: Dict[str, Any],
  target_market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  fulfillment_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  business_facts: Optional[Dict[str, Any]] = None,
  planning_mode: str = "",
  stage_ramp_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  del target_market_json, people_json, fulfillment_json, marketing_model_json
  baseline_summary = _baseline_summary_from_finmo_json(finmo_json) or _build_baseline_financial_summary(
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
  )
  cash_strategy_context = _cash_strategy_context(financials_json)
  stage_governance_context = _stage_governance_context(
    ops_json=ops_json,
    business_facts=business_facts,
    planning_mode=planning_mode,
    stage_ramp_contract=copy.deepcopy(stage_ramp_contract)
    if isinstance(stage_ramp_contract, dict)
    else None,
  )
  return {
    "baseline_summary": _sanitize_canonical_live_payload(baseline_summary or {}),
    "fixed_facts": {
      "model_input_json": _sanitize_canonical_live_payload(model_input_json or {}),
      "finmo_json": _sanitize_canonical_live_payload(finmo_json or {}),
    },
    "model_input_view": _sanitize_canonical_live_payload(model_input_json or {}),
    "finmo_view": _sanitize_canonical_live_payload(finmo_json or {}),
    "ops_lob_product_summary": _sanitize_canonical_live_payload(_ops_lob_product_summary(ops_json or {})),
    "shared_capacity_guidance": {
      "apply_within_lob": True,
      "rules": [
        "When products inside the same LOB share one operating engine, treat that LOB's capacity as one conserved 100% pool.",
        "Do not assume every product inside the same LOB has full standalone service capacity.",
        "Split that shared LOB capacity realistically across the products rather than giving each product its own independent full-capacity envelope.",
        "Only treat product capacities as fully independent when the business context clearly supports separate operating capacity.",
      ],
    },
    "cash_strategy_context": _sanitize_canonical_live_payload(cash_strategy_context),
    "stage_governance_context": _sanitize_canonical_live_payload(stage_governance_context),
    "viability_mode": True,
  }


def generate_live_quarter_grid_plan(
  *,
  business_name: str,
  planning_mode: str,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  ops_json: Dict[str, Any],
  target_market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  fulfillment_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  realism_memo_json: Optional[Dict[str, Any]] = None,
  business_facts: Optional[Dict[str, Any]] = None,
  stage_ramp_contract: Optional[Dict[str, Any]] = None,
  batch_size: int = 12,
  use_real_strategy_prompt: bool = True,
) -> Dict[str, Any]:
  normalized_mode = resolve_planning_mode(planning_mode)
  prompt_file = planning_mode_prompt_file(normalized_mode)
  baseline_inputs = FinancialModelInputs.from_model_input_json(model_input_json)
  baseline_outputs = calculate_finmo_model(baseline_inputs).quarter_rows()
  grid_rows = extract_quarter_grid_rows(
    model_input_json=model_input_json,
    baseline_outputs=baseline_outputs,
  )
  governor_payload = build_governor_payload_from_context(
    ops_json=ops_json,
    target_market_json=target_market_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    fulfillment_json=fulfillment_json,
    marketing_model_json=marketing_model_json,
    model_input_json=model_input_json,
    finmo_json=finmo_json,
    business_facts=business_facts or {},
    planning_mode=normalized_mode,
    stage_ramp_contract=copy.deepcopy(stage_ramp_contract)
    if isinstance(stage_ramp_contract, dict)
    else None,
  )
  grid_rows = attach_quarter_grid_cell_envelopes(
    grid_rows=grid_rows,
    governor_payload=governor_payload,
  )
  source_row = {
    "business_name": str(business_name or "").strip(),
    "realism_memo_json": normalize_realism_memo_payload(realism_memo_json),
  }
  response_rows: List[Dict[str, Any]] = []
  batch_summaries: List[str] = []
  batch_validation_summaries: List[Dict[str, Any]] = []
  batches = chunk_quarter_grid_rows(grid_rows, batch_size)
  started = time.perf_counter()
  for batch_offset, batch_rows in enumerate(batches, start=1):
    prompt = build_quarter_grid_prompt(
      source_row=source_row,
      grid_rows=batch_rows,
      governor_payload=governor_payload,
      batch_index=batch_offset,
      batch_count=len(batches),
      planning_mode=normalized_mode,
    )
    batch_response = call_quarter_grid_openai(
      prompt,
      allowed_row_ids=[str(item.get("row_id") or "") for item in batch_rows],
      use_real_strategy_prompt=bool(use_real_strategy_prompt),
      planning_mode=normalized_mode,
      realism_memo_present=bool((source_row.get("realism_memo_json") or {}).get("issues")),
    )
    raw_batch_validation = validate_quarter_grid_response(
      requested_rows=batch_rows,
      response_json=batch_response if isinstance(batch_response, dict) else {},
      governor_payload=governor_payload,
    )
    repaired_batch_response = repair_quarter_grid_response(
      requested_rows=batch_rows,
      response_json=batch_response if isinstance(batch_response, dict) else {},
    )
    repaired_batch_validation = validate_quarter_grid_response(
      requested_rows=batch_rows,
      response_json=repaired_batch_response,
      governor_payload=governor_payload,
    )
    for _repair_attempt in range(0, 3):
      if not (
        repaired_batch_validation.get("out_of_envelope_rows")
        or repaired_batch_validation.get("composite_revenue_ramp_violations")
      ):
        break
      repair_prompt = _quarter_grid_contract_repair_prompt(
        original_prompt=prompt,
        validation=repaired_batch_validation,
        invalid_response=repaired_batch_response,
      )
      batch_response = call_quarter_grid_openai(
        repair_prompt,
        allowed_row_ids=[str(item.get("row_id") or "") for item in batch_rows],
        use_real_strategy_prompt=bool(use_real_strategy_prompt),
        planning_mode=normalized_mode,
        realism_memo_present=bool((source_row.get("realism_memo_json") or {}).get("issues")),
      )
      raw_batch_validation = validate_quarter_grid_response(
        requested_rows=batch_rows,
        response_json=batch_response if isinstance(batch_response, dict) else {},
        governor_payload=governor_payload,
      )
      repaired_batch_response = repair_quarter_grid_response(
        requested_rows=batch_rows,
        response_json=batch_response if isinstance(batch_response, dict) else {},
      )
      repaired_batch_validation = validate_quarter_grid_response(
        requested_rows=batch_rows,
        response_json=repaired_batch_response,
        governor_payload=governor_payload,
      )
    if repaired_batch_validation.get("out_of_envelope_rows"):
      raise RuntimeError(
        "quarter_grid_contract_out_of_envelope: "
        + json.dumps(
          {
            "batch_index": batch_offset,
            "out_of_envelope_rows": repaired_batch_validation.get("out_of_envelope_rows"),
          },
          ensure_ascii=False,
        )
      )
    if repaired_batch_validation.get("composite_revenue_ramp_violations"):
      raise RuntimeError(
        "quarter_grid_contract_composite_revenue_ramp_failed: "
        + json.dumps(
          {
            "batch_index": batch_offset,
            "violations": repaired_batch_validation.get("composite_revenue_ramp_violations"),
          },
          ensure_ascii=False,
        )
      )
    response_rows.extend(repaired_batch_response.get("rows") if isinstance(repaired_batch_response.get("rows"), list) else [])
    batch_summaries.append(str(batch_response.get("summary") or f"Batch {batch_offset} completed."))
    batch_validation_summaries.append(
      {
        "batch_index": batch_offset,
        "raw_validation": raw_batch_validation,
        "repaired_validation": repaired_batch_validation,
        "repair_metadata": repaired_batch_response.get("repair_metadata") if isinstance(repaired_batch_response.get("repair_metadata"), dict) else {},
      }
    )
  runtime_seconds = round(time.perf_counter() - started, 3)
  raw_response_json = {
    "summary": f"Completed {len(batches)} quarter-grid probe batches.",
    "rows": response_rows,
  }
  raw_validation = validate_quarter_grid_response(
    requested_rows=grid_rows,
    response_json=raw_response_json,
    governor_payload=governor_payload,
  )
  response_json = repair_quarter_grid_response(
    requested_rows=grid_rows,
    response_json=raw_response_json,
  )
  validation = validate_quarter_grid_response(
    requested_rows=grid_rows,
    response_json=response_json,
    governor_payload=governor_payload,
  )
  if validation.get("out_of_envelope_rows"):
    raise RuntimeError(
      "quarter_grid_contract_out_of_envelope: "
      + json.dumps(
        {"out_of_envelope_rows": validation.get("out_of_envelope_rows")},
        ensure_ascii=False,
      )
    )
  if validation.get("composite_revenue_ramp_violations"):
    raise RuntimeError(
      "quarter_grid_contract_composite_revenue_ramp_failed: "
      + json.dumps(
        {"violations": validation.get("composite_revenue_ramp_violations")},
        ensure_ascii=False,
      )
    )
  metadata = {
    "planning_mode": normalized_mode,
    "prompt_file": prompt_file,
    "runtime_seconds": runtime_seconds,
    "requested_row_count": validation.get("requested_row_count"),
    "returned_row_count": validation.get("returned_row_count"),
    "batch_count": len(batches),
    "batch_size": int(batch_size or 0),
    "batch_summaries": batch_summaries,
    "batch_validation_summaries": batch_validation_summaries,
    "raw_validation": raw_validation,
    "validation": {
      "missing_rows": list(validation.get("missing_rows") or []),
      "extra_rows": list(validation.get("extra_rows") or []),
      "duplicate_rows": list(validation.get("duplicate_rows") or []),
      "malformed_rows": list(validation.get("malformed_rows") or []),
      "flat_rows": list(validation.get("flat_rows") or []),
      "composite_revenue_ramp_violations": list(validation.get("composite_revenue_ramp_violations") or []),
    },
    "repair_metadata": response_json.get("repair_metadata") if isinstance(response_json.get("repair_metadata"), dict) else {},
    "response_summary": str(response_json.get("summary") or "").strip(),
    "response_json": response_json,
  }
  return {
    "planning_mode": normalized_mode,
    "prompt_file": prompt_file,
    "grid_json": response_json,
    "grid_rows": grid_rows,
    "validation": validation,
    "metadata": metadata,
    "gpt_narrative": " ".join(item for item in batch_summaries if str(item or "").strip()).strip() or str(response_json.get("summary") or "").strip(),
  }


def _iter_controller_write_rows(model_input_json: Dict[str, Any]) -> List[Dict[str, Any]]:
  sections = model_input_json.get("sections") if isinstance(model_input_json.get("sections"), dict) else {}
  rows: List[Dict[str, Any]] = []
  for section_name in ("revenue", "expenses", "balance_sheet"):
    for row in sections.get(section_name) or []:
      lever_id = str((row or {}).get("lever_id") or "").strip()
      if isinstance(row, dict) and bool(row.get("controller_write", True)) and lever_id not in _GRID_EXCLUDED_LEVER_IDS:
        rows.append(row)
  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  for row in schedules.get("rows") or []:
    lever_id = str((row or {}).get("lever_id") or "").strip()
    if isinstance(row, dict) and bool(row.get("controller_write", True)) and lever_id not in _GRID_EXCLUDED_LEVER_IDS:
      rows.append(row)
  return rows


def _lever_row_map(model_input_json: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
  return {
    str(row.get("lever_id") or "").strip(): row
    for row in _iter_controller_write_rows(model_input_json)
    if str(row.get("lever_id") or "").strip()
  }


def _quarter_values_by_row(row: Dict[str, Any]) -> Dict[int, float]:
  values: Dict[int, float] = {}
  for item in (row.get("quarter_values") or []):
    if not isinstance(item, dict):
      continue
    quarter_index = int(item.get("quarter_index") or 0)
    if quarter_index < 1 or quarter_index > QUARTER_COUNT:
      continue
    value = float_or_none(item.get("value"))
    if value is None:
      continue
    values[quarter_index] = float(value)
  return values


def apply_exact_lever_updates_to_model_input(
  *,
  model_input_json: Dict[str, Any],
  exact_updates: List[Dict[str, Any]],
) -> Dict[str, Any]:
  try:
    from client_intake_and_finmo.finmo_bridge import apply_derived_driver_policies_to_model_input  # type: ignore
  except Exception:
    from finmo_bridge import apply_derived_driver_policies_to_model_input  # type: ignore
  next_model_input = json.loads(json.dumps(model_input_json if isinstance(model_input_json, dict) else {}))
  lever_rows = _lever_row_map(next_model_input)
  nonnegative_only_levers = {
    "balance_sheet::Distributions",
    "balance_sheet::Owner's Capital",
    "schedules::Debt Issuance (New Borrowing)",
    "schedules::Debt Repayment (Scheduled)",
    "balance_sheet::Short Term Debt (% of LTD)",
  }
  stock_level_levers = {
    "balance_sheet::Owner's Capital",
    "balance_sheet::Other Equity",
  }
  explicit_quarters_by_lever: Dict[str, set[int]] = {}
  for update in exact_updates:
    if not isinstance(update, dict):
      continue
    lever_id = str(update.get("lever_id") or "").strip()
    quarter_index = int(update.get("quarter_index") or 0)
    value = float_or_none(update.get("exact_value"))
    row = lever_rows.get(lever_id)
    if not lever_id or row is None or value is None or quarter_index < 1 or quarter_index > QUARTER_COUNT:
      continue
    if lever_id in nonnegative_only_levers:
      value = max(0.0, float(value))
    values = list(row.get("values") or [])
    has_stub = len(values) >= QUARTER_COUNT + 1
    target_length = QUARTER_COUNT + 1 if has_stub else QUARTER_COUNT
    if len(values) < target_length:
      values.extend([0.0 for _ in range(target_length - len(values))])
    row["values"] = values[:target_length]
    row["values"][quarter_index if has_stub else quarter_index - 1] = round(float(value), 6)
    explicit_quarters_by_lever.setdefault(lever_id, set()).add(quarter_index)
  for lever_id in stock_level_levers:
    row = lever_rows.get(lever_id)
    if row is None:
      continue
    explicit_quarters = sorted(explicit_quarters_by_lever.get(lever_id) or [])
    if not explicit_quarters:
      continue
    values = list(row.get("values") or [])
    has_stub = len(values) >= QUARTER_COUNT + 1
    target_length = QUARTER_COUNT + 1 if has_stub else QUARTER_COUNT
    if len(values) < target_length:
      values.extend([0.0 for _ in range(target_length - len(values))])
    row["values"] = values[:target_length]
    carryforward_active = False
    previous_value = None
    for quarter_index in range(1, QUARTER_COUNT + 1):
      value_idx = quarter_index if has_stub else quarter_index - 1
      current_value = float_or_none(row["values"][value_idx])
      if current_value is None:
        current_value = 0.0
      if quarter_index in explicit_quarters:
        carryforward_active = True
        if lever_id == "balance_sheet::Owner's Capital" and previous_value is not None:
          current_value = max(float(previous_value), float(current_value))
          row["values"][value_idx] = round(float(current_value), 6)
      elif carryforward_active and previous_value is not None:
        current_value = float(previous_value)
        row["values"][value_idx] = round(float(current_value), 6)
      previous_value = float(current_value)
  return apply_derived_driver_policies_to_model_input(next_model_input)


def apply_live_quarter_grid_plan(
  *,
  baseline_model_input_json: Dict[str, Any],
  grid_json: Dict[str, Any],
) -> Dict[str, Any]:
  try:
    from client_intake_and_finmo.numeric_execution import execute_numeric_plan  # type: ignore
  except Exception:
    from numeric_execution import execute_numeric_plan  # type: ignore
  exact_updates: List[Dict[str, Any]] = []
  for row in (grid_json.get("rows") or []):
    if not isinstance(row, dict):
      continue
    if str(row.get("row_type") or "").strip().lower() != "lever":
      continue
    lever_id = str(row.get("row_id") or "").strip()
    if not lever_id:
      continue
    for quarter_index, value in _quarter_values_by_row(row).items():
      exact_updates.append(
        {
          "lever_id": lever_id,
          "quarter_index": quarter_index,
          "exact_value": float(value),
        }
      )
  execution_result = execute_numeric_plan(
    model_input_json=baseline_model_input_json if isinstance(baseline_model_input_json, dict) else {},
    exact_updates=exact_updates,
    executor_context={"source": "apply_live_quarter_grid_plan"},
  )
  applied_model_input_json = execution_result.get("updated_model_input_json") or {}
  applied_finmo_json = execution_result.get("updated_finmo_json") or {}
  return {
    "application_summary": {
      "success": True,
      "applied_lever_update_count": len(exact_updates),
      "applied_lever_count": len({str(item.get('lever_id') or '').strip() for item in exact_updates if str(item.get('lever_id') or '').strip()}),
    },
    "applied_updates": exact_updates,
    "numeric_execution_boundary": execution_result.get("numeric_execution_boundary") or {},
    "numeric_executor": execution_result.get("numeric_executor"),
    "numeric_execution_plan": execution_result.get("numeric_execution_plan") or {},
    "numeric_execution_attempts": execution_result.get("numeric_execution_attempts") or [],
    "numeric_execution_outcome": execution_result.get("numeric_execution_outcome") or {},
    "applied_model_input_json": applied_model_input_json,
    "applied_finmo_json": applied_finmo_json,
  }


def grid_markdown(rows: List[Dict[str, Any]]) -> str:
  header = ["Variable", *[quarter_label(index) for index in range(1, QUARTER_COUNT + 1)]]
  lines = [
    "| " + " | ".join(header) + " |",
    "| " + " | ".join(["---"] * len(header)) + " |",
  ]
  for item in rows:
    values = []
    for raw_value in item.get("baseline_values") or []:
      number = float_or_none(raw_value)
      values.append("" if number is None else f"{number:.4f}")
    padded = values + [""] * (QUARTER_COUNT - len(values))
    lines.append("| " + " | ".join([str(item.get("row_id") or ""), *padded[:QUARTER_COUNT]]) + " |")
  return "\n".join(lines)


def quarter_grid_schema(allowed_row_ids: Sequence[str]) -> Dict[str, Any]:
  return {
    "name": "quarter_grid_probe",
    "schema": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "summary": {"type": "string"},
        "rows": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "row_id": {"type": "string", "enum": [str(item) for item in allowed_row_ids]},
              "row_type": {"type": "string", "enum": ["lever", "output"]},
              "quarter_values": {
                "type": "array",
                "items": {
                  "type": "object",
                  "additionalProperties": False,
                  "properties": {
                    "quarter_index": {"type": "integer", "minimum": 1, "maximum": QUARTER_COUNT},
                    "value": {"type": "number"},
                  },
                  "required": ["quarter_index", "value"],
                },
              },
            },
            "required": ["row_id", "row_type", "quarter_values"],
          },
        },
      },
      "required": ["summary", "rows"],
    },
    "strict": True,
  }


def _realism_memo_prompt_block(source_row: Dict[str, Any]) -> str:
  memo = normalize_realism_memo_payload(
    source_row.get("realism_memo_json") if isinstance(source_row, dict) else {}
  )
  issues = memo.get("issues") if isinstance(memo.get("issues"), list) else []
  if not issues:
    return ""
  issue_lines: List[str] = []
  for item in issues:
    if not isinstance(item, dict):
      continue
    issue = str(item.get("issue") or "").strip()
    detail = str(item.get("detail") or "").strip()
    if not issue or not detail:
      continue
    issue_lines.append(f"- {issue} {detail}".strip())
  if not issue_lines:
    return ""
  return (
    "Active realism correction memo:\n"
      + load_realism_memo_grid_advisory_prompt().strip()
      + "\n"
      + "\n".join(issue_lines)
      + "\n\n"
  )


def build_quarter_grid_prompt(
  *,
  source_row: Dict[str, Any],
  grid_rows: List[Dict[str, Any]],
  governor_payload: Dict[str, Any],
  batch_index: int,
  batch_count: int,
  planning_mode: str,
) -> str:
  business_name = str(source_row.get("business_name") or "").strip() or "Unknown business"
  row_descriptions = [f"- {item['row_id']} ({item['row_type']})" for item in grid_rows]
  realism_memo_block = _realism_memo_prompt_block(source_row)
  stage_governance_block = _stage_governance_prompt_block(governor_payload)
  return "".join(
    [
      f"You are building a quarter-by-quarter financial planning grid for {business_name}.\n",
      planning_mode_text(planning_mode),
      "\n",
      "Return one exact value for every listed row and every quarter Q1 through Q20.\n",
      "Fill every box. Every listed row must have one exact value in every quarter.\n",
      "Do not group periods. Do not omit rows. Do not invent rows.\n",
      "You must preserve every row_id exactly as given. Do not add suffixes, prefixes, labels, or parentheses.\n",
      "Every returned row must contain exactly 20 quarter_values, one for each quarter_index from 1 to 20.\n",
      "Every listed row includes deterministic `cell_envelopes` when Python has an allowed numeric range. "
      "You must keep every returned value inside that row's Q-specific min_value/max_value. "
      "These envelopes are the source of truth for all driver cells; do not free-form outside them.\n",
      "When cost-ratio rows are listed, their envelopes already include the stage maturity caps selected before convergence. "
      "Do not flatten Marketing and R&D to identical values unless the actual business facts make that natural.\n",
      "Rows may stay similar quarter to quarter when genuinely appropriate, but do not flatten the whole horizon into one repeated answer unless the business logic truly requires it.\n",
      "For output rows, use dollar values from Financial Model QTR semantics.\n",
      "For lever rows, use realistic model-input driver values.\n\n",
      stage_governance_block,
      "Shared-capacity rule:\n",
      "- reason at the LOB and product level, not just row by row\n",
      "- when products inside the same LOB share one operating engine, treat that LOB's capacity as one conserved 100% pool\n",
      "- do not silently give every product in the same LOB full standalone service capacity\n",
      "- split that shared LOB capacity realistically across the products in the grid\n",
      "- your product breakout inside a shared LOB must fit within that one whole capacity pool rather than multiple independent pools\n",
      "- only treat product capacities as fully independent when the business context clearly supports separate operating capacity\n\n",
      "Revenue-coupling rule:\n",
      "- revenue is not a standalone row and the three revenue drivers are not independent knobs\n",
      "- Python will multiply Capacity x Unit Price x Utilization for every product and validate the combined revenue path\n",
      "- keep the combined revenue path inside stage_governance_context.stage_ramp_contract; do not hide an unrealistic revenue jump by keeping each individual driver inside its row envelope\n\n",
      "Cost/profitability maturity rule:\n",
      "- stage_governance_context.stage_ramp_contract includes cost-ratio caps and net income margin floors by quarter\n",
      "- shape COGS, Marketing, R&D, G&A, Lease, revenue, utilization, and capacity together so profitability matures naturally by the later horizon\n",
      "- do not wait for a late repair to fix chronic losses; build the cost path coherently from the first grid\n\n",
      "Important financing and equity row meanings:\n",
      "- `schedules::Debt Issuance (New Borrowing)` = debt draws or new borrowing in only\n",
      "- `schedules::Debt Repayment (Scheduled)` = term debt repayment or deleveraging out only\n",
      "- `schedules::Capital Expenditures` = cash capex / PPE spend\n",
      "- `schedules::Less: Principal Repayments` = capital lease principal repayments\n",
      "- `schedules::Plus: Net Additions` = capital lease additions only, not owner draws, not generic financing\n",
      "- `balance_sheet::Owner's Capital` = owner or partner capital contributions in only\n",
      "- `balance_sheet::Distributions` = owner or partner payouts out only; use this for owner cash returns, not Owner's Capital\n",
      "- `balance_sheet::Other Equity` = outside-investor equity capital such as angel, VC, silent partner, crowdfunding, or investor ownership stake; do not use it as routine working-capital funding\n\n",
      "Profitability standard for this probe:\n",
      "- push toward profitability as early as the business stage realistically allows\n",
      "- never force instant mature profitability when stage_governance_context says the company is pre-revenue or early-stage\n",
      "- do not normalize persistent multi-year losses if a believable operating repair exists\n",
      "- use the full set of listed variables if needed to create a credible path\n",
      "- the resulting grid should read like a real company plan for this specific business and stage\n\n",
      "Cash-strategy handling:\n",
      "- if the governor context includes cash_strategy_context, treat it as a required planning dimension, not a throwaway note\n",
      "- do not override core business drivers like revenue realism, operating capacity, or baseline feasibility\n",
      "- instead, make capital allocation choices that are consistent with the selected cash posture using the existing planning levers already in the grid\n",
      "- make sure capex timing, hiring pace, marketing intensity, debt behavior, and retained liquidity read like one coherent management posture\n",
      "- explicitly reflect that posture in the summary so the narrative explains how the selected cash strategy shows up in the plan\n",
      "- the resulting quarter grid should make the cash posture visually legible where the business supports it, rather than leaving cash_strategy invisible in the outputs\n",
      "- do not invent reinvestment behavior; cash strategy is limited to preserve_cash, balanced, or shareholder_return\n",
      "- for preserve cash, keep a visibly more conservative liquidity posture and avoid overly eager cash deployment\n",
      "- for shareholder return, avoid letting excess cash pile up indefinitely without a believable reason to retain it\n",
      "- for balanced, show a middle path with some retained cushion and some selective deployment\n",
      "- do not treat any of the above as rigid rules; they are planning expectations that must still respect realism and economics\n\n",
      realism_memo_block,
      f"This is batch {batch_index} of {batch_count}. Return only the rows listed in this batch.\n\n",
      "Compact governor context payload:\n",
      json.dumps(_compact_governor_payload_for_prompt(governor_payload), ensure_ascii=False),
      "\n\n",
      "Rows you must fill:\n",
      "\n".join(
        [
          f"- {item['row_id']} ({item['row_type']}) :: {str(item.get('label') or item['row_id'])} :: "
          f"cell_envelopes={json.dumps(item.get('cell_envelopes') or [], ensure_ascii=False)}"
          for item in grid_rows
        ]
      ),
      "\n\nBaseline quarter grid:\n",
      grid_markdown(grid_rows),
    ]
  )


def quarter_grid_system_prompt(*, use_real_strategy_prompt: bool, planning_mode: str, realism_memo_present: bool = False) -> str:
  realism_boundary = (
    load_realism_memo_grid_advisory_prompt().strip() + "\n"
    if realism_memo_present
    else ""
  )
  if not use_real_strategy_prompt:
    return (
      "Fill the full quarter grid exactly. Return only the structured JSON schema response. "
      "Use real business judgment and match the company stage. "
      + realism_boundary
      + planning_mode_text(planning_mode)
    )
  return (
    "You are producing a quarter-native financial planning contract for a real business.\n"
    "This is not a grouped-period plan and not a strategy-id response.\n"
    "Do not return strategy ids, lever packages, grouped targets, or target posture.\n"
    "Return only the requested quarter-by-quarter grid rows using the attached schema.\n"
    "Fill every listed row for every quarter Q1 through Q20.\n"
    "Preserve each row_id exactly as given.\n"
    "Use the actual business context, stage, and baseline values to create a realistic path.\n"
    "If stage_governance_context is present, treat it as binding and shape Q1-Q20 around it before optimizing profitability.\n"
    "Before returning, calculate composite revenue yourself as sum(Capacity * Unit Price * Utilization) across products for each quarter and verify every adjacent QoQ growth rate is inside stage_governance_context.stage_ramp_contract.\n"
    "Also apply the stage maturity cost caps and net income margin floors in stage_governance_context.stage_ramp_contract; do not leave late chronic losses for a later repair pass.\n"
    "For percent/ratio rows such as COGS %, Marketing %, R&D %, G&A %, AR days ratios, or utilization, return decimal ratios inside the row envelope: 0.23 means 23%, not 23 and not 0.000023.\n"
    + realism_boundary
    + planning_mode_text(planning_mode)
    + "\n"
    "Express the result as exact quarter values in the quarter grid."
  )


def call_quarter_grid_openai(
  prompt: str,
  *,
  allowed_row_ids: Sequence[str],
  use_real_strategy_prompt: bool,
  planning_mode: str,
  realism_memo_present: bool = False,
) -> Dict[str, Any]:
  api_key = _require_openai_key()
  headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
  }
  payload = {
    "model": _openai_model(),
    "temperature": 0,
    "input": [
      {
        "role": "system",
        "content": [
          {
            "type": "input_text",
            "text": quarter_grid_system_prompt(
              use_real_strategy_prompt=use_real_strategy_prompt,
              planning_mode=planning_mode,
              realism_memo_present=realism_memo_present,
            ),
          }
        ],
      },
      {
        "role": "user",
        "content": [{"type": "input_text", "text": prompt}],
      },
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": "quarter_grid_probe",
        "schema": quarter_grid_schema(allowed_row_ids)["schema"],
        "strict": True,
      }
    },
  }
  response = _post_openai(
    url="https://api.openai.com/v1/responses",
    headers=headers,
    payload=payload,
    timeout_seconds=_openai_timeout_seconds("strategy"),
    max_attempts=1,
  )
  if response.status_code >= 400:
    raise RuntimeError(f"OpenAI API error {response.status_code}: {response.text[:1200]}")
  return _parse_json_response(response.json())


def _quarter_grid_contract_repair_prompt(
  *,
  original_prompt: str,
  validation: Dict[str, Any],
  invalid_response: Dict[str, Any],
) -> str:
  return (
    str(original_prompt or "").strip()
    + "\n\nCONTRACT REPAIR REQUIRED.\n"
    + "Your prior quarter-grid response violated deterministic Python validation. "
    + "Return a complete corrected response for the same requested row_ids only. "
    + "Do not add rows. Do not omit rows. Do not change row_ids. "
    + "Most importantly, the combined revenue path from Capacity * Unit Price * Utilization across all products "
    + "must satisfy stage_governance_context.stage_ramp_contract for every adjacent quarter pair. "
    + "Recalculate composite revenue before answering; if Q2 is too high for Q1, lower Q2 or smooth later quarters rather than violating the ramp.\n"
    + "For ratio rows, repair using decimal ratios inside the envelope. Example: if COGS min is 0.20, return 0.20 or higher, not 0.00002.\n"
    + "Validation errors:\n"
    + json.dumps(
      {
        "out_of_envelope_rows": validation.get("out_of_envelope_rows") or [],
        "composite_revenue_ramp_violations": validation.get("composite_revenue_ramp_violations") or [],
      },
      ensure_ascii=False,
    )
    + "\nInvalid response to repair:\n"
    + json.dumps(invalid_response if isinstance(invalid_response, dict) else {}, ensure_ascii=False)
  )


def chunk_quarter_grid_rows(rows: List[Dict[str, Any]], batch_size: int) -> List[List[Dict[str, Any]]]:
  normalized_size = max(1, int(batch_size or 1))
  return [rows[index:index + normalized_size] for index in range(0, len(rows), normalized_size)]


def _fallback_grid_row_from_requested(requested_row: Dict[str, Any]) -> Dict[str, Any]:
  baseline_values = list(requested_row.get("baseline_values") or [])
  quarter_values: List[Dict[str, Any]] = []
  for quarter_index in range(1, QUARTER_COUNT + 1):
    raw_value = baseline_values[quarter_index - 1] if quarter_index - 1 < len(baseline_values) else 0.0
    value = float_or_none(raw_value)
    quarter_values.append(
      {
        "quarter_index": quarter_index,
        "value": float(value if value is not None else 0.0),
      }
    )
  return {
    "row_id": str(requested_row.get("row_id") or "").strip(),
    "row_type": str(requested_row.get("row_type") or "lever").strip() or "lever",
    "quarter_values": quarter_values,
  }


def _normalize_grid_row(
  *,
  requested_row: Dict[str, Any],
  returned_row: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  fallback_row = _fallback_grid_row_from_requested(requested_row)
  if not isinstance(returned_row, dict):
    return fallback_row
  quarter_values = returned_row.get("quarter_values") if isinstance(returned_row.get("quarter_values"), list) else []
  normalized_values: Dict[int, float] = {}
  for item in quarter_values:
    if not isinstance(item, dict):
      continue
    quarter_index = int(item.get("quarter_index") or 0)
    value = float_or_none(item.get("value"))
    if quarter_index < 1 or quarter_index > QUARTER_COUNT or value is None:
      continue
    normalized_values[quarter_index] = float(value)
  fallback_values = {
    int(item.get("quarter_index") or 0): float_or_none(item.get("value")) or 0.0
    for item in (fallback_row.get("quarter_values") or [])
    if isinstance(item, dict)
  }
  repaired_quarter_values: List[Dict[str, Any]] = []
  for quarter_index in range(1, QUARTER_COUNT + 1):
    repaired_quarter_values.append(
      {
        "quarter_index": quarter_index,
        "value": float(normalized_values.get(quarter_index, fallback_values.get(quarter_index, 0.0))),
      }
    )
  return {
    "row_id": str(requested_row.get("row_id") or "").strip(),
    "row_type": str(requested_row.get("row_type") or "lever").strip() or "lever",
    "quarter_values": repaired_quarter_values,
  }


def repair_quarter_grid_response(
  *,
  requested_rows: List[Dict[str, Any]],
  response_json: Dict[str, Any],
) -> Dict[str, Any]:
  requested_map = {
    str(item.get("row_id") or "").strip(): item
    for item in requested_rows
    if isinstance(item, dict) and str(item.get("row_id") or "").strip()
  }
  returned_rows = response_json.get("rows") if isinstance(response_json.get("rows"), list) else []
  repaired_rows: List[Dict[str, Any]] = []
  seen_ids: set[str] = set()
  extras_dropped = 0
  duplicates_dropped = 0
  repaired_row_ids: List[str] = []

  for item in returned_rows:
    if not isinstance(item, dict):
      continue
    row_id = str(item.get("row_id") or "").strip()
    if not row_id:
      continue
    requested_row = requested_map.get(row_id)
    if requested_row is None:
      extras_dropped += 1
      continue
    if row_id in seen_ids:
      duplicates_dropped += 1
      continue
    normalized_row = _normalize_grid_row(requested_row=requested_row, returned_row=item)
    original_quarters = item.get("quarter_values") if isinstance(item.get("quarter_values"), list) else []
    original_map: Dict[int, float] = {}
    for quarter_value in original_quarters:
      if not isinstance(quarter_value, dict):
        continue
      quarter_index = int(quarter_value.get("quarter_index") or 0)
      value = float_or_none(quarter_value.get("value"))
      if 1 <= quarter_index <= QUARTER_COUNT and value is not None:
        original_map[quarter_index] = float(value)
    repaired_map = {
      int(qv.get("quarter_index") or 0): float_or_none(qv.get("value")) or 0.0
      for qv in (normalized_row.get("quarter_values") or [])
      if isinstance(qv, dict)
    }
    if len(original_quarters) != QUARTER_COUNT or any(
      abs(repaired_map.get(q, 0.0) - original_map.get(q, repaired_map.get(q, 0.0))) > 1e-9
      for q in range(1, QUARTER_COUNT + 1)
    ):
      repaired_row_ids.append(row_id)
    repaired_rows.append(normalized_row)
    seen_ids.add(row_id)

  for requested_row in requested_rows:
    row_id = str(requested_row.get("row_id") or "").strip()
    if not row_id or row_id in seen_ids:
      continue
    repaired_rows.append(_fallback_grid_row_from_requested(requested_row))
    repaired_row_ids.append(row_id)

  return {
    "summary": str(response_json.get("summary") or "").strip(),
    "rows": repaired_rows,
    "repair_metadata": {
      "extras_dropped": extras_dropped,
      "duplicates_dropped": duplicates_dropped,
      "repaired_or_fallback_row_ids": repaired_row_ids,
      "repair_applied": bool(extras_dropped or duplicates_dropped or repaired_row_ids),
    },
  }


def _quarter_grid_row_values(item: Dict[str, Any]) -> Dict[int, float]:
  values: Dict[int, float] = {}
  for quarter_value in (item.get("quarter_values") or []):
    if not isinstance(quarter_value, dict):
      continue
    quarter_index = int(quarter_value.get("quarter_index") or 0)
    value = float_or_none(quarter_value.get("value"))
    if 1 <= quarter_index <= QUARTER_COUNT and value is not None:
      values[quarter_index] = float(value)
  return values


def _composite_revenue_ramp_violations(
  *,
  requested_rows: List[Dict[str, Any]],
  returned_by_id: Dict[str, Dict[str, Any]],
  governor_payload: Optional[Dict[str, Any]],
) -> List[str]:
  context = governor_payload.get("stage_governance_context") if isinstance(governor_payload, dict) else {}
  contract = context.get("stage_ramp_contract") if isinstance(context, dict) and isinstance(context.get("stage_ramp_contract"), dict) else {}
  if not contract:
    return []
  ordinary_max = float(contract.get("revenue_qoq_growth_target_max") or 0.0)
  spike_max = float(contract.get("revenue_qoq_max_spike") or ordinary_max)
  spike_window = {
    int(item)
    for item in (contract.get("revenue_spike_window_quarters") or [])
    if int(float(item or 0)) >= 1
  }
  max_spike_count = int(contract.get("max_spike_count") or 0)
  if ordinary_max <= 0.0:
    return []

  slots: Dict[str, Dict[str, Dict[int, float]]] = {}
  for requested_row in requested_rows:
    if not isinstance(requested_row, dict):
      continue
    if str(requested_row.get("section") or "").strip().lower() != "revenue":
      continue
    driver = str(requested_row.get("driver") or requested_row.get("label") or "").strip().lower()
    if driver not in {"capacity", "unit price", "utilization"}:
      continue
    row_id = str(requested_row.get("row_id") or "").strip()
    returned_row = returned_by_id.get(row_id)
    if not isinstance(returned_row, dict):
      continue
    slot_key = str(requested_row.get("revenue_slot_key") or "").strip() or row_id.rsplit("::", 1)[0]
    slots.setdefault(slot_key, {})[driver] = _quarter_grid_row_values(returned_row)

  if not slots:
    return []
  revenue_by_quarter: Dict[int, float] = {idx: 0.0 for idx in range(1, QUARTER_COUNT + 1)}
  for driver_map in slots.values():
    capacity_values = driver_map.get("capacity") or {}
    price_values = driver_map.get("unit price") or {}
    utilization_values = driver_map.get("utilization") or {}
    for quarter_index in range(1, QUARTER_COUNT + 1):
      revenue_by_quarter[quarter_index] += (
        max(0.0, float(capacity_values.get(quarter_index) or 0.0))
        * max(0.0, float(price_values.get(quarter_index) or 0.0))
        * max(0.0, float(utilization_values.get(quarter_index) or 0.0))
      )

  violations: List[str] = []
  spike_count = 0
  for quarter_index in range(2, QUARTER_COUNT + 1):
    previous_revenue = float(revenue_by_quarter.get(quarter_index - 1) or 0.0)
    current_revenue = float(revenue_by_quarter.get(quarter_index) or 0.0)
    if previous_revenue <= 0.0 or current_revenue <= previous_revenue:
      continue
    growth = (current_revenue - previous_revenue) / previous_revenue
    allowed_growth = ordinary_max
    if growth > ordinary_max and (quarter_index - 1) in spike_window and spike_count < max_spike_count:
      allowed_growth = spike_max
      if growth <= allowed_growth + 1e-9:
        spike_count += 1
        continue
    if growth > allowed_growth + 1e-9:
      violations.append(
        "composite_revenue_ramp::"
        f"Q{quarter_index - 1}->Q{quarter_index}::"
        f"growth={round(growth, 6)}::allowed={round(allowed_growth, 6)}::"
        f"previous_revenue={round(previous_revenue, 2)}::current_revenue={round(current_revenue, 2)}"
      )
  return violations


def validate_quarter_grid_response(
  *,
  requested_rows: List[Dict[str, Any]],
  response_json: Dict[str, Any],
  governor_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  requested_ids = [str(item.get("row_id") or "") for item in requested_rows]
  requested_id_set = set(requested_ids)
  returned_rows = response_json.get("rows") if isinstance(response_json.get("rows"), list) else []
  returned_by_id: Dict[str, Dict[str, Any]] = {}
  duplicates: List[str] = []
  for item in returned_rows:
    if not isinstance(item, dict):
      continue
    row_id = str(item.get("row_id") or "").strip()
    if not row_id:
      continue
    if row_id in returned_by_id:
      duplicates.append(row_id)
    returned_by_id[row_id] = item

  missing_rows = [row_id for row_id in requested_ids if row_id not in returned_by_id]
  extra_rows = sorted(row_id for row_id in returned_by_id if row_id not in requested_id_set)

  malformed_rows: List[str] = []
  flat_rows: List[str] = []
  out_of_envelope_rows: List[str] = []
  requested_by_id = {
    str(item.get("row_id") or "").strip(): item
    for item in requested_rows
    if isinstance(item, dict) and str(item.get("row_id") or "").strip()
  }
  for row_id, item in returned_by_id.items():
    quarter_values = item.get("quarter_values") if isinstance(item.get("quarter_values"), list) else []
    if len(quarter_values) != QUARTER_COUNT:
      malformed_rows.append(f"{row_id}::quarter_count={len(quarter_values)}")
      continue
    seen_quarters = []
    exact_values = []
    for quarter_value in quarter_values:
      if not isinstance(quarter_value, dict):
        malformed_rows.append(f"{row_id}::non_object_value")
        break
      quarter_index = int(quarter_value.get("quarter_index") or 0)
      value = float_or_none(quarter_value.get("value"))
      if quarter_index < 1 or quarter_index > QUARTER_COUNT:
        malformed_rows.append(f"{row_id}::quarter={quarter_index}")
        break
      if value is None:
        malformed_rows.append(f"{row_id}::invalid_value::Q{quarter_index}")
        break
      seen_quarters.append(quarter_index)
      exact_values.append(round(float(value), 6))
      requested_row = requested_by_id.get(row_id) or {}
      envelope_by_quarter = {
        int(env.get("quarter_index") or 0): env
        for env in (requested_row.get("cell_envelopes") or [])
        if isinstance(env, dict)
      }
      envelope = envelope_by_quarter.get(quarter_index)
      if isinstance(envelope, dict):
        min_value = float_or_none(envelope.get("min_value"))
        max_value = float_or_none(envelope.get("max_value"))
        if min_value is not None and float(value) < float(min_value) - 1e-6:
          out_of_envelope_rows.append(
            f"{row_id}::Q{quarter_index}::value={value}::min={min_value}"
          )
        if max_value is not None and float(value) > float(max_value) + 1e-6:
          out_of_envelope_rows.append(
            f"{row_id}::Q{quarter_index}::value={value}::max={max_value}"
          )
    if sorted(seen_quarters) != list(range(1, QUARTER_COUNT + 1)):
      malformed_rows.append(f"{row_id}::quarter_indexes_invalid")
      continue
    if len(set(exact_values)) == 1:
      flat_rows.append(row_id)

  return {
    "requested_row_count": len(requested_rows),
    "returned_row_count": len(returned_by_id),
    "missing_rows": missing_rows,
    "extra_rows": extra_rows,
    "duplicate_rows": duplicates,
    "malformed_rows": malformed_rows,
    "flat_rows": flat_rows,
    "out_of_envelope_rows": out_of_envelope_rows,
    "composite_revenue_ramp_violations": _composite_revenue_ramp_violations(
      requested_rows=requested_rows,
      returned_by_id=returned_by_id,
      governor_payload=governor_payload,
    ),
}
