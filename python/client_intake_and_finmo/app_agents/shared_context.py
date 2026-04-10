from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Sequence

from financial_model_engine.finmo_model import calculate_finmo_model
from financial_model_engine.model_inputs import FinancialModelInputs, QUARTER_COUNT

from .business_mechanics import build_business_mechanics_profile
from .version import APP_AGENTS_CONTRACT_VERSION, APP_AGENTS_PLANNER_VERSION

try:
  from client_intake_and_finmo.app_agents.solver_bridge import extract_solver_grid_rows, float_or_none  # type: ignore
except Exception:
  from app_agents.solver_bridge import extract_solver_grid_rows, float_or_none  # type: ignore


def _safe_float(value: Any) -> float:
  number = float_or_none(value)
  return float(number or 0.0)


def _text(value: Any) -> str:
  return str(value or "").strip()


def _normalize_business_profile(
  *,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
) -> Dict[str, Any]:
  ops = ops_json if isinstance(ops_json, dict) else {}
  facts = business_facts if isinstance(business_facts, dict) else {}
  return {
    "business_name": _text(facts.get("name") or ops.get("business_name")),
    "business_description": _text(ops.get("business_description")),
    "business_model": _text(ops.get("delivery_method") or ops.get("sales_channel") or ops.get("business_description")),
    "business_type": _text(ops.get("business_type") or ops.get("industry") or ops.get("business_description")),
    "legal_entity": _text(ops.get("legal_entity")),
    "geography": _text(ops.get("geography") or facts.get("address")),
    "business_stage": _text(ops.get("business_stage") or facts.get("stage")),
    "business_start_date": _text(facts.get("start_date")),
    "customer_type": _text(ops.get("customer_type")),
    "delivery_method": _text(ops.get("delivery_method")),
    "sales_channel": _text(ops.get("sales_channel")),
    "growth_lever": _text(ops.get("growth_lever")),
    "competitive_advantage": _text(ops.get("competitive_advantage")),
  }


def _strategy_map(cash_strategy: str) -> Dict[str, Any]:
  normalized = _text(cash_strategy).lower()
  options = {
    "reinvest": {
      "cash_strategy_value": "reinvest",
      "cash_strategy_label": "Reinvest",
      "strategy_intent_summary": "Put excess cash back into growth, capacity, hiring, expansion, or other believable reinvestment channels.",
      "strategy_visibility_expectations": [
        "cash should not just staircase upward with no meaningful deployment",
        "supporting rows should show credible redeployment behavior",
      ],
    },
    "preserve_cash": {
      "cash_strategy_value": "preserve_cash",
      "cash_strategy_label": "Preserve cash",
      "strategy_intent_summary": "Retain a thicker liquidity cushion and deploy capital more cautiously.",
      "strategy_visibility_expectations": [
        "cash buffers should remain visibly stronger",
        "deployment should be more measured than reinvest",
      ],
    },
    "shareholder_return": {
      "cash_strategy_value": "shareholder_return",
      "cash_strategy_label": "Shareholder return",
      "strategy_intent_summary": "Avoid trapping excess cash indefinitely and allow believable extraction or non-retention behavior.",
      "strategy_visibility_expectations": [
        "cash should not pile up forever without reason",
        "supporting rows should reflect extraction or reduced retention posture",
      ],
    },
    "balanced": {
      "cash_strategy_value": "balanced",
      "cash_strategy_label": "Balanced",
      "strategy_intent_summary": "Blend retention and selective reinvestment rather than maximizing either extreme.",
      "strategy_visibility_expectations": [
        "some retained cushion should remain visible",
        "some selective deployment should also remain visible",
      ],
    },
  }
  return copy.deepcopy(options.get(normalized) or {
    "cash_strategy_value": normalized or "unknown",
    "cash_strategy_label": _text(cash_strategy) or "Unknown",
    "strategy_intent_summary": "",
    "strategy_visibility_expectations": [],
  })


def _build_strategy_profile(
  *,
  financials_json: Dict[str, Any],
  ops_json: Dict[str, Any],
) -> Dict[str, Any]:
  financials = financials_json if isinstance(financials_json, dict) else {}
  strategy = _strategy_map(_text(financials.get("cash_strategy")))
  strategy["goal_summary"] = _text(ops_json.get("goal_12_months"))
  return strategy


def _baseline_summary_from_finmo_json(finmo_json: Dict[str, Any]) -> Dict[str, Any]:
  rows = [
    item for item in ((finmo_json.get("quarter_rows") or []) if isinstance(finmo_json, dict) else [])
    if isinstance(item, dict) and int(item.get("quarter_index") or 0) >= 1
  ]
  first_year = rows[:4]
  if not first_year:
    return {}
  return {
    "revenue": sum(_safe_float(item.get("revenue")) for item in first_year),
    "cogs": sum(_safe_float(item.get("cost_of_goods_sold")) for item in first_year),
    "gross_profit": sum(_safe_float(item.get("gross_profit")) for item in first_year),
    "payroll": sum(_safe_float(item.get("payroll")) for item in first_year),
    "marketing": sum(_safe_float(item.get("marketing")) for item in first_year),
    "ebitda": sum(_safe_float(item.get("ebitda")) for item in first_year),
    "net_income": sum(_safe_float(item.get("net_income")) for item in first_year),
    "ending_cash_q4": _safe_float(first_year[-1].get("ending_cash")) if first_year else 0.0,
  }


def _opening_balance_seeds(model_input_json: Dict[str, Any]) -> Dict[str, float]:
  sections = model_input_json.get("sections") if isinstance(model_input_json.get("sections"), dict) else {}
  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  keys = (
    "debt_opening_balance_seed",
    "lease_opening_balance_seed",
    "ppe_opening_balance_seed",
    "accumulated_depreciation_opening_seed",
    "cash_opening_balance_seed",
    "accounts_receivable_opening_balance_seed",
    "inventory_opening_balance_seed",
    "accounts_payable_opening_balance_seed",
    "short_term_debt_opening_balance_seed",
  )
  return {key: _safe_float(schedules.get(key)) for key in keys}


def _row_semantics(row_id: str, section: str, label: str) -> str:
  lever_id = _text(row_id)
  lowered = f"{lever_id} {label}".lower()
  if section == "revenue":
    if "capacity" in lowered:
      return "Revenue capacity driver. Shapes throughput envelope and often interacts with staffing or facilities."
    if "utilization" in lowered:
      return "Revenue utilization driver. Converts available capacity into used capacity."
    if "unit price" in lowered or "price" in lowered:
      return "Revenue pricing driver. Affects revenue quality and realism."
    return "Revenue driver row."
  if "capital expenditures" in lowered or "capex" in lowered or "ppe" in lowered:
    return "Capital deployment row. Can express equipment, facility, or expansion investment when realistic."
  if "owner" in lowered or "equity" in lowered:
    return "Equity or owner capital row. Can express injections, retention, or extraction depending on business reality."
  if "principal" in lowered or "debt" in lowered:
    return "Debt behavior row. Can express financing, deleveraging, or liquidity posture."
  if "payroll" in lowered:
    return "Labor cost row. Critical for operating realism, staffing support, and growth absorption."
  if "marketing" in lowered:
    return "Demand generation row. Supports acquisition and growth when business model depends on it."
  if "receivable" in lowered or "payable" in lowered or "inventory" in lowered or "prepaid" in lowered or "deferred" in lowered:
    return "Working-capital timing row. Shapes cash conversion and liquidity timing."
  if section == "output":
    return "Output row consumed by the solver as a target band."
  return "Planner-controlled financial row."


def _row_flags(row_id: str, section: str, label: str) -> Dict[str, bool]:
  lowered = f"{row_id} {label}".lower()
  return {
    "capital_allocation_relevant": any(token in lowered for token in ("capex", "capital expenditures", "equity", "owner", "debt", "principal", "cash")),
    "shared_capacity_relevant": section == "revenue" and any(token in lowered for token in ("capacity", "utilization")),
  }


def _build_row_catalog(
  *,
  model_input_json: Dict[str, Any],
  baseline_outputs: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  rows = extract_solver_grid_rows(
    model_input_json=model_input_json if isinstance(model_input_json, dict) else {},
    baseline_outputs=list(baseline_outputs or []),
  )
  catalog: List[Dict[str, Any]] = []
  for row in rows:
    row_id = _text(row.get("row_id"))
    section = _text(row.get("section"))
    label = _text(row.get("label") or row_id)
    flags = _row_flags(row_id, section, label)
    catalog.append(
      {
        "row_id": row_id,
        "row_type": _text(row.get("row_type")),
        "section": section,
        "label": label,
        "baseline_values": list(row.get("baseline_values") or [])[:QUARTER_COUNT],
        "row_semantics": _row_semantics(row_id, section, label),
        **flags,
      }
    )
  return catalog


def default_planner_invariants() -> List[str]:
  return [
    "Do not change solver logic.",
    "Do not change row ids.",
    "Do not change row meanings.",
    "Do not change quarter count.",
    "Do not change min/max band semantics.",
    "Do not depend on legacy planner infrastructure such as realism memo.",
  ]


def default_external_business_reasoning_requirements() -> List[str]:
  return [
    "Reason from business model and business type, not only local SQL or stored facts.",
    "Use real-world operating knowledge for what this type of business can plausibly do.",
    "Use real-world capital allocation knowledge for the selected cash strategy.",
    "Maintain realism, row coherence, and visible strategy expression together.",
  ]


def build_shared_context(
  *,
  draft_id: str,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  target_market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]],
  fulfillment_json: Optional[Dict[str, Any]],
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
) -> Dict[str, Any]:
  baseline_inputs = FinancialModelInputs.from_model_input_json(model_input_json if isinstance(model_input_json, dict) else {})
  try:
    baseline_outputs = calculate_finmo_model(baseline_inputs).quarter_rows()
  except Exception:
    baseline_outputs = []
  business_profile = _normalize_business_profile(
    business_facts=business_facts if isinstance(business_facts, dict) else {},
    ops_json=ops_json if isinstance(ops_json, dict) else {},
  )
  strategy_profile = _build_strategy_profile(
    financials_json=financials_json if isinstance(financials_json, dict) else {},
    ops_json=ops_json if isinstance(ops_json, dict) else {},
  )
  baseline_summary = _baseline_summary_from_finmo_json(finmo_json if isinstance(finmo_json, dict) else {})
  row_catalog = _build_row_catalog(
    model_input_json=model_input_json if isinstance(model_input_json, dict) else {},
    baseline_outputs=baseline_outputs,
  )
  return {
    "contract": {
      "contract_version": APP_AGENTS_CONTRACT_VERSION,
      "planner_version": APP_AGENTS_PLANNER_VERSION,
      "recorded_at": "",
      "draft_id": _text(draft_id),
      "business_name": _text(business_profile.get("business_name")),
    },
    "business_profile": business_profile,
    "strategy_profile": strategy_profile,
    "intake_context": {
      "ops_json": copy.deepcopy(ops_json or {}),
      "target_market_json": copy.deepcopy(target_market_json or {}),
      "people_json": copy.deepcopy(people_json or {}),
      "financials_json": copy.deepcopy(financials_json or {}),
      "financials_year1_json": copy.deepcopy(financials_year1_json or {}),
      "marketing_model_json": copy.deepcopy(marketing_model_json or {}),
      "fulfillment_json": copy.deepcopy(fulfillment_json or {}),
      "business_facts": copy.deepcopy(business_facts or {}),
    },
    "financial_baseline": {
      "model_input_json": copy.deepcopy(model_input_json or {}),
      "finmo_json": copy.deepcopy(finmo_json or {}),
      "baseline_summary": baseline_summary,
      "opening_balance_seeds": _opening_balance_seeds(model_input_json if isinstance(model_input_json, dict) else {}),
    },
    "row_catalog": row_catalog,
    "business_mechanics": build_business_mechanics_profile(
      business_profile=business_profile,
      strategy_profile=strategy_profile,
      ops_json=ops_json if isinstance(ops_json, dict) else {},
      financials_json=financials_json if isinstance(financials_json, dict) else {},
      baseline_summary=baseline_summary,
      row_catalog=row_catalog,
    ),
    "planner_invariants": default_planner_invariants(),
    "external_business_reasoning_requirements": default_external_business_reasoning_requirements(),
  }
