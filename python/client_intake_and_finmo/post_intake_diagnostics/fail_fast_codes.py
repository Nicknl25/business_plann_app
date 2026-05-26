"""P3.33 Phase 3 step 9d — closed enum of fail-fast codes.

A *fail-fast point* is a structural invariant in the post-intake
pipeline that, when violated, must STOP the pipeline with a re-raised
structured RuntimeError rather than silently degrade. The doctrine
(item D from the step-8 design discussion) is:

  1. Best-effort audit row via ``safe_emit`` — observability never
     crashes the pipeline, so this is wrapped to swallow.
  2. ALWAYS re-raise. The RuntimeError message is prefixed
     ``post_intake_fail_fast::<code>`` so tests and upstream handlers
     can parse it.

The 24 codes below cover every fail-fast point catalogued in
``docs/architecture/p3_33_phase35_fail_fast_inventory.md`` after the
post-review corrections (item 13 — FLOOR_BUDGET — was dropped on
review because the §9.2 floor primitives do not loop). They are
partitioned by ``PhaseCode`` via ``FAIL_FAST_CODES_BY_PHASE`` in the
same shape as ``EVENT_CODES_BY_PHASE`` so the diagnostic stream stays
queryable along the same axes.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, FrozenSet

from client_intake_and_finmo.post_intake_diagnostics.phase_codes import (
  PhaseCode,
)


class FailFastCode(str, Enum):
  # cohort_bands_populator
  FAIL_COHORT_BANDS_MISSING              = "fail_cohort_bands_missing"
  FAIL_COHORT_BANDS_MALFORMED            = "fail_cohort_bands_malformed"

  # mirror_build
  FAIL_MIRROR_PLAN_STATE_NOT_DICT        = "fail_mirror_plan_state_not_dict"
  FAIL_MIRROR_BANDS_UNRESOLVED           = "fail_mirror_bands_unresolved"
  FAIL_MIRROR_FINMO_BASELINE_BUILD       = "fail_mirror_finmo_baseline_build"

  # round1_authoring
  FAIL_ROUND1_SET_TOOL_REJECTED          = "fail_round1_set_tool_rejected"
  FAIL_ROUND1_PLAN_STATE_INCOMPLETE      = "fail_round1_plan_state_incomplete"

  # evaluate_plan
  FAIL_EVALUATE_PLAN_EXCEPTION           = "fail_evaluate_plan_exception"
  FAIL_EVALUATE_PLAN_MALFORMED           = "fail_evaluate_plan_malformed"

  # cascade_walk
  FAIL_CASCADE_MODE_UNKNOWN              = "fail_cascade_mode_unknown"
  FAIL_CASCADE_TIER_UNKNOWN              = "fail_cascade_tier_unknown"
  FAIL_CASCADE_HALTED_WITHOUT_RESOLUTION = "fail_cascade_halted_without_resolution"

  # floor_invocation — primitives are one-shot, so no budget code.
  FAIL_FLOOR_PRIMITIVE_FAILED            = "fail_floor_primitive_failed"

  # session_terminated
  FAIL_SESSION_TERMINAL_STATE_UNKNOWN    = "fail_session_terminal_state_unknown"

  # finmo_sync
  FAIL_FINMO_NO_QUARTER_ROWS             = "fail_finmo_no_quarter_rows"
  FAIL_FINMO_SCHEMA_MISSING              = "fail_finmo_schema_missing"

  # target_seeking
  FAIL_TARGET_SEEKING_MODE_UNKNOWN       = "fail_target_seeking_mode_unknown"
  FAIL_TARGET_SEEKING_REASON_UNKNOWN     = "fail_target_seeking_reason_unknown"

  # cash_pass
  FAIL_CASH_PASS_RESULT_MALFORMED        = "fail_cash_pass_result_malformed"

  # realism_gate
  FAIL_REALISM_BAND_SOURCE_MISSING       = "fail_realism_band_source_missing"
  FAIL_REALISM_COUNT_MISMATCH            = "fail_realism_count_mismatch"

  # finalize
  FAIL_FINALIZE_STAGE_NOT_FINALIZED      = "fail_finalize_stage_not_finalized"

  # workbook_accept
  FAIL_WORKBOOK_ACCEPT_NO_RUN_ID         = "fail_workbook_accept_no_run_id"
  FAIL_WORKBOOK_ACCEPT_NO_DRAFT_ID       = "fail_workbook_accept_no_draft_id"

  # model_input_contract (P3.40 Contract 1 boundary enforcement)
  FAIL_MODEL_INPUT_CONTRACT_VIOLATION    = "fail_model_input_contract_violation"

  # solver_input_contract (P3.40 Contract 3 boundary enforcement)
  FAIL_SOLVER_INPUT_CONTRACT_VIOLATION   = "fail_solver_input_contract_violation"


FAIL_FAST_CODES_BY_PHASE: Dict[PhaseCode, FrozenSet[FailFastCode]] = {
  PhaseCode.COHORT_BANDS_POPULATOR: frozenset({
    FailFastCode.FAIL_COHORT_BANDS_MISSING,
    FailFastCode.FAIL_COHORT_BANDS_MALFORMED,
  }),
  PhaseCode.MIRROR_BUILD: frozenset({
    FailFastCode.FAIL_MIRROR_PLAN_STATE_NOT_DICT,
    FailFastCode.FAIL_MIRROR_BANDS_UNRESOLVED,
    FailFastCode.FAIL_MIRROR_FINMO_BASELINE_BUILD,
  }),
  PhaseCode.ROUND1_AUTHORING: frozenset({
    FailFastCode.FAIL_ROUND1_SET_TOOL_REJECTED,
    FailFastCode.FAIL_ROUND1_PLAN_STATE_INCOMPLETE,
  }),
  PhaseCode.EVALUATE_PLAN: frozenset({
    FailFastCode.FAIL_EVALUATE_PLAN_EXCEPTION,
    FailFastCode.FAIL_EVALUATE_PLAN_MALFORMED,
  }),
  PhaseCode.CASCADE_WALK: frozenset({
    FailFastCode.FAIL_CASCADE_MODE_UNKNOWN,
    FailFastCode.FAIL_CASCADE_TIER_UNKNOWN,
    FailFastCode.FAIL_CASCADE_HALTED_WITHOUT_RESOLUTION,
  }),
  PhaseCode.FLOOR_INVOCATION: frozenset({
    FailFastCode.FAIL_FLOOR_PRIMITIVE_FAILED,
  }),
  PhaseCode.SESSION_TERMINATED: frozenset({
    FailFastCode.FAIL_SESSION_TERMINAL_STATE_UNKNOWN,
  }),
  PhaseCode.FINMO_SYNC: frozenset({
    FailFastCode.FAIL_FINMO_NO_QUARTER_ROWS,
    FailFastCode.FAIL_FINMO_SCHEMA_MISSING,
  }),
  PhaseCode.TARGET_SEEKING: frozenset({
    FailFastCode.FAIL_TARGET_SEEKING_MODE_UNKNOWN,
    FailFastCode.FAIL_TARGET_SEEKING_REASON_UNKNOWN,
  }),
  PhaseCode.CASH_PASS: frozenset({
    FailFastCode.FAIL_CASH_PASS_RESULT_MALFORMED,
  }),
  PhaseCode.REALISM_GATE: frozenset({
    FailFastCode.FAIL_REALISM_BAND_SOURCE_MISSING,
    FailFastCode.FAIL_REALISM_COUNT_MISMATCH,
  }),
  PhaseCode.FINALIZE: frozenset({
    FailFastCode.FAIL_FINALIZE_STAGE_NOT_FINALIZED,
  }),
  PhaseCode.WORKBOOK_ACCEPT: frozenset({
    FailFastCode.FAIL_WORKBOOK_ACCEPT_NO_RUN_ID,
    FailFastCode.FAIL_WORKBOOK_ACCEPT_NO_DRAFT_ID,
  }),
  PhaseCode.MODEL_INPUT_CONTRACT: frozenset({
    FailFastCode.FAIL_MODEL_INPUT_CONTRACT_VIOLATION,
  }),
  PhaseCode.SOLVER_INPUT_CONTRACT: frozenset({
    FailFastCode.FAIL_SOLVER_INPUT_CONTRACT_VIOLATION,
  }),
}


def fail_fast_code_belongs_to_phase(
  code: FailFastCode, phase: PhaseCode,
) -> bool:
  allowed = FAIL_FAST_CODES_BY_PHASE.get(phase)
  return code in allowed if allowed is not None else False


FAIL_FAST_PREFIX = "post_intake_fail_fast::"


def raise_fail_fast(
  conn,
  *,
  draft_id: str,
  planning_run_id: str,
  phase: PhaseCode,
  code: FailFastCode,
  detail: str,
  where: str = "",
  cause: BaseException = None,
):
  """Emit a best-effort audit row to post_intake_run_diagnostics, then
  ALWAYS raise a structured RuntimeError. The audit row is emitted
  through ``safe_emit`` so failure to write it (e.g. table missing in
  a hermetic test) never masks the original fault.

  The RuntimeError message format is::

    post_intake_fail_fast::<code_value>: <detail>

  Upstream handlers / tests detect a fail-fast halt by checking the
  ``post_intake_fail_fast::`` prefix.
  """
  if not fail_fast_code_belongs_to_phase(code, phase):
    raise ValueError(
      f"fail_fast_code_phase_mismatch: code={code.value!r} "
      f"not registered for phase={phase.value!r}"
    )

  from client_intake_and_finmo.post_intake_diagnostics import (
    EventCode, Status, safe_emit,
  )
  # Map phase -> the *_FAILED EventCode for the audit row. Several
  # phases ship a check_failed or *_failed event; pick the most
  # specific one available.
  failed_event = {
    PhaseCode.COHORT_BANDS_POPULATOR: EventCode.COHORT_BANDS_FAILED,
    PhaseCode.MIRROR_BUILD: EventCode.MIRROR_BUILD_NO_BANDS,
    PhaseCode.ROUND1_AUTHORING: EventCode.ROUND1_COMPLETED,
    PhaseCode.EVALUATE_PLAN: EventCode.EVALUATE_PLAN_FAILURES_DETECTED,
    PhaseCode.CASCADE_WALK: EventCode.CASCADE_EXHAUSTED,
    PhaseCode.FLOOR_INVOCATION: EventCode.FLOOR_COMPLETED,
    PhaseCode.SESSION_TERMINATED: EventCode.SESSION_EXCEPTION_HALTED,
    PhaseCode.FINMO_SYNC: EventCode.FINMO_SYNC_FAILED,
    PhaseCode.TARGET_SEEKING: EventCode.TARGET_SEEKING_COMPLETED,
    PhaseCode.CASH_PASS: EventCode.CASH_PASS_COMPLETED,
    PhaseCode.REALISM_GATE: EventCode.REALISM_GATE_CHECK_FAILED,
    PhaseCode.FINALIZE: EventCode.FINALIZE_VALIDATION_FAILED,
    PhaseCode.WORKBOOK_ACCEPT: EventCode.WORKBOOK_ACCEPT_REJECTED,
    PhaseCode.MODEL_INPUT_CONTRACT: EventCode.MODEL_INPUT_CONTRACT_VIOLATION,
    PhaseCode.SOLVER_INPUT_CONTRACT: EventCode.SOLVER_INPUT_CONTRACT_VIOLATION,
  }[phase]

  safe_emit(
    conn,
    draft_id=str(draft_id or ""),
    planning_run_id=str(planning_run_id or ""),
    phase=phase,
    event_code=failed_event,
    status=Status.FAILED,
    diagnostic_data={
      "fail_fast_code": code.value,
      "where": where[:200],
      "detail": str(detail)[:500],
      "cause_type": type(cause).__name__ if cause is not None else None,
    },
  )
  err = RuntimeError(f"{FAIL_FAST_PREFIX}{code.value}: {detail}")
  if cause is not None:
    raise err from cause
  raise err


__all__ = [
  "FailFastCode",
  "FAIL_FAST_CODES_BY_PHASE",
  "FAIL_FAST_PREFIX",
  "fail_fast_code_belongs_to_phase",
  "raise_fail_fast",
]
