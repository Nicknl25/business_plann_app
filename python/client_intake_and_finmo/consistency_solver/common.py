from __future__ import annotations

import copy
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple


BLOCKING_CODES = {
  "capacity_unsupported",
  "ebitda_margin_too_low",
  "gross_margin_too_low",
  "payroll_too_light",
  "payroll_too_heavy",
}


def _clone(value: Any) -> Any:
  return copy.deepcopy(value)


def _safe_float(value: Any) -> float:
  try:
    num = float(value)
  except Exception:
    return 0.0
  if num != num:
    return 0.0
  return num


def _safe_int(value: Any) -> int:
  try:
    return int(round(float(value)))
  except Exception:
    return 0


def _normalize_ratio(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  raw = _safe_float(value)
  if raw > 1.0:
    raw = raw / 100.0
  return max(0.0, min(1.0, raw))


def _in_test_context() -> bool:
  joined_argv = " ".join(str(arg or "") for arg in sys.argv).lower()
  return (
    "test_planning_engines.py" in joined_argv
    or "unittest" in joined_argv
    or "\\tests\\" in joined_argv
  )


def _bool_env(name: str, default: bool) -> bool:
  raw = str(os.getenv(name) or "").strip().lower()
  if not raw:
    return default
  if raw in {"1", "true", "yes", "on"}:
    return True
  if raw in {"0", "false", "no", "off"}:
    return False
  return default


def _gpt_strategy_required() -> bool:
  if _in_test_context():
    return _bool_env("CONSISTENCY_GPT_STRATEGY_LAYER", False)
  return True


def _intensity_score(value: Any) -> float:
  raw = str(value or "").strip().lower()
  if raw == "strong":
    return 1.0
  if raw == "moderate":
    return 0.65
  if raw == "light":
    return 0.35
  return 0.5


def _severity_score(value: Any) -> float:
  raw = str(value or "").strip().lower()
  if raw == "severe":
    return 1.0
  if raw == "moderate":
    return 0.65
  if raw == "mild":
    return 0.35
  return 0.5


def _quarter_bounds(entry: Dict[str, Any]) -> Tuple[int, int]:
  start = max(1, _safe_int(entry.get("quarter_start")) or 1)
  end = max(start, _safe_int(entry.get("quarter_end")) or start)
  return start, end


def _family_synonyms() -> Dict[str, str]:
  return {
    "pricing": "pricing",
    "price": "pricing",
    "price_up": "pricing",
    "price_down": "pricing",
    "utilization": "utilization",
    "util": "utilization",
    "util_up": "utilization",
    "util_down": "utilization",
    "utilization_demand": "utilization_demand",
    "utilization_and_volume": "utilization_demand",
    "volume": "utilization_demand",
    "volume_demand": "utilization_demand",
    "marketing": "marketing_spend",
    "marketing_spend": "marketing_spend",
    "marketing_up": "marketing_spend",
    "marketing_down": "marketing_spend",
    "marketing_to_demand_link": "marketing_to_demand_link",
    "staffing_timing": "staffing_and_hiring_timing",
    "staffing_timing_capacity": "staffing_and_hiring_timing",
    "staffing_and_capacity_timing": "staffing_and_hiring_timing",
    "staffing_and_hiring_timing": "staffing_and_hiring_timing",
    "hire_delay": "staffing_and_hiring_timing",
    "hire_advance": "staffing_and_hiring_timing",
    "hiring_timing_and_structural_payroll": "staffing_and_hiring_timing",
    "staffing_support": "staffing_support",
    "payroll_up": "core_payroll",
    "payroll_down": "core_payroll",
    "core_leadership_payroll": "core_payroll",
    "core_founder_payroll": "core_payroll",
    "founder_payroll": "core_payroll",
    "structural_payroll": "core_payroll",
    "overhead_opex": "other_opex",
    "non_payroll_opex": "other_opex",
    "other_opex": "other_opex",
    "opex": "other_opex",
    "other_opex_up": "other_opex",
    "other_opex_down": "other_opex",
    "cogs": "cogs",
    "cogs_up": "cogs",
    "cogs_down": "cogs",
    "cogs_reduction": "cogs",
    "cogs_efficiency": "cogs",
    "capacity_expansion": "capacity_expansion",
  }


def _normalized_family_name(value: Any) -> str:
  raw = str(value or "").strip().lower()
  return _family_synonyms().get(raw, raw)


def _normalized_plan_entry_families(entry: Dict[str, Any]) -> List[str]:
  family = _normalized_family_name(entry.get("family"))
  direction = str(entry.get("direction") or "").strip().lower()
  if direction in {"", "hold"}:
    return []
  if family == "pricing":
    return ["price_up"] if direction == "up" else ["price_down"] if direction == "down" else ["price_up", "price_down"]
  if family in {"utilization", "utilization_demand"}:
    return ["util_up"] if direction == "up" else ["util_down"] if direction == "down" else ["util_up", "util_down"]
  if family == "marketing_spend":
    return ["marketing_up"] if direction == "up" else ["marketing_down"] if direction == "down" else ["marketing_up", "marketing_down"]
  if family == "marketing_to_demand_link":
    return ["util_up"] if direction == "up" else ["marketing_down"] if direction == "down" else ["util_up", "marketing_up"]
  if family == "other_opex":
    return ["other_opex_up"] if direction == "up" else ["other_opex_down"] if direction == "down" else ["other_opex_up", "other_opex_down"]
  if family == "cogs":
    return ["cogs_up"] if direction == "up" else ["cogs_down"] if direction == "down" else ["cogs_up", "cogs_down"]
  if family in {"staffing_and_hiring_timing", "staffing_support"}:
    if direction == "down":
      return ["hire_delay", "payroll_down"]
    if direction == "up":
      return ["hire_advance", "payroll_up"]
    return ["hire_delay", "hire_advance", "payroll_down", "payroll_up"]
  if family == "core_payroll":
    return ["payroll_up"] if direction == "up" else ["payroll_down"] if direction == "down" else ["payroll_up", "payroll_down"]
  if family == "capacity_expansion":
    return ["hire_advance"] if direction == "up" else ["hire_delay"] if direction == "down" else ["hire_advance", "hire_delay"]
  return []


def _unique_strings(values: Sequence[Any]) -> List[str]:
  seen: Set[str] = set()
  result: List[str] = []
  for item in values:
    value = str(item or "").strip()
    if not value or value in seen:
      continue
    seen.add(value)
    result.append(value)
  return result


def _package_expected_effects(
  packages: Sequence[Dict[str, Any]],
  *,
  lever_plan: Optional[Sequence[Dict[str, Any]]] = None,
  max_quarter: Optional[int] = None,
) -> List[str]:
  lever_plan = lever_plan if isinstance(lever_plan, Sequence) else []
  down_families = {
    _normalized_family_name(item.get("family"))
    for item in lever_plan
    if isinstance(item, dict) and str(item.get("direction") or "").strip().lower() == "down"
  }
  effects: List[str] = []
  for package in packages or []:
    if not isinstance(package, dict):
      continue
    start, _ = _quarter_bounds(package)
    if max_quarter is not None and start > max_quarter:
      continue
    for effect in package.get("expected_effects") or []:
      text = str(effect or "").strip().lower()
      if not text:
        continue
      if "support overhead rises" in text or "support overhead" in text:
        if "other_opex" in down_families:
          continue
        effects.append("support_opex_required")
        continue
      if "marketing support" in text or "demand growth requires marketing" in text:
        effects.append("marketing_support_required")
        continue
      if "capacity expands with staffing" in text or "capacity_tighter_until_hires" in text:
        effects.append("staffing_capacity_link")
        continue
      effects.append(text.replace(" ", "_"))
  return _unique_strings(effects)


def _derive_commercial_archetype(
  *,
  normalized_traits: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  fixed_facts: Optional[Dict[str, Any]] = None,
  lever_families: Optional[Sequence[str]] = None,
) -> str:
  traits = normalized_traits if isinstance(normalized_traits, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  facts = fixed_facts if isinstance(fixed_facts, dict) else {}
  capacity_driver = str(
    traits.get("capacity_driver")
    or ops.get("capacity_driver")
    or facts.get("capacity_driver")
    or ""
  ).strip().lower()
  sales_modality = str(
    traits.get("sales_modality")
    or ops.get("sales_modality")
    or facts.get("sales_modality")
    or ""
  ).strip().lower()
  customer_type = str(
    traits.get("customer_type")
    or ops.get("customer_type")
    or facts.get("customer_type")
    or ""
  ).strip().lower()
  unit_cadence = str(
    traits.get("unit_cadence")
    or ops.get("unit_cadence")
    or facts.get("unit_cadence")
    or ""
  ).strip().lower()

  if capacity_driver == "labor" and sales_modality in {"local_service", "project_based"}:
    if unit_cadence in {"contract", "project"}:
      return "labor_professional_service"
    return "labor_local_service"
  if sales_modality == "retail":
    return "retail_store"
  if sales_modality == "online" and capacity_driver in {"system", "space", "equipment"}:
    return "scalable_online"
  if unit_cadence in {"recurring", "subscription"}:
    if capacity_driver == "system":
      return "subscription_model"
    if capacity_driver == "labor":
      return "recurring_labor_service"
  if customer_type == "b2b" and capacity_driver == "labor" and unit_cadence in {"contract", "project"}:
    return "labor_professional_service"

  lever_families = list(lever_families or [])
  if any(item in {"marketing_up", "hire_advance", "payroll_up"} for item in lever_families):
    return "growth"
  if any(item in {"other_opex_down", "cogs_down", "payroll_down"} for item in lever_families):
    return "efficiency"
  if capacity_driver == "system":
    return "system_service"
  if capacity_driver == "space":
    return "space_service"
  return "general_operating_business"


def _commercial_context_policy(
  *,
  normalized_traits: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  current_marketing: float,
  current_other_opex: float,
) -> Dict[str, Any]:
  traits = normalized_traits if isinstance(normalized_traits, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  sales_modality = str(traits.get("sales_modality") or ops.get("sales_modality") or "").strip().lower()
  capacity_driver = str(traits.get("capacity_driver") or ops.get("capacity_driver") or "").strip().lower()
  customer_type = str(traits.get("customer_type") or "").strip().lower()
  business_stage = str(traits.get("business_stage") or "").strip().lower()
  archetype = _derive_commercial_archetype(
    normalized_traits=traits,
    ops_json=ops,
  )

  marketing_role = "supporting"
  marketing_up_cap_ratio = 0.22
  marketing_down_cap_ratio = 0.35
  marketing_demand_link = True
  opex_flexibility = "moderate"
  other_opex_down_cap_ratio = 0.10
  other_opex_up_cap_ratio = 0.08

  if archetype in {"labor_local_service", "labor_professional_service"}:
    marketing_role = "constrained"
    marketing_up_cap_ratio = 0.06 if customer_type == "b2b" else 0.09
    marketing_down_cap_ratio = 0.25
    marketing_demand_link = False
    opex_flexibility = "tight"
    other_opex_down_cap_ratio = 0.06
    other_opex_up_cap_ratio = 0.04
  elif archetype == "retail_store":
    marketing_role = "supporting"
    marketing_up_cap_ratio = 0.18
    marketing_down_cap_ratio = 0.25
    marketing_demand_link = True
    opex_flexibility = "moderate"
    other_opex_down_cap_ratio = 0.10
    other_opex_up_cap_ratio = 0.08
  elif archetype == "scalable_online":
    marketing_role = "primary"
    marketing_up_cap_ratio = 0.45
    marketing_down_cap_ratio = 0.30
    marketing_demand_link = True
    opex_flexibility = "moderate"
    other_opex_down_cap_ratio = 0.12
    other_opex_up_cap_ratio = 0.10
  elif archetype in {"subscription_model", "recurring_labor_service"}:
    marketing_role = "supporting" if archetype == "recurring_labor_service" else "primary"
    marketing_up_cap_ratio = 0.14 if archetype == "recurring_labor_service" else 0.30
    marketing_down_cap_ratio = 0.25
    marketing_demand_link = archetype != "recurring_labor_service"
    opex_flexibility = "moderate"
    other_opex_down_cap_ratio = 0.08
    other_opex_up_cap_ratio = 0.06

  if business_stage == "pre_revenue":
    marketing_up_cap_ratio *= 1.2
    marketing_down_cap_ratio *= 0.8
    if marketing_role != "constrained":
      marketing_demand_link = True
  if current_marketing <= 0 and marketing_role != "primary":
    marketing_up_cap_ratio = 0.0
    marketing_demand_link = False
  if current_other_opex <= 0:
    other_opex_down_cap_ratio = 0.0
    other_opex_up_cap_ratio = min(other_opex_up_cap_ratio, 0.03)

  growth_capable_archetypes = {
    "retail_store",
    "scalable_online",
    "subscription_model",
    "system_service",
    "space_service",
    "general_operating_business",
  }
  growth_demand_mode_enabled = bool(marketing_demand_link) and archetype in growth_capable_archetypes

  return {
    "commercial_archetype": archetype,
    "sales_modality": sales_modality,
    "capacity_driver": capacity_driver,
    "customer_type": customer_type,
    "business_stage": business_stage,
    "marketing_role": marketing_role,
    "marketing_demand_link": marketing_demand_link,
    "growth_demand_mode_enabled": growth_demand_mode_enabled,
    "marketing_up_cap_ratio": round(max(0.0, marketing_up_cap_ratio), 6),
    "marketing_down_cap_ratio": round(max(0.0, marketing_down_cap_ratio), 6),
    "opex_flexibility": opex_flexibility,
    "other_opex_down_cap_ratio": round(max(0.0, other_opex_down_cap_ratio), 6),
    "other_opex_up_cap_ratio": round(max(0.0, other_opex_up_cap_ratio), 6),
  }


def _derive_scenario_posture(candidate: Dict[str, Any]) -> Dict[str, str]:
  candidate = candidate if isinstance(candidate, dict) else {}
  lever_summary = candidate.get("lever_summary") if isinstance(candidate.get("lever_summary"), dict) else {}
  raw_moves = lever_summary.get("raw_family_moves") if isinstance(lever_summary, dict) else {}
  raw_moves = raw_moves if isinstance(raw_moves, dict) else {}
  meaningful_families = {
    str(item or "").strip()
    for item in (candidate.get("meaningful_families") or candidate.get("lever_families") or [])
    if str(item or "").strip()
  }
  baseline_units = max(
    0.0,
    _safe_float(candidate.get("baseline_required_units")),
    _safe_float(candidate.get("baseline_expected_units")),
  )
  scenario_units = max(
    0.0,
    _safe_float(candidate.get("scenario_required_units")),
    _safe_float(candidate.get("scenario_expected_units")),
  )
  baseline_revenue = max(0.0, _safe_float(candidate.get("baseline_revenue")))
  scenario_revenue = max(0.0, _safe_float(candidate.get("scenario_revenue")))
  unit_change_ratio = (
    ((scenario_units - baseline_units) / max(baseline_units, 1.0))
    if max(baseline_units, scenario_units) > 0
    else 0.0
  )
  revenue_change_ratio = (
    ((scenario_revenue - baseline_revenue) / max(baseline_revenue, 1.0))
    if max(baseline_revenue, scenario_revenue) > 0
    else 0.0
  )

  marketing_up = _safe_float(raw_moves.get("marketing_up"))
  marketing_down = _safe_float(raw_moves.get("marketing_down"))
  if marketing_up <= 0 and marketing_down <= 0 and "marketing" in meaningful_families:
    marketing_up = 0.08 if scenario_units >= baseline_units else 0.0
    marketing_down = 0.08 if scenario_units < baseline_units else 0.0
  payroll_up = _safe_float(raw_moves.get("payroll_up"))
  payroll_down = _safe_float(raw_moves.get("payroll_down"))
  if payroll_up <= 0 and payroll_down <= 0 and "payroll" in meaningful_families:
    payroll_up = 0.06
  hire_advance = _safe_float(raw_moves.get("hire_advance"))
  hire_delay = _safe_float(raw_moves.get("hire_delay"))
  if hire_advance <= 0 and hire_delay <= 0 and "hire_delay" in meaningful_families:
    hire_advance = 0.05
  util_up = _safe_float(raw_moves.get("util_up"))
  util_down = _safe_float(raw_moves.get("util_down"))
  if util_up <= 0 and util_down <= 0 and "utilization" in meaningful_families:
    util_up = 0.05
  cost_tighten_signal = (
    _safe_float(raw_moves.get("other_opex_down"))
    + _safe_float(raw_moves.get("cogs_down"))
    + payroll_down
  )
  cost_protect_signal = (
    _safe_float(raw_moves.get("other_opex_up"))
    + _safe_float(raw_moves.get("cogs_up"))
    + payroll_up
    + marketing_up
  )
  if cost_tighten_signal <= 0 and meaningful_families.intersection({"other_opex", "cogs"}):
    cost_tighten_signal = 0.08

  if unit_change_ratio >= 0.03 or revenue_change_ratio >= 0.03 or marketing_up > marketing_down + 0.02:
    demand_posture = "preserve"
  elif unit_change_ratio <= -0.03 or revenue_change_ratio <= -0.03 or marketing_down > marketing_up + 0.03:
    demand_posture = "reduce"
  else:
    demand_posture = "moderate"

  if (payroll_up + hire_advance) > (payroll_down + hire_delay) + 0.03:
    staffing_posture = "add_support"
  elif (payroll_down + hire_delay) > (payroll_up + hire_advance) + 0.03:
    staffing_posture = "delay"
  elif meaningful_families.intersection({"payroll", "hire_delay", "utilization"}):
    staffing_posture = "rebalance"
  else:
    staffing_posture = "hold"

  if cost_tighten_signal > cost_protect_signal + 0.04:
    cost_posture = "tighten"
  elif cost_protect_signal > cost_tighten_signal + 0.04:
    cost_posture = "protect"
  else:
    cost_posture = "moderate"

  return {
    "demand_posture": demand_posture,
    "staffing_posture": staffing_posture,
    "cost_posture": cost_posture,
  }


def _derive_structured_tradeoff(
  *,
  archetype: str,
  demand_posture: str,
  staffing_posture: str,
  cost_posture: str,
  meaningful_families: Sequence[str],
) -> str:
  families = {
    str(item or "").strip()
    for item in (meaningful_families or [])
    if str(item or "").strip()
  }
  if archetype == "growth":
    if staffing_posture == "add_support":
      return "preserves more Year-1 demand by adding support capacity behind the plan"
    if "marketing" in families:
      return "keeps more Year-1 demand in place and accepts support spend where it remains credible"
    return "leans toward preserving Year-1 volume without breaking delivery realism"
  if archetype == "efficiency":
    if cost_posture == "tighten":
      return "accepts a tighter cost posture and some revenue moderation to improve margin quality"
    return "leans into cleaner Year-1 economics instead of preserving every unit"
  if staffing_posture in {"add_support", "rebalance"}:
    return "rebalances staffing, workload, and throughput so the Year-1 plan is believable"
  if demand_posture == "reduce":
    return "moderates Year-1 demand to bring delivery and support back into line"
  return "balances workload, staffing, and throughput without leaning too hard on cost cuts or demand push"


def _archetype_consistency(candidate: Dict[str, Any]) -> Dict[str, Any]:
  candidate = candidate if isinstance(candidate, dict) else {}
  archetype = str(candidate.get("archetype") or "").strip()
  lever_summary = candidate.get("lever_summary") if isinstance(candidate.get("lever_summary"), dict) else {}
  dominant_family = str((lever_summary or {}).get("dominant_family") or "").strip()
  meaningful_families = {
    str(item or "").strip()
    for item in (candidate.get("meaningful_families") or candidate.get("lever_families") or [])
    if str(item or "").strip()
  }
  demand_posture = str(candidate.get("demand_posture") or "").strip()
  staffing_posture = str(candidate.get("staffing_posture") or "").strip()
  cost_posture = str(candidate.get("cost_posture") or "").strip()
  dominant_family_share = max(
    0.0,
    _safe_float(candidate.get("dominant_family_share"))
    or _safe_float((lever_summary or {}).get("dominant_family_share")),
  )
  coordination_issues = {
    str(item or "").strip()
    for item in ((candidate.get("coordination_issues") or []) or ((lever_summary or {}).get("coordination_issues") or []))
    if str(item or "").strip()
  }

  score = 0.0
  issues: List[str] = []
  if archetype == "growth":
    if demand_posture == "preserve":
      score += 2.5
    else:
      issues.append("growth_not_preserving_demand")
    if staffing_posture in {"add_support", "rebalance"}:
      score += 1.5
    if meaningful_families.intersection({"marketing", "utilization", "price"}):
      score += 1.0
    if cost_posture == "tighten" and not meaningful_families.intersection({"marketing", "utilization", "price"}):
      issues.append("growth_cost_story")
    if dominant_family in {"other_opex", "cogs"} and demand_posture != "preserve":
      issues.append("archetype_mismatch")
    if not meaningful_families.intersection({"marketing", "utilization", "price"}):
      issues.append("growth_missing_demand_lever")
    if staffing_posture not in {"add_support", "rebalance"}:
      issues.append("growth_missing_staffing_support")
  elif archetype == "efficiency":
    if cost_posture == "tighten":
      score += 2.5
    else:
      issues.append("efficiency_not_cost_led")
    if demand_posture in {"moderate", "reduce"}:
      score += 1.0
    if meaningful_families.intersection({"other_opex", "cogs", "payroll"}):
      score += 1.0
    if demand_posture == "preserve" and meaningful_families.intersection({"marketing", "utilization"}):
      issues.append("efficiency_growth_story")
    if dominant_family == "marketing":
      issues.append("archetype_mismatch")
    if not meaningful_families.intersection({"other_opex", "cogs", "payroll"}):
      issues.append("efficiency_missing_cost_lever")
  else:
    if staffing_posture in {"rebalance", "add_support"}:
      score += 1.8
    if demand_posture in {"moderate", "reduce"}:
      score += 1.0
    if cost_posture in {"moderate", "tighten"}:
      score += 0.8
    if meaningful_families.intersection({"utilization", "payroll", "hire_delay", "other_opex", "price"}):
      score += 1.0
    if meaningful_families.issubset({"marketing", "other_opex"}) and meaningful_families:
      issues.append("operations_absorber_story")
    if dominant_family == "marketing" and "marketing" in meaningful_families and staffing_posture != "add_support":
      issues.append("archetype_mismatch")
  if dominant_family_share > 0.72 and len(meaningful_families) < 2:
    issues.append("single_lever_dominance")
  if "demand_without_staffing" in coordination_issues:
    issues.append("demand_without_staffing")
  if "cost_without_structure" in coordination_issues:
    issues.append("cost_without_structure")
  if "utilization_without_support" in coordination_issues:
    issues.append("utilization_without_support")
  return {
    "archetype_consistency_score": round(max(0.0, score), 4),
    "archetype_consistency_issues": list(dict.fromkeys(issues)),
  }


def _role_update_map(candidate: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
  updates = candidate.get("exact_patches") if isinstance(candidate, dict) else {}
  updates = updates if isinstance(updates, dict) else {}
  role_updates = updates.get("people_role_updates") if isinstance(updates.get("people_role_updates"), list) else []
  result: Dict[str, Dict[str, Any]] = {}
  for item in role_updates:
    if not isinstance(item, dict):
      continue
    title = str(item.get("role_title") or "").strip()
    if title:
      result[title] = item
  return result


def _enrich_candidate_strategy(candidate: Dict[str, Any]) -> Dict[str, Any]:
  from .patches import _build_lever_summary

  candidate = dict(candidate or {})
  if not isinstance(candidate.get("lever_summary"), dict):
    candidate["lever_summary"] = _build_lever_summary(
      exact_patches=candidate.get("exact_patches") or {},
      family_raw_components=candidate.get("family_raw_components") or {},
    )
  if not candidate.get("meaningful_families"):
    merged_families = list(
      dict.fromkeys(
        [
          str(item or "").strip()
          for item in (
            list((candidate.get("lever_summary") or {}).get("meaningful_families") or [])
            + list(candidate.get("lever_families") or [])
          )
          if str(item or "").strip()
        ]
      )
    )
    candidate["meaningful_families"] = merged_families
  lever_count_floor = len(candidate.get("meaningful_families") or [])
  lever_count_current = int(max(0, _safe_int(candidate.get("meaningful_lever_count")) or 0))
  lever_count_summary = int(max(0, _safe_int((candidate.get("lever_summary") or {}).get("meaningful_lever_count")) or 0))
  candidate["meaningful_lever_count"] = max(lever_count_current, lever_count_summary, lever_count_floor)
  if candidate.get("coordination_score") is None:
    candidate["coordination_score"] = _safe_float((candidate.get("lever_summary") or {}).get("coordination_score"))
  if candidate.get("dominant_family_share") is None:
    candidate["dominant_family_share"] = _safe_float((candidate.get("lever_summary") or {}).get("dominant_family_share"))
  if candidate.get("aligned_pair_count") is None:
    candidate["aligned_pair_count"] = int(max(0, _safe_int((candidate.get("lever_summary") or {}).get("aligned_pair_count")) or 0))
  if candidate.get("coordination_issues") is None:
    candidate["coordination_issues"] = list((candidate.get("lever_summary") or {}).get("coordination_issues") or [])
  candidate.update(_derive_scenario_posture(candidate))
  if not str(candidate.get("dominant_tradeoff") or "").strip():
    candidate["dominant_tradeoff"] = _derive_structured_tradeoff(
      archetype=str(candidate.get("archetype") or "").strip(),
      demand_posture=str(candidate.get("demand_posture") or "").strip(),
      staffing_posture=str(candidate.get("staffing_posture") or "").strip(),
      cost_posture=str(candidate.get("cost_posture") or "").strip(),
      meaningful_families=candidate.get("meaningful_families") or [],
    )
  candidate.update(_archetype_consistency(candidate))
  return candidate


def _materially_distinct_candidate(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
  left_archetype = str(left.get("archetype") or "").strip()
  right_archetype = str(right.get("archetype") or "").strip()
  if left_archetype and right_archetype and left_archetype != right_archetype:
    return True
  for posture_key in ("demand_posture", "staffing_posture", "cost_posture"):
    left_posture = str(left.get(posture_key) or "").strip()
    right_posture = str(right.get(posture_key) or "").strip()
    if left_posture and right_posture and left_posture != right_posture:
      return True
  left_tradeoff = str(left.get("dominant_tradeoff") or "").strip()
  right_tradeoff = str(right.get("dominant_tradeoff") or "").strip()
  if left_tradeoff and right_tradeoff and left_tradeoff != right_tradeoff:
    return True
  left_families = tuple(str(item or "").strip() for item in (left.get("lever_families") or []) if str(item or "").strip())
  right_families = tuple(str(item or "").strip() for item in (right.get("lever_families") or []) if str(item or "").strip())
  if left_families and right_families and left_families != right_families:
    return True
  left_patch = left.get("exact_patches") if isinstance(left, dict) else {}
  right_patch = right.get("exact_patches") if isinstance(right, dict) else {}
  left_year1 = left_patch.get("financials_year1_patch") if isinstance(left_patch, dict) else {}
  right_year1 = right_patch.get("financials_year1_patch") if isinstance(right_patch, dict) else {}
  left_marketing = left_patch.get("marketing_model_patch") if isinstance(left_patch, dict) else {}
  right_marketing = right_patch.get("marketing_model_patch") if isinstance(right_patch, dict) else {}
  left_product_overrides = (left_year1 or {}).get("product_overrides") if isinstance(left_year1, dict) else {}
  right_product_overrides = (right_year1 or {}).get("product_overrides") if isinstance(right_year1, dict) else {}
  if isinstance(left_product_overrides, dict) or isinstance(right_product_overrides, dict):
    left_product_overrides = left_product_overrides if isinstance(left_product_overrides, dict) else {}
    right_product_overrides = right_product_overrides if isinstance(right_product_overrides, dict) else {}
    if set(left_product_overrides.keys()) != set(right_product_overrides.keys()):
      return True
    for product_name in left_product_overrides.keys():
      left_override = left_product_overrides.get(product_name) or {}
      right_override = right_product_overrides.get(product_name) or {}
      left_price = _safe_float((left_override or {}).get("unit_price"))
      right_price = _safe_float((right_override or {}).get("unit_price"))
      if max(left_price, right_price) > 0 and abs(left_price - right_price) >= max(0.25, 0.01 * max(left_price, right_price)):
        return True
      left_avg_units = _safe_float((left_override or {}).get("avg_units_per_period_year1"))
      right_avg_units = _safe_float((right_override or {}).get("avg_units_per_period_year1"))
      if max(left_avg_units, right_avg_units) > 0 and abs(left_avg_units - right_avg_units) >= max(1.0, 0.02 * max(left_avg_units, right_avg_units)):
        return True
      left_prod_util = _normalize_ratio((left_override or {}).get("utilization_rate"))
      right_prod_util = _normalize_ratio((right_override or {}).get("utilization_rate"))
      if left_prod_util is not None and right_prod_util is not None and abs(left_prod_util - right_prod_util) >= 0.01:
        return True
  left_util = _normalize_ratio((left_year1 or {}).get("utilization_rate"))
  right_util = _normalize_ratio((right_year1 or {}).get("utilization_rate"))
  if left_util is not None and right_util is not None and abs(left_util - right_util) >= 0.01:
    return True
  left_units = _safe_float((left_marketing or {}).get("expected_units_year1"))
  right_units = _safe_float((right_marketing or {}).get("expected_units_year1"))
  if max(left_units, right_units) > 0 and abs(left_units - right_units) >= max(1.0, 0.02 * max(left_units, right_units)):
    return True
  left_roles = _role_update_map(left)
  right_roles = _role_update_map(right)
  if set(left_roles.keys()) != set(right_roles.keys()):
    return True
  for role_title in left_roles.keys():
    left_item = left_roles.get(role_title) or {}
    right_item = right_roles.get(role_title) or {}
    if abs((_safe_int(left_item.get("months_until_hire")) or 0) - (_safe_int(right_item.get("months_until_hire")) or 0)) >= 1:
      return True
    left_wage = _safe_float(left_item.get("annual_wage"))
    right_wage = _safe_float(right_item.get("annual_wage"))
    if max(left_wage, right_wage) > 0 and abs(left_wage - right_wage) >= max(250.0, 0.01 * max(left_wage, right_wage)):
      return True
  return False


def _scenario_marketing_ratio(candidate: Dict[str, Any]) -> Optional[float]:
  summary = candidate.get("summary") if isinstance(candidate, dict) else {}
  summary = summary if isinstance(summary, dict) else {}
  revenue = max(0.0, _safe_float(summary.get("revenue")))
  marketing = max(0.0, _safe_float(summary.get("marketing")))
  if revenue <= 0:
    return None
  return marketing / revenue


def _candidate_target_margin_path(candidate: Dict[str, Any], *, state_model: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
  controller_profile = (
    ((candidate.get("contract_diagnostics") or {}) if isinstance(candidate.get("contract_diagnostics"), dict) else {}).get("controller_profile")
  )
  controller_profile = controller_profile if isinstance(controller_profile, dict) else {}
  path = controller_profile.get("target_margin_path") if isinstance(controller_profile.get("target_margin_path"), dict) else {}
  if not path and isinstance(state_model, dict):
    strategy_layer = state_model.get("strategy_layer") if isinstance(state_model.get("strategy_layer"), dict) else {}
    diagnosis = (strategy_layer or {}).get("diagnosis") if isinstance((strategy_layer or {}).get("diagnosis"), dict) else {}
    if isinstance(diagnosis, dict):
      path = diagnosis.get("target_margin_path") if isinstance(diagnosis.get("target_margin_path"), dict) else {}
  return dict(path or {}) if isinstance(path, dict) else {}


def _candidate_target_path_assessment(
  candidate: Dict[str, Any],
  *,
  state_model: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  path = _candidate_target_margin_path(candidate, state_model=state_model)
  years = candidate.get("forecast_years") if isinstance(candidate.get("forecast_years"), list) else []
  year_margins: Dict[int, Optional[float]] = {}
  for item in years:
    if not isinstance(item, dict):
      continue
    year_index = _safe_int(item.get("year_index"))
    revenue = max(0.0, _safe_float(item.get("revenue")))
    ebitda = _safe_float(item.get("ebitda"))
    year_margins[year_index] = (ebitda / revenue) if revenue > 0 else None
  misses: List[Dict[str, Any]] = []
  tolerance = 0.03
  for year_index in (1, 2, 3):
    margin = year_margins.get(year_index)
    if margin is None:
      continue
    min_key = f"year{year_index}_min"
    max_key = f"year{year_index}_max"
    target_min = _safe_float(path.get(min_key))
    target_max = _safe_float(path.get(max_key))
    if target_min is not None and margin < (target_min - tolerance):
      misses.append({"year_index": year_index, "kind": "below_min", "margin": margin, "target": target_min})
    if target_max is not None and margin > (target_max + tolerance):
      misses.append({"year_index": year_index, "kind": "above_max", "margin": margin, "target": target_max})
  year1_margin = year_margins.get(1)
  year2_margin = year_margins.get(2)
  year3_margin = year_margins.get(3)
  year5_margin = year_margins.get(5)
  all_negative = all(
    year_margins.get(idx) is not None and _safe_float(year_margins.get(idx)) < 0.0
    for idx in (1, 2, 3, 4, 5)
    if idx in year_margins
  ) and len(year_margins) >= 5
  degrading = False
  if year1_margin is not None and year2_margin is not None and year3_margin is not None:
    if year2_margin < (year1_margin - 0.01) or year3_margin < (year2_margin - 0.01):
      degrading = True
  if year3_margin is not None and year5_margin is not None and year5_margin < (year3_margin - 0.02):
    degrading = True
  return {
    "target_margin_path": _clone(path),
    "year_margins": {str(key): value for key, value in year_margins.items()},
    "misses": misses,
    "all_negative": all_negative,
    "degrading": degrading,
  }


def _presentation_issues(
  candidate: Dict[str, Any],
  *,
  state_model: Optional[Dict[str, Any]] = None,
  selected_candidates: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[str]:
  issues: List[str] = []
  candidate = _enrich_candidate_strategy(candidate if isinstance(candidate, dict) else {})
  state_model = state_model if isinstance(state_model, dict) else {}
  selected_candidates = [item for item in (selected_candidates or []) if isinstance(item, dict)]

  if _safe_float(candidate.get("remaining_blocking_count")) > 0:
    issues.append("remaining_blockers")

  if any(not _materially_distinct_candidate(candidate, existing) for existing in selected_candidates):
    issues.append("near_duplicate")

  exact_patches = candidate.get("exact_patches") if isinstance(candidate, dict) else {}
  exact_patches = exact_patches if isinstance(exact_patches, dict) else {}
  year1_patch = exact_patches.get("financials_year1_patch") if isinstance(exact_patches, dict) else {}
  year1_patch = year1_patch if isinstance(year1_patch, dict) else {}
  product_overrides = year1_patch.get("product_overrides") if isinstance(year1_patch, dict) else {}
  product_overrides = product_overrides if isinstance(product_overrides, dict) else {}
  if product_overrides and (year1_patch.get("unit_price") is not None or year1_patch.get("utilization_rate") is not None):
    issues.append("child_parent_contradiction")

  fixed_facts = state_model.get("fixed_facts") if isinstance(state_model, dict) else {}
  fixed_facts = fixed_facts if isinstance(fixed_facts, dict) else {}
  sales_modality = str(fixed_facts.get("sales_modality") or "").strip().lower()
  capacity_driver = str(fixed_facts.get("capacity_driver") or "").strip().lower()
  commercial_context = fixed_facts.get("commercial_context") if isinstance(fixed_facts.get("commercial_context"), dict) else {}
  marketing_role = str(commercial_context.get("marketing_role") or "").strip().lower()
  space_or_system_scaler = capacity_driver in {"space", "system"}
  constraint_profile = state_model.get("constraint_profile") if isinstance(state_model, dict) else {}
  constraint_profile = constraint_profile if isinstance(constraint_profile, dict) else {}
  util_envelope = (constraint_profile.get("utilization_envelope") if isinstance(constraint_profile, dict) else {}) or {}
  util_floor = _normalize_ratio((util_envelope or {}).get("min"))
  summary = candidate.get("summary") if isinstance(candidate, dict) else {}
  summary = summary if isinstance(summary, dict) else {}
  scenario_util = _normalize_ratio(
    ((year1_patch or {}).get("utilization_rate"))
    or (summary.get("utilization"))
    or (((candidate.get("forecast_engine_state") or {}) if isinstance(candidate.get("forecast_engine_state"), dict) else {}).get("starting_state") or {}).get("utilization")
  )
  presentation_util_floor = util_floor
  if capacity_driver == "labor" and sales_modality in {"local_service", "project_based"}:
    presentation_util_floor = max(presentation_util_floor or 0.0, 0.45)
  if scenario_util is not None and presentation_util_floor is not None and scenario_util < presentation_util_floor - 0.01:
    issues.append("weak_utilization_story")

  marketing_ratio = _scenario_marketing_ratio(candidate)
  archetype = str(candidate.get("archetype") or "").strip()
  lever_families = {
    str(family or "").strip()
    for family in (candidate.get("meaningful_families") or candidate.get("lever_families") or [])
    if str(family or "").strip()
  }
  if marketing_ratio is not None:
    bizarre_marketing_floor = 0.22
    if marketing_role == "constrained":
      bizarre_marketing_floor = 0.12
    elif marketing_role == "supporting":
      bizarre_marketing_floor = 0.18
    elif marketing_role == "primary":
      bizarre_marketing_floor = 0.28
    if archetype != "growth" and marketing_ratio > bizarre_marketing_floor:
      issues.append("bizarre_marketing")
    elif archetype == "growth" and marketing_ratio > max(0.32, bizarre_marketing_floor + 0.08):
      issues.append("bizarre_marketing")
  raw_family_moves = (((candidate.get("lever_summary") or {}) if isinstance(candidate.get("lever_summary"), dict) else {}).get("raw_family_moves", {}) or {})
  marketing_move = max(0.0, _safe_float(raw_family_moves.get("marketing")))
  staffing_move = max(0.0, _safe_float(raw_family_moves.get("payroll"))) + max(0.0, _safe_float(raw_family_moves.get("hire_delay")))
  retail_efficiency_reset = (
    space_or_system_scaler
    and sales_modality in {"retail", "online"}
    and archetype == "efficiency"
    and lever_families.intersection({"price", "other_opex", "cogs"})
    and staffing_move <= 0.02
  )
  if (
    marketing_role == "constrained"
    and "marketing" in lever_families
    and archetype != "growth"
    and marketing_ratio is not None
    and marketing_ratio > bizarre_marketing_floor
    and staffing_move <= 0.02
    and len(lever_families) <= 2
  ):
    issues.append("marketing_absorber_story")
  if lever_families and lever_families.issubset({"marketing", "other_opex"}) and archetype != "growth":
    issues.append("commercial_absorber_story")
  if archetype == "efficiency" and lever_families and "other_opex" in lever_families and lever_families.issubset({"other_opex", "marketing"}):
    issues.append("commercial_absorber_story")
  if (
    max(0.0, _safe_float(candidate.get("dominant_family_share"))) > 0.72
    and _safe_float(candidate.get("meaningful_lever_count")) < 2
    and _safe_float(candidate.get("coordination_score")) < 1.8
  ):
    issues.append("single_lever_dominance")
  for issue in (candidate.get("coordination_issues") or []):
    issue = str(issue or "").strip()
    if issue == "demand_without_staffing" and retail_efficiency_reset:
      continue
    if issue in {"demand_without_staffing", "cost_without_structure", "utilization_without_support"}:
      issues.append(issue)
  for issue in (candidate.get("archetype_consistency_issues") or []):
    issue = str(issue or "").strip()
    if issue == "efficiency_growth_story" and retail_efficiency_reset:
      continue
    if issue in {
      "archetype_mismatch",
      "growth_cost_story",
      "efficiency_growth_story",
      "operations_absorber_story",
      "single_lever_dominance",
    }:
      issues.append(issue)
  identity_blockers = {
    item for item in issues
    if item not in {"degrading_five_year_path", "all_negative_five_year_path", "target_path_miss"}
  }
  if _safe_float(candidate.get("archetype_consistency_score")) < 1.5 and identity_blockers:
    issues.append("weak_archetype_identity")

  label = str(candidate.get("label") or "").strip()
  rationale = str(candidate.get("rationale") or "").strip().lower()
  dominant_tradeoff = str(candidate.get("dominant_tradeoff") or "").strip().lower()
  if not label or ":" not in label:
    issues.append("weak_label")
  if dominant_tradeoff and dominant_tradeoff not in rationale:
    issues.append("weak_rationale")

  target_path = _candidate_target_path_assessment(candidate, state_model=state_model)
  candidate["target_path_assessment"] = _clone(target_path)
  if target_path.get("all_negative"):
    issues.append("all_negative_five_year_path")
  if target_path.get("degrading"):
    issues.append("degrading_five_year_path")
  misses = target_path.get("misses") if isinstance(target_path.get("misses"), list) else []
  if misses:
    issues.append("target_path_miss")

  return list(dict.fromkeys(issues))
