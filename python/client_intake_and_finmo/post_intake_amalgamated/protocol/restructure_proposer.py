"""Per-tier Python proposal builders (spec §6 + §4.3 + §4.2).

Given a cascade tier and the diagnostic state from ``evaluate_plan`` +
the mirror, the proposer computes:

  - For Type A tiers: a single ``Proposal`` with
    (section, field, current_value, proposed_value, rationale_text,
    reason_code) the session driver presents via the §6.3 Type A
    template.
  - For Type B tiers: 2-3 candidate ``Proposal`` records labelled
    A/B/C with tradeoff text the session driver presents via the §6.3
    Type B template.
  - ``None``: when smart entry (§4.2) determines every lever in the tier
    is pinned to its non-favorable edge — the session driver advances
    to the next tier without consulting GPT.

Lever priority within a tier is mechanical (§4.3, the manager's call,
not GPT's): the proposer picks the highest-priority lever that still
has headroom, breaking ties by CascadeLever.priority then by
distance-to-target. GPT does not pick which lever within a tier.

Target rules ("to_band_target", "to_band_max", etc.) resolve against
the lever's LeverMargin from the EvaluatePlanResult — that's the
authoritative source for cohort bands during a session (the mirror
caches the same data; both are equivalent reads).

Type B tier option generators (V3/V6/G3/G5/C4/B3/H1) live in
``_TYPE_B_GENERATORS`` — each is a small function that, given the tier
+ diagnostics, returns 2-3 option proposals. Adding a Type B tier
requires registering its generator here.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (
  EvaluatePlanResult,
  FailureMode,
  LeverMargin,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
  CascadeLever,
  CascadeTier,
  BOUND_RELAXATION_STEP_FRACTION,
  coherence_anchor_order,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (
  ReasonCode,
  StepType,
)


# ---------------------------------------------------------------------------
# Proposal shape
# ---------------------------------------------------------------------------

@dataclass
class Proposal:
  """One proposed adjustment the session driver presents to GPT.

  Type A: the proposer returns a single Proposal. The session driver
  fills the §6.3 Type A template, GPT confirms or vetoes.

  Type B: the proposer returns a list of 2-3 Proposals labelled A/B/C
  (option_id). Each carries tradeoff_text describing the trade-off in
  one sentence.
  """
  mode: FailureMode
  tier_id: str
  tier_name: str
  step_type: StepType
  reason_code: ReasonCode
  section: str
  field: str
  current_value: Optional[float] = None
  proposed_value: Optional[float] = None
  quarter_index: Optional[int] = None
  rationale_text: str = ""
  band_min: Optional[float] = None
  band_target: Optional[float] = None
  band_max: Optional[float] = None
  pinning_summary: str = ""
  # Type B only
  option_id: Optional[str] = None
  tradeoff_text: str = ""
  summary: str = ""


# ---------------------------------------------------------------------------
# Lever-margin helpers
# ---------------------------------------------------------------------------

def _find_margin(
  margins: List[LeverMargin],
  section: str,
  field: str,
) -> Optional[LeverMargin]:
  """Return the LeverMargin matching (section, field). lever_id matching
  is liberal: we accept either the full ``"section::field"`` style or
  the ``"field"``-only style emitted by some sections.
  """
  if not isinstance(margins, list):
    return None
  candidates = []
  for m in margins:
    if m.section != section:
      continue
    if m.lever_id == field:
      candidates.append(m)
    elif m.lever_id.endswith(f"::{field}") or m.lever_id == f"{section}::{field}":
      candidates.append(m)
  if not candidates:
    return None
  # Prefer the quarter=None (scalar) margin if multiple exist.
  candidates.sort(key=lambda m: (m.quarter is None, m.quarter or 0), reverse=True)
  return candidates[0]


def _pinning_summary(margin: LeverMargin) -> str:
  if margin.outside_band:
    return "outside band"
  if margin.pinned_max and margin.pinned_min:
    return "pinned at both edges (zero-width band)"
  if margin.pinned_max:
    return "pinned to band_max"
  if margin.pinned_min:
    return "pinned to band_min"
  return "in band with headroom"


def _is_unfavorable_pinned(margin: LeverMargin, direction: str) -> bool:
  """Return True iff the lever is pinned to the edge that would prevent
  this direction's intended move."""
  if direction == "to_band_target":
    # If we're already AT target (within a small epsilon) there's no
    # useful move; treat as pinned for smart-entry purposes.
    if margin.current is not None and margin.band_target is not None:
      return abs(margin.current - margin.band_target) < 1e-9
    return False
  if direction in ("to_band_max", "to_favorable_edge"):
    return bool(margin.pinned_max)
  if direction == "to_band_min":
    return bool(margin.pinned_min)
  if direction == "to_band_edge":
    return bool(margin.pinned_min and margin.pinned_max)
  # shape / scale / relax_robust_max / rebuild / choose_anchor / swap_anchor:
  # never blocked by pinning at this layer.
  return False


def _target_from_direction(
  direction: str,
  margin: LeverMargin,
) -> Optional[float]:
  if direction == "to_band_target":
    return margin.band_target
  if direction == "to_band_max":
    return margin.band_max
  if direction == "to_band_min":
    return margin.band_min
  if direction == "to_band_edge":
    # Clip to whichever edge is nearer (only meaningful when outside_band).
    if margin.current is None:
      return margin.band_target
    if margin.band_min is not None and margin.current < margin.band_min:
      return margin.band_min
    if margin.band_max is not None and margin.current > margin.band_max:
      return margin.band_max
    return margin.band_target
  if direction == "to_favorable_edge":
    # Default favorable edge for viability is band_min (lower cost ratio).
    return margin.band_min
  return None


# ---------------------------------------------------------------------------
# Lever picker — §4.3
# ---------------------------------------------------------------------------

def _pick_lever(
  tier: CascadeTier,
  margins: List[LeverMargin],
) -> Optional[Tuple[CascadeLever, Optional[LeverMargin]]]:
  """Choose the highest-priority lever that isn't unfavorably pinned.

  Returns (lever, margin) or None if every lever in the tier is pinned.
  margin can be None for non-band-tracked levers (capacity, payroll
  counts) — the proposer will then fall back to a deterministic default.
  """
  # C1 (spec §4.3) — sort keys in priority order:
  #   1. outside_band (True before False)               — rule 1
  #   2. computed viability_impact (larger first)       — rule 2 (DYNAMIC)
  #   3. CascadeLever.priority (1 before 2 before 3)    — rule 3 (tiebreak)
  #   4. distance from band_target (larger first)       — final tiebreak
  #
  # Rule 2 used to be hard-coded to CascadeLever.priority (which made
  # it indistinguishable from rule 3). Now it's a computed impact:
  #
  #   impact = abs(current - proposed_target) * viability_weight_factor
  #
  # When two candidates tie on outside_band (rule 1), the lever with
  # larger computed impact wins — even if its declared priority is
  # lower. This gives the proposer a way to express "this lever has a
  # bigger lever-arm" without rewriting the cascade table.
  candidates: List[Tuple[CascadeLever, Optional[LeverMargin], bool, float, int, float]] = []
  for lever in tier.levers:
    margin = _find_margin(margins, lever.section, lever.field)
    if margin is None:
      # Non-band-tracked lever — accept with neutral impact score.
      candidates.append((lever, None, False, 0.0, lever.priority, 0.0))
      continue
    if _is_unfavorable_pinned(margin, lever.direction):
      continue
    distance = 0.0
    if margin.current is not None and margin.band_target is not None:
      distance = abs(margin.current - margin.band_target)
    # Compute viability impact for rule 2.
    target = _target_from_direction(lever.direction, margin)
    if (margin.current is not None and isinstance(target, (int, float))):
      move_magnitude = abs(float(margin.current) - float(target))
    else:
      move_magnitude = distance
    weight = float(getattr(lever, "viability_weight_factor", 1.0) or 1.0)
    impact = move_magnitude * weight
    candidates.append((
      lever, margin,
      bool(margin.outside_band),   # rule 1
      impact,                       # rule 2 — dynamic
      lever.priority,               # rule 3 — declared priority tiebreak
      distance,                     # final tiebreak
    ))

  if not candidates:
    return None

  candidates.sort(key=lambda t: (not t[2], -t[3], t[4], -t[5]))
  best_lever, best_margin, _, _, _, _ = candidates[0]
  return best_lever, best_margin


# ---------------------------------------------------------------------------
# Type A proposer
# ---------------------------------------------------------------------------

def _type_a_proposal(
  mode: FailureMode,
  tier: CascadeTier,
  result: EvaluatePlanResult,
) -> Optional[Proposal]:
  picked = _pick_lever(tier, result.lever_margins or [])
  if picked is None:
    return None
  lever, margin = picked

  if tier.is_bound_relaxation:
    # Bound relaxation does not propose a new current/proposed value — it
    # relaxes the band's robust_max (or robust_min). The applied_value
    # column in the audit row records the relaxed bound, not a lever
    # value (the session driver wires this through to log_restructure
    # with proposed_value = current_value, applied_value = relaxed bound).
    band_max = margin.band_max if margin is not None else None
    relaxed_max = (
      band_max * (1.0 + BOUND_RELAXATION_STEP_FRACTION)
      if isinstance(band_max, (int, float)) else None
    )
    return Proposal(
      mode=mode, tier_id=tier.tier_id, tier_name=tier.name,
      step_type=StepType.TYPE_A, reason_code=tier.reason_code,
      section=lever.section, field=lever.field,
      current_value=margin.current if margin else None,
      proposed_value=relaxed_max,
      band_min=margin.band_min if margin else None,
      band_target=margin.band_target if margin else None,
      band_max=band_max,
      pinning_summary=_pinning_summary(margin) if margin else "no margin recorded",
      rationale_text=(
        f"Relax {lever.field}'s robust_max by "
        f"{int(BOUND_RELAXATION_STEP_FRACTION * 100)}% so the cascade can "
        f"re-attempt earlier tiers with a wider feasible region."
      ),
    )

  # Standard band-driven Type A proposal.
  if margin is None or margin.current is None:
    # Non-band lever — emit a placeholder proposal the session driver
    # routes via the deterministic-floor builder.
    return Proposal(
      mode=mode, tier_id=tier.tier_id, tier_name=tier.name,
      step_type=StepType.TYPE_A, reason_code=tier.reason_code,
      section=lever.section, field=lever.field,
      current_value=None, proposed_value=None,
      pinning_summary="no margin (non-band lever)",
      rationale_text=(
        f"{tier.name}: pull {lever.section}.{lever.field} per "
        f"{tier.target_rule}. No band margin tracked for this lever — "
        f"applied via the section's deterministic builder."
      ),
    )

  proposed = _target_from_direction(lever.direction, margin)
  worst_check = result.worst_failing_check or "(no specific failing check)"
  worst_distance = result.worst_failing_distance
  worst_phrase = (
    f"{worst_check} (currently {worst_distance:+.4f})"
    if isinstance(worst_distance, (int, float))
    else worst_check
  )
  return Proposal(
    mode=mode, tier_id=tier.tier_id, tier_name=tier.name,
    step_type=StepType.TYPE_A, reason_code=tier.reason_code,
    section=lever.section, field=lever.field,
    current_value=margin.current, proposed_value=proposed,
    band_min=margin.band_min, band_target=margin.band_target,
    band_max=margin.band_max,
    pinning_summary=_pinning_summary(margin),
    rationale_text=(
      f"{tier.name}: pull {lever.field} from {margin.current:.4f} to "
      f"{('%.4f' % proposed) if proposed is not None else 'band default'} "
      f"({tier.target_rule}). Failing check: {worst_phrase}."
    ),
  )


# ---------------------------------------------------------------------------
# Type B option generators
# ---------------------------------------------------------------------------

def _type_b_pricing(
  mode: FailureMode,
  tier: CascadeTier,
  result: EvaluatePlanResult,
) -> List[Proposal]:
  """V3 (VIABILITY pricing) and G3 (GROWTH pricing).

  Two named positioning calls — premium (raise) vs. value (lower).
  """
  margin = _find_margin(result.lever_margins or [], "operating_model", "unit_price")
  options: List[Proposal] = []

  premium_target = margin.band_max if margin else None
  value_target   = margin.band_min if margin else None
  current        = margin.current  if margin else None
  base = Proposal(
    mode=mode, tier_id=tier.tier_id, tier_name=tier.name,
    step_type=StepType.TYPE_B, reason_code=tier.reason_code,
    section="operating_model", field="unit_price",
    current_value=current,
    band_min=value_target, band_target=margin.band_target if margin else None,
    band_max=premium_target,
    pinning_summary=_pinning_summary(margin) if margin else "no margin",
  )

  options.append(Proposal(
    **{**base.__dict__,
       "option_id": "A",
       "proposed_value": premium_target,
       "summary": "Premium positioning — raise unit_price to band_max.",
       "tradeoff_text": (
         "Higher gross margin per unit; risks softer volume if buyers "
         "are price-sensitive in this cohort."
       ),
       "rationale_text": (
         f"Raise unit_price toward band_max ({premium_target}); favors "
         f"viability via margin improvement."
       )}
  ))
  options.append(Proposal(
    **{**base.__dict__,
       "option_id": "B",
       "proposed_value": value_target,
       "summary": "Value positioning — lower unit_price to band_min.",
       "tradeoff_text": (
         "Higher unit volume potential; lower margin per unit. "
         "Suits a brand competing on accessibility."
       ),
       "rationale_text": (
         f"Lower unit_price toward band_min ({value_target}); favors "
         f"growth via volume."
       )}
  ))
  return options


def _type_b_target_compression(
  mode: FailureMode,
  tier: CascadeTier,
  result: EvaluatePlanResult,
) -> List[Proposal]:
  """G5 / C4 — compress target revenue trajectory.

  Three named compressions: 0.75×, 0.50×, 0.25× of the originally
  authored target ramp. The session driver applies via revise_stage_ramp
  with a scale factor.
  """
  options: List[Proposal] = []
  for option_id, scale, summary, tradeoff in (
    ("A", 0.75, "Compress target to 75% of original",
     "Modest compression; preserves most of the growth ambition."),
    ("B", 0.50, "Compress target to 50% of original",
     "Halve the growth target; reaches feasibility with material concession."),
    ("C", 0.25, "Compress target to 25% of original",
     "Heavy compression; mostly preserves baseline operations, modest growth."),
  ):
    options.append(Proposal(
      mode=mode, tier_id=tier.tier_id, tier_name=tier.name,
      step_type=StepType.TYPE_B, reason_code=tier.reason_code,
      section="stage_ramp", field="revenue_path",
      current_value=1.0, proposed_value=scale,
      option_id=option_id, summary=summary, tradeoff_text=tradeoff,
      rationale_text=(
        f"{tier.name}: scale revenue_path by {scale:.2f} so the ramp "
        f"plateaus at the physically feasible ceiling."
      ),
    ))
  return options


def _type_b_payroll_restructure(
  mode: FailureMode,
  tier: CascadeTier,
  result: EvaluatePlanResult,
) -> List[Proposal]:
  """V6 — payroll restructure. Three abstract class-cut options the
  session driver translates into a revise_payroll patch."""
  options: List[Proposal] = []
  for option_id, class_target, summary, tradeoff in (
    ("A", "general_and_administrative",
     "Cut G&A headcount to band-target payroll %-of-revenue",
     "Lowest operational impact; G&A is typically the highest-headroom class."),
    ("B", "sales_and_marketing",
     "Cut sales/marketing headcount",
     "Slows growth but preserves operations; defensible at early stage."),
    ("C", "research_and_development",
     "Cut R&D headcount",
     "Preserves operations and growth motion; sacrifices product velocity."),
  ):
    options.append(Proposal(
      mode=mode, tier_id=tier.tier_id, tier_name=tier.name,
      step_type=StepType.TYPE_B, reason_code=tier.reason_code,
      section="payroll", field=f"classes.{class_target}",
      option_id=option_id, summary=summary, tradeoff_text=tradeoff,
      rationale_text=(
        f"V6 payroll restructure: shrink {class_target} FTE counts so "
        f"payroll %-of-revenue lands at the cohort band target."
      ),
    ))
  return options


def _type_b_band_relaxation(
  mode: FailureMode,
  tier: CascadeTier,
  result: EvaluatePlanResult,
) -> List[Proposal]:
  """B3 — judgment-call band relaxation. Two options: relax robust_max
  on the offending lever vs. rebuild the offending section."""
  outside = [m for m in (result.lever_margins or []) if m.outside_band]
  worst = outside[0] if outside else None
  field_name = worst.lever_id if worst else "(no out-of-band lever found)"
  section    = worst.section  if worst else "*"
  return [
    Proposal(
      mode=mode, tier_id=tier.tier_id, tier_name=tier.name,
      step_type=StepType.TYPE_B, reason_code=tier.reason_code,
      section=section, field=field_name, option_id="A",
      summary="Relax the offending band (rare; lever is structurally extreme for valid reasons).",
      tradeoff_text="Widens the realism envelope for this run only; logged in restructuring_log.",
      rationale_text=(
        f"BAND relaxation on {field_name}: relax robust_max by "
        f"{int(BOUND_RELAXATION_STEP_FRACTION * 100)}% step."
      ),
    ),
    Proposal(
      mode=mode, tier_id=tier.tier_id, tier_name=tier.name,
      step_type=StepType.TYPE_B, reason_code=tier.reason_code,
      section=section, field=field_name, option_id="B",
      summary="Rebuild the section from cohort defaults instead.",
      tradeoff_text="Discards the offending values; safer when no business reason backs the extreme.",
      rationale_text=(
        f"BAND rebuild: re-author section {section} via "
        f"set_*(contract=None) builder path."
      ),
    ),
  ]


_TYPE_B_GENERATORS: Dict[str, Callable[..., List[Proposal]]] = {
  "V3": _type_b_pricing,
  "V6": _type_b_payroll_restructure,
  "G3": _type_b_pricing,
  "G5": _type_b_target_compression,
  "C4": _type_b_target_compression,
  "B3": _type_b_band_relaxation,
}


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def propose_for_tier(
  mode: FailureMode,
  tier: CascadeTier,
  result: EvaluatePlanResult,
) -> Union[None, Proposal, List[Proposal]]:
  """Build the proposal(s) for ``tier`` given the current diagnostic state.

  Smart entry (§4.2): when every lever in the tier is unfavorably pinned
  the function returns ``None`` — the session driver advances to the
  next tier without calling GPT.

  Type A tiers return a single ``Proposal``. Type B tiers return a list
  of 2-3 ``Proposal`` records labelled A/B/C with tradeoff_text.

  Floor tiers (the last per cascade) and the META tier are not the
  proposer's concern — the session driver routes them to ``floor.py``
  and the META halt path respectively without calling this function.
  """
  if tier.step_type == StepType.FLOOR or tier.is_floor:
    raise ValueError(
      f"propose_for_tier called on floor tier {tier.tier_id!r}; the "
      f"session driver should route floors to floor.py, not the proposer"
    )

  if tier.step_type == StepType.TYPE_A:
    return _type_a_proposal(mode, tier, result)

  if tier.step_type == StepType.TYPE_B:
    gen = _TYPE_B_GENERATORS.get(tier.tier_id)
    if gen is None:
      raise KeyError(
        f"Type B tier {tier.tier_id!r} has no registered option "
        f"generator in _TYPE_B_GENERATORS (proposer is incomplete for "
        f"this tier — every Type B tier in spec §5 must register here)"
      )
    options = gen(mode, tier, result)
    return options if options else None

  raise ValueError(f"unhandled step_type {tier.step_type!r} on tier {tier.tier_id!r}")


__all__ = [
  "Proposal",
  "propose_for_tier",
]
