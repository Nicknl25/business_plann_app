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

PLAN_CONFIDENCE_HIGH_NO_ADAPTATION = "high_no_adaptation"
PLAN_CONFIDENCE_GPT_BAND_RELAXATION = "medium_gpt_band_relaxation"
PLAN_CONFIDENCE_COHORT_FALLBACK = "medium_cohort_fallback"
PLAN_CONFIDENCE_TARGET_TOLERANCE_WIDENED = "low_target_tolerance_widened"
PLAN_CONFIDENCE_SUPPLEMENTARY_LEVERS = "low_supplementary_levers_used"
PLAN_CONFIDENCE_PLANNING_MODE_SHIFTED = "low_planning_mode_shifted"
PLAN_CONFIDENCE_STAGE_FAMILY_WIDENED = "low_stage_family_widened"
PLAN_CONFIDENCE_GENERIC_FALLBACK = "generic_fallback_no_calibration"

_GPT_BAND_TIGHTENING_THRESHOLD_PCT = 0.25
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
  tightening_threshold_pct: float = _GPT_BAND_TIGHTENING_THRESHOLD_PCT,
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
    pct_remaining = (cur_width / py_width) if py_width > 0 else 1.0
    if pct_remaining > (1.0 - float(tightening_threshold_pct)):
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
) -> Tuple[Dict[str, Any], str, Dict[str, Any]]:
  """Walk tiers 1->7 until a tier lands. Returns (final_result_payload,
  plan_confidence, cascade_diagnostics). Tier 7 is the structural floor."""
  attempts: List[CascadeAttempt] = []

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
      modifications=mods, post_flight_repair=None,
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

  # Tier 1: GPT band walk-back
  t1_env, reverted = _envelope_with_gpt_bands_reverted(envelope_payload_post)
  if reverted:
    repair, residuals = _retry_post_flight(
      envelope=t1_env, targets=targets_payload_post, influence=influence_payload,
    )
    if not residuals:
      return _land(tier=1, name="gpt_band_relaxation",
                   confidence=PLAN_CONFIDENCE_GPT_BAND_RELAXATION,
                   mods={"reverted_lever_ids": reverted}, repair=repair, inner=inner_result)
    _record_failed(tier=1, name="gpt_band_relaxation",
                   mods={"reverted_lever_ids": reverted},
                   residuals=residuals, repair=repair)
  else:
    _record_skipped(tier=1, name="gpt_band_relaxation",
                    reason="no_gpt_calibrated_drivers_to_revert")

  # Tier 2: cohort walk-back
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

  attempt = CascadeAttempt(
    tier=7, tier_name="generic_fallback_no_calibration",
    attempted=True, success=True,  # structural floor — always lands
    plan_confidence=PLAN_CONFIDENCE_GENERIC_FALLBACK,
    residual_hard_fail_count=len(residuals),
    residual_violations=residuals,
    modifications={
      "envelope_source": "naics_cascade_only_no_cohort_no_gpt",
      "target_tolerance_widening_factor": _TARGET_TOLERANCE_GENERIC_WIDENING,
      "widened_metric_keys": widened_all,
      "planning_mode_forced": "turnaround",
      "stage_family_forced": "operational",
    },
    notes=[
      "tier_7_is_structural_floor_accepts_residuals",
      "low_confidence_plan_manual_review_recommended",
    ] + (["residuals_remain_but_accepted"] if residuals else []),
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
