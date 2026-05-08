"""Phase 8 — legacy-bound-name compatibility shims.

The deleted post_intake_issues runner exported ~130 underscore-prefixed
helpers via __all__ and bind injection. This module provides
shape-stable replacements under the same names so consumers (cash,
contracts, convergence runner, runtime, state runner) compile and load
without an avalanche of NameErrors.

Design intent (NOT a hidden re-implementation of issue machinery):
  - Functions that built collections from an issue ledger now return
    empty collections. The new authority is the realism gate and the
    cascade — both consulted directly elsewhere.
  - Functions that classified issue codes now use a small whitelist
    (cash_pass-owned ratios) for the only filter that actually matters
    downstream; everything else returns False / empty.
  - Functions that built prompt-context packets now return empty
    packets. The convergence runner's GPT-driven planning loop is
    being deprecated by the cascade; until the runner rewrite removes
    these callsites, the empty packets keep the pipeline loadable.

If you find yourself adding logic here, that logic belongs in
state.py (the new architecture) or the convergence runner rewrite.
This file is a compatibility surface, not a destination.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from client_intake_and_finmo.post_intake_resolution_state.state import (  # type: ignore
  build_controller_resolution_state,
  build_persisted_realism_memo_payload,
  build_realism_memo,
  build_resolution_summary,
  empty_controller_resolution_state,
  empty_realism_memo,
  empty_resolution_summary,
  filter_cash_pass_owned_issue_records,
  financial_story_issue_codes,
  issue_status_records_from_state,
)


# ---------------------------------------------------------------------------
# Top-level legacy wrappers — the high-traffic ones called from cash /
# contracts / convergence runner / runtime / state runner.
# ---------------------------------------------------------------------------


def _build_controller_resolution_state_from_issue_ledger(
  *args: Any, **kwargs: Any
) -> Dict[str, Any]:
  """Legacy: built controller_resolution_state from an issue ledger.
  Phase 8: builds it from realism_gate_payload + cascade_diagnostics
  when present; empty defaults otherwise. Old callsites pass an issue
  ledger as positional; we ignore it and look for new-architecture
  payloads under known kwarg names."""
  return build_controller_resolution_state(
    realism_gate_payload=kwargs.get("realism_gate_payload"),
    cascade_diagnostics=kwargs.get("cascade_diagnostics"),
    planning_mode_policy=kwargs.get("planning_mode_policy"),
  )


def _build_realism_memo_from_issue_ledger(
  *args: Any, **kwargs: Any
) -> Dict[str, Any]:
  return build_realism_memo(
    realism_gate_payload=kwargs.get("realism_gate_payload"),
    schedule_sanity_payload=kwargs.get("schedule_sanity_payload"),
    warnings=kwargs.get("warnings"),
  )


def _build_resolution_summary_from_issue_ledger(
  *args: Any, **kwargs: Any
) -> Dict[str, Any]:
  return build_resolution_summary(
    realism_gate_payload=kwargs.get("realism_gate_payload"),
    cascade_diagnostics=kwargs.get("cascade_diagnostics"),
  )


def _build_persisted_realism_memo_payload(
  *args: Any, **kwargs: Any
) -> Dict[str, Any]:
  return build_persisted_realism_memo_payload(
    controller_resolution_state=kwargs.get("controller_resolution_state"),
    working_memo=kwargs.get("working_memo"),
  )


def _controller_state_issue_status_records(
  state: Optional[Dict[str, Any]] = None, *args: Any, **kwargs: Any
) -> List[Dict[str, Any]]:
  return issue_status_records_from_state(state)


def _financial_story_issue_codes(
  controller_resolution_state: Optional[Dict[str, Any]] = None,
  *args: Any,
  **kwargs: Any,
) -> List[str]:
  return financial_story_issue_codes(controller_resolution_state)


def _filter_cash_pass_owned_issue_records(
  records: Optional[List[Dict[str, Any]]] = None, *args: Any, **kwargs: Any
) -> List[Dict[str, Any]]:
  return filter_cash_pass_owned_issue_records(records)


def _apply_realism_verification_to_issue_status_records(
  *args: Any, **kwargs: Any
) -> List[Dict[str, Any]]:
  """Legacy: merged realism verification verdicts into issue ledger.
  Phase 8: the realism gate is queried directly; this returns the
  records unchanged (or empty when not provided)."""
  if args and isinstance(args[0], list):
    return list(args[0])
  records = kwargs.get("issue_status_records") or kwargs.get("records") or []
  return list(records) if isinstance(records, list) else []


def _merge_new_scan_detected_issues(
  *args: Any, **kwargs: Any
) -> List[Dict[str, Any]]:
  if args and isinstance(args[0], list):
    return list(args[0])
  ledger = kwargs.get("ledger") or kwargs.get("issue_ledger") or []
  return list(ledger) if isinstance(ledger, list) else []


# ---------------------------------------------------------------------------
# All other legacy names — empty/identity defaults. The convergence runner
# rewrite removes the callsites that consume these. Until then, these
# stubs keep the modules loadable.
# ---------------------------------------------------------------------------


def _empty_dict(*args: Any, **kwargs: Any) -> Dict[str, Any]:
  return {}


def _empty_list(*args: Any, **kwargs: Any) -> List[Any]:
  return []


def _zero(*args: Any, **kwargs: Any) -> float:
  return 0.0


def _zero_int(*args: Any, **kwargs: Any) -> int:
  return 0


def _identity_first(*args: Any, **kwargs: Any) -> Any:
  if args:
    return args[0]
  return None


def _none(*args: Any, **kwargs: Any) -> None:
  return None


def _false(*args: Any, **kwargs: Any) -> bool:
  return False


def _true(*args: Any, **kwargs: Any) -> bool:
  return True


def _empty_tuple(*args: Any, **kwargs: Any) -> tuple:
  return ()


def _empty_set(*args: Any, **kwargs: Any) -> set:
  return set()


def _identity_dict(*args: Any, **kwargs: Any) -> Dict[str, Any]:
  if args and isinstance(args[0], dict):
    return copy.deepcopy(args[0])
  return {}


def _identity_list(*args: Any, **kwargs: Any) -> List[Any]:
  if args and isinstance(args[0], list):
    return copy.deepcopy(args[0])
  return []


# Aliases. The legacy machinery had specialized signatures; we collapse
# them all to the empty-collection / identity stubs above. Each alias
# documents what the legacy function nominally did.

# Snapshot / record builders.
_synthetic_controller_issue_completion_snapshot = _empty_dict
_normalize_issue_record_to_controller_truth = _identity_dict
_refresh_issue_status_records_from_scan = _identity_list
_clone_issue_status_records = _identity_list

# Realism planner state (only consulted by deprecated GPT planning).
_build_realism_planner_issue_state = _empty_dict
_active_issue_codes_from_planner_issue_state = _empty_list

# Trace compaction (telemetry only).
_compact_realism_memo_for_trace = _identity_dict
_compact_resolution_summary_for_trace = _identity_dict
_compact_issue_codes = _empty_list
_sanitize_realism_iteration_trace = _identity_list

# Issue-key extraction.
_issue_keys_from_status_records = _empty_list
_issue_keys_requiring_iteration = _empty_list
_filter_issue_status_records = _identity_list

# Status / blocking checks.
_controller_issue_effective_status = _none
_controller_issue_is_blocking = _false
_issue_needs_iteration = _false
_iteration_decision_from_issue_record = _empty_dict
_controller_resolution_from_verification_issue = _empty_dict

# Issue-code recognition.
_is_known_post_intake_issue_code = _false
_canonical_issue_title = _none

# Realism normalization (vestigial — the realism gate writes its own
# normalized fields directly).
_normalize_realism_verifier_status = _none
_normalize_realism_materiality = _none
_normalize_realism_remaining_quarters = _empty_list
_normalize_realism_lever_ids = _empty_list

# Issue-scope predicates.
_issue_requires_remaining_horizon_scope = _false
_is_cash_pass_owned_issue_code = _false
_remaining_horizon_issue_quarters = _empty_list
_issue_is_hard_issue = _false

# Snapshot / public record builders.
_controller_issue_completion_snapshot = _empty_dict
_controller_issue_public_record = _empty_dict
_build_controller_issue_grade_summary = _empty_dict
_convergence_completion_policy_payload = _empty_dict

# Metric / lever heuristics (vestigial — the realism gate + influence
# map cover these now).
_metric_direction_hint = _none
_severity_minimum_change_pct = _zero
_deterministic_lever_bound_value = _none
_metric_equilibrium_target = _none
_metric_target_zone = _empty_dict
_issue_impact_weight = _zero
_issue_priority_map = _empty_dict

# Prompt context builders (deprecated GPT path).
_compact_model_input_for_verification = _empty_dict
_build_realism_pass_consistency_context_payload = _empty_dict
_compact_current_cycle_packet_for_prompt = _empty_dict
_compact_issue_packets_for_prompt = _empty_list
_build_unified_numeric_guidance_packet = _empty_dict

# Strategy / context.
_build_strategy_resolved_issue_constraints = _empty_dict
_build_strategy_recheck_context_payload = _empty_dict

# Result-side helpers.
_touched_lever_ids_from_result = _empty_list
_touched_issue_codes_from_result = _empty_list
_normalized_issue_records = _empty_list

# Identity helpers.
_issue_ledger_key = _none
_core_issue_record = _empty_dict
_merge_issue_identity_fields = _identity_dict

# Misc.
_safe_int_in_range = _none
_completion_grade_letter = _none
_safe_divide = _none
_quarter_phase_label = _none
_issue_detail_blob = _empty_dict
_zone_repair_geometry = _empty_dict
_build_issue_metric_spec = _empty_dict
_table_target_currency_metric_spec = _empty_dict
_table_target_metric_id_set = _empty_set
_is_table_target_metric_name = _false
_cost_structure_direct_metric_specs_for_quarter = _empty_list
_issue_metric_specs_for_quarter = _empty_list
_issue_metric_specs_for_record = _empty_list
_issue_registry_entry = _empty_dict

# Lever / driver helpers.
_lever_catalog_entry_text = _none
_lever_catalog_entry_matches = _false
_repair_path_type_for_lever = _none
_driver_path_delta_bounds = _empty_dict
_repair_metric_delta_bounds = _empty_dict
_quarter_days_in_period = _zero
_quarter_row_cost_of_goods_sold = _zero
_quarter_row_operating_cost_base = _zero
_component_delta_to_lever_delta = _zero
_driver_target_conversion_context = _empty_dict
_metric_target_bounds_constrained_by_driver_scaffold = _empty_dict
_spillover_flags_for_metric = _empty_list

# Convergence-side helpers.
_build_convergence_scorecard = _empty_dict
_repair_aware_issue_packets = _empty_list
_sample_evenly_spaced_entries = _empty_list
_driver_path_sort_key = _zero
_select_focus_driver_paths = _empty_list
_compact_driver_paths_for_prompt = _empty_list
_compact_repair_targets_for_prompt = _empty_list
_compact_repair_envelope_packets_for_prompt = _empty_list
_compact_numeric_guidance_for_prompt = _empty_dict
_unified_target_fill_grid = _empty_dict
_locked_targets_by_quarter_response_template = _empty_dict
_unified_lever_control_fill_grid = _empty_dict
_full_horizon_model_input_repair_contract = _empty_dict
_model_input_repair_cell_schema = _empty_dict
_normalize_model_input_repair_cell_value = _none
_validate_and_normalize_model_input_repair_cells = _empty_list
_exact_updates_from_model_input_repair_cells = _empty_list
_convergence_issue_mapping_gate = _none
_lever_priority_tier = _zero_int
_ordered_quarters_by_preference = _empty_list
_build_deterministic_issue_packets = _empty_list
_build_issue_packets_from_issue_ledger = _empty_list

# Numeric solver contract helpers.
_numeric_solver_contract_issue_packet_map = _empty_dict
_numeric_solver_contract_baseline_quarter_map = _empty_dict
_numeric_adjust_actions_contract_error = _none
_normalize_unified_mapped_repair_targets = _empty_list
_declared_mapped_target_metric_names = _empty_list
_repair_target_direct_target_metric_names = _empty_list
_merge_required_target_tolerances = _empty_dict
_augment_solver_quarter_target_metrics = _empty_dict
_issue_packet_mapped_driver_lever_ids = _empty_list
_deterministic_guidance_focus_issue_codes = _empty_list
_issue_packet_declared_target_metric_names = _empty_list
_table_issue_candidate_lever_ids = _empty_list

# P&L flatline detection.
_raise_p_and_l_flatline_if_needed = _none
_p_and_l_flatline_signals = _empty_list
_build_p_and_l_flatline_issue_status_records = _empty_list

# Capacity / cost-structure issue records.
_build_capacity_support_issue_status_records = _empty_list
_build_stage_maturity_cost_structure_issue_status_records = _empty_list
