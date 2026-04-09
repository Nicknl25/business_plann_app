from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import requests
from financial_model_engine.finmo_model import calculate_finmo_model
from financial_model_engine.model_inputs import FinancialModelInputs, QUARTER_COUNT
from financial_model_engine.solver import LeverControl, OutputTarget, SolverOptions, solve_financial_model

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
  from cash_contract_baby_ai import build_binding_cash_contract, validate_binding_cash_contract  # type: ignore
except Exception:
  from client_intake_and_finmo.cash_contract_baby_ai import build_binding_cash_contract, validate_binding_cash_contract  # type: ignore

try:
  from capital_allocation_baby_ai import build_capital_allocation_plan  # type: ignore
except Exception:
  from client_intake_and_finmo.capital_allocation_baby_ai import build_capital_allocation_plan  # type: ignore

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


def _build_baseline_financial_summary(
  *,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Dict[str, Any]:
  financials = financials_json if isinstance(financials_json, dict) else {}
  year1 = financials_year1_json if isinstance(financials_year1_json, dict) else {}
  revenue = _safe_float(year1.get("company_revenue_total_year1") or financials.get("current_revenue"))
  cogs = _safe_float(
    financials.get("cogs_total_year1")
    or year1.get("company_cogs_total_year1")
    or year1.get("cogs_total_year1")
  )
  if cogs <= 0:
    cogs = _safe_float(financials.get("current_cogs"))
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
    os.getenv("CONSISTENCY_GPT_STRATEGY_MODEL")
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
  if kind == "strategy":
    return None
  return None


def _post_openai(
  *,
  url: str,
  headers: Dict[str, str],
  payload: Dict[str, Any],
  timeout_seconds: Optional[int] = None,
  max_attempts: int = 3,
) -> requests.Response:
  attempts = max(1, int(max_attempts or 1))
  last_exc: Optional[Exception] = None
  for attempt in range(attempts):
    try:
      request_kwargs: Dict[str, Any] = {
        "headers": headers,
        "json": payload,
      }
      if timeout_seconds is not None:
        request_kwargs["timeout"] = max(15, int(timeout_seconds))
      resp = requests.post(url, **request_kwargs)
      if resp.status_code in _RETRYABLE_STATUS and attempt < attempts - 1:
        time.sleep(0.75 * (2**attempt))
        continue
      return resp
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as exc:
      last_exc = exc
      if attempt >= attempts - 1:
        raise
      time.sleep(0.75 * (2**attempt))
  if last_exc:
    raise last_exc
  raise RuntimeError("OpenAI request failed unexpectedly.")


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


def _quarter_band_by_index(row: Dict[str, Any], quarter_index: int) -> Optional[Dict[str, Any]]:
  for item in (row.get("quarter_bands") or []):
    if not isinstance(item, dict):
      continue
    try:
      if int(item.get("quarter_index") or 0) == int(quarter_index):
        return item
    except Exception:
      continue
  return None


def _baseline_row_by_id(
  *,
  grid_rows: List[Dict[str, Any]],
  row_id: str,
) -> Optional[Dict[str, Any]]:
  target = str(row_id or "").strip()
  for row in grid_rows:
    if not isinstance(row, dict):
      continue
    if str(row.get("row_id") or "").strip() == target:
      return row
  return None


def _float_or_none_strict(value: Any) -> Optional[float]:
  try:
    num = float(value)
  except Exception:
    return None
  if num != num:
    return None
  return num


def _normalize_pct_points(value: Any) -> Optional[float]:
  num = _float_or_none_strict(value)
  if num is None:
    return None
  # Baby AI should emit whole percent points (e.g. 30 for 30%), but
  # older runs sometimes mixed ratio-style decimals like 0.3 for 30%.
  if num != 0.0 and abs(num) < 1.0:
    return float(num) * 100.0
  return float(num)


def _derive_authoritative_cash_bands(
  *,
  contract: Dict[str, Any],
  grid_rows: List[Dict[str, Any]],
  q1_cash_override: Optional[float] = None,
) -> List[Dict[str, Any]]:
  if not isinstance(contract, dict) or not contract:
    return []
  envelope = contract.get("cash_shape_envelope")
  if not isinstance(envelope, list) or len(envelope) != (QUARTER_COUNT - 1):
    return []
  starting_anchor = contract.get("starting_cash_anchor") if isinstance(contract.get("starting_cash_anchor"), dict) else {}
  starting_cash = _float_or_none_strict(starting_anchor.get("amount"))
  if starting_cash is None or starting_cash < 0:
    return []

  baseline_cash_row = next(
    (
      row
      for row in grid_rows
      if isinstance(row, dict) and str(row.get("row_id") or "").strip() == "Cash"
    ),
    None,
  )
  baseline_cash_values = (
    baseline_cash_row.get("baseline_values")
    if isinstance(baseline_cash_row, dict) and isinstance(baseline_cash_row.get("baseline_values"), list)
    else []
  )
  q1_cash = _float_or_none_strict(q1_cash_override)
  if q1_cash is None:
    q1_cash = _float_or_none_strict(baseline_cash_values[0]) if baseline_cash_values else None
  if q1_cash is None or q1_cash < 0:
    q1_cash = float(starting_cash)

  by_quarter: Dict[int, Dict[str, Any]] = {}
  for item in envelope:
    if not isinstance(item, dict):
      continue
    try:
      by_quarter[int(item.get("quarter_index") or 0)] = item
    except Exception:
      continue

  bands: List[Dict[str, Any]] = [
    {
      "quarter_index": 1,
      "min_value": round(float(q1_cash), 6),
      "max_value": round(float(q1_cash), 6),
    }
  ]
  prev_min = float(q1_cash)
  prev_max = float(q1_cash)
  for quarter_index in range(2, QUARTER_COUNT + 1):
    item = by_quarter.get(quarter_index) or {}
    min_pct_change = _normalize_pct_points(item.get("min_pct_change_from_prior"))
    max_pct_change = _normalize_pct_points(item.get("max_pct_change_from_prior"))
    if min_pct_change is None or max_pct_change is None:
      return []
    if float(min_pct_change) > float(max_pct_change):
      raise RuntimeError(
        f"Binding cash contract produced incoherent percentage changes for Q{quarter_index}: "
        f"min_pct_change_from_prior {float(min_pct_change):.2f} exceeds max_pct_change_from_prior {float(max_pct_change):.2f}."
      )

    actual_min = max(0.0, float(prev_min) * (1.0 + float(min_pct_change) / 100.0))
    actual_max = max(0.0, float(prev_max) * (1.0 + float(max_pct_change) / 100.0))
    if actual_min > actual_max:
      raise RuntimeError(
        f"Binding cash contract produced incoherent cash bands for Q{quarter_index}: "
        f"min {actual_min:.2f} exceeds max {actual_max:.2f}."
      )
    actual_min = round(actual_min, 6)
    actual_max = round(actual_max, 6)
    bands.append(
      {
        "quarter_index": quarter_index,
        "min_value": actual_min,
        "max_value": actual_max,
      }
    )
    prev_min = actual_min
    prev_max = actual_max
  return bands


def _derive_feasible_q1_cash_anchor(
  *,
  baseline_model_input_json: Dict[str, Any],
  response_json: Dict[str, Any],
) -> Optional[float]:
  if not isinstance(response_json, dict):
    return None
  rows = response_json.get("rows") if isinstance(response_json.get("rows"), list) else []
  q1_rows: List[Dict[str, Any]] = []
  for row in rows:
    if not isinstance(row, dict):
      continue
    if str(row.get("row_type") or "").strip().lower() != "lever":
      continue
    q1_band = _quarter_band_by_index(row, 1)
    if not isinstance(q1_band, dict):
      continue
    q1_rows.append(
      {
        "row_id": str(row.get("row_id") or "").strip(),
        "row_type": "lever",
        "quarter_bands": [
          {
            "quarter_index": 1,
            "min_value": q1_band.get("min_value"),
            "max_value": q1_band.get("max_value"),
          }
        ],
      }
    )
  if not q1_rows:
    return None
  try:
    q1_result = solve_live_quarter_grid_plan(
      baseline_model_input_json=baseline_model_input_json,
      grid_json={"summary": "Q1 feasibility anchor", "rows": q1_rows},
      max_iterations=120,
    )
  except Exception:
    return None
  solver_result = q1_result.get("solver_result") if isinstance(q1_result, dict) else None
  solved_outputs = getattr(solver_result, "solved_outputs", None) if solver_result is not None else None
  q1_row = solved_outputs[0] if isinstance(solved_outputs, list) and solved_outputs and isinstance(solved_outputs[0], dict) else {}
  q1_cash = _float_or_none_strict(q1_row.get("ending_cash"))
  if q1_cash is None:
    q1_cash = _float_or_none_strict(q1_row.get("cash"))
  if q1_cash is None or q1_cash < 0:
    return None
  return float(q1_cash)


def _refresh_cash_contract_from_q1_anchor(
  *,
  contract: Dict[str, Any],
  governor_payload: Dict[str, Any],
  grid_rows: List[Dict[str, Any]],
  baseline_model_input_json: Dict[str, Any],
  response_json: Dict[str, Any],
) -> tuple[Dict[str, Any], List[Dict[str, Any]], Optional[float]]:
  if not isinstance(contract, dict) or not contract:
    return {}, [], None
  q1_cash_anchor = _derive_feasible_q1_cash_anchor(
    baseline_model_input_json=baseline_model_input_json,
    response_json=response_json,
  )
  authoritative_cash_bands = _derive_authoritative_cash_bands(
    contract=contract,
    grid_rows=grid_rows,
    q1_cash_override=q1_cash_anchor,
  )
  refreshed_contract = dict(contract)
  if q1_cash_anchor is not None:
    refreshed_contract["q1_cash_anchor"] = {
      "ending_cash": round(float(q1_cash_anchor), 6),
      "source": "q1_feasibility_solve",
    }
  if authoritative_cash_bands:
    refreshed_contract["authoritative_cash_bands"] = _sanitize_canonical_live_payload(authoritative_cash_bands)
  governor_payload["cash_constraint_contract"] = _sanitize_canonical_live_payload(refreshed_contract)
  return refreshed_contract, authoritative_cash_bands, q1_cash_anchor


def _apply_authoritative_cash_bands(
  *,
  response_json: Dict[str, Any],
  authoritative_cash_bands: List[Dict[str, Any]],
) -> Dict[str, Any]:
  if not isinstance(response_json, dict) or not authoritative_cash_bands:
    return response_json
  rows = response_json.get("rows") if isinstance(response_json.get("rows"), list) else []
  updated_rows: List[Dict[str, Any]] = []
  replaced = False
  for row in rows:
    if not isinstance(row, dict):
      continue
    if str(row.get("row_id") or "").strip() == "Cash":
      updated = dict(row)
      updated["row_type"] = "output"
      updated["quarter_bands"] = [dict(item) for item in authoritative_cash_bands]
      updated_rows.append(updated)
      replaced = True
      continue
    updated_rows.append(row)
  if not replaced:
    updated_rows.append(
      {
        "row_id": "Cash",
        "row_type": "output",
        "quarter_bands": [dict(item) for item in authoritative_cash_bands],
      }
    )
  updated = dict(response_json)
  updated["rows"] = updated_rows
  return updated


_CAPITAL_ALLOCATION_ROW_IDS = {
  "expenses::Payroll",
  "expenses::Marketing",
  "balance_sheet::Owner's Capital",
  "balance_sheet::Other Equity",
}


def _capital_allocation_target_rows(
  *,
  grid_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  selected: List[Dict[str, Any]] = []
  for row in grid_rows:
    if not isinstance(row, dict):
      continue
    if str(row.get("row_type") or "").strip().lower() != "lever":
      continue
    row_id = str(row.get("row_id") or "").strip()
    section = str(row.get("section") or "").strip().lower()
    if not row_id:
      continue
    if section == "schedules" or row_id in _CAPITAL_ALLOCATION_ROW_IDS:
      selected.append(dict(row))
  return selected


def _capital_row_baseline_band(
  *,
  baseline_row: Dict[str, Any],
  quarter_index: int,
) -> Dict[str, Any]:
  baseline_values = list(baseline_row.get("baseline_values") or [])
  baseline_value = 0.0
  if 1 <= quarter_index <= len(baseline_values):
    baseline_value = float(_safe_float(baseline_values[quarter_index - 1]))
  return {
    "quarter_index": quarter_index,
    "min_value": round(float(baseline_value), 6),
    "max_value": round(float(baseline_value), 6),
  }


def _normalize_capital_allocation_rows(
  *,
  plan: Dict[str, Any],
  target_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  if not isinstance(plan, dict) or not target_rows:
    return []
  returned_rows = plan.get("rows") if isinstance(plan.get("rows"), list) else []
  returned_by_id = {
    str(item.get("row_id") or "").strip(): item
    for item in returned_rows
    if isinstance(item, dict) and str(item.get("row_id") or "").strip()
  }
  normalized_rows: List[Dict[str, Any]] = []
  for baseline_row in target_rows:
    row_id = str(baseline_row.get("row_id") or "").strip()
    if not row_id:
      continue
    returned_row = returned_by_id.get(row_id) if isinstance(returned_by_id.get(row_id), dict) else {}
    returned_bands = returned_row.get("quarter_bands") if isinstance(returned_row.get("quarter_bands"), list) else []
    returned_by_q = {
      int(item.get("quarter_index") or 0): item
      for item in returned_bands
      if isinstance(item, dict)
    }
    quarter_bands: List[Dict[str, Any]] = []
    for quarter_index in range(1, QUARTER_COUNT + 1):
      if quarter_index == 1:
        quarter_bands.append(
          _capital_row_baseline_band(
            baseline_row=baseline_row,
            quarter_index=quarter_index,
          )
        )
        continue
      returned_band = returned_by_q.get(quarter_index) if isinstance(returned_by_q.get(quarter_index), dict) else {}
      min_value = _float_or_none_strict(returned_band.get("min_value"))
      max_value = _float_or_none_strict(returned_band.get("max_value"))
      if min_value is None or max_value is None:
        baseline_band = _capital_row_baseline_band(
          baseline_row=baseline_row,
          quarter_index=quarter_index,
        )
        quarter_bands.append(baseline_band)
        continue
      low = min(float(min_value), float(max_value))
      high = max(float(min_value), float(max_value))
      quarter_bands.append(
        {
          "quarter_index": quarter_index,
          "min_value": round(low, 6),
          "max_value": round(high, 6),
        }
      )
    normalized_rows.append(
      {
        "row_id": row_id,
        "row_type": "lever",
        "quarter_bands": quarter_bands,
      }
    )
  return normalized_rows


def _apply_authoritative_rows(
  *,
  response_json: Dict[str, Any],
  authoritative_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
  if not isinstance(response_json, dict) or not authoritative_rows:
    return response_json
  authoritative_by_id = {
    str(item.get("row_id") or "").strip(): item
    for item in authoritative_rows
    if isinstance(item, dict) and str(item.get("row_id") or "").strip()
  }
  rows = response_json.get("rows") if isinstance(response_json.get("rows"), list) else []
  updated_rows: List[Dict[str, Any]] = []
  seen: set[str] = set()
  for row in rows:
    if not isinstance(row, dict):
      continue
    row_id = str(row.get("row_id") or "").strip()
    if row_id and row_id in authoritative_by_id:
      authoritative = dict(authoritative_by_id[row_id])
      authoritative["row_type"] = str(authoritative.get("row_type") or row.get("row_type") or "lever").strip() or "lever"
      updated_rows.append(authoritative)
      seen.add(row_id)
      continue
    updated_rows.append(row)
  for row_id, authoritative in authoritative_by_id.items():
    if row_id in seen:
      continue
    next_row = dict(authoritative)
    next_row["row_type"] = str(next_row.get("row_type") or "lever").strip() or "lever"
    updated_rows.append(next_row)
  updated = dict(response_json)
  updated["rows"] = updated_rows
  return updated


def _planner_rows_for_grid_construction(
  *,
  grid_rows: List[Dict[str, Any]],
  authoritative_cash_bands: List[Dict[str, Any]],
  authoritative_capital_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  omitted_row_ids = {
    str(item.get("row_id") or "").strip()
    for item in authoritative_capital_rows
    if isinstance(item, dict) and str(item.get("row_id") or "").strip()
  }
  if authoritative_cash_bands:
    omitted_row_ids.add("Cash")
  if not omitted_row_ids:
    return list(grid_rows)
  return [
    row
    for row in grid_rows
    if isinstance(row, dict) and str(row.get("row_id") or "").strip() not in omitted_row_ids
  ]


def _cash_row_from_response(response_json: Dict[str, Any]) -> Optional[Dict[str, Any]]:
  rows = response_json.get("rows") if isinstance(response_json, dict) else None
  if not isinstance(rows, list):
    return None
  for row in rows:
    if not isinstance(row, dict):
      continue
    if str(row.get("row_id") or "").strip() == "Cash":
      return row
  return None


def _cash_row_matches_authoritative_bands(
  *,
  response_json: Dict[str, Any],
  authoritative_cash_bands: List[Dict[str, Any]],
) -> Dict[str, Any]:
  if not authoritative_cash_bands:
    return {
      "matches": True,
      "mismatch_count": 0,
      "mismatch_quarters": [],
    }
  cash_row = _cash_row_from_response(response_json)
  quarter_bands = list((cash_row or {}).get("quarter_bands") or []) if isinstance(cash_row, dict) else []
  authoritative_by_q = {
    int(item.get("quarter_index") or 0): item
    for item in authoritative_cash_bands
    if isinstance(item, dict)
  }
  returned_by_q = {
    int(item.get("quarter_index") or 0): item
    for item in quarter_bands
    if isinstance(item, dict)
  }
  mismatch_quarters: List[int] = []
  for quarter_index in range(1, QUARTER_COUNT + 1):
    expected = authoritative_by_q.get(quarter_index) or {}
    actual = returned_by_q.get(quarter_index) or {}
    expected_min = _float_or_none_strict(expected.get("min_value"))
    expected_max = _float_or_none_strict(expected.get("max_value"))
    actual_min = _float_or_none_strict(actual.get("min_value"))
    actual_max = _float_or_none_strict(actual.get("max_value"))
    if expected_min is None or expected_max is None or actual_min is None or actual_max is None:
      mismatch_quarters.append(quarter_index)
      continue
    if abs(expected_min - actual_min) > 1e-6 or abs(expected_max - actual_max) > 1e-6:
      mismatch_quarters.append(quarter_index)
  return {
    "matches": not mismatch_quarters,
    "mismatch_count": len(mismatch_quarters),
    "mismatch_quarters": mismatch_quarters,
  }


def _cash_shape_summary(
  *,
  contract: Dict[str, Any],
  authoritative_cash_bands: List[Dict[str, Any]],
) -> Dict[str, Any]:
  envelope = contract.get("cash_shape_envelope") if isinstance(contract, dict) else None
  entries = envelope if isinstance(envelope, list) else []
  q1_cash_anchor = contract.get("q1_cash_anchor") if isinstance(contract, dict) and isinstance(contract.get("q1_cash_anchor"), dict) else {}
  deployment_quarters = [
    int(item.get("quarter_index") or 0)
    for item in entries
    if isinstance(item, dict) and str(item.get("shape_note") or "").strip() == "deployment_window"
  ]
  return {
    "strategy": str((((contract.get("strategy_interpretation") or {}) if isinstance(contract, dict) else {}).get("value") or "")).strip(),
    "q1_anchor_source": str(q1_cash_anchor.get("source") or "").strip(),
    "q1_anchor_ending_cash": _float_or_none_strict(q1_cash_anchor.get("ending_cash")),
    "deployment_quarters": deployment_quarters,
    "quarter_count": len(authoritative_cash_bands),
    "q1_band": _sanitize_canonical_live_payload(authoritative_cash_bands[0]) if authoritative_cash_bands else {},
    "q20_band": _sanitize_canonical_live_payload(authoritative_cash_bands[-1]) if authoritative_cash_bands else {},
  }


def _cash_chain_validation(
  *,
  contract: Dict[str, Any],
  authoritative_cash_bands: List[Dict[str, Any]],
) -> Dict[str, Any]:
  q1_cash_anchor = contract.get("q1_cash_anchor") if isinstance(contract, dict) and isinstance(contract.get("q1_cash_anchor"), dict) else {}
  q1_anchor_value = _float_or_none_strict(q1_cash_anchor.get("ending_cash"))
  envelope = contract.get("cash_shape_envelope") if isinstance(contract, dict) else None
  envelope_entries = envelope if isinstance(envelope, list) else []
  bands_by_q = {
    int(item.get("quarter_index") or 0): item
    for item in authoritative_cash_bands
    if isinstance(item, dict)
  }
  envelope_by_q = {
    int(item.get("quarter_index") or 0): item
    for item in envelope_entries
    if isinstance(item, dict)
  }
  q1_band = bands_by_q.get(1) or {}
  q1_band_min = _float_or_none_strict(q1_band.get("min_value"))
  q1_band_max = _float_or_none_strict(q1_band.get("max_value"))
  q1_matches = (
    q1_anchor_value is not None
    and q1_band_min is not None
    and q1_band_max is not None
    and abs(q1_band_min - q1_anchor_value) <= 1e-6
    and abs(q1_band_max - q1_anchor_value) <= 1e-6
  )
  chain_mismatch_quarters: List[int] = []
  if not q1_matches:
    chain_mismatch_quarters.append(1)
  prev_min = q1_anchor_value
  prev_max = q1_anchor_value
  for quarter_index in range(2, QUARTER_COUNT + 1):
    item = envelope_by_q.get(quarter_index) or {}
    min_pct_change = _normalize_pct_points(item.get("min_pct_change_from_prior"))
    max_pct_change = _normalize_pct_points(item.get("max_pct_change_from_prior"))
    expected_band = bands_by_q.get(quarter_index) or {}
    actual_min = _float_or_none_strict(expected_band.get("min_value"))
    actual_max = _float_or_none_strict(expected_band.get("max_value"))
    if (
      prev_min is None
      or prev_max is None
      or min_pct_change is None
      or max_pct_change is None
      or actual_min is None
      or actual_max is None
    ):
      chain_mismatch_quarters.append(quarter_index)
      continue
    expected_min = round(max(0.0, float(prev_min) * (1.0 + float(min_pct_change) / 100.0)), 6)
    expected_max = round(max(0.0, float(prev_max) * (1.0 + float(max_pct_change) / 100.0)), 6)
    if abs(expected_min - actual_min) > 1e-6 or abs(expected_max - actual_max) > 1e-6:
      chain_mismatch_quarters.append(quarter_index)
    prev_min = actual_min
    prev_max = actual_max
  return {
    "q1_anchor_present": q1_anchor_value is not None,
    "q1_band_matches_anchor": q1_matches,
    "q2_through_q20_chained": not [q for q in chain_mismatch_quarters if q >= 2],
    "chain_mismatch_quarters": chain_mismatch_quarters,
  }


def _solved_cash_band_audit(
  *,
  grid_json: Dict[str, Any],
  solved_outputs: List[Dict[str, Any]],
) -> Dict[str, Any]:
  cash_row = next(
    (
      row
      for row in (grid_json.get("rows") or [])
      if isinstance(row, dict) and str(row.get("row_id") or "").strip() == "Cash"
    ),
    None,
  )
  quarter_bands = cash_row.get("quarter_bands") if isinstance(cash_row, dict) and isinstance(cash_row.get("quarter_bands"), list) else []
  bands_by_q = {
    int(item.get("quarter_index") or 0): item
    for item in quarter_bands
    if isinstance(item, dict)
  }
  mismatch_quarters: List[int] = []
  for row in solved_outputs or []:
    if not isinstance(row, dict):
      continue
    quarter_index = int(row.get("quarter_index") or 0)
    if quarter_index < 1:
      continue
    band = bands_by_q.get(quarter_index) or {}
    min_value = _float_or_none_strict(band.get("min_value"))
    max_value = _float_or_none_strict(band.get("max_value"))
    cash_value = _float_or_none_strict(row.get("ending_cash"))
    if cash_value is None:
      cash_value = _float_or_none_strict(row.get("cash"))
    if min_value is None or max_value is None or cash_value is None:
      mismatch_quarters.append(quarter_index)
      continue
    if cash_value < (min_value - 1e-6) or cash_value > (max_value + 1e-6):
      mismatch_quarters.append(quarter_index)
  return {
    "all_quarters_inside": not mismatch_quarters,
    "mismatch_quarters": mismatch_quarters,
    "mismatch_count": len(mismatch_quarters),
  }


def _build_cash_pipeline_audit(
  *,
  contract: Dict[str, Any],
  authoritative_cash_bands: List[Dict[str, Any]],
  authoritative_capital_rows: List[Dict[str, Any]],
  planner_grid_rows: List[Dict[str, Any]],
  response_json: Dict[str, Any],
  cash_contract_review: Dict[str, Any],
) -> Dict[str, Any]:
  planner_row_ids = [
    str(item.get("row_id") or "").strip()
    for item in planner_grid_rows
    if isinstance(item, dict) and str(item.get("row_id") or "").strip()
  ]
  cash_match = _cash_row_matches_authoritative_bands(
    response_json=response_json,
    authoritative_cash_bands=authoritative_cash_bands,
  )
  chain_validation = _cash_chain_validation(
    contract=contract,
    authoritative_cash_bands=authoritative_cash_bands,
  )
  return {
    "contract_present": bool(contract),
    "authoritative_cash_bands_present": bool(authoritative_cash_bands),
    "authoritative_cash_band_quarters": len(authoritative_cash_bands),
    "authoritative_capital_rows_present": bool(authoritative_capital_rows),
    "authoritative_capital_row_count": len(authoritative_capital_rows),
    "planner_cash_row_omitted": "Cash" not in planner_row_ids,
    "planner_capital_rows_omitted": all(
      str(item.get("row_id") or "").strip() not in planner_row_ids
      for item in authoritative_capital_rows
      if isinstance(item, dict) and str(item.get("row_id") or "").strip()
    ),
    "final_cash_row_matches_authoritative": bool(cash_match.get("matches")),
    "final_cash_row_mismatch_count": int(cash_match.get("mismatch_count") or 0),
    "final_cash_row_mismatch_quarters": list(cash_match.get("mismatch_quarters") or []),
    "q1_anchor_present": bool(chain_validation.get("q1_anchor_present")),
    "q1_band_matches_anchor": bool(chain_validation.get("q1_band_matches_anchor")),
    "q2_through_q20_chained": bool(chain_validation.get("q2_through_q20_chained")),
    "cash_chain_mismatch_quarters": list(chain_validation.get("chain_mismatch_quarters") or []),
    "validator_status": str(cash_contract_review.get("status") or "").strip(),
    "validator_cash_band_compliance": str(cash_contract_review.get("cash_band_compliance") or "").strip(),
    "validator_grid_internal_consistency": str(cash_contract_review.get("grid_internal_consistency") or "").strip(),
    "validator_primary_failure_domain": str(cash_contract_review.get("primary_failure_domain") or "").strip(),
    "cash_shape_summary": _cash_shape_summary(
      contract=contract,
      authoritative_cash_bands=authoritative_cash_bands,
    ),
  }


def _clip_shared_capacity_max_bands(
  *,
  response_json: Dict[str, Any],
  ops_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Dict[str, Any]:
  rows = response_json.get("rows") if isinstance(response_json.get("rows"), list) else []
  row_map = {
    str(item.get("row_id") or "").strip(): item
    for item in rows
    if isinstance(item, dict) and str(item.get("row_id") or "").strip()
  }
  clips: List[Dict[str, Any]] = []
  for group in _shared_capacity_lobs(ops_json=ops_json, financials_year1_json=financials_year1_json):
    lob_name = str(group.get("lob_name") or "").strip()
    product_names = [str(item or "").strip() for item in (group.get("product_names") or []) if str(item or "").strip()]
    capacity_ceiling = float(group.get("capacity_ceiling") or 0.0)
    if len(product_names) < 2 or capacity_ceiling <= 0:
      continue
    for quarter_index in range(1, QUARTER_COUNT + 1):
      product_caps: Dict[str, Dict[str, Any]] = {}
      total_max = 0.0
      for product_name in product_names:
        row_id = f"revenue::{lob_name}::{product_name}::Capacity"
        row = row_map.get(row_id)
        if not isinstance(row, dict):
          continue
        band = _quarter_band_by_index(row, quarter_index)
        if not isinstance(band, dict):
          continue
        max_value = float_or_none(band.get("max_value"))
        min_value = float_or_none(band.get("min_value"))
        if max_value is None:
          continue
        total_max += float(max_value)
        product_caps[product_name] = {
          "band": band,
          "max_value": float(max_value),
          "min_value": float(min_value or 0.0),
        }
      if total_max <= capacity_ceiling + 1e-9 or len(product_caps) < 2:
        continue
      scale_factor = capacity_ceiling / total_max if total_max > 0 else 1.0
      for product_name, info in product_caps.items():
        current_max = float(info["max_value"])
        current_min = float(info["min_value"])
        clipped_max = max(current_min, current_max * scale_factor)
        if clipped_max >= current_max - 1e-9:
          continue
        info["band"]["max_value"] = round(float(clipped_max), 6)
        clips.append(
          {
            "lob_name": lob_name,
            "product_name": product_name,
            "quarter_index": quarter_index,
            "capacity_ceiling": round(capacity_ceiling, 6),
            "scale_factor": round(scale_factor, 6),
            "from_max": round(current_max, 6),
            "to_max": round(float(clipped_max), 6),
          }
        )
  return {
    "response_json": response_json,
    "clips": clips,
  }


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
    business_name=str(source_row.get("business_name") or "").strip(),
    ops_json=ops_json,
    target_market_json=target_market_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    fulfillment_json=fulfillment_json,
    marketing_model_json=marketing_model_json,
    model_input_json=model_input_json,
    finmo_json=finmo_json,
    realism_memo_json=normalize_realism_memo_payload(source_row.get("realism_memo_json")),
    business_facts={},
  )


def _cash_strategy_context(financials_json: Dict[str, Any]) -> Dict[str, Any]:
  financials = financials_json if isinstance(financials_json, dict) else {}
  strategy = str(financials.get("cash_strategy") or "").strip().lower()
  option_map = {
    "reinvest": {
      "value": "reinvest",
      "label": "Reinvest",
      "description": "The client would generally prefer extra cash to be put back into growth, capacity, or expansion when that is realistic.",
      "management_posture": "Management is willing to recycle constrained cash back into credible growth needs when the business can support it.",
      "coherence_test": "The non-cash grid should not read like management is hoarding operating flexibility while also claiming a growth-first posture.",
      "cash_path_discipline": "Use real deployment windows. Do not default to a comfortably rising cash max band every quarter if the strategy is reinvest and the business can credibly absorb cash into growth.",
    },
    "preserve_cash": {
      "value": "preserve_cash",
      "label": "Preserve cash",
      "description": "The client would generally prefer a thicker cash cushion and a more conservative liquidity posture.",
      "management_posture": "Management prefers thicker liquidity protection and more selective deployment decisions.",
      "coherence_test": "The non-cash grid should not look unnecessarily aggressive if the stated posture is to preserve cash.",
      "cash_path_discipline": "Favor continued positive cash build, but avoid unrealistically explosive accumulation. Bands should still be disciplined and believable.",
    },
    "shareholder_return": {
      "value": "shareholder_return",
      "label": "Shareholder return",
      "description": "The client would generally prefer excess cash to be available for owner or shareholder distributions rather than simply accumulating on the balance sheet.",
      "management_posture": "Management is less willing to leave excess capital idle inside the business once operating needs are covered.",
      "coherence_test": "The non-cash grid should not read like cash-hoarding or growth-at-all-costs behavior if the stated posture is shareholder return.",
      "cash_path_discipline": "Once a believable cushion is established, do not let the cash path keep compounding upward by default. Allow flatter or negative quarters when reality supports capital extraction.",
    },
    "balanced": {
      "value": "balanced",
      "label": "Balanced",
      "description": "The client wants a mix of cash preservation and selective reinvestment rather than pushing to either extreme.",
      "management_posture": "Management wants a middle path with protected liquidity and selective reinvestment when justified.",
      "coherence_test": "The non-cash grid should avoid collapsing into either an extreme hoarding posture or an extreme redeployment posture without a strong business reason.",
      "cash_path_discipline": "Mix build, flattening, and selective deployment. Do not let balanced collapse into a pure staircase or into extreme volatility.",
    },
  }
  selected = dict(option_map.get(strategy) or {})
  if not selected:
    return {}
  selected["planning_role"] = "required planning consistency dimension"
  selected["constraint_role"] = "management-posture context that must stay coherent with the hard app-owned cash constraint"
  selected["non_override_rule"] = (
    "Do not override core business drivers like revenue realism or operating capacity. "
    "Treat spread-placeholder row values as non-authoritative for later quarters. "
    "The hard cash constraint is set elsewhere; your job is to make the non-cash grid behave coherently underneath it."
  )
  selected["required_alignment_dimensions"] = [
    "capex timing",
    "hiring pace",
    "marketing intensity",
    "debt behavior",
    "operating posture",
  ]
  selected["differentiation_requirement"] = (
    "This strategy should still materially differentiate the non-cash plan from the other cash postures. "
    "Do not let the result collapse into only a slightly different version of the same operating plan."
  )
  selected["counterfactual_test"] = (
    "If the same business were planned under a different cash strategy, the non-cash grid should look meaningfully different in managerial posture and discretionary choices."
  )
  selected["realism_guardrail"] = (
    "Keep those decisions believable for the business. The goal is managerial coherence under the hard cash law, not theatrical changes that break realism or core operating logic."
  )
  selected["band_discipline"] = (
    "Use tighter bands in the quarters that are meant to visibly express the strategy. Deployment, flattening, and steady-retention quarters should not be left with wide upside if that would dilute the posture."
  )
  selected["quarter_role_discipline"] = {
    "buffer_build": "Positive build is allowed, especially early, but avoid needlessly huge upside unless the business reality clearly supports it.",
    "slower_build": "Still positive overall, but narrower and more moderated than a pure build quarter.",
    "deployment_window": "This quarter should visibly consume or constrain cash. If the strategy is reinvest or shareholder_return and the business supports it, do not default to a generous positive max band.",
    "flattening": "Treat this as near-flat or mildly negative/positive. Do not let flattening quarters look like ordinary growth quarters.",
    "rebuild": "Allow recovery after deployment, but keep it disciplined and strategy-consistent.",
    "steady_retention": "Use a controlled, believable path. Bands should usually be narrower here than in early build phases.",
  }
  selected["narrative_requirement"] = (
    "Explicitly explain how the selected cash strategy is reflected in the quarter plan so the narrative and the non-cash grid tell the same management story."
  )
  return selected


def _baseline_cash_path_from_finmo(finmo_json: Dict[str, Any]) -> List[float]:
  rows = [item for item in ((finmo_json.get("quarter_rows") or []) if isinstance(finmo_json, dict) else []) if isinstance(item, dict)]
  values: List[float] = []
  for item in rows[:QUARTER_COUNT]:
    value = float_or_none(item.get("ending_cash"))
    values.append(0.0 if value is None else float(value))
  if len(values) < QUARTER_COUNT:
    values.extend([0.0] * (QUARTER_COUNT - len(values)))
  return values[:QUARTER_COUNT]


def _cash_reality_context(
  *,
  business_name: str,
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  baseline_summary: Dict[str, Any],
  realism_memo_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  financials = financials_json if isinstance(financials_json, dict) else {}
  realism = normalize_realism_memo_payload(realism_memo_json or {})
  issues = realism.get("issues") if isinstance(realism.get("issues"), list) else []
  compact_issues: List[Dict[str, str]] = []
  for item in issues[:6]:
    if not isinstance(item, dict):
      continue
    compact_issues.append(
      {
        "issue": str(item.get("issue") or "").strip(),
        "detail": str(item.get("detail") or "").strip(),
      }
    )
  ops = ops_json if isinstance(ops_json, dict) else {}
  people = people_json if isinstance(people_json, dict) else {}
  return {
    "business_name": str(business_name or "").strip(),
    "business_description": str(ops.get("business_description") or "").strip(),
    "delivery_method": str(ops.get("delivery_method") or "").strip(),
    "sales_channel": str(ops.get("sales_channel") or "").strip(),
    "geography": str(ops.get("geography") or "").strip(),
    "growth_lever": str(ops.get("growth_lever") or "").strip(),
    "competitive_advantage": str(ops.get("competitive_advantage") or "").strip(),
    "owner_background": str(people.get("owner_background") or "").strip(),
    "other_key_people": str(people.get("other_key_people") or "").strip(),
    "starting_cash": _safe_float(financials.get("cash_on_hand")),
    "accounts_receivable": _safe_float(financials.get("ar_balance")),
    "accounts_payable": _safe_float(financials.get("ap_balance")),
    "inventory_balance": _safe_float(financials.get("inventory_balance")),
    "current_capex": _safe_float(financials.get("current_capex")),
    "initial_assets": _safe_float(financials.get("initial_assets")),
    "initial_equity": _safe_float(financials.get("initial_equity")),
    "total_debt_outstanding": _safe_float(financials.get("total_debt_outstanding")),
    "annual_interest_payment": _safe_float(financials.get("annual_interest_payment")),
    "annual_principal_payment": _safe_float(financials.get("annual_principal_payment")),
    "monthly_rent_expense": _safe_float(financials.get("monthly_rent_expense")),
    "owner_compensation": _safe_float(financials.get("owner_compensation")),
    "current_financial_summary": _sanitize_canonical_live_payload(baseline_summary or {}),
    "reference_cash_path": _sanitize_canonical_live_payload(_baseline_cash_path_from_finmo(finmo_json)),
    "realism_memo_status": str(realism.get("status") or "").strip(),
    "realism_issue_count": len(compact_issues),
    "realism_issues": compact_issues,
    "lob_product_summary": _sanitize_canonical_live_payload(_ops_lob_product_summary(ops)),
  }


def build_governor_payload_from_context(
  *,
  business_name: str = "",
  ops_json: Dict[str, Any],
  target_market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  fulfillment_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  realism_memo_json: Optional[Dict[str, Any]] = None,
  business_facts: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  del target_market_json, fulfillment_json, marketing_model_json, business_facts
  baseline_summary = _baseline_summary_from_finmo_json(finmo_json) or _build_baseline_financial_summary(
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
  )
  cash_strategy_context = _cash_strategy_context(financials_json)
  return {
    "current_financial_summary": _sanitize_canonical_live_payload(baseline_summary or {}),
    "ops_lob_product_summary": _sanitize_canonical_live_payload(_ops_lob_product_summary(ops_json or {})),
    "cash_reality_context": _sanitize_canonical_live_payload(
      _cash_reality_context(
        business_name=business_name,
        ops_json=ops_json or {},
        people_json=people_json or {},
        financials_json=financials_json or {},
        finmo_json=finmo_json or {},
        baseline_summary=baseline_summary or {},
        realism_memo_json=realism_memo_json,
      )
    ),
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
  prompt_grid_rows = _blank_prompt_baseline_after_q1(grid_rows)
  governor_payload = build_governor_payload_from_context(
    business_name=str(business_name or "").strip(),
    ops_json=ops_json,
    target_market_json=target_market_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    fulfillment_json=fulfillment_json,
    marketing_model_json=marketing_model_json,
    model_input_json=model_input_json,
    finmo_json=finmo_json,
    realism_memo_json=normalize_realism_memo_payload(realism_memo_json),
    business_facts=business_facts or {},
  )
  source_row = {
    "business_name": str(business_name or "").strip(),
    "realism_memo_json": normalize_realism_memo_payload(realism_memo_json),
  }
  cash_constraint_contract = build_binding_cash_contract(
    source_row=source_row,
    governor_payload=governor_payload,
    grid_rows=prompt_grid_rows,
    planning_mode=normalized_mode,
  )
  authoritative_cash_bands: List[Dict[str, Any]] = []
  capital_allocation_target_rows = _capital_allocation_target_rows(grid_rows=grid_rows)
  capital_allocation_plan: Dict[str, Any] = {}
  authoritative_capital_rows: List[Dict[str, Any]] = []
  if cash_constraint_contract:
    authoritative_cash_bands = _derive_authoritative_cash_bands(
      contract=cash_constraint_contract,
      grid_rows=grid_rows,
    )
    if authoritative_cash_bands:
      cash_constraint_contract = dict(cash_constraint_contract)
      cash_constraint_contract["authoritative_cash_bands"] = _sanitize_canonical_live_payload(authoritative_cash_bands)
    governor_payload["cash_constraint_contract"] = _sanitize_canonical_live_payload(cash_constraint_contract)
  if capital_allocation_target_rows:
    capital_allocation_plan = build_capital_allocation_plan(
      source_row=source_row,
      governor_payload=governor_payload,
      target_rows=_blank_prompt_baseline_after_q1(capital_allocation_target_rows),
      planning_mode=normalized_mode,
    )
    authoritative_capital_rows = _normalize_capital_allocation_rows(
      plan=capital_allocation_plan,
      target_rows=capital_allocation_target_rows,
    )
    if authoritative_capital_rows:
      capital_allocation_plan = dict(capital_allocation_plan if isinstance(capital_allocation_plan, dict) else {})
      capital_allocation_plan["authoritative_rows"] = _sanitize_canonical_live_payload(authoritative_capital_rows)
      governor_payload["capital_allocation_plan"] = _sanitize_canonical_live_payload(capital_allocation_plan)
  planner_grid_rows = _planner_rows_for_grid_construction(
    grid_rows=grid_rows,
    authoritative_cash_bands=authoritative_cash_bands,
    authoritative_capital_rows=authoritative_capital_rows,
  )
  response_rows: List[Dict[str, Any]] = []
  batch_summaries: List[str] = []
  if capital_allocation_plan:
    batch_summaries.append(str(capital_allocation_plan.get("summary") or "Capital allocation rows planned.").strip())
  batches = chunk_quarter_grid_rows(planner_grid_rows, batch_size)
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
    response_rows.extend(batch_response.get("rows") if isinstance(batch_response.get("rows"), list) else [])
    batch_summaries.append(str(batch_response.get("summary") or f"Batch {batch_offset} completed."))
  runtime_seconds = round(time.perf_counter() - started, 3)
  response_json = {
    "summary": f"Completed {len(batches)} quarter-grid probe batches.",
    "rows": response_rows,
  }
  if cash_constraint_contract:
    response_json["cash_constraint_contract"] = _sanitize_canonical_live_payload(cash_constraint_contract)
  if capital_allocation_plan:
    response_json["capital_allocation_plan"] = _sanitize_canonical_live_payload(capital_allocation_plan)
  if authoritative_capital_rows:
    response_json = _apply_authoritative_rows(
      response_json=response_json,
      authoritative_rows=authoritative_capital_rows,
    )
  if cash_constraint_contract:
    cash_constraint_contract, authoritative_cash_bands, _q1_cash_anchor = _refresh_cash_contract_from_q1_anchor(
      contract=cash_constraint_contract,
      governor_payload=governor_payload,
      grid_rows=grid_rows,
      baseline_model_input_json=model_input_json,
      response_json=response_json,
    )
    response_json["cash_constraint_contract"] = _sanitize_canonical_live_payload(cash_constraint_contract)
  if authoritative_cash_bands:
    response_json = _apply_authoritative_cash_bands(
      response_json=response_json,
      authoritative_cash_bands=authoritative_cash_bands,
    )
  clip_result = _clip_shared_capacity_max_bands(
    response_json=response_json,
    ops_json=ops_json if isinstance(ops_json, dict) else {},
    financials_year1_json=financials_year1_json if isinstance(financials_year1_json, dict) else {},
  )
  response_json = clip_result.get("response_json") if isinstance(clip_result.get("response_json"), dict) else response_json
  shared_capacity_clips = clip_result.get("clips") if isinstance(clip_result.get("clips"), list) else []
  validation = validate_quarter_grid_response(
    requested_rows=grid_rows,
    response_json=response_json,
  )
  cash_contract_review = {
    "status": "pass",
    "summary": "No cash-constraint review required.",
    "reasons": [],
    "revision_instructions": "",
  }
  cash_contract_revision_attempts = 0
  if cash_constraint_contract:
    max_cash_contract_revisions = 2
    for attempt in range(max_cash_contract_revisions + 1):
      cash_contract_review = validate_binding_cash_contract(
        source_row=source_row,
        governor_payload=governor_payload,
        contract=cash_constraint_contract,
        grid_rows=prompt_grid_rows,
        response_json=response_json,
        planning_mode=normalized_mode,
      )
      if str(cash_contract_review.get("status") or "").strip().lower() == "pass":
        break
      if attempt >= max_cash_contract_revisions:
        break
      cash_contract_revision_attempts = attempt + 1
      revision_prompt = build_quarter_grid_prompt(
        source_row=source_row,
        grid_rows=planner_grid_rows,
        governor_payload=governor_payload,
        batch_index=1,
        batch_count=1,
        planning_mode=normalized_mode,
        revision_instructions=str(cash_contract_review.get("revision_instructions") or "").strip(),
      )
      revised_response = call_quarter_grid_openai(
        revision_prompt,
        allowed_row_ids=[str(item.get("row_id") or "") for item in planner_grid_rows],
        use_real_strategy_prompt=bool(use_real_strategy_prompt),
        planning_mode=normalized_mode,
        realism_memo_present=bool((source_row.get("realism_memo_json") or {}).get("issues")),
      )
      revised_rows = revised_response.get("rows") if isinstance(revised_response.get("rows"), list) else []
      response_json = {
        "summary": str(revised_response.get("summary") or f"Cash-contract revision {attempt + 1} completed.").strip(),
        "rows": revised_rows,
        "cash_constraint_contract": _sanitize_canonical_live_payload(cash_constraint_contract),
      }
      if capital_allocation_plan:
        response_json["capital_allocation_plan"] = _sanitize_canonical_live_payload(capital_allocation_plan)
      if authoritative_capital_rows:
        response_json = _apply_authoritative_rows(
          response_json=response_json,
          authoritative_rows=authoritative_capital_rows,
        )
      if cash_constraint_contract:
        cash_constraint_contract, authoritative_cash_bands, _q1_cash_anchor = _refresh_cash_contract_from_q1_anchor(
          contract=cash_constraint_contract,
          governor_payload=governor_payload,
          grid_rows=grid_rows,
          baseline_model_input_json=model_input_json,
          response_json=response_json,
        )
        response_json["cash_constraint_contract"] = _sanitize_canonical_live_payload(cash_constraint_contract)
      if authoritative_cash_bands:
        response_json = _apply_authoritative_cash_bands(
          response_json=response_json,
          authoritative_cash_bands=authoritative_cash_bands,
        )
      clip_result = _clip_shared_capacity_max_bands(
        response_json=response_json,
        ops_json=ops_json if isinstance(ops_json, dict) else {},
        financials_year1_json=financials_year1_json if isinstance(financials_year1_json, dict) else {},
      )
      response_json = clip_result.get("response_json") if isinstance(clip_result.get("response_json"), dict) else response_json
      shared_capacity_clips = clip_result.get("clips") if isinstance(clip_result.get("clips"), list) else []
      validation = validate_quarter_grid_response(
        requested_rows=grid_rows,
        response_json=response_json,
      )
      batch_summaries.append(
        str(cash_contract_review.get("summary") or f"Cash contract revision {attempt + 1} requested.").strip()
      )
    if str(cash_contract_review.get("status") or "").strip().lower() != "pass":
      reasons = [str(item or "").strip() for item in (cash_contract_review.get("reasons") or []) if str(item or "").strip()]
      detail = "; ".join(reasons[:6]) if reasons else str(cash_contract_review.get("summary") or "Cash contract validation failed.").strip()
      raise RuntimeError(f"Binding cash contract validation failed after {cash_contract_revision_attempts} revision attempts: {detail}")
  cash_pipeline_audit = _build_cash_pipeline_audit(
    contract=cash_constraint_contract if isinstance(cash_constraint_contract, dict) else {},
    authoritative_cash_bands=authoritative_cash_bands,
    authoritative_capital_rows=authoritative_capital_rows,
    planner_grid_rows=planner_grid_rows,
    response_json=response_json,
    cash_contract_review=cash_contract_review if isinstance(cash_contract_review, dict) else {},
  )
  if authoritative_cash_bands:
    if not bool(cash_pipeline_audit.get("planner_cash_row_omitted")):
      raise RuntimeError("Cash pipeline audit failed: Cash row was still sent to grid GPT despite authoritative cash bands.")
    if not bool(cash_pipeline_audit.get("final_cash_row_matches_authoritative")):
      raise RuntimeError(
        "Cash pipeline audit failed: Final Cash row does not match authoritative cash bands "
        f"for quarters {cash_pipeline_audit.get('final_cash_row_mismatch_quarters') or []}."
      )
    if not bool(cash_pipeline_audit.get("q1_anchor_present")) or not bool(cash_pipeline_audit.get("q1_band_matches_anchor")):
      raise RuntimeError("Cash pipeline audit failed: Q1 cash anchor was not derived and applied coherently.")
    if not bool(cash_pipeline_audit.get("q2_through_q20_chained")):
      raise RuntimeError(
        "Cash pipeline audit failed: Q2-Q20 cash bands are not chained coherently from the solved Q1 anchor "
        f"for quarters {cash_pipeline_audit.get('cash_chain_mismatch_quarters') or []}."
      )
  if authoritative_capital_rows and not bool(cash_pipeline_audit.get("planner_capital_rows_omitted")):
    raise RuntimeError("Capital allocation audit failed: capital-allocation rows were still sent to main grid GPT despite authoritative app-owned bands.")
  metadata = {
    "planning_mode": normalized_mode,
    "prompt_file": prompt_file,
    "runtime_seconds": runtime_seconds,
    "requested_row_count": validation.get("requested_row_count"),
    "returned_row_count": validation.get("returned_row_count"),
    "batch_count": len(batches),
    "batch_size": int(batch_size or 0),
    "batch_summaries": batch_summaries,
    "validation": {
      "missing_rows": list(validation.get("missing_rows") or []),
      "extra_rows": list(validation.get("extra_rows") or []),
      "duplicate_rows": list(validation.get("duplicate_rows") or []),
      "malformed_rows": list(validation.get("malformed_rows") or []),
      "flat_rows": list(validation.get("flat_rows") or []),
    },
    "shared_capacity_clips": list(shared_capacity_clips),
    "cash_constraint_contract": _sanitize_canonical_live_payload(cash_constraint_contract),
    "capital_allocation_plan": _sanitize_canonical_live_payload(capital_allocation_plan),
    "authoritative_capital_rows": _sanitize_canonical_live_payload(authoritative_capital_rows),
    "authoritative_cash_bands": _sanitize_canonical_live_payload(authoritative_cash_bands),
    "cash_contract_review": _sanitize_canonical_live_payload(cash_contract_review),
    "cash_pipeline_audit": _sanitize_canonical_live_payload(cash_pipeline_audit),
    "cash_contract_revision_attempts": int(cash_contract_revision_attempts),
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


def solve_live_quarter_grid_plan(
  *,
  baseline_model_input_json: Dict[str, Any],
  grid_json: Dict[str, Any],
  max_iterations: int = 300,
  movement_penalty_weight: float = 0.000001,
) -> Dict[str, Any]:
  try:
    from client_intake_and_finmo.finmo_bridge import build_python_finmo_json  # type: ignore
  except Exception:
    from finmo_bridge import build_python_finmo_json  # type: ignore

  baseline_inputs = FinancialModelInputs.from_model_input_json(
    baseline_model_input_json if isinstance(baseline_model_input_json, dict) else {}
  )
  controls = controls_from_quarter_grid(grid_json if isinstance(grid_json, dict) else {})
  targets = targets_from_quarter_grid(grid_json if isinstance(grid_json, dict) else {})
  result = solve_financial_model(
    baseline_inputs,
    controls=controls,
    targets=targets,
    options=SolverOptions(
      max_iterations=max(1, int(max_iterations)),
      movement_penalty_weight=float(movement_penalty_weight),
    ),
  )
  solved_model_input_json = result.solved_model_input_json if isinstance(result.solved_model_input_json, dict) else {}
  solved_finmo_json = build_python_finmo_json(model_input_json=solved_model_input_json)
  max_accounting_check = max(
    abs(float(row.get("accounting_equation_check") or 0.0))
    for row in (result.solved_outputs or [])
  ) if result.solved_outputs else 0.0
  solved_cash_band_audit = _solved_cash_band_audit(
    grid_json=grid_json if isinstance(grid_json, dict) else {},
    solved_outputs=result.solved_outputs or [],
  )
  solver_summary = {
    "success": bool(result.success),
    "objective_before": float(result.objective_before or 0.0),
    "objective_after": float(result.objective_after or 0.0),
    "target_constraints_satisfied": bool(getattr(result, "target_constraints_satisfied", False)),
    "max_target_violation": float(getattr(result, "max_target_violation", 0.0) or 0.0),
    "iterations": len(result.iterations or []),
    "control_count": len(controls),
    "target_count": len(targets),
    "accounting_equation_check_max_abs": float(max_accounting_check),
    "movement_penalty_weight": float(movement_penalty_weight),
    "target_center_weight": float(getattr(SolverOptions(), "target_center_weight", 1.0)),
    "max_iterations": int(max_iterations),
    "solved_cash_all_quarters_inside_bands": bool(solved_cash_band_audit.get("all_quarters_inside")),
    "solved_cash_band_mismatch_count": int(solved_cash_band_audit.get("mismatch_count") or 0),
    "solved_cash_band_mismatch_quarters": list(solved_cash_band_audit.get("mismatch_quarters") or []),
  }
  return {
    "solver_result": result,
    "controls": controls,
    "targets": targets,
    "solved_model_input_json": solved_model_input_json,
    "solved_finmo_json": solved_finmo_json,
    "solver_summary": solver_summary,
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


def _blank_prompt_baseline_after_q1(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
  scrubbed: List[Dict[str, Any]] = []
  for item in rows or []:
    if not isinstance(item, dict):
      continue
    next_item = dict(item)
    baseline_values = list(item.get("baseline_values") or [])
    if baseline_values:
      q1_value = baseline_values[0] if len(baseline_values) >= 1 else None
      next_item["baseline_values"] = [q1_value] + [None] * max(0, QUARTER_COUNT - 1)
    scrubbed.append(next_item)
  return scrubbed


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
              "quarter_bands": {
                "type": "array",
                "items": {
                  "type": "object",
                  "additionalProperties": False,
                  "properties": {
                    "quarter_index": {"type": "integer", "minimum": 1, "maximum": QUARTER_COUNT},
                    "min_value": {"type": "number"},
                    "max_value": {"type": "number"},
                  },
                  "required": ["quarter_index", "min_value", "max_value"],
                },
              },
            },
            "required": ["row_id", "row_type", "quarter_bands"],
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
    "Advisory realism memo:\n"
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
  revision_instructions: str = "",
) -> str:
  business_name = str(source_row.get("business_name") or "").strip() or "Unknown business"
  prompt_grid_rows = _blank_prompt_baseline_after_q1(grid_rows)
  row_descriptions = [f"- {item['row_id']} ({item['row_type']})" for item in prompt_grid_rows]
  realism_memo_block = _realism_memo_prompt_block(source_row)
  revision_block = ""
  if str(revision_instructions or "").strip():
    revision_block = (
      "Binding cash-contract revision instructions:\n"
      f"{str(revision_instructions or '').strip()}\n\n"
      "Revise the grid so it obeys those instructions while preserving realism and the same row set.\n\n"
    )
  return "".join(
    [
      f"You are building a quarter-by-quarter financial planning grid for {business_name}.\n",
      planning_mode_text(planning_mode),
      "\n",
      "Return a min/max band for every listed row and every quarter Q1 through Q20.\n",
      "Fill every box. Every listed row must have a min/max band in every quarter.\n",
      "Do not group periods. Do not omit rows. Do not invent rows.\n",
      "You must preserve every row_id exactly as given. Do not add suffixes, prefixes, labels, or parentheses.\n",
      "Every returned row must contain exactly 20 quarter_bands, one for each quarter_index from 1 to 20.\n",
      "For each quarter, min_value must be less than or equal to max_value.\n",
      "Every row-quarter cell is an active planning decision, not a placeholder carry-forward.\n",
      "Do not leave later-quarter cells on autopilot, and do not repeat Q1 or prior-quarter values by inertia.\n",
      "A row may stay similar or flat only when that is the deliberate realistic answer for that specific row and quarter.\n",
      "Rows may stay similar quarter to quarter when genuinely appropriate, but do not flatten the whole horizon into one repeated answer unless the business logic truly requires it.\n",
      "For output rows, use dollar values from Financial Model QTR semantics.\n",
      "For lever rows, use realistic model-input driver values.\n\n",
      "Quarter treatment:\n",
      "- Q1 is the most anchored forecast quarter and should usually stay closer to the business's real starting position unless the context clearly requires otherwise\n",
      "- Q2 through Q20 are fair game for material change when realism and the hard cash law require it\n",
      "- the displayed Q2 through Q20 row values are intentionally blank; do not infer hidden defaults from them\n",
      "- do not preserve flat spread-placeholder schedule rows just because intake started from one number\n",
      "- especially for discretionary deployment rows like capex, debt movement, and other schedule rows, do not treat flat placeholder values as recommendations to keep the row flat\n",
      "- realism means believable business behavior, not loyalty to a synthetic spread pattern\n\n",
      "Shared-capacity rule:\n",
      "- reason at the LOB and product level, not just row by row\n",
      "- when products inside the same LOB share one operating engine, treat that LOB's capacity as one conserved 100% pool\n",
      "- do not silently give every product in the same LOB full standalone service capacity\n",
      "- split that shared LOB capacity realistically across the products in the grid\n",
      "- your product breakout inside a shared LOB must fit within that one whole capacity pool rather than multiple independent pools\n",
      "- only treat product capacities as fully independent when the business context clearly supports separate operating capacity\n\n",
      "Profitability standard for this probe:\n",
      "- push toward profitability as early as realism allows\n",
      "- do not normalize persistent multi-year losses if a believable operating repair exists\n",
      "- use the full set of listed variables if needed to create a credible path\n",
      "- the resulting grid should read like a real company plan for this specific business and stage\n\n",
      "Cash-strategy handling:\n",
      "- if the governor context includes cash_strategy_context, treat it as a required planning differentiator and consistency dimension, not a throwaway note\n",
      "- do not override core business drivers like revenue realism or operating capacity, but do not confuse that with preserving synthetic placeholder-shaped discretionary rows in later quarters\n",
      "- if the governor context includes cash_constraint_contract, treat that cash constraint as binding during grid construction rather than advisory\n",
      "- if the governor context includes capital_allocation_plan, treat those app-owned capital-allocation rows as already planned and make the rest of the grid work coherently around them\n",
      "- when authoritative_cash_bands are present in the contract, those dollar cash bands are already fixed by the app and are the controlling Cash constraint for each quarter\n",
      "- when authoritative_cash_bands are present, the app may omit the Cash row from the listed rows because Cash is being supplied separately as a hard constraint\n",
      "- when authoritative capital-allocation rows are present in the governor context, the app may omit those rows from the listed rows because they are already being supplied separately as binding non-cash constraints\n",
      "- do not invent, reinterpret, or optimize the Cash row when authoritative_cash_bands are present; treat those fixed quarter-by-quarter dollar bands as the controlling Cash law and make the rest of the grid work around them\n",
      "- treat the authoritative cash bands as hard constraints during construction, not as suggestions to approximate later\n",
      "- your role is not to shape cash directly; your role is to make the non-cash grid work coherently under the hard cash law\n",
      "- your role is also not to reinvent app-owned capital-allocation rows when they are omitted; instead, make the remaining rows fit coherently around that capital-allocation plan\n",
      "- you may adjust any realistic lever in the grid if that is what it takes to satisfy the quarter-by-quarter Cash constraint while keeping the business believable\n",
      "- if the cash law requires meaningful deployment or absorption, you are expected to move discretionary non-cash rows materially after Q1 when that is what a believable business would do\n",
      "- the hard cash bands come from a sequential baby-AI path: the client cash seed is opening cash only, Q1 cash is app-supplied from a feasibility solve, and each later quarter is derived from the prior quarter; treat that sequential cash law as given\n",
      "- treat Q1 as a feasibility-owned anchor quarter, not as the main strategy-expression quarter for cash posture\n",
      "- the selected cash strategy should show up mainly from Q2 through Q20 in the surrounding non-cash grid decisions\n",
      "- use the contract's starting_cash_anchor as opening-cash context only, plus its quarter-to-quarter change guidance, reality guardrails, lever_freedom_rule, and non_overlap_rule, as grounding context for the surrounding grid choices\n",
      "- if a row choice conflicts with the binding cash_constraint_contract, revise the row choice so the grid obeys the contract rather than drifting away from it\n",
      "- make sure capex timing, hiring pace, marketing intensity, debt behavior, and any other relevant levers read like one coherent management posture under the hard cash law\n",
      "- do not treat capex, debt movement, or other discretionary schedule rows like maintenance bills that must remain near their spread placeholder unless the business reality truly requires that\n",
      "- do not let the four strategies collapse into only minor variants of the same plan; the selected strategy should materially shape the constrained non-cash grid, not just the wording in the summary\n",
      "- explicitly reflect that posture in the summary so the narrative explains how the selected cash strategy shows up in the plan\n",
      "- for reinvest, the non-cash grid should read like management is willing to fund credible growth under the imposed cash law\n",
      "- for preserve cash, the non-cash grid should read like management is more conservative and selective under the imposed cash law\n",
      "- for shareholder return, the non-cash grid should read like management is less willing to trap capital unnecessarily inside the business under the imposed cash law\n",
      "- for balanced, the non-cash grid should read like a middle path under the imposed cash law\n",
      "- use the existing levers to make that management posture believable rather than inventing new mechanics\n",
      "- do not treat any of the above as rigid rules; they are consistency expectations that must still respect realism, scale, and economics\n\n",
      realism_memo_block,
      revision_block,
      f"This is batch {batch_index} of {batch_count}. Return only the rows listed in this batch.\n\n",
      "Real governor context payload:\n",
      json.dumps(governor_payload, ensure_ascii=False),
      "\n\n",
      "Rows you must fill:\n",
      "\n".join(row_descriptions),
      "\n\nDisplayed Q1 row reference grid (later quarter values intentionally blank):\n",
      grid_markdown(prompt_grid_rows),
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
    "Use the actual business context and stage to create a realistic path.\n"
    "Treat Q1 as the most anchored forecast quarter, but treat Q2 through Q20 as fair game for realistic change when the business logic and hard cash law require it.\n"
    + realism_boundary
    + planning_mode_text(planning_mode)
    + "\n"
    "Express the result as min/max bands in the quarter grid."
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
    max_attempts=2,
  )
  if response.status_code >= 400:
    raise RuntimeError(f"OpenAI API error {response.status_code}: {response.text[:1200]}")
  return _parse_json_response(response.json())


def chunk_quarter_grid_rows(rows: List[Dict[str, Any]], batch_size: int) -> List[List[Dict[str, Any]]]:
  normalized_size = max(1, int(batch_size or 1))
  return [rows[index:index + normalized_size] for index in range(0, len(rows), normalized_size)]


def validate_quarter_grid_response(
  *,
  requested_rows: List[Dict[str, Any]],
  response_json: Dict[str, Any],
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
  for row_id, item in returned_by_id.items():
    quarter_bands = item.get("quarter_bands") if isinstance(item.get("quarter_bands"), list) else []
    if len(quarter_bands) != QUARTER_COUNT:
      malformed_rows.append(f"{row_id}::quarter_count={len(quarter_bands)}")
      continue
    seen_quarters = []
    identical_pairs = []
    for band in quarter_bands:
      if not isinstance(band, dict):
        malformed_rows.append(f"{row_id}::non_object_band")
        break
      quarter_index = int(band.get("quarter_index") or 0)
      minimum = float_or_none(band.get("min_value"))
      maximum = float_or_none(band.get("max_value"))
      if quarter_index < 1 or quarter_index > QUARTER_COUNT:
        malformed_rows.append(f"{row_id}::quarter={quarter_index}")
        break
      if minimum is None or maximum is None or minimum > maximum:
        malformed_rows.append(f"{row_id}::invalid_band::Q{quarter_index}")
        break
      seen_quarters.append(quarter_index)
      identical_pairs.append((round(minimum, 6), round(maximum, 6)))
    if sorted(seen_quarters) != list(range(1, QUARTER_COUNT + 1)):
      malformed_rows.append(f"{row_id}::quarter_indexes_invalid")
      continue
    if len(set(identical_pairs)) == 1:
      flat_rows.append(row_id)

  return {
    "requested_row_count": len(requested_rows),
    "returned_row_count": len(returned_by_id),
    "missing_rows": missing_rows,
    "extra_rows": extra_rows,
    "duplicate_rows": duplicates,
    "malformed_rows": malformed_rows,
    "flat_rows": flat_rows,
  }


def controls_from_quarter_grid(grid_json: Dict[str, Any]) -> List[LeverControl]:
  controls: List[LeverControl] = []
  for row in grid_json.get("rows") or []:
    if not isinstance(row, dict):
      continue
    if str(row.get("row_type") or "").strip().lower() != "lever":
      continue
    lever_id = str(row.get("row_id") or "").strip()
    if not lever_id:
      continue
    for band in row.get("quarter_bands") or []:
      if not isinstance(band, dict):
        continue
      quarter_index = int(band.get("quarter_index") or 0)
      if quarter_index < 1:
        continue
      controls.append(
        LeverControl(
          lever_id=lever_id,
          quarter_start=quarter_index,
          quarter_end=quarter_index,
          min_value=float_or_none(band.get("min_value")),
          max_value=float_or_none(band.get("max_value")),
        )
      )
  return controls


def targets_from_quarter_grid(grid_json: Dict[str, Any]) -> List[OutputTarget]:
  targets: List[OutputTarget] = []
  for row in grid_json.get("rows") or []:
    if not isinstance(row, dict):
      continue
    if str(row.get("row_type") or "").strip().lower() != "output":
      continue
    metric = str(row.get("row_id") or "").strip()
    if not metric:
      continue
    if metric != "Cash":
      continue
    for band in row.get("quarter_bands") or []:
      if not isinstance(band, dict):
        continue
      quarter_index = int(band.get("quarter_index") or 0)
      if quarter_index < 1:
        continue
      targets.append(
        OutputTarget(
          metric=metric,
          quarter_start=quarter_index,
          quarter_end=quarter_index,
          min_value=float_or_none(band.get("min_value")),
          max_value=float_or_none(band.get("max_value")),
        )
      )
  return targets
