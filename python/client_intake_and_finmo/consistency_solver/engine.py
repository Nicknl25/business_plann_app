from __future__ import annotations

from itertools import product
from typing import Any, Dict, List, Optional, Sequence, Tuple

from consistency_financials import build_consistency_financial_summary  # type: ignore
from constraint_engine import build_constraint_engine_bundle  # type: ignore
from forecast_engine import build_forecast_engine_bundle  # type: ignore

from .common import (
  BLOCKING_CODES,
  _archetype_consistency,
  _clone,
  _derive_commercial_archetype,
  _derive_scenario_posture,
  _enrich_candidate_strategy,
  _normalize_ratio,
  _presentation_issues,
  _safe_float,
  _safe_int,
  _unique_strings,
)
from .patches import (
  _apply_exact_patches,
  _build_lever_summary,
  _exact_patches_from_solution,
  _label_and_rationale_from_patches,
)


MAX_SCENARIOS = 3


def _solver_required(*args: Any, **kwargs: Any) -> bool:
  del args, kwargs
  return True


def _build_client_scenario_output(candidate: Dict[str, Any], *, scenario_id: str) -> Dict[str, Any]:
  archetype = str(candidate.get("archetype") or "operations").strip().lower()
  if archetype == "growth":
    scenario_name = "Growth Strategy"
  elif archetype == "efficiency":
    scenario_name = "Efficiency Strategy"
  else:
    scenario_name = "Operational Strategy"
  posture = {
    "demand": str(candidate.get("demand_posture") or "moderate"),
    "staffing": str(candidate.get("staffing_posture") or "measured"),
    "cost": str(candidate.get("cost_posture") or "moderate"),
  }
  summary = (
    f"This path keeps demand {posture['demand']} while staffing stays {posture['staffing']} "
    f"and cost posture remains {posture['cost']}."
  )
  years = [item for item in (candidate.get("forecast_years") or []) if isinstance(item, dict)]
  year5 = years[-1] if years else {}
  return {
    "scenario_id": str(scenario_id or "").strip(),
    "scenario_name": scenario_name,
    "summary": summary,
    "key_metrics": {
      "year1_revenue": _safe_float((((candidate.get("summary") or {}) if isinstance(candidate.get("summary"), dict) else {}).get("revenue"))),
      "year1_ebitda": _safe_float((((candidate.get("summary") or {}) if isinstance(candidate.get("summary"), dict) else {}).get("ebitda"))),
      "year5_revenue": _safe_float(year5.get("revenue")),
      "year5_ebitda": _safe_float(year5.get("ebitda")),
    },
    "tradeoff": (
      f"The upside is a more believable {scenario_name.lower()} with clearer operating logic. "
      f"The downside is that it requires tighter choices on pricing, staffing, or cost posture."
    ),
    "confidence": {
      "forecast_confidence": _safe_float((((candidate.get("forecast_engine_state") or {}) if isinstance(candidate.get("forecast_engine_state"), dict) else {}).get("forecast_confidence"))),
      "convergence_strength": _safe_float((((candidate.get("forecast_engine_state") or {}) if isinstance(candidate.get("forecast_engine_state"), dict) else {}).get("convergence_strength"))),
    },
  }


def _scenario_year_margin(item: Dict[str, Any]) -> Optional[float]:
  revenue = max(0.0, _safe_float(item.get("revenue")))
  if revenue <= 0:
    return None
  return _safe_float(item.get("ebitda")) / revenue


def _scenario_violations(
  *,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  constraint_engine_state: Optional[Dict[str, Any]],
  direct_inputs: Optional[Dict[str, Any]] = None,
) -> List[str]:
  summary = build_consistency_financial_summary(
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
  )
  state = constraint_engine_state if isinstance(constraint_engine_state, dict) else {}
  direct = direct_inputs if isinstance(direct_inputs, dict) else {}
  revenue = max(1.0, _safe_float(summary.get("revenue")))
  ebitda_margin = _safe_float(summary.get("ebitda")) / revenue
  gross_margin = _safe_float(summary.get("gross_profit")) / revenue
  payroll_ratio = _safe_float(summary.get("payroll")) / revenue
  total_opex_ratio = _safe_float(summary.get("other_opex")) / revenue
  marketing_ratio = _safe_float(summary.get("marketing")) / revenue
  util = _normalize_ratio(financials_year1_json.get("utilization_rate"))
  violations: List[str] = []
  current_metrics = state.get("current_metrics") if isinstance(state.get("current_metrics"), dict) else {}

  def _band_min(name: str) -> Optional[float]:
    band = state.get(name) if isinstance(state.get(name), dict) else {}
    value = _safe_float((band or {}).get("min"))
    return value if value > 0 or value == 0 else None

  def _band_max(name: str) -> Optional[float]:
    band = state.get(name) if isinstance(state.get(name), dict) else {}
    value = _safe_float((band or {}).get("max"))
    return value if value > 0 or value == 0 else None

  gm_min = _band_min("gross_margin_band")
  gm_max = _band_max("gross_margin_band")
  if gm_min is not None and gross_margin < gm_min - 0.01:
    violations.append("gross_margin_too_low")
  if gm_max is not None and gross_margin > gm_max + 0.02:
    violations.append("gross_margin_too_high")
  em_min = _band_min("ebitda_margin_band")
  em_max = _band_max("ebitda_margin_band")
  if em_min is not None and ebitda_margin < em_min - 0.02:
    violations.append("ebitda_margin_too_low")
  if em_max is not None and ebitda_margin > em_max + 0.02:
    violations.append("ebitda_margin_too_high")
  pay_min = _band_min("payroll_intensity_band")
  pay_max = _band_max("payroll_intensity_band")
  structural_floor = max(
    _safe_float(current_metrics.get("structural_payroll_floor")),
    _safe_float((direct.get("structural_payroll_floor"))),
  )
  people_floor = max(
    0.0,
    _safe_float(current_metrics.get("people_payroll_floor")),
    _safe_float(direct.get("target_payroll_min_total")),
  )
  payroll_support_basis = str(current_metrics.get("payroll_support_basis") or "").strip().lower()
  role_activation_ratio = max(0.0, _safe_float(current_metrics.get("role_activation_ratio")))
  # When the modified scenario keeps only fixed current staff active and explicitly reduces/defer
  # current compensation, use the fixed-people floor rather than the old workload-payroll heuristic.
  if payroll_support_basis == "payroll" and role_activation_ratio <= 0.01 and people_floor > 0:
    structural_floor = people_floor
  payroll_total = _safe_float(summary.get("payroll"))
  if pay_min is not None and (payroll_ratio < pay_min - 0.015 or (structural_floor > 0 and payroll_total + 1.0 < structural_floor)):
    violations.append("payroll_too_light")
  if pay_max is not None and payroll_ratio > pay_max + 0.02:
    violations.append("payroll_too_heavy")
  util_min = _band_min("utilization_range")
  util_max = _band_max("utilization_range")
  if util is not None and util_min is not None and util < util_min - 0.02:
    violations.append("utilization_too_low")
  if util is not None and util_max is not None and util > util_max + 0.02:
    violations.append("utilization_too_high")
  opex_min = _band_min("opex_intensity_band")
  opex_max = _band_max("opex_intensity_band")
  if opex_min is not None and total_opex_ratio < opex_min - 0.02:
    violations.append("opex_too_light")
  if opex_max is not None and total_opex_ratio > opex_max + 0.02:
    violations.append("opex_too_heavy")
  marketing_min = _band_min("marketing_intensity_band")
  marketing_max = _band_max("marketing_intensity_band")
  if marketing_min is not None and marketing_ratio < marketing_min - 0.02:
    violations.append("marketing_too_low")
  if marketing_max is not None and marketing_ratio > marketing_max + 0.02:
    violations.append("marketing_too_high")
  return _unique_strings(violations)


def _build_modified_state(
  *,
  baseline_state: Dict[str, Any],
  exact_patches: Dict[str, Any],
) -> Dict[str, Any]:
  next_ops, next_people, next_financials, next_year1, next_marketing = _apply_exact_patches(
    ops_json=_clone((baseline_state.get("ops_json") or {}) if isinstance(baseline_state.get("ops_json"), dict) else {}),
    people_json=_clone((baseline_state.get("people_json") or {}) if isinstance(baseline_state.get("people_json"), dict) else {}),
    financials_json=_clone((baseline_state.get("financials_json") or {}) if isinstance(baseline_state.get("financials_json"), dict) else {}),
    financials_year1_json=_clone((baseline_state.get("financials_year1_json") or {}) if isinstance(baseline_state.get("financials_year1_json"), dict) else {}),
    marketing_model_json=_clone((baseline_state.get("marketing_model_json") or {}) if isinstance(baseline_state.get("marketing_model_json"), dict) else {}),
    exact_patches=exact_patches,
  )
  return {
    "ops_json": next_ops,
    "target_market_json": _clone((baseline_state.get("target_market_json") or {}) if isinstance(baseline_state.get("target_market_json"), dict) else {}),
    "people_json": next_people,
    "financials_json": next_financials,
    "financials_year1_json": next_year1,
    "fulfillment_json": _clone((baseline_state.get("fulfillment_json") or {}) if isinstance(baseline_state.get("fulfillment_json"), dict) else {}),
    "marketing_model_json": next_marketing,
  }


def _build_modified_constraint_bundle(
  *,
  modified_state: Dict[str, Any],
) -> Dict[str, Any]:
  try:
    bundle = build_constraint_engine_bundle(
      conn=None,
      shared_context={},
      operating_model_json=(modified_state.get("ops_json") or {}) if isinstance(modified_state.get("ops_json"), dict) else {},
      target_market_json=(modified_state.get("target_market_json") or {}) if isinstance(modified_state.get("target_market_json"), dict) else {},
      people_json=(modified_state.get("people_json") or {}) if isinstance(modified_state.get("people_json"), dict) else {},
      financials_json=(modified_state.get("financials_json") or {}) if isinstance(modified_state.get("financials_json"), dict) else {},
      financials_year1_json=(modified_state.get("financials_year1_json") or {}) if isinstance(modified_state.get("financials_year1_json"), dict) else {},
      marketing_model_json=(modified_state.get("marketing_model_json") or {}) if isinstance(modified_state.get("marketing_model_json"), dict) else {},
      fulfillment_json=(modified_state.get("fulfillment_json") or {}) if isinstance(modified_state.get("fulfillment_json"), dict) else {},
    )
  except Exception:
    bundle = {}
  return bundle if isinstance(bundle, dict) else {}


def _build_scenario_forecast_bundle(
  *,
  baseline_state: Dict[str, Any],
  exact_patches: Dict[str, Any],
  normalized_traits: Optional[Dict[str, Any]],
  benchmark_payload: Optional[Dict[str, Any]],
  scenario_strategy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  modified_state = _build_modified_state(
    baseline_state=baseline_state,
    exact_patches=exact_patches,
  )
  constraint_bundle = _build_modified_constraint_bundle(
    modified_state=modified_state,
  )
  forecast_bundle = build_forecast_engine_bundle(
    operating_model_json=modified_state.get("ops_json"),
    target_market_json=modified_state.get("target_market_json"),
    people_json=modified_state.get("people_json"),
    financials_json=modified_state.get("financials_json"),
    financials_year1_json=modified_state.get("financials_year1_json"),
    marketing_model_json=modified_state.get("marketing_model_json"),
    normalized_traits=((constraint_bundle.get("normalized_traits") or {}) if isinstance((constraint_bundle.get("normalized_traits") or {}), dict) else (normalized_traits or {})),
    benchmark_payload=((constraint_bundle.get("benchmark_payload") or {}) if isinstance((constraint_bundle.get("benchmark_payload") or {}), dict) else (benchmark_payload or {})),
    constraint_engine_state=((constraint_bundle.get("constraint_engine_state") or {}) if isinstance((constraint_bundle.get("constraint_engine_state") or {}), dict) else {}),
    scenario_strategy=scenario_strategy or {},
  )
  forecast_bundle["modified_state"] = modified_state
  forecast_bundle["constraint_bundle"] = constraint_bundle
  forecast_state = (forecast_bundle.get("forecast_engine_state") or {}) if isinstance(forecast_bundle.get("forecast_engine_state"), dict) else {}
  forecast_years = [item for item in (forecast_bundle.get("forecast_years") or []) if isinstance(item, dict)]
  last_quarter = ((forecast_state.get("last_quarter_summary") or {}) if isinstance(forecast_state.get("last_quarter_summary"), dict) else {})
  forecast_bundle["forecast_summary"] = {
    "status": str(forecast_state.get("status") or "").strip(),
    "year1_ebitda": _safe_float((forecast_years[0] if len(forecast_years) >= 1 else {}).get("ebitda")),
    "year3_ebitda": _safe_float((forecast_years[2] if len(forecast_years) >= 3 else {}).get("ebitda")),
    "year5_exit_ebitda": _safe_float((forecast_years[4] if len(forecast_years) >= 5 else {}).get("ebitda")),
    "last_quarter_ebitda": _safe_float(last_quarter.get("ebitda")),
  }
  return forecast_bundle


def _target_path_assessment(
  *,
  forecast_years: Sequence[Dict[str, Any]],
  target_margin_path: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  path = target_margin_path if isinstance(target_margin_path, dict) else {}
  assessment = {
    "year1_margin": None,
    "year2_margin": None,
    "year3_margin": None,
    "miss_years": [],
  }
  for idx, year in enumerate(list(forecast_years)[:3], start=1):
    margin = _scenario_year_margin(year) if isinstance(year, dict) else None
    assessment[f"year{idx}_margin"] = margin
    lower = path.get(f"year{idx}_min")
    upper = path.get(f"year{idx}_max")
    if margin is None:
      continue
    if lower is not None and margin < (_safe_float(lower) - 0.02):
      assessment["miss_years"].append(idx)
      continue
    if upper is not None and margin > (_safe_float(upper) + 0.03):
      assessment["miss_years"].append(idx)
  assessment["target_path_miss"] = bool(assessment["miss_years"])
  return assessment


def _build_candidate(
  *,
  profile: Dict[str, Any],
  solution: Dict[str, Any],
  contract_bundle: Dict[str, Any],
  state_model: Dict[str, Any],
  scenario_index: int,
) -> Dict[str, Any]:
  baseline_state = (state_model.get("baseline_state") or {}) if isinstance(state_model.get("baseline_state"), dict) else {}
  exact_patches = _exact_patches_from_solution(
    solution=solution,
    direct_inputs=contract_bundle.get("direct_inputs") or {},
    ops_json=(baseline_state.get("ops_json") or {}) if isinstance(baseline_state.get("ops_json"), dict) else {},
  )
  marketing_patch = exact_patches.get("marketing_model_patch") if isinstance(exact_patches.get("marketing_model_patch"), dict) else None
  baseline_marketing = (baseline_state.get("marketing_model_json") or {}) if isinstance(baseline_state.get("marketing_model_json"), dict) else {}
  baseline_expected_units = _safe_float(baseline_marketing.get("expected_units_year1"))
  allowed_levers = set(profile.get("allowed_levers") or [])
  if (
    marketing_patch is not None
    and baseline_expected_units > 0
    and "marketing_up" not in allowed_levers
    and _safe_float(marketing_patch.get("expected_units_year1")) > baseline_expected_units
  ):
    marketing_patch["expected_units_year1"] = round(baseline_expected_units, 2)
  lever_summary = _build_lever_summary(
    exact_patches=exact_patches,
    family_raw_components=solution.get("family_raw_components"),
  )
  label, rationale, families = _label_and_rationale_from_patches(
    exact_patches=exact_patches,
    archetype=str(profile.get("archetype") or "operations"),
    archetype_display=str(profile.get("archetype_display") or "Operational balance"),
    dominant_tradeoff=str(profile.get("dominant_tradeoff") or ""),
  )
  forecast_strategy = {
    "strategy_id": str(profile.get("strategy_id") or "").strip(),
    "strategy_name": str(profile.get("strategy_name") or "").strip(),
    "archetype": str(profile.get("archetype") or "operations").strip(),
    "demand_posture": str(profile.get("demand_posture") or "").strip(),
    "staffing_posture": str(profile.get("staffing_posture") or "").strip(),
    "cost_posture": str(profile.get("cost_posture") or "").strip(),
    "forecast_orchestration": _clone(profile.get("forecast_orchestration") or {}),
  }
  preview_state = _build_modified_state(
    baseline_state=baseline_state,
    exact_patches=exact_patches,
  )
  forecast_bundle = _build_scenario_forecast_bundle(
    baseline_state=baseline_state,
    exact_patches=exact_patches,
    normalized_traits=state_model.get("normalized_traits") if isinstance(state_model.get("normalized_traits"), dict) else {},
    benchmark_payload=state_model.get("benchmark_payload") if isinstance(state_model.get("benchmark_payload"), dict) else {},
    scenario_strategy=forecast_strategy,
  )
  scenario_constraint_state = (
    ((forecast_bundle.get("constraint_bundle") or {}).get("constraint_engine_state") or {})
    if isinstance((forecast_bundle.get("constraint_bundle") or {}).get("constraint_engine_state"), dict)
    else {}
  )
  remaining_violations = _scenario_violations(
    financials_json=preview_state.get("financials_json") or {},
    financials_year1_json=preview_state.get("financials_year1_json") or {},
    constraint_engine_state=scenario_constraint_state,
    direct_inputs=contract_bundle.get("direct_inputs") or {},
  )
  forecast_state = (forecast_bundle.get("forecast_engine_state") or {}) if isinstance(forecast_bundle.get("forecast_engine_state"), dict) else {}
  if remaining_violations:
    forecast_state["remaining_violations"] = list(remaining_violations)
  forecast_bundle["forecast_engine_state"] = forecast_state
  forecast_years = [item for item in (forecast_bundle.get("forecast_years") or []) if isinstance(item, dict)]
  summary = build_consistency_financial_summary(
    financials_json=(forecast_bundle.get("modified_state") or {}).get("financials_json") if isinstance(forecast_bundle.get("modified_state"), dict) else {},
    financials_year1_json=(forecast_bundle.get("modified_state") or {}).get("financials_year1_json") if isinstance(forecast_bundle.get("modified_state"), dict) else {},
  )
  candidate: Dict[str, Any] = {
    "scenario_id": str(scenario_index),
    "strategy_id": str(profile.get("strategy_id") or "").strip(),
    "strategy_name": str(profile.get("strategy_name") or "").strip(),
    "solution_profile_id": str(profile.get("profile_id") or profile.get("strategy_id") or "").strip(),
    "archetype": str(profile.get("archetype") or _derive_commercial_archetype(fixed_facts=(state_model.get("fixed_facts") or {}), lever_families=families)).strip(),
    "archetype_display": str(profile.get("archetype_display") or "Operational balance").strip(),
    "dominant_tradeoff": str(profile.get("dominant_tradeoff") or "").strip(),
    "allowed_levers": _clone(profile.get("allowed_levers") or []),
    "relationship_rules": _clone(profile.get("relationship_rules") or []),
    "lever_families": families,
    "label": label,
    "rationale": rationale,
    "summary": summary,
    "exact_patches": exact_patches,
    "modified_state": _clone(forecast_bundle.get("modified_state") or {}),
    "forecast_orchestration": _clone((((forecast_bundle.get("forecast_engine_state") or {}) if isinstance(forecast_bundle.get("forecast_engine_state"), dict) else {}).get("forecast_orchestration") or {})),
    "scenario_strategy": _clone((((forecast_bundle.get("forecast_engine_state") or {}) if isinstance(forecast_bundle.get("forecast_engine_state"), dict) else {}).get("scenario_strategy") or {})),
    "forecast_quarters": _clone(forecast_bundle.get("forecast_quarters") or []),
    "forecast_years": _clone(forecast_years),
    "forecast_engine_state": _clone(forecast_bundle.get("forecast_engine_state") or {}),
    "forecast_summary": _clone(forecast_bundle.get("forecast_summary") or {}),
    "remaining_violations": remaining_violations,
    "remaining_blocking_count": len([code for code in remaining_violations if code in BLOCKING_CODES]),
    "remaining_blocking_violations": [code for code in remaining_violations if code in BLOCKING_CODES],
    "remaining_violation_count": len(remaining_violations),
    "contract_diagnostics": _clone(contract_bundle.get("diagnostics") or {}),
    "lever_summary": lever_summary,
    "ebitda": _safe_float(summary.get("ebitda")),
    "realism_distance": float(len(remaining_violations)) * 0.02,
    "target_distance": abs(_safe_float(summary.get("ebitda")) - (_safe_float(contract_bundle.get("target_ebitda_min")) if contract_bundle.get("target_ebitda_min") is not None else _safe_float(summary.get("ebitda")))) / max(1.0, abs(_safe_float(summary.get("revenue")))),
    "distortion_total": sum(max(0.0, _safe_float(value)) for value in ((solution.get("family_raw_components") or {}) if isinstance(solution.get("family_raw_components"), dict) else {}).values()),
    "disruption_score": sum(max(0.0, _safe_float(value)) for value in ((solution.get("family_raw_components") or {}) if isinstance(solution.get("family_raw_components"), dict) else {}).values()),
  }
  candidate.update(_derive_scenario_posture(candidate))
  candidate.update(_archetype_consistency(candidate))
  candidate["target_path_assessment"] = _target_path_assessment(
    forecast_years=forecast_years,
    target_margin_path=(((state_model.get("strategy_layer") or {}).get("diagnosis") or {}) if isinstance((state_model.get("strategy_layer") or {}).get("diagnosis"), dict) else {}).get("target_margin_path"),
  )
  candidate["presentation_issues"] = _presentation_issues(candidate, state_model=state_model)
  candidate["meaningful_lever_count"] = _safe_int((lever_summary or {}).get("meaningful_lever_count"))
  candidate["coordination_score"] = _safe_float((lever_summary or {}).get("coordination_score"))
  candidate["client_output"] = _build_client_scenario_output(candidate, scenario_id=str(scenario_index))
  return candidate


def _select_materially_distinct_scenarios(candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
  ranked = sorted(
    [item for item in candidates if isinstance(item, dict)],
    key=lambda item: (
      _safe_int(item.get("remaining_blocking_count")),
      _safe_int(item.get("remaining_violation_count")),
      len(item.get("presentation_issues") or []),
      _safe_float(item.get("realism_distance")),
      _safe_float(item.get("target_distance")),
      -_safe_float(item.get("ebitda")),
    ),
  )
  selected: List[Dict[str, Any]] = []
  seen_archetypes = set()
  for item in ranked:
    archetype = str(item.get("archetype") or "").strip()
    if archetype and archetype not in seen_archetypes:
      selected.append(item)
      seen_archetypes.add(archetype)
    elif len(selected) < MAX_SCENARIOS and all(str(existing.get("label") or "") != str(item.get("label") or "") for existing in selected):
      selected.append(item)
    if len(selected) >= MAX_SCENARIOS:
      break
  return selected


def _select_client_ready_scenarios(
  candidates: Sequence[Dict[str, Any]],
  state_model: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
  ready: List[Dict[str, Any]] = []
  for candidate in candidates:
    if not isinstance(candidate, dict):
      continue
    candidate = _enrich_candidate_strategy(_clone(candidate))
    if "presentation_issues" not in candidate:
      candidate["presentation_issues"] = _presentation_issues(candidate, state_model=state_model)
    if _safe_int(candidate.get("remaining_blocking_count")) > 0:
      continue
    if _safe_int(candidate.get("remaining_violation_count")) > 0:
      continue
    issues = set(candidate.get("presentation_issues") or [])
    if issues:
      continue
    lever_summary = candidate.get("lever_summary") if isinstance(candidate.get("lever_summary"), dict) else {}
    if _safe_int(lever_summary.get("meaningful_lever_count")) < 2:
      continue
    if _safe_float(lever_summary.get("dominant_family_share")) > 0.72:
      continue
    ready.append(candidate)
  return _select_materially_distinct_scenarios(ready)


def _select_best_effort_governed_scenarios(
  candidates: Sequence[Dict[str, Any]],
  state_model: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
  # Best-effort mode is the governed fallback after retries. Soft narrative/archetype issues
  # should not cause a hard crash when the economics materially improved and hard blockers cleared.
  allowed_issues = {
    "target_path_miss",
    "degrading_five_year_path",
    "all_negative_five_year_path",
    "weak_archetype_identity",
    "efficiency_growth_story",
    "growth_cost_story",
    "operations_absorber_story",
    "archetype_mismatch",
  }
  filtered = []
  for candidate in candidates:
    if not isinstance(candidate, dict):
      continue
    candidate = _enrich_candidate_strategy(_clone(candidate))
    if "presentation_issues" not in candidate:
      candidate["presentation_issues"] = _presentation_issues(candidate, state_model=state_model)
    if _safe_int(candidate.get("remaining_blocking_count")) > 0:
      continue
    issues = set(candidate.get("presentation_issues") or [])
    hard_negative_failure = (
      "all_negative_five_year_path" in issues
      and "degrading_five_year_path" in issues
    )
    if hard_negative_failure:
      continue
    if not issues.issubset(allowed_issues):
      continue
    filtered.append(candidate)
  return _select_materially_distinct_scenarios(filtered)


def _distribute_child_solution(
  *,
  product_basis: Sequence[Dict[str, Any]],
  annual_units_total: float,
  price_ratio: float,
) -> Tuple[Dict[str, Dict[str, Any]], int]:
  baseline_total = sum(max(0.0, _safe_float(item.get("annual_units"))) for item in product_basis if isinstance(item, dict))
  remaining = annual_units_total - baseline_total
  child_solution: Dict[str, Dict[str, Any]] = {}
  basis_items = [item for item in product_basis if isinstance(item, dict)]
  if remaining >= 0:
    ranked = sorted(
      basis_items,
      key=lambda item: (
        -max(0.0, _safe_float(item.get("annual_capacity_units")) - _safe_float(item.get("annual_units"))),
        str(item.get("product_key") or ""),
      ),
    )
  else:
    ranked = sorted(
      basis_items,
      key=lambda item: (
        -_safe_float(item.get("annual_units")),
        str(item.get("product_key") or ""),
      ),
    )
  for item in basis_items:
    child_solution[str(item.get("product_key") or "")] = {
      "unit_price": _safe_float(item.get("unit_price")),
      "utilization_rate": _safe_float(item.get("utilization_rate")),
      "avg_units_per_period_year1": _safe_float(item.get("avg_units_per_period_year1")),
    }
  changed = set()
  for item in ranked:
    key = str(item.get("product_key") or "")
    current_units = max(0.0, _safe_float(item.get("annual_units")))
    capacity_units = max(current_units, _safe_float(item.get("annual_capacity_units")))
    periods = max(1.0, _safe_float(item.get("operating_periods_per_year")))
    if remaining > 0:
      delta = min(remaining, max(0.0, capacity_units - current_units))
      if delta <= 0:
        continue
      current_units += delta
      remaining -= delta
    elif remaining < 0:
      delta = min(current_units, abs(remaining))
      current_units -= delta
      remaining += delta
    else:
      break
    child_solution[key]["avg_units_per_period_year1"] = round(current_units / periods, 4)
    child_solution[key]["utilization_rate"] = round(current_units / max(capacity_units, 1e-9), 6) if capacity_units > 0 else child_solution[key]["utilization_rate"]
    child_solution[key]["unit_price"] = round(_safe_float(item.get("unit_price")) * price_ratio, 2)
    changed.add(key)
    if abs(remaining) <= 1e-6:
      break
  return child_solution, len(changed)


def _solve_direct_profile(
  *,
  profile: Dict[str, Any],
  direct_inputs: Dict[str, Any],
  target_ebitda_min: Optional[float] = None,
  target_ebitda_max: Optional[float] = None,
  enforce_blocking_bands: bool = True,
) -> Optional[Dict[str, Any]]:
  allowed = set(profile.get("allowed_levers") or [])
  if not direct_inputs:
    return None
  current_price = max(1.0, _safe_float(direct_inputs.get("current_price")))
  current_util = max(0.01, _safe_float(direct_inputs.get("current_util")))
  baseline_units = max(1.0, _safe_float(direct_inputs.get("baseline_units")))
  current_marketing = max(0.0, _safe_float(direct_inputs.get("current_marketing")))
  current_opex = max(0.0, _safe_float(direct_inputs.get("current_other_opex")))
  current_cogs_ratio = max(0.0, _safe_float(direct_inputs.get("current_cogs_ratio")))
  current_payroll = max(0.0, _safe_float(direct_inputs.get("current_payroll_total")))
  rent = max(0.0, _safe_float(direct_inputs.get("rent_annualized")))
  interest = max(0.0, _safe_float(direct_inputs.get("current_interest")))
  constraint_violations = {str(item or "").strip() for item in (direct_inputs.get("constraint_violations") or [])}
  profile_constraints = (profile.get("constraints") or {}) if isinstance(profile.get("constraints"), dict) else {}
  prefer_growth_units = bool(profile_constraints.get("prefer_growth_units")) or bool(direct_inputs.get("growth_demand_mode_enabled"))
  levels = [0.0, 0.4, 0.75, 1.0]
  families = [
    family for family in ["price", "util", "marketing", "opex", "cogs", "payroll"]
    if (
      ("price" == family and any(item in allowed for item in {"price_up", "price_down"}))
      or ("util" == family and any(item in allowed for item in {"util_up", "util_down"}))
      or ("marketing" == family and any(item in allowed for item in {"marketing_up", "marketing_down"}))
      or ("opex" == family and any(item in allowed for item in {"other_opex_up", "other_opex_down"}))
      or ("cogs" == family and any(item in allowed for item in {"cogs_up", "cogs_down"}))
      or ("payroll" == family and any(item in allowed for item in {"payroll_up", "payroll_down", "hire_delay", "hire_advance"}))
    )
  ]
  if not families:
    families = ["price"]
  target_mid = None
  if target_ebitda_min is not None and target_ebitda_max is not None:
    target_mid = (target_ebitda_min + target_ebitda_max) / 2.0
  elif target_ebitda_min is not None:
    target_mid = target_ebitda_min
  elif target_ebitda_max is not None:
    target_mid = target_ebitda_max
  best: Optional[Dict[str, Any]] = None
  best_score: Optional[float] = None
  for combo in product(levels, repeat=len(families)):
    scale_map = dict(zip(families, combo))
    price = current_price
    util = current_util
    marketing = current_marketing
    other_opex = current_opex
    cogs_ratio = current_cogs_ratio
    payroll = current_payroll
    role_months: Dict[str, int] = {}
    fixed_people_target = _safe_float(direct_inputs.get("fixed_people_payroll")) or current_payroll
    if "price_up" in allowed:
      price = current_price + (max(current_price, _safe_float(direct_inputs.get("price_upper"))) - current_price) * scale_map.get("price", 0.0)
    elif "price_down" in allowed:
      price = current_price - (current_price - max(1.0, _safe_float(direct_inputs.get("price_lower")))) * scale_map.get("price", 0.0)
    if "util_up" in allowed:
      util = current_util + (max(current_util, _safe_float(direct_inputs.get("util_max"))) - current_util) * scale_map.get("util", 0.0)
    elif "util_down" in allowed:
      util = current_util - (current_util - max(0.01, _safe_float(direct_inputs.get("util_min")))) * scale_map.get("util", 0.0)
    if "marketing_up" in allowed:
      marketing = current_marketing + (max(current_marketing, _safe_float(direct_inputs.get("marketing_upper"))) - current_marketing) * scale_map.get("marketing", 0.0)
    elif "marketing_down" in allowed:
      marketing = current_marketing - (current_marketing - max(0.0, _safe_float(direct_inputs.get("marketing_min")))) * scale_map.get("marketing", 0.0)
    if "other_opex_down" in allowed:
      other_opex = current_opex - (current_opex - max(0.0, _safe_float(direct_inputs.get("other_opex_min")))) * scale_map.get("opex", 0.0)
    elif "other_opex_up" in allowed:
      other_opex = current_opex + (max(current_opex, _safe_float(direct_inputs.get("other_opex_max"))) - current_opex) * scale_map.get("opex", 0.0)
    if "cogs_down" in allowed:
      cogs_ratio = current_cogs_ratio - (current_cogs_ratio - max(0.0, _safe_float(direct_inputs.get("cogs_ratio_min")))) * scale_map.get("cogs", 0.0)
    elif "cogs_up" in allowed:
      cogs_ratio = current_cogs_ratio + (max(current_cogs_ratio, _safe_float(direct_inputs.get("cogs_ratio_max"))) - current_cogs_ratio) * scale_map.get("cogs", 0.0)
    fixed_payroll = _safe_float(direct_inputs.get("fixed_people_payroll"))
    if "payroll_down" in allowed:
      fixed_people_target = max(0.0, fixed_payroll * (1.0 - 0.35 * scale_map.get("payroll", 0.0)))
    elif "payroll_up" in allowed:
      fixed_people_target = fixed_payroll + (max(fixed_payroll, _safe_float(direct_inputs.get("target_payroll_max_total")) - max(0.0, _safe_float(direct_inputs.get("baseline_planned_payroll")))) - fixed_payroll) * scale_map.get("payroll", 0.0)
    if "hire_delay" in allowed or "hire_advance" in allowed:
      payroll = fixed_people_target
      for role in direct_inputs.get("roles") or []:
        if not isinstance(role, dict):
          continue
        base_months = max(0, _safe_int(role.get("base_months")))
        max_months = max(base_months, _safe_int(role.get("max_months")) or base_months)
        if "hire_delay" in allowed:
          months_until = base_months + int(round((max_months - base_months) * scale_map.get("payroll", 0.0)))
        else:
          months_until = max(0, base_months - int(round(base_months * scale_map.get("payroll", 0.0))))
        role_months[str(role.get("role_title") or "")] = months_until
        payroll += max(0.0, _safe_float(role.get("annual_wage"))) * max(0.0, (12 - min(12, months_until)) / 12.0)
    elif "payroll_up" in allowed:
      payroll = current_payroll + (max(current_payroll, _safe_float(direct_inputs.get("target_payroll_max_total"))) - current_payroll) * scale_map.get("payroll", 0.0)
      fixed_people_target = payroll
    elif "payroll_down" in allowed:
      payroll = current_payroll - (current_payroll - max(0.0, _safe_float(direct_inputs.get("target_payroll_min_total")))) * scale_map.get("payroll", 0.0)
    marketing_factor = 1.0
    if current_marketing > 0:
      marketing_factor = max(0.75, min(1.35, 1.0 + 0.35 * ((marketing / current_marketing) - 1.0)))
    price_factor = max(0.7, 1.0 - max(0.0, (price / current_price) - 1.0) * 0.35)
    if "price_down" in allowed and price < current_price:
      price_factor = min(1.25, 1.0 + ((current_price - price) / current_price) * 0.3)
    units = baseline_units * (util / current_util) * marketing_factor * price_factor
    growth_units_floor = 0.0
    if prefer_growth_units:
      growth_anchor = max(
        _safe_float(direct_inputs.get("expected_units")),
        _safe_float(direct_inputs.get("marketing_support_units_baseline")),
        baseline_units,
      )
      growth_units_floor = min(_safe_float(direct_inputs.get("units_max")), max(_safe_float(direct_inputs.get("units_min")), growth_anchor * 0.8))
      units = max(units, growth_units_floor)
    units = max(_safe_float(direct_inputs.get("units_min")), min(_safe_float(direct_inputs.get("units_max")), units))
    revenue = units * price
    cogs = revenue * cogs_ratio
    ebitda = revenue - cogs - payroll - marketing - other_opex - rent - interest
    score = 0.0
    if enforce_blocking_bands:
      if target_ebitda_min is not None and ebitda < target_ebitda_min:
        score += (target_ebitda_min - ebitda)
      if target_ebitda_max is not None and ebitda > target_ebitda_max + max(2500.0, 0.03 * revenue):
        score += (ebitda - target_ebitda_max)
    if target_mid is not None:
      score += abs(ebitda - target_mid)
    else:
      score += max(0.0, -ebitda) * 0.5
    if "payroll_too_light" in constraint_violations and payroll + 1.0 < _safe_float(direct_inputs.get("structural_payroll_floor")):
      score += (_safe_float(direct_inputs.get("structural_payroll_floor")) - payroll) * 40.0
    if prefer_growth_units and growth_units_floor > 0 and units + 1e-6 < growth_units_floor:
      score += (growth_units_floor - units) * 250.0
    score += sum(scale_map.values()) * 250.0
    if best_score is None or score < best_score:
      family_raw_components = {
        ("price_up" if "price_up" in allowed else "price_down"): scale_map.get("price", 0.0) if any(item in allowed for item in {"price_up", "price_down"}) else 0.0,
        ("util_up" if "util_up" in allowed else "util_down"): scale_map.get("util", 0.0) if any(item in allowed for item in {"util_up", "util_down"}) else 0.0,
        ("marketing_up" if "marketing_up" in allowed else "marketing_down"): scale_map.get("marketing", 0.0) if any(item in allowed for item in {"marketing_up", "marketing_down"}) else 0.0,
        ("other_opex_up" if "other_opex_up" in allowed else "other_opex_down"): scale_map.get("opex", 0.0) if any(item in allowed for item in {"other_opex_up", "other_opex_down"}) else 0.0,
        ("cogs_up" if "cogs_up" in allowed else "cogs_down"): scale_map.get("cogs", 0.0) if any(item in allowed for item in {"cogs_up", "cogs_down"}) else 0.0,
        ("payroll_up" if "payroll_up" in allowed else "payroll_down" if "payroll_down" in allowed else "hire_delay" if "hire_delay" in allowed else "hire_advance"): scale_map.get("payroll", 0.0) if any(item in allowed for item in {"payroll_up", "payroll_down", "hire_delay", "hire_advance"}) else 0.0,
      }
      solution: Dict[str, Any] = {
        "price": round(price, 2),
        "utilization_rate": round(util, 6),
        "annual_units_total": round(units, 4),
        "marketing_total_year1": round(marketing, 2),
        "marketing_support_units_year1": round(units, 2),
        "other_operating_expense": round(other_opex, 2),
        "cogs_total_year1": round(cogs, 2),
        "payroll_total_year1": round(payroll, 2),
        "current_payroll_total": round(payroll, 2),
        "fixed_people_payroll_target": round(fixed_people_target, 2),
        "structural_payroll_required_total": round(max(payroll, _safe_float(direct_inputs.get("structural_payroll_floor"))), 2),
        "role_months": role_months,
        "role_year1_payroll": {},
        "role_wage_meta": {},
        "family_raw_components": family_raw_components,
        "ebitda": round(ebitda, 2),
        "ebitda_margin": round(ebitda / max(revenue, 1.0), 6),
      }
      product_basis = [item for item in (direct_inputs.get("product_driver_basis") or []) if isinstance(item, dict)]
      if str(direct_inputs.get("solve_mode") or "") == "child_first" and product_basis:
        child_solution, changed_count = _distribute_child_solution(
          product_basis=product_basis,
          annual_units_total=units,
          price_ratio=(price / current_price) if current_price > 0 else 1.0,
        )
        solution["child_product_solution"] = child_solution
        solution["changed_child_product_count"] = changed_count
      best = solution
      best_score = score
  return best


def _build_governed_rescue_scenarios(
  *,
  state_model: Dict[str, Any],
  attempted_candidates: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  allowed_issues = {"target_path_miss", "degrading_five_year_path", "all_negative_five_year_path"}
  attempted = [item for item in attempted_candidates if isinstance(item, dict)]
  if not attempted:
    return []
  attempted = [
    _enrich_candidate_strategy(_clone(item))
    for item in attempted
    if _safe_int(item.get("remaining_blocking_count")) <= 0
    and set(item.get("presentation_issues") or []).issubset(allowed_issues)
    and not (
      "all_negative_five_year_path" in set(item.get("presentation_issues") or [])
      and "degrading_five_year_path" in set(item.get("presentation_issues") or [])
    )
  ]
  if not attempted:
    return []
  ranked = sorted(
    attempted,
    key=lambda item: (
      _safe_int(item.get("remaining_blocking_count")),
      _safe_int(item.get("remaining_violation_count")),
      len(item.get("presentation_issues") or []),
      _safe_float(item.get("target_distance")),
      -_safe_float(item.get("ebitda")),
    ),
  )
  return ranked[:1]
