"""Phase 3 — FINMO output target shaping consultant.

Calibrates the deterministic finmo_output_targets payload produced by the
Phase 2 assembler. Same proposer/critic shape as the band-shaping
consultant.

Per the directive: "bootstrapped profitable from Q1 -> EBITDA target
15-25%; VC-funded with runway focus -> EBITDA target -10% to +5% Y1,
ramping to +20% Y3" — these per-business calibrations are exactly what
this consultant produces. Python's defaults are the steady-state NAICS
band; GPT shapes them for the business profile and stage.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional


_TARGET_SHAPING_CONSULTANT_NAME = "finmo_output_targets_calibration"
_DEFAULT_TIMEOUT_SECONDS = 45.0


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


_TARGET_SHAPING_RESPONSE_SCHEMA: Dict[str, Any] = {
  "type": "object",
  "additionalProperties": False,
  "properties": {
    "review_status": {"type": "string", "enum": ["accepted", "amended", "rejected"]},
    "calibrated_metrics": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
          "metric_key": {"type": "string"},
          "target_min": {"type": ["number", "null"]},
          "target_target": {"type": ["number", "null"]},
          "target_max": {"type": ["number", "null"]},
          "rationale": {"type": "string"},
        },
        "required": [
          "metric_key", "target_min", "target_target", "target_max",
          "rationale",
        ],
      },
    },
    "critique_summary": {"type": "string"},
  },
  "required": ["review_status", "calibrated_metrics", "critique_summary"],
}


_TARGET_SHAPING_SYSTEM_PROMPT = (
  "You are reviewing a deterministic Python proposal for the FINMO "
  "output target ranges that a post-intake target-seeking solver chases. "
  "Each metric entry has target_min, target_target, target_max from the "
  "NAICS band plus a per-confidence-tier tolerance widening. You are "
  "the consultant that calibrates these targets to THIS specific "
  "business — typically tightening for steady-state mature operations, "
  "widening for early-stage / growth / turnaround / runway-focused "
  "businesses where launch-quarter volatility legitimately lands "
  "outside steady-state bands.\n\n"
  "Operating rules:\n"
  "1. Output only `metric_key` values that already exist in the "
  "proposal. Do NOT invent new metrics.\n"
  "2. target_min <= target_target <= target_max must hold after your "
  "amendment.\n"
  "3. For metrics whose realism gate_kind is `hard_fail` (e.g., "
  "cogs_to_revenue_ratio, ar_days_dso, ap_days_dpo, effective_tax_rate), "
  "tightening is strongly preferred over widening — these are the "
  "metrics the system will fail loudly on if the solver cannot land "
  "them. Widen only when the business profile clearly justifies it.\n"
  "4. For warn-mode metrics (ebitda_margin, gross_margin_percent, "
  "operating_margin_percent, etc.), per-stage shaping is the primary "
  "use case. A bootstrapped Q1 ebitda may legitimately be -15% even "
  "when the steady-state band is +18% to +28%.\n"
  "5. Return review_status=accepted when the Python proposal is "
  "already correct. Return review_status=amended with only the metrics "
  "you want to change. Return review_status=rejected only when the "
  "proposal is structurally wrong; Python will fall back as the safety "
  "floor."
)


def _ensure_target_invariants(entry: Dict[str, Any]) -> Dict[str, Any]:
  mn = _safe_float(entry.get("target_min"))
  tg = _safe_float(entry.get("target_target"))
  mx = _safe_float(entry.get("target_max"))
  if mn is not None and mx is not None and mx < mn:
    mn, mx = mx, mn
  if tg is not None and mn is not None and tg < mn:
    tg = mn
  if tg is not None and mx is not None and tg > mx:
    tg = mx
  if mn is not None:
    entry["target_min"] = round(float(mn), 6)
  if mx is not None:
    entry["target_max"] = round(float(mx), 6)
  if tg is not None:
    entry["target_target"] = round(float(tg), 6)
  return entry


def _build_user_context(
  *,
  proposal: Dict[str, Any],
  business_context: Dict[str, Any],
) -> Dict[str, Any]:
  metrics = proposal.get("metrics") or {}
  metric_summary: List[Dict[str, Any]] = []
  for metric_key, entry in metrics.items():
    if not isinstance(entry, dict):
      continue
    metric_summary.append({
      "metric_key": metric_key,
      "finmo_line_label": entry.get("finmo_line_label"),
      "gate_kind": entry.get("gate_kind"),
      "quarter_aggregation": entry.get("quarter_aggregation"),
      "applicability_rule_key": entry.get("applicability_rule_key"),
      "target_min": entry.get("target_min"),
      "target_target": entry.get("target_target"),
      "target_max": entry.get("target_max"),
      "calibration_source": (entry.get("provenance") or {}).get("calibration_source"),
      "confidence_tier": (entry.get("provenance") or {}).get("confidence_tier"),
    })
  return {
    "consultant": _TARGET_SHAPING_CONSULTANT_NAME,
    "horizon_quarters": proposal.get("horizon"),
    "naics_6": proposal.get("naics_6"),
    "business_context": business_context,
    "proposed_metrics": metric_summary,
  }


def calibrate_finmo_output_targets_with_gpt(
  *,
  targets_proposal: Dict[str, Any],
  business_context: Optional[Dict[str, Any]] = None,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
  """Calibrate FINMO output targets via GPT target-shaping consultant.

  Returns:
    {
      "calibrated_targets": <targets payload, possibly mutated>,
      "decision_source": str,
      "amended_metric_keys": [...],
      "uncalibrated_metric_keys": [...],
      "raw_openai_response": dict,
      "critic_diagnostics": {...},
    }
  """
  proposal = copy.deepcopy(targets_proposal or {})
  context = copy.deepcopy(business_context or {})
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
  user_context = _build_user_context(proposal=proposal, business_context=context)
  call_result = call_gpt_with_schema_or_fallback(
    consultant_name=_TARGET_SHAPING_CONSULTANT_NAME,
    system_prompt=_TARGET_SHAPING_SYSTEM_PROMPT,
    user_context=user_context,
    response_schema=_TARGET_SHAPING_RESPONSE_SCHEMA,
    schema_name=_TARGET_SHAPING_CONSULTANT_NAME,
    timeout_seconds=timeout_seconds,
  )
  decision_source = call_result.get("decision_source") or "python_proposer_only_unknown"
  parsed = call_result.get("parsed") if isinstance(call_result.get("parsed"), dict) else None

  amended_metric_keys: List[str] = []
  if parsed and _clean_text(parsed.get("review_status")) == "amended":
    for amend in (parsed.get("calibrated_metrics") or []):
      if not isinstance(amend, dict):
        continue
      metric_key = _clean_text(amend.get("metric_key"))
      entry = metrics.get(metric_key)
      if not isinstance(entry, dict):
        continue
      original_provenance = entry.get("provenance") if isinstance(entry.get("provenance"), dict) else {}
      original_min = entry.get("target_min")
      original_target = entry.get("target_target")
      original_max = entry.get("target_max")
      proposed_min = _safe_float(amend.get("target_min"))
      proposed_target = _safe_float(amend.get("target_target"))
      proposed_max = _safe_float(amend.get("target_max"))
      next_entry = copy.deepcopy(entry)
      if proposed_min is not None:
        next_entry["target_min"] = float(proposed_min)
      if proposed_target is not None:
        next_entry["target_target"] = float(proposed_target)
      if proposed_max is not None:
        next_entry["target_max"] = float(proposed_max)
      next_entry = _ensure_target_invariants(next_entry)
      next_provenance = copy.deepcopy(original_provenance) if original_provenance else {}
      next_provenance["calibration_source"] = "gpt_calibrated"
      next_provenance["python_default"] = {
        "target_min": original_min,
        "target_target": original_target,
        "target_max": original_max,
        "calibration_source_before": original_provenance.get("calibration_source"),
      }
      next_provenance["gpt_amendment"] = {"rationale": _clean_text(amend.get("rationale"))}
      next_entry["provenance"] = next_provenance
      metrics[metric_key] = next_entry
      amended_metric_keys.append(metric_key)

  uncalibrated_metric_keys: List[str] = []
  if decision_source != "python_proposer_plus_gpt_critic":
    fallback_tag = (
      "uncalibrated_due_to_no_api_key"
      if decision_source == "python_proposer_only_no_api_key"
      else "uncalibrated_due_to_gpt_failure"
    )
    for metric_key, entry in metrics.items():
      if not isinstance(entry, dict):
        continue
      provenance = entry.get("provenance") if isinstance(entry.get("provenance"), dict) else {}
      original_source = _clean_text(provenance.get("calibration_source"))
      if original_source == "naics_default":
        continue
      provenance.setdefault("python_default_calibration_source", original_source)
      provenance["calibration_source"] = fallback_tag
      entry["provenance"] = provenance
      uncalibrated_metric_keys.append(metric_key)

  proposal["metrics"] = metrics
  proposal["calibration"] = {
    "consultant_name": _TARGET_SHAPING_CONSULTANT_NAME,
    "decision_source": decision_source,
    "model_used": call_result.get("model_used"),
    "amended_metric_keys": amended_metric_keys,
    "uncalibrated_metric_keys": uncalibrated_metric_keys,
    "review_status": _clean_text((parsed or {}).get("review_status")) or "not_invoked",
    "critique_summary": _clean_text((parsed or {}).get("critique_summary")),
    "fallback_detail": call_result.get("detail"),
  }

  return {
    "calibrated_targets": proposal,
    "decision_source": decision_source,
    "amended_metric_keys": amended_metric_keys,
    "uncalibrated_metric_keys": uncalibrated_metric_keys,
    "raw_openai_response": call_result.get("raw_openai_response") or {},
    "critic_diagnostics": {
      "review_status": _clean_text((parsed or {}).get("review_status")) or "not_invoked",
      "critique_summary": _clean_text((parsed or {}).get("critique_summary")),
      "fallback_detail": call_result.get("detail"),
    },
  }
