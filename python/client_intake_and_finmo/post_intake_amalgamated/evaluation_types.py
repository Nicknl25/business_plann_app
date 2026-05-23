"""Structured types for evaluate_plan output.

The restructure protocol (lands in a later commit before step 4) dispatches
on this shape. Every field is here because the protocol needs to read it.
Do NOT collapse this into a free-form dict — the typing keeps the protocol
honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class FailureMode(str, Enum):
  """The enum the restructure protocol dispatches on. Every failing check
  is classified as exactly one of these. The protocol's lever-priority and
  escalation tables key off this value, so it must remain stable across
  Phase 3 commits.
  """
  CASH_INVARIANT       = "cash_invariant"        # cash balance / current assets / cash-health checks
  VIABILITY_INVARIANT  = "viability_invariant"   # EBITDA, NI trajectory, viability timeline
  GROWTH_INVARIANT     = "growth_invariant"      # revenue not flat, BS growth plausibility
  CAPACITY_INVARIANT   = "capacity_invariant"    # capacity / utilization ceilings
  BAND_INVARIANT       = "band_invariant"        # any lever outside its cohort band (realism)
  COHERENCE_INVARIANT  = "coherence_invariant"   # cross-section (stage_ramp ↔ drivers etc.)
  META_INVARIANT       = "meta_invariant"        # gate machinery checks (stage_reached, cascade_tier_set, ...)


# Canonical authoring sections. Mirrored in cohort_bands_table._SECTION_LEVERS.
SECTIONS = ("stage_ramp", "drivers", "payroll", "capex_rd", "balance_sheet")


@dataclass
class CheckResult:
  """One acceptance / viability check."""
  name: str
  passed: bool
  failure_mode: Optional[FailureMode] = None
  # Signed distance to the feasibility boundary in the check's natural
  # units; positive = passing with margin, negative = failing by that
  # much, None = check is binary or distance not computable from inputs.
  distance_to_feasibility: Optional[float] = None
  distance_units: Optional[str] = None  # "fraction" | "dollars" | "days" | "quarters" | "dimensionless"
  implicated_sections: List[str] = field(default_factory=list)
  detail: Dict[str, Any] = field(default_factory=dict)

  def to_dict(self) -> Dict[str, Any]:
    d = asdict(self)
    d["failure_mode"] = self.failure_mode.value if self.failure_mode is not None else None
    return d


@dataclass
class LeverMargin:
  """Distance from a committed lever value to its band edges. The
  restructure protocol uses ``pinned_min`` / ``pinned_max`` to tell which
  levers still have headroom to absorb a revision request.
  """
  lever_id: str
  section: str
  quarter: Optional[int] = None     # None = scalar lever (e.g. capex %); set for per-quarter levers
  current: Optional[float] = None
  band_min: Optional[float] = None
  band_target: Optional[float] = None
  band_max: Optional[float] = None
  distance_to_min: Optional[float] = None  # current - band_min (>=0 means at-or-above min)
  distance_to_max: Optional[float] = None  # band_max - current (>=0 means at-or-below max)
  pinned_min: bool = False
  pinned_max: bool = False
  outside_band: bool = False        # current < band_min or current > band_max

  def to_dict(self) -> Dict[str, Any]:
    return asdict(self)


@dataclass
class QuarterTrajectory:
  """Per-quarter trajectory snapshot. Sparse fields are fine — a check
  may emit only the metrics it touched."""
  quarter: int
  revenue: Optional[float] = None
  cash: Optional[float] = None
  ebitda: Optional[float] = None
  ebitda_margin: Optional[float] = None
  gross_margin: Optional[float] = None
  net_income: Optional[float] = None
  net_income_margin: Optional[float] = None
  utilization: Optional[float] = None
  cogs_ratio: Optional[float] = None

  def to_dict(self) -> Dict[str, Any]:
    return {k: v for k, v in asdict(self).items() if v is not None or k == "quarter"}


@dataclass
class EvaluatePlanResult:
  """The full payload the restructure protocol consumes."""
  all_pass: bool
  round_number: int
  structural_completeness: bool
  strictness: str  # "mini_finmo" while assembling | "full_acceptance_gate" once structurally complete
  checks: List[CheckResult] = field(default_factory=list)
  trajectory: List[QuarterTrajectory] = field(default_factory=list)
  lever_margins: List[LeverMargin] = field(default_factory=list)
  # Worst failing check's signed distance — quick handle for the
  # ring-buffer "did my last move help" delta.
  worst_failing_distance: Optional[float] = None
  worst_failing_check: Optional[str] = None
  evaluated_at: Optional[str] = None
  notes: List[str] = field(default_factory=list)

  def to_dict(self) -> Dict[str, Any]:
    return {
      "all_pass": self.all_pass,
      "round_number": self.round_number,
      "structural_completeness": self.structural_completeness,
      "strictness": self.strictness,
      "checks": [c.to_dict() for c in self.checks],
      "trajectory": [q.to_dict() for q in self.trajectory],
      "lever_margins": [m.to_dict() for m in self.lever_margins],
      "worst_failing_distance": self.worst_failing_distance,
      "worst_failing_check": self.worst_failing_check,
      "evaluated_at": self.evaluated_at,
      "notes": list(self.notes),
    }
