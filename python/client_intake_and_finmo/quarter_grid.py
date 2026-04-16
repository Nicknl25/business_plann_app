from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import requests
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
  del kind
  return None


def _post_openai(
  *,
  url: str,
  headers: Dict[str, str],
  payload: Dict[str, Any],
  timeout_seconds: Optional[int] = None,
  max_attempts: int = 3,
) -> requests.Response:
  timeout = timeout_seconds if timeout_seconds is not None else _openai_timeout_seconds()
  attempts = max(1, int(max_attempts or 1))
  last_exc: Optional[Exception] = None
  for attempt in range(attempts):
    try:
      resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
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
  strategy = str(financials.get("cash_strategy") or "").strip().lower()
  option_map = {
    "reinvest": {
      "value": "reinvest",
      "label": "Reinvest",
      "description": "The client would generally prefer extra cash to be put back into growth, capacity, or expansion when that is realistic.",
      "capital_allocation_posture": "Favor staged redeployment of excess cash into credible growth needs instead of leaving cash to build smoothly with no use.",
      "timing_expectation": "If the business economics support it, reflect periods of cash buildup followed by realistic deployment through existing planning choices such as hiring pace, capex timing, marketing intensity, or debt behavior.",
      "alignment_test": "A reinvest plan should not read like management is simply hoarding cash while also claiming to prioritize growth.",
      "visual_goal": "The grid and resulting cash path should usually show some visible redeployment behavior rather than a perfectly smooth cash staircase.",
    },
    "preserve_cash": {
      "value": "preserve_cash",
      "label": "Preserve cash",
      "description": "The client would generally prefer a thicker cash cushion and a more conservative liquidity posture.",
      "capital_allocation_posture": "Favor retaining more liquidity and deploying capital more cautiously unless the operating case clearly justifies faster use of cash.",
      "timing_expectation": "Let cash cushions build earlier and keep deployment pacing more measured across capex, hiring, marketing, and debt choices.",
      "alignment_test": "A preserve-cash plan should not look overly aggressive in capital deployment while still claiming a conservative cash posture.",
      "visual_goal": "The grid and resulting cash path should usually show stronger retained buffers and fewer sharp deployments than a reinvest case.",
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
      "description": "The client wants a mix of cash preservation and selective reinvestment rather than pushing to either extreme.",
      "capital_allocation_posture": "Blend healthy retained liquidity with selective reinvestment when the business case is strong.",
      "timing_expectation": "Allow some buildup and some deployment, but keep both the narrative and the grid from leaning too far toward hoarding or aggressive redeployment.",
      "alignment_test": "A balanced plan should not collapse into an extreme cash-hoarding or extreme redeployment posture without a strong business reason.",
      "visual_goal": "The grid and resulting cash path should sit between preserve-cash and reinvest behavior, with visible but measured deployment of excess cash.",
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
) -> Dict[str, Any]:
  del target_market_json, people_json, fulfillment_json, marketing_model_json, business_facts
  baseline_summary = _baseline_summary_from_finmo_json(finmo_json) or _build_baseline_financial_summary(
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
  )
  cash_strategy_context = _cash_strategy_context(financials_json)
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
    )
    repaired_batch_response = repair_quarter_grid_response(
      requested_rows=batch_rows,
      response_json=batch_response if isinstance(batch_response, dict) else {},
    )
    repaired_batch_validation = validate_quarter_grid_response(
      requested_rows=batch_rows,
      response_json=repaired_batch_response,
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
  )
  response_json = repair_quarter_grid_response(
    requested_rows=grid_rows,
    response_json=raw_response_json,
  )
  validation = validate_quarter_grid_response(
    requested_rows=grid_rows,
    response_json=response_json,
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
  next_model_input = json.loads(json.dumps(model_input_json if isinstance(model_input_json, dict) else {}))
  lever_rows = _lever_row_map(next_model_input)
  for update in exact_updates:
    if not isinstance(update, dict):
      continue
    lever_id = str(update.get("lever_id") or "").strip()
    quarter_index = int(update.get("quarter_index") or 0)
    value = float_or_none(update.get("exact_value"))
    row = lever_rows.get(lever_id)
    if not lever_id or row is None or value is None or quarter_index < 1 or quarter_index > QUARTER_COUNT:
      continue
    values = list(row.get("values") or [])
    has_stub = len(values) >= QUARTER_COUNT + 1
    target_length = QUARTER_COUNT + 1 if has_stub else QUARTER_COUNT
    if len(values) < target_length:
      values.extend([0.0 for _ in range(target_length - len(values))])
    row["values"] = values[:target_length]
    row["values"][quarter_index if has_stub else quarter_index - 1] = round(float(value), 6)
  return next_model_input


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
      "Rows may stay similar quarter to quarter when genuinely appropriate, but do not flatten the whole horizon into one repeated answer unless the business logic truly requires it.\n",
      "For output rows, use dollar values from Financial Model QTR semantics.\n",
      "For lever rows, use realistic model-input driver values.\n\n",
      "Shared-capacity rule:\n",
      "- reason at the LOB and product level, not just row by row\n",
      "- when products inside the same LOB share one operating engine, treat that LOB's capacity as one conserved 100% pool\n",
      "- do not silently give every product in the same LOB full standalone service capacity\n",
      "- split that shared LOB capacity realistically across the products in the grid\n",
      "- your product breakout inside a shared LOB must fit within that one whole capacity pool rather than multiple independent pools\n",
      "- only treat product capacities as fully independent when the business context clearly supports separate operating capacity\n\n",
      "Important financing and equity row meanings:\n",
      "- `schedules::Plus: Additions (repayments), net` = debt draws or debt repayments\n",
      "- `schedules::Capital Expenditures` = cash capex / PPE spend\n",
      "- `schedules::Less: Principal Repayments` = capital lease principal repayments\n",
      "- `schedules::Plus: Net Additions` = capital lease additions only, not owner draws, not generic financing\n",
      "- `balance_sheet::Owner's Capital` = owner or partner capital contributions in only\n",
      "- `balance_sheet::Distributions` = owner or partner payouts out only; use this for owner cash returns, not Owner's Capital\n",
      "- `balance_sheet::Other Equity` = other equity in/out\n\n",
      "Profitability standard for this probe:\n",
      "- push toward profitability as early as realism allows\n",
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
      "- for reinvest, if the economics support it, do not let excess cash simply rise smoothly with no believable redeployment path\n",
      "- for preserve cash, keep a visibly more conservative liquidity posture and avoid overly eager cash deployment\n",
      "- for shareholder return, avoid letting excess cash pile up indefinitely without a believable reason to retain it\n",
      "- for balanced, show a middle path with some retained cushion and some selective deployment\n",
      "- do not treat any of the above as rigid rules; they are planning expectations that must still respect realism and economics\n\n",
      realism_memo_block,
      f"This is batch {batch_index} of {batch_count}. Return only the rows listed in this batch.\n\n",
      "Real governor context payload:\n",
      json.dumps(governor_payload, ensure_ascii=False),
      "\n\n",
      "Rows you must fill:\n",
      "\n".join(
        [
          f"- {item['row_id']} ({item['row_type']}) :: {str(item.get('label') or item['row_id'])}"
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
}
