"""Deterministic floor — spec §9.

The floor is **not** a separate fallback system. It is the same cascade
machinery, run unattended with Python defaults at each Type A and Type B
step (§9.1):

  1. Replay attempted tiers with Python applying defaults at every step:
     - Type A: Python's proposal is auto-confirmed.
     - Type B: Python chooses option A (first option in priority order).
  2. Apply each step via the authoring tool's ``contract=None`` builder
     path or the corresponding ``revise_*`` tool.
  3. After each step, re-run ``evaluate_plan``. If the originating mode
     passes, floor succeeded for this mode.
  4. If all tiers including bound relaxation fail, apply the mode-
     specific **floor primitive** (§9.2).

The primitives are guaranteed to terminate (each is a finite
deterministic computation). They may produce a plan that some downstream
check still fails — that's acceptable per doctrine §10.6: the floor's
contract is to produce a committed, in-bounds, viable-in-the-floor's-
sense state, not a globally optimal plan.

The floor never consults GPT. The session driver (step 5d) invokes the
floor whenever a cascade exhausts, the protocol stagnates, or budget
hits the floor threshold (§8.4 / §8.6 / §8.7).
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Callable, Dict, List, Optional, Tuple

from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (
  FailureMode,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
  CascadeTier,
  get_cascade,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (
  AppliedBy,
  ReasonCode,
  StepType,
)


# ---------------------------------------------------------------------------
# Floor result shape
# ---------------------------------------------------------------------------

@dataclass
class FloorStepResult:
  """One step in the floor walk (audit + observability)."""
  tier_id: str
  tier_name: str
  reason_code: ReasonCode
  applied_by: AppliedBy
  step_type: StepType
  section: str
  field: Optional[str] = None
  applied_value: Optional[float] = None
  accepted: bool = True
  detail: str = ""


@dataclass
class FloorResult:
  """The floor's return shape (spec §9.4 — floor never skips audit).

  ``status`` is one of:
    - "resolved"           — cascade-as-floor brought the mode to passing
    - "primitive_applied"  — §9.2 primitive fired (guaranteed terminator)
    - "no_primitive"       — mode lacks a registered primitive (bug)
  """
  mode: FailureMode
  status: str
  steps: List[FloorStepResult] = dc_field(default_factory=list)
  primitive_reason: Optional[ReasonCode] = None
  detail: str = ""


# ---------------------------------------------------------------------------
# Primitive registry — spec §9.2
# ---------------------------------------------------------------------------
#
# Each primitive takes the mirror/inputs the session driver supplies and
# returns a list of FloorStepResult records (the floor's audit trail for
# this primitive). The primitives themselves are wrappers around existing
# K13 utilities (apply_viability_floor for VIABILITY, reconcile_revenue_
# to_stage_ramp for GROWTH) and three new deterministic computations
# (capacity resize, band clip, coherence forced reconciliation).
#
# The wrappers exist here so the session driver has a single dispatch
# table; the actual K13 functions still live in post_intake_gpt_exhaustion_
# handler.handler unchanged. The new primitives (CAPACITY/BAND/COHERENCE)
# compute their result from the mirror + evaluate_plan state alone.


PrimitiveResult = List[FloorStepResult]
Primitive = Callable[..., PrimitiveResult]


def _step(
  *, mode: FailureMode, primitive_reason: ReasonCode,
  section: str, field: Optional[str] = None,
  applied_value: Optional[float] = None, accepted: bool = True,
  detail: str = "",
) -> FloorStepResult:
  tier_id, tier_name = _floor_primitive_tier_handles(mode)
  return FloorStepResult(
    tier_id=tier_id, tier_name=tier_name,
    reason_code=primitive_reason,
    applied_by=AppliedBy.FLOOR_PRIMITIVE,
    step_type=StepType.FLOOR,
    section=section, field=field,
    applied_value=applied_value,
    accepted=accepted, detail=detail,
  )


def _floor_primitive_tier_handles(mode: FailureMode) -> Tuple[str, str]:
  """Return (tier_id, tier_name) for the audit log when a primitive
  fires. The tier_id is the cascade's final tier; the tier_name is
  augmented with ' primitive' to distinguish from the cascade-as-floor
  walk."""
  tiers = get_cascade(mode)
  if not tiers:
    return ("--", "primitive")
  last = tiers[-1]
  return (last.tier_id, f"{last.name} primitive")


# ---------------------------------------------------------------------------
# VIABILITY primitive — wraps K13 Fix 3 apply_viability_floor
# ---------------------------------------------------------------------------

def viability_floor_primitive(
  *,
  model_input: Optional[Dict[str, Any]] = None,
  build_finmo: Optional[Callable[..., Any]] = None,
  stage_ramp_contract: Optional[Dict[str, Any]] = None,
  _apply_viability_floor: Optional[Callable[..., Dict[str, Any]]] = None,
) -> PrimitiveResult:
  """Wrap K13 Fix 3 ``apply_viability_floor``.

  Pulls cost ratios to realistic targets and steps COGS down (floor 0.20)
  until Q11 EBITDA >= 0. Committed even if other invariants degrade.
  Logs VIABILITY_FLOOR_PRIMITIVE.
  """
  fn = _apply_viability_floor
  if fn is None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (  # type: ignore
      apply_viability_floor,
    )
    fn = apply_viability_floor

  try:
    result = fn(
      model_input=model_input or {},
      build_finmo=build_finmo,
      stage_ramp_contract=stage_ramp_contract or {},
    )
  except Exception as exc:
    return [_step(
      mode=FailureMode.VIABILITY_INVARIANT,
      primitive_reason=ReasonCode.VIABILITY_FLOOR_PRIMITIVE,
      section="*", accepted=False,
      detail=f"apply_viability_floor raised: {type(exc).__name__}: {str(exc)[:300]}",
    )]

  if not isinstance(result, dict):
    return [_step(
      mode=FailureMode.VIABILITY_INVARIANT,
      primitive_reason=ReasonCode.VIABILITY_FLOOR_PRIMITIVE,
      section="*", accepted=False,
      detail="apply_viability_floor returned non-dict",
    )]

  applied_cogs = result.get("applied_cogs")
  return [_step(
    mode=FailureMode.VIABILITY_INVARIANT,
    primitive_reason=ReasonCode.VIABILITY_FLOOR_PRIMITIVE,
    section="drivers", field="expenses::Cost of Goods Sold",
    applied_value=float(applied_cogs) if isinstance(applied_cogs, (int, float)) else None,
    accepted=True,
    detail=(
      f"K13 Fix 3 apply_viability_floor committed; Q11 EBITDA "
      f"{result.get('q11_ebitda_after')!r}"
    ),
  )]


# ---------------------------------------------------------------------------
# GROWTH primitive — wraps K13 Fix 4 reconcile_revenue_to_stage_ramp
# ---------------------------------------------------------------------------

def growth_floor_primitive(
  *,
  model_input: Optional[Dict[str, Any]] = None,
  build_finmo: Optional[Callable[..., Any]] = None,
  stage_ramp_contract: Optional[Dict[str, Any]] = None,
  max_passes: int = 12,
  _reconcile: Optional[Callable[..., Dict[str, Any]]] = None,
) -> PrimitiveResult:
  """Wrap K13 Fix 4 ``reconcile_revenue_to_stage_ramp``.

  Clamps driver-implied revenue QoQ growth to the band by scaling
  utilization, then price. Committed. Logs GROWTH_FLOOR_PRIMITIVE.
  """
  fn = _reconcile
  if fn is None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (  # type: ignore
      reconcile_revenue_to_stage_ramp,
    )
    fn = reconcile_revenue_to_stage_ramp

  try:
    result = fn(
      model_input=model_input or {},
      build_finmo=build_finmo,
      stage_ramp_contract=stage_ramp_contract or {},
      max_passes=max_passes,
    )
  except Exception as exc:
    return [_step(
      mode=FailureMode.GROWTH_INVARIANT,
      primitive_reason=ReasonCode.GROWTH_FLOOR_PRIMITIVE,
      section="*", accepted=False,
      detail=f"reconcile_revenue_to_stage_ramp raised: {type(exc).__name__}: {str(exc)[:300]}",
    )]

  applied_util = result.get("applied_utilization") if isinstance(result, dict) else None
  return [_step(
    mode=FailureMode.GROWTH_INVARIANT,
    primitive_reason=ReasonCode.GROWTH_FLOOR_PRIMITIVE,
    section="operating_model", field="utilization_rate",
    applied_value=float(applied_util) if isinstance(applied_util, (int, float)) else None,
    accepted=True,
    detail=(
      f"K13 Fix 4 reconcile_revenue_to_stage_ramp committed; passes="
      f"{result.get('passes_used') if isinstance(result, dict) else None}"
    ),
  )]


# ---------------------------------------------------------------------------
# CAPACITY primitive — resize capacity to support target revenue
# ---------------------------------------------------------------------------

def capacity_floor_primitive(
  *,
  target_q12_revenue: Optional[float] = None,
  unit_price: Optional[float] = None,
  cohort_util_target: Optional[float] = None,
) -> PrimitiveResult:
  """Resize ``units_per_week_capacity`` to support the target Q12 revenue
  at cohort-target utilization (spec §9.2 CAPACITY primitive formula):

    units_per_week_capacity = ceil(target_q12_revenue /
                                   (52 * unit_price * cohort_util_target))
  """
  import math as _math
  errors: List[str] = []
  if target_q12_revenue is None or target_q12_revenue <= 0:
    errors.append("missing target_q12_revenue")
  if unit_price is None or unit_price <= 0:
    errors.append("missing unit_price")
  if cohort_util_target is None or cohort_util_target <= 0:
    errors.append("missing cohort_util_target")
  if errors:
    return [_step(
      mode=FailureMode.CAPACITY_INVARIANT,
      primitive_reason=ReasonCode.CAPACITY_FLOOR_PRIMITIVE,
      section="operating_model", field="units_per_week_capacity",
      accepted=False,
      detail="missing inputs: " + ", ".join(errors),
    )]

  required = float(target_q12_revenue) / (52.0 * float(unit_price) * float(cohort_util_target))
  required_capacity = float(_math.ceil(required))
  return [_step(
    mode=FailureMode.CAPACITY_INVARIANT,
    primitive_reason=ReasonCode.CAPACITY_FLOOR_PRIMITIVE,
    section="operating_model", field="units_per_week_capacity",
    applied_value=required_capacity,
    accepted=True,
    detail=(
      f"resized to support target_q12_revenue={target_q12_revenue} at "
      f"unit_price={unit_price} × cohort_util_target={cohort_util_target}"
    ),
  )]


# ---------------------------------------------------------------------------
# BAND primitive — clip every out-of-band lever to its nearest band edge
# ---------------------------------------------------------------------------

def band_floor_primitive(
  *,
  lever_margins: Optional[List[Any]] = None,
) -> PrimitiveResult:
  """Clip every out-of-band lever to its nearest band edge.

  Reads from the EvaluatePlanResult's lever_margins. For each margin
  with ``outside_band=True``, emit a step that clips ``current`` to the
  nearer of ``band_min`` / ``band_max``. The session driver applies the
  clips via the corresponding ``revise_*`` tool.
  """
  steps: List[FloorStepResult] = []
  margins = lever_margins or []
  if not margins:
    return [_step(
      mode=FailureMode.BAND_INVARIANT,
      primitive_reason=ReasonCode.BAND_FLOOR_PRIMITIVE,
      section="*", accepted=True,
      detail="no lever_margins to inspect — no-op",
    )]

  for m in margins:
    if not getattr(m, "outside_band", False):
      continue
    current = getattr(m, "current", None)
    bmin = getattr(m, "band_min", None)
    bmax = getattr(m, "band_max", None)
    if current is None or (bmin is None and bmax is None):
      continue
    if bmin is not None and current < bmin:
      target = float(bmin)
    elif bmax is not None and current > bmax:
      target = float(bmax)
    else:
      continue
    steps.append(_step(
      mode=FailureMode.BAND_INVARIANT,
      primitive_reason=ReasonCode.BAND_FLOOR_PRIMITIVE,
      section=getattr(m, "section", "*"),
      field=getattr(m, "lever_id", None),
      applied_value=target,
      accepted=True,
      detail=f"clipped from {current!r} to nearest band edge",
    ))

  if not steps:
    steps.append(_step(
      mode=FailureMode.BAND_INVARIANT,
      primitive_reason=ReasonCode.BAND_FLOOR_PRIMITIVE,
      section="*", accepted=True,
      detail="no out-of-band levers found — no-op",
    ))
  return steps


# ---------------------------------------------------------------------------
# COHERENCE primitive — forced reconciliation via anchor
# ---------------------------------------------------------------------------

def coherence_floor_primitive(
  *,
  anchor_section: Optional[str] = None,
  non_anchor_sections: Optional[List[str]] = None,
) -> PrimitiveResult:
  """Re-author every non-anchor section from the anchor's implied values
  (forced reconciliation, regardless of tolerance).

  Per spec §9.2 — the cascade caller supplies the chosen anchor; defaults
  to the §14.2 authority order's first entry (stage_ramp). Each non-
  anchor section is rebuilt via its ``set_*(contract=None)`` builder
  with anchor-derived inputs; this primitive just records the intent
  per section. The session driver does the actual rebuild calls.
  """
  from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
    coherence_anchor_order,
  )
  order = coherence_anchor_order()
  anchor = anchor_section or order[0]
  non_anchors = non_anchor_sections if non_anchor_sections is not None else [
    s for s in order if s != anchor
  ]
  steps: List[FloorStepResult] = [_step(
    mode=FailureMode.COHERENCE_INVARIANT,
    primitive_reason=ReasonCode.COHERENCE_FLOOR_PRIMITIVE,
    section=anchor, accepted=True,
    detail=f"forced reconciliation anchor = {anchor}",
  )]
  for sec in non_anchors:
    steps.append(_step(
      mode=FailureMode.COHERENCE_INVARIANT,
      primitive_reason=ReasonCode.COHERENCE_FLOOR_PRIMITIVE,
      section=sec, accepted=True,
      detail=f"re-author from {anchor}-derived inputs",
    ))
  return steps


# ---------------------------------------------------------------------------
# Primitive dispatch
# ---------------------------------------------------------------------------

PRIMITIVES: Dict[FailureMode, Primitive] = {
  FailureMode.VIABILITY_INVARIANT:  viability_floor_primitive,
  FailureMode.GROWTH_INVARIANT:     growth_floor_primitive,
  FailureMode.CAPACITY_INVARIANT:   capacity_floor_primitive,
  FailureMode.BAND_INVARIANT:       band_floor_primitive,
  FailureMode.COHERENCE_INVARIANT:  coherence_floor_primitive,
}


def apply_floor_primitive(mode: FailureMode, **kwargs: Any) -> FloorResult:
  """Dispatch to the registered §9.2 primitive for ``mode``.

  The session driver passes mode-appropriate inputs as kwargs (e.g.
  ``target_q12_revenue`` / ``unit_price`` / ``cohort_util_target`` for
  CAPACITY; ``lever_margins`` for BAND; ``anchor_section`` /
  ``non_anchor_sections`` for COHERENCE; ``model_input`` /
  ``build_finmo`` / ``stage_ramp_contract`` for VIABILITY+GROWTH).
  """
  prim = PRIMITIVES.get(mode)
  if prim is None:
    return FloorResult(
      mode=mode, status="no_primitive",
      detail=f"no §9.2 floor primitive registered for {mode.value}",
    )
  steps = prim(**kwargs)
  reason = (
    steps[0].reason_code if steps else None
  )
  return FloorResult(
    mode=mode, status="primitive_applied",
    steps=steps, primitive_reason=reason,
    detail=f"§9.2 {mode.value} primitive completed in {len(steps)} steps",
  )


# ---------------------------------------------------------------------------
# Cascade-as-floor walker (§9.1)
# ---------------------------------------------------------------------------
#
# The cascade-as-floor walker is the "same machinery, run unattended"
# part of the floor. Full integration with the proposer + revise_* tools
# happens in the session driver (step 5d), which has the live mirror
# state. Here we expose the orchestration scaffolding the driver wires
# into: ``floor_for_mode`` runs the cascade-as-floor pass (currently a
# pass-through to the primitive — the driver supplies the walker
# callback) then falls back to the primitive if needed.


def floor_for_mode(
  mode: FailureMode,
  *,
  cascade_walker: Optional[Callable[..., FloorResult]] = None,
  primitive_kwargs: Optional[Dict[str, Any]] = None,
) -> FloorResult:
  """Floor entry point — try cascade-as-floor (if a walker is wired in),
  otherwise go straight to the §9.2 primitive.

  ``cascade_walker`` is the session driver's unattended cascade pass:
  same proposer + revise_* tools as the GPT-driven cascade but with
  every Type A auto-confirmed and every Type B picking option A. The
  driver supplies this callback; tests inject fakes. When the walker
  returns status='resolved', the primitive is skipped.
  """
  if cascade_walker is not None:
    walker_result = cascade_walker(mode=mode)
    if walker_result.status == "resolved":
      return walker_result
  return apply_floor_primitive(mode, **(primitive_kwargs or {}))


__all__ = [
  "FloorStepResult",
  "FloorResult",
  "PRIMITIVES",
  "viability_floor_primitive",
  "growth_floor_primitive",
  "capacity_floor_primitive",
  "band_floor_primitive",
  "coherence_floor_primitive",
  "apply_floor_primitive",
  "floor_for_mode",
]
