from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional, Sequence

from consistency_financials import (  # type: ignore
  build_consistency_financial_summary,
  build_consistency_financial_table,
)

from .common import (
  _archetype_consistency,
  _clone,
  _derive_commercial_archetype,
  _derive_scenario_posture,
  _gpt_strategy_required,
  _in_test_context,
  _normalize_ratio,
  _package_expected_effects,
  _presentation_issues,
  _safe_float,
  _safe_int,
  _unique_strings,
)
from .controller import (
  _build_calibration_contract,
  _build_consistency_state_model,
  _build_controller_inputs,
  _build_strategy_catalog,
  _build_runtime_strategy,
  _contextualize_deterministic_strategy,
  _controller_enforced_profile,
  _diagnose_case,
  _gpt_blueprint_is_usable,
  _controller_profiles,
)
from .finmo_controller import build_controller_finmo_candidate
MAX_GOVERNED_ATTEMPTS = 3


def _baseline_summary_from_finmo(finmo_json: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  if not isinstance(finmo_json, dict) or not finmo_json:
    return {}
  try:
    from finmo_bridge import build_consistency_forecast_view_from_finmo  # type: ignore
  except Exception:
    from client_intake_and_finmo.finmo_bridge import build_consistency_forecast_view_from_finmo  # type: ignore
  try:
    result = build_consistency_forecast_view_from_finmo(finmo_json)
  except Exception:
    result = {}
  forecast_years = [item for item in ((result.get("forecast_years") or []) if isinstance(result, dict) else []) if isinstance(item, dict)]
  if not forecast_years:
    return {}
  year1 = forecast_years[0]
  lease = _safe_float(year1.get("lease"))
  return {
    "revenue": _safe_float(year1.get("revenue")),
    "cogs": _safe_float(year1.get("cogs")),
    "gross_profit": _safe_float(year1.get("gross_profit")),
    "marketing": _safe_float(year1.get("marketing")),
    "payroll": _safe_float(year1.get("payroll")),
    "other_opex_non_rent": max(0.0, _safe_float(year1.get("opex")) - lease),
    "rent_annualized": lease,
    "ebitda": _safe_float(year1.get("ebitda")),
    "interest": _safe_float(year1.get("interest")),
    "taxes": _safe_float(year1.get("taxes")),
    "net_income": _safe_float(year1.get("net_income")),
  }


def _gpt_strategy_selection(
  *,
  baseline_summary: Dict[str, Any],
  fixed_facts: Dict[str, Any],
  viability_mode: bool,
  diagnosis: Dict[str, Any],
  strategy_catalog: List[Dict[str, Any]],
  retry_feedback: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  try:
    from consistency_strategy_advisor import advise_consistency_strategy_selection  # type: ignore
  except Exception:
    from client_intake_and_finmo.consistency_strategy_advisor import advise_consistency_strategy_selection  # type: ignore
  try:
    result = advise_consistency_strategy_selection(
      baseline_summary=baseline_summary,
      fixed_facts=fixed_facts,
      viability_mode=viability_mode,
      diagnosis=diagnosis,
      strategy_catalog=strategy_catalog,
      retry_context=retry_feedback,
    )
  except Exception as exc:
    return {"error": "strategy_advisor_execution_failed", "error_detail": str(exc)}
  return result if isinstance(result, dict) else {"error": "strategy_advisor_invalid_response"}


def _gpt_finmo_validation(
  *,
  validation_request: Dict[str, Any],
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  fixed_facts: Optional[Dict[str, Any]] = None,
  strategy_selection: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  try:
    from consistency_strategy_advisor import validate_consistency_finmo_result  # type: ignore
  except Exception:
    from client_intake_and_finmo.consistency_strategy_advisor import validate_consistency_finmo_result  # type: ignore
  try:
    result = validate_consistency_finmo_result(
      validation_request=validation_request,
      model_input_json=model_input_json,
      finmo_json=finmo_json,
      fixed_facts=fixed_facts,
      strategy_selection=strategy_selection,
    )
  except Exception as exc:
    return {"error": str(exc)}
  return result if isinstance(result, dict) else {}


def _strategy_retry_feedback(
  *,
  strategy_layer: Dict[str, Any],
  attempted_scenarios: Sequence[Dict[str, Any]],
  baseline_summary: Dict[str, Any],
) -> Dict[str, Any]:
  scenario_feedback = [
    {
      "strategy_id": str(item.get("strategy_id") or "").strip(),
      "remaining_violations": list(item.get("remaining_violations") or []),
      "presentation_issues": list(item.get("presentation_issues") or []),
      "target_path_assessment": item.get("target_path_assessment") or {},
    }
    for item in attempted_scenarios
    if isinstance(item, dict)
  ]
  hard_negative_failures = [
    item for item in scenario_feedback
    if {
      "all_negative_five_year_path",
      "degrading_five_year_path",
    }.issubset(set(item.get("presentation_issues") or []))
  ]
  repeated_strategy_ids = [
    str(item.get("strategy_id") or "").strip()
    for item in (strategy_layer.get("strategies") or [])
    if isinstance(item, dict)
  ]
  return {
    "prior_attempts": [
      {
        "strategy_id": str(item.get("strategy_id") or "").strip(),
        "issues": list(item.get("remaining_violations") or []),
        "optimistic_ebitda": _safe_float((((item.get("forecast_years") or [None])[0] or {}) if isinstance((item.get("forecast_years") or [None])[0], dict) else {}).get("ebitda")),
      }
      for item in attempted_scenarios
      if isinstance(item, dict)
    ],
    "attempted_scenarios": scenario_feedback,
    "baseline_summary": baseline_summary,
    "selected_strategy_ids": repeated_strategy_ids,
    "escalation_required": bool(scenario_feedback) and len(hard_negative_failures) == len(scenario_feedback),
    "hard_negative_failure_count": len(hard_negative_failures),
    "total_attempted_scenario_count": len(scenario_feedback),
  }


def _finmo_attempt_sort_key(candidate: Dict[str, Any]) -> tuple:
  issues = set(str(item or "").strip() for item in (candidate.get("presentation_issues") or []))
  forecast_years = [item for item in (candidate.get("forecast_years") or []) if isinstance(item, dict)]
  year1 = forecast_years[0] if forecast_years else {}
  year3 = forecast_years[2] if len(forecast_years) >= 3 else {}
  validation = (candidate.get("gpt_validation_result") or {}) if isinstance(candidate.get("gpt_validation_result"), dict) else {}
  validation_status = str(validation.get("validation_status") or "").strip().lower()
  accepted = 1 if validation_status in {"accepted", "ready", "pass"} else 0
  return (
    accepted,
    -_safe_int(candidate.get("remaining_blocking_count")),
    -_safe_int(candidate.get("remaining_violation_count")),
    -len(issues),
    _safe_float(year3.get("ebitda")),
    _safe_float(year1.get("ebitda")),
  )


def _select_best_finmo_attempts(
  attempts: Sequence[Dict[str, Any]],
  *,
  require_clear: bool,
  limit: int = 1,
) -> List[Dict[str, Any]]:
  valid_attempts = [item for item in attempts if isinstance(item, dict)]
  if require_clear:
    valid_attempts = [item for item in valid_attempts if _safe_int(item.get("remaining_blocking_count")) <= 0]
  ranked = sorted(valid_attempts, key=_finmo_attempt_sort_key, reverse=True)
  return [_clone(item) for item in ranked[:max(1, limit)]]


def _build_blocking_consistency_state(
  *,
  baseline_summary: Dict[str, Any],
  baseline_table_markdown: str,
  state_model: Dict[str, Any],
  blocking_reason: str,
  blocking_violations: Optional[Sequence[str]] = None,
  attempted_scenarios: Optional[Sequence[Dict[str, Any]]] = None,
  attempt_failures: Optional[Sequence[Dict[str, Any]]] = None,
  governed_attempt_count: int = 0,
  strategy_retry_attempts: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
  return {
    "status": "blocking_unresolved",
    "blocking_reason": str(blocking_reason or "no_viable_scenarios"),
    "blocking_violations": list(blocking_violations or []),
    "selection_status": None,
    "revenue_driver_resolution_mode": str(state_model.get("revenue_driver_resolution_mode") or "parent_fallback"),
    "baseline_summary": baseline_summary,
    "baseline_loss_pct": (_safe_float(baseline_summary.get("ebitda")) / max(1.0, _safe_float(baseline_summary.get("revenue")))),
    "baseline_table_markdown": str(baseline_table_markdown or "").strip(),
    "state_model": state_model,
    "scenarios": [],
    "attempted_scenarios": list(attempted_scenarios or []),
    "attempt_failures": list(attempt_failures or []),
    "governed_attempt_limit": MAX_GOVERNED_ATTEMPTS,
    "governed_attempt_count": int(governed_attempt_count or 0),
    "strategy_retry_attempts": list(strategy_retry_attempts or []),
    "selected_target_label": "governed_year1_target",
    "selected_target_ebitda_min": None,
    "selected_target_ebitda_max": None,
    "structural_gap": _safe_float(baseline_summary.get("ebitda")),
  }


def _build_strategy_layer(
  *,
  state_model: Dict[str, Any],
  direct_inputs: Optional[Dict[str, Any]],
  baseline_summary: Dict[str, Any],
  diagnostic_state: Optional[Dict[str, Any]],
  viability_mode: bool,
  retry_feedback: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  del diagnostic_state
  diagnosis: Dict[str, Any] = _diagnose_case(
    baseline_summary=baseline_summary,
    diagnostic_state=None,
  )
  catalog = _build_strategy_catalog(state_model=state_model, direct_inputs=direct_inputs)
  prior_selected_ids = [
    str(item or "").strip()
    for item in ((retry_feedback or {}).get("selected_strategy_ids") or [])
    if str(item or "").strip()
  ] if isinstance(retry_feedback, dict) else []
  escalation_required = bool((retry_feedback or {}).get("escalation_required")) if isinstance(retry_feedback, dict) else False
  preferred_ids = [
    str(item or "").strip()
    for item in (diagnosis.get("preferred_strategy_ids") or [])
    if str(item or "").strip()
  ]
  shortlisted_catalog = [
    item for item in catalog
    if isinstance(item, dict) and str(item.get("strategy_id") or "").strip() in set(preferred_ids)
  ]
  catalog_for_selection = list(shortlisted_catalog or catalog)
  if escalation_required and prior_selected_ids:
    alternative_catalog = [
      item for item in (shortlisted_catalog or catalog)
      if isinstance(item, dict) and str(item.get("strategy_id") or "").strip() not in set(prior_selected_ids)
    ]
    if alternative_catalog:
      catalog_for_selection = alternative_catalog
  gpt_required = _gpt_strategy_required()
  selection = _gpt_strategy_selection(
    baseline_summary=baseline_summary,
    fixed_facts=(state_model.get("fixed_facts") or {}) if isinstance(state_model.get("fixed_facts"), dict) else {},
    viability_mode=viability_mode,
    diagnosis=diagnosis,
    strategy_catalog=catalog_for_selection,
    retry_feedback=retry_feedback,
  )
  strategy_by_id = {str(item.get("strategy_id") or "").strip(): item for item in catalog if isinstance(item, dict)}
  selected_ids = [
    str(item or "").strip()
    for item in (selection.get("selected_strategy_ids") or [])
    if str(item or "").strip() in strategy_by_id
  ] if isinstance(selection, dict) else []
  if gpt_required and not selected_ids:
    diagnosis["strategy_advisor_error"] = str((selection or {}).get("error") or "missing_strategy_selection")
    return {
      "source": "gpt_required_unavailable",
      "primary_drivers": [],
      "diagnosis": diagnosis,
      "strategies": [],
      "strategy_catalog": catalog,
      "strategy_selection": selection if isinstance(selection, dict) else {},
    }
  if gpt_required and selected_ids and not _gpt_blueprint_is_usable(selection if isinstance(selection, dict) else {}):
    diagnosis["strategy_advisor_error"] = "strategy_advisor_invalid_blueprint"
    diagnosis["strategy_advisor_coverage_issues"] = _clone(
      (selection or {}).get("coverage_issues") if isinstance(selection, dict) else []
    )
    return {
      "source": "gpt_required_invalid_blueprint",
      "primary_drivers": [],
      "diagnosis": diagnosis,
      "strategies": [],
      "strategy_catalog": catalog,
      "strategy_selection": selection if isinstance(selection, dict) else {},
    }
  if selected_ids and _gpt_blueprint_is_usable(selection if isinstance(selection, dict) else {}):
    strategies = [
      _build_runtime_strategy(strategy_id, selection if isinstance(selection, dict) else {}, diagnosis)
      for strategy_id in selected_ids[:2]
    ]
    merged = dict(diagnosis)
    for key in [
      "primary_cause",
      "secondary_causes",
      "reason",
      "business_model_assessment",
      "severity_class",
      "severity_reason",
      "minimum_package_strength",
      "viability_blueprint_summary",
      "scaling_model_summary",
      "allowed_model_input_levers",
      "forbidden_model_input_levers",
      "controller_directives",
      "target_posture",
      "governed_period_groups",
      "lever_adjustment_plan",
      "controlled_output_targets",
      "capacity_release_plan",
      "hiring_release_plan",
      "demand_build_plan",
      "milestone_activation_plan",
      "support_overhead_plan",
      "outer_year_margin_logic",
    ]:
      if isinstance(selection, dict) and selection.get(key) is not None:
        merged[key] = selection.get(key)
    controller_directives = merged.get("controller_directives") if isinstance(merged.get("controller_directives"), dict) else {}
    if controller_directives:
      allowed_lever_count = len({
        str(item or "").strip()
        for item in (merged.get("allowed_model_input_levers") or [])
        if str(item or "").strip()
      })
      plan_lever_count = len({
        str(item.get("lever_id") or "").strip()
        for item in (merged.get("lever_adjustment_plan") or [])
        if isinstance(item, dict) and str(item.get("direction") or "").strip().lower() != "hold"
      })
      package_count = len([item for item in (merged.get("governed_period_groups") or []) if isinstance(item, dict)])
      merged["controller_directives"] = {
        **controller_directives,
        "minimum_meaningful_levers": max(
          _safe_int(controller_directives.get("minimum_meaningful_levers")),
          allowed_lever_count,
          plan_lever_count,
        ),
        "minimum_package_count": max(
          _safe_int(controller_directives.get("minimum_package_count")),
          package_count,
        ),
      }
    merged["gpt_primary_cause"] = selection.get("primary_cause") if isinstance(selection, dict) else None
    merged["selected_strategy_ids"] = list(selected_ids[:2])
    merged["preferred_strategy_ids"] = list(selected_ids[:2])
    if retry_feedback:
      merged["governed_retry_attempt"] = len([item for item in (retry_feedback.get("prior_attempts") or []) if isinstance(item, dict)])
      merged["escalation_required"] = bool(retry_feedback.get("escalation_required"))
    return {
      "source": "gpt",
      "primary_drivers": [],
      "diagnosis": merged,
      "strategies": strategies,
      "strategy_catalog": catalog,
      "strategy_selection": selection if isinstance(selection, dict) else {},
    }
  return {
    "source": "gpt_unavailable",
    "primary_drivers": [],
    "diagnosis": diagnosis,
    "strategies": [],
    "strategy_catalog": catalog,
    "strategy_selection": selection if isinstance(selection, dict) else {},
  }


def build_consistency_governance_state(
  *,
  ops_json: Dict[str, Any],
  target_market_json: Optional[Dict[str, Any]] = None,
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  fulfillment_json: Optional[Dict[str, Any]] = None,
  marketing_model_json: Optional[Dict[str, Any]],
  diagnostic_state: Optional[Dict[str, Any]] = None,
  finmo_path: Optional[str] = None,
  business_facts: Optional[Dict[str, Any]] = None,
  model_input_json: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
  baseline_summary = _baseline_summary_from_finmo(finmo_json) or build_consistency_financial_summary(
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
  )
  baseline_table_markdown = build_consistency_financial_table(
    baseline_summary,
  )
  state_model = _build_consistency_state_model(
    ops_json=ops_json,
    target_market_json=target_market_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    fulfillment_json=fulfillment_json,
    marketing_model_json=marketing_model_json,
    baseline_summary=baseline_summary,
    diagnostic_state=None,
    finmo_path=finmo_path,
    business_facts=business_facts,
    model_input_json=model_input_json,
    finmo_json=finmo_json,
  )
  direct_inputs = _build_controller_inputs(state_model=state_model)
  state_model["direct_inputs"] = _clone(direct_inputs) if isinstance(direct_inputs, dict) else {}
  strategy_layer = _build_strategy_layer(
    state_model=state_model,
    direct_inputs=direct_inputs,
    baseline_summary=baseline_summary,
    diagnostic_state=None,
    viability_mode=True,
  )
  state_model["strategy_layer"] = strategy_layer
  if not direct_inputs:
    return _build_blocking_consistency_state(
      baseline_summary=baseline_summary,
      baseline_table_markdown=baseline_table_markdown,
      state_model=state_model,
      blocking_reason="missing_solver_state_model",
      blocking_violations=[],
    )
  if not (strategy_layer.get("strategies") or []):
    return _build_blocking_consistency_state(
      baseline_summary=baseline_summary,
      baseline_table_markdown=baseline_table_markdown,
      state_model=state_model,
      blocking_reason="gpt_strategy_selection_unavailable",
      blocking_violations=[],
    )
  attempted_scenarios: List[Dict[str, Any]] = []
  attempt_failures: List[Dict[str, Any]] = []
  retry_attempts: List[Dict[str, Any]] = []
  selected: List[Dict[str, Any]] = []
  selection_status: Optional[str] = None
  selected_target_label = "governed_year1_target"
  current_strategy_layer = strategy_layer
  governed_attempt_count = 0
  for attempt_index in range(1, MAX_GOVERNED_ATTEMPTS + 1):
    governed_attempt_count = attempt_index
    state_model["strategy_layer"] = current_strategy_layer
    target_ebitda_min = None
    target_ebitda_max = None
    attempt_candidates: List[Dict[str, Any]] = []
    attempt_records: List[Dict[str, Any]] = []
    attempt_failure_records: List[Dict[str, Any]] = []
    selection_payload = (
      (current_strategy_layer.get("strategy_selection") or {})
      if isinstance(current_strategy_layer.get("strategy_selection"), dict)
      else {}
    )
    profiles = [item for item in _controller_profiles(state_model=state_model) if isinstance(item, dict)]
    active_profiles = profiles if _in_test_context() else (profiles[:1] if profiles else [])
    for profile_index, active_profile in enumerate(active_profiles, start=1):
      next_profile = _clone(active_profile)
      if not next_profile:
        continue
      contract_bundle = _build_calibration_contract(
        state_model=state_model,
        direct_inputs=direct_inputs,
        profile=next_profile,
        target_ebitda_min=target_ebitda_min,
        target_ebitda_max=target_ebitda_max,
      )
      diagnostics = (contract_bundle.get("diagnostics") or {}) if isinstance(contract_bundle.get("diagnostics"), dict) else {}
      candidate = build_controller_finmo_candidate(
        profile=contract_bundle.get("profile") or {},
        contract_bundle=contract_bundle,
        state_model=state_model,
        scenario_index=len(attempted_scenarios) + len(attempt_candidates) + 1,
      )
      candidate_failure = (
        candidate.get("candidate_failure")
        if isinstance(candidate, dict) and isinstance(candidate.get("candidate_failure"), dict)
        else {}
      )
      if candidate_failure:
        failure_record = {
          "attempt_index": attempt_index,
          "profile_index": profile_index,
          "scenario_id": str((candidate or {}).get("scenario_id") or "").strip(),
          "strategy_id": str((candidate or {}).get("strategy_id") or "").strip(),
          "strategy_name": str((candidate or {}).get("strategy_name") or "").strip(),
          "controller_input_seed_count": len([
            item for item in (((candidate or {}).get("controller_input_seed") or []) if isinstance((candidate or {}).get("controller_input_seed"), list) else [])
            if isinstance(item, dict)
          ]),
          "controller_calibration_request": _clone(
            (candidate or {}).get("controller_calibration_request")
            if isinstance((candidate or {}).get("controller_calibration_request"), dict)
            else {}
          ),
          "candidate_failure": _clone(candidate_failure),
        }
        attempt_failure_records.append(failure_record)
        attempt_failures.append(_clone(failure_record))
        continue
      if not isinstance(candidate, dict) or not candidate:
        continue
      validation_request = (
        candidate.get("gpt_validation_request")
        if isinstance(candidate.get("gpt_validation_request"), dict)
        else {}
      )
      validation_result = _gpt_finmo_validation(
        validation_request=validation_request,
        model_input_json=(candidate.get("model_input_json") if isinstance(candidate.get("model_input_json"), dict) else {}),
        finmo_json=(candidate.get("finmo_json") if isinstance(candidate.get("finmo_json"), dict) else {}),
        fixed_facts={
          **_clone((state_model.get("fixed_facts") or {}) if isinstance(state_model.get("fixed_facts"), dict) else {}),
          "baseline_summary": _clone(baseline_summary or {}),
        },
        strategy_selection=selection_payload,
      )
      candidate["gpt_validation_result"] = _clone(validation_result)
      validation_status = str((validation_result or {}).get("validation_status") or "").strip().lower()
      if validation_status == "rejected":
        remaining_violations = _unique_strings(list(candidate.get("remaining_violations") or []) + ["gpt_validation_rejected"])
        remaining_blocking_violations = _unique_strings(list(candidate.get("remaining_blocking_violations") or []) + ["gpt_validation_rejected"])
        candidate["remaining_violations"] = remaining_violations
        candidate["remaining_blocking_violations"] = remaining_blocking_violations
        candidate["remaining_blocking_count"] = len(remaining_blocking_violations)
        candidate["remaining_violation_count"] = len(remaining_violations)
        finmo_execution_state = (
          candidate.get("finmo_execution_state")
          if isinstance(candidate.get("finmo_execution_state"), dict)
          else {}
        )
        finmo_execution_state["gpt_validation_status"] = "rejected"
        finmo_execution_state["gpt_validation_issues"] = _clone((validation_result or {}).get("issues") or [])
        candidate["finmo_execution_state"] = finmo_execution_state
      elif validation_status:
        finmo_execution_state = (
          candidate.get("finmo_execution_state")
          if isinstance(candidate.get("finmo_execution_state"), dict)
          else {}
        )
        finmo_execution_state["gpt_validation_status"] = validation_status
        finmo_execution_state["gpt_validation_issues"] = _clone((validation_result or {}).get("issues") or [])
        candidate["finmo_execution_state"] = finmo_execution_state
      attempt_candidates.append(candidate)
      attempt_records.append(
        {
          "profile": next_profile,
          "contract_bundle": contract_bundle,
          "solution": {},
          "candidate": candidate,
        }
      )
      attempted_scenarios.extend([_clone(item.get("candidate") or {}) for item in attempt_records if isinstance(item.get("candidate"), dict)])
    accepted_attempts = _select_best_finmo_attempts(attempt_candidates, require_clear=True, limit=1)
    if accepted_attempts:
      selected = accepted_attempts
      selection_status = "finmo_validated"
      break
    retry_feedback = _strategy_retry_feedback(
      strategy_layer=current_strategy_layer,
      attempted_scenarios=attempted_scenarios,
      baseline_summary=baseline_summary,
    )
    retry_attempts.append(
      {
        "attempt_index": attempt_index,
        "attempted_scenario_count": len(attempt_candidates),
        "client_ready_scenario_count": len(accepted_attempts),
        "candidate_failure_count": len(attempt_failure_records),
        "candidate_failures": _clone(attempt_failure_records),
        "feedback": retry_feedback,
      }
    )
    if attempt_index >= MAX_GOVERNED_ATTEMPTS:
      break
    current_strategy_layer = _build_strategy_layer(
      state_model=state_model,
      direct_inputs=direct_inputs,
      baseline_summary=baseline_summary,
      diagnostic_state=None,
      viability_mode=True,
      retry_feedback=retry_feedback,
    )
    if not (current_strategy_layer.get("strategies") or []):
      return _build_blocking_consistency_state(
        baseline_summary=baseline_summary,
        baseline_table_markdown=baseline_table_markdown,
        state_model=state_model,
        blocking_reason="gpt_strategy_selection_unavailable",
        blocking_violations=[],
        attempted_scenarios=attempted_scenarios,
        attempt_failures=attempt_failures,
        governed_attempt_count=governed_attempt_count,
        strategy_retry_attempts=retry_attempts,
      )
  if not selected:
    selected = _select_best_finmo_attempts(attempted_scenarios, require_clear=True, limit=1)
    if selected:
      selection_status = "finmo_provisional"
  if not selected:
    return _build_blocking_consistency_state(
      baseline_summary=baseline_summary,
      baseline_table_markdown=baseline_table_markdown,
      state_model=state_model,
      blocking_reason="no_viable_scenarios",
      blocking_violations=[],
      attempted_scenarios=attempted_scenarios,
      attempt_failures=attempt_failures,
      governed_attempt_count=governed_attempt_count,
      strategy_retry_attempts=retry_attempts,
    )
  return {
    "status": "awaiting_choice",
    "blocking_reason": None,
    "blocking_violations": [],
    "selection_status": selection_status,
    "revenue_driver_resolution_mode": str(state_model.get("revenue_driver_resolution_mode") or "parent_fallback"),
    "baseline_summary": baseline_summary,
    "baseline_loss_pct": (_safe_float(baseline_summary.get("ebitda")) / max(1.0, _safe_float(baseline_summary.get("revenue")))),
    "baseline_table_markdown": baseline_table_markdown,
    "state_model": state_model,
    "scenarios": selected,
    "attempted_scenarios": attempted_scenarios,
    "attempt_failures": attempt_failures,
    "governed_attempt_limit": MAX_GOVERNED_ATTEMPTS,
    "governed_attempt_count": governed_attempt_count,
    "strategy_retry_attempts": retry_attempts,
    "selected_target_label": selected_target_label,
    "selected_target_ebitda_min": target_ebitda_min,
    "selected_target_ebitda_max": target_ebitda_max,
    "structural_gap": _safe_float(baseline_summary.get("ebitda")),
  }


def apply_consistency_selected_path(
  *,
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  governance_state: Dict[str, Any],
  selected_scenario_id: str,
  overrides: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  del overrides, ops_json, people_json, financials_json, financials_year1_json, marketing_model_json
  scenarios = [item for item in (governance_state.get("scenarios") or []) if isinstance(item, dict)]
  selected = next((item for item in scenarios if str(item.get("scenario_id") or "") == str(selected_scenario_id or "")), None)
  if not isinstance(selected, dict):
    return None
  modified_state = selected.get("modified_state") if isinstance(selected.get("modified_state"), dict) else {}
  if not modified_state:
    return None
  return {
    "ops_json": _clone(modified_state.get("ops_json") or {}),
    "people_json": _clone(modified_state.get("people_json") or {}),
    "financials_json": _clone(modified_state.get("financials_json") or {}),
    "financials_year1_json": _clone(modified_state.get("financials_year1_json") or {}),
    "marketing_model_json": _clone(modified_state.get("marketing_model_json") or {}),
    "scenario": selected,
  }


__all__ = [
  "_archetype_consistency",
  "_build_calibration_contract",
  "_build_consistency_state_model",
  "_build_controller_inputs",
  "_controller_enforced_profile",
  "_derive_commercial_archetype",
  "_derive_scenario_posture",
  "_gpt_blueprint_is_usable",
  "_gpt_strategy_required",
  "_gpt_strategy_selection",
  "_normalize_ratio",
  "_package_expected_effects",
  "_presentation_issues",
  "_safe_float",
  "_select_best_finmo_attempts",
  "_controller_profiles",
  "apply_consistency_selected_path",
  "build_consistency_governance_state",
]
