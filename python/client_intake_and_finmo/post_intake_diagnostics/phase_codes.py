"""Closed enums for the post_intake_run_diagnostics event stream.

Source of truth for the 13 pipeline phases and the ~50 specific events
within them. The writer in ``run_diagnostics_table.emit_diagnostic``
validates every write against these enums.

Phases run roughly in this order (some may interleave or repeat):

  1. cohort_bands_populator     — band resolver writes to
                                  post_intake_cohort_bands
  2. mirror_build                — amalgamated session mirror constructed
  3. round1_authoring            — set_*(contract=None) per section
                                  (Python-deterministic round-1)
  4. evaluate_plan               — standards check (every round)
  5. cascade_walk                — restructure cascade per mode
  6. floor_invocation            — §9.1 unattended walk + §9.2 primitive
  7. session_terminated          — SessionDriver exit
  8. finmo_sync                  — build_python_finmo_json over the
                                  authored plan
  9. target_seeking              — deterministic solver loop
 10. cash_pass                   — funding allocation
 11. realism_gate                — industry-band realism check
 12. finalize                    — global invariants + workbook prep
 13. workbook_accept             — acceptance gate
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, FrozenSet


class PhaseCode(str, Enum):
  COHORT_BANDS_POPULATOR = "cohort_bands_populator"
  MIRROR_BUILD            = "mirror_build"
  ROUND1_AUTHORING        = "round1_authoring"
  EVALUATE_PLAN           = "evaluate_plan"
  CASCADE_WALK            = "cascade_walk"
  FLOOR_INVOCATION        = "floor_invocation"
  SESSION_TERMINATED      = "session_terminated"
  FINMO_SYNC              = "finmo_sync"
  TARGET_SEEKING          = "target_seeking"
  CASH_PASS               = "cash_pass"
  REALISM_GATE            = "realism_gate"
  FINALIZE                = "finalize"
  WORKBOOK_ACCEPT         = "workbook_accept"


class EventCode(str, Enum):
  # cohort_bands_populator
  COHORT_BANDS_STARTED               = "cohort_bands_started"
  COHORT_BANDS_COMPLETED             = "cohort_bands_completed"
  COHORT_BANDS_FAILED                = "cohort_bands_failed"

  # mirror_build
  MIRROR_BUILD_STARTED               = "mirror_build_started"
  MIRROR_BUILD_COMPLETED             = "mirror_build_completed"
  MIRROR_BUILD_NO_BANDS              = "mirror_build_no_bands"

  # round1_authoring
  ROUND1_STARTED                     = "round1_started"
  ROUND1_CAPEX_RD_BALANCE_SEED_OK    = "round1_capex_rd_balance_seed_accepted"
  ROUND1_CAPEX_RD_BALANCE_SEED_FAIL  = "round1_capex_rd_balance_seed_rejected"
  ROUND1_STAGE_RAMP_OK               = "round1_stage_ramp_accepted"
  ROUND1_STAGE_RAMP_FAIL             = "round1_stage_ramp_rejected"
  ROUND1_PAYROLL_OK                  = "round1_payroll_accepted"
  ROUND1_PAYROLL_FAIL                = "round1_payroll_rejected"
  ROUND1_DRIVERS_OK                  = "round1_drivers_accepted"
  ROUND1_DRIVERS_FAIL                = "round1_drivers_rejected"
  ROUND1_COMPLETED                   = "round1_completed"

  # evaluate_plan
  EVALUATE_PLAN_STARTED              = "evaluate_plan_started"
  EVALUATE_PLAN_ALL_PASS             = "evaluate_plan_all_pass"
  EVALUATE_PLAN_FAILURES_DETECTED    = "evaluate_plan_failures_detected"
  EVALUATE_PLAN_COMPLETED            = "evaluate_plan_completed"

  # cascade_walk
  CASCADE_ENTERED                    = "cascade_entered"
  CASCADE_TIER_WALKED                = "cascade_tier_walked"
  CASCADE_SMART_ENTRY_SKIPPED        = "cascade_smart_entry_skipped"
  CASCADE_PROPOSAL_CONFIRMED         = "cascade_proposal_confirmed"
  CASCADE_PROPOSAL_VETOED            = "cascade_proposal_vetoed"
  CASCADE_PROPOSAL_CHOSEN            = "cascade_proposal_chosen"
  CASCADE_PROPOSAL_OTHER             = "cascade_proposal_other"
  CASCADE_PROPOSAL_OUT_OF_BAND       = "cascade_proposal_out_of_band"
  CASCADE_RESOLVED                   = "cascade_resolved"
  CASCADE_EXHAUSTED                  = "cascade_exhausted"

  # floor_invocation
  FLOOR_WALKER_ENTERED               = "floor_walker_entered"
  FLOOR_WALKER_RESOLVED              = "floor_walker_resolved"
  FLOOR_PRIMITIVE_APPLIED            = "floor_primitive_applied"
  FLOOR_COMPLETED                    = "floor_completed"

  # session_terminated
  SESSION_RESOLVED                   = "session_resolved"
  SESSION_FLOOR_ALL                  = "session_floor_all"
  SESSION_META_HALTED                = "session_meta_halted"
  SESSION_BUDGET_EXHAUSTED           = "session_budget_exhausted"
  SESSION_EXCEPTION_HALTED           = "session_exception_halted"

  # finmo_sync
  FINMO_SYNC_STARTED                 = "finmo_sync_started"
  FINMO_SYNC_COMPLETED               = "finmo_sync_completed"
  FINMO_SYNC_FAILED                  = "finmo_sync_failed"

  # target_seeking
  TARGET_SEEKING_FEASIBILITY_STARTED        = "target_seeking_feasibility_started"
  TARGET_SEEKING_PREFLIGHT_STARTED          = "target_seeking_preflight_started"
  TARGET_SEEKING_REPAIR_STARTED             = "target_seeking_repair_started"
  TARGET_SEEKING_ADAPTATION_CASCADE_STARTED = "target_seeking_adaptation_cascade_started"
  TARGET_SEEKING_PRE_CASH_GATE_STARTED      = "target_seeking_pre_cash_gate_started"
  TARGET_SEEKING_COMPLETED                  = "target_seeking_completed"

  # cash_pass
  CASH_PASS_STARTED                  = "cash_pass_started"
  CASH_PASS_MODE_CHOSEN              = "cash_pass_mode_chosen"
  CASH_PASS_FUNDING_GAP_RESOLVED     = "cash_pass_funding_gap_resolved"
  CASH_PASS_COMPLETED                = "cash_pass_completed"

  # realism_gate
  REALISM_GATE_STARTED               = "realism_gate_started"
  REALISM_GATE_CHECK_PASSED          = "realism_gate_check_passed"
  REALISM_GATE_CHECK_FAILED          = "realism_gate_check_failed"
  REALISM_GATE_COMPLETED             = "realism_gate_completed"

  # finalize
  FINALIZE_STARTED                   = "finalize_started"
  FINALIZE_VALIDATION_PASSED         = "finalize_validation_passed"
  FINALIZE_VALIDATION_FAILED         = "finalize_validation_failed"
  FINALIZE_COMPLETED                 = "finalize_completed"

  # workbook_accept
  WORKBOOK_ACCEPT_STARTED            = "workbook_accept_started"
  WORKBOOK_ACCEPT_ACCEPTED           = "workbook_accept_accepted"
  WORKBOOK_ACCEPT_REJECTED           = "workbook_accept_rejected"


class Status(str, Enum):
  """Coarse status tag for the event row. Most events use COMPLETED
  (the default in the writer); STARTED marks phase entries; FAILED
  marks fault paths; SKIPPED marks no-op or smart-entry-skipped paths."""
  STARTED   = "started"
  COMPLETED = "completed"
  FAILED    = "failed"
  SKIPPED   = "skipped"


# Phase -> the EventCodes that belong to it. The writer validates every
# (phase, event_code) pair against this partition so the event stream
# stays queryable along these axes.
EVENT_CODES_BY_PHASE: Dict[PhaseCode, FrozenSet[EventCode]] = {
  PhaseCode.COHORT_BANDS_POPULATOR: frozenset({
    EventCode.COHORT_BANDS_STARTED,
    EventCode.COHORT_BANDS_COMPLETED,
    EventCode.COHORT_BANDS_FAILED,
  }),
  PhaseCode.MIRROR_BUILD: frozenset({
    EventCode.MIRROR_BUILD_STARTED,
    EventCode.MIRROR_BUILD_COMPLETED,
    EventCode.MIRROR_BUILD_NO_BANDS,
  }),
  PhaseCode.ROUND1_AUTHORING: frozenset({
    EventCode.ROUND1_STARTED,
    EventCode.ROUND1_CAPEX_RD_BALANCE_SEED_OK,
    EventCode.ROUND1_CAPEX_RD_BALANCE_SEED_FAIL,
    EventCode.ROUND1_STAGE_RAMP_OK,
    EventCode.ROUND1_STAGE_RAMP_FAIL,
    EventCode.ROUND1_PAYROLL_OK,
    EventCode.ROUND1_PAYROLL_FAIL,
    EventCode.ROUND1_DRIVERS_OK,
    EventCode.ROUND1_DRIVERS_FAIL,
    EventCode.ROUND1_COMPLETED,
  }),
  PhaseCode.EVALUATE_PLAN: frozenset({
    EventCode.EVALUATE_PLAN_STARTED,
    EventCode.EVALUATE_PLAN_ALL_PASS,
    EventCode.EVALUATE_PLAN_FAILURES_DETECTED,
    EventCode.EVALUATE_PLAN_COMPLETED,
  }),
  PhaseCode.CASCADE_WALK: frozenset({
    EventCode.CASCADE_ENTERED,
    EventCode.CASCADE_TIER_WALKED,
    EventCode.CASCADE_SMART_ENTRY_SKIPPED,
    EventCode.CASCADE_PROPOSAL_CONFIRMED,
    EventCode.CASCADE_PROPOSAL_VETOED,
    EventCode.CASCADE_PROPOSAL_CHOSEN,
    EventCode.CASCADE_PROPOSAL_OTHER,
    EventCode.CASCADE_PROPOSAL_OUT_OF_BAND,
    EventCode.CASCADE_RESOLVED,
    EventCode.CASCADE_EXHAUSTED,
  }),
  PhaseCode.FLOOR_INVOCATION: frozenset({
    EventCode.FLOOR_WALKER_ENTERED,
    EventCode.FLOOR_WALKER_RESOLVED,
    EventCode.FLOOR_PRIMITIVE_APPLIED,
    EventCode.FLOOR_COMPLETED,
  }),
  PhaseCode.SESSION_TERMINATED: frozenset({
    EventCode.SESSION_RESOLVED,
    EventCode.SESSION_FLOOR_ALL,
    EventCode.SESSION_META_HALTED,
    EventCode.SESSION_BUDGET_EXHAUSTED,
    EventCode.SESSION_EXCEPTION_HALTED,
  }),
  PhaseCode.FINMO_SYNC: frozenset({
    EventCode.FINMO_SYNC_STARTED,
    EventCode.FINMO_SYNC_COMPLETED,
    EventCode.FINMO_SYNC_FAILED,
  }),
  PhaseCode.TARGET_SEEKING: frozenset({
    EventCode.TARGET_SEEKING_FEASIBILITY_STARTED,
    EventCode.TARGET_SEEKING_PREFLIGHT_STARTED,
    EventCode.TARGET_SEEKING_REPAIR_STARTED,
    EventCode.TARGET_SEEKING_ADAPTATION_CASCADE_STARTED,
    EventCode.TARGET_SEEKING_PRE_CASH_GATE_STARTED,
    EventCode.TARGET_SEEKING_COMPLETED,
  }),
  PhaseCode.CASH_PASS: frozenset({
    EventCode.CASH_PASS_STARTED,
    EventCode.CASH_PASS_MODE_CHOSEN,
    EventCode.CASH_PASS_FUNDING_GAP_RESOLVED,
    EventCode.CASH_PASS_COMPLETED,
  }),
  PhaseCode.REALISM_GATE: frozenset({
    EventCode.REALISM_GATE_STARTED,
    EventCode.REALISM_GATE_CHECK_PASSED,
    EventCode.REALISM_GATE_CHECK_FAILED,
    EventCode.REALISM_GATE_COMPLETED,
  }),
  PhaseCode.FINALIZE: frozenset({
    EventCode.FINALIZE_STARTED,
    EventCode.FINALIZE_VALIDATION_PASSED,
    EventCode.FINALIZE_VALIDATION_FAILED,
    EventCode.FINALIZE_COMPLETED,
  }),
  PhaseCode.WORKBOOK_ACCEPT: frozenset({
    EventCode.WORKBOOK_ACCEPT_STARTED,
    EventCode.WORKBOOK_ACCEPT_ACCEPTED,
    EventCode.WORKBOOK_ACCEPT_REJECTED,
  }),
}


def event_code_belongs_to_phase(event: EventCode, phase: PhaseCode) -> bool:
  """Return True iff ``event`` is a registered event for ``phase``."""
  allowed = EVENT_CODES_BY_PHASE.get(phase)
  return event in allowed if allowed is not None else False


__all__ = [
  "PhaseCode",
  "EventCode",
  "Status",
  "EVENT_CODES_BY_PHASE",
  "event_code_belongs_to_phase",
]
