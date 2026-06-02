"""Phase 9 P3.26 Commit 2 — payroll feasibility repair routing.

When the post-grid or finalize global feasibility checks fire
`payroll_revenue_economic_feasibility_failed`, this module routes
the failure back to Handler C (`estimate_payroll_headcount_schedule_with_gpt`)
with the feasibility context as `previous_contract_failure`
feedback. Handler C is canonical for payroll dollars per doctrine
§6; re-authoring through it preserves Mirror Flavor 1 alignment
across all four payroll surfaces (payroll_headcount.quarter_totals,
model_input.expenses.Payroll, finmo.pl.Payroll,
finmo.quarter_rows.payroll).

The apply chain that runs after Handler C returns (capacity →
headcount → finmo rebuild) writes all four surfaces from the
same canonical schedule, and the existing assertions
(`assert_payroll_headcount_model_input_applied` +
`assert_finmo_payroll_matches_headcount_schedule`) enforce the
alignment with zero tolerance.

DO NOT extend this module to author payroll outside Handler C.
DO NOT expand any other handler's authority over expenses::Payroll.
The architectural contract: Handler C is the single writer.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Tuple

from client_intake_and_finmo.finmo_bridge import (  # type: ignore
  apply_derived_driver_policies_to_model_input,
  build_python_finmo_json,
)
from client_intake_and_finmo.post_intake_headcount.schedule import (
  apply_payroll_headcount_payload_to_model_input,
  apply_payroll_supported_capacity_to_model_input,
  assert_finmo_payroll_matches_headcount_schedule,
  assert_payroll_headcount_model_input_applied,
  author_round1_payroll_contract,
  build_payroll_headcount_payload_from_contract,
  validate_payroll_headcount_contract_payload,
)
from client_intake_and_finmo.post_intake_sequence import (  # type: ignore
  post_intake_sequence_step_scope,
)


def _previous_contract_failure_payload(
  *, error_code: str, message: str, stage: str, details: Dict[str, Any], source: str,
) -> Dict[str, Any]:
  return {
    "error": str(message or "")[:6000],
    "error_code": str(error_code or ""),
    "stage": str(stage or ""),
    "details": copy.deepcopy(details or {}),
    "source": str(source or "payroll_feasibility_repair"),
  }


def apply_payroll_schedule_to_state(
  *,
  schedule_payload: Dict[str, Any],
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  live_count: int,
  stage_prefix: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
  """Re-apply a payroll headcount schedule to model_input + rebuild
  finmo. Mirror Flavor 1 enforcement: assertions verify
  model_input.expenses.Payroll == headcount.quarter_totals and
  finmo Payroll == headcount.quarter_totals before returning.

  P3.26 fix2: wrapped in a sequence_step_scope so downstream
  helpers (apply_payroll_supported_capacity_to_model_input,
  apply_payroll_headcount_payload_to_model_input, etc.) that gate
  on assert_post_intake_sequence_controller_active can run.
  """
  with post_intake_sequence_step_scope(
    step_key="payroll_feasibility_repair_apply",
    phase="post_intake_target_seeking",
    executor_function="apply_payroll_headcount_payload_to_model_input",
    step_kind="orchestration",
  ):
    capacity_mi = apply_payroll_supported_capacity_to_model_input(
      copy.deepcopy(model_input_json or {}),
      copy.deepcopy(schedule_payload or {}),
      live_count=live_count,
    )
    next_mi = apply_payroll_headcount_payload_to_model_input(
      copy.deepcopy(capacity_mi),
      copy.deepcopy(schedule_payload or {}),
      live_count=live_count,
    )
    next_mi = apply_derived_driver_policies_to_model_input(copy.deepcopy(next_mi))
    assert_payroll_headcount_model_input_applied(
      copy.deepcopy(next_mi),
      copy.deepcopy(schedule_payload or {}),
      stage=f"{stage_prefix}_model_input",
    )
    next_finmo = build_python_finmo_json(model_input_json=copy.deepcopy(next_mi))
    assert_finmo_payroll_matches_headcount_schedule(
      copy.deepcopy(next_finmo),
      copy.deepcopy(schedule_payload or {}),
      stage=f"{stage_prefix}_finmo",
    )
  return next_mi, next_finmo


def _recompute_payroll_via_dollar_path(
  *,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  stage_ramp_contract: Dict[str, Any],
  draft_id: str,
  client_id: str,
) -> Dict[str, Any]:
  """OQ-1 repair lever (payroll_producer_spec.md Part E.3 / Part I): on a
  payroll/revenue feasibility failure, re-run the DETERMINISTIC DOLLAR PATH
  (author_round1_payroll_contract: revenue x band-midpoint -> budget -> FTE)
  against the CURRENT post-quarter-grid revenue the feasibility check uses --
  NOT round-1 revenue. capacity_units_per_supporting_fte is never the lever
  (Part E broke that loop); capacity stays the revenue anchor.

  Authors a fresh contract, validates it, and builds the payload via the same
  canonical validator + builder the round-1 path uses. The model_input_json /
  finmo_json passed in are the post-quarter-grid state (the callers pass
  applied_/final_ model_input + finmo), so author_round1 reads finmo_revenue
  from the reshaped revenue.
  """
  contract = author_round1_payroll_contract(
    business_facts=copy.deepcopy(business_facts or {}),
    ops_json=copy.deepcopy(ops_json or {}),
    people_json=copy.deepcopy(people_json or {}),
    financials_json=copy.deepcopy(financials_json or {}),
    financials_year1_json=copy.deepcopy(financials_year1_json or {}),
    model_input_json=copy.deepcopy(model_input_json or {}),
    finmo_json=copy.deepcopy(finmo_json or {}),
    stage_ramp_contract=copy.deepcopy(stage_ramp_contract or {}),
  )
  normalized = validate_payroll_headcount_contract_payload(payload=contract)
  return build_payroll_headcount_payload_from_contract(
    normalized,
    draft_id=str(draft_id or "").strip(),
    client_id=str(client_id or "").strip(),
    model_input_json=copy.deepcopy(model_input_json or {}),
    business_facts=copy.deepcopy(business_facts or {}),
    ops_json=copy.deepcopy(ops_json or {}),
    people_json=copy.deepcopy(people_json or {}),
  )


def route_payroll_feasibility_to_handler_c(
  *,
  failure_code: str,
  failure_message: str,
  failure_stage: str,
  failure_details: Dict[str, Any],
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  planning_mode: str,
  planning_mode_reason: str,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  payroll_headcount: Dict[str, Any],
  stage_ramp_contract: Dict[str, Any],
  draft_id: str,
  client_id: str,
  live_count: int,
  stage_prefix: str,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
  """Routing for payroll feasibility failures.

  OQ-1 (payroll_producer_spec.md Part E.3 / Part I): the repair lever is the
  DETERMINISTIC DOLLAR PATH, not the deleted GPT loop. On a payroll/revenue
  feasibility failure this re-runs author_round1_payroll_contract against the
  POST-quarter-grid revenue (passed in as model_input_json / finmo_json), then
  validates + builds via the canonical chain and re-applies, writing all four
  payroll surfaces from the same source. Returns (schedule_payload,
  model_input_json, finmo_json).

  (Name retained for the existing call sites in the initial-grid runner and the
  solver orchestrator; it no longer routes to Handler C / GPT.
  planning_mode / planning_mode_reason are kept for signature stability.)

  This is the SINGLE writer entry-point for payroll feasibility repair across
  the pipeline. Callers must NOT bypass it with ad-hoc payroll authoring.
  """
  previous_contract_failure = _previous_contract_failure_payload(
    error_code=failure_code,
    message=failure_message,
    stage=failure_stage,
    details=failure_details,
    source="payroll_feasibility_repair",
  )
  # P3.26 fix2: Handler C's downstream helpers gate themselves on
  # `assert_post_intake_sequence_controller_active`. Without a
  # registered scope, the helpers raise
  # `post_intake_sequence_controller_required`. The
  # `payroll_feasibility_repair` scope identifies this routing as
  # an orchestration-level Handler C re-author (the same step_key
  # the SQL `post_intake_process_sequence_lookup` table reserves
  # for the canonical feasibility-repair process at
  # initial_grid:65).
  # OQ-1 wiring: the repair lever is the DOLLAR PATH, not the deleted GPT loop.
  # estimate_payroll_headcount_schedule_with_gpt is a dead stub (its tool-calling
  # loop was removed) -- routing to it returned build_pending_payroll_stub, whose
  # empty enums + diagnostic text then failed validation. Re-run the deterministic
  # producer against the post-quarter-grid revenue instead. previous_contract_failure
  # is retained for diagnostics/trace; it is NOT injected into the payload (that
  # diagnostic block is exactly what broke the stub's validation).
  del previous_contract_failure  # diagnostics-only; not threaded into the payload
  with post_intake_sequence_step_scope(
    step_key="payroll_feasibility_repair",
    phase="post_intake_target_seeking",
    executor_function="retry_payroll_headcount_schedule_from_feasibility_failure",
    step_kind="orchestration",
  ):
    new_schedule = _recompute_payroll_via_dollar_path(
      business_facts=business_facts,
      ops_json=ops_json,
      people_json=people_json,
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
      model_input_json=model_input_json,
      finmo_json=finmo_json,
      stage_ramp_contract=stage_ramp_contract,
      draft_id=draft_id,
      client_id=client_id,
    )
  new_mi, new_finmo = apply_payroll_schedule_to_state(
    schedule_payload=new_schedule,
    model_input_json=model_input_json,
    finmo_json=finmo_json,
    live_count=live_count,
    stage_prefix=stage_prefix,
  )
  return new_schedule, new_mi, new_finmo


def is_payroll_feasibility_failure(failure: Any) -> bool:
  """True when a failure represents a payroll feasibility
  violation routable to Handler C.

  Three exception shapes can carry the failure:
    1. Direct FailFastError with the feasibility code (Site A
       catches this from _assert_global_invariants_via_sequence).
    2. FailFastError with `post_intake_schedule_marker_missing`
       wrapper code carrying the inner code in `details.exception`.
    3. RuntimeError raised by finalize's `_raise_if_errors`
       (finalize_post_intake.py:39-44) which CONCATENATES the
       FailFastError text into a "post_intake_finalize_validation_failed: ..."
       message. Site B receives this shape; we detect it by
       inspecting str(failure) for the inner feasibility code.
  """
  code = str(getattr(failure, "code", "") or "")
  if code in {
    "payroll_revenue_economic_feasibility_failed",
    "payroll_stage_profitability_feasibility_failed",
  }:
    return True
  if code == "post_intake_schedule_marker_missing":
    inner = str((getattr(failure, "details", {}) or {}).get("exception") or "")
    if (
      "payroll_revenue_economic_feasibility_failed" in inner
      or "payroll_stage_profitability_feasibility_failed" in inner
    ):
      return True
  # Shape 3: finalize's _raise_if_errors wraps the FailFastError
  # diagnostic text in a generic RuntimeError. Inspect str(failure)
  # for the inner code.
  msg = str(failure or "")
  if (
    "payroll_revenue_economic_feasibility_failed" in msg
    or "payroll_stage_profitability_feasibility_failed" in msg
  ):
    return True
  return False
