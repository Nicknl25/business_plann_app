import copy
import hashlib
import json
import math
import os
import re
import time
import calendar
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_CONVERGENCE_DEFAULT_QUARTER_COUNT = 20
_CONVERGENCE_MAX_FOCUS_LEVERS = 12
_CONVERGENCE_MAX_FOCUS_LEVER_FAMILIES = 3
_CONVERGENCE_MAX_FOCUS_DRIVER_PATHS = 12
_CONVERGENCE_MAX_FOCUS_METRICS_PER_ISSUE = 2
_CONVERGENCE_PROMPT_METRIC_PACKET_LIMIT = 10
_CONVERGENCE_PROMPT_LEVER_PACKET_LIMIT = 12
_CONVERGENCE_MEANINGFUL_SCORE_DELTA_PCT = 5.0
_UNIFIED_ACCOUNTING_EQUATION_TOLERANCE = 1.0
_UNIFIED_CATASTROPHIC_LIQUIDITY_FLOOR = -250000.0
_UNIFIED_CONVERGENCE_ACTIVE_ISSUE_LIMIT = 1
_UNIFIED_CONVERGENCE_ACTIVE_QUARTER_LIMIT = 20
_UNIFIED_ALLOWED_TARGET_METRIC_KEYS: Tuple[str, ...] = tuple()
_UNIFIED_PRIMARY_TARGET_MIN_COUNT = 1
_UNIFIED_PRIMARY_TARGET_MAX_COUNT = 6
_UNIFIED_EXPLICIT_CAPITAL_ALLOCATION_LEVER_IDS: Tuple[str, ...] = tuple()
_CASH_PASS_OWNED_ISSUE_CODES = {"liquidity_failure", "working_capital_mismatch", "funding_structure_mismatch"}
_CASH_STRATEGY_FUNDING_SOURCE_LEVER_IDS: Tuple[str, ...] = tuple()
_UNIFIED_CONVERGENCE_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts" / "unified_convergence"
_UNIFIED_CONVERGENCE_PROMPT_PATH = _UNIFIED_CONVERGENCE_PROMPTS_DIR / "reviewer.md"


def bind_runtime_dependencies(dependencies: Dict[str, Any]) -> None:
  if not isinstance(dependencies, dict):
    return
  globals().update({
    key: value
    for key, value in dependencies.items()
    if key != "bind_runtime_dependencies"
  })


__all__ = [
  "_financial_story_live_quarter_rows",
  "_financial_story_series",
  "_financial_story_average",
  "_financial_story_window",
  "_financial_story_window_sum",
  "_financial_story_ratio",
  "_financial_story_window_ratio",
  "_financial_story_compact_currency",
  "_financial_story_percent",
  "_financial_story_multiple",
  "_financial_story_trim",
  "_financial_story_days",
  "_financial_story_average_days",
  "_build_financial_story_payload",
  "_build_unified_horizon_snapshot",
  "_build_unified_hard_rule_assessment",
  "_build_unified_convergence_context_payload",
  "_load_unified_convergence_prompt",
  "_planning_mode_prompt_text",
  "_build_planning_mode_context",
  "_truncate_summary_text",
  "_compact_summary_value",
  "_compact_summary_section",
  "_build_planning_context_summary_payload",
  "_persist_unified_convergence_state",
  "_parse_responses_json_dict",
  "_openai_strict_json_schema",
  "_compact_convergence_quarter_rows_for_state",
  "_build_current_cycle_convergence_packet",
  "_lever_allowed_mapped_repair_targets",
  "_run_unified_convergence_openai",
  "_quarter_count_from_model_input",
  "_normalized_quarter_window",
  "_solved_lever_value_map",
  "_solved_lever_stub_value_map",
  "_lever_review_catalog_entry_map",
  "_payroll_row_from_model_input",
  "_subset_lever_value_map",
  "_finmo_rows_for_quarters",
  "_window_values",
  "_baseline_window_summary",
  "_translate_unified_convergence_adjustment",
  "_scoped_unified_allowed_lever_ids",
  "_build_unified_convergence_pass_plan",
  "_shape_sensitive_trajectory_values_schema",
  "_shape_sensitive_trajectory_values_by_quarter",
  "_shape_sensitive_trajectory_error_code",
  "_shape_sensitive_path_validation_detail",
  "_shape_sensitive_path_validation_error",
  "_baseline_map_quarter_count",
  "_deterministic_lever_bound_lookup",
  "_lever_family_from_lever_id",
  "_raise_negative_net_income_if_needed",
  "_sum_series",
  "_model_input_revenue_driver_quarter_states",
  "_growth_supported_by_capacity_or_utilization",
  "_allowed_stage_growth_result",
  "_operating_trajectory_allowed_levers",
  "_series_longest_flat_run",
  "_raise_unified_convergence_cycle_timeout_if_needed",
  "_raise_unified_convergence_stage_budget_if_needed",
  "_mark_unified_convergence_cycle_phase",
  "get_runtime_probe_payload",
  "_convergence_test_mode_enabled",
  "_handle_convergence_test_mode_failure",
  "_build_convergence_progress_failure_diagnostics",
  "_build_unified_cycle_stall_assessment",
]


def _financial_story_live_quarter_rows(finmo_payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  finmo_obj = finmo_payload if isinstance(finmo_payload, dict) else {}
  quarter_rows = [row for row in (finmo_obj.get("quarter_rows") or []) if isinstance(row, dict)]
  return [row for row in quarter_rows if int(float(row.get("quarter_index") or 0)) >= 1]

def _financial_story_series(rows: List[Dict[str, Any]], key: str) -> List[float]:
  return [float(_safe_float(row.get(key)) or 0.0) for row in rows]

def _financial_story_average(values: List[float]) -> float:
  if not values:
    return 0.0
  return float(sum(values) / len(values))

def _financial_story_window(values: List[float], *, count: int = 4, tail: bool = False) -> List[float]:
  if count <= 0:
    return []
  return list(values[-count:] if tail else values[:count])

def _financial_story_window_sum(values: List[float], *, count: int = 4, tail: bool = False) -> float:
  return float(sum(_financial_story_window(values, count=count, tail=tail)))

def _financial_story_ratio(numerator: float, denominator: float) -> float:
  if abs(float(denominator)) <= 1e-9:
    return 0.0
  return float(numerator) / float(denominator)

def _financial_story_window_ratio(
  numerator_series: List[float],
  denominator_series: List[float],
  *,
  count: int = 4,
  tail: bool = False,
) -> float:
  numerator = _financial_story_window_sum(numerator_series, count=count, tail=tail)
  denominator = _financial_story_window_sum(denominator_series, count=count, tail=tail)
  return _financial_story_ratio(numerator, denominator)

def _financial_story_compact_currency(value: Any) -> str:
  amount = float(_safe_float(value) or 0.0)
  sign = "-" if amount < 0 else ""
  magnitude = abs(amount)
  if magnitude >= 1_000_000_000:
    return f"{sign}${magnitude / 1_000_000_000:.1f}B"
  if magnitude >= 1_000_000:
    return f"{sign}${magnitude / 1_000_000:.1f}M"
  if magnitude >= 1_000:
    return f"{sign}${magnitude / 1_000:.1f}K"
  return f"{sign}${magnitude:,.0f}"

def _financial_story_percent(value: Any, *, digits: int = 1) -> str:
  ratio = float(_safe_float(value) or 0.0)
  return f"{ratio * 100:.{digits}f}%"

def _financial_story_multiple(value: Any, *, digits: int = 1) -> str:
  multiple = _safe_float(value)
  if multiple is None or not math.isfinite(float(multiple)):
    return "n/a"
  return f"{float(multiple):.{digits}f}x"

def _financial_story_trim(text: Any, *, max_chars: int) -> str:
  collapsed = re.sub(r"\s+", " ", str(text or "")).strip()
  if len(collapsed) <= max_chars:
    return collapsed
  trimmed = collapsed[: max_chars - 1].rstrip(" ,;:-")
  last_break = max(trimmed.rfind(". "), trimmed.rfind("; "), trimmed.rfind(", "))
  if last_break >= max_chars // 2:
    trimmed = trimmed[:last_break].rstrip(" ,;:-.")
  return f"{trimmed}."

def _financial_story_days(balance_value: Any, flow_value: Any, days_in_quarter: Any) -> Optional[float]:
  balance = _safe_float(balance_value)
  flow = _safe_float(flow_value)
  days = _safe_float(days_in_quarter)
  if balance is None or flow is None or days is None:
    return None
  if abs(float(flow)) <= 1e-9 or float(days) <= 0:
    return None
  return float(balance) / abs(float(flow)) * float(days)

def _financial_story_average_days(
  rows: List[Dict[str, Any]],
  *,
  balance_key: str,
  flow_key: str,
) -> float:
  values: List[float] = []
  for row in rows:
    day_value = _financial_story_days(
      row.get(balance_key),
      row.get(flow_key),
      row.get("days_in_quarter"),
    )
    if day_value is None or not math.isfinite(day_value):
      continue
    values.append(float(day_value))
  return _financial_story_average(values)

def _build_financial_story_payload(
  *,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  target_market_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  planning_context_summary_json: Optional[Dict[str, Any]],
  current_finmo_json: Optional[Dict[str, Any]],
  controller_resolution_state: Optional[Dict[str, Any]],
  hard_rule_assessment: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  business = business_facts if isinstance(business_facts, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  market = target_market_json if isinstance(target_market_json, dict) else {}
  financials = financials_json if isinstance(financials_json, dict) else {}
  planning_context = planning_context_summary_json if isinstance(planning_context_summary_json, dict) else {}
  hard_rules = hard_rule_assessment if isinstance(hard_rule_assessment, dict) else {}
  rows = _financial_story_live_quarter_rows(current_finmo_json)

  business_name = (
    str(business.get("name") or business.get("business_name") or planning_context.get("business_name") or "").strip()
    or "The business"
  )
  business_type = (
    str(ops.get("business_type") or ((planning_context.get("operating_profile") or {}) if isinstance(planning_context.get("operating_profile"), dict) else {}).get("business_type") or "").strip()
    or "operating business"
  )
  unit_name = (
    str(ops.get("unit_name") or ((planning_context.get("operating_profile") or {}) if isinstance(planning_context.get("operating_profile"), dict) else {}).get("unit_name") or "unit").strip()
    or "unit"
  )
  unit_price = _safe_float(
    ops.get("unit_price")
    if ops.get("unit_price") is not None
    else ((planning_context.get("operating_profile") or {}) if isinstance(planning_context.get("operating_profile"), dict) else {}).get("unit_price")
  )
  weekly_capacity = _safe_float(
    ops.get("units_per_week_capacity")
    if ops.get("units_per_week_capacity") is not None
    else ((planning_context.get("operating_profile") or {}) if isinstance(planning_context.get("operating_profile"), dict) else {}).get("units_per_week_capacity")
  )
  utilization = _safe_float(
    ops.get("utilization_rate")
    if ops.get("utilization_rate") is not None
    else ((planning_context.get("operating_profile") or {}) if isinstance(planning_context.get("operating_profile"), dict) else {}).get("utilization_rate")
  )
  capacity_driver = str(ops.get("capacity_driver") or "").strip() or "operating throughput"
  shipping_method = str(ops.get("shipping_method") or "").strip()
  primary_growth_lever = str(ops.get("primary_growth_lever") or "").strip() or "repeat volume growth"
  cash_strategy = (
    str(financials.get("cash_strategy") or planning_context.get("selected_cash_strategy") or "").strip()
    or "balanced"
  )
  marketing_summary = str(market.get("marketing_plan_summary") or "").strip()
  market_focus = ", ".join(
    [str(item or "").strip() for item in (market.get("b2b_industry_terms") or []) if str(item or "").strip()][:3]
  )

  revenue_series = _financial_story_series(rows, "revenue")
  gross_profit_series = _financial_story_series(rows, "gross_profit")
  cogs_series = _financial_story_series(rows, "cogs")
  ebitda_series = _financial_story_series(rows, "ebitda")
  net_income_series = _financial_story_series(rows, "net_income")
  operating_cash_flow_series = _financial_story_series(rows, "operating_cash_flow")
  ending_cash_series = _financial_story_series(rows, "ending_cash")
  marketing_series = _financial_story_series(rows, "marketing")
  payroll_series = _financial_story_series(rows, "payroll")
  g_and_a_series = _financial_story_series(rows, "g_and_a")
  lease_rent_series = _financial_story_series(rows, "lease_rent")
  capital_expenditure_series = _financial_story_series(rows, "capital_expenditures")
  ppe_series = _financial_story_series(rows, "ppe")
  current_assets_series = _financial_story_series(rows, "current_assets")
  current_liabilities_series = _financial_story_series(rows, "current_liabilities")
  accounts_receivable_series = _financial_story_series(rows, "accounts_receivable")
  inventory_series = _financial_story_series(rows, "inventory")
  accounts_payable_series = _financial_story_series(rows, "accounts_payable")
  long_term_debt_series = _financial_story_series(rows, "long_term_debt")
  short_term_debt_series = _financial_story_series(rows, "short_term_debt")
  owners_capital_series = _financial_story_series(rows, "owners_capital")
  other_equity_series = _financial_story_series(rows, "other_equity")
  total_equity_series = _financial_story_series(rows, "total_equity")
  interest_series = _financial_story_series(rows, "interest")

  quarter_count = len(rows)
  first_year_revenue = _financial_story_window_sum(revenue_series, count=4, tail=False)
  final_year_revenue = _financial_story_window_sum(revenue_series, count=4, tail=True)
  first_year_ebitda = _financial_story_window_sum(ebitda_series, count=4, tail=False)
  final_year_ebitda = _financial_story_window_sum(ebitda_series, count=4, tail=True)
  first_year_operating_cash = _financial_story_window_sum(operating_cash_flow_series, count=4, tail=False)
  final_year_operating_cash = _financial_story_window_sum(operating_cash_flow_series, count=4, tail=True)
  final_cash = ending_cash_series[-1] if ending_cash_series else 0.0
  minimum_cash = min(ending_cash_series) if ending_cash_series else 0.0
  peak_cash = max(ending_cash_series) if ending_cash_series else 0.0
  final_ppe = ppe_series[-1] if ppe_series else 0.0
  total_capex = float(sum(capital_expenditure_series))
  early_capex = _financial_story_window_sum(capital_expenditure_series, count=4, tail=False)
  late_capex = _financial_story_window_sum(capital_expenditure_series, count=4, tail=True)
  final_total_debt = (long_term_debt_series[-1] if long_term_debt_series else 0.0) + (short_term_debt_series[-1] if short_term_debt_series else 0.0)
  peak_total_debt = max(
    [
      lt + st
      for lt, st in zip(
        long_term_debt_series or [0.0] * max(1, quarter_count),
        short_term_debt_series or [0.0] * max(1, quarter_count),
      )
    ]
  ) if quarter_count else 0.0
  trailing_interest = _financial_story_window_sum(interest_series, count=4, tail=True)
  trailing_ebitda = final_year_ebitda
  interest_coverage = (
    _financial_story_ratio(trailing_ebitda, trailing_interest)
    if abs(trailing_interest) > 1e-9
    else None
  )
  leverage_ratio = (
    _financial_story_ratio(final_total_debt, trailing_ebitda)
    if abs(trailing_ebitda) > 1e-9
    else None
  )
  gross_margin_early = _financial_story_window_ratio(gross_profit_series, revenue_series, count=4, tail=False)
  gross_margin_late = _financial_story_window_ratio(gross_profit_series, revenue_series, count=4, tail=True)
  ebitda_margin_early = _financial_story_window_ratio(ebitda_series, revenue_series, count=4, tail=False)
  ebitda_margin_late = _financial_story_window_ratio(ebitda_series, revenue_series, count=4, tail=True)
  cogs_percent = _financial_story_ratio(sum(cogs_series), sum(revenue_series))
  payroll_percent = _financial_story_ratio(sum(payroll_series), sum(revenue_series))
  marketing_percent = _financial_story_ratio(sum(marketing_series), sum(revenue_series))
  overhead_percent = _financial_story_ratio(sum(g_and_a_series) + sum(lease_rent_series), sum(revenue_series))
  operating_cash_positive_quarters = len([value for value in operating_cash_flow_series if value > 0.0])
  ebitda_positive_quarters = len([value for value in ebitda_series if value > 0.0])
  negative_cash_quarters = len([value for value in ending_cash_series if value < 0.0])
  current_ratio_series = [
    _financial_story_ratio(current_assets, current_liabilities)
    for current_assets, current_liabilities in zip(current_assets_series, current_liabilities_series)
  ]
  final_current_ratio = current_ratio_series[-1] if current_ratio_series else 0.0
  average_ar_days = _financial_story_average_days(rows, balance_key="accounts_receivable", flow_key="revenue")
  average_inventory_days = _financial_story_average_days(rows, balance_key="inventory", flow_key="cogs")
  average_ap_days = _financial_story_average_days(rows, balance_key="accounts_payable", flow_key="cogs")
  annualized_growth = 0.0
  horizon_year_span = max(1.0, (quarter_count / 4.0) - 1.0)
  if first_year_revenue > 0.0 and final_year_revenue > 0.0:
    annualized_growth = float((final_year_revenue / first_year_revenue) ** (1.0 / horizon_year_span) - 1.0)
  modeled_units_year_one = (
    first_year_revenue / unit_price
    if unit_price is not None and abs(float(unit_price)) > 1e-9
    else None
  )
  final_equity = total_equity_series[-1] if total_equity_series else 0.0
  final_owners_capital = owners_capital_series[-1] if owners_capital_series else 0.0
  final_other_equity = other_equity_series[-1] if other_equity_series else 0.0
  remaining_issue_codes = _financial_story_issue_codes(controller_resolution_state)
  hard_rule_clear = bool(hard_rules.get("all_hard_rules_cleared")) if hard_rules else negative_cash_quarters == 0

  logistics_like = any(
    keyword in str(business_type or "").lower()
    for keyword in ("shipping", "logistics", "transport", "freight", "delivery")
  )
  cogs_components = (
    [
      "Purchased transportation, linehaul, and last-mile delivery expense",
      "Sorting, handling, and network operations tied to shipment volume",
      "Fuel, carrier payments, and other throughput-linked fulfillment cost",
    ]
    if logistics_like
    else [
      "Direct fulfillment or service-delivery cost tied to customer volume",
      "Variable labor or contractor expense needed to deliver the offering",
      "Materials, pass-through items, and operating inputs that scale with demand",
    ]
  )

  revenue_drivers = [
    _financial_story_trim(
      (
        f"Volume is primarily governed by {capacity_driver}, with modeled weekly capacity of "
        f"{int(weekly_capacity):,} {unit_name}s at approximately {_financial_story_percent(utilization)} utilization."
      ) if weekly_capacity is not None and utilization is not None else (
        f"Volume growth is driven mainly by {capacity_driver}, so throughput execution matters more than a headline pricing reset."
      ),
      max_chars=135,
    ),
    _financial_story_trim(
      (
        f"Pricing is anchored near {_financial_story_compact_currency(unit_price)} per {unit_name}, which keeps the revenue build dependent on repeatable activity rather than aggressive yield expansion."
      ) if unit_price is not None else (
        "Pricing appears steady and operationally grounded, so the forecast depends more on repeat volume and mix quality than on a heroic price assumption."
      ),
      max_chars=135,
    ),
    _financial_story_trim(
      (
        f"Demand concentration appears oriented toward {market_focus}, which should help diversify the customer base if execution stays aligned with the current operating profile."
      ) if market_focus else (
        f"The model assumes {primary_growth_lever} while keeping the commercial posture broadly consistent with the operating footprint."
      ),
      max_chars=90,
    ),
  ]
  revenue_drivers = [item for item in revenue_drivers[:2] if str(item or "").strip()]

  margin_drivers = [
    _financial_story_trim(
      f"Gross margin expands from about {_financial_story_percent(gross_margin_early)} in the opening year to {_financial_story_percent(gross_margin_late)} in the final year.",
      max_chars=110,
    ),
    _financial_story_trim(
      f"Payroll runs at roughly {_financial_story_percent(payroll_percent)} of revenue, so labor absorption remains a core determinant of EBITDA quality.",
      max_chars=115,
    ),
    _financial_story_trim(
      f"Marketing and overhead together average roughly {_financial_story_percent(marketing_percent + overhead_percent)}, leaving margin upside dependent on scale rather than expense suppression.",
      max_chars=120,
    ),
  ]
  margin_drivers = margin_drivers[:2]

  key_risks = [
    _financial_story_trim(
      "A shortfall in volume or utilization would pressure margins quickly because the business carries a real labor and network cost base ahead of revenue.",
      max_chars=120,
    ),
    _financial_story_trim(
      "Gross-margin slippage would matter disproportionately because direct cost is the largest expense block in the modeled structure.",
      max_chars=115,
    ),
    _financial_story_trim(
      "Liquidity remains sensitive to collection timing and working-capital discipline, especially if receivables stretch while growth is still being funded.",
      max_chars=120,
    ),
  ]
  key_risks = key_risks[:2]
  sensitivity_drivers = [
    _financial_story_trim("Volume and realized utilization.", max_chars=80),
    _financial_story_trim("Gross margin / COGS discipline.", max_chars=80),
  ]
  if final_total_debt > 0.0:
    sensitivity_drivers.append(
      _financial_story_trim("Debt burden and interest coverage.", max_chars=80)
    )

  revenue_summary = _financial_story_trim(
    " ".join(
      [
        f"{business_name} shows a throughput-led revenue model rather than a speculative one.",
        f"The plan moves from about {_financial_story_compact_currency(first_year_revenue)} in the first four quarters to {_financial_story_compact_currency(final_year_revenue)} in the final four quarters, or roughly {_financial_story_percent(annualized_growth)} annualized growth over the horizon.",
        (
          f"Pricing stays anchored near {_financial_story_compact_currency(unit_price)} per {unit_name}, so the top line depends more on volume absorption and customer retention than on repricing."
          if unit_price is not None
          else "Pricing does not appear to be doing the heavy lifting in the forecast."
        ),
        (
          f"Capacity of roughly {int(weekly_capacity):,} {unit_name}s per week at {_financial_story_percent(utilization)} utilization gives the lender a visible operating constraint to underwrite."
          if weekly_capacity is not None and utilization is not None
          else f"The principal growth lever remains {primary_growth_lever}, which ties revenue to a real operating driver."
        ),
      ]
    ),
    max_chars=430,
  )

  cost_structure_summary = _financial_story_trim(
    " ".join(
      [
        f"The cost structure is dominated by direct operating cost, with cost of goods sold averaging about {_financial_story_percent(cogs_percent)} of revenue across the modeled horizon.",
        f"Payroll averages roughly {_financial_story_percent(payroll_percent)}, marketing about {_financial_story_percent(marketing_percent)}, and core overhead, defined here as G&A plus lease/rent, about {_financial_story_percent(overhead_percent)}.",
        "For credit review, that mix is constructive because the plan does not create EBITDA by pretending the operating platform can run on an unrealistically thin support base.",
        "Margins therefore depend on scale absorption and cost discipline, not on missing expense lines.",
      ]
    ),
    max_chars=430,
  )

  profitability_summary = _financial_story_trim(
    " ".join(
      [
        f"Profitability improves in a manner that looks operational rather than cosmetic, with gross margin moving from roughly {_financial_story_percent(gross_margin_early)} in the opening year to {_financial_story_percent(gross_margin_late)} in the final year.",
        f"EBITDA margin follows the same pattern, moving from about {_financial_story_percent(ebitda_margin_early)} to {_financial_story_percent(ebitda_margin_late)}, while final-year EBITDA reaches approximately {_financial_story_compact_currency(final_year_ebitda)}.",
        f"EBITDA stays positive in {ebitda_positive_quarters} of {quarter_count} modeled quarters, which is a better sign of durability than a single late-horizon spike.",
      ]
    ),
    max_chars=260,
  )

  cash_flow_summary = _financial_story_trim(
    " ".join(
      [
        f"Cash flow behavior is credible for lending purposes because operating cash flow is positive in {operating_cash_positive_quarters} of {quarter_count} quarters, minimum ending cash stays around {_financial_story_compact_currency(minimum_cash)}, and final ending cash reaches about {_financial_story_compact_currency(final_cash)}.",
        f"Average working-capital intensity is manageable but real, with receivable days near {average_ar_days:.0f}, inventory days near {average_inventory_days:.0f}, and payable days near {average_ap_days:.0f}.",
        f"The current ratio ends near {_financial_story_multiple(final_current_ratio)}, so the plan does not appear to rely on an artificial liquidity cliff to reach completion.",
        f"Under the selected {cash_strategy} cash posture, collections and direct-cost discipline remain the key cash-conversion variables.",
      ]
    ),
    max_chars=450,
  )

  capital_requirements_summary = _financial_story_trim(
    " ".join(
      [
        f"Capital requirements are meaningful but not uncontrolled. Total modeled capital expenditure is about {_financial_story_compact_currency(total_capex)} over the forecast, with approximately {_financial_story_compact_currency(early_capex)} deployed in the first year and {_financial_story_compact_currency(late_capex)} in the final year.",
        f"Ending PPE reaches roughly {_financial_story_compact_currency(final_ppe)}, which suggests the footprint is backed by real asset support.",
      ]
    ),
    max_chars=260,
  )

  financing_summary = _financial_story_trim(
    " ".join(
      [
        f"The modeled capital structure ends with total debt of about {_financial_story_compact_currency(final_total_debt)} against total equity of {_financial_story_compact_currency(final_equity)}.",
        f"Owner's capital and other equity together account for roughly {_financial_story_compact_currency(final_owners_capital + final_other_equity)} of the permanent capital base, which provides real cushion ahead of creditors.",
        (
          f"Trailing four-quarter interest expense is approximately {_financial_story_compact_currency(trailing_interest)}, implying interest coverage of {_financial_story_multiple(interest_coverage)} and end-state leverage of {_financial_story_multiple(leverage_ratio)}."
          if final_total_debt > 0.0 and trailing_interest > 0.0
          else "Funded debt is present but not dominant in the capital stack, so repayment capacity depends more on operating cash generation and liquidity preservation than on refinancing."
        ),
        f"Peak modeled debt reaches about {_financial_story_compact_currency(peak_total_debt)}.",
      ]
    ),
    max_chars=250,
  )

  downside_commentary = _financial_story_trim(
    " ".join(
      [
        "The cleanest downside case to test is lower volume combined with slower collections.",
        "That scenario would hit gross margin, current ratio, and ending cash at the same time.",
        (
          f"The model nevertheless concludes with no catastrophic liquidity break and a minimum ending cash balance near {_financial_story_compact_currency(minimum_cash)}."
          if hard_rule_clear
          else "The lender should therefore underwrite to conservative working-capital behavior rather than assume the base case will always self-correct."
        ),
      ]
    ),
    max_chars=220,
  )

  phase_1_text = _financial_story_trim(
    " ".join(
      [
        f"Phase 1, covering the first four quarters, is the build-and-prove period. Revenue reaches about {_financial_story_compact_currency(first_year_revenue)} with EBITDA of roughly {_financial_story_compact_currency(first_year_ebitda)} and operating cash flow of {_financial_story_compact_currency(first_year_operating_cash)}.",
        "This is the point where the model proves that the operating base can support real cost and working-capital needs.",
      ]
    ),
    max_chars=180,
  )
  phase_2_text = _financial_story_trim(
    " ".join(
      [
        "Phase 2, roughly the middle of the horizon, is where scale absorption should become visible if the business is truly working.",
        "This is the period when revenue density and labor productivity should widen margins and stabilize liquidity.",
      ]
    ),
    max_chars=165,
  )
  phase_3_text = _financial_story_trim(
    " ".join(
      [
        f"Phase 3, the final four quarters, shows the mature run rate with revenue of about {_financial_story_compact_currency(final_year_revenue)}, EBITDA of {_financial_story_compact_currency(final_year_ebitda)}, and operating cash flow of {_financial_story_compact_currency(final_year_operating_cash)}.",
        "That end-state matters because it shows whether the business exits the plan with durable earnings and liquidity.",
      ]
    ),
    max_chars=185,
  )

  repayment_capacity_text = _financial_story_trim(
    " ".join(
      [
        f"Repayment capacity appears supported by a final-year EBITDA run rate of {_financial_story_compact_currency(final_year_ebitda)} and ending cash of {_financial_story_compact_currency(final_cash)}.",
        (
          f"On the modeled debt load, interest coverage is about {_financial_story_multiple(interest_coverage)} and leverage ends near {_financial_story_multiple(leverage_ratio)}, which is workable if operating performance stays close to plan."
          if final_total_debt > 0.0 and trailing_interest > 0.0
          else "Because funded debt is not the dominant claim on the capital structure, repayment appears to rely more on recurring operating cash flow than on capital-markets access."
        ),
      ]
    ),
    max_chars=170,
  )
  cash_stability_text = _financial_story_trim(
    " ".join(
      [
        f"Cash stability is acceptable because minimum ending cash stays around {_financial_story_compact_currency(minimum_cash)}, peak cash reaches {_financial_story_compact_currency(peak_cash)}, and the current ratio ends near {_financial_story_multiple(final_current_ratio)}.",
        f"Receivable days of roughly {average_ar_days:.0f} mean collections discipline still matters, but the model does not end with a liquidity hole that would obviously threaten near-term obligations.",
      ]
    ),
    max_chars=170,
  )
  overall_credit_story_text = _financial_story_trim(
    " ".join(
      [
        f"Overall, this reads as a financeable {business_type.lower()} credit story if management can execute the modeled throughput, gross-margin, and working-capital disciplines.",
        "The plan shows a real operating cost base, a credible capital structure, and a forecast that ends with liquidity rather than with an unresolved repair case.",
        (
          "The forecast closes with positive liquidity and no visible catastrophic cash break, which is the key final underwriting signal."
          if hard_rule_clear and not remaining_issue_codes
          else "Underwriting should remain focused on the small set of drivers that still carry execution sensitivity."
        ),
      ]
    ),
    max_chars=180,
  )

  return {
    "contract_version": "financial_story_v1",
    "perspective": "lender",
    "financial_narrative": {
      "revenue_model": {
        "summary": revenue_summary,
        "drivers": revenue_drivers,
        "pricing_logic": _financial_story_trim(
          (
            f"Pricing appears anchored near {_financial_story_compact_currency(unit_price)} per {unit_name}, so lender confidence should come from repeatable volume and mix rather than from aggressive price inflation."
          ) if unit_price is not None else (
            "Pricing does not appear to be the primary bridge to viability; the stronger credit signal is whether the business can sustain volume and mix at the modeled service level."
          ),
          max_chars=95,
        ),
        "volume_assumptions": _financial_story_trim(
          (
            f"The first-year plan implies roughly {int(modeled_units_year_one):,} {unit_name}s if pricing holds near the stated level, and that unit volume must be supported by {capacity_driver} rather than by a one-time demand spike."
          ) if modeled_units_year_one is not None else (
            f"Volume assumptions are best viewed through the lens of {capacity_driver}, because that is the operating bottleneck that has to support the revenue path."
          ),
          max_chars=95,
        ),
        "scaling_behavior": _financial_story_trim(
          f"Scaling is expected to come from throughput absorption and operating density, with annual revenue rising from {_financial_story_compact_currency(first_year_revenue)} to {_financial_story_compact_currency(final_year_revenue)} while keeping the commercial posture broadly intact.",
          max_chars=95,
        ),
      },
      "cost_structure": {
        "summary": cost_structure_summary,
        "cogs": {
          "description": _financial_story_trim(
            f"Direct cost remains the dominant expense block at approximately {_financial_story_percent(cogs_percent)} of revenue, which is consistent with a business whose service delivery consumes real throughput-linked operating cost.",
            max_chars=90,
          ),
          "percent_of_revenue": _financial_story_percent(cogs_percent),
          "key_components": cogs_components,
        },
        "operating_expenses": {
          "labor": _financial_story_trim(
            f"Labor expense averages about {_financial_story_percent(payroll_percent)} of revenue and behaves like a real capacity cost rather than a plug, which is positive for forecast credibility but raises sensitivity to volume absorption.",
            max_chars=85,
          ),
          "marketing": _financial_story_trim(
            f"Marketing runs near {_financial_story_percent(marketing_percent)} of revenue; that is supportable, but it still requires customer acquisition efficiency so that cash conversion does not deteriorate as the business scales.",
            max_chars=80,
          ),
          "overhead": _financial_story_trim(
            f"G&A plus lease/rent average about {_financial_story_percent(overhead_percent)} of revenue, creating a moderate fixed-cost layer that should improve with scale but will pressure margins if throughput underperforms.",
            max_chars=80,
          ),
        },
        "fixed_vs_variable_mix": _financial_story_trim(
          "The mix is balanced toward variable direct cost with a meaningful but not overwhelming fixed overhead layer, which should allow earnings to improve with scale while still leaving a clear downside if utilization fades.",
          max_chars=85,
        ),
        "operating_leverage_commentary": _financial_story_trim(
          "Operating leverage is present because fixed labor and support infrastructure do not need to rise one-for-one with revenue, but it is not so extreme that the model looks engineered solely for margin expansion.",
          max_chars=80,
        ),
      },
      "profitability_profile": {
        "summary": profitability_summary,
        "gross_margin_trend": _financial_story_trim(
          f"Gross margin improves from roughly {_financial_story_percent(gross_margin_early)} in the first year to {_financial_story_percent(gross_margin_late)} in the final year, suggesting better absorption of direct operating cost as the business scales.",
          max_chars=90,
        ),
        "ebitda_trend": _financial_story_trim(
          f"EBITDA margin rises from approximately {_financial_story_percent(ebitda_margin_early)} to {_financial_story_percent(ebitda_margin_late)}, with final-year EBITDA of about {_financial_story_compact_currency(final_year_ebitda)}.",
          max_chars=90,
        ),
        "margin_drivers": margin_drivers,
        "stability_commentary": _financial_story_trim(
          f"The business records positive EBITDA in {ebitda_positive_quarters} of {quarter_count} quarters, which is a better sign of earnings durability than a single late-horizon spike.",
          max_chars=75,
        ),
      },
      "cash_flow_dynamics": {
        "summary": cash_flow_summary,
        "operating_cash_flow_behavior": _financial_story_trim(
          f"Operating cash flow is positive in {operating_cash_positive_quarters} of {quarter_count} quarters and improves from {_financial_story_compact_currency(first_year_operating_cash)} in the first year to {_financial_story_compact_currency(final_year_operating_cash)} in the final year.",
          max_chars=100,
        ),
        "working_capital_assumptions": {
          "ar": _financial_story_trim(
            f"Receivables average roughly {average_ar_days:.0f} days outstanding, so the credit story assumes management can keep collections reasonably close to invoicing growth.",
            max_chars=70,
          ),
          "ap": _financial_story_trim(
            f"Payables average around {average_ap_days:.0f} days, which provides some supplier float but not enough to fully offset slower customer receipts in a downside case.",
            max_chars=70,
          ),
          "inventory": _financial_story_trim(
            f"Inventory turns imply roughly {average_inventory_days:.0f} days on hand, keeping the model from relying on an unrealistically lean working-capital posture.",
            max_chars=65,
          ),
        },
        "cash_conversion_commentary": _financial_story_trim(
          f"Cash conversion is adequate because liquidity builds to {_financial_story_compact_currency(final_cash)} without a catastrophic cash break, but the path still depends on protecting gross margin and collection timing quarter by quarter.",
          max_chars=85,
        ),
      },
      "capital_requirements": {
        "capex_strategy": _financial_story_trim(
          f"The business invests about {_financial_story_compact_currency(total_capex)} of capital over the full horizon, which supports a real operating footprint rather than an asset-light story that would be difficult to defend under diligence.",
          max_chars=85,
        ),
        "timing_of_investment": _financial_story_trim(
          f"Capex is not back-ended exclusively: roughly {_financial_story_compact_currency(early_capex)} lands in the first year and {_financial_story_compact_currency(late_capex)} in the final year, showing a staged build rather than a single catch-up event.",
          max_chars=85,
        ),
        "asset_intensity_commentary": capital_requirements_summary,
      },
      "financing_and_debt": {
        "current_structure": _financial_story_trim(
          f"The ending capital structure shows total debt of {_financial_story_compact_currency(final_total_debt)} against total equity of {_financial_story_compact_currency(final_equity)}, with owner and retained capital still carrying a meaningful share of the funding burden.",
          max_chars=90,
        ),
        "debt_levels": _financial_story_trim(
          f"Debt peaks near {_financial_story_compact_currency(peak_total_debt)} and ends around {_financial_story_compact_currency(final_total_debt)}, so the balance sheet does not rely on ever-rising leverage to make the model work.",
          max_chars=85,
        ),
        "interest_burden": _financial_story_trim(
          (
            f"Trailing four-quarter interest expense runs near {_financial_story_compact_currency(trailing_interest)}, which remains manageable relative to the final-year EBITDA run rate."
          ) if trailing_interest > 0.0 else (
            "Interest burden is modest in the modeled end state, so debt service pressure appears more tied to principal discipline and liquidity preservation than to coupon load."
          ),
          max_chars=85,
        ),
        "debt_service_ability": _financial_story_trim(
          (
            f"Modeled debt service ability looks acceptable with interest coverage of {_financial_story_multiple(interest_coverage)} and ending cash of {_financial_story_compact_currency(final_cash)}, assuming revenue and margin stay broadly on plan."
          ) if final_total_debt > 0.0 and trailing_interest > 0.0 else (
            f"Debt service ability appears supported mainly by operating cash flow and ending cash of {_financial_story_compact_currency(final_cash)}, rather than by dependence on refinancing."
          ),
          max_chars=90,
        ),
        "leverage_commentary": financing_summary,
      },
      "risk_and_sensitivity": {
        "key_risks": key_risks,
        "sensitivity_drivers": sensitivity_drivers,
        "downside_commentary": downside_commentary,
      },
      "five_year_trajectory": {
        "phase_1": phase_1_text,
        "phase_2": phase_2_text,
        "phase_3": phase_3_text,
        "inflection_points": [
          _financial_story_trim(
            f"Revenue scales from {_financial_story_compact_currency(first_year_revenue)} in the first year to {_financial_story_compact_currency(final_year_revenue)} in the final year.",
            max_chars=120,
          ),
          _financial_story_trim(
            f"Liquidity stays above a minimum ending cash level of {_financial_story_compact_currency(minimum_cash)}.",
            max_chars=110,
          ),
          _financial_story_trim(
            f"Final-year EBITDA reaches approximately {_financial_story_compact_currency(final_year_ebitda)}.",
            max_chars=90,
          ),
        ],
      },
      "lender_summary": {
        "repayment_capacity": repayment_capacity_text,
        "cash_stability": cash_stability_text,
        "overall_credit_story": overall_credit_story_text,
      },
    },
  }

def _build_unified_horizon_snapshot(
  current_finmo_json: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
  metrics = _cash_review_quarter_metrics(current_finmo_json)
  ending_cash_series = [float(_safe_float(item.get("ending_cash")) or 0.0) for item in metrics]
  ebitda_series = [float(_safe_float(item.get("ebitda")) or 0.0) for item in metrics]
  net_income_series = [float(_safe_float(item.get("net_income")) or 0.0) for item in metrics]
  revenue_series = [float(_safe_float(item.get("revenue")) or 0.0) for item in metrics]
  negative_cash_quarters = [idx + 1 for idx, value in enumerate(ending_cash_series) if value < 0.0]
  catastrophic_liquidity_quarters = [
    idx + 1
    for idx, value in enumerate(ending_cash_series)
    if value < _UNIFIED_CATASTROPHIC_LIQUIDITY_FLOOR
  ]
  negative_net_income_quarters = [idx + 1 for idx, value in enumerate(net_income_series) if value < 0.0]
  negative_ebitda_quarters = [idx + 1 for idx, value in enumerate(ebitda_series) if value < 0.0]
  final_cash = ending_cash_series[-1] if ending_cash_series else 0.0
  horizon_snapshot = {
    "quarter_count": len(metrics),
    "negative_cash_quarters": negative_cash_quarters,
    "catastrophic_liquidity_quarters": catastrophic_liquidity_quarters,
    "negative_net_income_quarters": negative_net_income_quarters,
    "negative_ebitda_quarters": negative_ebitda_quarters,
    "minimum_ending_cash": min(ending_cash_series) if ending_cash_series else 0.0,
    "maximum_ending_cash": max(ending_cash_series) if ending_cash_series else 0.0,
    "final_ending_cash": final_cash,
    "final_revenue": revenue_series[-1] if revenue_series else 0.0,
    "final_ebitda": ebitda_series[-1] if ebitda_series else 0.0,
    "final_net_income": net_income_series[-1] if net_income_series else 0.0,
    "business_appears_ongoing_concern": not catastrophic_liquidity_quarters and final_cash > _UNIFIED_CATASTROPHIC_LIQUIDITY_FLOOR,
  }
  return horizon_snapshot, metrics

def _build_unified_hard_rule_assessment(
  *,
  controller_resolution_state: Optional[Dict[str, Any]],
  current_finmo_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  controller_state = controller_resolution_state if isinstance(controller_resolution_state, dict) else {}
  horizon_snapshot, metrics = _build_unified_horizon_snapshot(current_finmo_json)
  accounting_failure_quarters: List[int] = []
  catastrophic_liquidity_quarters = [
    int(_safe_float(item) or 0)
    for item in (horizon_snapshot.get("catastrophic_liquidity_quarters") or [])
    if int(_safe_float(item) or 0) >= 1
  ]
  for row in (metrics or []):
    if not isinstance(row, dict):
      continue
    quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
    if quarter_index < 1:
      continue
    accounting_gap = abs(float(_safe_float(row.get("accounting_equation_check")) or 0.0))
    if accounting_gap > _UNIFIED_ACCOUNTING_EQUATION_TOLERANCE:
      accounting_failure_quarters.append(quarter_index)

  remaining_hard_issue_codes: List[str] = []
  for item in _controller_state_issue_status_records(controller_state):
    if not isinstance(item, dict):
      continue
    snapshot = _controller_issue_completion_snapshot(
      item,
      current_finmo_json=current_finmo_json,
    )
    if not bool(snapshot.get("blocking")) or not bool(snapshot.get("hard_issue")):
      continue
    issue_code = str(snapshot.get("issue_code") or "").strip().lower()
    if _is_cash_pass_owned_issue_code(issue_code):
      continue
    if issue_code and issue_code not in remaining_hard_issue_codes:
      remaining_hard_issue_codes.append(issue_code)

  failed_rule_codes: List[str] = []
  if accounting_failure_quarters:
    failed_rule_codes.append("accounting_integrity_failure")
  for issue_code in remaining_hard_issue_codes:
    if issue_code not in failed_rule_codes:
      failed_rule_codes.append(issue_code)

  return {
    "contract_version": "unified_hard_rule_assessment_v1",
    "all_hard_rules_cleared": not failed_rule_codes,
    "remaining_hard_issue_count": len(remaining_hard_issue_codes),
    "remaining_hard_issue_codes": copy.deepcopy(remaining_hard_issue_codes),
    "accounting_integrity_passed": not accounting_failure_quarters,
    "accounting_failure_quarters": copy.deepcopy(accounting_failure_quarters),
    "cash_pass_owns_liquidity_detection": True,
    "catastrophic_liquidity_passed": True,
    "catastrophic_liquidity_quarters": copy.deepcopy(catastrophic_liquidity_quarters),
    "failed_rule_codes": copy.deepcopy(failed_rule_codes),
    "minimum_ending_cash": float(_safe_float(horizon_snapshot.get("minimum_ending_cash")) or 0.0),
    "final_ending_cash": float(_safe_float(horizon_snapshot.get("final_ending_cash")) or 0.0),
    "final_ebitda": float(_safe_float(horizon_snapshot.get("final_ebitda")) or 0.0),
  }

def _build_unified_convergence_context_payload(
  *,
  draft_id: str,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  planning_context_summary_json: Optional[Dict[str, Any]],
  planning_mode: str,
  planning_mode_reason: str,
  prompt_file: str,
  current_model_input_json: Optional[Dict[str, Any]],
  current_finmo_json: Optional[Dict[str, Any]],
  controller_resolution_state: Optional[Dict[str, Any]],
  grid_application_summary: Optional[Dict[str, Any]] = None,
  protected_resolved_issue_constraints: Optional[List[Dict[str, Any]]] = None,
  prior_numeric_feedback: Optional[Dict[str, Any]] = None,
  stage_ramp_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  cash_strategy_context: Dict[str, Any] = {}
  business_world_contract = _business_world_contract(
    business_facts=copy.deepcopy(business_facts or {}),
    ops_json=copy.deepcopy(ops_json or {}),
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    stage_ramp_contract=copy.deepcopy(stage_ramp_contract)
    if isinstance(stage_ramp_contract, dict)
    else None,
  )
  leverage_catalog = _build_writable_lever_review_catalog(current_model_input_json)
  issue_status_records = _filter_cash_pass_owned_issue_records(
    _controller_state_issue_status_records(controller_resolution_state)
  )
  convergence_controller_resolution_state = copy.deepcopy(controller_resolution_state or {})
  if isinstance(convergence_controller_resolution_state, dict):
    convergence_controller_resolution_state["issue_status_records"] = copy.deepcopy(issue_status_records)
    convergence_controller_resolution_state["remaining_issues"] = _filter_cash_pass_owned_issue_records(
      convergence_controller_resolution_state.get("remaining_issues") or []
    )
  resolved_issue_constraints = [
    item for item in (protected_resolved_issue_constraints or [])
    if isinstance(item, dict)
  ] or _build_strategy_resolved_issue_constraints(copy.deepcopy(issue_status_records))
  whole_horizon_snapshot, horizon_quarter_metrics = _build_unified_horizon_snapshot(
    current_finmo_json
  )
  hard_rule_assessment = _build_unified_hard_rule_assessment(
    controller_resolution_state=copy.deepcopy(controller_resolution_state or {}),
    current_finmo_json=copy.deepcopy(current_finmo_json or {}),
  )
  try:
    from client_intake_and_finmo.numeric_execution import build_numeric_solver_contract  # type: ignore
  except Exception:
    from numeric_execution import build_numeric_solver_contract  # type: ignore
  numeric_solver_contract = build_numeric_solver_contract(
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    selected_cash_strategy=_resolved_cash_strategy(financials_json),
    issue_status_records=copy.deepcopy(issue_status_records),
    writable_lever_catalog=copy.deepcopy(leverage_catalog),
    current_model_input_json=copy.deepcopy(current_model_input_json or {}),
    current_finmo_json=copy.deepcopy(current_finmo_json or {}),
    pass_name="unified_convergence",
    contract_scope="unified_convergence",
  )
  if isinstance(numeric_solver_contract, dict):
    numeric_solver_contract["pass_name"] = "unified_convergence"
    numeric_solver_contract["contract_scope"] = "unified_convergence"
    numeric_solver_contract["solver_phase_status"] = "phase_9_unified_convergence_solver_live"
    solver_settings = (
      numeric_solver_contract.get("solver_settings")
      if isinstance(numeric_solver_contract.get("solver_settings"), dict)
      else {}
    )
    solver_settings = copy.deepcopy(solver_settings)
    solver_settings["current_execution_mode"] = "phase_9_unified_convergence_solver_live"
    numeric_solver_contract["solver_settings"] = solver_settings
  deterministic_issue_packets = _build_issue_packets_from_issue_ledger(
    issue_status_records=copy.deepcopy(issue_status_records),
    numeric_solver_contract=copy.deepcopy(numeric_solver_contract),
    current_finmo_json=copy.deepcopy(current_finmo_json or {}),
  )
  return {
    "contract_version": "unified_convergence_context_v1",
    "draft_id": str(draft_id or "").strip(),
    "business_name": str((business_facts or {}).get("name") or (business_facts or {}).get("business_name") or "").strip(),
    "planning_mode_context": _build_planning_mode_context(
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      prompt_file=prompt_file,
    ),
    "selected_cash_strategy": str((financials_json or {}).get("cash_strategy") or "").strip(),
    "review_role": "single_unified_convergence_owner",
    "planning_context_summary": copy.deepcopy(planning_context_summary_json or {}),
    "business_world_contract": copy.deepcopy(business_world_contract),
    "grid_application_summary": copy.deepcopy(grid_application_summary or {}),
    "controller_resolution_state": copy.deepcopy(convergence_controller_resolution_state or {}),
    "current_issue_summaries": copy.deepcopy(_controller_state_issue_summaries(convergence_controller_resolution_state)),
    "issue_status_records": copy.deepcopy(issue_status_records),
    "deterministic_issue_packets": copy.deepcopy(deterministic_issue_packets),
    "resolved_issue_constraints": copy.deepcopy(resolved_issue_constraints),
    "resolved_issue_protection_policy": {
      "default_behavior": "preserve_previously_resolved_issues",
      "material_reopening_allowed_only_for_clear_viability_gain": True,
      "do_not_exit_with_reopened_issues": True,
    },
    "whole_horizon_snapshot": copy.deepcopy(whole_horizon_snapshot),
    "horizon_quarter_metrics": copy.deepcopy(horizon_quarter_metrics),
    "hard_rule_assessment": copy.deepcopy(hard_rule_assessment),
    "current_model_input_json": copy.deepcopy(current_model_input_json or {}),
    "current_finmo_json": copy.deepcopy(current_finmo_json or {}),
    "current_finmo_quarter_rows": [
      row for row in ((current_finmo_json or {}).get("quarter_rows") or []) if isinstance(row, dict)
    ],
    "writable_lever_catalog": {
      "lever_ids": [
        str(item.get("lever_id") or "").strip()
        for item in leverage_catalog
        if str(item.get("lever_id") or "").strip()
      ],
      "entries": copy.deepcopy(leverage_catalog),
    },
    "numeric_solver_contract": copy.deepcopy(numeric_solver_contract),
    "prior_numeric_solver_feedback": copy.deepcopy(prior_numeric_feedback or {}),
    "context_modules": {
      "unified_convergence": {
        "whole_horizon_snapshot": copy.deepcopy(whole_horizon_snapshot),
        "horizon_quarter_metrics": copy.deepcopy(horizon_quarter_metrics),
      },
      "cash_strategy": {
        "selected_cash_strategy": str((cash_strategy_context or {}).get("selected_cash_strategy") or "").strip(),
        "cash_profile_summary": copy.deepcopy((cash_strategy_context or {}).get("cash_profile_summary") or {}),
        "decision_trigger_candidates": copy.deepcopy((cash_strategy_context or {}).get("decision_trigger_candidates") or []),
        "strategy_relevant_series": copy.deepcopy((cash_strategy_context or {}).get("strategy_relevant_series") or {}),
        "cash_pass_ownership": "cash_strategy_review_context_is_built_after_convergence",
      },
      "hard_rules": {
        "hard_rule_assessment": copy.deepcopy(hard_rule_assessment),
        "resolved_issue_protection_policy": {
          "default_behavior": "preserve_previously_resolved_issues",
          "material_reopening_allowed_only_for_clear_viability_gain": True,
          "do_not_exit_with_reopened_issues": True,
        },
      },
    },
  }

def _load_unified_convergence_prompt() -> str:
  try:
    return _UNIFIED_CONVERGENCE_PROMPT_PATH.read_text(encoding="utf-8").strip()
  except Exception:
    return (
      "You are the single unified convergence planner for a real business plan.\n"
      "You own the entire convergence loop from the first post-grid cycle until the business is fully viable.\n"
      "See the whole system holistically from the start: planning mode, realism, cash posture, stabilization, issue state, and full trajectory.\n"
      "Do not behave like a narrow stage reviewer. You are the one convergence owner.\n"
      "Use only the provided writable lever ids and the quarter-specific solver contract.\n"
      "For active issues, return a coordinated strategy that can actually move the business toward a viable ongoing-concern state.\n"
      "Solver will execute every valid package, so focus on strategy quality, quarter targets, and lever coordination.\n"
      "Read shape_sensitive_contract directly before choosing structural levers.\n"
      "For shape-sensitive levers, return a full remaining-horizon path that preserves continuity: no quarter-to-quarter drop over 50%, no quarter-to-quarter jump over 2.5x, no snapback after a large build, and no abrupt regime switching without a believable transition.\n"
      "Do not return vague guidance. Return structured JSON only."
    ).strip()

def _planning_mode_prompt_text(planning_mode: Any) -> str:
  mode = str(planning_mode or "").strip().lower()
  if not mode:
    return ""
  try:
    from client_intake_and_finmo.quarter_grid import planning_mode_text  # type: ignore
  except Exception:
    try:
      from quarter_grid import planning_mode_text  # type: ignore
    except Exception:
      planning_mode_text = None  # type: ignore
  if planning_mode_text is None:
    return ""
  try:
    return str(planning_mode_text(mode) or "").strip()
  except Exception:
    return ""

def _build_planning_mode_context(
  *,
  planning_mode: Any,
  planning_mode_reason: Any = "",
  prompt_file: Any = "",
) -> Dict[str, Any]:
  mode = str(planning_mode or "").strip().lower()
  return {
    "planning_mode": mode,
    "planning_mode_reason": str(planning_mode_reason or "").strip(),
    "prompt_file": str(prompt_file or "").strip(),
    "mode_prompt_text": _planning_mode_prompt_text(mode),
    "carryforward_instruction": (
      "Continue this exact quarter-grid planning mode downstream. "
      "Do not invent a new posture or reinterpret the mode."
      if mode
      else ""
    ),
  }

def _truncate_summary_text(value: Any, *, max_len: int = 220) -> str:
  text = " ".join(str(value or "").strip().split())
  if not text:
    return ""
  if len(text) <= max_len:
    return text
  return text[: max_len - 3].rstrip() + "..."

def _compact_summary_value(value: Any) -> Any:
  if value is None:
    return None
  if isinstance(value, bool):
    return value
  if isinstance(value, (int, float)):
    return value
  if isinstance(value, str):
    return _truncate_summary_text(value)
  if isinstance(value, list):
    compact_items: List[Any] = []
    for item in value:
      compact_item = _compact_summary_value(item)
      if compact_item in (None, "", [], {}):
        continue
      if isinstance(compact_item, dict):
        continue
      compact_items.append(compact_item)
      if len(compact_items) >= 6:
        break
    return compact_items or None
  return None

def _compact_summary_section(
  payload: Optional[Dict[str, Any]],
  *,
  preferred_keys: List[str],
  max_fields: int = 10,
) -> Dict[str, Any]:
  source = payload if isinstance(payload, dict) else {}
  result: Dict[str, Any] = {}
  seen: set[str] = set()
  ordered_keys = list(preferred_keys) + sorted(source.keys())
  for key in ordered_keys:
    key_name = str(key or "").strip()
    if not key_name or key_name in seen or key_name not in source:
      continue
    compact_value = _compact_summary_value(source.get(key_name))
    if compact_value in (None, "", [], {}):
      continue
    result[key_name] = compact_value
    seen.add(key_name)
    if len(result) >= max_fields:
      break
  return result

def _build_planning_context_summary_payload(
  *,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  target_market_json: Optional[Dict[str, Any]],
  people_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  financials_year1_json: Optional[Dict[str, Any]],
  marketing_model_json: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]] = None,
  planning_mode: str = "",
  planning_mode_reason: str = "",
  prompt_file: str = "",
) -> Dict[str, Any]:
  business = business_facts if isinstance(business_facts, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  market = target_market_json if isinstance(target_market_json, dict) else {}
  people = people_json if isinstance(people_json, dict) else {}
  financials = financials_json if isinstance(financials_json, dict) else {}
  year1 = financials_year1_json if isinstance(financials_year1_json, dict) else {}
  marketing = marketing_model_json if isinstance(marketing_model_json, dict) else {}
  model_input = model_input_json if isinstance(model_input_json, dict) else {}
  people_list = [item for item in (people.get("people") or []) if isinstance(item, dict)]
  inferred_roles = [item for item in (people.get("inferred_roles") or []) if isinstance(item, dict)]
  products = [item for item in (ops.get("products") or []) if isinstance(item, dict)]
  services = [item for item in (ops.get("services") or []) if isinstance(item, dict)]
  return {
    "contract_version": "planning_context_summary_v1",
    "business_name": str(business.get("name") or business.get("business_name") or "").strip(),
    "planning_mode_context": _build_planning_mode_context(
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      prompt_file=prompt_file,
    ),
    "selected_cash_strategy": str(financials.get("cash_strategy") or "").strip(),
    "intake_non_binding_policy": {
      "intake_numbers_are_binding": False,
      "realism_overrides_intake": True,
      "stub_values_are_intake_snapshot_only": True,
      "stub_values_must_not_drive_forecast_decisions": True,
    },
    "business_profile": _compact_summary_section(
      business,
      preferred_keys=[
        "business_name",
        "name",
        "start_date",
        "address",
        "address_city",
        "address_state",
        "address_country",
      ],
      max_fields=7,
    ),
    "operating_profile": {
      **_compact_summary_section(
        ops,
        preferred_keys=[
          "business_type",
          "business_naics_6",
          "unit_name",
          "unit_description",
          "unit_cadence",
          "unit_price",
          "capacity_driver",
          "units_per_period_capacity",
          "units_per_week_capacity",
          "operating_periods_per_year",
          "utilization_rate",
          "shipping_method",
          "sales_modality",
          "geographic_scope",
          "competitive_advantage",
        ],
        max_fields=12,
      ),
      "product_count": len(products),
      "service_count": len(services),
    },
    "market_profile": _compact_summary_section(
      market,
      preferred_keys=[
        "target_market_summary",
        "customer_description",
        "primary_customer",
        "target_customer",
        "pricing_position",
        "sales_cycle",
        "geographic_focus",
      ],
      max_fields=10,
    ),
    "people_profile": {
      **_compact_summary_section(
        people,
        preferred_keys=[
          "key_people_summary",
          "management_summary",
          "staffing_strategy",
          "org_design_summary",
        ],
        max_fields=8,
      ),
      "people_count": len(people_list),
      "inferred_role_count": len(inferred_roles),
    },
    "financial_profile": _compact_summary_section(
      financials,
      preferred_keys=[
        "cash_strategy",
        "funding_strategy",
        "owner_draw_strategy",
        "owner_distributions",
        "debt_strategy",
        "equity_strategy",
        "capital_intensity",
      ],
      max_fields=10,
    ),
    "year1_anchor_summary": _compact_summary_section(
      year1,
      preferred_keys=[
        "revenue",
        "gross_profit",
        "ebitda",
        "net_income",
        "ending_cash",
        "operating_cash_flow",
        "capital_expenditures",
      ],
      max_fields=10,
    ),
    "marketing_profile": _compact_summary_section(
      marketing,
      preferred_keys=[
        "summary",
        "primary_channel",
        "channel_mix",
        "sales_motion",
        "go_to_market_motion",
      ],
      max_fields=8,
    ),
  }

def _persist_unified_convergence_state(
  *,
  conn,
  draft_id: str,
  stage: str,
  status: str,
  planning_context_summary_json: Optional[Dict[str, Any]],
  controller_resolution_state: Optional[Dict[str, Any]],
  resolution_summary: Optional[Dict[str, Any]],
  planning_mode: str,
  planning_mode_reason: str,
  prompt_file: str,
  grid_application_summary: Optional[Dict[str, Any]],
  realism_memo_before_resolution: Optional[Dict[str, Any]],
  realism_memo_json: Optional[Dict[str, Any]],
  unified_convergence_context: Optional[Dict[str, Any]],
  unified_convergence_decision: Optional[Dict[str, Any]],
  unified_convergence_plan: Optional[Dict[str, Any]],
  unified_convergence_result: Optional[Dict[str, Any]],
  unified_convergence_iterations: Optional[List[Dict[str, Any]]],
  unified_convergence_cycle_count: Optional[int],
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  cash_strategy_review_context: Optional[Dict[str, Any]] = None,
  cash_strategy_review_decision: Optional[Dict[str, Any]] = None,
  cash_strategy_second_pass_plan: Optional[Dict[str, Any]] = None,
  cash_strategy_second_pass_result: Optional[Dict[str, Any]] = None,
  cash_strategy_effect_summary: Optional[Dict[str, Any]] = None,
  controller_retry_heartbeat: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  return _persist_post_intake_stage_state(
    conn=conn,
    draft_id=str(draft_id).strip(),
    stage=stage,
    status=status,
    planning_context_summary_json=copy.deepcopy(planning_context_summary_json or {}),
    controller_resolution_state=copy.deepcopy(controller_resolution_state or {}),
    resolution_summary=copy.deepcopy(resolution_summary or {}),
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    prompt_file=prompt_file,
    grid_application_summary=copy.deepcopy(grid_application_summary or {}),
    realism_memo_before_resolution=copy.deepcopy(realism_memo_before_resolution or {}),
    realism_memo_json=copy.deepcopy(realism_memo_json or {}),
    model_input_json=copy.deepcopy(model_input_json or {}),
    finmo_json=copy.deepcopy(finmo_json or {}),
    unified_convergence_context=copy.deepcopy(unified_convergence_context or {}),
    unified_convergence_decision=copy.deepcopy(unified_convergence_decision or {}),
    unified_convergence_plan=copy.deepcopy(unified_convergence_plan or {}),
    unified_convergence_result=copy.deepcopy(unified_convergence_result or {}),
    unified_convergence_iterations=copy.deepcopy(unified_convergence_iterations or []),
    unified_convergence_cycle_count=unified_convergence_cycle_count,
    cash_strategy_review_context=copy.deepcopy(cash_strategy_review_context or {}),
    cash_strategy_review_decision=copy.deepcopy(cash_strategy_review_decision or {}),
    cash_strategy_second_pass_plan=copy.deepcopy(cash_strategy_second_pass_plan or {}),
    cash_strategy_second_pass_result=copy.deepcopy(cash_strategy_second_pass_result or {}),
    cash_strategy_effect_summary=copy.deepcopy(cash_strategy_effect_summary or {}),
    controller_retry_heartbeat=copy.deepcopy(controller_retry_heartbeat or {}),
    explicit_numeric_feedback_candidates=[
      ("unified_convergence_result", unified_convergence_result),
      ("cash_strategy_second_pass_result", cash_strategy_second_pass_result),
    ],
  )

def _parse_responses_json_dict(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
  output = data.get("output") or []
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_json" and isinstance(part.get("json"), dict):
        return part["json"]
  try:
    parsed = json.loads(_parse_responses_text(data))
  except Exception:
    return None
  return parsed if isinstance(parsed, dict) else None

def _openai_strict_json_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
  """Normalize local schemas to OpenAI strict structured-output requirements."""
  normalized = copy.deepcopy(schema if isinstance(schema, dict) else {})

  def _visit(node: Any) -> None:
    if isinstance(node, dict):
      properties = node.get("properties")
      if isinstance(properties, dict):
        node["additionalProperties"] = False
        node["required"] = list(properties.keys())
        for child in properties.values():
          _visit(child)
      items = node.get("items")
      if isinstance(items, dict):
        _visit(items)
      for key in ("anyOf", "oneOf", "allOf"):
        variants = node.get(key)
        if isinstance(variants, list):
          for variant in variants:
            _visit(variant)
    elif isinstance(node, list):
      for item in node:
        _visit(item)

  _visit(normalized)
  return normalized

def _compact_convergence_quarter_rows_for_state(rows: Any) -> List[Dict[str, Any]]:
  compact_rows: List[Dict[str, Any]] = []
  for row in (rows or []):
    if not isinstance(row, dict):
      continue
    try:
      quarter_index = int(float(row.get("quarter_index") or 0))
    except Exception:
      quarter_index = 0
    if quarter_index < 1:
      continue
    compact_rows.append(
      {
        "quarter_index": quarter_index,
        "year": copy.deepcopy(row.get("year")),
        "quarter": copy.deepcopy(row.get("quarter")),
        "revenue": _safe_float(row.get("revenue")),
        "gross_profit": _safe_float(row.get("gross_profit")),
        "ebitda": _safe_float(row.get("ebitda")),
        "net_income": _safe_float(row.get("net_income")),
        "ending_cash": _safe_float(row.get("ending_cash")),
        "operating_cash_flow": _safe_float(row.get("operating_cash_flow")),
        "investing_cash_flow": _safe_float(row.get("investing_cash_flow")),
        "financing_cash_flow": _safe_float(row.get("financing_cash_flow")),
        "current_assets": _safe_float(row.get("current_assets")),
        "ppe": _safe_float(row.get("ppe")),
        "current_liabilities": _safe_float(row.get("current_liabilities")),
        "total_liabilities": _safe_float(row.get("total_liabilities")),
        "total_equity": _safe_float(row.get("total_equity")),
        "accounting_equation_check": _safe_float(row.get("accounting_equation_check")),
      }
    )
  return compact_rows

def _build_current_cycle_convergence_packet(
  *,
  stage: str,
  status: str,
  planning_mode: Optional[str],
  planning_mode_reason: Optional[str],
  planning_context_summary: Optional[Dict[str, Any]],
  unified_convergence_context: Optional[Dict[str, Any]],
  controller_resolution_state: Optional[Dict[str, Any]],
  controller_retry_context: Optional[Dict[str, Any]] = None,
  prior_numeric_feedback: Optional[Dict[str, Any]] = None,
  unified_convergence_decision: Optional[Dict[str, Any]] = None,
  unified_convergence_plan: Optional[Dict[str, Any]] = None,
  unified_convergence_result: Optional[Dict[str, Any]] = None,
  unified_convergence_cycle_count: Optional[int] = None,
  cycle_debug: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  planning_summary = planning_context_summary if isinstance(planning_context_summary, dict) else {}
  convergence_context = (
    unified_convergence_context if isinstance(unified_convergence_context, dict) else {}
  )
  controller_state = (
    controller_resolution_state if isinstance(controller_resolution_state, dict) else {}
  )
  retry_context = (
    controller_retry_context if isinstance(controller_retry_context, dict) else {}
  )
  numeric_feedback = (
    prior_numeric_feedback if isinstance(prior_numeric_feedback, dict) else {}
  )
  cycle_debug_payload = cycle_debug if isinstance(cycle_debug, dict) else {}
  lever_catalog = (
    convergence_context.get("writable_lever_catalog")
    if isinstance(convergence_context.get("writable_lever_catalog"), dict)
    else {}
  )
  lever_ids = [
    str(item or "").strip()
    for item in (lever_catalog.get("lever_ids") or [])
    if str(item or "").strip()
  ]
  current_finmo_json = (
    convergence_context.get("current_finmo_json")
    if isinstance(convergence_context.get("current_finmo_json"), dict)
    else {}
  )
  current_finmo_rows = (
    current_finmo_json.get("quarter_rows")
    if isinstance(current_finmo_json.get("quarter_rows"), list)
    else convergence_context.get("current_finmo_quarter_rows")
    if isinstance(convergence_context.get("current_finmo_quarter_rows"), list)
    else []
  )
  numeric_guidance_packet = _build_unified_numeric_guidance_packet(
    controller_resolution_state=controller_state,
    controller_retry_context=retry_context,
    unified_convergence_context=convergence_context,
    quarter_count=max(
      _CONVERGENCE_DEFAULT_QUARTER_COUNT,
      len(current_finmo_rows or []),
    ),
  )
  repair_aware_issue_packets = _repair_aware_issue_packets(
    issue_packets=copy.deepcopy(convergence_context.get("deterministic_issue_packets") or []),
    numeric_guidance_packet=copy.deepcopy(numeric_guidance_packet),
  )
  convergence_scorecard = _build_convergence_scorecard(
    controller_resolution_state=controller_state,
    controller_retry_context=retry_context,
  )
  hard_rule_state = (
    convergence_context.get("hard_rule_assessment")
    if isinstance(convergence_context.get("hard_rule_assessment"), dict)
    else {}
  )
  return {
    "contract_version": "convergence_state_v1",
    "owner": "unified_convergence",
    "stage": str(stage or "").strip() or None,
    "status": str(status or "").strip() or None,
    "current_cycle": (
      int(_safe_float(unified_convergence_cycle_count))
      if unified_convergence_cycle_count is not None
      else None
    ),
    "convergence_test_mode": _convergence_test_mode_enabled(),
    "convergence_engine_contract": _unified_convergence_engine_contract_payload(),
    "business_context": {
      "business_name": str(
        planning_summary.get("business_name")
        or convergence_context.get("business_name")
        or ""
      ).strip() or None,
      "business_type": str(
        planning_summary.get("business_type")
        or planning_summary.get("industry")
        or ""
      ).strip() or None,
      "business_model": str(
        planning_summary.get("business_model")
        or planning_summary.get("business_model_summary")
        or ""
      ).strip() or None,
      "planning_mode": str(planning_mode or "").strip() or None,
      "planning_mode_reason": str(planning_mode_reason or "").strip() or None,
      "selected_cash_strategy": str(
        convergence_context.get("selected_cash_strategy") or ""
      ).strip() or None,
    },
    "issue_state": {
      "controller_status": str(controller_state.get("status") or "").strip() or None,
      "detected_issue_count": int(_safe_float(controller_state.get("detected_issue_count")) or 0),
      "remaining_issue_count": int(_safe_float(controller_state.get("remaining_issue_count")) or 0),
      "resolved_issue_count": int(_safe_float(controller_state.get("resolved_issue_count")) or 0),
      "tolerated_issue_count": int(_safe_float(controller_state.get("tolerated_issue_count")) or 0),
      "iteration_pending_issue_count": int(
        _safe_float(controller_state.get("iteration_pending_issue_count")) or 0
      ),
      "overall_completion_score_pct": int(
        _safe_float(controller_state.get("overall_completion_score_pct")) or 0
      ),
      "overall_completion_grade": str(
        controller_state.get("overall_completion_grade") or ""
      ).strip() or "D",
      "lowest_quarter_score_pct": int(
        _safe_float(controller_state.get("lowest_quarter_score_pct")) or 0
      ),
      "failing_quarters": copy.deepcopy(controller_state.get("failing_quarters") or []),
      "open_issue_codes": [
        str(item.get("issue_code") or "").strip()
        for item in (controller_state.get("remaining_issues") or [])
        if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
      ],
      "resolved_issue_codes": [
        str(item.get("issue_code") or "").strip()
        for item in (controller_state.get("resolved_issues") or [])
        if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
      ],
      "tolerated_issue_codes": [
        str(item.get("issue_code") or "").strip()
        for item in (controller_state.get("tolerated_issues") or [])
        if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
      ],
      "current_issue_summaries": copy.deepcopy(
        convergence_context.get("current_issue_summaries") or {}
      ),
      "deterministic_issue_packets": copy.deepcopy(repair_aware_issue_packets),
    },
    "hard_rule_state": copy.deepcopy(hard_rule_state),
    "retry_state": {
      "progress_status": str(retry_context.get("progress_status") or "").strip() or None,
      "failed_quarters": copy.deepcopy(retry_context.get("failed_quarters") or []),
      "failed_metrics": copy.deepcopy(retry_context.get("failed_metrics") or []),
      "required_open_issue_codes": copy.deepcopy(
        retry_context.get("required_open_issue_codes") or []
      ),
      "required_primary_metric_candidates": copy.deepcopy(
        retry_context.get("required_primary_metric_candidates") or []
      ),
      "required_issue_lever_ids": copy.deepcopy(
        retry_context.get("required_issue_lever_ids") or []
      ),
      "last_failure_reason": str(
        retry_context.get("last_failure_reason") or ""
      ).strip() or None,
      "minimum_primary_metric_coverage_count": int(
        _safe_float(retry_context.get("minimum_primary_metric_coverage_count")) or 0
      ) or None,
    },
    "numeric_state": {
      "solver_invoked": bool(numeric_feedback.get("solver_invoked")),
      "solver_execution_state": str(
        numeric_feedback.get("solver_execution_state") or ""
      ).strip() or None,
      "execution_state": str(
        numeric_feedback.get("execution_state") or ""
      ).strip() or None,
      "target_metric_names": copy.deepcopy(numeric_feedback.get("target_metric_names") or []),
      "targeted_quarters": copy.deepcopy(numeric_feedback.get("targeted_quarters") or []),
      "quarters_with_all_targets_within_tolerance": int(
        _safe_float(numeric_feedback.get("quarters_with_all_targets_within_tolerance")) or 0
      ),
      "quarters_with_target_misses": int(
        _safe_float(numeric_feedback.get("quarters_with_target_misses")) or 0
      ),
      "quarter_fit_summary": copy.deepcopy(numeric_feedback.get("quarter_fit_summary") or []),
    },
    "convergence_scorecard": copy.deepcopy(convergence_scorecard),
    "deterministic_numeric_guidance": copy.deepcopy(numeric_guidance_packet),
    "quarter_snapshot": _compact_convergence_quarter_rows_for_state(
      copy.deepcopy(current_finmo_rows or [])
    ),
    "lever_scope": {
      "lever_count": len(lever_ids),
      "lever_ids": copy.deepcopy(lever_ids),
    },
    "context_modules": copy.deepcopy(convergence_context.get("context_modules") or {}),
    "decision_summary": _compact_unified_convergence_decision_for_storage(
      copy.deepcopy(unified_convergence_decision or {})
    ),
    "plan_summary": _compact_unified_convergence_plan_for_storage(
      copy.deepcopy(unified_convergence_plan or {})
    ),
    "result_summary": _compact_unified_convergence_result_for_storage(
      copy.deepcopy(unified_convergence_result or {})
    ),
    "cycle_debug_summary": copy.deepcopy(
      cycle_debug_payload.get("issue_alignment_debug_summary") or {}
    ),
    "cycle_issue_debug": copy.deepcopy(
      cycle_debug_payload.get("issue_alignment_debug") or []
    ),
  }

def _lever_allowed_mapped_repair_targets(
  deterministic_numeric_guidance: Optional[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
  guidance = deterministic_numeric_guidance if isinstance(deterministic_numeric_guidance, dict) else {}
  mapping_quarters: Dict[Tuple[str, str, str], set[int]] = {}
  for issue_packet in (guidance.get("issue_repair_packets") or []):
    if not isinstance(issue_packet, dict):
      continue
    issue_code = str(issue_packet.get("issue_code") or "").strip().lower()
    if not issue_code:
      continue
    for repair_target in (issue_packet.get("repair_targets") or []):
      if not isinstance(repair_target, dict):
        continue
      quarter = int(_safe_float(repair_target.get("quarter")) or 0)
      if quarter < 1:
        continue
      for driver_path in (repair_target.get("driver_paths") or []):
        if not isinstance(driver_path, dict):
          continue
        lever_id = str(driver_path.get("lever") or "").strip()
        if not lever_id:
          continue
        target_metric_name = post_intake_direct_target_metric_for_lever(lever_id)
        if not target_metric_name:
          continue
        mapping_quarters.setdefault((lever_id, issue_code, target_metric_name), set()).add(quarter)
  lever_mapping_map: Dict[str, List[Dict[str, Any]]] = {}
  for lever_id, issue_code, target_metric_name in sorted(mapping_quarters.keys()):
    lever_mapping_map.setdefault(lever_id, []).append(
      {
        "issue_code": issue_code,
        "target_metric_name": target_metric_name,
        "target_quarters": sorted(mapping_quarters[(lever_id, issue_code, target_metric_name)]),
      }
    )
  return lever_mapping_map

def _run_unified_convergence_openai(
  *,
  draft_id: str,
  planning_context_summary_json: Optional[Dict[str, Any]],
  planning_mode: str,
  planning_mode_reason: str,
  planning_mode_prompt_file: str,
  unified_convergence_context: Dict[str, Any],
  prior_numeric_feedback: Optional[Dict[str, Any]] = None,
  controller_retry_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  prompt_file = "client_intake_and_finmo/prompts/unified_convergence/reviewer.md"
  planning_context_summary = (
    planning_context_summary_json if isinstance(planning_context_summary_json, dict) else {}
  )
  selected_cash_strategy = _resolved_cash_strategy(
    planning_context_summary,
    unified_convergence_context,
  )
  api_key = _openai_key()
  if not api_key:
    return {
      "contract_version": "unified_convergence_decision_v1",
      "status": "skipped_missing_openai_key",
      "prompt_file": prompt_file,
      "selected_cash_strategy": selected_cash_strategy,
      "review_status": "not_completed",
      "detail": "OPENAI_API_KEY is not configured.",
      "decision": {},
    }
  full_numeric_solver_contract = copy.deepcopy((unified_convergence_context or {}).get("numeric_solver_contract") or {})
  effective_prior_numeric_feedback = copy.deepcopy(
    prior_numeric_feedback
    if isinstance(prior_numeric_feedback, dict)
    else (unified_convergence_context or {}).get("prior_numeric_solver_feedback") or {}
  )
  current_cycle_convergence_packet = _build_current_cycle_convergence_packet(
    stage="convergence_running",
    status="running",
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    planning_context_summary=copy.deepcopy(planning_context_summary or {}),
    unified_convergence_context=copy.deepcopy(unified_convergence_context or {}),
    controller_resolution_state=copy.deepcopy(
      (unified_convergence_context or {}).get("controller_resolution_state")
      if isinstance((unified_convergence_context or {}).get("controller_resolution_state"), dict)
      else {}
    ),
    controller_retry_context=copy.deepcopy(controller_retry_context or {}),
    prior_numeric_feedback=copy.deepcopy(effective_prior_numeric_feedback),
    unified_convergence_cycle_count=copy.deepcopy(
      (controller_retry_context or {}).get("attempt_number")
      or (controller_retry_context or {}).get("cycle")
      or None
    ),
  )
  current_cycle_deterministic_numeric_guidance = copy.deepcopy(
    (current_cycle_convergence_packet.get("deterministic_numeric_guidance") if isinstance(current_cycle_convergence_packet, dict) else {})
    or {}
  )
  raw_retry_scope_payload = _build_retry_scope_payload(
    controller_retry_context=copy.deepcopy(controller_retry_context or {}),
    prior_numeric_feedback=copy.deepcopy(effective_prior_numeric_feedback),
    numeric_solver_contract=copy.deepcopy(full_numeric_solver_contract),
    deterministic_numeric_guidance=copy.deepcopy(current_cycle_deterministic_numeric_guidance),
    solved_model_input_json=copy.deepcopy((unified_convergence_context or {}).get("current_model_input_json") or {}),
    solved_finmo_json=copy.deepcopy((unified_convergence_context or {}).get("current_finmo_json") or {}),
  )
  retry_scope_payload = copy.deepcopy(raw_retry_scope_payload)
  scoped_numeric_solver_contract = _subset_numeric_solver_contract(
    numeric_solver_contract=copy.deepcopy(full_numeric_solver_contract),
    retry_scope_payload=copy.deepcopy(retry_scope_payload),
  )
  scoped_numeric_solver_contract = _with_shape_sensitive_solver_contract_policy(
    copy.deepcopy(scoped_numeric_solver_contract)
  )
  allowed_lever_ids = [
    str(item or "").strip()
    for item in (
      (((scoped_numeric_solver_contract or {}).get("writable_lever_catalog", {}) or {}).get("lever_ids") or [])
      or (((unified_convergence_context or {}).get("writable_lever_catalog", {}) or {}).get("lever_ids") or [])
    )
    if str(item or "").strip()
  ]
  if not allowed_lever_ids:
    return {
      "contract_version": "unified_convergence_decision_v1",
      "status": "failed_missing_levers",
      "prompt_file": prompt_file,
      "selected_cash_strategy": selected_cash_strategy,
      "review_status": "not_completed",
      "detail": "No writable lever ids were available for unified convergence.",
      "decision": {},
    }
  fallback_writable_catalog = (
    (unified_convergence_context or {}).get("writable_lever_catalog")
    if isinstance((unified_convergence_context or {}).get("writable_lever_catalog"), dict)
    else {}
  )
  scoped_lever_catalog = copy.deepcopy(
    retry_scope_payload.get("lever_catalog_entries")
    or (fallback_writable_catalog.get("entries") or [])
  )
  scoped_lever_values = copy.deepcopy(
    retry_scope_payload.get("lever_current_values")
    or _solved_lever_value_map((unified_convergence_context or {}).get("current_model_input_json"))
  )
  scoped_model_payload = copy.deepcopy(
    retry_scope_payload.get("model_input_payload")
    or {
      "retry_scope": "full_horizon",
      "quarter_indexes": copy.deepcopy(retry_scope_payload.get("scoped_quarters") or []),
      "lever_ids": copy.deepcopy(allowed_lever_ids),
      "lever_current_values": copy.deepcopy(scoped_lever_values),
    }
  )
  scoped_finmo_rows = copy.deepcopy(
    retry_scope_payload.get("finmo_quarter_rows")
    or [
      row
      for row in (
        ((((unified_convergence_context or {}).get("current_finmo_json") or {}) if isinstance((unified_convergence_context or {}).get("current_finmo_json"), dict) else {}).get("quarter_rows") or [])
      )
      if isinstance(row, dict)
    ]
  )
  scoped_baseline_map = _solved_lever_value_map(
    (unified_convergence_context or {}).get("current_model_input_json")
  )
  full_horizon_quarter_count = _quarter_count_from_model_input(
    (unified_convergence_context or {}).get("current_model_input_json")
  )
  required_target_quarters = copy.deepcopy(retry_scope_payload.get("scoped_quarters") or [])
  effective_retry_context = copy.deepcopy(controller_retry_context or {})
  prompt_safe_numeric_guidance = copy.deepcopy(
    current_cycle_deterministic_numeric_guidance
  )
  current_guidance_issue_packets = [
    copy.deepcopy(item)
    for item in (current_cycle_deterministic_numeric_guidance.get("issue_repair_packets") or [])
    if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
  ]
  if current_guidance_issue_packets:
    scoped_numeric_solver_contract = copy.deepcopy(scoped_numeric_solver_contract)
    scoped_numeric_solver_contract["issue_target_packets"] = copy.deepcopy(current_guidance_issue_packets)
    scoped_numeric_solver_contract["active_issue_count"] = len(current_guidance_issue_packets)
  allowed_lever_ids = _scoped_unified_allowed_lever_ids(
    fallback_allowed_lever_ids=allowed_lever_ids,
    deterministic_numeric_guidance=prompt_safe_numeric_guidance,
  )
  effective_retry_context = _normalize_retry_requirements_to_allowed_scope(
    retry_context=effective_retry_context,
    allowed_lever_ids=allowed_lever_ids,
  )
  original_recommended_primary_target_metric_keys = _normalize_primary_target_metric_names(
    (scoped_numeric_solver_contract or {}).get("recommended_primary_target_metric_keys") or []
  )
  allowed_target_metric_names = _normalize_primary_target_metric_names(
    (scoped_numeric_solver_contract or {}).get("allowed_target_metric_ids")
    or original_recommended_primary_target_metric_keys
    or []
  )
  if isinstance(scoped_model_payload, dict):
    scoped_model_payload["lever_ids"] = copy.deepcopy(allowed_lever_ids)
  prompt_safe_unified_convergence_context = {
    "contract_version": str((unified_convergence_context or {}).get("contract_version") or "unified_convergence_context_v1"),
    "draft_id": str((unified_convergence_context or {}).get("draft_id") or "").strip(),
    "business_name": str((unified_convergence_context or {}).get("business_name") or "").strip(),
    "review_role": str((unified_convergence_context or {}).get("review_role") or "").strip(),
    "selected_cash_strategy": str((unified_convergence_context or {}).get("selected_cash_strategy") or "").strip(),
    "business_world_contract": copy.deepcopy((unified_convergence_context or {}).get("business_world_contract") or {}),
    "convergence_engine_contract": copy.deepcopy(
      (unified_convergence_context or {}).get("convergence_engine_contract")
      or _unified_convergence_engine_contract_payload()
    ),
    "resolved_issue_constraints": copy.deepcopy((unified_convergence_context or {}).get("resolved_issue_constraints") or []),
    "context_modules": copy.deepcopy((unified_convergence_context or {}).get("context_modules") or {}),
  }
  focus_issue_codes_for_contract = [
    str(item.get("issue_code") or "").strip().lower()
    for item in (prompt_safe_numeric_guidance.get("issue_repair_packets") or [])
    if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
  ]
  if focus_issue_codes_for_contract:
    effective_retry_context["required_open_issue_codes"] = copy.deepcopy(focus_issue_codes_for_contract)
  issue_coverage_requirements = [
    {
      "issue_code": str(item.get("issue_code") or "").strip().lower(),
      "metric_candidates": copy.deepcopy(_issue_packet_declared_target_metric_names(item)),
    }
    for item in (prompt_safe_numeric_guidance.get("issue_repair_packets") or [])
    if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
  ]
  if issue_coverage_requirements:
    effective_retry_context["issue_coverage_requirements"] = copy.deepcopy(issue_coverage_requirements)
  if allowed_lever_ids:
    effective_retry_context["required_issue_lever_ids"] = copy.deepcopy(allowed_lever_ids)
  effective_retry_context = _normalize_retry_requirements_to_allowed_scope(
    retry_context=effective_retry_context,
    allowed_lever_ids=allowed_lever_ids,
  )
  effective_retry_context.pop("required_primary_metric_candidates", None)
  effective_retry_context.pop("minimum_primary_metric_coverage_count", None)
  aligned_primary_target_metric_keys = [
    metric_name
    for metric_name in original_recommended_primary_target_metric_keys
    if not allowed_target_metric_names or metric_name in allowed_target_metric_names
  ]
  if aligned_primary_target_metric_keys:
    scoped_numeric_solver_contract = copy.deepcopy(scoped_numeric_solver_contract)
    scoped_numeric_solver_contract["recommended_primary_target_metric_keys"] = copy.deepcopy(
      aligned_primary_target_metric_keys[:_UNIFIED_PRIMARY_TARGET_MAX_COUNT]
    )
  required_quarter_target_scaffold = _solver_required_quarter_target_scaffold(
    copy.deepcopy(scoped_numeric_solver_contract),
    required_target_quarters=copy.deepcopy(required_target_quarters),
  )
  locked_target_fill_grid = _unified_target_fill_grid(
    required_target_quarters=copy.deepcopy(required_target_quarters),
    deterministic_numeric_guidance=copy.deepcopy(prompt_safe_numeric_guidance),
    baseline_finmo_rows=copy.deepcopy(scoped_finmo_rows),
  )
  locked_lever_control_fill_grid = _unified_lever_control_fill_grid(
    allowed_lever_ids=copy.deepcopy(allowed_lever_ids),
    target_quarters=copy.deepcopy(required_target_quarters),
    baseline_map=copy.deepcopy(scoped_baseline_map),
    full_horizon_quarter_count=full_horizon_quarter_count,
    deterministic_numeric_guidance=copy.deepcopy(prompt_safe_numeric_guidance),
    business_world_contract=copy.deepcopy((unified_convergence_context or {}).get("business_world_contract") or {}),
  )
  prompt_safe_retry_scope_payload = {
    "scope_mode": str(retry_scope_payload.get("scope_mode") or "").strip(),
    "focus_issue_codes": copy.deepcopy(retry_scope_payload.get("focus_issue_codes") or []),
    "scoped_quarters": copy.deepcopy(retry_scope_payload.get("scoped_quarters") or []),
    "scoped_lever_ids": copy.deepcopy(retry_scope_payload.get("scoped_lever_ids") or []),
    "prior_attempt_summary": copy.deepcopy(retry_scope_payload.get("prior_attempt_summary") or {}),
  }
  prompt_safe_retry_packet = {
    "issues_remaining": int(_safe_float((effective_retry_context or {}).get("issues_remaining")) or 0),
    "failed_quarters": copy.deepcopy((effective_retry_context or {}).get("failed_quarters") or []),
    "failed_metrics": copy.deepcopy((effective_retry_context or {}).get("failed_metrics") or []),
    "previous_levers_used": copy.deepcopy(
      (effective_retry_context or {}).get("previous_levers_used")
      or (effective_retry_context or {}).get("previous_allowed_lever_ids")
      or []
    ),
    "progress_status": str((effective_retry_context or {}).get("progress_status") or "").strip(),
    "last_failure_reason": str((effective_retry_context or {}).get("last_failure_reason") or "").strip(),
    "required_open_issue_codes": copy.deepcopy((effective_retry_context or {}).get("required_open_issue_codes") or []),
    "required_issue_lever_ids": copy.deepcopy((effective_retry_context or {}).get("required_issue_lever_ids") or []),
    "issue_coverage_requirements": copy.deepcopy(
      (effective_retry_context or {}).get("issue_coverage_requirements") or []
    ),
    "constraints": copy.deepcopy((effective_retry_context or {}).get("constraints") or []),
    "validation_correction_grid": _retry_validation_correction_grid(effective_retry_context),
  }
  prompt_safe_numeric_feedback = {
    "execution_state": str(effective_prior_numeric_feedback.get("execution_state") or "").strip(),
    "outcome_reason": str(effective_prior_numeric_feedback.get("outcome_reason") or "").strip(),
    "solver_invoked": bool(effective_prior_numeric_feedback.get("solver_invoked")),
    "solver_execution_state": str(effective_prior_numeric_feedback.get("solver_execution_state") or "").strip(),
    "quarters_with_all_targets_within_tolerance": int(_safe_float(effective_prior_numeric_feedback.get("quarters_with_all_targets_within_tolerance")) or 0),
    "quarters_with_target_misses": int(_safe_float(effective_prior_numeric_feedback.get("quarters_with_target_misses")) or 0),
    "target_metric_names": copy.deepcopy(effective_prior_numeric_feedback.get("target_metric_names") or []),
    "targeted_quarters": copy.deepcopy(effective_prior_numeric_feedback.get("targeted_quarters") or []),
    "allowed_lever_ids": copy.deepcopy(effective_prior_numeric_feedback.get("allowed_lever_ids") or []),
    "attempted_lever_families": copy.deepcopy(effective_prior_numeric_feedback.get("attempted_lever_families") or []),
    "target_verification": copy.deepcopy(effective_prior_numeric_feedback.get("target_verification") or {}),
    "quarter_fit_summary": copy.deepcopy(effective_prior_numeric_feedback.get("quarter_fit_summary") or []),
    "quarter_target_payloads": copy.deepcopy(effective_prior_numeric_feedback.get("quarter_target_payloads") or []),
  }
  prompt_safe_numeric_solver_contract = {
    "contract_version": str(scoped_numeric_solver_contract.get("contract_version") or "").strip(),
    "pass_name": str(scoped_numeric_solver_contract.get("pass_name") or "").strip(),
    "contract_scope": str(scoped_numeric_solver_contract.get("contract_scope") or "").strip(),
    "planning_mode_profile": copy.deepcopy(scoped_numeric_solver_contract.get("planning_mode_profile") or {}),
    "selected_cash_strategy": str(scoped_numeric_solver_contract.get("selected_cash_strategy") or "").strip(),
    "active_issue_count": int(_safe_float(scoped_numeric_solver_contract.get("active_issue_count")) or 0),
    "issue_target_packets": copy.deepcopy(scoped_numeric_solver_contract.get("issue_target_packets") or []),
    "recommended_primary_target_metric_keys": copy.deepcopy(
      scoped_numeric_solver_contract.get("recommended_primary_target_metric_keys") or []
    ),
    "allowed_target_metric_ids": copy.deepcopy(
      scoped_numeric_solver_contract.get("allowed_target_metric_ids") or []
    ),
    "solver_settings": copy.deepcopy(scoped_numeric_solver_contract.get("solver_settings") or {}),
    "lever_sensitivity_policy": copy.deepcopy(scoped_numeric_solver_contract.get("lever_sensitivity_policy") or {}),
  }
  planner_input_packet = _build_repair_guidance_payload(
    draft_id=str(draft_id).strip(),
    stage="convergence_running",
    status="running",
    planning_context_summary_json=copy.deepcopy(planning_context_summary or {}),
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    planning_mode_prompt_file=planning_mode_prompt_file,
    unified_convergence_context=copy.deepcopy(unified_convergence_context or {}),
    controller_resolution_state=copy.deepcopy(
      (unified_convergence_context or {}).get("controller_resolution_state")
      if isinstance((unified_convergence_context or {}).get("controller_resolution_state"), dict)
      else {}
    ),
    controller_retry_context=copy.deepcopy(controller_retry_context or {}),
    prior_numeric_feedback=copy.deepcopy(effective_prior_numeric_feedback),
    unified_convergence_cycle_count=copy.deepcopy(
      (controller_retry_context or {}).get("attempt_number")
      or (controller_retry_context or {}).get("cycle")
      or None
    ),
  )
  full_horizon_model_input_repair_contract = (
    planner_input_packet.get("full_horizon_model_input_repair_contract")
    if isinstance(planner_input_packet.get("full_horizon_model_input_repair_contract"), dict)
    else {}
  )
  issue_mapping_gate = (
    planner_input_packet.get("issue_mapping_gate")
    if isinstance(planner_input_packet.get("issue_mapping_gate"), dict)
    else {}
  )
  if str(issue_mapping_gate.get("status") or "").strip().lower() == "failed":
    first_error = (
      (issue_mapping_gate.get("errors") or [None])[0]
      if isinstance(issue_mapping_gate.get("errors"), list)
      else None
    )
    first_error_reason = (
      str((first_error or {}).get("reason") or "").strip()
      if isinstance(first_error, dict)
      else ""
    )
    return {
      "contract_version": "unified_convergence_decision_v1",
      "status": "failed_issue_mapping_contract",
      "prompt_file": prompt_file,
      "selected_cash_strategy": selected_cash_strategy,
      "review_status": "not_completed",
      "detail": (
        "issue_detection_unmapped_repair_path"
        + (f": {first_error_reason}" if first_error_reason else "")
      ),
      "decision": {},
      "issue_mapping_gate": copy.deepcopy(issue_mapping_gate),
      "full_horizon_model_input_repair_contract": copy.deepcopy(full_horizon_model_input_repair_contract),
    }
  required_model_input_repair_cell_ids = [
    str(item).strip()
    for item in (full_horizon_model_input_repair_contract.get("required_editable_cell_ids") or [])
    if str(item).strip()
  ]
  if not required_model_input_repair_cell_ids:
    return {
      "contract_version": "unified_convergence_decision_v1",
      "status": "failed_missing_full_horizon_model_input_contract",
      "prompt_file": prompt_file,
      "selected_cash_strategy": selected_cash_strategy,
      "review_status": "not_completed",
      "detail": (
        "Full-horizon model-input repair contract had no editable cells. "
        "Active convergence requires deterministic editable model_input cells."
      ),
      "decision": {},
      "full_horizon_model_input_repair_contract": copy.deepcopy(full_horizon_model_input_repair_contract),
    }
  planner_input_packet["gpt_contract_field_spec"] = _post_intake_contract_prompt_spec(
    "unified_convergence_decision"
  )
  locked_target_value_options = sorted(
    {
      int(round(float(value)))
      for row in (
        ((planner_input_packet.get("locked_target_fill_grid") or {}) if isinstance(planner_input_packet.get("locked_target_fill_grid"), dict) else {}).get("rows")
        or []
      )
      if isinstance(row, dict)
      for value in [
        row.get("recommended_target_value"),
        row.get("minimum_target_value") if row.get("minimum_target_value") == row.get("maximum_target_value") else None,
      ]
      if _safe_float(value) is not None
    }
  )
  payload = {
    "model": _openai_model(),
    "temperature": 0,
    "input": [
      {"role": "system", "content": [{"type": "input_text", "text": _load_unified_convergence_prompt()}]},
      {"role": "user", "content": [{"type": "input_text", "text": json.dumps(planner_input_packet, ensure_ascii=False)}]},
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": "unified_convergence_decision",
        "schema": _unified_convergence_schema(
          allowed_lever_ids,
          allowed_target_metric_names,
          allowed_mapped_target_quarters=required_target_quarters,
          allowed_target_values=locked_target_value_options,
          locked_target_rows=copy.deepcopy(
            ((planner_input_packet.get("locked_target_fill_grid") or {}) if isinstance(planner_input_packet.get("locked_target_fill_grid"), dict) else {}).get("rows")
            or []
          ),
          allowed_model_input_repair_cell_ids=copy.deepcopy(required_model_input_repair_cell_ids),
          allowed_model_input_repair_quarters=copy.deepcopy(
            full_horizon_model_input_repair_contract.get("horizon_quarters") or []
          ),
        ),
        "strict": True,
      }
    },
  }
  try:
    resp = _post_openai(
      url="https://api.openai.com/v1/responses",
      headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
      payload=payload,
    )
  except Exception as exc:
    return {
      "contract_version": "unified_convergence_decision_v1",
      "status": "failed_openai_request",
      "prompt_file": prompt_file,
      "selected_cash_strategy": selected_cash_strategy,
      "review_status": "not_completed",
      "detail": str(exc),
      "decision": {},
    }
  if resp.status_code >= 400:
    return {
      "contract_version": "unified_convergence_decision_v1",
      "status": "failed_openai_status",
      "prompt_file": prompt_file,
      "selected_cash_strategy": selected_cash_strategy,
      "review_status": "not_completed",
      "detail": resp.text[:1200],
      "decision": {},
    }
  parsed = _parse_responses_json_dict(resp.json())
  if not isinstance(parsed, dict):
    return {
      "contract_version": "unified_convergence_decision_v1",
      "status": "failed_parse",
      "prompt_file": prompt_file,
      "selected_cash_strategy": selected_cash_strategy,
      "review_status": "not_completed",
      "detail": "Unable to parse unified convergence JSON.",
      "decision": {},
    }
  parsed = _normalize_post_intake_contract_payload(
    contract_name="unified_convergence_decision",
    payload=parsed,
  )
  table_contract_errors = _post_intake_contract_payload_errors(
    contract_name="unified_convergence_decision",
    payload=parsed,
  )
  if table_contract_errors:
    return {
      "contract_version": "unified_convergence_decision_v1",
      "status": "failed_table_contract",
      "prompt_file": prompt_file,
      "selected_cash_strategy": selected_cash_strategy,
      "review_status": "not_completed",
      "detail": (
        "unified_convergence_decision_table_contract_invalid: "
        + "; ".join(str(item) for item in table_contract_errors[:20])
      ),
      "decision": copy.deepcopy(parsed),
      "gpt_contract_field_spec": _post_intake_contract_prompt_spec("unified_convergence_decision"),
    }
  table_horizon_errors = validate_unified_convergence_contract_horizon(parsed)
  if table_horizon_errors:
    return {
      "contract_version": "unified_convergence_decision_v1",
      "status": "failed_table_horizon_contract",
      "prompt_file": prompt_file,
      "selected_cash_strategy": selected_cash_strategy,
      "review_status": "not_completed",
      "detail": (
        "post_intake_contract_horizon_violation: "
        + "; ".join(str(item) for item in table_horizon_errors[:20])
      ),
      "decision": copy.deepcopy(parsed),
      "gpt_contract_field_spec": _post_intake_contract_prompt_spec("unified_convergence_decision"),
    }
  primary_metric_contract_error = _auto_repair_unified_primary_metric_coverage(
    parsed=parsed,
    numeric_solver_contract=copy.deepcopy(scoped_numeric_solver_contract),
    controller_retry_context=copy.deepcopy(effective_retry_context),
  )
  model_input_cell_contract_error = _validate_and_normalize_model_input_repair_cells(
    parsed=parsed,
    full_horizon_model_input_repair_contract=copy.deepcopy(full_horizon_model_input_repair_contract),
  )
  contract_error = (
    primary_metric_contract_error
    or model_input_cell_contract_error
    or _unified_convergence_decision_contract_error(
      parsed=parsed,
      required_target_quarters=copy.deepcopy(required_target_quarters),
      numeric_solver_contract=copy.deepcopy(scoped_numeric_solver_contract),
      deterministic_numeric_guidance=copy.deepcopy(prompt_safe_numeric_guidance),
      controller_retry_context=copy.deepcopy(effective_retry_context),
      baseline_map=copy.deepcopy(scoped_baseline_map),
      baseline_finmo_rows=copy.deepcopy(scoped_finmo_rows),
      business_world_contract=copy.deepcopy((unified_convergence_context or {}).get("business_world_contract") or {}),
      full_horizon_quarter_count=full_horizon_quarter_count,
    )
  )
  if contract_error:
    retry_payload = copy.deepcopy(payload)
    retry_payload["input"] = list(retry_payload.get("input") or []) + [
      {
        "role": "user",
        "content": [
          {
            "type": "input_text",
            "text": json.dumps(
              {
                "repair_contract_violation": str(contract_error).strip(),
                "required_target_quarters": copy.deepcopy(required_target_quarters),
                "required_quarter_target_scaffold": copy.deepcopy(required_quarter_target_scaffold),
                "locked_target_fill_grid": copy.deepcopy(locked_target_fill_grid),
                "locked_lever_control_fill_grid": copy.deepcopy(locked_lever_control_fill_grid),
                "full_horizon_model_input_repair_contract": copy.deepcopy(full_horizon_model_input_repair_contract),
                "recommended_primary_target_metric_keys": copy.deepcopy(
                  (scoped_numeric_solver_contract or {}).get("recommended_primary_target_metric_keys") or []
                ),
                "invalid_response_to_repair": copy.deepcopy(parsed),
                "issue_coverage_requirements": copy.deepcopy(
                  (effective_retry_context or {}).get("issue_coverage_requirements") or []
                ),
                "shape_sensitive_contract": copy.deepcopy(
                  (scoped_numeric_solver_contract or {}).get("lever_sensitivity_policy") or {}
                ),
                "business_world_contract": copy.deepcopy((unified_convergence_context or {}).get("business_world_contract") or {}),
                "instruction": (
                  "Repair the response contract. Return a valid unified convergence package with only the direct "
                  "primary_target_metric_names required by locked_target_fill_grid.allowed_target_metric_names, "
                  "provide numeric targets only for locked_target_fill_grid.required_target_quarters, and include target_tolerances for "
                  "every chosen primary target metric. Fill model_input_repair_cells exactly from "
                  "full_horizon_model_input_repair_contract.required_editable_cell_ids; those cells are the execution contract. "
                  "Use deterministic_numeric_guidance.driver_target_mapping_lookup as read-only driver-to-target context. "
                  "Keep realism, cash posture, and planning mode active as "
                  "guardrails, not as extra exact target lines. "
                  "The active issue in issue_coverage_requirements must still have direct "
                  "primary-target coverage. "
                  "Every chosen primary metric must appear in every targeted quarter row. Every targeted quarter must be present explicitly. "
                  "Do not add cells, omit cells, or edit locked/derived cells. "
                  "If the violation involves a shape-sensitive lever trajectory, repair that trajectory explicitly: "
                  "cover the full remaining horizon, do not drop by more than 50% quarter-to-quarter, do not jump by more than 2.5x quarter-to-quarter, "
                  "do not create snapback after a large build, and do not switch regime direction sharply without a believable transition. "
                  "For large structural increases, use a ramp or staged step-up over multiple quarters. "
                  "If the violation starts with stage_ramp_contract_, repair revenue targets and revenue-driver trajectories so every adjacent quarter pair respects business_world_contract.stage_ramp_contract. "
                  "Do not throw away the invalid response and start over blindly. Repair the invalid_response_to_repair directly, preserving valid fields. "
                  "Read shape_sensitive_contract directly and express the final allowed values in model_input_repair_cells."
                ),
              },
              ensure_ascii=False,
            ),
          }
        ],
      }
    ]
    try:
      retry_resp = _post_openai(
        url="https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        payload=retry_payload,
      )
    except Exception as exc:
      return {
        "contract_version": "unified_convergence_decision_v1",
        "status": "failed_contract_retry_request",
        "prompt_file": prompt_file,
        "selected_cash_strategy": selected_cash_strategy,
        "review_status": "not_completed",
        "detail": f"{contract_error} Retry error: {exc}",
        "decision": {},
      }
    if retry_resp.status_code >= 400:
      return {
        "contract_version": "unified_convergence_decision_v1",
        "status": "failed_contract_retry_status",
        "prompt_file": prompt_file,
        "selected_cash_strategy": selected_cash_strategy,
        "review_status": "not_completed",
        "detail": f"{contract_error} Retry status body: {retry_resp.text[:1200]}",
        "decision": {},
      }
    parsed_retry = _parse_responses_json_dict(retry_resp.json())
    if not isinstance(parsed_retry, dict):
      return {
        "contract_version": "unified_convergence_decision_v1",
        "status": "failed_contract_retry_parse",
        "prompt_file": prompt_file,
        "selected_cash_strategy": selected_cash_strategy,
        "review_status": "not_completed",
        "detail": f"{contract_error} Retry parse failed.",
        "decision": {},
      }
    parsed_retry = _normalize_post_intake_contract_payload(
      contract_name="unified_convergence_decision",
      payload=parsed_retry,
    )
    retry_table_contract_errors = _post_intake_contract_payload_errors(
      contract_name="unified_convergence_decision",
      payload=parsed_retry,
    )
    retry_table_horizon_errors = validate_unified_convergence_contract_horizon(parsed_retry)
    if retry_table_contract_errors or retry_table_horizon_errors:
      return {
        "contract_version": "unified_convergence_decision_v1",
        "status": "failed_contract_retry_table_contract",
        "prompt_file": prompt_file,
        "selected_cash_strategy": selected_cash_strategy,
        "review_status": "not_completed",
        "detail": (
          "retry unified convergence contract did not pass SQL contract lookup validation: "
          + "; ".join(str(item) for item in (retry_table_contract_errors + retry_table_horizon_errors)[:20])
        ),
        "decision": copy.deepcopy(parsed_retry),
        "gpt_contract_field_spec": _post_intake_contract_prompt_spec("unified_convergence_decision"),
      }
    retry_primary_metric_contract_error = _auto_repair_unified_primary_metric_coverage(
      parsed=parsed_retry,
      numeric_solver_contract=copy.deepcopy(scoped_numeric_solver_contract),
      controller_retry_context=copy.deepcopy(effective_retry_context),
    )
    retry_model_input_cell_contract_error = _validate_and_normalize_model_input_repair_cells(
      parsed=parsed_retry,
      full_horizon_model_input_repair_contract=copy.deepcopy(full_horizon_model_input_repair_contract),
    )
    retry_contract_error = (
      retry_primary_metric_contract_error
      or retry_model_input_cell_contract_error
      or _unified_convergence_decision_contract_error(
        parsed=parsed_retry,
        required_target_quarters=copy.deepcopy(required_target_quarters),
        numeric_solver_contract=copy.deepcopy(scoped_numeric_solver_contract),
        deterministic_numeric_guidance=copy.deepcopy(prompt_safe_numeric_guidance),
        controller_retry_context=copy.deepcopy(effective_retry_context),
        baseline_map=copy.deepcopy(scoped_baseline_map),
        baseline_finmo_rows=copy.deepcopy(scoped_finmo_rows),
        business_world_contract=copy.deepcopy((unified_convergence_context or {}).get("business_world_contract") or {}),
        full_horizon_quarter_count=full_horizon_quarter_count,
      )
    )
    if retry_contract_error:
      return {
        "contract_version": "unified_convergence_decision_v1",
        "status": "failed_invalid_contract",
        "prompt_file": prompt_file,
        "selected_cash_strategy": selected_cash_strategy,
        "review_status": "not_completed",
        "detail": str(retry_contract_error).strip(),
        "decision": {},
      }
    parsed = parsed_retry
  return {
    "contract_version": "unified_convergence_decision_v1",
    "numeric_resolution_contract": _unified_solver_target_contract_spec_payload(),
    "numeric_solver_contract": copy.deepcopy(scoped_numeric_solver_contract),
    "retry_scope_payload": copy.deepcopy(retry_scope_payload),
    "status": "completed",
    "prompt_file": prompt_file,
    "selected_cash_strategy": selected_cash_strategy,
    "review_status": "completed",
    "detail": "",
    "decision": parsed,
    "full_horizon_model_input_repair_contract": copy.deepcopy(full_horizon_model_input_repair_contract),
  }

def _quarter_count_from_model_input(model_input_json: Optional[Dict[str, Any]]) -> int:
  model_input = model_input_json if isinstance(model_input_json, dict) else {}
  periods = [item for item in (model_input.get("periods") or []) if isinstance(item, dict)]
  if not periods:
    return 20
  live_quarters = [
    int(_safe_float(item.get("quarter")) or 0)
    for item in periods
    if (
      not bool(item.get("is_stub"))
      and int(_safe_float(item.get("quarter")) or 0) >= 1
    )
  ]
  if live_quarters:
    return max(live_quarters)
  non_stub_count = len([item for item in periods if not bool(item.get("is_stub"))])
  if non_stub_count > 0:
    return max(1, non_stub_count)
  return max(1, len(periods))

def _normalized_quarter_window(start_q: Any, end_q: Any, *, quarter_count: int) -> Tuple[int, int]:
  start = int(_safe_float(start_q) or 1)
  end = int(_safe_float(end_q) or start)
  start = max(1, min(int(quarter_count or 1), start))
  end = max(start, min(int(quarter_count or 1), end))
  return start, end

def _solved_lever_value_map(model_input_json: Optional[Dict[str, Any]]) -> Dict[str, List[float]]:
  model_input = model_input_json if isinstance(model_input_json, dict) else {}
  sections = model_input.get("sections") if isinstance(model_input.get("sections"), dict) else {}
  lever_map: Dict[str, List[float]] = {}

  def _live_values(row_values: Any) -> List[float]:
    values = [float(_safe_float(value) or 0.0) for value in (row_values or [])]
    if len(values) >= 21:
      return values[1:21]
    return values[:20]

  for row in [item for item in (sections.get("revenue") or []) if isinstance(item, dict)]:
    lever_id = str(row.get("lever_id") or "").strip()
    if lever_id:
      lever_map[lever_id] = _live_values(row.get("values") or [])
  for section_name in ("expenses", "balance_sheet"):
    for row in [item for item in (sections.get(section_name) or []) if isinstance(item, dict)]:
      lever_id = str(row.get("lever_id") or "").strip()
      if lever_id:
        lever_map[lever_id] = _live_values(row.get("values") or [])
  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  for row in [item for item in (schedules.get("rows") or []) if isinstance(item, dict)]:
    lever_id = str(row.get("lever_id") or "").strip()
    if lever_id:
      lever_map[lever_id] = _live_values(row.get("values") or [])
  return lever_map

def _solved_lever_stub_value_map(model_input_json: Optional[Dict[str, Any]]) -> Dict[str, float]:
  model_input = model_input_json if isinstance(model_input_json, dict) else {}
  sections = model_input.get("sections") if isinstance(model_input.get("sections"), dict) else {}
  stub_map: Dict[str, float] = {}

  def _stub_value(row_values: Any) -> Optional[float]:
    values = [float(_safe_float(value) or 0.0) for value in (row_values or [])]
    if not values:
      return None
    return float(values[0])

  for row in [item for item in (sections.get("revenue") or []) if isinstance(item, dict)]:
    lever_id = str(row.get("lever_id") or "").strip()
    stub_value = _stub_value(row.get("values") or [])
    if lever_id and stub_value is not None:
      stub_map[lever_id] = float(stub_value)
  for section_name in ("expenses", "balance_sheet"):
    for row in [item for item in (sections.get(section_name) or []) if isinstance(item, dict)]:
      lever_id = str(row.get("lever_id") or "").strip()
      stub_value = _stub_value(row.get("values") or [])
      if lever_id and stub_value is not None:
        stub_map[lever_id] = float(stub_value)
  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  for row in [item for item in (schedules.get("rows") or []) if isinstance(item, dict)]:
    lever_id = str(row.get("lever_id") or "").strip()
    stub_value = _stub_value(row.get("values") or [])
    if lever_id and stub_value is not None:
      stub_map[lever_id] = float(stub_value)
  return stub_map

def _lever_review_catalog_entry_map(
  writable_lever_catalog: Any,
) -> Dict[str, Dict[str, Any]]:
  entries = (
    writable_lever_catalog.get("entries")
    if isinstance(writable_lever_catalog, dict) and isinstance(writable_lever_catalog.get("entries"), list)
    else writable_lever_catalog
    if isinstance(writable_lever_catalog, list)
    else []
  )
  return {
    str(item.get("lever_id") or "").strip(): copy.deepcopy(item)
    for item in entries
    if isinstance(item, dict) and str(item.get("lever_id") or "").strip()
  }

def _payroll_row_from_model_input(model_input_json: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  expenses = sections.get("expenses") if isinstance(sections.get("expenses"), list) else []
  for row in expenses:
    if isinstance(row, dict) and str(row.get("label") or "").strip() == "Payroll":
      return row
  return None

def _subset_lever_value_map(
  lever_value_map: Optional[Dict[str, List[float]]],
  lever_ids: Optional[List[str]],
  quarter_indexes: Optional[List[int]] = None,
) -> Dict[str, List[float]]:
  lever_map = lever_value_map if isinstance(lever_value_map, dict) else {}
  lever_id_set = {
    str(item).strip()
    for item in (lever_ids or [])
    if str(item).strip()
  }
  quarter_list = [
    int(_safe_float(item) or 0)
    for item in (quarter_indexes or [])
    if int(_safe_float(item) or 0) >= 1
  ]
  out: Dict[str, List[float]] = {}
  for lever_id, values in lever_map.items():
    if lever_id_set and lever_id not in lever_id_set:
      continue
    normalized_values = [float(_safe_float(value) or 0.0) for value in (values or [])]
    if quarter_list:
      out[lever_id] = [
        float(normalized_values[quarter_index - 1] if 0 <= quarter_index - 1 < len(normalized_values) else 0.0)
        for quarter_index in quarter_list
      ]
    else:
      out[lever_id] = normalized_values[:20]
  return out

def _finmo_rows_for_quarters(
  finmo_json: Optional[Dict[str, Any]],
  quarter_indexes: Optional[List[int]],
) -> List[Dict[str, Any]]:
  quarter_set = {
    int(_safe_float(item) or 0)
    for item in (quarter_indexes or [])
    if int(_safe_float(item) or 0) >= 1
  }
  rows = [
    row for row in ((finmo_json or {}).get("quarter_rows") or [])
    if isinstance(row, dict)
  ]
  if not quarter_set:
    return copy.deepcopy(rows)
  return [
    copy.deepcopy(row)
    for row in rows
    if int(_safe_float(row.get("quarter_index")) or 0) in quarter_set
  ]

def _window_values(values: List[float], *, start_q: int, end_q: int) -> List[float]:
  if not values:
    return []
  start_idx = max(0, int(start_q) - 1)
  end_idx = max(start_idx, int(end_q) - 1)
  return [float(_safe_float(item) or 0.0) for item in values[start_idx:end_idx + 1]]

def _baseline_window_summary(values: List[float], *, start_q: int, end_q: int) -> Dict[str, Any]:
  window = _window_values(values, start_q=start_q, end_q=end_q)
  if not window:
    return {
      "quarter_start": start_q,
      "quarter_end": end_q,
      "value_start": 0.0,
      "value_end": 0.0,
      "value_min": 0.0,
      "value_max": 0.0,
    }
  return {
    "quarter_start": start_q,
    "quarter_end": end_q,
    "value_start": window[0],
    "value_end": window[-1],
    "value_min": min(window),
    "value_max": max(window),
  }

def _translate_unified_convergence_adjustment(
  *,
  adjustment: Dict[str, Any],
  baseline_map: Dict[str, List[float]],
  quarter_count: int,
  shape_sensitive_required_quarters: Optional[List[int]] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
  lever_id = str(adjustment.get("lever_id") or "").strip()
  required_quarters = [
    int(_safe_float(item) or 0)
    for item in (shape_sensitive_required_quarters or [])
    if int(_safe_float(item) or 0) >= 1
  ]
  if lever_id and required_quarters:
    trajectory_values = _shape_sensitive_trajectory_values_by_quarter(adjustment)
    if not trajectory_values:
      return [], f"{lever_id} shape-sensitive trajectory is missing values or trajectory_values"
    baseline_values = baseline_map.get(lever_id)
    if not baseline_values:
      return [], f"unknown lever_id {lever_id}"
    translated_controls: List[Dict[str, Any]] = []
    for quarter_index in required_quarters:
      if quarter_index not in trajectory_values:
        return [], f"{lever_id} values or trajectory_values is missing Q{quarter_index}"
      translated_controls.append(
        {
          "lever_id": lever_id,
          "section": str(adjustment.get("section") or "").strip(),
          "direction": str(adjustment.get("direction") or "").strip().lower(),
          "control_mode": "exact",
          "timing_start_q": quarter_index,
          "timing_end_q": quarter_index,
          "baseline_window": _baseline_window_summary(
            baseline_values,
            start_q=quarter_index,
            end_q=quarter_index,
          ),
          "business_reason": str(
            adjustment.get("trajectory_rationale")
            or adjustment.get("rationale")
            or adjustment.get("business_reason")
            or ""
          ).strip(),
          "linked_action_effect": str(adjustment.get("linked_action_effect") or "").strip(),
          "mapped_repair_targets": _normalize_unified_mapped_repair_targets(
            adjustment.get("mapped_repair_targets") or []
          ),
          "shape_type": str(adjustment.get("shape_type") or "").strip().lower(),
          "exact_value": (
            int(round(float(trajectory_values.get(quarter_index) or 0.0)))
            if float(int(round(float(trajectory_values.get(quarter_index) or 0.0))))
            == float(trajectory_values.get(quarter_index) or 0.0)
            else round(float(trajectory_values.get(quarter_index) or 0.0), 2)
          ),
          "min_value": None,
          "max_value": None,
        }
      )
    return translated_controls, None
  translated, warning = _translate_cash_strategy_adjustment(
    adjustment=adjustment,
    baseline_map=baseline_map,
    quarter_count=quarter_count,
  )
  if warning:
    return [], warning
  return ([translated] if translated else []), None

def _scoped_unified_allowed_lever_ids(
  *,
  fallback_allowed_lever_ids: Optional[List[str]],
  deterministic_numeric_guidance: Optional[Dict[str, Any]],
) -> List[str]:
  fallback_ids = [
    str(item).strip()
    for item in (fallback_allowed_lever_ids or [])
    if str(item).strip()
  ]
  guidance = deterministic_numeric_guidance if isinstance(deterministic_numeric_guidance, dict) else {}
  issue_packets = [
    item
    for item in (guidance.get("issue_repair_packets") or [])
    if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
  ]
  focus_issue_code_set = {
    str(item.get("issue_code") or "").strip().lower()
    for item in issue_packets
    if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
  }
  scoped_ids: List[str] = []
  for issue_packet in issue_packets:
    for lever_id in _issue_packet_mapped_driver_lever_ids(issue_packet):
      lever = str(lever_id).strip()
      if lever and lever in fallback_ids and lever not in scoped_ids:
        scoped_ids.append(lever)
  if issue_packets:
    return scoped_ids
  for scaffold in (guidance.get("lever_band_scaffold") or []):
    if not isinstance(scaffold, dict):
      continue
    lever = str(scaffold.get("lever_id") or "").strip()
    if not lever or lever not in fallback_ids or lever in scoped_ids:
      continue
    covered_issue_codes = {
      str(item).strip().lower()
      for item in (scaffold.get("covered_issue_codes") or [])
      if str(item).strip()
    }
    if focus_issue_code_set and covered_issue_codes and covered_issue_codes.isdisjoint(focus_issue_code_set):
      continue
    scoped_ids.append(lever)
  return fallback_ids

def _build_unified_convergence_pass_plan(
  *,
  draft_id: str = "",
  business_facts: Optional[Dict[str, Any]] = None,
  planning_mode: Any = "",
  planning_mode_reason: Any = "",
  review_decision_payload: Optional[Dict[str, Any]] = None,
  solved_model_input_json: Optional[Dict[str, Any]] = None,
  solved_finmo_json: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  people_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  marketing_model_json: Optional[Dict[str, Any]] = None,
  numeric_solver_contract: Optional[Dict[str, Any]] = None,
  deterministic_numeric_guidance: Optional[Dict[str, Any]] = None,
  stage_ramp_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  review_payload = review_decision_payload if isinstance(review_decision_payload, dict) else {}
  scoped_contract = (
    review_payload.get("numeric_solver_contract")
    if isinstance(review_payload.get("numeric_solver_contract"), dict)
    else {}
  )
  solver_contract = (
    copy.deepcopy(scoped_contract)
    if isinstance(scoped_contract, dict) and scoped_contract
    else copy.deepcopy(numeric_solver_contract)
    if isinstance(numeric_solver_contract, dict)
    else {}
  )
  selected_cash_strategy = _resolved_cash_strategy(financials_json, review_payload)
  review_status = str(review_payload.get("status") or "").strip()
  prompt_file = str(review_payload.get("prompt_file") or "").strip()
  if review_status != "completed":
    return {
      "contract_version": "unified_convergence_pass_plan_v1",
      "status": "skipped_review_not_completed",
      "selected_cash_strategy": selected_cash_strategy,
      "prompt_file": prompt_file,
      "review_status": review_status,
      "numeric_solver_contract": solver_contract,
      "translated_action_packages": [],
      "translation_warnings": [],
      "touched_lever_ids": [],
      "next_step": "wait_for_completed_unified_convergence_review",
    }

  decision = review_payload.get("decision") if isinstance(review_payload.get("decision"), dict) else {}
  business_world_contract = _business_world_contract(
    business_facts=copy.deepcopy(business_facts or {}),
    ops_json=copy.deepcopy(ops_json or {}),
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    stage_ramp_contract=copy.deepcopy(stage_ramp_contract)
    if isinstance(stage_ramp_contract, dict)
    else None,
  )
  raw_lever_selection = list(
    dict.fromkeys(
      [
        str(item).strip()
        for item in (decision.get("lever_selection") or [])
        if str(item).strip()
      ]
    )
  )
  payroll_selection_requested = "expenses::Payroll" in raw_lever_selection
  lever_selection = [
    lever_id for lever_id in raw_lever_selection
    if lever_id != "expenses::Payroll"
  ]
  primary_target_metric_names = _unified_required_target_metric_keys(
    decision_payload=decision,
    numeric_solver_contract=solver_contract,
  )
  target_tolerances = _merge_required_target_tolerances(
    decision.get("target_tolerances") or [],
    primary_target_metric_names,
  )
  targets_by_quarter = _augment_solver_quarter_target_metrics(
    raw_targets=decision.get("targets_by_quarter") or [],
    required_metric_names=primary_target_metric_names,
    numeric_solver_contract=copy.deepcopy(solver_contract),
  )
  targeted_quarters = sorted(
    {
      int(_safe_float(item.get("quarter_index")) or 0)
      for item in targets_by_quarter
      if int(_safe_float(item.get("quarter_index")) or 0) >= 1
    }
  )
  quarter_count = _quarter_count_from_model_input(solved_model_input_json)
  baseline_map = _solved_lever_value_map(solved_model_input_json)
  model_input_repair_cells = [
    copy.deepcopy(item)
    for item in (decision.get("model_input_repair_cells") or [])
    if isinstance(item, dict)
  ]
  model_input_repair_exact_updates = _exact_updates_from_model_input_repair_cells(
    model_input_repair_cells=copy.deepcopy(model_input_repair_cells)
  )
  model_input_repair_contract = (
    copy.deepcopy(review_payload.get("full_horizon_model_input_repair_contract"))
    if isinstance(review_payload.get("full_horizon_model_input_repair_contract"), dict)
    else {}
  )
  guidance_packet = deterministic_numeric_guidance if isinstance(deterministic_numeric_guidance, dict) else {}
  writable_lever_catalog = _build_writable_lever_review_catalog(solved_model_input_json)
  leverage_catalog_map = _lever_review_catalog_entry_map(writable_lever_catalog)
  lever_bound_lookup = _deterministic_lever_bound_lookup(guidance_packet)
  explicit_lever_adjustments = [
    item for item in (decision.get("lever_adjustments") or []) if isinstance(item, dict)
  ]
  explicit_lever_adjustment_map = {
    str(item.get("lever_id") or "").strip(): copy.deepcopy(item)
    for item in explicit_lever_adjustments
    if str(item.get("lever_id") or "").strip()
  }
  explicit_lever_ids = {
    str(item.get("lever_id") or "").strip()
    for item in explicit_lever_adjustments
    if str(item.get("lever_id") or "").strip()
  }
  auto_lever_adjustments = _autofill_unified_lever_adjustments_from_guidance(
    lever_selection=lever_selection,
    deterministic_numeric_guidance=guidance_packet,
    primary_target_metric_names=primary_target_metric_names,
    targeted_quarters=targeted_quarters,
  )
  auto_lever_adjustments = [
    item for item in auto_lever_adjustments
    if (
      str(item.get("lever_id") or "").strip()
      and str(item.get("lever_id") or "").strip() not in explicit_lever_ids
      and _shape_sensitive_lever_class(str(item.get("lever_id") or "").strip()) != "remaining_horizon_required"
    )
  ]
  effective_lever_adjustments = explicit_lever_adjustments + auto_lever_adjustments
  shape_sensitive_requirements = _shape_sensitive_remaining_horizon_requirements(
    selected_lever_ids=copy.deepcopy(lever_selection),
    targeted_quarters=copy.deepcopy(targeted_quarters),
    numeric_solver_contract=copy.deepcopy(solver_contract),
    lever_adjustments=copy.deepcopy(effective_lever_adjustments),
    baseline_map=copy.deepcopy(baseline_map),
    full_horizon_quarter_count=quarter_count,
  )
  lever_bound_validation_details: List[Dict[str, Any]] = []
  for adjustment in effective_lever_adjustments:
    lever_id = str(adjustment.get("lever_id") or "").strip()
    lever_bound_validation_details.extend(
      _pre_solver_lever_bound_validation_details(
        adjustment=adjustment,
        lever_bound_lookup=lever_bound_lookup,
        required_target_quarters=(
          copy.deepcopy(shape_sensitive_requirements.get("required_target_quarters") or [])
          if lever_id in (shape_sensitive_requirements.get("required_lever_ids") or [])
          else None
        ),
        baseline_map=baseline_map,
      )
    )
  payroll_derivation_validation = _validate_payroll_derivation_contract(
    model_input_json=copy.deepcopy(solved_model_input_json or {}),
    business_world_contract=copy.deepcopy(business_world_contract),
  )
  warnings: List[str] = []
  if payroll_selection_requested:
    warnings.append(
      "unified_cycle: Payroll is revenue/OEWS-derived and must not be selected as a writable convergence lever."
    )
    lever_bound_validation_details.append(
      {
        "error": "payroll_is_derived_not_writable",
        "lever_id": "expenses::Payroll",
        "quarter": None,
        "previous_value": None,
        "current_value": None,
        "reason": (
          "Payroll is revenue/OEWS-derived in the model-input layer and must not be selected as a writable convergence lever."
        ),
        "validation_category": "internal_consistency",
      }
    )
  eligible_lever_ids = _solver_contract_eligible_lever_ids(
    numeric_solver_contract=solver_contract,
    target_quarters=targeted_quarters,
  )
  eligible_lookup = set(eligible_lever_ids)
  translated_controls: List[Dict[str, Any]] = []
  missing_explicit_capital_adjustment_lever_ids = [
    lever_id
    for lever_id in lever_selection
    if lever_id in _UNIFIED_EXPLICIT_CAPITAL_ALLOCATION_LEVER_IDS
    and lever_id not in explicit_lever_ids
  ]
  shape_sensitive_validation_errors: List[str] = []
  shape_sensitive_validation_details: List[Dict[str, Any]] = []
  for lever_id in (shape_sensitive_requirements.get("required_lever_ids") or []):
    adjustment = explicit_lever_adjustment_map.get(lever_id)
    if adjustment is None:
      missing_detail = {
        "error": _shape_sensitive_trajectory_error_code(lever_id),
        "lever_id": lever_id,
        "quarter": min(shape_sensitive_requirements.get("required_target_quarters") or [0]) or None,
        "previous_value": None,
        "current_value": None,
        "reason": f"{lever_id} is shape-sensitive and requires explicit GPT-authored values or trajectory_values.",
        "validation_category": "horizon_coverage",
      }
      shape_sensitive_validation_details.append(copy.deepcopy(missing_detail))
      shape_sensitive_validation_errors.append(
        str(missing_detail.get("reason") or "").strip()
      )
      continue
    path_detail = _shape_sensitive_path_validation_detail(
      lever_id=lever_id,
      adjustment=adjustment,
      required_target_quarters=copy.deepcopy(
        shape_sensitive_requirements.get("required_target_quarters") or []
      ),
    )
    if path_detail:
      shape_sensitive_validation_details.append(copy.deepcopy(path_detail))
      shape_sensitive_validation_errors.append(
        _shape_sensitive_path_validation_error(
          lever_id=lever_id,
          adjustment=adjustment,
          required_target_quarters=copy.deepcopy(
            shape_sensitive_requirements.get("required_target_quarters") or []
          ),
        )
        or str(path_detail.get("reason") or "").strip()
      )
  for adjustment in effective_lever_adjustments:
    lever_id = str(adjustment.get("lever_id") or "").strip()
    translated_items, warning = _translate_unified_convergence_adjustment(
      adjustment=adjustment,
      baseline_map=baseline_map,
      quarter_count=quarter_count,
      shape_sensitive_required_quarters=(
        copy.deepcopy(shape_sensitive_requirements.get("required_target_quarters") or [])
        if lever_id in (shape_sensitive_requirements.get("required_lever_ids") or [])
        else None
      ),
    )
    if warning:
      warnings.append(f"unified_cycle: {warning}")
      continue
    for translated in translated_items:
      lever_id = str((translated or {}).get("lever_id") or "").strip()
      if eligible_lookup and lever_id not in eligible_lookup:
        warnings.append(
          f"unified_cycle: lever_id {lever_id} is outside the deterministic eligible lever scope"
        )
        continue
      translated_controls.append(translated)
  if model_input_repair_exact_updates:
    editable_repair_cell_by_id = {
      str(item.get("cell_id") or "").strip(): item
      for item in (model_input_repair_contract.get("editable_cells") or [])
      if isinstance(item, dict) and str(item.get("cell_id") or "").strip()
    }
    for update in model_input_repair_exact_updates:
      lever_id = str(update.get("lever_id") or "").strip()
      quarter_index = int(_safe_float(update.get("quarter_index")) or 0)
      exact_value = _safe_float(update.get("exact_value"))
      source_cell_id = str(update.get("source_cell_id") or "").strip()
      source_cell = editable_repair_cell_by_id.get(source_cell_id) or {}
      if not lever_id or quarter_index < 1 or exact_value is None:
        continue
      if eligible_lookup and lever_id not in eligible_lookup:
        warnings.append(
          f"unified_cycle: model_input_repair_cell lever_id {lever_id} is outside the deterministic eligible lever scope"
        )
        continue
      translated_controls.append(
        {
          "lever_id": lever_id,
          "section": str((leverage_catalog_map.get(lever_id) or {}).get("section") or "").strip(),
          "direction": "exact_model_input_cell",
          "control_mode": "exact",
          "timing_start_q": quarter_index,
          "timing_end_q": quarter_index,
          "baseline_window": _baseline_window_summary(
            baseline_map.get(lever_id) or [],
            start_q=quarter_index,
            end_q=quarter_index,
          ),
          "business_reason": "Full-horizon model_input repair cell authored by GPT inside Python bounds.",
          "linked_action_effect": "direct_model_input_json_cell_update",
          "mapped_repair_targets": copy.deepcopy(
            source_cell.get("mapped_repair_targets") or []
          ),
          "shape_type": "full_horizon_model_input_cell",
          "exact_value": (
            int(round(float(exact_value)))
            if float(int(round(float(exact_value)))) == float(exact_value)
            else round(float(exact_value), 2)
          ),
          "min_value": None,
          "max_value": None,
          "source_cell_id": str(update.get("source_cell_id") or "").strip(),
        }
      )
  strategy_class = str(decision.get("strategy_class") or "").strip()
  strategy_rationale = str(decision.get("strategy_rationale") or "").strip()
  change_type = str(decision.get("change_type") or "").strip()
  progress_expectation = str(decision.get("progress_expectation") or "").strip()
  retry_reason = str(decision.get("retry_reason") or "").strip()
  strategy_class_lower = strategy_class.lower()
  boldness = "moderate"
  if any(token in strategy_class_lower for token in ("cleanup", "refine", "fine_tune", "fine-tune")):
    boldness = "light"
  elif any(token in strategy_class_lower for token in ("restructure", "reset", "capital", "holistic", "structural", "mixed")):
    boldness = "strong"

  translated_action_packages: List[Dict[str, Any]] = []
  if lever_selection and targets_by_quarter and targeted_quarters:
    derived_solver_allowed_lever_ids = _derive_solver_allowed_lever_ids(
      action={"solver_allowed_lever_ids": lever_selection},
      translated_controls=translated_controls,
      eligible_lever_ids=eligible_lever_ids,
    )
    if not translated_controls:
      warnings.append(
        "unified_cycle: no solver-ready lever controls were available from the explicit GPT-authored lever_adjustments."
      )
    translated_action_packages.append(
      {
        "action_id": "unified_cycle",
        "business_move": strategy_class or "unified_convergence_move",
        "why_now": strategy_rationale,
        "expected_visual_effect": progress_expectation,
        "coordination_notes": retry_reason,
        "timing_start_q": targeted_quarters[0],
        "timing_end_q": targeted_quarters[-1],
        "priority": 1,
        "boldness": boldness,
        "solver_allowed_lever_ids": derived_solver_allowed_lever_ids,
        "required_target_metric_keys": copy.deepcopy(primary_target_metric_names),
        "target_tolerances": copy.deepcopy(target_tolerances),
        "quarter_target_metrics": copy.deepcopy(targets_by_quarter),
        "translated_controls": copy.deepcopy(translated_controls),
      }
    )

  touched_lever_ids = _solver_ready_touched_lever_ids(translated_action_packages)
  status = "ready"
  next_step = "ready_for_unified_convergence_solver"
  if not targets_by_quarter:
    status = "ready_no_valid_solver_contract"
    next_step = "review_unified_targets_levers_and_bands_before_solver"
  elif missing_explicit_capital_adjustment_lever_ids:
    status = "ready_no_valid_solver_contract"
    next_step = "provide_explicit_capital_allocation_adjustments_before_solver"
    warnings.extend(
      [
        (
          "unified_cycle: "
          f"{lever_id} requires explicit GPT-authored lever_adjustments; capital allocation levers are not scaffolded."
        )
        for lever_id in missing_explicit_capital_adjustment_lever_ids
      ]
    )
  elif shape_sensitive_validation_errors:
    status = "ready_no_valid_solver_contract"
    next_step = "provide_full_remaining_horizon_trajectory_for_shape_sensitive_levers"
    warnings.extend([f"unified_cycle: {item}" for item in shape_sensitive_validation_errors])
  elif lever_bound_validation_details:
    status = "ready_no_valid_solver_contract"
    next_step = "bring_selected_levers_back_inside_deterministic_bounds_before_solver"
    warnings.extend(
      [
        f"unified_cycle: {str(item.get('reason') or '').strip()}"
        for item in lever_bound_validation_details
        if str(item.get("reason") or "").strip()
      ]
    )
  elif lever_selection and not translated_controls and not model_input_repair_exact_updates:
    status = "ready_no_valid_solver_contract"
    next_step = "review_unified_targets_levers_and_bands_before_solver"
    warnings.append(
      "unified_cycle: no solver-ready lever controls were available from the explicit GPT-authored lever_adjustments."
    )
  elif not touched_lever_ids and not model_input_repair_exact_updates:
    status = "ready_no_valid_solver_contract"
    next_step = "review_unified_targets_levers_and_bands_before_solver"
  elif payroll_derivation_validation.get("details"):
    status = "ready_no_valid_solver_contract"
    next_step = "fix_payroll_derivation_contract_before_solver"
    warnings.extend(
      [
        f"unified_cycle: {str(item.get('reason') or '').strip()}"
        for item in (payroll_derivation_validation.get("details") or [])
        if isinstance(item, dict) and str(item.get("reason") or "").strip()
      ]
    )
  elif guidance_packet.get("translation_failures"):
    status = "ready_no_valid_solver_contract"
    next_step = "fix_metric_to_lever_translation_before_solver"
    warnings.extend(
      [
        f"unified_cycle: {str(item.get('reason') or '').strip()}"
        for item in (guidance_packet.get("translation_failures") or [])
        if isinstance(item, dict) and str(item.get("reason") or "").strip()
      ]
    )
  pre_solver_validation_fail_flags: List[str] = []
  pre_solver_validation_errors: List[Dict[str, Any]] = []
  for detail in shape_sensitive_validation_details:
    pre_solver_validation_fail_flags.extend(
      _shape_sensitive_path_fail_fast_flags(validation_detail=detail)
    )
    pre_solver_validation_errors.append(
      {
        "error": str(detail.get("error") or "").strip() or "invalid_shape_sensitive_trajectory",
        "lever_id": str(detail.get("lever_id") or "").strip() or None,
        "quarter": int(_safe_float(detail.get("quarter")) or 0) or None,
        "previous_value": _safe_float(detail.get("previous_value")),
        "current_value": _safe_float(detail.get("current_value")),
        "reason": str(detail.get("reason") or "").strip() or None,
        "validation_category": str(detail.get("validation_category") or "").strip() or None,
      }
    )
  for detail in lever_bound_validation_details:
    pre_solver_validation_fail_flags.extend(
      _shape_sensitive_path_fail_fast_flags(validation_detail=detail)
    )
    pre_solver_validation_errors.append(
      {
        "error": str(detail.get("error") or "").strip() or "lever_bounds_violation",
        "lever_id": str(detail.get("lever_id") or "").strip() or None,
        "quarter": int(_safe_float(detail.get("quarter")) or 0) or None,
        "previous_value": _safe_float(detail.get("previous_value")),
        "current_value": _safe_float(detail.get("current_value")),
        "reason": str(detail.get("reason") or "").strip() or None,
        "validation_category": str(detail.get("validation_category") or "").strip() or None,
      }
    )
  for detail in (payroll_derivation_validation.get("details") or []):
    if not isinstance(detail, dict):
      continue
    pre_solver_validation_fail_flags.append("payroll_derivation_failed")
    error_code = str(detail.get("error") or "").strip()
    if error_code in _PAYROLL_DERIVATION_TEST_MODE_FAIL_FLAGS:
      pre_solver_validation_fail_flags.append(error_code)
    pre_solver_validation_errors.append(
      {
        "error": error_code or "payroll_derivation_failed",
        "lever_id": str(detail.get("lever_id") or "").strip() or "expenses::Payroll",
        "quarter": int(_safe_float(detail.get("quarter")) or 0) or None,
        "previous_value": _safe_float(detail.get("previous_value")),
        "current_value": _safe_float(detail.get("current_value")),
        "reason": str(detail.get("reason") or "").strip() or None,
        "validation_category": str(detail.get("validation_category") or "").strip() or "payroll_derivation",
      }
    )
  for detail in (guidance_packet.get("translation_failures") or []):
    if not isinstance(detail, dict):
      continue
    pre_solver_validation_fail_flags.append("metric_to_lever_translation_failed")
    error_code = str(detail.get("error") or "").strip()
    if error_code in _TRANSLATION_TEST_MODE_FAIL_FLAGS:
      pre_solver_validation_fail_flags.append(error_code)
    pre_solver_validation_errors.append(
      {
        "error": error_code or "metric_to_lever_translation_failed",
        "lever_id": str(detail.get("lever_id") or "").strip() or None,
        "quarter": int(_safe_float(detail.get("quarter")) or 0) or None,
        "previous_value": _safe_float(detail.get("current_metric_value")),
        "current_value": _safe_float(detail.get("metric_delta")),
        "reason": str(detail.get("reason") or "").strip() or None,
        "validation_category": str(detail.get("validation_category") or "").strip() or "translation_contract",
      }
    )
  if not targets_by_quarter:
    pre_solver_validation_fail_flags.append("trajectory_horizon_coverage_failed")
    pre_solver_validation_errors.append(
      {
        "error": "missing_targets_by_quarter",
        "lever_id": None,
        "quarter": None,
        "previous_value": None,
        "current_value": None,
        "reason": "targets_by_quarter must include numeric quarter targets for the current cycle.",
        "validation_category": "horizon_coverage",
      }
    )
  if lever_selection and not translated_controls and not model_input_repair_exact_updates:
    pre_solver_validation_fail_flags.append("internal_consistency_failed")
    pre_solver_validation_errors.append(
      {
        "error": "no_solver_ready_controls",
        "lever_id": None,
        "quarter": None,
        "previous_value": None,
        "current_value": None,
        "reason": "No solver-ready lever controls were available from explicit GPT-authored lever_adjustments.",
        "validation_category": "internal_consistency",
      }
    )
  if not touched_lever_ids and not model_input_repair_exact_updates:
    pre_solver_validation_fail_flags.append("internal_consistency_failed")
    pre_solver_validation_errors.append(
      {
        "error": "no_touched_levers",
        "lever_id": None,
        "quarter": None,
        "previous_value": None,
        "current_value": None,
        "reason": "Planner did not produce any touched levers for the active issue cycle.",
        "validation_category": "internal_consistency",
      }
    )
  if missing_explicit_capital_adjustment_lever_ids:
    pre_solver_validation_fail_flags.append("capital_allocation_adjustment_missing")
    for lever_id in missing_explicit_capital_adjustment_lever_ids:
      pre_solver_validation_errors.append(
        {
          "error": "capital_allocation_explicit_adjustment_required",
          "lever_id": lever_id,
          "quarter": min(targeted_quarters or [0]) or None,
          "previous_value": None,
          "current_value": None,
          "reason": (
            f"{lever_id} is a capital allocation lever and requires explicit GPT-authored "
            "lever_adjustments with real numeric controls. Python will not scaffold capital mix decisions."
          ),
          "validation_category": "internal_consistency",
        }
      )
  pre_solver_validation_fail_flags = list(
    dict.fromkeys([str(flag).strip() for flag in pre_solver_validation_fail_flags if str(flag).strip()])
  )
  pre_solver_validation = {
    "stage": "pre_solver_validation",
    "status": "failed" if pre_solver_validation_errors else "passed",
    "flags": copy.deepcopy(pre_solver_validation_fail_flags),
    "errors": copy.deepcopy(pre_solver_validation_errors),
  }

  return {
    "contract_version": "unified_convergence_pass_plan_v1",
    "status": status,
    "solver_phase_status": str(solver_contract.get("solver_phase_status") or "").strip(),
    "numeric_execution_phase": "unified_convergence",
    "selected_cash_strategy": selected_cash_strategy,
    "prompt_file": prompt_file,
    "review_status": review_status,
    "strategy_class": strategy_class,
    "change_type": change_type,
    "progress_expectation": progress_expectation,
    "strategy_rationale": strategy_rationale,
    "retry_reason": retry_reason,
    "focus_issue_codes": copy.deepcopy(
      [
        str(item).strip().lower()
        for item in (
          ((review_payload.get("retry_scope_payload") or {}).get("focus_issue_codes"))
          if isinstance(review_payload.get("retry_scope_payload"), dict)
          else []
        )
        if str(item).strip()
      ]
    ),
    "baseline_source": "unified_convergence_state",
    "numeric_solver_contract": solver_contract,
    "required_target_metric_keys": copy.deepcopy(primary_target_metric_names),
    "default_unspecified_lever_policy": {
      "mode": "lock_to_current_values",
      "scope": "all_unspecified_writable_levers",
      "rationale": "Unified convergence should only move levers explicitly selected by GPT for the current cycle.",
    },
    "translated_action_packages": translated_action_packages,
    "translated_control_count": sum(len(item.get("translated_controls") or []) for item in translated_action_packages),
    "touched_lever_ids": touched_lever_ids,
    "state_model": "single_model_input_truth_full_horizon_v1",
    "full_horizon_model_input_repair_contract": copy.deepcopy(model_input_repair_contract),
    "model_input_repair_cells": copy.deepcopy(model_input_repair_cells),
    "model_input_repair_exact_updates": copy.deepcopy(model_input_repair_exact_updates),
    "translation_warnings": warnings,
    "lever_adjustment_source": (
      "explicit_gpt"
      if explicit_lever_adjustments
      else "none"
    ),
    "explicit_lever_adjustment_count": len(explicit_lever_adjustments),
    "auto_generated_lever_adjustment_count": len(auto_lever_adjustments),
    "shape_sensitive_requirements": copy.deepcopy(shape_sensitive_requirements),
    "pre_solver_validation": copy.deepcopy(pre_solver_validation),
    "payroll_derivation_validation": copy.deepcopy(payroll_derivation_validation),
    "translation_failures": copy.deepcopy(guidance_packet.get("translation_failures") or []),
    "deterministic_guidance_metric_count": len(guidance_packet.get("metric_pressure_packets") or []),
    "deterministic_guidance_lever_count": len(guidance_packet.get("lever_band_scaffold") or []),
    "lever_selection": copy.deepcopy(lever_selection),
    "target_tolerances": copy.deepcopy(target_tolerances),
    "targets_by_quarter": copy.deepcopy(targets_by_quarter),
    "next_step": next_step,
  }

def _shape_sensitive_trajectory_values_schema() -> Dict[str, Any]:
  quarter_keys = [f"Q{quarter_index}" for quarter_index in range(1, 21)]
  return {
    "type": ["object", "null"],
    "additionalProperties": False,
    "properties": {
      quarter_key: {"type": ["number", "null"]}
      for quarter_key in quarter_keys
    },
    "required": quarter_keys,
  }

def _shape_sensitive_trajectory_values_by_quarter(
  adjustment: Optional[Dict[str, Any]],
) -> Dict[int, float]:
  item = adjustment if isinstance(adjustment, dict) else {}
  raw_values = (
    item.get("trajectory_values")
    if isinstance(item.get("trajectory_values"), dict)
    else item.get("values")
    if isinstance(item.get("values"), dict)
    else {}
  )
  out: Dict[int, float] = {}
  for quarter_index in range(1, 21):
    raw_value = _safe_float(raw_values.get(f"Q{quarter_index}"))
    if raw_value is None:
      continue
    out[quarter_index] = float(raw_value)
  return out

def _shape_sensitive_trajectory_error_code(lever_id: Any) -> str:
  lever = str(lever_id or "").strip().lower()
  tail = lever.split("::")[-1] if "::" in lever else lever
  sanitized = re.sub(r"[^a-z0-9]+", "_", tail).strip("_") or "trajectory"
  return f"invalid_{sanitized}_trajectory"

def _shape_sensitive_path_validation_detail(
  *,
  lever_id: Any,
  adjustment: Optional[Dict[str, Any]],
  required_target_quarters: Optional[List[int]],
) -> Optional[Dict[str, Any]]:
  lever = str(lever_id or "").strip()
  item = adjustment if isinstance(adjustment, dict) else {}
  shape_type = str(item.get("shape_type") or "").strip().lower()
  if shape_type not in _SHAPE_SENSITIVE_ALLOWED_SHAPE_TYPES:
    return {
      "error": _shape_sensitive_trajectory_error_code(lever),
      "lever_id": lever,
      "quarter": None,
      "previous_value": None,
      "current_value": None,
      "reason": (
        f"{lever} is shape-sensitive and requires shape_type in "
        f"{list(_SHAPE_SENSITIVE_ALLOWED_SHAPE_TYPES)}."
      ),
      "validation_category": "internal_consistency",
    }
  trajectory_values = _shape_sensitive_trajectory_values_by_quarter(item)
  required_quarters = [
    int(_safe_float(quarter_value) or 0)
    for quarter_value in (required_target_quarters or [])
    if int(_safe_float(quarter_value) or 0) >= 1
  ]
  if not required_quarters:
    return {
      "error": _shape_sensitive_trajectory_error_code(lever),
      "lever_id": lever,
      "quarter": None,
      "previous_value": None,
      "current_value": None,
      "reason": f"{lever} is shape-sensitive but required_target_quarters was empty.",
      "validation_category": "horizon_coverage",
    }
  missing_quarters = [
    quarter_index
    for quarter_index in required_quarters
    if quarter_index not in trajectory_values
  ]
  if missing_quarters:
    return {
      "error": _shape_sensitive_trajectory_error_code(lever),
      "lever_id": lever,
      "quarter": min(missing_quarters),
      "previous_value": None,
      "current_value": None,
      "reason": (
        f"{lever} is shape-sensitive and must provide values or trajectory_values for every remaining quarter. "
        f"Missing {missing_quarters}."
      ),
      "validation_category": "horizon_coverage",
    }
  prior_value: Optional[float] = None
  pre_prior_value: Optional[float] = None
  previous_change_direction: Optional[int] = None
  previous_change_ratio: Optional[float] = None
  for quarter_index in required_quarters:
    current_value = float(trajectory_values.get(quarter_index) or 0.0)
    if prior_value is not None:
      if (
        abs(prior_value) > 1e-9
        and prior_value > 0.0
        and current_value >= 0.0
        and current_value < prior_value * 0.50
      ):
        return {
          "error": _shape_sensitive_trajectory_error_code(lever),
          "lever_id": lever,
          "quarter": quarter_index,
          "previous_value": float(prior_value),
          "current_value": float(current_value),
          "reason": "unjustified discontinuity",
          "validation_category": "trajectory_continuity",
        }
      if (
        abs(prior_value) > 1e-9
        and prior_value > 0.0
        and current_value > prior_value * 2.50
      ):
        return {
          "error": _shape_sensitive_trajectory_error_code(lever),
          "lever_id": lever,
          "quarter": quarter_index,
          "previous_value": float(prior_value),
          "current_value": float(current_value),
          "reason": "unjustified regime jump",
          "validation_category": "trajectory_continuity",
        }
      if (
        pre_prior_value is not None
        and pre_prior_value > 0.0
        and prior_value > pre_prior_value * 1.25
        and current_value < prior_value * 0.75
      ):
        return {
          "error": _shape_sensitive_trajectory_error_code(lever),
          "lever_id": lever,
          "quarter": quarter_index,
          "previous_value": float(prior_value),
          "current_value": float(current_value),
          "reason": "unrealistic snapback",
          "validation_category": "trajectory_continuity",
        }
      if abs(prior_value) > 1e-9:
        change_ratio = float((current_value - prior_value) / abs(prior_value))
        direction = 1 if change_ratio > 0.0 else -1 if change_ratio < 0.0 else 0
        if (
          previous_change_direction is not None
          and previous_change_ratio is not None
          and direction != 0
          and previous_change_direction != 0
          and direction != previous_change_direction
          and abs(change_ratio) >= 0.25
          and abs(previous_change_ratio) >= 0.25
        ):
          return {
            "error": _shape_sensitive_trajectory_error_code(lever),
            "lever_id": lever,
            "quarter": quarter_index,
            "previous_value": float(prior_value),
            "current_value": float(current_value),
            "reason": "inconsistent regime switching",
            "validation_category": "internal_consistency",
          }
        previous_change_direction = direction
        previous_change_ratio = change_ratio
    pre_prior_value = prior_value
    prior_value = current_value
  return None

def _shape_sensitive_path_validation_error(
  *,
  lever_id: Any,
  adjustment: Optional[Dict[str, Any]],
  required_target_quarters: Optional[List[int]],
) -> Optional[str]:
  detail = _shape_sensitive_path_validation_detail(
    lever_id=lever_id,
    adjustment=adjustment,
    required_target_quarters=required_target_quarters,
  )
  if not isinstance(detail, dict) or not detail:
    return None
  lever = str(detail.get("lever_id") or lever_id or "").strip()
  quarter = int(_safe_float(detail.get("quarter")) or 0)
  previous_value = _safe_float(detail.get("previous_value"))
  current_value = _safe_float(detail.get("current_value"))
  reason = str(detail.get("reason") or "").strip()
  if previous_value is not None and current_value is not None and quarter >= 1:
    return (
      f"{lever} invalid trajectory at Q{quarter}: "
      f"{float(previous_value):.2f} -> {float(current_value):.2f}. {reason}"
    )
  if quarter >= 1:
    return f"{lever} invalid trajectory at Q{quarter}: {reason}"
  return f"{lever} invalid trajectory: {reason}"

def _baseline_map_quarter_count(
  baseline_map: Optional[Dict[str, List[float]]],
) -> int:
  baseline = baseline_map if isinstance(baseline_map, dict) else {}
  quarter_counts = [
    len(item)
    for item in baseline.values()
    if isinstance(item, list)
  ]
  return max(quarter_counts or [0])

def _deterministic_lever_bound_lookup(
  guidance_packet: Optional[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
  guidance = guidance_packet if isinstance(guidance_packet, dict) else {}
  lookup: Dict[str, Dict[str, Any]] = {}
  for item in (guidance.get("lever_band_scaffold") or []):
    if not isinstance(item, dict):
      continue
    lever_id = str(item.get("lever_id") or "").strip()
    if not lever_id:
      continue
    mapping_entry = post_intake_driver_target_mapping_entry(lever_id) or {}
    if str(mapping_entry.get("control_owner") or "").strip().lower() != "gpt_editable":
      continue
    lookup[lever_id] = {
      "min_value": _safe_float(item.get("suggested_min_value")),
      "max_value": _safe_float(item.get("suggested_max_value")),
      "value_kind": str(item.get("value_kind") or "").strip() or None,
      "input_semantics": str(item.get("input_semantics") or "").strip() or None,
      "target_driver": str(item.get("target_driver") or "").strip() or None,
    }
  return lookup

def _lever_family_from_lever_id(lever_id: Any) -> str:
  raw = str(lever_id or "").strip()
  if not raw:
    return ""
  return str(raw.split("::", 1)[0] or "").strip().lower()

def _raise_negative_net_income_if_needed(
  *,
  final_finmo_json: Optional[Dict[str, Any]],
  stage: str,
) -> None:
  finmo_by_quarter = _finmo_quarter_row_map(final_finmo_json)
  violations: List[Dict[str, Any]] = []
  for quarter_index in sorted(finmo_by_quarter):
    if quarter_index < 1:
      continue
    row = finmo_by_quarter.get(quarter_index) or {}
    net_income = int(round(float(_safe_float(row.get("net_income")) or 0.0)))
    if net_income >= 0:
      continue
    violations.append(
      {
        "quarter_index": int(quarter_index),
        "net_income": net_income,
        "revenue": int(round(float(_safe_float(row.get("revenue")) or 0.0))),
        "ebitda": int(round(float(_safe_float(row.get("ebitda")) or 0.0))),
        "depreciation": int(round(float(_safe_float(row.get("depreciation")) or 0.0))),
        "interest_expense": int(round(float(_safe_float(row.get("interest_expense")) or 0.0))),
        "ending_cash": int(round(float(_safe_float(row.get("ending_cash")) or 0.0))),
      }
    )
  if not violations:
    return
  diagnostics = {
    "failure_stage": str(stage or "final_model").strip() or "final_model",
    "failure_reason": "negative_net_income_hard_gate",
    "validation_error": {
      "rejected": True,
      "reason_code": "negative_net_income_hard_gate",
      "reason": "Final model contains live-quarter negative net income.",
    },
    "pre_solver_validation": {
      "flags": ["negative_net_income_hard_gate"],
      "errors": [
        {
          "error": "negative_net_income_hard_gate",
          "reason": "Every live quarter must satisfy net_income >= 0 before the run can complete.",
          "validation_category": "financial_viability",
          "violating_quarters": [int(item.get("quarter_index") or 0) for item in violations],
        }
      ],
    },
    "negative_net_income_violations": copy.deepcopy(violations),
  }
  raise StructuredSystemRunFailure(
    detail="negative_net_income_hard_gate",
    diagnostics=diagnostics,
  )

def _sum_series(values: Any) -> float:
  if not isinstance(values, list):
    return 0.0
  return float(sum(float(_safe_float(item) or 0.0) for item in values))

def _model_input_revenue_driver_quarter_states(
  model_input_json: Optional[Dict[str, Any]],
) -> Dict[int, Dict[str, Any]]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  revenue_rows = [row for row in (sections.get("revenue") or []) if isinstance(row, dict)]
  grouped: Dict[str, Dict[str, List[Any]]] = {}
  max_live_count = 0
  for row in revenue_rows:
    driver = str(row.get("driver") or row.get("label") or "").strip().lower()
    if driver not in {"capacity", "unit price", "utilization"}:
      continue
    slot_key = str(row.get("revenue_slot_key") or row.get("lever_id") or "").strip()
    if not slot_key:
      continue
    values = list(row.get("values") or [])
    max_live_count = max(max_live_count, max(0, len(values) - 1))
    grouped.setdefault(slot_key, {})[driver] = values
  states: Dict[int, Dict[str, Any]] = {}
  for quarter_index in range(1, max_live_count + 1):
    total_capacity = 0.0
    total_realized_units = 0.0
    populated_slots = 0
    for driver_rows in grouped.values():
      capacity_values = driver_rows.get("capacity") or []
      utilization_values = driver_rows.get("utilization") or []
      capacity = max(0.0, float(_safe_float(capacity_values[quarter_index] if quarter_index < len(capacity_values) else None) or 0.0))
      utilization = max(0.0, float(_safe_float(utilization_values[quarter_index] if quarter_index < len(utilization_values) else None) or 0.0))
      if capacity <= 0.0 and utilization <= 0.0:
        continue
      populated_slots += 1
      total_capacity += capacity
      total_realized_units += capacity * utilization
    aggregate_utilization = (total_realized_units / total_capacity) if total_capacity > 0.0 else 0.0
    states[quarter_index] = {
      "quarter_index": quarter_index,
      "structural_capacity": total_capacity,
      "aggregate_utilization": aggregate_utilization,
      "populated_revenue_slots": populated_slots,
    }
  previous: Optional[Dict[str, Any]] = None
  for quarter_index in sorted(states):
    state = states[quarter_index]
    if previous:
      previous_capacity = float(previous.get("structural_capacity") or 0.0)
      current_capacity = float(state.get("structural_capacity") or 0.0)
      previous_utilization = float(previous.get("aggregate_utilization") or 0.0)
      current_utilization = float(state.get("aggregate_utilization") or 0.0)
      state["capacity_growth_qoq"] = (
        ((current_capacity - previous_capacity) / previous_capacity)
        if previous_capacity > 0.0
        else None
      )
      state["utilization_change_qoq"] = current_utilization - previous_utilization
      state["previous_structural_capacity"] = previous_capacity
      state["previous_aggregate_utilization"] = previous_utilization
    previous = state
  return states

def _growth_supported_by_capacity_or_utilization(
  *,
  previous_state: Optional[Dict[str, Any]],
  current_state: Optional[Dict[str, Any]],
  high_watermark: float,
) -> Dict[str, Any]:
  previous = previous_state if isinstance(previous_state, dict) else {}
  current = current_state if isinstance(current_state, dict) else {}
  previous_capacity = float(_safe_float(previous.get("structural_capacity")) or 0.0)
  current_capacity = float(_safe_float(current.get("structural_capacity")) or 0.0)
  previous_utilization = float(_safe_float(previous.get("aggregate_utilization")) or 0.0)
  current_utilization = float(_safe_float(current.get("aggregate_utilization")) or 0.0)
  capacity_growth = ((current_capacity - previous_capacity) / previous_capacity) if previous_capacity > 0.0 else None
  utilization_change = current_utilization - previous_utilization
  capacity_expanded = bool(capacity_growth is not None and capacity_growth > 0.001)
  utilization_ramped = bool(previous_utilization < high_watermark and utilization_change > 0.01)
  if previous_utilization >= high_watermark and not capacity_expanded:
    supported = False
    reason = "growth_at_high_utilization_requires_structural_capacity_expansion"
  elif capacity_expanded or utilization_ramped:
    supported = True
    reason = "growth_supported_by_capacity_expansion_or_utilization_ramp"
  else:
    supported = False
    reason = "growth_not_supported_by_capacity_or_utilization_ramp"
  return {
    "supported": supported,
    "reason": reason,
    "previous_structural_capacity": previous_capacity,
    "current_structural_capacity": current_capacity,
    "capacity_growth_qoq": capacity_growth,
    "previous_aggregate_utilization": previous_utilization,
    "current_aggregate_utilization": current_utilization,
    "utilization_change_qoq": utilization_change,
    "capacity_expanded": capacity_expanded,
    "utilization_ramped": utilization_ramped,
  }

def _allowed_stage_growth_result(
  *,
  growth: float,
  policy: Dict[str, Any],
  metric_prefix: str,
  from_quarter: int,
  prior_fte: Optional[float],
  support: Dict[str, Any],
  spike_count_used: int,
) -> Dict[str, Any]:
  pair_limit = _stage_ramp_pair_growth_limit(
    policy,
    from_quarter=int(from_quarter or 0),
    metric_prefix=metric_prefix,
    spike_count_used=spike_count_used,
  )
  ordinary_max = float(_safe_float(pair_limit.get("ordinary_growth_max")) or 0.0)
  spike_max = float(_safe_float(pair_limit.get("spike_growth_max")) or ordinary_max)
  if growth <= ordinary_max + 1e-9:
    return {
      "allowed": True,
      "allowed_growth": ordinary_max,
      "used_spike": False,
      "reason": "within_ordinary_stage_growth_max",
      "ramp_grid_row": copy.deepcopy(pair_limit.get("ramp_grid_row") or {}),
    }
  spike_available_by_grid = bool(pair_limit.get("spike_available"))
  spike_allowed_by_grid = bool(pair_limit.get("spike_allowed_for_pair"))
  support_ok = bool((support or {}).get("supported"))
  small_base_threshold = _safe_float(policy.get("fte_spike_small_base_threshold"))
  small_base_ok = (
    True
    if metric_prefix != "fte"
    else (small_base_threshold is not None and prior_fte is not None and float(prior_fte) < float(small_base_threshold))
  )
  if metric_prefix == "fte" and str(policy.get("stage_family") or "").strip().lower() != "startup":
    small_base_ok = True
  if (
    growth <= spike_max + 1e-9
    and spike_available_by_grid
    and support_ok
    and small_base_ok
  ):
    return {
      "allowed": True,
      "allowed_growth": spike_max,
      "used_spike": True,
      "reason": "within_stage_spike_max_with_required_operating_support",
      "ramp_grid_row": copy.deepcopy(pair_limit.get("ramp_grid_row") or {}),
    }
  return {
    "allowed": False,
    "allowed_growth": ordinary_max if not spike_allowed_by_grid else spike_max,
    "used_spike": False,
    "reason": (
      "stage_growth_exceeds_deterministic_ramp_contract"
      if growth > spike_max
      else str((support or {}).get("reason") or "stage_growth_spike_not_supported_by_grid")
    ),
    "ramp_grid_row": copy.deepcopy(pair_limit.get("ramp_grid_row") or {}),
  }

def _operating_trajectory_allowed_levers(
  model_input_json: Optional[Dict[str, Any]],
  *,
  target_metric_names: Optional[List[str]] = None,
) -> List[str]:
  target_filter = {
    str(item or "").strip().lower()
    for item in (target_metric_names or [])
    if str(item or "").strip()
  }
  available_lever_ids = [
    str(item.get("lever_id") or "").strip()
    for item in _build_writable_lever_review_catalog(model_input_json)
    if isinstance(item, dict) and str(item.get("lever_id") or "").strip()
  ]
  allowed: List[str] = []
  for lever_id in available_lever_ids:
    if not (
      post_intake_driver_target_lever_allowed_for_issue(
        lever_id,
        "capacity_support_mismatch",
        phase="convergence",
      )
      or post_intake_driver_target_lever_allowed_for_issue(
        lever_id,
        "p_and_l_flatline",
        phase="convergence",
      )
    ):
      continue
    mapping_entry = post_intake_driver_target_mapping_entry(lever_id) or {}
    target_metric = str(mapping_entry.get("target_metric_name") or "").strip().lower()
    if target_filter and target_metric not in target_filter:
      continue
    if target_metric:
      allowed.append(lever_id)
  return allowed

def _series_longest_flat_run(
  values: List[float],
  *,
  relative_epsilon: float = 0.001,
  absolute_epsilon: float = 1.0,
) -> Dict[str, Any]:
  if not values:
    return {"length": 0, "start_quarter": None, "end_quarter": None}
  best_start = 1
  best_len = 1
  current_start = 1
  current_len = 1
  for idx in range(1, len(values)):
    previous = float(values[idx - 1])
    current = float(values[idx])
    epsilon = max(float(absolute_epsilon), abs(previous) * float(relative_epsilon))
    if abs(current - previous) <= epsilon:
      current_len += 1
    else:
      if current_len > best_len:
        best_len = current_len
        best_start = current_start
      current_start = idx + 1
      current_len = 1
  if current_len > best_len:
    best_len = current_len
    best_start = current_start
  return {
    "length": int(best_len),
    "start_quarter": int(best_start),
    "end_quarter": int(best_start + best_len - 1),
  }

def _raise_unified_convergence_cycle_timeout_if_needed(
  *,
  cycle: int,
  cycle_started_at: float,
  stage: str,
  detail: str = "",
  cycle_timing: Optional[Dict[str, Any]] = None,
) -> None:
  elapsed_seconds = float(time.perf_counter() - float(cycle_started_at))
  if elapsed_seconds <= _UNIFIED_CONVERGENCE_CYCLE_TIMEOUT_SECONDS:
    return
  timing_payload = copy.deepcopy(cycle_timing if isinstance(cycle_timing, dict) else {})
  timing_payload.update(
    {
      "cycle": int(cycle),
      "stage": str(stage or "").strip() or "unknown",
      "elapsed_seconds": round(elapsed_seconds, 3),
      "timeout_seconds": round(float(_UNIFIED_CONVERGENCE_CYCLE_TIMEOUT_SECONDS), 3),
      "detail": str(detail or "").strip(),
    }
  )
  diagnostics = {
    "failure_stage": "cycle_timing",
    "failure_reason": "convergence_cycle_timeout",
    "solver_invoked": False,
    "cycle": int(cycle),
    "timing": timing_payload,
    "validation_error": {
      "rejected": True,
      "reason_code": "convergence_cycle_timeout",
      "reason": (
        f"Unified convergence cycle {int(cycle)} exceeded "
        f"{int(_UNIFIED_CONVERGENCE_CYCLE_TIMEOUT_SECONDS)} seconds during "
        f"{str(stage or '').strip() or 'unknown'}."
        + (f" Detail: {str(detail or '').strip()}" if str(detail or "").strip() else "")
      ),
    },
    "pre_solver_validation": {
      "flags": ["convergence_cycle_timeout"],
      "errors": [
        {
          "error": "convergence_cycle_timeout",
          "reason": (
            f"Cycle elapsed {elapsed_seconds:.3f}s exceeds "
            f"{_UNIFIED_CONVERGENCE_CYCLE_TIMEOUT_SECONDS:.3f}s budget."
          ),
          "validation_category": "cycle_timing",
        }
      ],
    },
  }
  raise StructuredSystemRunFailure(
    detail=_structured_system_run_failure_detail(
      diagnostics=diagnostics,
      fallback="convergence_cycle_timeout",
    ),
    diagnostics=diagnostics,
  )

def _raise_unified_convergence_stage_budget_if_needed(
  *,
  cycle: int,
  cycle_started_at: float,
  stage: str,
  minimum_remaining_seconds: float,
  detail: str = "",
  cycle_timing: Optional[Dict[str, Any]] = None,
) -> None:
  elapsed_seconds = float(time.perf_counter() - float(cycle_started_at))
  remaining_seconds = float(_UNIFIED_CONVERGENCE_CYCLE_TIMEOUT_SECONDS) - elapsed_seconds
  if remaining_seconds >= float(minimum_remaining_seconds):
    return
  timing_payload = copy.deepcopy(cycle_timing if isinstance(cycle_timing, dict) else {})
  timing_payload.update(
    {
      "cycle": int(cycle),
      "stage": str(stage or "").strip() or "unknown",
      "elapsed_seconds": round(elapsed_seconds, 3),
      "remaining_seconds": round(remaining_seconds, 3),
      "minimum_remaining_seconds": round(float(minimum_remaining_seconds), 3),
      "timeout_seconds": round(float(_UNIFIED_CONVERGENCE_CYCLE_TIMEOUT_SECONDS), 3),
      "detail": str(detail or "").strip(),
    }
  )
  diagnostics = {
    "failure_stage": "cycle_timing",
    "failure_reason": "convergence_cycle_insufficient_stage_budget",
    "solver_invoked": False,
    "cycle": int(cycle),
    "timing": timing_payload,
    "validation_error": {
      "rejected": True,
      "reason_code": "convergence_cycle_insufficient_stage_budget",
      "reason": (
        f"Unified convergence cycle {int(cycle)} has only {remaining_seconds:.3f}s remaining before "
        f"{str(stage or '').strip() or 'unknown'}, below the required "
        f"{float(minimum_remaining_seconds):.3f}s stage budget."
      ),
    },
    "pre_solver_validation": {
      "flags": ["convergence_cycle_insufficient_stage_budget"],
      "errors": [
        {
          "error": "convergence_cycle_insufficient_stage_budget",
          "reason": (
            f"Cycle has {remaining_seconds:.3f}s remaining, below required "
            f"{float(minimum_remaining_seconds):.3f}s for {str(stage or '').strip() or 'unknown'}."
          ),
          "validation_category": "cycle_timing",
        }
      ],
    },
  }
  raise StructuredSystemRunFailure(
    detail=_structured_system_run_failure_detail(
      diagnostics=diagnostics,
      fallback="convergence_cycle_insufficient_stage_budget",
    ),
    diagnostics=diagnostics,
  )

def _mark_unified_convergence_cycle_phase(
  *,
  cycle_timing: Dict[str, Any],
  cycle_started_at: float,
  phase_name: str,
  phase_started_at: float,
  status: str = "completed",
  detail: str = "",
) -> None:
  now = time.perf_counter()
  elapsed = float(now - float(cycle_started_at))
  duration = float(now - float(phase_started_at))
  remaining = float(_UNIFIED_CONVERGENCE_CYCLE_TIMEOUT_SECONDS) - elapsed
  phase_payload = {
    "phase": str(phase_name or "").strip() or "unknown",
    "status": str(status or "").strip() or "completed",
    "duration_seconds": round(duration, 3),
    "cycle_elapsed_seconds": round(elapsed, 3),
    "cycle_remaining_seconds": round(remaining, 3),
  }
  if str(detail or "").strip():
    phase_payload["detail"] = str(detail or "").strip()
  phases = cycle_timing.get("phase_timings") if isinstance(cycle_timing.get("phase_timings"), list) else []
  phases.append(phase_payload)
  cycle_timing["phase_timings"] = phases
  cycle_timing["latest_phase"] = copy.deepcopy(phase_payload)
  cycle_timing["total_elapsed_seconds"] = round(elapsed, 3)
  cycle_timing["remaining_seconds"] = round(remaining, 3)

def get_runtime_probe_payload() -> Dict[str, Any]:
  return {
    "status": "ok",
    "runtime_probe_version": _INTAKE_CONSULT_RUNTIME_PROBE_VERSION,
    "architecture": "unified_convergence_plus_cash_pass",
    "mapping_source": "sql.post_intak_mapping_lookup",
    "unified_convergence": {
      "max_cycles": int(_UNIFIED_CONVERGENCE_MAX_CYCLES),
      "cycle_timeout_seconds": float(_UNIFIED_CONVERGENCE_CYCLE_TIMEOUT_SECONDS),
      "active_issue_limit": int(_UNIFIED_CONVERGENCE_ACTIVE_ISSUE_LIMIT),
      "active_quarter_limit": int(_UNIFIED_CONVERGENCE_ACTIVE_QUARTER_LIMIT),
      "non_productive_cycle_limit": int(_CONVERGENCE_NON_PRODUCTIVE_CYCLE_LIMIT),
    },
    "issue_codes": sorted(_ISSUE_CODE_REGISTRY.keys()),
    "cash_pass_owned_issue_codes": sorted(_CASH_PASS_OWNED_ISSUE_CODES),
    "remaining_horizon_issue_codes": sorted(_REMAINING_HORIZON_ISSUE_CODES),
  }

def _convergence_test_mode_enabled() -> bool:
  raw = (os.getenv("CONVERGENCE_TEST_MODE") or "false").strip().lower()
  return raw not in {"", "0", "false", "no", "off"}

def _handle_convergence_test_mode_failure(
  quality_assessment: Optional[Dict[str, Any]],
) -> None:
  assessment = quality_assessment if isinstance(quality_assessment, dict) else {}
  strict_failure = (
    assessment.get("strict_failure")
    if isinstance(assessment.get("strict_failure"), dict)
    else {}
  )
  if not strict_failure:
    return
  terminal_message = str(strict_failure.get("terminal_message") or "").strip()
  detail = str(
    strict_failure.get("detail")
    or terminal_message
    or "unified_convergence_test_mode_failure"
  ).strip()
  if _convergence_test_mode_enabled():
    if terminal_message:
      print(terminal_message, flush=True)
      logger.error(terminal_message)
    raise RuntimeError(detail)
  if terminal_message:
    logger.warning(terminal_message)
  else:
    logger.warning(detail)

def _build_convergence_progress_failure_diagnostics(
  *,
  cycles_attempted: int,
  last_known_state: Optional[Dict[str, Any]],
  repeated_failure_pattern: Optional[Dict[str, Any]],
  planner_plan_status: str = "",
) -> Dict[str, Any]:
  state = last_known_state if isinstance(last_known_state, dict) else {}
  pattern = repeated_failure_pattern if isinstance(repeated_failure_pattern, dict) else {}
  return {
    "failure_stage": "convergence_progress",
    "failure_reason": "no_meaningful_progress",
    "cycles_attempted": int(_safe_float(cycles_attempted) or 0),
    "last_known_state": {
      "remaining_issue_count": int(_safe_float(state.get("remaining_issue_count")) or 0),
      "resolved_issue_count": int(_safe_float(state.get("resolved_issue_count")) or 0),
      "tolerated_issue_count": int(_safe_float(state.get("tolerated_issue_count")) or 0),
      "pre_solver_validation_flags": copy.deepcopy(pattern.get("pre_solver_validation_flags") or []),
    },
    "repeated_failure_pattern": {
      "planner_status": str(pattern.get("planner_status") or planner_plan_status or "").strip() or None,
      "solver_invoked": bool(pattern.get("solver_invoked")),
      "invalid_levers": copy.deepcopy(pattern.get("invalid_levers") or []),
      "pre_solver_validation_flags": copy.deepcopy(pattern.get("pre_solver_validation_flags") or []),
    },
    "convergence_test_mode": _convergence_test_mode_enabled(),
  }

def _build_unified_cycle_stall_assessment(
  *,
  consecutive_no_progress_cycles: int,
  latest_quality_assessment: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  quality = latest_quality_assessment if isinstance(latest_quality_assessment, dict) else {}
  consecutive = max(0, int(consecutive_no_progress_cycles or 0))
  open_issue_codes = [
    str(item).strip().lower()
    for item in (quality.get("open_issue_codes_after") or quality.get("open_issue_codes_before") or [])
    if str(item).strip()
  ]
  structural_issue_codes = [
    code
    for code in open_issue_codes
    if code in _ISSUE_CODE_REGISTRY
  ]
  progress_detected = bool(quality.get("meaningful_progress"))
  same_issue_signature_without_progress = bool(quality.get("same_issue_signature_without_progress"))
  issue_count_regressed_without_progress = bool(
    quality.get("issue_count_regressed")
    and not progress_detected
  )
  unresolved_issue_plateau = bool(quality.get("unresolved_issue_plateau"))
  stalled = bool(
    consecutive >= 1
    or same_issue_signature_without_progress
    or quality.get("no_progress")
    or quality.get("insufficient_issue_progress")
    or quality.get("early_failure_detected")
    or issue_count_regressed_without_progress
    or unresolved_issue_plateau
    or quality.get("cash_only_viability_progress")
  )
  structurally_stalled = bool(
    consecutive >= 2
    or (structural_issue_codes and (unresolved_issue_plateau or consecutive >= 1))
  )
  return {
    "stalled": stalled,
    "consecutive_no_progress_cycles": consecutive,
    "force_material_tactic_change": stalled,
    "force_full_horizon_scope": False,
    "force_all_writable_levers": False,
    "force_structural_driver_changes": structurally_stalled,
    "minimum_new_lever_count": 3 if structurally_stalled else (2 if stalled else 0),
    "require_target_reframe_on_same_issue_state": same_issue_signature_without_progress,
    "open_issue_codes": copy.deepcopy(open_issue_codes),
    "structural_issue_codes": copy.deepcopy(structural_issue_codes),
    "required_change_type": "structural" if structurally_stalled else ("focused_reframe" if stalled else "none"),
    "latest_quality_assessment": copy.deepcopy(quality),
    "instruction": (
      "The convergence loop has stalled. The next attempt must materially change tactic within the current 20-quarter contract."
      if stalled
      else "No unified-cycle stall is currently detected."
    ),
  }
