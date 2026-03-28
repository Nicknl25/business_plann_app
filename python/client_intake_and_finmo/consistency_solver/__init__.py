from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional, Sequence

from consistency_financials import (  # type: ignore
  build_consistency_financial_summary,
  build_consistency_financial_table,
)
from forecast_engine import build_forecast_engine_bundle  # type: ignore

from .common import (
  _archetype_consistency,
  _clone,
  _derive_commercial_archetype,
  _derive_scenario_posture,
  _gpt_strategy_required,
  _in_test_context,
  _normalize_ratio,
  _normalized_family_name,
  _normalized_plan_entry_families,
  _package_expected_effects,
  _presentation_issues,
  _safe_float,
  _safe_int,
  _unique_strings,
)
from .controller import (
  _build_direct_solver_inputs,
  _build_profile_solver_contract,
  _build_solver_state_model,
  _build_strategy_catalog,
  _build_runtime_strategy,
  _contextualize_deterministic_strategy,
  _controller_enforced_profile,
  _diagnose_case,
  _gpt_blueprint_is_usable,
  _solver_profiles,
)
from .finmo_controller import build_controller_finmo_candidate
from .engine import (
  MAX_SCENARIOS,
  _build_candidate,
  _build_client_scenario_output,
  _build_governed_rescue_scenarios,
  _build_scenario_forecast_bundle,
  _select_best_effort_governed_scenarios,
  _select_client_ready_scenarios,
  _select_materially_distinct_scenarios,
  _solver_required,
)
from .patches import (
  _apply_exact_patches,
  _build_lever_summary,
  _exact_patches_from_solution,
  _label_and_rationale_from_patches,
  _sync_marketing_derived_fields,
)


MAX_GOVERNED_ATTEMPTS = 3


def _gpt_strategy_selection(
  *,
  baseline_summary: Dict[str, Any],
  constraint_engine_state: Optional[Dict[str, Any]],
  baseline_forecast_bundle: Optional[Dict[str, Any]],
  fixed_facts: Dict[str, Any],
  viability_mode: bool,
  diagnosis: Dict[str, Any],
  strategy_catalog: List[Dict[str, Any]],
  orchestration_context: Optional[Dict[str, Any]] = None,
  solver_feedback: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  try:
    from consistency_strategy_advisor import advise_consistency_strategy_selection  # type: ignore
  except Exception:
    from client_intake_and_finmo.consistency_strategy_advisor import advise_consistency_strategy_selection  # type: ignore
  try:
    result = advise_consistency_strategy_selection(
      baseline_summary=baseline_summary,
      constraint_engine_state=constraint_engine_state,
      baseline_forecast_bundle=baseline_forecast_bundle,
      fixed_facts=fixed_facts,
      viability_mode=viability_mode,
      diagnosis=diagnosis,
      strategy_catalog=strategy_catalog,
      orchestration_context=orchestration_context,
      solver_feedback=solver_feedback,
    )
  except Exception as exc:
    return {"error": "strategy_advisor_execution_failed", "error_detail": str(exc)}
  return result if isinstance(result, dict) else {"error": "strategy_advisor_invalid_response"}


def _gpt_translation_audit(
  *,
  strategy_selection: Dict[str, Any],
  translated_contract: Dict[str, Any],
  translated_modified_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  try:
    from consistency_strategy_advisor import audit_consistency_controller_translation  # type: ignore
  except Exception:
    from client_intake_and_finmo.consistency_strategy_advisor import audit_consistency_controller_translation  # type: ignore
  try:
    result = audit_consistency_controller_translation(
      strategy_selection=strategy_selection,
      translated_contract=translated_contract,
      translated_modified_state=translated_modified_state,
    )
  except Exception as exc:
    return {"error": str(exc)}
  return result if isinstance(result, dict) else {}


def _translation_audit_payload(contract_bundle: Dict[str, Any]) -> Dict[str, Any]:
  profile = (contract_bundle.get("profile") or {}) if isinstance(contract_bundle.get("profile"), dict) else {}
  orchestration = (profile.get("forecast_orchestration") or {}) if isinstance(profile.get("forecast_orchestration"), dict) else {}
  translated_contract = {
    "profile": _clone(profile),
    "direct_inputs": _clone(contract_bundle.get("direct_inputs") or {}),
    "diagnostics": _clone(contract_bundle.get("diagnostics") or {}),
    "forecast_orchestration": _clone(orchestration),
  }
  translated_modified_state = {
    "allowed_levers": _clone(profile.get("allowed_levers") or []),
    "forecast_orchestration": _clone(orchestration),
    "role_timing_overrides": _clone(orchestration.get("role_timing_overrides") or []),
    "milestone_timing_overrides": _clone(orchestration.get("milestone_timing_overrides") or []),
    "event_response": _clone(orchestration.get("event_response") or {}),
  }
  return {
    "translated_contract": translated_contract,
    "translated_modified_state": translated_modified_state,
  }


def _strategy_retry_feedback(
  *,
  strategy_layer: Dict[str, Any],
  attempted_contract_bundles: Sequence[Dict[str, Any]],
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
        "issues": list((((item.get("diagnostics") or {}) if isinstance(item.get("diagnostics"), dict) else {}).get("issues") or [])),
        "optimistic_ebitda": _safe_float((((item.get("diagnostics") or {}) if isinstance(item.get("diagnostics"), dict) else {}).get("optimistic_ebitda"))),
      }
      for item in attempted_contract_bundles
      if isinstance(item, dict)
    ],
    "attempted_scenarios": scenario_feedback,
    "baseline_summary": baseline_summary,
    "selected_strategy_ids": repeated_strategy_ids,
    "escalation_required": bool(scenario_feedback) and len(hard_negative_failures) == len(scenario_feedback),
    "hard_negative_failure_count": len(hard_negative_failures),
    "total_attempted_scenario_count": len(scenario_feedback),
  }


def _build_blocking_solver_state(
  *,
  baseline_summary: Dict[str, Any],
  baseline_table_markdown: str,
  state_model: Dict[str, Any],
  blocking_reason: str,
  blocking_violations: Optional[Sequence[str]] = None,
  attempted_contract_bundles: Optional[Sequence[Dict[str, Any]]] = None,
  attempted_scenarios: Optional[Sequence[Dict[str, Any]]] = None,
  governed_attempt_count: int = 0,
  strategy_retry_attempts: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
  return {
    "status": "blocking_unresolved",
    "blocking_reason": str(blocking_reason or "no_viable_scenarios"),
    "blocking_violations": list(blocking_violations or []),
    "selection_mode": None,
    "solve_mode": str(state_model.get("solve_mode") or "parent_fallback"),
    "search_mode": "governed",
    "baseline_summary": baseline_summary,
    "baseline_loss_pct": (_safe_float(baseline_summary.get("ebitda")) / max(1.0, _safe_float(baseline_summary.get("revenue")))),
    "baseline_table_markdown": str(baseline_table_markdown or "").strip(),
    "state_model": state_model,
    "scenarios": [],
    "client_scenarios": [],
    "attempted_scenarios": list(attempted_scenarios or []),
    "attempted_contract_bundles": list(attempted_contract_bundles or []),
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
  baseline_summary: Dict[str, Any],
  constraint_engine_state: Optional[Dict[str, Any]],
  normalized_traits: Optional[Dict[str, Any]],
  viability_mode: bool,
  baseline_forecast_bundle: Optional[Dict[str, Any]] = None,
  solver_feedback: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  del normalized_traits
  diagnosis = _diagnose_case(
    baseline_summary=baseline_summary,
    constraint_engine_state=constraint_engine_state,
  )
  catalog = _build_strategy_catalog()
  prior_selected_ids = [
    str(item or "").strip()
    for item in ((solver_feedback or {}).get("selected_strategy_ids") or [])
    if str(item or "").strip()
  ] if isinstance(solver_feedback, dict) else []
  escalation_required = bool((solver_feedback or {}).get("escalation_required")) if isinstance(solver_feedback, dict) else False
  catalog_for_selection = list(catalog)
  if escalation_required and prior_selected_ids:
    alternative_catalog = [
      item for item in catalog
      if isinstance(item, dict) and str(item.get("strategy_id") or "").strip() not in set(prior_selected_ids)
    ]
    if alternative_catalog:
      catalog_for_selection = alternative_catalog
  gpt_required = _gpt_strategy_required()
  selection = _gpt_strategy_selection(
    baseline_summary=baseline_summary,
    constraint_engine_state=constraint_engine_state,
    baseline_forecast_bundle=baseline_forecast_bundle,
    fixed_facts=(state_model.get("fixed_facts") or {}) if isinstance(state_model.get("fixed_facts"), dict) else {},
    viability_mode=viability_mode,
    diagnosis=diagnosis,
    strategy_catalog=catalog_for_selection,
    orchestration_context={},
    solver_feedback=solver_feedback,
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
      "primary_drivers": list((constraint_engine_state or {}).get("violations") or []),
      "diagnosis": diagnosis,
      "strategies": [],
      "strategy_catalog": catalog,
      "strategy_selection": selection if isinstance(selection, dict) else {},
    }
  if gpt_required and selected_ids and not _gpt_blueprint_is_usable(selection if isinstance(selection, dict) else {}):
    diagnosis["strategy_advisor_error"] = "strategy_advisor_invalid_blueprint"
    return {
      "source": "gpt_required_invalid_blueprint",
      "primary_drivers": list((constraint_engine_state or {}).get("violations") or []),
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
      "required_lever_families",
      "forbidden_lever_families",
      "controller_directives",
      "target_margin_path",
      "target_posture",
      "coordinated_lever_packages",
      "lever_family_plan",
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
      required_family_count = len({
        _normalized_family_name(item)
        for item in (merged.get("required_lever_families") or [])
        if str(item or "").strip()
      })
      plan_family_count = len({
        _normalized_family_name(item.get("family"))
        for item in (merged.get("lever_family_plan") or [])
        if isinstance(item, dict) and str(item.get("direction") or "").strip().lower() != "hold"
      })
      package_count = len([item for item in (merged.get("coordinated_lever_packages") or []) if isinstance(item, dict)])
      merged["controller_directives"] = {
        **controller_directives,
        "minimum_meaningful_levers": max(
          _safe_int(controller_directives.get("minimum_meaningful_levers")),
          required_family_count,
          plan_family_count,
        ),
        "minimum_package_count": max(
          _safe_int(controller_directives.get("minimum_package_count")),
          package_count,
        ),
      }
    merged["gpt_primary_cause"] = selection.get("primary_cause") if isinstance(selection, dict) else None
    merged["selected_strategy_ids"] = list(selected_ids[:2])
    merged["preferred_strategy_ids"] = list(selected_ids[:2])
    merged["gpt_expected_year1_ebitda_margin_min"] = _safe_float((selection or {}).get("expected_year1_ebitda_margin_min"))
    merged["gpt_expected_year1_ebitda_margin_max"] = _safe_float((selection or {}).get("expected_year1_ebitda_margin_max"))
    if solver_feedback:
      merged["governed_retry_attempt"] = len([item for item in (solver_feedback.get("prior_attempts") or []) if isinstance(item, dict)])
      merged["escalation_required"] = bool(solver_feedback.get("escalation_required"))
    return {
      "source": "gpt",
      "primary_drivers": list((constraint_engine_state or {}).get("violations") or []),
      "diagnosis": merged,
      "strategies": strategies,
      "strategy_catalog": catalog,
      "strategy_selection": selection if isinstance(selection, dict) else {},
    }
  strategies: List[Dict[str, Any]] = []
  preferred_ids = [
    str(item or "").strip()
    for item in (diagnosis.get("preferred_strategy_ids") or [])
    if str(item or "").strip() in strategy_by_id
  ]
  seen_ids = set()
  for strategy_id in preferred_ids:
    template = strategy_by_id.get(strategy_id)
    if not isinstance(template, dict):
      continue
    strategies.append(
      _contextualize_deterministic_strategy(
        template=template,
        diagnosis=diagnosis,
        constraint_engine_state=constraint_engine_state,
      )
    )
    seen_ids.add(strategy_id)
    if len(strategies) >= 2:
      break
  if len(strategies) < 2:
    for item in catalog:
      if not isinstance(item, dict):
        continue
      strategy_id = str(item.get("strategy_id") or "").strip()
      if not strategy_id or strategy_id in seen_ids:
        continue
      strategies.append(
        _contextualize_deterministic_strategy(
          template=item,
          diagnosis=diagnosis,
          constraint_engine_state=constraint_engine_state,
        )
      )
      seen_ids.add(strategy_id)
      if len(strategies) >= 2:
        break
  diagnosis["preferred_strategy_ids"] = [str(item.get("strategy_id") or "").strip() for item in strategies[:2]]
  return {
    "source": "deterministic",
    "primary_drivers": list((constraint_engine_state or {}).get("violations") or []),
    "diagnosis": diagnosis,
    "strategies": strategies[:2],
    "strategy_catalog": catalog,
    "strategy_selection": selection if isinstance(selection, dict) else {},
  }


def build_consistency_solver_state(
  *,
  ops_json: Dict[str, Any],
  target_market_json: Optional[Dict[str, Any]] = None,
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  fulfillment_json: Optional[Dict[str, Any]] = None,
  marketing_model_json: Optional[Dict[str, Any]],
  normalized_traits: Optional[Dict[str, Any]] = None,
  benchmark_payload: Optional[Dict[str, Any]] = None,
  constraint_engine_state: Optional[Dict[str, Any]] = None,
  finmo_path: Optional[str] = None,
  business_facts: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
  baseline_summary = build_consistency_financial_summary(
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
  )
  baseline_table_markdown = build_consistency_financial_table(
    baseline_summary,
  )
  state_model = _build_solver_state_model(
    ops_json=ops_json,
    target_market_json=target_market_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    fulfillment_json=fulfillment_json,
    marketing_model_json=marketing_model_json,
    baseline_summary=baseline_summary,
    constraint_engine_state=constraint_engine_state,
    normalized_traits=normalized_traits,
    benchmark_payload=benchmark_payload,
    finmo_path=finmo_path,
    business_facts=business_facts,
  )
  baseline_forecast_bundle = build_forecast_engine_bundle(
    operating_model_json=ops_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    marketing_model_json=marketing_model_json or {},
    normalized_traits=normalized_traits or {},
    benchmark_payload=benchmark_payload or {},
    constraint_engine_state=constraint_engine_state or {},
  )
  baseline_forecast_bundle = _clone(baseline_forecast_bundle)
  state_model["baseline_forecast_bundle"] = baseline_forecast_bundle
  strategy_layer = _build_strategy_layer(
    state_model=state_model,
    baseline_summary=baseline_summary,
    constraint_engine_state=constraint_engine_state,
    normalized_traits=normalized_traits,
    viability_mode=True,
    baseline_forecast_bundle=baseline_forecast_bundle,
  )
  state_model["strategy_layer"] = strategy_layer
  direct_inputs = _build_direct_solver_inputs(state_model=state_model)
  if not direct_inputs:
    return _build_blocking_solver_state(
      baseline_summary=baseline_summary,
      baseline_table_markdown=baseline_table_markdown,
      state_model=state_model,
      blocking_reason="missing_solver_state_model",
      blocking_violations=list((constraint_engine_state or {}).get("violations") or []),
    )
  if not (strategy_layer.get("strategies") or []):
    return _build_blocking_solver_state(
      baseline_summary=baseline_summary,
      baseline_table_markdown=baseline_table_markdown,
      state_model=state_model,
      blocking_reason="gpt_strategy_selection_unavailable",
      blocking_violations=list((constraint_engine_state or {}).get("violations") or []),
    )
  attempted_contract_bundles: List[Dict[str, Any]] = []
  attempted_scenarios: List[Dict[str, Any]] = []
  retry_attempts: List[Dict[str, Any]] = []
  selected: List[Dict[str, Any]] = []
  selection_mode: Optional[str] = None
  selected_target_label = "governed_year1_target"
  current_strategy_layer = strategy_layer
  for attempt_index in range(1, MAX_GOVERNED_ATTEMPTS + 1):
    state_model["strategy_layer"] = current_strategy_layer
    target_path = (((current_strategy_layer.get("diagnosis") or {}) if isinstance(current_strategy_layer.get("diagnosis"), dict) else {}).get("target_margin_path") or {})
    revenue = max(1.0, _safe_float(direct_inputs.get("current_revenue")))
    target_ebitda_min = revenue * _safe_float(target_path.get("year1_min")) if isinstance(target_path, dict) and target_path.get("year1_min") is not None else None
    target_ebitda_max = revenue * _safe_float(target_path.get("year1_max")) if isinstance(target_path, dict) and target_path.get("year1_max") is not None else None
    attempt_candidates: List[Dict[str, Any]] = []
    attempt_records: List[Dict[str, Any]] = []
    selection_payload = (
      (current_strategy_layer.get("strategy_selection") or {})
      if isinstance(current_strategy_layer.get("strategy_selection"), dict)
      else {}
    )
    profiles = [item for item in _solver_profiles(state_model=state_model) if isinstance(item, dict)]
    primary_profile = _clone(profiles[0]) if profiles else {}
    if primary_profile:
      contract_bundle = _build_profile_solver_contract(
        state_model=state_model,
        direct_inputs=direct_inputs,
        profile=primary_profile,
        target_ebitda_min=target_ebitda_min,
        target_ebitda_max=target_ebitda_max,
      )
      attempted_contract_bundles.append(contract_bundle)
      diagnostics = (contract_bundle.get("diagnostics") or {}) if isinstance(contract_bundle.get("diagnostics"), dict) else {}
      if "invalid_gpt_orchestration" not in set(diagnostics.get("issues") or []):
        candidate = build_controller_finmo_candidate(
          profile=contract_bundle.get("profile") or {},
          contract_bundle=contract_bundle,
          state_model=state_model,
          scenario_index=len(attempted_scenarios) + 1,
        )
        attempt_candidates.append(candidate)
        attempt_records.append(
          {
            "profile": _clone(primary_profile),
            "contract_bundle": contract_bundle,
            "solution": {},
            "candidate": candidate,
          }
        )
    provisional_audit_target: Optional[Dict[str, Any]] = None
    provisional_client_ready = _select_client_ready_scenarios(attempt_candidates, state_model=state_model)
    if provisional_client_ready:
      provisional_id = str((provisional_client_ready[0] or {}).get("scenario_id") or "").strip()
      provisional_audit_target = next((item for item in attempt_records if str((((item.get("candidate") or {}) if isinstance(item.get("candidate"), dict) else {}).get("scenario_id") or "")).strip() == provisional_id), None)
    else:
      provisional_candidates = [
        item for item in _select_materially_distinct_scenarios(
          [
            candidate for candidate in attempt_candidates
            if isinstance(candidate, dict)
            and _safe_int(candidate.get("remaining_blocking_count")) <= 0
          ]
        )
        if isinstance(item, dict)
      ]
      if provisional_candidates:
        provisional_id = str((provisional_candidates[0] or {}).get("scenario_id") or "").strip()
        provisional_audit_target = next((item for item in attempt_records if str((((item.get("candidate") or {}) if isinstance(item.get("candidate"), dict) else {}).get("scenario_id") or "")).strip() == provisional_id), None)
    if provisional_audit_target and str((((provisional_audit_target.get("profile") or {}) if isinstance(provisional_audit_target.get("profile"), dict) else {}).get("strategy_source") or "")).strip().lower() == "gpt":
      contract_bundle = (provisional_audit_target.get("contract_bundle") or {}) if isinstance(provisional_audit_target.get("contract_bundle"), dict) else {}
      translation_payload = _translation_audit_payload(contract_bundle)
      translation_audit = _gpt_translation_audit(
        strategy_selection=selection_payload,
        translated_contract=translation_payload["translated_contract"],
        translated_modified_state=translation_payload["translated_modified_state"],
      )
      diagnostics = (contract_bundle.get("diagnostics") or {}) if isinstance(contract_bundle.get("diagnostics"), dict) else {}
      diagnostics["gpt_translation_audit"] = _clone(translation_audit)
      contract_bundle["diagnostics"] = diagnostics
      candidate_ref = (provisional_audit_target.get("candidate") or {}) if isinstance(provisional_audit_target.get("candidate"), dict) else {}
      if candidate_ref:
        candidate_ref["contract_diagnostics"] = _clone(diagnostics)
        provisional_audit_target["candidate"] = candidate_ref
      if str((translation_audit or {}).get("error") or "").strip():
        diagnostics["issues"] = _unique_strings(list(diagnostics.get("issues") or []) + ["gpt_translation_audit_failed"])
        contract_bundle["diagnostics"] = diagnostics
        old_id = str((((provisional_audit_target.get("candidate") or {}) if isinstance(provisional_audit_target.get("candidate"), dict) else {}).get("scenario_id") or "")).strip()
        attempt_candidates = [item for item in attempt_candidates if str((item.get("scenario_id") or "")).strip() != old_id]
        provisional_audit_target["candidate"] = {}
        continue
      audit_status = str((translation_audit or {}).get("audit_status") or "").strip().lower()
      if audit_status == "rejected_translation":
        corrected_bundle = _build_profile_solver_contract(
          state_model=state_model,
          direct_inputs=direct_inputs,
          profile=(provisional_audit_target.get("profile") or {}) if isinstance(provisional_audit_target.get("profile"), dict) else {},
          target_ebitda_min=target_ebitda_min,
          target_ebitda_max=target_ebitda_max,
          translation_audit=translation_audit,
        )
        corrected_diagnostics = (corrected_bundle.get("diagnostics") or {}) if isinstance(corrected_bundle.get("diagnostics"), dict) else {}
        corrected_diagnostics["gpt_translation_audit_initial"] = _clone(translation_audit)
        corrected_diagnostics["gpt_translation_audit"] = {
          "audit_status": "accepted_gpt_replacement_applied",
          "captured_correctly": True,
          "notes": "Controller applied GPT replacement_forecast_orchestration directly and proceeded with controller validation only.",
        }
        corrected_bundle["diagnostics"] = corrected_diagnostics
        attempted_contract_bundles.append(corrected_bundle)
        corrected_self_audit = (corrected_diagnostics.get("translation_self_audit") or {}) if isinstance(corrected_diagnostics.get("translation_self_audit"), dict) else {}
        if (
          "invalid_gpt_orchestration" in set(corrected_diagnostics.get("issues") or [])
          or bool(corrected_self_audit.get("missing_required_translations"))
          or bool(corrected_self_audit.get("conflicting_roles"))
        ):
          corrected_candidate = None
        else:
          corrected_candidate = build_controller_finmo_candidate(
            profile=corrected_bundle.get("profile") or {},
            contract_bundle=corrected_bundle,
            state_model=state_model,
            scenario_index=_safe_int(((provisional_audit_target.get("candidate") or {}) if isinstance(provisional_audit_target.get("candidate"), dict) else {}).get("scenario_id")),
          )
        if isinstance(corrected_candidate, dict):
          old_candidate = (provisional_audit_target.get("candidate") or {}) if isinstance(provisional_audit_target.get("candidate"), dict) else {}
          old_id = str(old_candidate.get("scenario_id") or "").strip()
          attempt_candidates = [corrected_candidate if str((item.get("scenario_id") or "")).strip() == old_id else item for item in attempt_candidates]
          provisional_audit_target["contract_bundle"] = corrected_bundle
          provisional_audit_target["solution"] = {}
          provisional_audit_target["candidate"] = corrected_candidate
        else:
          corrected_diagnostics["issues"] = _unique_strings(list(corrected_diagnostics.get("issues") or []) + ["gpt_translation_rejected"])
          old_id = str((((provisional_audit_target.get("candidate") or {}) if isinstance(provisional_audit_target.get("candidate"), dict) else {}).get("scenario_id") or "")).strip()
          attempt_candidates = [item for item in attempt_candidates if str((item.get("scenario_id") or "")).strip() != old_id]
          provisional_audit_target["candidate"] = {}
      else:
        provisional_audit_target["contract_bundle"] = contract_bundle
    attempted_scenarios.extend([_clone(item.get("candidate") or {}) for item in attempt_records if isinstance(item.get("candidate"), dict)])
    client_ready = _select_client_ready_scenarios(attempt_candidates, state_model=state_model)
    if client_ready:
      selected = client_ready
      selection_mode = "client_ready"
      break
    retry_feedback = _strategy_retry_feedback(
      strategy_layer=current_strategy_layer,
      attempted_contract_bundles=attempted_contract_bundles,
      attempted_scenarios=attempted_scenarios,
      baseline_summary=baseline_summary,
    )
    retry_attempts.append(
      {
        "attempt_index": attempt_index,
        "attempted_scenario_count": len(attempt_candidates),
        "client_ready_scenario_count": len(client_ready),
        "feedback": retry_feedback,
      }
    )
    if attempt_index >= MAX_GOVERNED_ATTEMPTS:
      break
    current_strategy_layer = _build_strategy_layer(
      state_model=state_model,
      baseline_summary=baseline_summary,
      constraint_engine_state=constraint_engine_state,
      normalized_traits=normalized_traits,
      viability_mode=True,
      baseline_forecast_bundle=baseline_forecast_bundle,
      solver_feedback=retry_feedback,
    )
    if not (current_strategy_layer.get("strategies") or []):
      return _build_blocking_solver_state(
        baseline_summary=baseline_summary,
        baseline_table_markdown=baseline_table_markdown,
        state_model=state_model,
        blocking_reason="gpt_strategy_selection_unavailable",
        blocking_violations=list((constraint_engine_state or {}).get("violations") or []),
        attempted_contract_bundles=attempted_contract_bundles,
        attempted_scenarios=attempted_scenarios,
        governed_attempt_count=attempt_index,
        strategy_retry_attempts=retry_attempts,
      )
  if not selected:
    governed_projection_candidates = [
      item for item in attempted_scenarios
      if isinstance(item, dict)
      and _safe_int(item.get("remaining_blocking_count")) <= 0
      and not {
        "all_negative_five_year_path",
        "degrading_five_year_path",
      }.issubset(set(item.get("presentation_issues") or []))
    ]
    selected = _select_materially_distinct_scenarios(governed_projection_candidates)
    if selected:
      selection_mode = "governed_projection"
  if not selected:
    return _build_blocking_solver_state(
      baseline_summary=baseline_summary,
      baseline_table_markdown=baseline_table_markdown,
      state_model=state_model,
      blocking_reason="no_viable_scenarios",
      blocking_violations=list((constraint_engine_state or {}).get("violations") or []),
      attempted_contract_bundles=attempted_contract_bundles,
      attempted_scenarios=attempted_scenarios,
      governed_attempt_count=MAX_GOVERNED_ATTEMPTS,
      strategy_retry_attempts=retry_attempts,
    )
  return {
    "status": "awaiting_choice",
    "blocking_reason": None,
    "blocking_violations": [],
    "selection_mode": selection_mode,
    "solve_mode": str(state_model.get("solve_mode") or "parent_fallback"),
    "search_mode": "governed",
    "baseline_summary": baseline_summary,
    "baseline_loss_pct": (_safe_float(baseline_summary.get("ebitda")) / max(1.0, _safe_float(baseline_summary.get("revenue")))),
    "baseline_table_markdown": baseline_table_markdown,
    "state_model": state_model,
    "scenarios": selected,
    "client_scenarios": selected if selection_mode == "client_ready" else [],
    "attempted_scenarios": attempted_scenarios,
    "attempted_contract_bundles": attempted_contract_bundles,
    "governed_attempt_count": MAX_GOVERNED_ATTEMPTS if retry_attempts else 1,
    "strategy_retry_attempts": retry_attempts,
    "selected_target_label": selected_target_label,
    "selected_target_ebitda_min": target_ebitda_min,
    "selected_target_ebitda_max": target_ebitda_max,
    "structural_gap": _safe_float(baseline_summary.get("ebitda")),
  }


def apply_consistency_solver_choice(
  *,
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  solver_state: Dict[str, Any],
  selected_scenario_id: str,
  overrides: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  del overrides
  scenarios = [item for item in (solver_state.get("scenarios") or []) if isinstance(item, dict)]
  selected = next((item for item in scenarios if str(item.get("scenario_id") or "") == str(selected_scenario_id or "")), None)
  if not isinstance(selected, dict):
    return None
  modified_state = selected.get("modified_state") if isinstance(selected.get("modified_state"), dict) else {}
  if modified_state:
    return {
      "ops_json": _clone(modified_state.get("ops_json") or ops_json),
      "people_json": _clone(modified_state.get("people_json") or people_json),
      "financials_json": _clone(modified_state.get("financials_json") or financials_json),
      "financials_year1_json": _clone(modified_state.get("financials_year1_json") or financials_year1_json),
      "marketing_model_json": _clone(modified_state.get("marketing_model_json") or marketing_model_json),
      "scenario": selected,
      "exact_patches": _clone(selected.get("exact_patches") or {}),
    }
  next_ops, next_people, next_financials, next_year1, next_marketing = _apply_exact_patches(
    ops_json=ops_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    marketing_model_json=marketing_model_json,
    exact_patches=_clone(selected.get("exact_patches") or {}),
  )
  return {
    "ops_json": next_ops,
    "people_json": next_people,
    "financials_json": next_financials,
    "financials_year1_json": next_year1,
    "marketing_model_json": next_marketing,
    "scenario": selected,
    "exact_patches": _clone(selected.get("exact_patches") or {}),
  }


__all__ = [
  "_apply_exact_patches",
  "_archetype_consistency",
  "_build_client_scenario_output",
  "_build_direct_solver_inputs",
  "_build_governed_rescue_scenarios",
  "_build_lever_summary",
  "_build_profile_solver_contract",
  "_build_scenario_forecast_bundle",
  "_build_solver_state_model",
  "_controller_enforced_profile",
  "_derive_commercial_archetype",
  "_derive_scenario_posture",
  "_exact_patches_from_solution",
  "_gpt_blueprint_is_usable",
  "_gpt_strategy_required",
  "_gpt_strategy_selection",
  "_label_and_rationale_from_patches",
  "_normalize_ratio",
  "_normalized_plan_entry_families",
  "_package_expected_effects",
  "_presentation_issues",
  "_safe_float",
  "_select_best_effort_governed_scenarios",
  "_select_client_ready_scenarios",
  "_select_materially_distinct_scenarios",
  "_solver_profiles",
  "_solver_required",
  "_sync_marketing_derived_fields",
  "apply_consistency_solver_choice",
  "build_consistency_solver_state",
]
