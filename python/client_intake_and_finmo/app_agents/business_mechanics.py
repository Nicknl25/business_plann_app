from __future__ import annotations

from typing import Any, Dict, List


def _text(value: Any) -> str:
  return str(value or "").strip()


def _safe_float(value: Any) -> float:
  try:
    return float(value)
  except Exception:
    return 0.0


def _contains_any(text: str, keywords: List[str]) -> bool:
  lowered = _text(text).lower()
  return any(keyword in lowered for keyword in keywords)


def _classify_row(row: Dict[str, Any]) -> List[str]:
  row_id = _text(row.get("row_id"))
  label = _text(row.get("label") or row_id)
  lowered = f"{row_id} {label}".lower()
  groups: List[str] = []

  if row_id == "Revenue":
    groups.append("output_revenue")
  if row_id == "EBITDA":
    groups.append("output_ebitda")
  if row_id == "Cash":
    groups.append("output_cash")

  if "capacity" in lowered:
    groups.append("capacity_drivers")
  if "utilization" in lowered:
    groups.append("utilization_drivers")
  if "price" in lowered:
    groups.append("pricing_drivers")
  if any(token in lowered for token in ("marketing", "advertis", "lead", "cac", "sales commission", "channel")):
    groups.append("demand_generation")
  if any(token in lowered for token in ("payroll", "salary", "wage", "labor", "staff", "headcount", "provider compensation")):
    groups.append("payroll_labor")
  if any(token in lowered for token in ("rent", "lease", "g&a", "general and administrative", "admin", "office", "software", "insurance", "utilities", "other operating")):
    groups.append("support_opex")
  if any(token in lowered for token in ("capital expenditures", "capex", "equipment", "leasehold", "ppe")):
    groups.append("capital_deployment")
  if any(token in lowered for token in ("debt", "principal", "interest", "equity", "distribution", "dividend", "owner draw", "owner contribution", "additions")):
    groups.append("financing_flows")
  if any(token in lowered for token in ("receivable", "payable", "inventory", "prepaid", "deferred", "tax")):
    groups.append("working_capital_and_tax")
  return groups


def _group_catalog(row_catalog: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
  labels = {
    "output_revenue": "Revenue output",
    "output_ebitda": "EBITDA output",
    "output_cash": "Cash output",
    "capacity_drivers": "Capacity drivers",
    "utilization_drivers": "Utilization drivers",
    "pricing_drivers": "Pricing drivers",
    "demand_generation": "Demand generation",
    "payroll_labor": "Payroll and labor support",
    "support_opex": "Support operating costs",
    "capital_deployment": "Capital deployment",
    "financing_flows": "Debt, equity, and principal behavior",
    "working_capital_and_tax": "Working capital and taxes",
  }
  grouped: Dict[str, List[str]] = {group_id: [] for group_id in labels}
  for row in row_catalog:
    if not isinstance(row, dict):
      continue
    row_id = _text(row.get("row_id"))
    if not row_id:
      continue
    for group_id in _classify_row(row):
      grouped.setdefault(group_id, [])
      if row_id not in grouped[group_id]:
        grouped[group_id].append(row_id)
  return [
    {"group_id": group_id, "label": label, "row_ids": grouped.get(group_id, [])}
    for group_id, label in labels.items()
  ]


def _group_row_ids(driver_groups: List[Dict[str, Any]], group_id: str) -> List[str]:
  for group in driver_groups:
    if not isinstance(group, dict):
      continue
    if _text(group.get("group_id")) != group_id:
      continue
    return [_text(item) for item in (group.get("row_ids") or []) if _text(item)]
  return []


def _growth_story_present(ops_json: Dict[str, Any], strategy_label: str) -> bool:
  growth_text = " ".join(
    _text(item)
    for item in (
      ops_json.get("goal_12_months"),
      ops_json.get("growth_lever"),
      ops_json.get("business_description"),
      ops_json.get("competitive_advantage"),
    )
  )
  if _contains_any(growth_text, ["grow", "growth", "increase", "expand", "scale", "reach", "add provider", "add providers", "hire", "ramp", "more sessions", "higher utilization"]):
    return True
  return strategy_label in {"reinvest", "balanced"}


def build_business_mechanics_profile(
  *,
  business_profile: Dict[str, Any],
  strategy_profile: Dict[str, Any],
  ops_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  baseline_summary: Dict[str, Any],
  row_catalog: List[Dict[str, Any]],
) -> Dict[str, Any]:
  business_text = " ".join(
    _text(item)
    for item in (
      business_profile.get("business_description"),
      business_profile.get("business_model"),
      business_profile.get("business_type"),
      business_profile.get("delivery_method"),
      business_profile.get("sales_channel"),
      business_profile.get("growth_lever"),
      ops_json.get("goal_12_months"),
    )
  )
  strategy_value = _text(strategy_profile.get("cash_strategy_value")).lower()
  driver_groups = _group_catalog(row_catalog)
  ebitda = _safe_float((baseline_summary or {}).get("ebitda"))
  net_income = _safe_float((baseline_summary or {}).get("net_income"))
  revenue = _safe_float((baseline_summary or {}).get("revenue"))
  ending_cash_q4 = _safe_float((baseline_summary or {}).get("ending_cash_q4"))
  ebitda_margin = (ebitda / revenue) if revenue > 0 else 0.0

  if ebitda < 0 or net_income < 0:
    planning_mode = "turnaround"
    planning_mode_reason = "baseline is loss-making, so the planner must build a credible repair path instead of preserving fantasy."
  elif ebitda_margin > 0.30:
    planning_mode = "normalize"
    planning_mode_reason = "baseline profitability appears overstated for many real businesses, so the planner must challenge optimistic drivers."
  else:
    planning_mode = "rebalance"
    planning_mode_reason = "baseline is directionally usable but must be rebalanced into a more coherent, strategy-visible business plan."

  acquisition_motion_required = _contains_any(
    " ".join(_text(item) for item in (business_profile.get("sales_channel"), ops_json.get("sales_channel"), business_profile.get("growth_lever"))),
    ["paid ads", "ads", "marketing", "online scheduling", "lead", "sales", "book", "bookings", "demand"],
  )
  labor_scaling_required = _contains_any(
    business_text,
    ["in person", "treatment", "provider", "session", "studio", "clinic", "med spa", "service", "appointment", "delivery"],
  ) or bool(_group_row_ids(driver_groups, "payroll_labor"))
  growth_story_present = _growth_story_present(ops_json, strategy_value)
  capital_deployment_required = strategy_value in {"reinvest", "balanced", "shareholder_return"}
  working_capital_motion_expected = bool(_group_row_ids(driver_groups, "working_capital_and_tax")) and growth_story_present

  baseline_pressure_points: List[str] = []
  if growth_story_present:
    baseline_pressure_points.append("The business context describes growth or expansion, so the final grid must show real operating change instead of preserving a flat baseline.")
  if ending_cash_q4 > 0:
    baseline_pressure_points.append("Baseline cash is already positive, so the planner must decide whether to retain, deploy, or extract cash in a visible strategy-specific way.")
  if ebitda_margin > 0.25:
    baseline_pressure_points.append("Baseline profitability is strong enough that the planner must challenge whether price, utilization, and support rows are still realistic together.")
  if acquisition_motion_required:
    baseline_pressure_points.append("Demand appears acquisition-driven, so utilization or growth cannot be detached from marketing support.")
  if labor_scaling_required:
    baseline_pressure_points.append("The business looks labor- or provider-constrained, so scaling requires payroll and support to move with demand and capacity.")

  anti_flat_rules = [
    "Do not leave the entire business flat for 20 quarters unless the context truly describes a stable no-growth company.",
    "If the business has a growth goal, Revenue and at least one core revenue driver group must show visible movement.",
    "If the business is labor-constrained, payroll cannot stay frozen while growth, utilization, or capacity increases.",
    "If the sales model depends on marketing or lead generation, demand rows cannot remain mechanically flat while growth is claimed.",
    "Under reinvest or balanced strategy, excess cash must not appear only as a staircase with token capex changes.",
  ]

  profitability_standard = [
    "Push toward profitability as early as realism allows without inventing fantasy economics.",
    "Do not preserve persistent multi-year losses if a believable operating repair exists.",
    "If the baseline is too optimistic, normalize price, utilization, capacity, or support rows rather than protecting them blindly.",
  ]

  shared_capacity_rules = [
    "Reason at the business-model and operating-engine level, not just row by row.",
    "When products or services share one operating engine, treat that capacity as one conserved pool.",
    "Do not silently give every product or service full standalone capacity unless the context clearly supports it.",
  ]

  interaction_rules = [
    {
      "rule_id": "revenue_driver_support_link",
      "description": "Growth in Revenue must be supported by believable movement in at least one revenue driver and one support group.",
      "trigger_rows": _group_row_ids(driver_groups, "output_revenue"),
      "required_rows": _group_row_ids(driver_groups, "capacity_drivers") + _group_row_ids(driver_groups, "utilization_drivers") + _group_row_ids(driver_groups, "pricing_drivers") + _group_row_ids(driver_groups, "payroll_labor") + _group_row_ids(driver_groups, "demand_generation"),
    },
    {
      "rule_id": "provider_scaling_link",
      "description": "Provider- or labor-constrained businesses must move payroll and support rows when scaling demand, throughput, or capacity.",
      "trigger_rows": _group_row_ids(driver_groups, "capacity_drivers") + _group_row_ids(driver_groups, "utilization_drivers") + _group_row_ids(driver_groups, "output_revenue"),
      "required_rows": _group_row_ids(driver_groups, "payroll_labor") + _group_row_ids(driver_groups, "support_opex"),
    },
    {
      "rule_id": "acquisition_link",
      "description": "Acquisition-driven growth must show demand-support movement rather than claiming utilization growth in the dark.",
      "trigger_rows": _group_row_ids(driver_groups, "output_revenue") + _group_row_ids(driver_groups, "utilization_drivers"),
      "required_rows": _group_row_ids(driver_groups, "demand_generation"),
    },
    {
      "rule_id": "capital_strategy_link",
      "description": "Cash strategy must show up numerically through deployment, financing behavior, or retained buffers rather than a default staircase.",
      "trigger_rows": _group_row_ids(driver_groups, "output_cash"),
      "required_rows": _group_row_ids(driver_groups, "capital_deployment") + _group_row_ids(driver_groups, "financing_flows") + _group_row_ids(driver_groups, "payroll_labor") + _group_row_ids(driver_groups, "demand_generation"),
    },
    {
      "rule_id": "working_capital_link",
      "description": "When growth or deployment materially changes the business, working capital and tax timing rows should not all remain frozen.",
      "trigger_rows": _group_row_ids(driver_groups, "output_revenue") + _group_row_ids(driver_groups, "capital_deployment"),
      "required_rows": _group_row_ids(driver_groups, "working_capital_and_tax"),
    },
  ]

  return {
    "planning_mode": planning_mode,
    "planning_mode_reason": planning_mode_reason,
    "growth_story_present": bool(growth_story_present),
    "acquisition_motion_required": bool(acquisition_motion_required),
    "labor_scaling_required": bool(labor_scaling_required),
    "capital_deployment_required": bool(capital_deployment_required),
    "working_capital_motion_expected": bool(working_capital_motion_expected),
    "baseline_pressure_points": baseline_pressure_points,
    "profitability_standard": profitability_standard,
    "shared_capacity_rules": shared_capacity_rules,
    "anti_flat_rules": anti_flat_rules,
    "driver_groups": driver_groups,
    "interaction_rules": interaction_rules,
  }
