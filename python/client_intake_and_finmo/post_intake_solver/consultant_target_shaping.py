"""Phase 3 / 5.2 — Per-metric FINMO output target shaping consultant.

Calibrates the deterministic ``finmo_output_targets`` payload produced
by the Phase 2 assembler. Per Phase 5.2 R1, GPT is invoked once per
output metric with a per-metric scoped context dict resolved by
``resolve_consultant_context``.

GPT can:
  - Tighten the target band (typical for hard_fail metrics whose
    Python defaults span unreasonable ranges).
  - Widen the target band (typical for warn metrics where the
    business's stage / planning_mode legitimately produces values
    outside the steady-state cohort band).
  - Reject the proposal (rare; system falls back to Python default).

Each per-metric call gets a small (~3KB) payload focused on one
metric's calibration. Temperature=0; deterministic.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional


_TARGET_SHAPING_CONSULTANT_NAME = "finmo_output_targets_calibration"
_TARGET_SHAPING_CONTRACT_NAME = "post_intake_target_shaping_consultant"
_TARGET_SHAPING_INCLUDE_PHASE = "target_shaping"
_DEFAULT_TIMEOUT_SECONDS = 30.0


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  try:
    number = float(value)
  except Exception:
    return None
  if number != number:
    return None
  return number


_PER_METRIC_RESPONSE_SCHEMA: Dict[str, Any] = {
  "type": "object",
  "additionalProperties": False,
  "properties": {
    "review_status": {"type": "string", "enum": ["accepted", "amended", "rejected"]},
    "target_min": {"type": ["number", "null"]},
    "target_target": {"type": ["number", "null"]},
    "target_max": {"type": ["number", "null"]},
    "rationale": {"type": "string"},
  },
  "required": [
    "review_status", "target_min", "target_target", "target_max", "rationale",
  ],
}


_PER_METRIC_SYSTEM_PROMPT = (
  "You are calibrating ONE FINMO output target range for a "
  "post-intake target-seeking solver. The metric has target_min, "
  "target_target, target_max from the NAICS / cohort band plus a "
  "per-confidence-tier tolerance widening. You decide whether to "
  "tighten (steady-state mature), widen (early stage / runway focus / "
  "turnaround), or accept the Python proposal.\n\n"
  "Operating rules:\n"
  "1. target_min < target_target < target_max strictly. No point "
  "ranges.\n"
  "2. For hard_fail metrics (cogs_to_revenue_ratio, ar_days_dso, "
  "ap_days_dpo, effective_tax_rate, etc.), tightening is strongly "
  "preferred over widening — these are the metrics the system fails "
  "loudly on if the solver cannot land them. Widen only when the "
  "business profile clearly justifies it.\n"
  "3. For warn metrics (ebitda_margin, gross_margin_percent, "
  "operating_margin_percent, etc.), per-stage shaping is the primary "
  "use case. A bootstrapped Q1 ebitda may be -15%% even when the "
  "steady-state cohort band is +18%% to +28%%.\n"
  "4. review_status=accepted means keep the proposal. amended means "
  "use the supplied target_min / target / target_max. rejected falls "
  "back to the Python default."
)


def _build_per_metric_user_context(
  *,
  metric_key: str,
  metric_entry: Dict[str, Any],
  resolver_context: Dict[str, Any],
) -> Dict[str, Any]:
  return {
    "consultant": _TARGET_SHAPING_CONSULTANT_NAME,
    "metric_key": metric_key,
    "finmo_line_label": metric_entry.get("finmo_line_label"),
    "gate_kind": metric_entry.get("gate_kind"),
    "quarter_aggregation": metric_entry.get("quarter_aggregation"),
    "applicability_rule_key": metric_entry.get("applicability_rule_key"),
    "governs_model_input_lever_id": metric_entry.get("governs_model_input_lever_id"),
    "python_proposed_target": {
      "target_min": metric_entry.get("target_min"),
      "target_target": metric_entry.get("target_target"),
      "target_max": metric_entry.get("target_max"),
      "calibration_source": (metric_entry.get("provenance") or {}).get("calibration_source"),
      "confidence_tier": (metric_entry.get("provenance") or {}).get("confidence_tier"),
    },
    "context": resolver_context,
  }


def _apply_metric_amendment(
  *, metric_key: str, original_entry: Dict[str, Any], parsed: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  proposed_min = _safe_float(parsed.get("target_min"))
  proposed_target = _safe_float(parsed.get("target_target"))
  proposed_max = _safe_float(parsed.get("target_max"))
  if proposed_min is None or proposed_max is None:
    return None
  if proposed_max <= proposed_min:
    # Strict inequality — silently fall back to Python default. Targets
    # don't have the same buffer-rule guarantees as bands; widening
    # tolerances is handled by the cascade.
    return None
  if proposed_target is None:
    proposed_target = (proposed_min + proposed_max) / 2.0
  if proposed_target < proposed_min:
    proposed_target = proposed_min
  if proposed_target > proposed_max:
    proposed_target = proposed_max

  next_entry = copy.deepcopy(original_entry)
  next_entry["target_min"] = round(float(proposed_min), 6)
  next_entry["target_target"] = round(float(proposed_target), 6)
  next_entry["target_max"] = round(float(proposed_max), 6)

  original_provenance = (
    original_entry.get("provenance") if isinstance(original_entry.get("provenance"), dict) else {}
  )
  next_provenance = copy.deepcopy(original_provenance) if original_provenance else {}
  next_provenance["calibration_source"] = "gpt_calibrated"
  next_provenance["python_default"] = {
    "target_min": original_entry.get("target_min"),
    "target_target": original_entry.get("target_target"),
    "target_max": original_entry.get("target_max"),
    "calibration_source_before": original_provenance.get("calibration_source"),
  }
  next_provenance["gpt_amendment"] = {"rationale": _clean_text(parsed.get("rationale"))}
  next_entry["provenance"] = next_provenance
  return next_entry


def _tag_uncalibrated_metric(entry: Dict[str, Any], *, fallback_tag: str) -> None:
  provenance = entry.get("provenance") if isinstance(entry.get("provenance"), dict) else {}
  original_source = _clean_text(provenance.get("calibration_source"))
  if original_source == "naics_default":
    return
  provenance.setdefault("python_default_calibration_source", original_source)
  provenance["calibration_source"] = fallback_tag
  entry["provenance"] = provenance


def calibrate_finmo_output_targets_with_gpt(
  *,
  targets_proposal: Dict[str, Any],
  draft_id: str,
  planning_run_id: str,
  conn: Any,
  runtime_objects: Dict[str, Any],
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
  """Calibrate FINMO output targets metric-by-metric via GPT."""
  proposal = copy.deepcopy(targets_proposal or {})
  metrics = proposal.get("metrics") if isinstance(proposal.get("metrics"), dict) else {}
  if not metrics:
    return {
      "calibrated_targets": proposal,
      "decision_source": "python_proposer_only_no_metrics",
      "amended_metric_keys": [],
      "uncalibrated_metric_keys": [],
      "raw_openai_response": {},
      "critic_diagnostics": {"reason": "targets_payload_has_no_metrics"},
    }

  from client_intake_and_finmo.post_intake_solver._gpt_critic_io import (  # type: ignore
    call_gpt_with_schema_or_fallback,
  )
  from client_intake_and_finmo.post_intake_solver.consultant_context_resolver import (  # type: ignore
    resolve_consultant_context,
  )

  amended_metric_keys: List[str] = []
  per_metric_diagnostics: List[Dict[str, Any]] = []
  any_gpt_call_succeeded = False
  any_gpt_call_failed = False
  first_no_api_key = False

  for metric_key, original_entry in list(metrics.items()):
    if not isinstance(original_entry, dict):
      continue

    scoped_runtime = dict(runtime_objects or {})
    scoped_runtime["metric_entry"] = copy.deepcopy(original_entry)

    resolver_context = resolve_consultant_context(
      contract_name=_TARGET_SHAPING_CONTRACT_NAME,
      include_phase=_TARGET_SHAPING_INCLUDE_PHASE,
      scope_key={"metric_key": metric_key},
      draft_id=draft_id,
      planning_run_id=planning_run_id,
      conn=conn,
      runtime_objects=scoped_runtime,
    )

    user_context = _build_per_metric_user_context(
      metric_key=metric_key,
      metric_entry=original_entry,
      resolver_context=resolver_context,
    )
    call_result = call_gpt_with_schema_or_fallback(
      consultant_name=_TARGET_SHAPING_CONSULTANT_NAME,
      system_prompt=_PER_METRIC_SYSTEM_PROMPT,
      user_context=user_context,
      response_schema=_PER_METRIC_RESPONSE_SCHEMA,
      schema_name=_TARGET_SHAPING_CONSULTANT_NAME,
      timeout_seconds=timeout_seconds,
    )
    decision_source = call_result.get("decision_source") or "python_proposer_only_unknown"
    parsed = call_result.get("parsed") if isinstance(call_result.get("parsed"), dict) else None

    if decision_source == "python_proposer_plus_gpt_critic":
      any_gpt_call_succeeded = True
    elif decision_source == "python_proposer_only_no_api_key":
      first_no_api_key = True
      any_gpt_call_failed = True
    else:
      any_gpt_call_failed = True

    if not parsed or _clean_text(parsed.get("review_status")) != "amended":
      per_metric_diagnostics.append({
        "metric_key": metric_key,
        "decision_source": decision_source,
        "review_status": _clean_text((parsed or {}).get("review_status")),
        "amended": False,
      })
      continue

    amended = _apply_metric_amendment(
      metric_key=metric_key, original_entry=original_entry, parsed=parsed,
    )
    if amended is None:
      per_metric_diagnostics.append({
        "metric_key": metric_key,
        "decision_source": decision_source,
        "review_status": _clean_text(parsed.get("review_status")),
        "amended": False,
        "reason": "rejected_invalid_or_point_range",
      })
      continue
    metrics[metric_key] = amended
    amended_metric_keys.append(metric_key)
    per_metric_diagnostics.append({
      "metric_key": metric_key,
      "decision_source": decision_source,
      "review_status": "amended",
      "amended": True,
    })

  uncalibrated_metric_keys: List[str] = []
  if not any_gpt_call_succeeded:
    fallback_tag = (
      "uncalibrated_due_to_no_api_key" if first_no_api_key
      else "uncalibrated_due_to_gpt_failure"
    )
    for metric_key, entry in metrics.items():
      if not isinstance(entry, dict):
        continue
      _tag_uncalibrated_metric(entry, fallback_tag=fallback_tag)
      uncalibrated_metric_keys.append(metric_key)

  proposal["metrics"] = metrics
  if amended_metric_keys or any_gpt_call_succeeded:
    rolling_decision_source = "python_proposer_plus_gpt_critic"
  elif first_no_api_key:
    rolling_decision_source = "python_proposer_only_no_api_key"
  elif any_gpt_call_failed:
    rolling_decision_source = "python_proposer_only_critic_failure"
  else:
    rolling_decision_source = "python_proposer_only_no_metrics_to_calibrate"

  proposal["calibration"] = {
    "consultant_name": _TARGET_SHAPING_CONSULTANT_NAME,
    "decision_source": rolling_decision_source,
    "amended_metric_keys": amended_metric_keys,
    "uncalibrated_metric_keys": uncalibrated_metric_keys,
    "per_metric_diagnostics": per_metric_diagnostics,
    "scope": "per_metric",
  }

  return {
    "calibrated_targets": proposal,
    "decision_source": rolling_decision_source,
    "amended_metric_keys": amended_metric_keys,
    "uncalibrated_metric_keys": uncalibrated_metric_keys,
    "raw_openai_response": {},
    "critic_diagnostics": {
      "scope": "per_metric",
      "per_metric_diagnostic_count": len(per_metric_diagnostics),
      "fallback_detail": "" if any_gpt_call_succeeded else rolling_decision_source,
    },
  }
