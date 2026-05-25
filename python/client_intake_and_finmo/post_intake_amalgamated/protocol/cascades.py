"""Cascade policy tables — spec §5.

The five failure-mode cascades as Python data structures. The session
driver (lands in a later step-5 commit) loads ``CASCADES`` at startup and
walks the appropriate tier list when a mode is in failure.

Per spec §14.4 user decision Q4: cascades live in Python (not a SQL
policy table). The migration to a runtime-tunable SQL store is a ~50 LOC
refactor when needed; doing it now would add complexity for a
flexibility we don't yet need.

Each cascade is an ordered list of ``CascadeTier`` records. Tiers are
ordered by disruption (least to most). Tier 7 (or its mode-specific
equivalent) is always bound relaxation. The final tier per cascade is
the floor handoff (the cascade-as-floor walker in ``floor.py`` runs
tiers 1..N-1 unattended; if all fail the §9.2 mode-specific primitive
fires).

The cascade tables are the **source of truth** for protocol behavior.
Changes here are spec revisions; never edit them in line. The
reason_code field on each tier is what the audit row carries
(``protocol.reason_codes.ReasonCode``) — adding a tier without adding
its ReasonCode upstream is a structural bug.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Dict, List, Optional, Tuple

from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (
  FailureMode,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (
  ReasonCode,
  StepType,
)


# ---------------------------------------------------------------------------
# Per-tier shape
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CascadeLever:
  """A single (section, field, direction) tuple the tier can pull.

  Direction values are advisory hints the proposer uses to pick the
  numeric target:

    "to_band_target"   — move toward cohort target
    "to_band_min"      — move down to robust_min
    "to_band_max"      — move up to robust_max
    "to_favorable_edge" — direction depends on lever (price ↑ for
                          growth, price ↓ for value positioning)
    "shape"            — non-scalar; the proposer computes a trajectory
                         (e.g. stage_ramp grid reshape)
    "scale"            — multiplicative on the existing value
    "relax_robust_max" — band relaxation (tier 7-equivalent only)

  ``priority`` orders levers within a tier per spec §4.3:
    1 = most-out-of-band first
    2 = largest viability impact next
    3 = most headroom last

  ``viability_weight_factor`` scales the lever's impact in the C1
  dynamic priority sort: among rule-1-tied candidates, the lever with
  the larger ``abs(current - proposed) * viability_weight_factor``
  wins. Defaults to 1.0; spec-recognized high-impact levers (COGS,
  Q12 revenue ramp, payroll headcount) can override with a larger
  factor so the proposer prefers them when their impact is comparable
  to a lower-impact lever's distance.
  """
  section: str
  field: str
  direction: str
  priority: int = 1
  viability_weight_factor: float = 1.0


@dataclass(frozen=True)
class CascadeTier:
  """One tier in a per-mode cascade (spec §4.1)."""
  tier_id: str            # 'V1'..'V8', 'G1'..'G7', etc.
  name: str               # human-readable; surfaced in audit + reason codes
  levers: Tuple[CascadeLever, ...]
  target_rule: str        # human-readable target description (for rationale)
  step_type: StepType     # spec §6 (Type A = veto; Type B = choose; floor = unattended)
  reason_code: ReasonCode
  is_floor: bool = False  # final tier per cascade — triggers floor primitive

  @property
  def is_bound_relaxation(self) -> bool:
    return self.reason_code in _BOUND_RELAXATION_REASON_CODES

  @property
  def is_target_compression(self) -> bool:
    return self.reason_code in _TARGET_COMPRESSION_REASON_CODES


_BOUND_RELAXATION_REASON_CODES = frozenset({
  ReasonCode.VIABILITY_BOUND_RELAXED,
  ReasonCode.GROWTH_BOUND_RELAXED,
  ReasonCode.CAPACITY_BOUND_RELAXED,
  ReasonCode.BAND_BOUND_RELAXED,
  ReasonCode.COHERENCE_TOLERANCE_RELAXED,
})

_TARGET_COMPRESSION_REASON_CODES = frozenset({
  ReasonCode.GROWTH_TARGET_COMPRESSED,
  ReasonCode.CAPACITY_TARGET_COMPRESSED,
})


# ---------------------------------------------------------------------------
# §5.1 VIABILITY cascade
# ---------------------------------------------------------------------------

_VIABILITY_CASCADE: Tuple[CascadeTier, ...] = (
  CascadeTier(
    tier_id="V1", name="Cost-ratio tuning",
    levers=(
      # COGS has the largest viability impact (it's the biggest line item
      # by share of revenue for most businesses); weighted accordingly.
      CascadeLever("drivers", "expenses::Cost of Goods Sold",       "to_band_target", priority=1, viability_weight_factor=2.0),
      CascadeLever("drivers", "expenses::Marketing",                "to_band_target", priority=2),
      CascadeLever("drivers", "expenses::General & Administrative", "to_band_target", priority=3),
      CascadeLever("drivers", "expenses::Research & Development",   "to_band_target", priority=3),
    ),
    target_rule="cohort band target",
    step_type=StepType.TYPE_A,
    reason_code=ReasonCode.VIABILITY_COST_RATIO_TUNED,
  ),
  CascadeTier(
    tier_id="V2", name="Stage-ramp efficiency",
    levers=(
      CascadeLever("stage_ramp", "cogs_max",      "shape", priority=1),
      CascadeLever("stage_ramp", "marketing_max", "shape", priority=2),
      CascadeLever("stage_ramp", "ni_floor",      "shape", priority=3),
    ),
    target_rule="band target per quarter",
    step_type=StepType.TYPE_A,
    reason_code=ReasonCode.VIABILITY_RAMP_TUNED,
  ),
  CascadeTier(
    tier_id="V3", name="Pricing",
    levers=(
      CascadeLever("operating_model", "unit_price", "to_favorable_edge", priority=1),
    ),
    target_rule="nearest band edge favorable to viability (premium vs value reasoning)",
    step_type=StepType.TYPE_B,
    reason_code=ReasonCode.VIABILITY_PRICING_ADJUSTED,
  ),
  CascadeTier(
    tier_id="V4", name="Utilization",
    levers=(
      CascadeLever("operating_model", "utilization_rate", "to_band_target", priority=1),
      CascadeLever("stage_ramp",      "util_floor",       "shape",          priority=2),
    ),
    target_rule="band target",
    step_type=StepType.TYPE_A,
    reason_code=ReasonCode.VIABILITY_UTIL_ADJUSTED,
  ),
  CascadeTier(
    tier_id="V5", name="Capacity",
    levers=(
      CascadeLever("operating_model", "units_per_week_capacity", "scale", priority=1),
    ),
    target_rule="sized to support target revenue at band-target utilization (down only when over-built)",
    step_type=StepType.TYPE_A,
    reason_code=ReasonCode.VIABILITY_CAPACITY_RESIZED,
  ),
  CascadeTier(
    tier_id="V6", name="Payroll restructure",
    levers=(
      CascadeLever("payroll", "classes", "scale", priority=1),
      CascadeLever("payroll", "fte_counts", "scale", priority=2),
    ),
    target_rule="sized to band target payroll %-of-revenue (which class to shed is GPT choice)",
    step_type=StepType.TYPE_B,
    reason_code=ReasonCode.VIABILITY_PAYROLL_RESTRUCTURED,
  ),
  CascadeTier(
    tier_id="V7", name="Bound relaxation",
    levers=(
      # R&D first (most cohort variance in early stage), then marketing, then G&A.
      # COGS is NEVER relaxed (cohort cogs band represents physical economics).
      CascadeLever("drivers", "expenses::Research & Development",   "relax_robust_max", priority=1),
      CascadeLever("drivers", "expenses::Marketing",                "relax_robust_max", priority=2),
      CascadeLever("drivers", "expenses::General & Administrative", "relax_robust_max", priority=3),
    ),
    target_rule="relax robust_max by 5% step, capped at 15% cumulative (3 relaxations max per band)",
    step_type=StepType.TYPE_A,
    reason_code=ReasonCode.VIABILITY_BOUND_RELAXED,
  ),
  CascadeTier(
    tier_id="V8", name="Floor",
    levers=(),
    target_rule="all of the above, unattended, Python defaults; then VIABILITY_FLOOR_PRIMITIVE if still failing",
    step_type=StepType.FLOOR,
    reason_code=ReasonCode.VIABILITY_FLOOR_APPLIED,
    is_floor=True,
  ),
)


# ---------------------------------------------------------------------------
# §5.2 GROWTH cascade
# ---------------------------------------------------------------------------

_GROWTH_CASCADE: Tuple[CascadeTier, ...] = (
  CascadeTier(
    tier_id="G1", name="Ramp shape",
    levers=(
      CascadeLever("stage_ramp", "revenue_path", "shape", priority=1),
      CascadeLever("stage_ramp", "util_floor",   "shape", priority=2),
    ),
    target_rule="reshape to plateau at physically feasible level by Q8",
    step_type=StepType.TYPE_A,
    reason_code=ReasonCode.GROWTH_RAMP_RESHAPED,
  ),
  CascadeTier(
    tier_id="G2", name="Utilization ceiling raise",
    levers=(
      CascadeLever("operating_model", "utilization_rate", "to_band_max", priority=1),
    ),
    target_rule="band target -> band max if needed",
    step_type=StepType.TYPE_A,
    reason_code=ReasonCode.GROWTH_UTIL_RAISED,
  ),
  CascadeTier(
    tier_id="G3", name="Pricing",
    levers=(
      CascadeLever("operating_model", "unit_price", "to_band_max", priority=1),
    ),
    target_rule="up to band max favorable to growth",
    step_type=StepType.TYPE_B,
    reason_code=ReasonCode.GROWTH_PRICING_ADJUSTED,
  ),
  CascadeTier(
    tier_id="G4", name="Capacity expansion",
    levers=(
      CascadeLever("operating_model", "units_per_week_capacity", "scale", priority=1),
    ),
    target_rule="sized to support target rev at band-target util",
    step_type=StepType.TYPE_A,
    reason_code=ReasonCode.GROWTH_CAPACITY_EXPANDED,
  ),
  CascadeTier(
    tier_id="G5", name="Target compression",
    levers=(
      CascadeLever("stage_ramp", "revenue_path", "scale", priority=1),
    ),
    target_rule="compress target revenue trajectory to physically feasible ceiling (business owner judgment)",
    step_type=StepType.TYPE_B,
    reason_code=ReasonCode.GROWTH_TARGET_COMPRESSED,
  ),
  CascadeTier(
    tier_id="G6", name="Bound relaxation",
    levers=(
      CascadeLever("operating_model", "utilization_rate", "relax_robust_max", priority=1),
    ),
    target_rule="relax utilization band max by 5% step, capped at 15% cumulative",
    step_type=StepType.TYPE_A,
    reason_code=ReasonCode.GROWTH_BOUND_RELAXED,
  ),
  CascadeTier(
    tier_id="G7", name="Floor",
    levers=(),
    target_rule="unattended cascade-as-floor; then GROWTH_FLOOR_PRIMITIVE if still failing",
    step_type=StepType.FLOOR,
    reason_code=ReasonCode.GROWTH_FLOOR_APPLIED,
    is_floor=True,
  ),
)


# ---------------------------------------------------------------------------
# §5.3 CAPACITY cascade
# ---------------------------------------------------------------------------

_CAPACITY_CASCADE: Tuple[CascadeTier, ...] = (
  CascadeTier(
    tier_id="C1", name="Utilization re-anchor",
    levers=(
      CascadeLever("operating_model", "utilization_rate", "to_band_target", priority=1),
    ),
    target_rule="move toward cohort target (preferred over capacity resize — capacity is Stub 0-adjacent)",
    step_type=StepType.TYPE_A,
    reason_code=ReasonCode.CAPACITY_UTIL_REANCHORED,
  ),
  CascadeTier(
    tier_id="C2", name="Capacity re-size",
    levers=(
      CascadeLever("operating_model", "units_per_week_capacity", "scale", priority=1),
    ),
    target_rule="rebuild to match target revenue × cohort utilization",
    step_type=StepType.TYPE_A,
    reason_code=ReasonCode.CAPACITY_RESIZED,
  ),
  CascadeTier(
    tier_id="C3", name="Headcount alignment",
    levers=(
      CascadeLever("payroll",         "fte_counts",            "scale", priority=1),
      CascadeLever("operating_model", "per_employee_productivity", "to_band_target", priority=2),
    ),
    target_rule="productivity in band",
    step_type=StepType.TYPE_A,
    reason_code=ReasonCode.CAPACITY_HEADCOUNT_ALIGNED,
  ),
  CascadeTier(
    tier_id="C4", name="Target compression",
    levers=(
      CascadeLever("stage_ramp", "revenue_path", "scale", priority=1),
    ),
    target_rule="compress target revenue",
    step_type=StepType.TYPE_B,
    reason_code=ReasonCode.CAPACITY_TARGET_COMPRESSED,
  ),
  CascadeTier(
    tier_id="C5", name="Bound relaxation",
    levers=(
      CascadeLever("operating_model", "per_employee_productivity", "relax_robust_max", priority=1),
    ),
    target_rule="relax productivity band robust_max by 10% step, capped 25% cumulative",
    step_type=StepType.TYPE_A,
    reason_code=ReasonCode.CAPACITY_BOUND_RELAXED,
  ),
  CascadeTier(
    tier_id="C6", name="Floor",
    levers=(),
    target_rule="unattended cascade-as-floor; then CAPACITY_FLOOR_PRIMITIVE if still failing",
    step_type=StepType.FLOOR,
    reason_code=ReasonCode.CAPACITY_FLOOR_APPLIED,
    is_floor=True,
  ),
)


# ---------------------------------------------------------------------------
# §5.4 BAND cascade
# ---------------------------------------------------------------------------

_BAND_CASCADE: Tuple[CascadeTier, ...] = (
  CascadeTier(
    tier_id="B1", name="Clip to band edge",
    levers=(
      # The actual lever is whichever lever_margins.outside_band=True at runtime;
      # this row is a sentinel — the proposer picks the offending lever.
      CascadeLever("*", "*", "to_band_edge", priority=1),
    ),
    target_rule="nearest band edge",
    step_type=StepType.TYPE_A,
    reason_code=ReasonCode.BAND_CLIPPED,
  ),
  CascadeTier(
    tier_id="B2", name="Rebuild section",
    levers=(
      CascadeLever("*", "*", "rebuild_from_cohort_defaults", priority=1),
    ),
    target_rule="re-author the offending section via set_<section>(contract=None) builder path",
    step_type=StepType.TYPE_A,
    reason_code=ReasonCode.BAND_SECTION_REBUILT,
  ),
  CascadeTier(
    tier_id="B3", name="Bound relaxation",
    levers=(
      CascadeLever("*", "*", "relax_robust_max", priority=1),
    ),
    target_rule="relax offending band (rare; lever must be structurally extreme for valid reasons)",
    step_type=StepType.TYPE_B,
    reason_code=ReasonCode.BAND_BOUND_RELAXED,
  ),
  CascadeTier(
    tier_id="B4", name="Floor",
    levers=(),
    target_rule="unattended cascade-as-floor; then BAND_FLOOR_PRIMITIVE if still failing",
    step_type=StepType.FLOOR,
    reason_code=ReasonCode.BAND_FLOOR_APPLIED,
    is_floor=True,
  ),
)


# ---------------------------------------------------------------------------
# §5.5 COHERENCE cascade
# ---------------------------------------------------------------------------
#
# §14.2 user decision Q2: anchor authority order is
#   stage_ramp > drivers > payroll > capex_rd > balance_sheet
# (stage_ramp first because it's the planning artifact most expressive of
# business intent; downstream sections re-author from anchor-implied
# values).
_COHERENCE_ANCHOR_ORDER: Tuple[str, ...] = (
  "stage_ramp", "drivers", "payroll", "capex_rd", "balance_sheet",
)

_COHERENCE_CASCADE: Tuple[CascadeTier, ...] = (
  CascadeTier(
    tier_id="H1", name="Identify anchor",
    levers=(
      CascadeLever("*", "*", "choose_anchor", priority=1),
    ),
    target_rule=(
      "pick which section is the 'right' one in this conflict, per the "
      "authority order " + " > ".join(_COHERENCE_ANCHOR_ORDER)
    ),
    step_type=StepType.TYPE_A,
    reason_code=ReasonCode.COHERENCE_ANCHOR_CHOSEN,
  ),
  CascadeTier(
    tier_id="H2", name="Recompute non-anchor",
    levers=(
      CascadeLever("*", "*", "rebuild_from_anchor", priority=1),
    ),
    target_rule=(
      "re-author every non-anchor section via its set_*(contract=None) "
      "builder with anchor-derived inputs"
    ),
    step_type=StepType.TYPE_A,
    reason_code=ReasonCode.COHERENCE_RECONCILED,
  ),
  CascadeTier(
    tier_id="H3", name="Iterate (swap anchor)",
    levers=(
      CascadeLever("*", "*", "swap_anchor", priority=1),
    ),
    target_rule="re-evaluate; if still incoherent, swap anchor and retry once",
    step_type=StepType.TYPE_A,
    reason_code=ReasonCode.COHERENCE_ANCHOR_SWAPPED,
  ),
  CascadeTier(
    tier_id="H4", name="Tolerance relaxation",
    levers=(
      CascadeLever("*", "coherence_tolerance", "relax_robust_max", priority=1),
    ),
    target_rule="relax coherence tolerance by 5% step, capped 15% cumulative",
    step_type=StepType.TYPE_A,
    reason_code=ReasonCode.COHERENCE_TOLERANCE_RELAXED,
  ),
  CascadeTier(
    tier_id="H5", name="Floor",
    levers=(),
    target_rule="unattended cascade-as-floor; then COHERENCE_FLOOR_PRIMITIVE if still failing",
    step_type=StepType.FLOOR,
    reason_code=ReasonCode.COHERENCE_FLOOR_APPLIED,
    is_floor=True,
  ),
)


# ---------------------------------------------------------------------------
# Public cascade index + accessors
# ---------------------------------------------------------------------------

CASCADES: Dict[FailureMode, Tuple[CascadeTier, ...]] = {
  FailureMode.VIABILITY_INVARIANT:  _VIABILITY_CASCADE,
  FailureMode.GROWTH_INVARIANT:     _GROWTH_CASCADE,
  FailureMode.CAPACITY_INVARIANT:   _CAPACITY_CASCADE,
  FailureMode.BAND_INVARIANT:       _BAND_CASCADE,
  FailureMode.COHERENCE_INVARIANT:  _COHERENCE_CASCADE,
}


# §7.1 — when multiple modes are failing the protocol enters cascades in
# this order (cheap-to-fix first; encodes the dependency graph too).
MODE_PRIORITY: Tuple[FailureMode, ...] = (
  FailureMode.BAND_INVARIANT,
  FailureMode.COHERENCE_INVARIANT,
  FailureMode.CAPACITY_INVARIANT,
  FailureMode.GROWTH_INVARIANT,
  FailureMode.VIABILITY_INVARIANT,
)


# §14.1 user decision Q1: 3 relaxations max per band, 5% step, cumulative 15%.
BOUND_RELAXATION_STEP_FRACTION = 0.05
BOUND_RELAXATION_MAX_ATTEMPTS  = 3
BOUND_RELAXATION_CUMULATIVE_CAP = 0.15

# §14.5 user decision Q5: progress threshold = 10% improvement in worst-
# failing-distance. Two consecutive no-progress cascades trigger floor-all.
PROGRESS_THRESHOLD_FRACTION = 0.10
MAX_CONSECUTIVE_NO_PROGRESS = 2

# §8.7 — default tool-call budget per session, with budget-aware mode
# entering at 5 calls remaining and floor at 1 call remaining.
DEFAULT_TOOL_CALL_BUDGET    = 35
BUDGET_AWARE_THRESHOLD      = 5
BUDGET_FLOOR_THRESHOLD      = 1


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------

def get_cascade(mode: FailureMode) -> Tuple[CascadeTier, ...]:
  """Return the ordered tier list for ``mode``. KeyError on META."""
  if mode not in CASCADES:
    raise KeyError(
      f"mode {mode!r} has no cascade (only the five restructurable "
      f"modes have cascades; META is escalation-only per spec §8.5)"
    )
  return CASCADES[mode]


def get_tier(mode: FailureMode, tier_id: str) -> CascadeTier:
  """Return the tier with the given id within ``mode``'s cascade."""
  for tier in get_cascade(mode):
    if tier.tier_id == tier_id:
      return tier
  raise KeyError(
    f"tier {tier_id!r} not found in {mode.value} cascade (known: "
    f"{[t.tier_id for t in get_cascade(mode)]})"
  )


def next_tier(mode: FailureMode, current_tier_id: Optional[str]) -> Optional[CascadeTier]:
  """Return the tier that follows ``current_tier_id`` in ``mode``'s cascade.

  ``current_tier_id=None`` returns the first tier (cascade entry).
  Returns ``None`` when ``current_tier_id`` is the last tier.
  """
  tiers = get_cascade(mode)
  if current_tier_id is None:
    return tiers[0] if tiers else None
  for idx, tier in enumerate(tiers):
    if tier.tier_id == current_tier_id:
      return tiers[idx + 1] if idx + 1 < len(tiers) else None
  raise KeyError(f"tier {current_tier_id!r} not found in {mode.value} cascade")


def coherence_anchor_order() -> Tuple[str, ...]:
  """The §14.2 section-authority order for the COHERENCE cascade."""
  return _COHERENCE_ANCHOR_ORDER


__all__ = [
  "CascadeLever",
  "CascadeTier",
  "CASCADES",
  "MODE_PRIORITY",
  "BOUND_RELAXATION_STEP_FRACTION",
  "BOUND_RELAXATION_MAX_ATTEMPTS",
  "BOUND_RELAXATION_CUMULATIVE_CAP",
  "PROGRESS_THRESHOLD_FRACTION",
  "MAX_CONSECUTIVE_NO_PROGRESS",
  "DEFAULT_TOOL_CALL_BUDGET",
  "BUDGET_AWARE_THRESHOLD",
  "BUDGET_FLOOR_THRESHOLD",
  "get_cascade",
  "get_tier",
  "next_tier",
  "coherence_anchor_order",
]
