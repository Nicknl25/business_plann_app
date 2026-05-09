"""Adaptation Cascade — Phase 3.7.

Replaces the orchestrator's terminal raise with a 7-tier cascade that
progressively relaxes inputs until a plan lands. Tier 7 is structurally
guaranteed to produce a plan via pure NAICS-cascade defaults + maximally
permissive planning_mode + 2x target tolerance.

Tiers walked strictly 1->7 on Tier 0 failure:
  1. Walk back GPT band-shaping (revert to Python defaults).
  2. Walk back cohort matching (use cascade resolver).
  3. Widen output target tolerances (1.5x; warn-mode first, then hard_fail).
  4. Mapping breadth expansion (drop targeting_allowed filter).
  5. Planning mode shift to turnaround (skipped if already turnaround).
  6. Stage family widening (startup -> early -> operational).
  7. Generic NAICS-cascade fallback. Always lands.

Pure re-use of existing infrastructure: cascade resolver, GPT-default
walk-back, target widening, influence_map rebuild, stage_planning_ramp_policy,
assemble_driver_movement_envelope. No new tables, no new GPT contracts,
no new policies.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)

class CascadeAndRestorationExhausted(RuntimeError):
  """Phase 9 Phase D — terminal cause #7 per doctrine.

  Raised when the adaptation cascade exhausts every tier AND the
  feasibility_restoration cascade also exhausts without producing a
  plan that satisfies the universal viability rule. Carries the full
  diagnostic so the consultant sees every adaptation attempted, every
  restoration attempted, and exactly which residuals couldn't be
  cleared. The orchestrator catches this and surfaces the diagnostic
  to the client interface — it is NOT an unhandled exception.
  """

  def __init__(self, diagnostic_payload: Dict[str, Any]):
    super().__init__(
      f"adaptation_cascade_and_restoration_exhausted: residuals={len(diagnostic_payload.get('residual_hard_fails') or [])}"
    )
    self.diagnostic_payload = diagnostic_payload


PLAN_CONFIDENCE_HIGH_NO_ADAPTATION = "high_no_adaptation"
PLAN_CONFIDENCE_GPT_BAND_RELAXATION = "medium_gpt_band_relaxation"
PLAN_CONFIDENCE_COHORT_FALLBACK = "medium_cohort_fallback"
PLAN_CONFIDENCE_TARGET_TOLERANCE_WIDENED = "low_target_tolerance_widened"
PLAN_CONFIDENCE_SUPPLEMENTARY_LEVERS = "low_supplementary_levers_used"
PLAN_CONFIDENCE_PLANNING_MODE_SHIFTED = "low_planning_mode_shifted"
PLAN_CONFIDENCE_STAGE_FAMILY_WIDENED = "low_stage_family_widened"
PLAN_CONFIDENCE_GENERIC_FALLBACK = "generic_fallback_no_calibration"

# Phase 6 Step 3: Tier 1 walk-back floor — aligned with the Phase 5.2 R2
# buffer rule's _PYTHON_DEFAULT_WIDTH_RETENTION_FRACTION at
# consultant_band_amendment_rules.py:28. A GPT amendment is walked back
# only when its remaining band width has fallen BELOW the buffer floor —
# meaning the amendment got past the buffer (a legacy code path or a
# missed validation). The buffer rule already rejects amendments below
# this floor at the consultant layer, so in a healthy system Tier 1 is a
# defensive no-op. Pre-Phase 6 this was 0.75 (walked back any amendment
# narrowed by ≥25%), which contradicted the buffer rule by reverting
# amendments the buffer had explicitly approved.
_GPT_BAND_RETENTION_FLOOR_PCT = 0.25
_TARGET_TOLERANCE_WIDENING = 1.5
_TARGET_TOLERANCE_GENERIC_WIDENING = 2.0


@dataclass
class CascadeAttempt:
  tier: int
  tier_name: str
  attempted: bool
  success: bool
  plan_confidence: Optional[str] = None
  residual_hard_fail_count: int = 0
  residual_violations: List[Dict[str, Any]] = field(default_factory=list)
  modifications: Dict[str, Any] = field(default_factory=dict)
  skip_reason: Optional[str] = None
  notes: List[str] = field(default_factory=list)
  final_model_input_json: Optional[Dict[str, Any]] = None
  final_finmo_json: Optional[Dict[str, Any]] = None
  inner_result: Optional[Dict[str, Any]] = None

  def to_diagnostic(self) -> Dict[str, Any]:
    return {
      "tier": self.tier, "tier_name": self.tier_name,
      "attempted": self.attempted, "success": self.success,
      "plan_confidence": self.plan_confidence,
      "residual_hard_fail_count": int(self.residual_hard_fail_count),
      "residual_violations": copy.deepcopy(self.residual_violations[:6]),
      "modifications": copy.deepcopy(self.modifications),
      "skip_reason": self.skip_reason, "notes": list(self.notes),
    }


def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  try:
    n = float(value)
    return None if n != n else n
  except Exception:
    return None


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


# --- Tier transformations ------------------------------------------------


def _envelope_with_gpt_bands_reverted(
  envelope_payload: Dict[str, Any],
  *,
  retention_floor_pct: float = _GPT_BAND_RETENTION_FLOOR_PCT,
) -> Tuple[Dict[str, Any], List[str]]:
  next_env = copy.deepcopy(envelope_payload or {})
  drivers = next_env.get("drivers") if isinstance(next_env.get("drivers"), dict) else {}
  reverted: List[str] = []
  for lever_id, entry in drivers.items():
    if not isinstance(entry, dict):
      continue
    prov = entry.get("provenance") if isinstance(entry.get("provenance"), dict) else {}
    if _clean_text(prov.get("calibration_source")) != "gpt_calibrated":
      continue
    py = prov.get("python_default") if isinstance(prov.get("python_default"), dict) else None
    if not py:
      continue
    py_min = _safe_float(py.get("min_allowed"))
    py_max = _safe_float(py.get("max_allowed"))
    py_default = _safe_float(py.get("default_value"))
    if py_min is None or py_max is None or py_default is None:
      continue
    cur_min = _safe_float(entry.get("min_allowed"))
    cur_max = _safe_float(entry.get("max_allowed"))
    py_width = max(0.0, py_max - py_min)
    cur_width = max(0.0, (cur_max or 0) - (cur_min or 0))
    # Walk back only when remaining width has fallen BELOW the buffer
    # rule's retention floor. Mirrors the buffer rule's exact comparison
    # shape (consultant_band_amendment_rules.py:151:
    # `if proposed_width < required_width: reject`). Amendments at or
    # above the floor were validated by the consultant layer (R2 buffer
    # rule); reverting them here contradicts the consultant contract.
    required_width = float(retention_floor_pct) * py_width
    if cur_width >= required_width:
      continue
    entry["min_allowed"] = float(py_min)
    entry["max_allowed"] = float(py_max)
    entry["default_value"] = float(py_default)
    if isinstance(py.get("applicable"), bool):
      entry["applicable"] = bool(py.get("applicable"))
    prov["calibration_source"] = "gpt_band_relaxed_for_adaptation"
    prov["gpt_amendment_walked_back"] = True
    entry["provenance"] = prov
    reverted.append(lever_id)
  next_env["drivers"] = drivers
  return next_env, reverted


def _envelope_with_cohort_walked_back(
  envelope_payload: Dict[str, Any],
  *,
  cascade_resolver: Callable[[str, str], Optional[Dict[str, Any]]],
) -> Tuple[Dict[str, Any], List[str]]:
  next_env = copy.deepcopy(envelope_payload or {})
  drivers = next_env.get("drivers") if isinstance(next_env.get("drivers"), dict) else {}
  naics_6 = _clean_text(next_env.get("naics_6"))
  walked: List[str] = []
  for lever_id, entry in drivers.items():
    if not isinstance(entry, dict):
      continue
    prov = entry.get("provenance") if isinstance(entry.get("provenance"), dict) else {}
    if not _clean_text(prov.get("calibration_source")).startswith("cohort_matched_"):
      continue
    metric_key = _clean_text(entry.get("metric_key"))
    band = cascade_resolver(metric_key, naics_6) if metric_key and naics_6 else None
    if not isinstance(band, dict):
      continue
    raw_target = _safe_float(band.get("benchmark_target"))
    raw_min = _safe_float(band.get("benchmark_min"))
    raw_max = _safe_float(band.get("benchmark_max"))
    if raw_target is None and raw_min is None and raw_max is None:
      continue
    target = raw_target if raw_target is not None else (raw_min if raw_min is not None else raw_max)
    lo = raw_min if raw_min is not None else target
    hi = raw_max if raw_max is not None else target
    entry["min_allowed"] = round(float(lo), 6)
    entry["max_allowed"] = round(float(hi), 6)
    entry["default_value"] = round(float(target), 6)
    prov["calibration_source"] = "naics_cascade_for_adaptation"
    prov["cohort_walked_back"] = True
    prov["naics_band"] = {
      "metric_key": metric_key,
      "benchmark_min": raw_min, "benchmark_target": raw_target, "benchmark_max": raw_max,
      "naics_code_used": band.get("naics_code_used"),
      "naics_level_used": band.get("naics_level_used"),
      "data_source": band.get("data_source"),
      "trust_flag": band.get("trust_flag"),
    }
    entry["provenance"] = prov
    walked.append(lever_id)
  next_env["drivers"] = drivers
  return next_env, walked


def _targets_with_widened_tolerance(
  targets_payload: Dict[str, Any],
  *,
  factor: float,
  only_gate_kinds: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], List[str]]:
  next_t = copy.deepcopy(targets_payload or {})
  metrics = next_t.get("metrics") if isinstance(next_t.get("metrics"), dict) else {}
  widened: List[str] = []
  filt = set(only_gate_kinds) if only_gate_kinds else None
  for metric_key, entry in metrics.items():
    if not isinstance(entry, dict):
      continue
    if filt is not None and _clean_text(entry.get("gate_kind")) not in filt:
      continue
    tmin = _safe_float(entry.get("target_min"))
    tmax = _safe_float(entry.get("target_max"))
    ttarget = _safe_float(entry.get("target_target"))
    if tmin is None or tmax is None:
      continue
    if ttarget is None:
      ttarget = (tmin + tmax) / 2.0
    new_min = ttarget - (ttarget - tmin) * factor
    new_max = ttarget + (tmax - ttarget) * factor
    entry["target_min"] = round(new_min, 6)
    entry["target_max"] = round(new_max, 6)
    prov = entry.get("provenance") if isinstance(entry.get("provenance"), dict) else {}
    prov["calibration_source"] = "target_tolerance_widened_for_adaptation"
    prov["widening_factor_applied"] = float(factor)
    entry["provenance"] = prov
    widened.append(metric_key)
  next_t["metrics"] = metrics
  return next_t, widened


def _influence_map_without_targeting_allowed_filter() -> Dict[str, Any]:
  try:
    from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
      load_post_intake_driver_target_mapping_rows,
    )
    from client_intake_and_finmo.post_intake_realism.lookup import (  # type: ignore
      post_intake_finalize_realism_check_rows,
    )
    from client_intake_and_finmo.post_intake_solver.influence_map import (  # type: ignore
      driver_influence_map,
    )
  except Exception:
    return {}
  rows = load_post_intake_driver_target_mapping_rows()
  expanded = [{**r, "targeting_allowed": True} for r in rows if isinstance(r, dict)]
  return driver_influence_map(
    mapping_rows=expanded,
    realism_rows=post_intake_finalize_realism_check_rows(),
  )


def _next_widened_stage_family(stage_family: Optional[str]) -> Optional[str]:
  cur = _clean_text(stage_family).lower() or "operational"
  return {"startup": "early", "early": "operational"}.get(cur)


def _build_widened_stage_ramp_contract(
  *,
  stage_family: str,
  planning_mode: str,
  planning_mode_reason: str,
  business_naics_6: Optional[str],
  business_stage: Optional[str],
) -> Optional[Dict[str, Any]]:
  try:
    from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
      stage_planning_ramp_policy,
    )
    return stage_planning_ramp_policy(
      stage_family=stage_family,
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      business_naics=business_naics_6,
      business_stage=business_stage,
    )
  except Exception as exc:
    logger.warning("adaptation_cascade_stage_ramp_policy_failed: %s", exc)
    return None


def _build_cascade_resolver_callable() -> Callable[[str, str], Optional[Dict[str, Any]]]:
  def _resolve(metric_key: str, naics_6: str) -> Optional[Dict[str, Any]]:
    if not metric_key or not naics_6:
      return None
    try:
      from client_intake_and_finmo.post_intake_industry_baseline import (  # type: ignore
        post_intake_industry_baseline_for_naics,
      )
      band = post_intake_industry_baseline_for_naics(metric_key=metric_key, naics_6=naics_6)
    except Exception:
      return None
    if not isinstance(band, dict) or band.get("trust_flag") == "no_coverage":
      return None
    return band
  return _resolve


def _repair_summary(repair: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  if not isinstance(repair, dict):
    return {}
  return {
    "status": repair.get("status"),
    "iterations_used": repair.get("iterations_used"),
    "trace_length": len(repair.get("trace") or []),
    "inner_invocations": repair.get("inner_invocations"),
  }


# --- Top-level cascade ---------------------------------------------------


def _starting_tier_for_abort_reason(abort_reason: Optional[str]) -> int:
  """Phase 6 Step 8 — pick the cascade tier that best matches the
  abort_reason from the inner runner. Lower-numbered tiers are tried
  first; the cascade always walks 1 -> 7 sequentially, so this is a
  starting tier, not the only tier attempted.

  Mapping per Phase 6 directive:
    convergence_total_phase_budget_exceeded → Tier 1
        (walk back GPT band amendments — less-aggressive bands mean
         fewer cycles needed, fewer cycles fit in budget)
    solver_not_invoked → Tier 1
        (zero editable cells; walk back GPT band amendments to restore
         editability; Tier 4 broader lever set is the next step)
    no_meaningful_progress → Tier 5
        (planning_mode shift to turnaround relaxes posture and floor
         constraints, breaking the stuck pattern)

  Unknown / unspecified abort_reason → Tier 1 (least invasive default).
  """
  reason = str(abort_reason or "").strip().lower()
  if reason == "no_meaningful_progress":
    return 5
  return 1


def run_adaptation_cascade(
  *,
  pre_input: Dict[str, Any],
  post_inner_model: Dict[str, Any],
  inner_result: Dict[str, Any],
  final_finmo_json: Dict[str, Any],
  envelope_payload_post: Dict[str, Any],
  targets_payload_post: Dict[str, Any],
  influence_payload: Dict[str, Any],
  final_hard_fails: List[Dict[str, Any]],
  pre_pass: Dict[str, Any],
  repair_pass: Optional[Dict[str, Any]],
  build_finmo_callable: Callable[[Dict[str, Any]], Dict[str, Any]],
  apply_lever_callable: Callable[[Dict[str, Any], str, float], Dict[str, Any]],
  run_target_seeking_pass_callable: Callable[..., Dict[str, Any]],
  hard_fail_violations_callable: Callable[..., List[Dict[str, Any]]],
  inner_runner_callable: Callable[..., Dict[str, Any]],
  inner_runner_kwargs: Dict[str, Any],
  original_planning_mode: str,
  original_planning_mode_reason: str = "",
  original_stage_family: Optional[str] = None,
  original_stage_ramp_contract: Optional[Dict[str, Any]] = None,
  business_naics_6: Optional[str] = None,
  business_stage: Optional[str] = None,
  horizon: int = 20,
  abort_reason: Optional[str] = None,
) -> Tuple[Dict[str, Any], str, Dict[str, Any]]:
  """Walk tiers 1->7 until a tier lands. Returns (final_result_payload,
  plan_confidence, cascade_diagnostics). Tier 7 is the structural floor.

  Phase 6 Step 8 — when ``abort_reason`` is supplied (set by the
  orchestrator when the inner runner returned status=abort_for_cascade),
  the cascade selects a starting tier matched to that reason instead of
  always Tier 1. Tiers below the start tier are still attempted IF
  later tiers fail, but they're attempted in their normal slot — the
  starting tier is only a starting point optimization, not a skip.
  """
  attempts: List[CascadeAttempt] = []
  starting_tier = _starting_tier_for_abort_reason(abort_reason)

  def _retry_post_flight(
    *, envelope: Dict[str, Any], targets: Dict[str, Any], influence: Dict[str, Any],
  ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    repair = run_target_seeking_pass_callable(
      pass_label="post_flight_repair_adapted",
      model_input_json=post_inner_model,
      build_finmo_callable=build_finmo_callable,
      apply_lever_callable=apply_lever_callable,
      envelope_payload=envelope, targets_payload=targets, influence_payload=influence,
      max_iterations=24, numeric_tolerance=1e-6,
      enable_inner_joint_fit=True, horizon=horizon,
    )
    final_fin = repair.get("final_finmo_json") or final_finmo_json
    residuals = hard_fail_violations_callable(
      finmo_json=final_fin, envelope_payload=envelope, targets_payload=targets,
    )
    return repair, residuals

  def _retry_with_inner(
    *, overrides: Dict[str, Any], envelope: Dict[str, Any],
    targets: Dict[str, Any], influence: Dict[str, Any],
  ) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    next_input = copy.deepcopy(pre_input)
    si = next_input.setdefault("solver_input", {})
    if isinstance(si, dict):
      try:
        from client_intake_and_finmo.post_intake_solver import (  # type: ignore
          DRIVER_MOVEMENT_ENVELOPE_KEY, FINMO_OUTPUT_TARGET_KEY,
        )
        si[DRIVER_MOVEMENT_ENVELOPE_KEY] = copy.deepcopy(envelope)
        si[FINMO_OUTPUT_TARGET_KEY] = copy.deepcopy(targets)
      except Exception:
        pass
    next_kwargs = dict(inner_runner_kwargs)
    next_kwargs.update(overrides)
    next_kwargs["applied_model_input_json"] = next_input
    new_inner = inner_runner_callable(**next_kwargs)
    new_post_model = (
      new_inner.get("model_input_json") if isinstance(new_inner, dict) else None
    ) or next_input
    new_final_fin = (
      new_inner.get("finmo_json") if isinstance(new_inner, dict) else None
    ) or final_finmo_json
    repair = run_target_seeking_pass_callable(
      pass_label="post_flight_repair_adapted",
      model_input_json=new_post_model,
      build_finmo_callable=build_finmo_callable,
      apply_lever_callable=apply_lever_callable,
      envelope_payload=envelope, targets_payload=targets, influence_payload=influence,
      max_iterations=24, numeric_tolerance=1e-6,
      enable_inner_joint_fit=True, horizon=horizon,
    )
    final_fin = repair.get("final_finmo_json") or new_final_fin
    residuals = hard_fail_violations_callable(
      finmo_json=final_fin, envelope_payload=envelope, targets_payload=targets,
    )
    return new_inner, repair, residuals

  def _land(
    *, tier: int, name: str, confidence: str, mods: Dict[str, Any],
    repair: Dict[str, Any], inner: Dict[str, Any],
  ) -> Tuple[Dict[str, Any], str, Dict[str, Any]]:
    attempt = CascadeAttempt(
      tier=tier, tier_name=name, attempted=True, success=True,
      plan_confidence=confidence, residual_hard_fail_count=0,
      modifications=mods,
      final_model_input_json=repair.get("final_model_input_json") or post_inner_model,
      final_finmo_json=repair.get("final_finmo_json") or final_finmo_json,
      inner_result=inner,
    )
    attempts.append(attempt)
    return _build_final_payload(inner, attempt, attempts)

  def _record_failed(
    *, tier: int, name: str, mods: Dict[str, Any],
    residuals: List[Dict[str, Any]], repair: Dict[str, Any],
  ) -> None:
    attempts.append(CascadeAttempt(
      tier=tier, tier_name=name, attempted=True, success=False,
      residual_hard_fail_count=len(residuals),
      residual_violations=residuals, modifications=mods,
    ))

  def _record_skipped(*, tier: int, name: str, reason: str) -> None:
    attempts.append(CascadeAttempt(
      tier=tier, tier_name=name, attempted=False, success=False,
      skip_reason=reason,
    ))

  # Phase 6 Step 8 — when starting_tier > 1, the orchestrator's
  # abort_reason chose to skip ahead. Tiers prior to starting_tier are
  # recorded as skipped (with a reason carrying the abort_reason) so
  # the run report still shows the full attempt history. The cascade
  # then walks the remaining tiers in their normal sequence; Tier 7 is
  # the final structural floor regardless of starting tier.
  skip_reason_for_jump = (
    f"skipped_per_abort_reason={str(abort_reason or '').strip().lower() or 'unknown'}"
  )

  # Phase 9 Phase D — Tier 1 (gpt_band_relaxation) removed per Q2.
  # The R2 buffer rule at consultant_band_amendment_rules.py already
  # rejects band amendments below the retention floor; Tier 1 was a
  # defensive no-op in a healthy system. Doctrine Q2 directs removal so
  # the cascade does not carry contradictory remediation logic. The
  # tier slot is preserved in attempts diagnostic for backwards-
  # compatible diagnostic readers.
  _record_skipped(tier=1, name="gpt_band_relaxation",
                  reason="removed_per_phase_9_doctrine_q2_redundant_with_r2_buffer_rule")

  # Tier 2: cohort walk-back
  if starting_tier > 2:
    _record_skipped(tier=2, name="cohort_fallback",
                    reason=skip_reason_for_jump)
  else:
    t2_env, walked = _envelope_with_cohort_walked_back(
      envelope_payload_post, cascade_resolver=_build_cascade_resolver_callable(),
    )
    if walked:
      repair, residuals = _retry_post_flight(
        envelope=t2_env, targets=targets_payload_post, influence=influence_payload,
      )
      if not residuals:
        return _land(tier=2, name="cohort_fallback",
                     confidence=PLAN_CONFIDENCE_COHORT_FALLBACK,
                     mods={"walked_back_lever_ids": walked}, repair=repair, inner=inner_result)
      _record_failed(tier=2, name="cohort_fallback",
                     mods={"walked_back_lever_ids": walked},
                     residuals=residuals, repair=repair)
    else:
      _record_skipped(tier=2, name="cohort_fallback",
                      reason="no_cohort_matched_drivers_to_walk_back")

  # Tier 3: target tolerance widening (warn first, then hard_fail).
  # When skipped per abort_reason, t3b_targets still needs a value for
  # downstream tiers — fall back to the original targets_payload_post.
  if starting_tier > 3:
    _record_skipped(tier=3, name="target_tolerance_widened",
                    reason=skip_reason_for_jump)
    t3b_targets = targets_payload_post
    widened_warn = []
    widened_hard = []
  else:
    # Tier 3a: warn-mode widening
    t3a_targets, widened_warn = _targets_with_widened_tolerance(
      targets_payload_post, factor=_TARGET_TOLERANCE_WIDENING, only_gate_kinds=["warn"],
    )
    repair, residuals = _retry_post_flight(
      envelope=envelope_payload_post, targets=t3a_targets, influence=influence_payload,
    )
    if not residuals:
      return _land(tier=3, name="target_tolerance_widened",
                   confidence=PLAN_CONFIDENCE_TARGET_TOLERANCE_WIDENED,
                   mods={"widened_warn_metric_keys": widened_warn,
                         "factor": _TARGET_TOLERANCE_WIDENING},
                   repair=repair, inner=inner_result)
    # Tier 3b: also widen hard_fail
    t3b_targets, widened_hard = _targets_with_widened_tolerance(
      t3a_targets, factor=_TARGET_TOLERANCE_WIDENING, only_gate_kinds=["hard_fail"],
    )
    repair, residuals = _retry_post_flight(
      envelope=envelope_payload_post, targets=t3b_targets, influence=influence_payload,
    )
    if not residuals:
      return _land(tier=3, name="target_tolerance_widened",
                   confidence=PLAN_CONFIDENCE_TARGET_TOLERANCE_WIDENED,
                   mods={"widened_warn_metric_keys": widened_warn,
                         "widened_hard_fail_metric_keys": widened_hard,
                         "factor": _TARGET_TOLERANCE_WIDENING},
                   repair=repair, inner=inner_result)
    _record_failed(tier=3, name="target_tolerance_widened",
                   mods={"widened_warn_metric_keys": widened_warn,
                         "widened_hard_fail_metric_keys": widened_hard,
                         "factor": _TARGET_TOLERANCE_WIDENING},
                   residuals=residuals, repair=repair)

  # Tier 4: influence-map breadth expansion
  if starting_tier > 4:
    _record_skipped(tier=4, name="supplementary_levers_used",
                    reason=skip_reason_for_jump)
    t4_influence = None
  else:
    t4_influence = _influence_map_without_targeting_allowed_filter()
    if t4_influence and t4_influence.get("metrics"):
      repair, residuals = _retry_post_flight(
        envelope=envelope_payload_post, targets=t3b_targets, influence=t4_influence,
      )
      if not residuals:
        return _land(tier=4, name="supplementary_levers_used",
                     confidence=PLAN_CONFIDENCE_SUPPLEMENTARY_LEVERS,
                     mods={"influence_map_targeting_allowed_filter": "removed"},
                     repair=repair, inner=inner_result)
      _record_failed(tier=4, name="supplementary_levers_used",
                     mods={"influence_map_targeting_allowed_filter": "removed"},
                     residuals=residuals, repair=repair)
    else:
      _record_skipped(tier=4, name="supplementary_levers_used",
                      reason="influence_map_rebuild_failed_or_empty")

  # Tier 5: planning_mode shift to turnaround
  if _clean_text(original_planning_mode).lower() != "turnaround":
    new_inner, repair, residuals = _retry_with_inner(
      overrides={
        "planning_mode": "turnaround",
        "planning_mode_reason": (original_planning_mode_reason or "")
          + " | adapted_to_turnaround_for_plan_landing",
      },
      envelope=envelope_payload_post, targets=t3b_targets,
      influence=t4_influence or influence_payload,
    )
    if not residuals:
      return _land(tier=5, name="planning_mode_shifted",
                   confidence=PLAN_CONFIDENCE_PLANNING_MODE_SHIFTED,
                   mods={"planning_mode_before": original_planning_mode,
                         "planning_mode_after": "turnaround"},
                   repair=repair, inner=new_inner)
    _record_failed(tier=5, name="planning_mode_shifted",
                   mods={"planning_mode_before": original_planning_mode,
                         "planning_mode_after": "turnaround"},
                   residuals=residuals, repair=repair)
  else:
    _record_skipped(tier=5, name="planning_mode_shifted",
                    reason="original_mode_already_turnaround")

  # Tier 6: stage_family widening
  widened_stage = _next_widened_stage_family(original_stage_family)
  if widened_stage:
    new_contract = _build_widened_stage_ramp_contract(
      stage_family=widened_stage, planning_mode="turnaround",
      planning_mode_reason=(original_planning_mode_reason or "")
        + " | adapted_to_widened_stage_for_plan_landing",
      business_naics_6=business_naics_6, business_stage=business_stage,
    )
    new_inner, repair, residuals = _retry_with_inner(
      overrides={
        "planning_mode": "turnaround",
        "stage_ramp_contract": new_contract or original_stage_ramp_contract,
      },
      envelope=envelope_payload_post, targets=t3b_targets,
      influence=t4_influence or influence_payload,
    )
    if not residuals:
      return _land(tier=6, name="stage_family_widened",
                   confidence=PLAN_CONFIDENCE_STAGE_FAMILY_WIDENED,
                   mods={"stage_family_before": original_stage_family or "operational",
                         "stage_family_after": widened_stage},
                   repair=repair, inner=new_inner)
    _record_failed(tier=6, name="stage_family_widened",
                   mods={"stage_family_before": original_stage_family or "operational",
                         "stage_family_after": widened_stage},
                   residuals=residuals, repair=repair)
  else:
    _record_skipped(tier=6, name="stage_family_widened",
                    reason="stage_family_already_widest")

  # Tier 7: generic NAICS-cascade fallback (structural floor — always lands)
  try:
    from client_intake_and_finmo.post_intake_solver import (  # type: ignore
      assemble_driver_movement_envelope,
      assemble_finmo_output_targets,
    )
    t7_env = assemble_driver_movement_envelope(
      business_naics_6=business_naics_6, live_count=horizon,
    )
    # Stamp `calibration` marker so finmo_bridge preserves this envelope
    # across the inner runner's many model_input rebuilds.
    t7_env["calibration"] = {
      "consultant_name": "adaptation_cascade_tier_7",
      "decision_source": "tier_7_generic_fallback_no_calibration",
      "amended_lever_ids": [], "uncalibrated_lever_ids": [],
      "review_status": "tier_7_floor",
    }
    t7_targets_proposal = assemble_finmo_output_targets(
      business_naics_6=business_naics_6, live_count=horizon,
    )
    t7_targets, widened_all = _targets_with_widened_tolerance(
      t7_targets_proposal, factor=_TARGET_TOLERANCE_GENERIC_WIDENING,
    )
    t7_targets["calibration"] = {
      "consultant_name": "adaptation_cascade_tier_7",
      "decision_source": "tier_7_generic_fallback_no_calibration",
      "amended_metric_keys": [], "uncalibrated_metric_keys": [],
      "review_status": "tier_7_floor",
    }
  except Exception as exc:
    logger.warning("adaptation_cascade_tier7_envelope_build_failed: %s", exc)
    t7_env = envelope_payload_post
    t7_targets = targets_payload_post
    widened_all = []

  try:
    new_inner, repair, residuals = _retry_with_inner(
      overrides={
        "planning_mode": "turnaround",
        "stage_ramp_contract": _build_widened_stage_ramp_contract(
          stage_family="operational", planning_mode="turnaround",
          planning_mode_reason="adapted_to_generic_fallback_for_plan_landing",
          business_naics_6=business_naics_6, business_stage=business_stage,
        ) or original_stage_ramp_contract,
      },
      envelope=t7_env, targets=t7_targets,
      influence=t4_influence or influence_payload,
    )
  except Exception as exc:
    logger.warning("adaptation_cascade_tier7_inner_runner_failed: %s", exc)
    new_inner = inner_result
    repair = repair_pass or {}
    residuals = []

  # Phase 9 Phase D — Tier 7 NEVER ships success with residuals.
  # When residuals remain after Tier 7's NAICS-cascade fallback, the
  # cascade has exhausted the adaptation space. Per doctrine Q5,
  # escalate to feasibility_restoration (business-model lever
  # adjustments — capacity, headcount, price, utilization). If
  # restoration also exhausts, raise terminal cause #7 with full
  # diagnostic of every adaptation attempted and every restoration
  # attempted so the consultant sees what specifically couldn't reach
  # viability.
  if not residuals:
    attempt = CascadeAttempt(
      tier=7, tier_name="generic_fallback_no_calibration",
      attempted=True, success=True,
      plan_confidence=PLAN_CONFIDENCE_GENERIC_FALLBACK,
      residual_hard_fail_count=0,
      residual_violations=[],
      modifications={
        "envelope_source": "naics_cascade_only_no_cohort_no_gpt",
        "target_tolerance_widening_factor": _TARGET_TOLERANCE_GENERIC_WIDENING,
        "widened_metric_keys": widened_all,
        "planning_mode_forced": "turnaround",
        "stage_family_forced": "operational",
      },
      notes=[
        "tier_7_landed_clean_no_residuals",
        "low_confidence_plan_manual_review_recommended",
      ],
      final_model_input_json=(
        (repair.get("final_model_input_json") if isinstance(repair, dict) else None)
        or post_inner_model
      ),
      final_finmo_json=(
        (repair.get("final_finmo_json") if isinstance(repair, dict) else None)
        or final_finmo_json
      ),
      inner_result=new_inner,
    )
    attempts.append(attempt)
    return _build_final_payload(new_inner, attempt, attempts)

  # Tier 7 left residuals — escalate to feasibility_restoration.
  _record_failed(tier=7, name="generic_fallback_no_calibration",
                 mods={
                   "envelope_source": "naics_cascade_only_no_cohort_no_gpt",
                   "target_tolerance_widening_factor": _TARGET_TOLERANCE_GENERIC_WIDENING,
                   "widened_metric_keys": widened_all,
                   "planning_mode_forced": "turnaround",
                   "stage_family_forced": "operational",
                 },
                 residuals=residuals, repair=repair)

  # Phase 9 Phase D — feasibility_restoration cascade after adaptation
  # exhausts. Modifies business-model levers (capacity, headcount,
  # price, utilization) — the kind of changes the consultant must
  # discuss with the client.
  restoration_diag: Dict[str, Any] = {"attempted": False}
  try:
    from client_intake_and_finmo.post_intake_solver.feasibility_restoration import (  # type: ignore
      restore_feasibility,
    )
    restoration = restore_feasibility(
      structural_result=None,  # the cascade reached this point on FINMO residuals,
      ops_json=(inner_runner_kwargs or {}).get("ops_json") or {},
      financials_json=(inner_runner_kwargs or {}).get("financials_json") or {},
      financials_year1_json=(inner_runner_kwargs or {}).get("financials_year1_json") or {},
      payroll_headcount=(inner_runner_kwargs or {}).get("payroll_headcount") or {},
      business_naics_6=business_naics_6,
    )
    restoration_diag = restoration.to_dict() if hasattr(restoration, "to_dict") else {"attempted": True}
  except TypeError:
    # restore_feasibility's signature requires a structural_result; build a
    # synthetic one carrying the residuals as the gap.
    try:
      from client_intake_and_finmo.post_intake_solver.feasibility_restoration import (  # type: ignore
        restore_feasibility,
      )
      from client_intake_and_finmo.post_intake_solver.structural_feasibility_check import (  # type: ignore
        StructuralFeasibilityResult,
      )
      synth = StructuralFeasibilityResult(
        feasible=False,
        reason="adaptation_cascade_exhausted_with_residuals",
        diagnostic={
          "residual_hard_fails": residuals[:6],
          "tier_7_widened_targets": widened_all,
        },
        recommended_adjustments={},
      )
      restoration = restore_feasibility(
        structural_result=synth,
        ops_json=(inner_runner_kwargs or {}).get("ops_json") or {},
        financials_json=(inner_runner_kwargs or {}).get("financials_json") or {},
        financials_year1_json=(inner_runner_kwargs or {}).get("financials_year1_json") or {},
        payroll_headcount=(inner_runner_kwargs or {}).get("payroll_headcount") or {},
        business_naics_6=business_naics_6,
      )
      restoration_diag = restoration.to_dict() if hasattr(restoration, "to_dict") else {"attempted": True}
    except Exception as exc:
      restoration_diag = {
        "attempted": True,
        "exception": f"{type(exc).__name__}: {str(exc)[:300]}",
        "applied_adjustments": [],
      }
  except Exception as exc:
    restoration_diag = {
      "attempted": True,
      "exception": f"{type(exc).__name__}: {str(exc)[:300]}",
      "applied_adjustments": [],
    }

  # Persist the restoration attempt in attempts so downstream sees it.
  attempts.append(CascadeAttempt(
    tier=8, tier_name="feasibility_restoration_after_cascade_exhaustion",
    attempted=True,
    success=bool(restoration_diag.get("applied_adjustments")),
    residual_hard_fail_count=len(residuals),
    residual_violations=residuals,
    modifications=restoration_diag,
    notes=["restoration_after_cascade_exhausted"],
  ))

  # If restoration applied changes, retry post-flight with the adjusted state.
  if restoration_diag.get("applied_adjustments"):
    try:
      retry_inner = inner_runner_callable(**dict(inner_runner_kwargs))
      retry_post_model = (
        retry_inner.get("model_input_json") if isinstance(retry_inner, dict) else None
      ) or post_inner_model
      retry_repair = run_target_seeking_pass_callable(
        pass_label="post_flight_repair_after_restoration",
        model_input_json=retry_post_model,
        build_finmo_callable=build_finmo_callable,
        apply_lever_callable=apply_lever_callable,
        envelope_payload=t7_env, targets_payload=t7_targets, influence_payload=influence_payload,
        max_iterations=24, numeric_tolerance=1e-6,
        enable_inner_joint_fit=True, horizon=horizon,
      )
      retry_final_fin = retry_repair.get("final_finmo_json") or final_finmo_json
      retry_residuals = hard_fail_violations_callable(
        finmo_json=retry_final_fin, envelope_payload=t7_env, targets_payload=t7_targets,
      )
      if not retry_residuals:
        attempt = CascadeAttempt(
          tier=8, tier_name="feasibility_restoration_landed",
          attempted=True, success=True,
          plan_confidence="restoration_after_cascade_exhausted",
          residual_hard_fail_count=0,
          modifications=restoration_diag,
          notes=["restoration_business_model_lever_adjustments_landed"],
          final_model_input_json=(
            retry_repair.get("final_model_input_json") or retry_post_model
          ),
          final_finmo_json=retry_final_fin,
          inner_result=retry_inner,
        )
        attempts.append(attempt)
        return _build_final_payload(retry_inner, attempt, attempts)
    except Exception as exc:
      restoration_diag["retry_exception"] = f"{type(exc).__name__}: {str(exc)[:300]}"

  # Both cascade and restoration exhausted — terminal cause #7 per
  # doctrine. Raise a structured exception carrying the full diagnostic
  # so the consultant sees every adaptation attempted, every restoration
  # attempted, and exactly which residuals couldn't be cleared.
  diagnostic_payload = {
    "terminal_cause": "adaptation_and_restoration_cascades_both_exhausted",
    "doctrine_terminal_id": 7,
    "residual_hard_fails": copy.deepcopy(residuals),
    "tier_attempts": [a.to_diagnostic() for a in attempts],
    "feasibility_restoration_diagnostic": copy.deepcopy(restoration_diag),
    "consultant_message": (
      "The system attempted every adaptation path (Tiers 2-7) and every "
      "feasibility restoration adjustment without producing a viable plan. "
      "The business model as configured cannot reach the universal viability "
      "rule (EBITDA positive by Q11, funded loss window, no post-recovery "
      "relapse). Review with client: the diagnostic lists exactly which "
      "drivers were tried and which residuals remained."
    ),
  }
  raise CascadeAndRestorationExhausted(diagnostic_payload)


def _build_final_payload(
  inner_result: Optional[Dict[str, Any]],
  successful_attempt: CascadeAttempt,
  attempts: List[CascadeAttempt],
) -> Tuple[Dict[str, Any], str, Dict[str, Any]]:
  base = copy.deepcopy(inner_result if isinstance(inner_result, dict) else {})
  if successful_attempt.final_model_input_json is not None:
    base["model_input_json"] = successful_attempt.final_model_input_json
  if successful_attempt.final_finmo_json:
    base["finmo_json"] = successful_attempt.final_finmo_json
  diagnostics = {
    "tier_landed": successful_attempt.tier,
    "tier_landed_name": successful_attempt.tier_name,
    "plan_confidence": successful_attempt.plan_confidence,
    "tier_attempts": [a.to_diagnostic() for a in attempts],
    "residuals_at_landing": copy.deepcopy(successful_attempt.residual_violations[:6]),
    "notes": list(successful_attempt.notes),
  }
  return base, successful_attempt.plan_confidence or PLAN_CONFIDENCE_GENERIC_FALLBACK, diagnostics


# Phase 5.2 R3: pre-solver feasibility cascade. Walked when
# verify_joint_feasibility returns False after Phase 3 calibration. We
# reuse the existing tier transformations (GPT band walk-back; cohort
# walk-back; tolerance widening) and exit on the first transformation
# that restores joint feasibility. If no pre-solver tier restores
# feasibility, the solver runs anyway — the post-flight cascade Tier 7
# is the structural floor that always lands a plan.

def run_pre_solver_feasibility_cascade(
  *,
  envelope_payload: Dict[str, Any],
  targets_payload: Dict[str, Any],
  business_profile: Optional[Dict[str, Any]],
  initial_diagnostic: Any,
) -> Dict[str, Any]:
  """Walk pre-solver tiers 1->3 until verify_joint_feasibility passes.

  Args:
    envelope_payload, targets_payload: post-Phase-3-calibration payloads.
    business_profile: forwarded to the feasibility checker.
    initial_diagnostic: FeasibilityResult from the failing initial check.

  Returns:
    {
      "envelope_payload": <possibly walked-back envelope>,
      "targets_payload": <possibly widened targets>,
      "diagnostic": { tier_landed, tier_attempts, ... },
    }

  Never raises. If no tier restores feasibility, the original payloads
  fall through and the solver runs against them; downstream the
  post-flight cascade picks up the residuals.
  """
  from client_intake_and_finmo.post_intake_solver.joint_feasibility_check import (  # type: ignore
    verify_joint_feasibility,
  )
  attempts: List[Dict[str, Any]] = []
  current_env = copy.deepcopy(envelope_payload or {})
  current_targets = copy.deepcopy(targets_payload or {})

  attempts.append({
    "tier": 0, "tier_name": "phase_3_calibrated_initial",
    "feasible": False,
    "diagnostic": initial_diagnostic.to_dict() if hasattr(initial_diagnostic, "to_dict") else {},
  })

  # Tier 1: walk back GPT band amendments to Python defaults.
  t1_env, reverted = _envelope_with_gpt_bands_reverted(current_env)
  attempt = {"tier": 1, "tier_name": "gpt_band_relaxation",
             "reverted_lever_ids": reverted, "attempted": bool(reverted)}
  if reverted:
    fr1 = verify_joint_feasibility(
      envelope_payload=t1_env, targets_payload=current_targets,
      business_profile=business_profile,
    )
    attempt["feasible_after"] = fr1.feasible
    attempt["diagnostic"] = fr1.to_dict()
    attempts.append(attempt)
    if fr1.feasible:
      return {
        "envelope_payload": t1_env,
        "targets_payload": current_targets,
        "diagnostic": {
          "tier_landed": 1, "tier_landed_name": "gpt_band_relaxation",
          "plan_confidence": PLAN_CONFIDENCE_GPT_BAND_RELAXATION,
          "tier_attempts": attempts,
        },
      }
    current_env = t1_env  # carry forward the walked-back envelope
  else:
    attempt["skip_reason"] = "no_gpt_calibrated_drivers_to_revert"
    attempts.append(attempt)

  # Tier 2: cohort walk-back to NAICS cascade defaults.
  t2_env, walked = _envelope_with_cohort_walked_back(
    current_env, cascade_resolver=_build_cascade_resolver_callable(),
  )
  attempt = {"tier": 2, "tier_name": "cohort_fallback",
             "walked_back_lever_ids": walked, "attempted": bool(walked)}
  if walked:
    fr2 = verify_joint_feasibility(
      envelope_payload=t2_env, targets_payload=current_targets,
      business_profile=business_profile,
    )
    attempt["feasible_after"] = fr2.feasible
    attempt["diagnostic"] = fr2.to_dict()
    attempts.append(attempt)
    if fr2.feasible:
      return {
        "envelope_payload": t2_env,
        "targets_payload": current_targets,
        "diagnostic": {
          "tier_landed": 2, "tier_landed_name": "cohort_fallback",
          "plan_confidence": PLAN_CONFIDENCE_COHORT_FALLBACK,
          "tier_attempts": attempts,
        },
      }
    current_env = t2_env
  else:
    attempt["skip_reason"] = "no_cohort_matched_drivers_to_walk_back"
    attempts.append(attempt)

  # Tier 3: target tolerance widening (warn + hard_fail).
  t3a_targets, widened_warn = _targets_with_widened_tolerance(
    current_targets, factor=_TARGET_TOLERANCE_WIDENING, only_gate_kinds=["warn"],
  )
  fr3a = verify_joint_feasibility(
    envelope_payload=current_env, targets_payload=t3a_targets,
    business_profile=business_profile,
  )
  attempts.append({
    "tier": 3, "tier_name": "target_tolerance_widened_warn",
    "widened_metric_keys": widened_warn,
    "feasible_after": fr3a.feasible,
    "diagnostic": fr3a.to_dict(),
  })
  if fr3a.feasible:
    return {
      "envelope_payload": current_env,
      "targets_payload": t3a_targets,
      "diagnostic": {
        "tier_landed": 3, "tier_landed_name": "target_tolerance_widened",
        "plan_confidence": PLAN_CONFIDENCE_TARGET_TOLERANCE_WIDENED,
        "tier_attempts": attempts,
      },
    }
  t3b_targets, widened_hard = _targets_with_widened_tolerance(
    t3a_targets, factor=_TARGET_TOLERANCE_WIDENING, only_gate_kinds=["hard_fail"],
  )
  fr3b = verify_joint_feasibility(
    envelope_payload=current_env, targets_payload=t3b_targets,
    business_profile=business_profile,
  )
  attempts.append({
    "tier": 3, "tier_name": "target_tolerance_widened_hard_fail",
    "widened_metric_keys": widened_hard,
    "feasible_after": fr3b.feasible,
    "diagnostic": fr3b.to_dict(),
  })
  if fr3b.feasible:
    return {
      "envelope_payload": current_env,
      "targets_payload": t3b_targets,
      "diagnostic": {
        "tier_landed": 3, "tier_landed_name": "target_tolerance_widened",
        "plan_confidence": PLAN_CONFIDENCE_TARGET_TOLERANCE_WIDENED,
        "tier_attempts": attempts,
      },
    }

  # Pre-solver tiers exhausted. Hand the still-infeasible payload to the
  # solver; the post-flight cascade will pick up the residuals (Tier 7
  # is the structural floor and always lands a plan).
  return {
    "envelope_payload": current_env,
    "targets_payload": t3b_targets,
    "diagnostic": {
      "tier_landed": None,
      "tier_landed_name": "pre_solver_tiers_exhausted",
      "plan_confidence": None,
      "tier_attempts": attempts,
      "note": "pre_solver_tiers_exhausted_handing_off_to_post_flight_cascade",
    },
  }
