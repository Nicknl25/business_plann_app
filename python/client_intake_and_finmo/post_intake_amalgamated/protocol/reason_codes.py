"""Closed enums for the restructure protocol audit log.

Source of truth for spec §10.2 (ReasonCode) and §10.3 (AppliedBy). Cascade
tables (§5, lands in step 5 ``cascades.py``) reference these by name. The
``restructuring_log`` row writer (``restructuring_log_table.log_restructure``)
validates every write against these enums — any addition is a spec revision,
not an in-line tweak.

StepType is the §6 step semantics tag ('A' = Python proposes / GPT vetoes,
'B' = Python presents options / GPT chooses, 'floor' = unattended floor walk,
'meta' = META halt row).
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, FrozenSet

from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (
  FailureMode,
)


class ReasonCode(str, Enum):
  """The closed set of restructure reason codes (spec §10.2).

  Adding a code here is a spec revision. The row writer rejects anything
  not in this enum so audit logs remain queryable by a stable vocabulary.
  """

  # VIABILITY cascade — §5.1
  VIABILITY_COST_RATIO_TUNED      = "VIABILITY_COST_RATIO_TUNED"
  VIABILITY_RAMP_TUNED            = "VIABILITY_RAMP_TUNED"
  VIABILITY_PRICING_ADJUSTED      = "VIABILITY_PRICING_ADJUSTED"
  VIABILITY_UTIL_ADJUSTED         = "VIABILITY_UTIL_ADJUSTED"
  VIABILITY_CAPACITY_RESIZED      = "VIABILITY_CAPACITY_RESIZED"
  VIABILITY_PAYROLL_RESTRUCTURED  = "VIABILITY_PAYROLL_RESTRUCTURED"
  VIABILITY_BOUND_RELAXED         = "VIABILITY_BOUND_RELAXED"
  VIABILITY_FLOOR_APPLIED         = "VIABILITY_FLOOR_APPLIED"
  VIABILITY_FLOOR_PRIMITIVE       = "VIABILITY_FLOOR_PRIMITIVE"

  # GROWTH cascade — §5.2
  GROWTH_RAMP_RESHAPED            = "GROWTH_RAMP_RESHAPED"
  GROWTH_UTIL_RAISED              = "GROWTH_UTIL_RAISED"
  GROWTH_PRICING_ADJUSTED         = "GROWTH_PRICING_ADJUSTED"
  GROWTH_CAPACITY_EXPANDED        = "GROWTH_CAPACITY_EXPANDED"
  GROWTH_TARGET_COMPRESSED        = "GROWTH_TARGET_COMPRESSED"
  GROWTH_BOUND_RELAXED            = "GROWTH_BOUND_RELAXED"
  GROWTH_FLOOR_APPLIED            = "GROWTH_FLOOR_APPLIED"
  GROWTH_FLOOR_PRIMITIVE          = "GROWTH_FLOOR_PRIMITIVE"

  # CAPACITY cascade — §5.3
  CAPACITY_UTIL_REANCHORED        = "CAPACITY_UTIL_REANCHORED"
  CAPACITY_RESIZED                = "CAPACITY_RESIZED"
  CAPACITY_HEADCOUNT_ALIGNED      = "CAPACITY_HEADCOUNT_ALIGNED"
  CAPACITY_TARGET_COMPRESSED      = "CAPACITY_TARGET_COMPRESSED"
  CAPACITY_BOUND_RELAXED          = "CAPACITY_BOUND_RELAXED"
  CAPACITY_FLOOR_APPLIED          = "CAPACITY_FLOOR_APPLIED"
  CAPACITY_FLOOR_PRIMITIVE        = "CAPACITY_FLOOR_PRIMITIVE"

  # BAND cascade — §5.4
  BAND_CLIPPED                    = "BAND_CLIPPED"
  BAND_SECTION_REBUILT            = "BAND_SECTION_REBUILT"
  BAND_BOUND_RELAXED              = "BAND_BOUND_RELAXED"
  BAND_FLOOR_APPLIED              = "BAND_FLOOR_APPLIED"
  BAND_FLOOR_PRIMITIVE            = "BAND_FLOOR_PRIMITIVE"

  # COHERENCE cascade — §5.5
  COHERENCE_ANCHOR_CHOSEN         = "COHERENCE_ANCHOR_CHOSEN"
  COHERENCE_RECONCILED            = "COHERENCE_RECONCILED"
  COHERENCE_ANCHOR_SWAPPED        = "COHERENCE_ANCHOR_SWAPPED"
  COHERENCE_TOLERANCE_RELAXED     = "COHERENCE_TOLERANCE_RELAXED"
  COHERENCE_FLOOR_APPLIED         = "COHERENCE_FLOOR_APPLIED"
  COHERENCE_FLOOR_PRIMITIVE       = "COHERENCE_FLOOR_PRIMITIVE"

  # Protocol meta — §8.5 / §7.3 / §8.7
  META_ESCALATED                  = "META_ESCALATED"
  STAGNATION_FLOOR_ALL            = "STAGNATION_FLOOR_ALL"
  BUDGET_EXHAUSTED_FLOOR          = "BUDGET_EXHAUSTED_FLOOR"


class AppliedBy(str, Enum):
  """The closed set of audit-log ``applied_by`` values (spec §10.3).

  Every row in ``post_intake_restructuring_log`` carries one of these. The
  set covers every way a cascade step can land — confirmed proposals,
  vetoes (logged even though no state changes), free-form 'other'
  proposals (in-band vs out-of-band), floor walks, floor primitives, META
  halts, and budget-aware auto-confirms.
  """

  AMALGAMATED_GPT_CONFIRMED      = "amalgamated_gpt_confirmed"
  AMALGAMATED_GPT_VETOED         = "amalgamated_gpt_vetoed"
  AMALGAMATED_GPT_CHOSE          = "amalgamated_gpt_chose"
  AMALGAMATED_GPT_OTHER          = "amalgamated_gpt_other"
  AMALGAMATED_GPT_OTHER_OUT_BAND = "amalgamated_gpt_other_out_band"
  DETERMINISTIC_FLOOR            = "deterministic_floor"
  FLOOR_PRIMITIVE                = "floor_primitive"
  META_ESCALATION                = "meta_escalation"
  BUDGET_AWARE_AUTO_CONFIRM      = "budget_aware_auto_confirm"


class StepType(str, Enum):
  """Cascade step type — spec §6 + §10.1 column 'step_type'."""

  TYPE_A = "A"     # Python proposes / GPT vetoes
  TYPE_B = "B"     # Python presents options / GPT chooses
  FLOOR  = "floor" # Unattended floor walk (either cascade-as-floor or primitive)
  META   = "meta"  # META escalation row (no application; audit only)


# Map FailureMode -> the ReasonCodes that may appear with that mode. The row
# writer uses this to reject mismatched (mode, reason_code) pairs early —
# logging a VIABILITY_PRICING_ADJUSTED against a GROWTH_INVARIANT is a bug.
# META meta-codes (STAGNATION_FLOOR_ALL, BUDGET_EXHAUSTED_FLOOR, META_ESCALATED)
# are routed via FailureMode.META_INVARIANT.
REASON_CODES_BY_MODE: Dict[FailureMode, FrozenSet[ReasonCode]] = {
  FailureMode.VIABILITY_INVARIANT: frozenset({
    ReasonCode.VIABILITY_COST_RATIO_TUNED,
    ReasonCode.VIABILITY_RAMP_TUNED,
    ReasonCode.VIABILITY_PRICING_ADJUSTED,
    ReasonCode.VIABILITY_UTIL_ADJUSTED,
    ReasonCode.VIABILITY_CAPACITY_RESIZED,
    ReasonCode.VIABILITY_PAYROLL_RESTRUCTURED,
    ReasonCode.VIABILITY_BOUND_RELAXED,
    ReasonCode.VIABILITY_FLOOR_APPLIED,
    ReasonCode.VIABILITY_FLOOR_PRIMITIVE,
  }),
  FailureMode.GROWTH_INVARIANT: frozenset({
    ReasonCode.GROWTH_RAMP_RESHAPED,
    ReasonCode.GROWTH_UTIL_RAISED,
    ReasonCode.GROWTH_PRICING_ADJUSTED,
    ReasonCode.GROWTH_CAPACITY_EXPANDED,
    ReasonCode.GROWTH_TARGET_COMPRESSED,
    ReasonCode.GROWTH_BOUND_RELAXED,
    ReasonCode.GROWTH_FLOOR_APPLIED,
    ReasonCode.GROWTH_FLOOR_PRIMITIVE,
  }),
  FailureMode.CAPACITY_INVARIANT: frozenset({
    ReasonCode.CAPACITY_UTIL_REANCHORED,
    ReasonCode.CAPACITY_RESIZED,
    ReasonCode.CAPACITY_HEADCOUNT_ALIGNED,
    ReasonCode.CAPACITY_TARGET_COMPRESSED,
    ReasonCode.CAPACITY_BOUND_RELAXED,
    ReasonCode.CAPACITY_FLOOR_APPLIED,
    ReasonCode.CAPACITY_FLOOR_PRIMITIVE,
  }),
  FailureMode.BAND_INVARIANT: frozenset({
    ReasonCode.BAND_CLIPPED,
    ReasonCode.BAND_SECTION_REBUILT,
    ReasonCode.BAND_BOUND_RELAXED,
    ReasonCode.BAND_FLOOR_APPLIED,
    ReasonCode.BAND_FLOOR_PRIMITIVE,
  }),
  FailureMode.COHERENCE_INVARIANT: frozenset({
    ReasonCode.COHERENCE_ANCHOR_CHOSEN,
    ReasonCode.COHERENCE_RECONCILED,
    ReasonCode.COHERENCE_ANCHOR_SWAPPED,
    ReasonCode.COHERENCE_TOLERANCE_RELAXED,
    ReasonCode.COHERENCE_FLOOR_APPLIED,
    ReasonCode.COHERENCE_FLOOR_PRIMITIVE,
  }),
  FailureMode.META_INVARIANT: frozenset({
    ReasonCode.META_ESCALATED,
    ReasonCode.STAGNATION_FLOOR_ALL,
    ReasonCode.BUDGET_EXHAUSTED_FLOOR,
  }),
}


def reason_code_belongs_to_mode(code: ReasonCode, mode: FailureMode) -> bool:
  """Return True iff ``code`` is allowed for ``mode``. Used by the row writer
  to catch mismatched (mode, code) pairs at write time."""
  allowed = REASON_CODES_BY_MODE.get(mode)
  if allowed is None:
    return False
  return code in allowed


__all__ = [
  "ReasonCode",
  "AppliedBy",
  "StepType",
  "REASON_CODES_BY_MODE",
  "reason_code_belongs_to_mode",
]
