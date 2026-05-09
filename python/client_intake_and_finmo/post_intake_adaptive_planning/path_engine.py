"""Phase 9 Phase C2 — path engine.

Pure deterministic shape functions and a per-driver shape registry. No GPT.

Consumed by Phase C3's path-aware writer when the solver moves a lever:
the writer asks ``compute_per_quarter_values()`` to translate a single
scalar amplitude into a Q1-Q20 path consistent with the doctrine and the
generated stage_ramp_contract.

Shape catalogue (one function per shape kind):
  flat                          — same value Q1..QN
  linear_to_mature              — linear from start to target by deadline_q,
                                  held flat thereafter
  glidepath                     — linear interpolation from start to target
                                  reaching target at horizon (or deadline)
  s_curve                       — symmetric logistic from start to target
  capacity_expansion            — stage-aware staged ramp (s_curve for
                                  startup/early; near-flat for mature)
  industry_convergence_decay    — exponential decay toward industry target

Schedule-locked drivers (Payroll, Capex schedule, Debt schedule) and
calculated drivers (Depreciation, Interest, Tax) return a no-write
signal — the existing schedule machinery owns them, the path engine
does not write over their values.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


# ----------------------------------------------------------------------------
# Shape kinds (vocabulary)
# ----------------------------------------------------------------------------

SHAPE_FLAT = "flat"
SHAPE_LINEAR_TO_MATURE = "linear_to_mature"
SHAPE_GLIDEPATH = "glidepath"
SHAPE_S_CURVE = "s_curve"
SHAPE_CAPACITY_EXPANSION = "capacity_expansion"
SHAPE_INDUSTRY_CONVERGENCE_DECAY = "industry_convergence_decay"
SHAPE_HIRING_SCHEDULE = "hiring_schedule"
SHAPE_CALCULATED = "calculated"
SHAPE_STOCK_CARRYFORWARD = "stock_carryforward"
SHAPE_SCHEDULE_LOCKED = "schedule_locked"

ALL_SHAPES: List[str] = [
  SHAPE_FLAT,
  SHAPE_LINEAR_TO_MATURE,
  SHAPE_GLIDEPATH,
  SHAPE_S_CURVE,
  SHAPE_CAPACITY_EXPANSION,
  SHAPE_INDUSTRY_CONVERGENCE_DECAY,
  SHAPE_HIRING_SCHEDULE,
  SHAPE_CALCULATED,
  SHAPE_STOCK_CARRYFORWARD,
  SHAPE_SCHEDULE_LOCKED,
]

# Shapes that produce per-quarter values the writer must persist. Other
# shapes either carry forward stock semantics (Owner's Capital), are owned
# by separate machinery (Payroll, Capex schedule), or are derived from
# upstream rows (Depreciation, Interest).
WRITABLE_SHAPES: List[str] = [
  SHAPE_FLAT,
  SHAPE_LINEAR_TO_MATURE,
  SHAPE_GLIDEPATH,
  SHAPE_S_CURVE,
  SHAPE_CAPACITY_EXPANSION,
  SHAPE_INDUSTRY_CONVERGENCE_DECAY,
]


# ----------------------------------------------------------------------------
# Per-driver shape registry
# ----------------------------------------------------------------------------

# Exact lever ids handled by the registry. Wildcards on revenue subscripts
# (per-product / per-slot) are handled via _LEVER_PATTERNS below.
_EXPENSE_LEVER_SHAPES: Dict[str, str] = {
  "expenses::Cost of Goods Sold": SHAPE_GLIDEPATH,
  "expenses::Marketing": SHAPE_GLIDEPATH,
  "expenses::Research & Development": SHAPE_GLIDEPATH,
  "expenses::General & Administrative": SHAPE_GLIDEPATH,
  "expenses::Lease": SHAPE_FLAT,
  "expenses::Payroll": SHAPE_HIRING_SCHEDULE,
  "expenses::Taxes": SHAPE_FLAT,
  "expenses::Depreciation": SHAPE_CALCULATED,
  "expenses::Interest": SHAPE_CALCULATED,
}

_BALANCE_SHEET_LEVER_SHAPES: Dict[str, str] = {
  "balance_sheet::Accounts Receivable Days": SHAPE_LINEAR_TO_MATURE,
  "balance_sheet::Accounts Payable Days": SHAPE_LINEAR_TO_MATURE,
  "balance_sheet::AR Days": SHAPE_LINEAR_TO_MATURE,
  "balance_sheet::AP Days": SHAPE_LINEAR_TO_MATURE,
  "balance_sheet::Inventory Days": SHAPE_LINEAR_TO_MATURE,
  "balance_sheet::Prepaid Expenses (% of Revenue)": SHAPE_LINEAR_TO_MATURE,
  "balance_sheet::Deferred Revenue (% of Revenue)": SHAPE_LINEAR_TO_MATURE,
  "balance_sheet::Owner's Capital": SHAPE_STOCK_CARRYFORWARD,
  "balance_sheet::Other Equity": SHAPE_STOCK_CARRYFORWARD,
  "balance_sheet::Distributions": SHAPE_FLAT,
  "balance_sheet::Short Term Debt (% of LTD)": SHAPE_FLAT,
  "balance_sheet::Cash": SHAPE_CALCULATED,
}

# Revenue formula-bundle levers carry per-product / per-slot subscripts:
# revenue::<Product>::<Slot>::Capacity etc. Match by suffix.
_REVENUE_SUFFIX_SHAPES: List[Tuple[str, str]] = [
  ("::Capacity", SHAPE_CAPACITY_EXPANSION),
  ("::Unit Price", SHAPE_INDUSTRY_CONVERGENCE_DECAY),
  ("::Utilization", SHAPE_S_CURVE),
  ("::Periods", SHAPE_FLAT),
]


def lookup_shape_for_lever(lever_id: str) -> str:
  """Return the doctrinal shape kind for a given lever id.

  Falls back to SHAPE_FLAT for unknown lever ids — preserves the
  pre-Phase-C broadcast behavior so unfamiliar levers don't accidentally
  trigger path-shaping. Phase C adds explicit registry entries; later
  phases (D especially) extend this when new lever_ids land.
  """
  lever = (lever_id or "").strip()
  if not lever:
    return SHAPE_FLAT
  if lever in _EXPENSE_LEVER_SHAPES:
    return _EXPENSE_LEVER_SHAPES[lever]
  if lever in _BALANCE_SHEET_LEVER_SHAPES:
    return _BALANCE_SHEET_LEVER_SHAPES[lever]
  if lever.startswith("schedules::"):
    return SHAPE_SCHEDULE_LOCKED
  if lever.startswith("revenue::"):
    for suffix, shape in _REVENUE_SUFFIX_SHAPES:
      if lever.endswith(suffix):
        return shape
    return SHAPE_FLAT
  return SHAPE_FLAT


# ----------------------------------------------------------------------------
# Shape functions
# ----------------------------------------------------------------------------

def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  try:
    number = float(value)
  except Exception:
    return None
  if number != number:  # NaN
    return None
  return number


def flat_path(value: float, *, horizon: int) -> List[float]:
  v = float(value)
  return [v for _ in range(int(max(1, horizon)))]


def linear_to_mature(
  start: float,
  target: float,
  *,
  horizon: int,
  deadline_q: int = 11,
) -> List[float]:
  """Linear from `start` at Q1 to `target` at `deadline_q`, then flat at target."""
  h = int(max(1, horizon))
  d = int(max(1, min(deadline_q, h)))
  if d == 1:
    return [float(target) for _ in range(h)]
  s = float(start)
  t = float(target)
  out: List[float] = []
  for q in range(1, h + 1):
    if q >= d:
      out.append(t)
    else:
      progress = (q - 1) / float(d - 1)
      out.append(s + (t - s) * progress)
  return out


def glidepath(
  start: float,
  target: float,
  *,
  horizon: int,
  deadline_q: Optional[int] = None,
) -> List[float]:
  """Smooth linear glide from start to target reaching target by deadline_q (or horizon)."""
  h = int(max(1, horizon))
  d = int(max(1, min(deadline_q if deadline_q else h, h)))
  if d == 1:
    return [float(target) for _ in range(h)]
  s = float(start)
  t = float(target)
  out: List[float] = []
  for q in range(1, h + 1):
    if q >= d:
      out.append(t)
    else:
      progress = (q - 1) / float(d - 1)
      out.append(s + (t - s) * progress)
  return out


def s_curve(
  start: float,
  target: float,
  *,
  horizon: int,
  midpoint_q: Optional[int] = None,
  steepness: float = 4.0,
) -> List[float]:
  """Symmetric logistic from start to target.

  ``midpoint_q`` controls where 50% transition occurs (default = horizon/2).
  ``steepness`` controls slope at midpoint; higher = sharper transition.
  """
  h = int(max(1, horizon))
  if h == 1:
    return [float(target)]
  s = float(start)
  t = float(target)
  m = float(midpoint_q) if midpoint_q else (h + 1) / 2.0
  k = float(max(1.0, steepness)) / float(h)
  out: List[float] = []
  for q in range(1, h + 1):
    z = -k * (q - m) * 4.0
    sigma = 1.0 / (1.0 + math.exp(z))
    out.append(s + (t - s) * sigma)
  return out


def capacity_expansion(
  start: float,
  target: float,
  *,
  horizon: int,
  stage_profile: str = "operational",
) -> List[float]:
  """Stage-aware capacity ramp.

  Startup / early stages use an s_curve to mature target.
  Operational and mature businesses default to a slow glidepath
  (capacity rarely changes mid-flight).
  """
  if stage_profile in ("startup", "early"):
    return s_curve(start, target, horizon=horizon, steepness=3.5)
  if stage_profile == "operational":
    return glidepath(start, target, horizon=horizon)
  # mature: hold capacity flat unless an explicit expansion target moves it
  if abs(float(target) - float(start)) < 1e-6:
    return flat_path(start, horizon=horizon)
  return glidepath(start, target, horizon=horizon, deadline_q=horizon)


def industry_convergence_decay(
  start: float,
  target: float,
  *,
  horizon: int,
  half_life_q: int = 6,
) -> List[float]:
  """Exponential approach toward target with a quarter half-life.

  Phase 8's 1% unit_price ramp produced a generic linear nudge regardless
  of how far the start was from the industry mature value. This shape
  decays toward the target at a configurable half-life so a very-low-price
  startup converges quickly while a near-mature business barely moves.
  """
  h = int(max(1, horizon))
  if h == 1:
    return [float(target)]
  s = float(start)
  t = float(target)
  hl = float(max(1, half_life_q))
  out: List[float] = []
  for q in range(1, h + 1):
    fraction_remaining = math.pow(0.5, (q - 1) / hl)
    out.append(t + (s - t) * fraction_remaining)
  return out


# ----------------------------------------------------------------------------
# Stage ramp contract reading helpers
# ----------------------------------------------------------------------------

def _quarter_ramp_grid_rows(stage_ramp_contract: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  if not isinstance(stage_ramp_contract, dict):
    return []
  rows = stage_ramp_contract.get("quarter_ramp_grid")
  if not isinstance(rows, list):
    return []
  return [r for r in rows if isinstance(r, dict)]


_LEVER_TO_CONTRACT_FIELD: Dict[str, str] = {
  "expenses::Cost of Goods Sold": "cogs_percent_max",
  "expenses::Marketing": "marketing_percent_max",
  "expenses::Research & Development": "rd_percent_max",
  "expenses::General & Administrative": "g_and_a_percent_max",
  "expenses::Lease": "lease_percent_max",
}


def _contract_target_for_quarter(
  *,
  lever_id: str,
  quarter_index: int,
  stage_ramp_contract: Optional[Dict[str, Any]],
) -> Optional[float]:
  """Return the contract's target value for this lever at this quarter."""
  field_name = _LEVER_TO_CONTRACT_FIELD.get(lever_id)
  if not field_name:
    if lever_id.endswith("::Utilization"):
      field_name = "utilization_cap"
    else:
      return None
  rows = _quarter_ramp_grid_rows(stage_ramp_contract)
  for row in rows:
    qi = _safe_float(row.get("quarter_index"))
    if qi is None:
      continue
    if int(round(qi)) == int(quarter_index):
      return _safe_float(row.get(field_name))
  return None


def _contract_mature_target(
  *,
  lever_id: str,
  stage_ramp_contract: Optional[Dict[str, Any]],
  horizon: int,
) -> Optional[float]:
  """Return the contract's target at the maturity quarter (last quarter)."""
  rows = _quarter_ramp_grid_rows(stage_ramp_contract)
  if not rows:
    return None
  rows_sorted = sorted(
    rows,
    key=lambda r: int(round(_safe_float(r.get("quarter_index")) or 0)),
  )
  last = rows_sorted[-1]
  return _contract_target_for_quarter(
    lever_id=lever_id,
    quarter_index=int(round(_safe_float(last.get("quarter_index")) or horizon)),
    stage_ramp_contract=stage_ramp_contract,
  )


# ----------------------------------------------------------------------------
# Public path computation
# ----------------------------------------------------------------------------

@dataclass
class PathComputation:
  """Result of compute_per_quarter_values()."""

  lever_id: str
  shape_kind: str
  per_quarter_values: Optional[List[float]]   # None when shape is non-writable
  skip_write_reason: Optional[str]            # populated when path engine declines
  resolved_target: Optional[float]            # what the path converges toward
  start_value: Optional[float]                # value at Q1
  notes: str = ""

  def to_dict(self) -> Dict[str, Any]:
    return {
      "lever_id": self.lever_id,
      "shape_kind": self.shape_kind,
      "per_quarter_values": (
        list(self.per_quarter_values)
        if isinstance(self.per_quarter_values, list)
        else None
      ),
      "skip_write_reason": self.skip_write_reason,
      "resolved_target": self.resolved_target,
      "start_value": self.start_value,
      "notes": self.notes,
    }


def _stage_profile_from_policy(adaptive_policy: Optional[Dict[str, Any]]) -> str:
  if not isinstance(adaptive_policy, dict):
    return "operational"
  stage = str(adaptive_policy.get("stage_profile") or "").strip().lower()
  return stage or "operational"


def _viability_deadline(
  *,
  lever_id: str,
  adaptive_policy: Optional[Dict[str, Any]],
  default_q: int = 11,
) -> int:
  if not isinstance(adaptive_policy, dict):
    return default_q
  deadlines = adaptive_policy.get("viability_deadline_quarters") or {}
  if not isinstance(deadlines, dict):
    return default_q
  if lever_id.endswith("::Utilization"):
    return int(deadlines.get("payroll_ratio_mature") or default_q)
  if lever_id.endswith("::Unit Price"):
    return int(deadlines.get("ebitda_positive") or default_q)
  if lever_id.endswith("::Capacity"):
    return int(deadlines.get("ebitda_positive") or default_q)
  if lever_id in _LEVER_TO_CONTRACT_FIELD:
    return int(deadlines.get("ebitda_positive") or default_q)
  if "Days" in lever_id:
    return int(deadlines.get("working_capital_match") or 20)
  return default_q


def compute_per_quarter_values(
  *,
  lever_id: str,
  base_value: float,
  horizon: int,
  stage_ramp_contract: Optional[Dict[str, Any]] = None,
  adaptive_policy: Optional[Dict[str, Any]] = None,
  industry_target: Optional[float] = None,
) -> PathComputation:
  """Compute the Q1..Qhorizon path the writer should persist for ``lever_id``.

  ``base_value`` is the solver's chosen amplitude — the value the writer
  would have broadcast Q1..Qhorizon under the pre-Phase-C flat regime.
  The path engine reinterprets that scalar as the Q1 starting value and
  walks toward the contract / industry target via the registered shape.

  Returns a PathComputation. When ``per_quarter_values`` is None the
  writer must NOT overwrite the lever (schedule_locked, stock_carryforward,
  calculated, or unknown shape) — the existing machinery handles it.
  """
  shape = lookup_shape_for_lever(lever_id)
  start = float(base_value if base_value is not None else 0.0)
  stage = _stage_profile_from_policy(adaptive_policy)
  h = int(max(1, horizon))

  # Non-writable shapes — return signal only.
  if shape == SHAPE_HIRING_SCHEDULE:
    return PathComputation(
      lever_id=lever_id,
      shape_kind=shape,
      per_quarter_values=None,
      skip_write_reason="payroll owned by headcount_schedule",
      resolved_target=None,
      start_value=start,
    )
  if shape == SHAPE_CALCULATED:
    return PathComputation(
      lever_id=lever_id,
      shape_kind=shape,
      per_quarter_values=None,
      skip_write_reason="value derived from upstream rows",
      resolved_target=None,
      start_value=start,
    )
  if shape == SHAPE_STOCK_CARRYFORWARD:
    return PathComputation(
      lever_id=lever_id,
      shape_kind=shape,
      per_quarter_values=None,
      skip_write_reason="stock-level lever uses existing carryforward",
      resolved_target=None,
      start_value=start,
    )
  if shape == SHAPE_SCHEDULE_LOCKED:
    return PathComputation(
      lever_id=lever_id,
      shape_kind=shape,
      per_quarter_values=None,
      skip_write_reason="schedule-locked lever",
      resolved_target=None,
      start_value=start,
    )

  # Flat — broadcast the scalar (rent, distributions, statutory tax rate, etc.)
  if shape == SHAPE_FLAT:
    values = flat_path(start, horizon=h)
    return PathComputation(
      lever_id=lever_id,
      shape_kind=shape,
      per_quarter_values=values,
      skip_write_reason=None,
      resolved_target=start,
      start_value=start,
    )

  # All path-shaped writes need a target.
  contract_target = _contract_mature_target(
    lever_id=lever_id,
    stage_ramp_contract=stage_ramp_contract,
    horizon=h,
  )
  resolved_target: Optional[float] = None
  if industry_target is not None:
    resolved_target = float(industry_target)
  elif contract_target is not None:
    resolved_target = float(contract_target)

  if resolved_target is None:
    # No target available — fall back to flat broadcast so we don't
    # invent a trajectory.
    return PathComputation(
      lever_id=lever_id,
      shape_kind=SHAPE_FLAT,
      per_quarter_values=flat_path(start, horizon=h),
      skip_write_reason=None,
      resolved_target=start,
      start_value=start,
      notes=f"fallback to flat: no contract or industry target for {lever_id}",
    )

  deadline_q = _viability_deadline(lever_id=lever_id, adaptive_policy=adaptive_policy)

  if shape == SHAPE_LINEAR_TO_MATURE:
    values = linear_to_mature(start, resolved_target, horizon=h, deadline_q=deadline_q)
  elif shape == SHAPE_GLIDEPATH:
    values = glidepath(start, resolved_target, horizon=h, deadline_q=deadline_q)
  elif shape == SHAPE_S_CURVE:
    values = s_curve(start, resolved_target, horizon=h)
  elif shape == SHAPE_CAPACITY_EXPANSION:
    values = capacity_expansion(start, resolved_target, horizon=h, stage_profile=stage)
  elif shape == SHAPE_INDUSTRY_CONVERGENCE_DECAY:
    half_life = max(2, deadline_q // 2)
    values = industry_convergence_decay(start, resolved_target, horizon=h, half_life_q=half_life)
  else:  # pragma: no cover — defensive
    values = flat_path(start, horizon=h)

  return PathComputation(
    lever_id=lever_id,
    shape_kind=shape,
    per_quarter_values=values,
    skip_write_reason=None,
    resolved_target=resolved_target,
    start_value=start,
  )
