"""Shared numeric execution boundary and orchestration for intake/finmo flows."""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional


NUMERIC_EXECUTION_BOUNDARY_VERSION = "numeric_execution_boundary_v1"
NUMERIC_SOLVER_CONTRACT_VERSION = "numeric_solver_contract_v1"
NUMERIC_EXECUTION_PLAN_VERSION = "numeric_execution_plan_v1"
NUMERIC_EXECUTION_RESULT_VERSION = "numeric_execution_result_v1"
CURRENT_NUMERIC_EXECUTOR = "live_gpt_led_numeric_executor"
TARGET_NUMERIC_EXECUTOR = "gpt_led_solver"
SOLVER_PHASE_STATUS = "phase_8_live_numeric_executor_boundary"
SOLVER_PHASE_2_STATUS = "phase_2_contract_defined"
SOLVER_PHASE_3_STATUS = "phase_3_adaptive_number_cruncher_ready"
SOLVER_PHASE_4_STATUS = "phase_4_initial_restructure_solver_live"
SOLVER_PHASE_5_STATUS = "phase_5_realism_resolution_solver_live"
SOLVER_PHASE_6_STATUS = "phase_6_cash_strategy_solver_live"
SOLVER_PHASE_8_STATUS = "phase_8_live_numeric_executor_boundary"

IMMUTABLE_CORE_MODEL_FILES = (
  "python/financial_model_engine/model_inputs.py",
  "python/financial_model_engine/finmo_model.py",
)


_ISSUE_SOLVER_OBJECTIVES: Dict[str, Dict[str, Any]] = {
  "financing_solvency_mismatch": {
    "metric_targets": ["ending_cash", "liquidity_support", "debt_burden"],
    "solver_objective": "restore_liquidity_without_breaking_operating_shape",
  },
  "profitability_cash_shape_unrealistic": {
    "metric_targets": ["ebitda", "net_income", "ending_cash"],
    "solver_objective": "improve_trajectory_and_ongoing_concern_shape",
  },
  "capacity_revenue_mismatch": {
    "metric_targets": ["revenue", "capacity_utilization"],
    "solver_objective": "align_volume_with_capacity_and_timing",
  },
  "staffing_payroll_mismatch": {
    "metric_targets": ["payroll", "staffing_load", "revenue"],
    "solver_objective": "align_headcount_cost_with_operating_scale",
  },
  "capex_footprint_mismatch": {
    "metric_targets": ["capital_expenditures", "ppe", "investing_cash_flow", "ending_cash", "financing_cash_flow"],
    "solver_objective": "align_asset_intensity_with_operating_footprint",
  },
  "cost_structure_mismatch": {
    "metric_targets": ["gross_margin", "operating_costs", "ebitda"],
    "solver_objective": "rebalance_cost_structure_without_fake_plugs",
  },
  "working_capital_payment_model_mismatch": {
    "metric_targets": ["operating_cash_flow", "current_assets", "current_liabilities", "ending_cash"],
    "solver_objective": "align_working_capital_with_real_collection_payment_timing",
  },
  "pricing_positioning_mismatch": {
    "metric_targets": ["price_realization", "gross_margin", "revenue"],
    "solver_objective": "align_price_with_offer_and demand reality",
  },
  "growth_model_mismatch": {
    "metric_targets": ["revenue", "operating_scale", "ending_cash"],
    "solver_objective": "align growth path with viable operating support",
  },
  "operating_model_contradiction": {
    "metric_targets": ["operating_cash_flow", "revenue", "payroll", "capital_expenditures"],
    "solver_objective": "restore an operating model that is cash-coherent and supportable at the chosen scale",
  },
  "catastrophic_liquidity_failure": {
    "metric_targets": ["ending_cash", "financing_cash_flow", "operating_cash_flow"],
    "solver_objective": "repair near-term liquidity through direct cash levers and supportable operating fixes",
  },
}

TARGETABLE_FINMO_METRIC_IDS = (
  "revenue",
  "cogs",
  "gross_profit",
  "marketing",
  "research_and_development",
  "lease_rent",
  "payroll",
  "g_and_a",
  "ebitda",
  "interest",
  "depreciation",
  "taxes",
  "net_income",
  "ending_cash",
  "accounts_receivable",
  "inventory",
  "prepaid_expenses",
  "current_assets",
  "noncurrent_assets",
  "ppe",
  "accumulated_depreciation",
  "accounts_payable",
  "short_term_debt",
  "deferred_revenue",
  "current_liabilities",
  "long_term_debt",
  "total_liabilities",
  "owners_capital",
  "distributions",
  "retained_earnings",
  "other_equity",
  "total_equity",
  "total_liabilities_and_equity",
  "beginning_cash",
  "changes_in_current_assets",
  "changes_in_current_liabilities",
  "operating_cash_flow",
  "capital_expenditures",
  "investing_cash_flow",
  "debt_issuance",
  "debt_repayment",
  "debt_receive_repay",
  "equity",
  "owner_distributions",
  "financing_cash_flow",
  "net_cash_flow",
  "noncurrent_liabilities",
)

PRIMARY_TARGETABLE_FINMO_METRIC_IDS = (
  "revenue",
  "gross_profit",
  "ebitda",
  "net_income",
  "ending_cash",
  "operating_cash_flow",
  "investing_cash_flow",
  "financing_cash_flow",
  "current_assets",
  "ppe",
  "current_liabilities",
  "noncurrent_liabilities",
  "payroll",
  "marketing",
  "g_and_a",
  "lease_rent",
  "capital_expenditures",
  "long_term_debt",
  "total_liabilities",
  "owners_capital",
  "other_equity",
  "distributions",
)

PRIMARY_TARGET_METRIC_MIN_COUNT = 3
PRIMARY_TARGET_METRIC_MAX_COUNT = 6

_ISSUE_PRIMARY_TARGET_CANDIDATES: Dict[str, List[str]] = {
  "financing_solvency_mismatch": [
    "ending_cash",
    "financing_cash_flow",
    "operating_cash_flow",
    "owners_capital",
    "noncurrent_liabilities",
  ],
  "profitability_cash_shape_unrealistic": [
    "ebitda",
    "net_income",
    "ending_cash",
    "operating_cash_flow",
    "gross_profit",
  ],
  "staffing_payroll_mismatch": [
    "payroll",
    "revenue",
    "gross_profit",
    "ebitda",
  ],
  "capacity_revenue_mismatch": [
    "revenue",
    "gross_profit",
    "ebitda",
    "payroll",
    "capital_expenditures",
  ],
  "capex_footprint_mismatch": [
    "capital_expenditures",
    "investing_cash_flow",
    "ppe",
    "ending_cash",
    "financing_cash_flow",
  ],
  "cost_structure_mismatch": [
    "gross_profit",
    "ebitda",
    "net_income",
    "operating_cash_flow",
    "payroll",
    "g_and_a",
  ],
  "pricing_positioning_mismatch": [
    "gross_profit",
    "ebitda",
    "net_income",
  ],
  "growth_model_mismatch": [
    "revenue",
    "ending_cash",
    "operating_cash_flow",
    "payroll",
    "capital_expenditures",
  ],
  "operating_model_contradiction": [
    "operating_cash_flow",
    "ending_cash",
    "revenue",
    "payroll",
    "capital_expenditures",
  ],
  "catastrophic_liquidity_failure": [
    "ending_cash",
    "financing_cash_flow",
    "operating_cash_flow",
    "owners_capital",
    "capital_expenditures",
  ],
}

_OBJECTIVE_METRIC_ALIAS_MAP: Dict[str, str] = {
  "liquidity_support": "ending_cash",
  "debt_burden": "noncurrent_liabilities",
  "gross_margin": "gross_profit",
  "operating_costs": "ebitda",
  "price_realization": "revenue",
  "staffing_load": "payroll",
  "operating_scale": "revenue",
  "capacity_utilization": "revenue",
}

_DEFAULT_PRIMARY_TARGET_METRICS = (
  "ending_cash",
  "ebitda",
  "net_income",
  "operating_cash_flow",
  "gross_profit",
)
_PREFERRED_PRIMARY_TARGET_METRIC_COUNT = 6


def _solver_phase_status_for_pass(pass_name: Any) -> str:
  normalized = str(pass_name or "").strip().lower()
  if normalized == "initial_restructure":
    return SOLVER_PHASE_4_STATUS
  if normalized == "realism_resolution":
    return SOLVER_PHASE_5_STATUS
  if normalized == "cash_strategy_review":
    return SOLVER_PHASE_6_STATUS
  return SOLVER_PHASE_8_STATUS


def _phase_scope_for_status(phase_status: Any) -> str:
  normalized = str(phase_status or "").strip().lower()
  if normalized == str(SOLVER_PHASE_4_STATUS).lower():
    return "initial_restructure_solver_live"
  if normalized == str(SOLVER_PHASE_5_STATUS).lower():
    return "realism_resolution_solver_live"
  if normalized == str(SOLVER_PHASE_6_STATUS).lower():
    return "cash_strategy_solver_live"
  return "live_numeric_executor_boundary"


def _safe_float(value: Any) -> Optional[float]:
  try:
    if value is None or value == "":
      return None
    return float(value)
  except Exception:
    return None


def _normalized_primary_target_metric_name(metric_name: Any) -> str:
  raw = str(metric_name or "").strip().lower()
  if not raw:
    return ""
  normalized = _OBJECTIVE_METRIC_ALIAS_MAP.get(raw) or raw
  return normalized if normalized in set(PRIMARY_TARGETABLE_FINMO_METRIC_IDS) else ""


def _recommended_primary_target_metric_keys(
  issue_status_records: Optional[List[Dict[str, Any]]],
) -> List[str]:
  keys: List[str] = []
  active_issue_codes: List[str] = []
  for packet in _issue_target_packets(issue_status_records):
    issue_code = str(packet.get("issue_code") or "").strip().lower()
    if not issue_code:
      continue
    active_issue_codes.append(issue_code)
    for metric_name in (packet.get("metric_targets") or []):
      normalized = _normalized_primary_target_metric_name(metric_name)
      if normalized and normalized not in keys:
        keys.append(normalized)
    for metric_name in (_ISSUE_PRIMARY_TARGET_CANDIDATES.get(issue_code) or []):
      normalized = _normalized_primary_target_metric_name(metric_name)
      if normalized and normalized not in keys:
        keys.append(normalized)
  for metric_name in _DEFAULT_PRIMARY_TARGET_METRICS:
    normalized = _normalized_primary_target_metric_name(metric_name)
    if normalized and normalized not in keys:
      keys.append(normalized)
  if "ending_cash" in keys:
    keys = ["ending_cash"] + [metric for metric in keys if metric != "ending_cash"]
  return keys[: min(PRIMARY_TARGET_METRIC_MAX_COUNT, _PREFERRED_PRIMARY_TARGET_METRIC_COUNT)]


def _tactic_family(tactic: Any) -> str:
  tactic_norm = str(tactic or "").strip().lower()
  if tactic_norm in {"financing_supported_reset", "debt_or_distribution_retiming"}:
    return "financing"
  if tactic_norm in {"cost_and_timing_rebalance", "pricing_and_mix_rebalance"}:
    return "margin_cost"
  if tactic_norm in {"staffing_and_capacity_rebalance", "capacity_growth_retime"}:
    return "operating_scale"
  if tactic_norm in {"holistic_stabilization", "coordinated_multi_lever_reset", "structural_rebalance"}:
    return "holistic_reset"
  if tactic_norm in {"strategy_aligned_capital_allocation", "cash_preservation_bias"}:
    return "capital_allocation"
  return "general"


def _normalized_issue_status_records(issue_status_records: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
  out: List[Dict[str, Any]] = []
  for item in (issue_status_records or []):
    if not isinstance(item, dict):
      continue
    issue_code = str(item.get("issue_code") or "").strip().lower()
    if not issue_code:
      continue
    out.append(
      {
        "issue_code": issue_code,
        "verifier_status": str(item.get("verifier_status") or "").strip().lower() or "not_resolved",
        "remaining_issue_materiality": str(item.get("remaining_issue_materiality") or "").strip().lower(),
        "remaining_issue_severity_score": int(round(_safe_float(item.get("remaining_issue_severity_score")) or 0.0)),
        "remaining_problem_quarters": [
          int(round(_safe_float(q) or 0.0))
          for q in (item.get("remaining_problem_quarters") or [])
          if int(round(_safe_float(q) or 0.0)) >= 1
        ],
        "next_required_lever_ids": [
          str(v).strip()
          for v in (item.get("next_required_lever_ids") or [])
          if str(v).strip()
        ],
        "iteration_needed": bool(item.get("iteration_needed")),
      }
    )
  return out


def _issue_default_severity(issue_code: str) -> int:
  code = str(issue_code or "").strip().lower()
  if code == "financing_solvency_mismatch":
    return 95
  if code == "working_capital_payment_model_mismatch":
    return 90
  if code in {"profitability_cash_shape_unrealistic", "capex_footprint_mismatch"}:
    return 88
  if code in {"staffing_payroll_mismatch", "capacity_revenue_mismatch", "cost_structure_mismatch"}:
    return 82
  return 75


def _expand_quarter_window(quarters: List[int], *, all_quarters: List[int]) -> List[int]:
  allowed = {int(q) for q in all_quarters if int(q) >= 1}
  expanded: List[int] = []
  for quarter in [int(q) for q in quarters if int(q) >= 1]:
    for candidate in (quarter - 1, quarter, quarter + 1):
      if candidate in allowed and candidate not in expanded:
        expanded.append(candidate)
  return sorted(expanded or [q for q in all_quarters if int(q) >= 1])


def _infer_issue_quarters(
  *,
  issue_code: str,
  current_finmo_json: Optional[Dict[str, Any]],
) -> List[int]:
  rows = _quarter_metric_snapshots(current_finmo_json)
  all_quarters = [int(row.get("quarter_index") or 0) for row in rows if int(row.get("quarter_index") or 0) >= 1]
  if not all_quarters:
    return []
  negative_cash_quarters = [q for q, row in ((int(r.get("quarter_index") or 0), r) for r in rows) if float(_safe_float(row.get("ending_cash")) or 0.0) < 0.0]
  loss_quarters = [q for q, row in ((int(r.get("quarter_index") or 0), r) for r in rows) if float(_safe_float(row.get("net_income")) or 0.0) < 0.0]
  negative_ebitda_quarters = [q for q, row in ((int(r.get("quarter_index") or 0), r) for r in rows) if float(_safe_float(row.get("ebitda")) or 0.0) < 0.0]
  capex_quarters = [
    q
    for q, row in ((int(r.get("quarter_index") or 0), r) for r in rows)
    if float(_safe_float(row.get("capital_expenditures")) or 0.0) > 0.0
    or float(_safe_float(row.get("investing_cash_flow")) or 0.0) < 0.0
  ]
  revenue_quarters = [q for q, row in ((int(r.get("quarter_index") or 0), r) for r in rows) if float(_safe_float(row.get("revenue")) or 0.0) > 0.0]
  code = str(issue_code or "").strip().lower()
  if code == "financing_solvency_mismatch":
    return _expand_quarter_window(negative_cash_quarters or loss_quarters or all_quarters[:8], all_quarters=all_quarters)
  if code == "profitability_cash_shape_unrealistic":
    return _expand_quarter_window(loss_quarters or negative_cash_quarters or negative_ebitda_quarters or all_quarters[:8], all_quarters=all_quarters)
  if code == "working_capital_payment_model_mismatch":
    return _expand_quarter_window(negative_cash_quarters or revenue_quarters[:10] or all_quarters[:10], all_quarters=all_quarters)
  if code == "capex_footprint_mismatch":
    return _expand_quarter_window(capex_quarters or revenue_quarters[:8] or all_quarters[:8], all_quarters=all_quarters)
  if code in {"staffing_payroll_mismatch", "capacity_revenue_mismatch", "growth_model_mismatch"}:
    return _expand_quarter_window(revenue_quarters or all_quarters[:8], all_quarters=all_quarters)
  return _expand_quarter_window(negative_cash_quarters or loss_quarters or revenue_quarters[:6] or all_quarters[:6], all_quarters=all_quarters)


def _catalog_entry_text(entry: Dict[str, Any]) -> str:
  return " | ".join(
    [
      str(entry.get("lever_id") or "").strip().lower(),
      str(entry.get("section") or "").strip().lower(),
      str(entry.get("label_path") or "").strip().lower(),
      str(entry.get("driver") or "").strip().lower(),
      str(entry.get("accounting_role") or "").strip().lower(),
      str(entry.get("input_semantics") or "").strip().lower(),
    ]
  )


def _entry_matches_any(entry: Dict[str, Any], terms: List[str]) -> bool:
  haystack = _catalog_entry_text(entry)
  return any(str(term or "").strip().lower() in haystack for term in terms if str(term or "").strip())


def _infer_issue_lever_ids(
  *,
  issue_code: str,
  writable_lever_catalog: Optional[List[Dict[str, Any]]],
) -> List[str]:
  entries = [
    item
    for item in (writable_lever_catalog or [])
    if isinstance(item, dict) and str(item.get("lever_id") or "").strip()
  ]
  if not entries:
    return []
  code = str(issue_code or "").strip().lower()
  selected: List[str] = []

  def add_matching(terms: List[str], *, limit: Optional[int] = None) -> None:
    for entry in entries:
      lever_id = str(entry.get("lever_id") or "").strip()
      if not lever_id or lever_id in selected:
        continue
      if not _entry_matches_any(entry, terms):
        continue
      selected.append(lever_id)
      if limit is not None and len(selected) >= limit:
        return

  if code == "financing_solvency_mismatch":
    add_matching(["owner's capital", "owner_equity_contribution", "other equity", "debt draw", "debt issuance", "new borrowing", "debt repayment", "short term debt", "distributions"])
    add_matching(["unit price", "utilization", "capacity", "cost of goods sold", "payroll", "general & administrative", "marketing", "capital expenditures"])
  elif code == "profitability_cash_shape_unrealistic":
    add_matching(["unit price", "utilization", "capacity", "cost of goods sold", "payroll", "general & administrative", "marketing", "lease"])
    add_matching(["owner's capital", "other equity", "distributions", "debt issuance", "new borrowing", "debt repayment", "capital expenditures"])
  elif code == "staffing_payroll_mismatch":
    add_matching(["payroll", "capacity", "utilization", "unit price", "marketing", "general & administrative"])
  elif code == "capacity_revenue_mismatch":
    add_matching(["capacity", "utilization", "unit price", "payroll", "capital expenditures", "lease"])
  elif code == "capex_footprint_mismatch":
    add_matching(["capital expenditures", "lease", "capacity", "payroll", "owner's capital", "debt issuance", "new borrowing", "debt repayment"])
  elif code == "working_capital_payment_model_mismatch":
    add_matching([
      "accounts receivable days",
      "inventory days",
      "accounts payable days",
      "prepaid expenses",
      "deferred revenue",
      "owner's capital",
      "distributions",
      "debt issuance",
      "new borrowing",
      "debt repayment",
      "unit price",
      "utilization",
      "capacity",
    ])
  elif code == "catastrophic_liquidity_failure":
    add_matching(["owner's capital", "other equity", "distributions", "debt issuance", "new borrowing", "debt repayment", "capital expenditures"])
    add_matching([
      "accounts receivable days",
      "inventory days",
      "accounts payable days",
      "prepaid expenses",
      "deferred revenue",
      "unit price",
      "utilization",
      "capacity",
    ])
  elif code == "cost_structure_mismatch":
    add_matching(["cost of goods sold", "payroll", "general & administrative", "marketing", "lease"])
  else:
    add_matching(["owner's capital", "capacity", "utilization", "unit price", "cost of goods sold", "payroll", "general & administrative", "marketing", "capital expenditures"])

  if not selected:
    selected = [
      str(entry.get("lever_id") or "").strip()
      for entry in entries[: min(len(entries), 10)]
      if str(entry.get("lever_id") or "").strip()
    ]
  return selected[:12]


def _enriched_issue_status_records(
  *,
  issue_status_records: Optional[List[Dict[str, Any]]],
  writable_lever_catalog: Optional[List[Dict[str, Any]]],
  current_finmo_json: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  enriched: List[Dict[str, Any]] = []
  for item in _normalized_issue_status_records(issue_status_records):
    issue_code = str(item.get("issue_code") or "").strip().lower()
    if not issue_code:
      continue
    record = copy.deepcopy(item)
    if str(record.get("verifier_status") or "").strip().lower() != "resolved":
      if int(_safe_float(record.get("remaining_issue_severity_score")) or 0.0) <= 0:
        record["remaining_issue_severity_score"] = _issue_default_severity(issue_code)
      if not (record.get("remaining_problem_quarters") or []):
        record["remaining_problem_quarters"] = _infer_issue_quarters(
          issue_code=issue_code,
          current_finmo_json=current_finmo_json,
        )
      if not (record.get("next_required_lever_ids") or []):
        record["next_required_lever_ids"] = _infer_issue_lever_ids(
          issue_code=issue_code,
          writable_lever_catalog=writable_lever_catalog,
        )
      if not str(record.get("remaining_issue_materiality") or "").strip():
        record["remaining_issue_materiality"] = "material"
    enriched.append(record)
  return enriched


def _normalized_planning_mode_profile(
  planning_mode: Any,
  planning_mode_reason: Any,
  *,
  pass_name: str,
) -> Dict[str, Any]:
  mode = str(planning_mode or "").strip().lower()
  reason = str(planning_mode_reason or "").strip()
  if mode == "turnaround":
    return {
      "planning_mode": mode,
      "planning_mode_reason": reason,
      "primary_posture": "restore_working_business_earlier",
      "solver_bias": "favor_ongoing_concern_and_earlier_repair",
      "pass_name": pass_name,
    }
  if mode == "normalize":
    return {
      "planning_mode": mode,
      "planning_mode_reason": reason,
      "primary_posture": "remove_overstatement_without_fake_rescue",
      "solver_bias": "favor_plausibility_and_proportion",
      "pass_name": pass_name,
    }
  return {
    "planning_mode": mode or "rebalance",
    "planning_mode_reason": reason,
    "primary_posture": "rebalance_business_shape",
    "solver_bias": "favor_proportion_and_coherence",
    "pass_name": pass_name,
  }


def _normalized_solver_settings(
  *,
  pass_name: str,
  planning_mode: Any,
) -> Dict[str, Any]:
  mode = str(planning_mode or "").strip().lower() or "rebalance"
  aggressiveness = "moderate"
  if pass_name == "initial_restructure":
    aggressiveness = "high"
  elif pass_name == "unified_convergence":
    aggressiveness = "structural"
  elif pass_name == "cash_strategy_review":
    aggressiveness = "light"
  if mode == "turnaround" and aggressiveness != "light":
    aggressiveness = "high"
  return {
    "solver_family": "live_scipy_quarter_solver",
    "current_execution_mode": _solver_phase_status_for_pass(pass_name),
    "quarter_level_targets_required": True,
    "enforce_quarter_specific_targets": True,
    "full_horizon_primary_targeting_required": False,
    "sequential_quarter_solve_required": True,
    "quarter_execution_order": "ascending",
    "lumped_horizon_objective_allowed": False,
    "post_quarter_rollforward_required": True,
    "avoid_flattening": True,
    "shape_guardrail_mode": "quarter_specific_not_lumped",
    "preserve_turning_points": True,
    "shape_guardrail_weight": 0.35,
    "max_solver_attempts_per_pass": 3,
    "aggressiveness": aggressiveness,
    "tolerance_mode": "gpt_defined_primary_metric_tolerances",
    "preserve_non_targeted_levers": True,
    "allow_multi_lever_coordination": True,
    "no_progress_response": "switch_tactic_not_repeat_same_move",
    "focused_cycle_issue_limit": 2 if pass_name == "unified_convergence" else None,
    "focused_cycle_quarter_limit": 4 if pass_name == "unified_convergence" else None,
    "focused_cycle_lever_family_limit": 3 if pass_name == "unified_convergence" else None,
  }


def _dominant_issue_cluster(issue_status_records: Optional[List[Dict[str, Any]]]) -> str:
  codes = {
    str(item.get("issue_code") or "").strip().lower()
    for item in _normalized_issue_status_records(issue_status_records)
    if str(item.get("verifier_status") or "").strip().lower() != "resolved"
  }
  if "financing_solvency_mismatch" in codes:
    return "liquidity_financing"
  if "profitability_cash_shape_unrealistic" in codes or "cost_structure_mismatch" in codes:
    return "profitability_shape"
  if "staffing_payroll_mismatch" in codes:
    return "staffing_scale"
  if "capacity_revenue_mismatch" in codes or "growth_model_mismatch" in codes:
    return "capacity_growth"
  if "pricing_positioning_mismatch" in codes:
    return "pricing_mix"
  return "general_rebalance"


def _quarter_metric_snapshots(current_finmo_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  finmo = current_finmo_json if isinstance(current_finmo_json, dict) else {}
  out: List[Dict[str, Any]] = []
  for row in (finmo.get("quarter_rows") or []):
    if not isinstance(row, dict):
      continue
    quarter_index = int(round(_safe_float(row.get("quarter_index")) or 0.0))
    if quarter_index < 1:
      continue
    out.append(
      {
        "quarter_index": quarter_index,
        "date": row.get("date"),
        "revenue": float(_safe_float(row.get("revenue")) or 0.0),
        "cogs": float(_safe_float(row.get("cogs")) or 0.0),
        "gross_profit": float(_safe_float(row.get("gross_profit")) or 0.0),
        "marketing": float(_safe_float(row.get("marketing")) or 0.0),
        "research_and_development": float(_safe_float(row.get("research_and_development")) or 0.0),
        "lease_rent": float(_safe_float(row.get("lease_rent")) or 0.0),
        "payroll": float(_safe_float(row.get("payroll")) or 0.0),
        "g_and_a": float(_safe_float(row.get("g_and_a")) or 0.0),
        "ebitda": float(_safe_float(row.get("ebitda")) or 0.0),
        "interest": float(_safe_float(row.get("interest")) or 0.0),
        "depreciation": float(_safe_float(row.get("depreciation")) or 0.0),
        "taxes": float(_safe_float(row.get("taxes")) or 0.0),
        "net_income": float(_safe_float(row.get("net_income")) or 0.0),
        "cash": float(_safe_float(row.get("cash")) or 0.0),
        "ending_cash": float(_safe_float(row.get("ending_cash")) or 0.0),
        "accounts_receivable": float(_safe_float(row.get("accounts_receivable")) or 0.0),
        "inventory": float(_safe_float(row.get("inventory")) or 0.0),
        "prepaid_expenses": float(_safe_float(row.get("prepaid_expenses")) or 0.0),
        "current_assets": float(_safe_float(row.get("current_assets")) or 0.0),
        "noncurrent_assets": (
          float(_safe_float(row.get("total_assets")) or 0.0)
          - float(_safe_float(row.get("current_assets")) or 0.0)
        ),
        "ppe": float(_safe_float(row.get("ppe")) or 0.0),
        "accumulated_depreciation": float(_safe_float(row.get("accumulated_depreciation")) or 0.0),
        "total_assets": float(_safe_float(row.get("total_assets")) or 0.0),
        "accounts_payable": float(_safe_float(row.get("accounts_payable")) or 0.0),
        "short_term_debt": float(_safe_float(row.get("short_term_debt")) or 0.0),
        "deferred_revenue": float(_safe_float(row.get("deferred_revenue")) or 0.0),
        "current_liabilities": float(_safe_float(row.get("current_liabilities")) or 0.0),
        "long_term_debt": float(_safe_float(row.get("long_term_debt")) or 0.0),
        "total_liabilities": float(_safe_float(row.get("total_liabilities")) or 0.0),
        "owners_capital": float(_safe_float(row.get("owners_capital")) or 0.0),
        "distributions": float(_safe_float(row.get("distributions")) or 0.0),
        "retained_earnings": float(_safe_float(row.get("retained_earnings")) or 0.0),
        "other_equity": float(_safe_float(row.get("other_equity")) or 0.0),
        "total_equity": float(_safe_float(row.get("total_equity")) or 0.0),
        "total_liabilities_and_equity": float(_safe_float(row.get("total_liabilities_and_equity")) or 0.0),
        "beginning_cash": float(_safe_float(row.get("beginning_cash")) or 0.0),
        "changes_in_current_assets": float(_safe_float(row.get("changes_in_current_assets")) or 0.0),
        "changes_in_current_liabilities": float(_safe_float(row.get("changes_in_current_liabilities")) or 0.0),
        "operating_cash_flow": float(_safe_float(row.get("operating_cash_flow")) or 0.0),
        "capital_expenditures": float(_safe_float(row.get("capital_expenditures")) or 0.0),
        "investing_cash_flow": float(_safe_float(row.get("investing_cash_flow")) or 0.0),
        "debt_issuance": float(_safe_float(row.get("debt_issuance")) or 0.0),
        "debt_repayment": float(_safe_float(row.get("debt_repayment")) or 0.0),
        "debt_receive_repay": float(_safe_float(row.get("debt_receive_repay")) or 0.0),
        "equity": float(_safe_float(row.get("equity")) or 0.0),
        "owner_distributions": float(_safe_float(row.get("owner_distributions")) or 0.0),
        "financing_cash_flow": float(_safe_float(row.get("financing_cash_flow")) or 0.0),
        "net_cash_flow": float(_safe_float(row.get("net_cash_flow")) or 0.0),
        "noncurrent_liabilities": (
          float(_safe_float(row.get("total_liabilities")) or 0.0)
          - float(_safe_float(row.get("current_liabilities")) or 0.0)
        ),
      }
    )
  return out


def _issue_target_packets(issue_status_records: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
  packets: List[Dict[str, Any]] = []
  for item in _normalized_issue_status_records(issue_status_records):
    issue_code = str(item.get("issue_code") or "").strip().lower()
    objective = copy.deepcopy(_ISSUE_SOLVER_OBJECTIVES.get(issue_code) or {})
    packets.append(
      {
        "issue_code": issue_code,
        "verifier_status": str(item.get("verifier_status") or "").strip().lower(),
        "remaining_issue_materiality": str(item.get("remaining_issue_materiality") or "").strip().lower(),
        "remaining_issue_severity_score": int(item.get("remaining_issue_severity_score") or 0),
        "remaining_problem_quarters": copy.deepcopy(item.get("remaining_problem_quarters") or []),
        "next_required_lever_ids": copy.deepcopy(item.get("next_required_lever_ids") or []),
        "iteration_needed": bool(item.get("iteration_needed")),
        "metric_targets": copy.deepcopy(objective.get("metric_targets") or []),
        "solver_objective": str(objective.get("solver_objective") or "align_issue_to_viable_quarter_shape").strip(),
      }
    )
  return packets


def _quarter_target_grid(
  *,
  issue_status_records: Optional[List[Dict[str, Any]]],
  current_finmo_json: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  issue_packets = _issue_target_packets(issue_status_records)
  quarter_map: Dict[int, Dict[str, Any]] = {}
  for row in _quarter_metric_snapshots(current_finmo_json):
    quarter_index = int(row.get("quarter_index") or 0)
    if quarter_index < 1:
      continue
    quarter_map[quarter_index] = {
      "quarter_index": quarter_index,
      "baseline_metrics": copy.deepcopy(row),
      "target_metric_groups": [],
      "driving_issue_codes": [],
      "required_lever_ids": [],
    }
  for packet in issue_packets:
    issue_code = str(packet.get("issue_code") or "").strip().lower()
    for quarter_index in (packet.get("remaining_problem_quarters") or []):
      quarter = int(round(_safe_float(quarter_index) or 0.0))
      if quarter < 1:
        continue
      entry = quarter_map.setdefault(
        quarter,
        {
          "quarter_index": quarter,
          "baseline_metrics": {"quarter_index": quarter},
          "target_metric_groups": [],
          "driving_issue_codes": [],
          "required_lever_ids": [],
        },
      )
      for metric in (packet.get("metric_targets") or []):
        if metric not in entry["target_metric_groups"]:
          entry["target_metric_groups"].append(metric)
      if issue_code and issue_code not in entry["driving_issue_codes"]:
        entry["driving_issue_codes"].append(issue_code)
      for lever_id in (packet.get("next_required_lever_ids") or []):
        lever = str(lever_id).strip()
        if lever and lever not in entry["required_lever_ids"]:
          entry["required_lever_ids"].append(lever)
  return [quarter_map[key] for key in sorted(quarter_map.keys())]


def build_numeric_solver_contract(
  *,
  planning_mode: Any = None,
  planning_mode_reason: Any = None,
  selected_cash_strategy: Any = None,
  issue_status_records: Optional[List[Dict[str, Any]]] = None,
  writable_lever_catalog: Optional[List[Dict[str, Any]]] = None,
  current_model_input_json: Optional[Dict[str, Any]] = None,
  current_finmo_json: Optional[Dict[str, Any]] = None,
  pass_name: Optional[str] = None,
  contract_scope: Optional[str] = None,
) -> Dict[str, Any]:
  normalized_pass_name = str(pass_name or "").strip() or "generic"
  normalized_scope = str(contract_scope or "").strip() or "planning"
  normalized_issues = _enriched_issue_status_records(
    issue_status_records=issue_status_records,
    writable_lever_catalog=writable_lever_catalog,
    current_finmo_json=current_finmo_json,
  )
  active_issues = [
    item
    for item in normalized_issues
    if str(item.get("verifier_status") or "").strip().lower() != "resolved"
  ]
  lever_entries = [
    copy.deepcopy(item)
    for item in (writable_lever_catalog or [])
    if isinstance(item, dict) and str(item.get("lever_id") or "").strip()
  ]
  recommended_primary_target_metric_keys = _recommended_primary_target_metric_keys(active_issues)
  return {
    "contract_version": NUMERIC_SOLVER_CONTRACT_VERSION,
    "solver_phase_status": _solver_phase_status_for_pass(normalized_pass_name),
    "current_numeric_executor": CURRENT_NUMERIC_EXECUTOR,
    "target_numeric_executor": TARGET_NUMERIC_EXECUTOR,
    "pass_name": normalized_pass_name,
    "contract_scope": normalized_scope,
    "planning_mode_profile": _normalized_planning_mode_profile(
      planning_mode,
      planning_mode_reason,
      pass_name=normalized_pass_name,
    ),
    "selected_cash_strategy": str(selected_cash_strategy or "").strip(),
    "active_issue_count": len(active_issues),
    "issue_target_packets": _issue_target_packets(active_issues),
    "quarter_target_grid": _quarter_target_grid(
      issue_status_records=active_issues,
      current_finmo_json=current_finmo_json,
    ),
    "allowed_target_metric_ids": list(PRIMARY_TARGETABLE_FINMO_METRIC_IDS),
    "recommended_primary_target_metric_keys": copy.deepcopy(recommended_primary_target_metric_keys),
    "primary_target_metric_min_count": int(PRIMARY_TARGET_METRIC_MIN_COUNT),
    "primary_target_metric_max_count": int(PRIMARY_TARGET_METRIC_MAX_COUNT),
    "guardrail_metric_names": [
      "ending_cash",
      "ebitda",
      "net_income",
      "operating_cash_flow",
      "financing_cash_flow",
      "current_assets",
      "ppe",
      "current_liabilities",
      "noncurrent_liabilities",
    ],
    "writable_lever_catalog": {
      "lever_count": len(lever_entries),
      "lever_ids": [str(item.get("lever_id") or "").strip() for item in lever_entries],
      "entries": lever_entries,
    },
    "baseline_quarter_metrics": _quarter_metric_snapshots(current_finmo_json),
    "solver_settings": _normalized_solver_settings(
      pass_name=normalized_pass_name,
      planning_mode=planning_mode,
    ),
    "immutable_core_model_files": list(IMMUTABLE_CORE_MODEL_FILES),
    "current_model_present": bool(isinstance(current_model_input_json, dict) and current_model_input_json),
    "current_finmo_present": bool(isinstance(current_finmo_json, dict) and current_finmo_json),
    "behavior_change": False,
  }


def _review_plan_required_target_metric_keys(review_plan: Optional[Dict[str, Any]]) -> List[str]:
  plan = review_plan if isinstance(review_plan, dict) else {}
  plan_level = [
    _normalized_primary_target_metric_name(item)
    for item in (plan.get("required_target_metric_keys") or [])
  ]
  normalized_plan_level = [item for item in plan_level if item]
  if normalized_plan_level:
    return list(dict.fromkeys(normalized_plan_level))
  collected: List[str] = []
  for action in [item for item in ((plan.get("translated_action_packages") or [])) if isinstance(item, dict)]:
    action_collected = False
    for metric_name in (action.get("required_target_metric_keys") or []):
      normalized = _normalized_primary_target_metric_name(metric_name)
      if normalized and normalized not in collected:
        collected.append(normalized)
        action_collected = True
    if action_collected:
      continue
    for target in [item for item in (action.get("quarter_target_metrics") or []) if isinstance(item, dict)]:
      for metric_name in TARGETABLE_FINMO_METRIC_IDS:
        normalized = _normalized_primary_target_metric_name(metric_name)
        if normalized and _safe_float(target.get(metric_name)) is not None and normalized not in collected:
          collected.append(normalized)
  return collected


def build_numeric_execution_boundary_payload(
  *,
  phase_status: Optional[str] = None,
  behavior_change: bool = False,
) -> Dict[str, Any]:
  resolved_phase_status = str(phase_status or "").strip() or SOLVER_PHASE_8_STATUS
  return {
    "contract_version": NUMERIC_EXECUTION_BOUNDARY_VERSION,
    "current_numeric_executor": CURRENT_NUMERIC_EXECUTOR,
    "target_numeric_executor": TARGET_NUMERIC_EXECUTOR,
    "solver_phase_status": resolved_phase_status,
    "behavior_change": bool(behavior_change),
    "immutable_core_model_files": list(IMMUTABLE_CORE_MODEL_FILES),
    "immutable_core_flow": "model_input_json -> finmo_json",
    "phase_scope": _phase_scope_for_status(resolved_phase_status),
  }


def build_numeric_execution_plan(
  *,
  numeric_solver_contract: Optional[Dict[str, Any]],
  exact_updates: List[Dict[str, Any]],
  review_plan: Optional[Dict[str, Any]] = None,
  executor_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  contract = numeric_solver_contract if isinstance(numeric_solver_contract, dict) else {}
  touched_lever_ids = sorted(
    {
      str(item.get("lever_id") or "").strip()
      for item in exact_updates
      if isinstance(item, dict) and str(item.get("lever_id") or "").strip()
    }
  )
  touched_quarters = sorted(
    {
      int(round(_safe_float(item.get("quarter_index")) or 0.0))
      for item in exact_updates
      if isinstance(item, dict) and int(round(_safe_float(item.get("quarter_index")) or 0.0)) >= 1
    }
  )
  target_metric_names: List[str] = []
  allowed_lever_ids: List[str] = []
  targeted_quarters: List[int] = []
  quarter_target_payloads: List[Dict[str, Any]] = []
  target_tolerances: List[Dict[str, Any]] = []
  required_target_metric_keys = _review_plan_required_target_metric_keys(review_plan)
  for action in [item for item in ((review_plan or {}).get("translated_action_packages") or []) if isinstance(item, dict)]:
    action_required_target_metric_keys = [
      _normalized_primary_target_metric_name(item)
      for item in (action.get("required_target_metric_keys") or required_target_metric_keys)
    ]
    action_required_target_metric_keys = [item for item in action_required_target_metric_keys if item]
    for lever_id in (action.get("solver_allowed_lever_ids") or []):
      lever = str(lever_id).strip()
      if lever and lever not in allowed_lever_ids:
        allowed_lever_ids.append(lever)
    for tolerance_item in (action.get("target_tolerances") or []):
      if not isinstance(tolerance_item, dict):
        continue
      metric_name = _normalized_primary_target_metric_name(tolerance_item.get("metric_name"))
      if not metric_name:
        continue
      if any(str(existing.get("metric_name") or "").strip().lower() == metric_name for existing in target_tolerances):
        continue
      target_tolerances.append(
        {
          "metric_name": metric_name,
          "relative_tolerance_pct": _safe_float(tolerance_item.get("relative_tolerance_pct")),
          "absolute_tolerance": _safe_float(tolerance_item.get("absolute_tolerance")),
          "tolerance_reason": str(tolerance_item.get("tolerance_reason") or "").strip(),
        }
      )
    for item in (action.get("quarter_target_metrics") or []):
      if not isinstance(item, dict):
        continue
      quarter_index = int(round(_safe_float(item.get("quarter_index")) or 0.0))
      if quarter_index < 1:
        continue
      if quarter_index not in targeted_quarters:
        targeted_quarters.append(quarter_index)
      quarter_metric_names: List[str] = []
      for metric_name in TARGETABLE_FINMO_METRIC_IDS:
        if _safe_float(item.get(metric_name)) is None:
          continue
        quarter_metric_names.append(metric_name)
        if metric_name not in target_metric_names:
          target_metric_names.append(metric_name)
      quarter_target_payloads.append(
        {
          "quarter_index": quarter_index,
          "target_metric_names": quarter_metric_names,
          "required_target_metric_keys": copy.deepcopy(action_required_target_metric_keys),
          "allowed_lever_ids": [
            str(lever_id).strip()
            for lever_id in (action.get("solver_allowed_lever_ids") or [])
            if str(lever_id).strip()
          ],
        }
      )
  quarter_target_payloads.sort(key=lambda item: int(item.get("quarter_index") or 0))
  return {
    "contract_version": NUMERIC_EXECUTION_PLAN_VERSION,
    "numeric_executor": CURRENT_NUMERIC_EXECUTOR,
    "target_numeric_executor": TARGET_NUMERIC_EXECUTOR,
    "solver_phase_status": str(contract.get("solver_phase_status") or "").strip() or _solver_phase_status_for_pass(contract.get("pass_name")),
    "pass_name": str(contract.get("pass_name") or "").strip() or "generic",
    "contract_scope": str(contract.get("contract_scope") or "").strip() or "planning",
    "execution_mode": "quarter_specific_targets_only",
    "quarter_execution_order": "ascending",
    "lumped_horizon_objective_used": False,
    "attempt_budget": int(round(_safe_float(((contract.get("solver_settings") or {}).get("max_solver_attempts_per_pass")) or 0.0) or 0.0)) or 3,
    "touched_lever_ids": touched_lever_ids,
    "touched_quarters": touched_quarters,
    "targeted_quarters": sorted(targeted_quarters),
    "target_metric_names": target_metric_names,
    "required_target_metric_keys": copy.deepcopy(required_target_metric_keys),
    "target_tolerances": copy.deepcopy(target_tolerances),
    "quarter_target_payloads": quarter_target_payloads,
    "allowed_lever_ids": allowed_lever_ids,
    "proposed_update_count": len([item for item in exact_updates if isinstance(item, dict)]),
    "executor_context": copy.deepcopy(executor_context or {}),
  }


def _execution_outcome_assessment(
  *,
  exact_updates: List[Dict[str, Any]],
  execution_plan: Dict[str, Any],
) -> Dict[str, Any]:
  update_count = len([item for item in exact_updates if isinstance(item, dict)])
  if update_count <= 0:
    return {
      "execution_state": "no_numeric_updates",
      "updates_present": False,
      "reason": "No numeric updates were available to apply.",
    }
  return {
    "execution_state": "numeric_updates_applied",
    "updates_present": True,
    "reason": "Concrete numeric updates were applied to the model.",
  }


def execute_core_model_updates(
  *,
  model_input_json: Optional[Dict[str, Any]],
  exact_updates: List[Dict[str, Any]],
  phase_status: Optional[str] = None,
  executor_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  try:
    from client_intake_and_finmo.quarter_grid import apply_exact_lever_updates_to_model_input  # type: ignore
  except Exception:
    from quarter_grid import apply_exact_lever_updates_to_model_input  # type: ignore
  try:
    from client_intake_and_finmo.finmo_bridge import build_python_finmo_json  # type: ignore
  except Exception:
    from finmo_bridge import build_python_finmo_json  # type: ignore

  updated_model_input_json = apply_exact_lever_updates_to_model_input(
    model_input_json=model_input_json if isinstance(model_input_json, dict) else {},
    exact_updates=[item for item in exact_updates if isinstance(item, dict)],
  )
  updated_finmo_json = build_python_finmo_json(model_input_json=updated_model_input_json)

  return {
    "numeric_execution_boundary": build_numeric_execution_boundary_payload(phase_status=phase_status),
    "solver_phase_status": str(phase_status or "").strip() or SOLVER_PHASE_8_STATUS,
    "numeric_executor": CURRENT_NUMERIC_EXECUTOR,
    "numeric_execution_mode": "canonical_model_apply",
    "executor_context": copy.deepcopy(executor_context or {}),
    "updated_model_input_json": updated_model_input_json,
    "updated_finmo_json": updated_finmo_json,
  }


def execute_numeric_plan(
  *,
  model_input_json: Optional[Dict[str, Any]],
  exact_updates: List[Dict[str, Any]],
  numeric_solver_contract: Optional[Dict[str, Any]] = None,
  review_plan: Optional[Dict[str, Any]] = None,
  phase_status: Optional[str] = None,
  executor_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  solver_result: Dict[str, Any] = {}
  final_exact_updates = [copy.deepcopy(item) for item in exact_updates if isinstance(item, dict)]
  contract = numeric_solver_contract if isinstance(numeric_solver_contract, dict) else {}
  resolved_phase_status = (
    str(phase_status or "").strip()
    or str(contract.get("solver_phase_status") or "").strip()
    or _solver_phase_status_for_pass(contract.get("pass_name"))
  )
  try:
    from client_intake_and_finmo.numeric_solver import solve_review_plan  # type: ignore
  except Exception:
    try:
      from numeric_solver import solve_review_plan  # type: ignore
    except Exception:
      solve_review_plan = None  # type: ignore
  if callable(solve_review_plan):
    try:
      solver_result = solve_review_plan(
        model_input_json=model_input_json,
        review_plan=review_plan,
        numeric_solver_contract=numeric_solver_contract,
        fallback_exact_updates=final_exact_updates,
      )
      solved_updates = solver_result.get("exact_updates") if isinstance(solver_result.get("exact_updates"), list) else []
      if solved_updates:
        final_exact_updates = [copy.deepcopy(item) for item in solved_updates if isinstance(item, dict)]
    except Exception as exc:
      solver_result = {
        "execution_state": "numeric_solver_exception",
        "solver_invoked": False,
        "exact_updates": [copy.deepcopy(item) for item in final_exact_updates],
        "attempts": [],
        "outcome": {"execution_state": "numeric_solver_exception", "reason": str(exc)},
      }
  execution_plan = build_numeric_execution_plan(
    numeric_solver_contract=numeric_solver_contract,
    exact_updates=final_exact_updates,
    review_plan=review_plan,
    executor_context=executor_context,
  )
  base_result = execute_core_model_updates(
    model_input_json=model_input_json,
    exact_updates=final_exact_updates,
    phase_status=resolved_phase_status,
    executor_context=executor_context,
  )
  outcome = _execution_outcome_assessment(
    exact_updates=final_exact_updates,
    execution_plan=execution_plan,
  )
  if isinstance(solver_result.get("outcome"), dict):
    outcome = {**copy.deepcopy(outcome), **copy.deepcopy(solver_result.get("outcome") or {})}
  return {
    "contract_version": NUMERIC_EXECUTION_RESULT_VERSION,
    **base_result,
    "solver_phase_status": base_result.get("solver_phase_status") or SOLVER_PHASE_8_STATUS,
    "numeric_execution_mode": "live_gpt_led_number_cruncher",
    "numeric_execution_plan": execution_plan,
    "numeric_execution_attempts": (
      copy.deepcopy(solver_result.get("attempts") or [])
      if isinstance(solver_result.get("attempts"), list) and (solver_result.get("attempts") or [])
      else [
        {
          "attempt_index": 1,
          "quarter_index": None,
          "applied_update_count": len([item for item in final_exact_updates if isinstance(item, dict)]),
          "outcome": copy.deepcopy(outcome),
        }
      ]
    ),
    "numeric_execution_outcome": outcome,
    "numeric_solver_result": copy.deepcopy(solver_result or {}),
  }
