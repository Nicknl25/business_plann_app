"""Phase 3 — Driver-band shaping consultant.

Calibrates the deterministic driver_movement_envelope produced by the
Phase 2 assembler. Pattern follows the existing `Python proposes, GPT
critiques` flow:

  1. Python proposer (assemble_driver_movement_envelope) builds the full
     envelope from NAICS bands + applicability + mapping bounds.
  2. This consultant calls GPT with the proposal + business context and
     asks for surgical amendments per lever (typically tightening some
     bands, occasionally widening, occasionally flipping applicability).
  3. Corrections are applied via apply_corrections_to_proposal. After
     corrections, every amended driver entry is re-clamped to its
     mapping-table absolute bounds and ordering invariants
     (min_allowed <= default_value <= max_allowed) are re-enforced.
  4. Each amended entry's provenance.calibration_source is updated to
     `gpt_calibrated`. Entries the critic did not touch keep their
     original `naics_default` / `mapping_band_midpoint_no_naics_coverage` /
     `applicability_gate_not_applicable` source.
  5. On any failure (no API key, timeout, invalid JSON, validator
     rejection), Python's proposal stands. Each affected entry is tagged
     with calibration_source=`uncalibrated_due_to_gpt_failure` (or
     `_no_api_key`) so the orchestrator's diagnostics can surface it.

The consultant runs once per business at the start of the system run.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional


_BAND_SHAPING_CONSULTANT_NAME = "driver_movement_envelope_calibration"
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


_BAND_SHAPING_RESPONSE_SCHEMA: Dict[str, Any] = {
  "type": "object",
  "additionalProperties": False,
  "properties": {
    "review_status": {"type": "string", "enum": ["accepted", "amended", "rejected"]},
    "calibrated_drivers": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
          "lever_id": {"type": "string"},
          "applicable": {"type": ["boolean", "null"]},
          "min_allowed": {"type": ["number", "null"]},
          "max_allowed": {"type": ["number", "null"]},
          "default_value": {"type": ["number", "null"]},
          "rationale": {"type": "string"},
        },
        "required": [
          "lever_id", "applicable", "min_allowed", "max_allowed",
          "default_value", "rationale",
        ],
      },
    },
    "critique_summary": {"type": "string"},
  },
  "required": ["review_status", "calibrated_drivers", "critique_summary"],
}


_BAND_SHAPING_SYSTEM_PROMPT = (
  "You are reviewing a deterministic Python proposal for the driver "
  "movement envelopes that constrain a post-intake target-seeking "
  "solver. Each driver entry has min_allowed, max_allowed, and "
  "default_value (the NAICS benchmark target) plus an applicability "
  "decision. Python built the proposal from NAICS resolver bands, the "
  "mapping table's absolute live-value bounds, and per-lever "
  "applicability rules. You are the consultant that calibrates these "
  "bands to THIS specific business — typically tightening some bands "
  "where the business profile narrows the plausible range, occasionally "
  "widening, occasionally flipping applicability. "
  "\n\n"
  "Operating rules (NEVER violate):\n"
  "1. Output only `lever_id` values that already exist in the proposal. "
  "Do NOT invent new levers.\n"
  "2. min_allowed <= default_value <= max_allowed must hold after your "
  "amendment. Use values consistent with the proposal's value_kind "
  "(ratios are fractional, day_counts are days, etc.).\n"
  "3. Stay within plausibility for the business profile. If a lever's "
  "NAICS band is already narrow (e.g., COGS band is 0.55-0.65), only "
  "tighten further when the business profile clearly justifies it.\n"
  "4. When a lever is not applicable for this business, set "
  "`applicable=false` and the band fields to null (Python interprets "
  "this as a deterministic zero).\n"
  "5. Return review_status=accepted with empty calibrated_drivers when "
  "every Python entry is already correctly calibrated for this "
  "business. Return review_status=amended with only the calibrated "
  "drivers you want to change. Return review_status=rejected only when "
  "the proposal is structurally wrong; Python will fall back to the "
  "proposal anyway as the safety floor."
)


def _ensure_amended_entry_invariants(entry: Dict[str, Any]) -> Dict[str, Any]:
  """Re-clamp min/default/max ordering after a critic amendment.

  Keeps the proposal's mapping-table absolute bounds visible in
  provenance for downstream traceability. Removes amendments that
  violate min<=default<=max even after clamping.
  """
  applicable = bool(entry.get("applicable"))
  if not applicable:
    entry["min_allowed"] = 0.0
    entry["max_allowed"] = 0.0
    entry["default_value"] = 0.0
    return entry
  mn = _safe_float(entry.get("min_allowed"))
  mx = _safe_float(entry.get("max_allowed"))
  dv = _safe_float(entry.get("default_value"))
  if mn is not None and mx is not None and mx < mn:
    mn, mx = mx, mn
  if dv is not None and mn is not None and dv < mn:
    dv = mn
  if dv is not None and mx is not None and dv > mx:
    dv = mx
  if mn is not None:
    entry["min_allowed"] = round(float(mn), 6)
  if mx is not None:
    entry["max_allowed"] = round(float(mx), 6)
  if dv is not None:
    entry["default_value"] = round(float(dv), 6)
  return entry


def _build_user_context(
  *,
  proposal: Dict[str, Any],
  business_context: Dict[str, Any],
) -> Dict[str, Any]:
  drivers = proposal.get("drivers") or {}
  driver_summary: List[Dict[str, Any]] = []
  for lever_id, entry in drivers.items():
    if not isinstance(entry, dict):
      continue
    driver_summary.append({
      "lever_id": lever_id,
      "metric_key": entry.get("metric_key"),
      "value_kind": entry.get("value_kind"),
      "applicable": entry.get("applicable"),
      "schedule_locked": entry.get("schedule_locked"),
      "min_allowed": entry.get("min_allowed"),
      "default_value": entry.get("default_value"),
      "max_allowed": entry.get("max_allowed"),
      "calibration_source": (entry.get("provenance") or {}).get("calibration_source"),
    })
  return {
    "consultant": _BAND_SHAPING_CONSULTANT_NAME,
    "horizon_quarters": proposal.get("horizon"),
    "naics_6": proposal.get("naics_6"),
    "naics_2": proposal.get("naics_2"),
    "business_context": business_context,
    "proposed_drivers": driver_summary,
  }


def calibrate_driver_movement_envelope_with_gpt(
  *,
  envelope_proposal: Dict[str, Any],
  business_context: Optional[Dict[str, Any]] = None,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
  """Calibrate the driver movement envelope via GPT band-shaping consultant.

  Args:
    envelope_proposal: payload returned by assemble_driver_movement_envelope.
    business_context: dict of business-shaping signals the critic should
      consider (e.g. business_facts summary, ops planning_mode, stage
      ramp). Optional.
    timeout_seconds: critic call deadline.

  Returns:
    {
      "calibrated_envelope": <envelope payload, possibly mutated>,
      "decision_source": str,
      "amended_lever_ids": [...],
      "uncalibrated_lever_ids": [...],   # entries left at python defaults
      "raw_openai_response": dict,
      "critic_diagnostics": {...},
    }
  """
  proposal = copy.deepcopy(envelope_proposal or {})
  context = copy.deepcopy(business_context or {})
  drivers = proposal.get("drivers") if isinstance(proposal.get("drivers"), dict) else {}
  if not drivers:
    return {
      "calibrated_envelope": proposal,
      "decision_source": "python_proposer_only_no_drivers",
      "amended_lever_ids": [],
      "uncalibrated_lever_ids": [],
      "raw_openai_response": {},
      "critic_diagnostics": {"reason": "envelope_payload_has_no_drivers"},
    }

  from client_intake_and_finmo.post_intake_solver._gpt_critic_io import (  # type: ignore
    call_gpt_with_schema_or_fallback,
  )
  user_context = _build_user_context(proposal=proposal, business_context=context)
  call_result = call_gpt_with_schema_or_fallback(
    consultant_name=_BAND_SHAPING_CONSULTANT_NAME,
    system_prompt=_BAND_SHAPING_SYSTEM_PROMPT,
    user_context=user_context,
    response_schema=_BAND_SHAPING_RESPONSE_SCHEMA,
    schema_name=_BAND_SHAPING_CONSULTANT_NAME,
    timeout_seconds=timeout_seconds,
  )
  decision_source = call_result.get("decision_source") or "python_proposer_only_unknown"
  parsed = call_result.get("parsed") if isinstance(call_result.get("parsed"), dict) else None

  amended_lever_ids: List[str] = []
  if parsed and _clean_text(parsed.get("review_status")) == "amended":
    for amend in (parsed.get("calibrated_drivers") or []):
      if not isinstance(amend, dict):
        continue
      lever_id = _clean_text(amend.get("lever_id"))
      entry = drivers.get(lever_id)
      if not isinstance(entry, dict):
        continue
      original_provenance = entry.get("provenance") if isinstance(entry.get("provenance"), dict) else {}
      original_default_value = entry.get("default_value")
      original_min = entry.get("min_allowed")
      original_max = entry.get("max_allowed")
      original_applicable = bool(entry.get("applicable"))
      proposed_applicable = amend.get("applicable")
      if proposed_applicable is None:
        proposed_applicable = original_applicable
      proposed_min = _safe_float(amend.get("min_allowed"))
      proposed_max = _safe_float(amend.get("max_allowed"))
      proposed_default = _safe_float(amend.get("default_value"))
      next_entry = copy.deepcopy(entry)
      next_entry["applicable"] = bool(proposed_applicable)
      if proposed_min is not None:
        next_entry["min_allowed"] = float(proposed_min)
      if proposed_max is not None:
        next_entry["max_allowed"] = float(proposed_max)
      if proposed_default is not None:
        next_entry["default_value"] = float(proposed_default)
      next_entry = _ensure_amended_entry_invariants(next_entry)
      next_provenance = copy.deepcopy(original_provenance) if original_provenance else {}
      next_provenance["calibration_source"] = "gpt_calibrated"
      next_provenance["python_default"] = {
        "applicable": original_applicable,
        "min_allowed": original_min,
        "max_allowed": original_max,
        "default_value": original_default_value,
        "calibration_source_before": original_provenance.get("calibration_source"),
      }
      next_provenance["gpt_amendment"] = {
        "rationale": _clean_text(amend.get("rationale")),
      }
      next_entry["provenance"] = next_provenance
      drivers[lever_id] = next_entry
      amended_lever_ids.append(lever_id)

  # When the critic call did not succeed, surface the failure on every
  # entry so downstream traceability shows the conservative-by-default
  # path was taken.
  uncalibrated_lever_ids: List[str] = []
  if decision_source != "python_proposer_plus_gpt_critic":
    fallback_tag = (
      "uncalibrated_due_to_no_api_key"
      if decision_source == "python_proposer_only_no_api_key"
      else "uncalibrated_due_to_gpt_failure"
    )
    for lever_id, entry in drivers.items():
      if not isinstance(entry, dict):
        continue
      provenance = entry.get("provenance") if isinstance(entry.get("provenance"), dict) else {}
      original_source = _clean_text(provenance.get("calibration_source"))
      if original_source in {"naics_default", "applicability_gate_not_applicable"}:
        continue
      provenance.setdefault("python_default_calibration_source", original_source)
      provenance["calibration_source"] = fallback_tag
      entry["provenance"] = provenance
      uncalibrated_lever_ids.append(lever_id)

  proposal["drivers"] = drivers
  proposal["calibration"] = {
    "consultant_name": _BAND_SHAPING_CONSULTANT_NAME,
    "decision_source": decision_source,
    "model_used": call_result.get("model_used"),
    "amended_lever_ids": amended_lever_ids,
    "uncalibrated_lever_ids": uncalibrated_lever_ids,
    "review_status": _clean_text((parsed or {}).get("review_status")) or "not_invoked",
    "critique_summary": _clean_text((parsed or {}).get("critique_summary")),
    "fallback_detail": call_result.get("detail"),
  }

  return {
    "calibrated_envelope": proposal,
    "decision_source": decision_source,
    "amended_lever_ids": amended_lever_ids,
    "uncalibrated_lever_ids": uncalibrated_lever_ids,
    "raw_openai_response": call_result.get("raw_openai_response") or {},
    "critic_diagnostics": {
      "review_status": _clean_text((parsed or {}).get("review_status")) or "not_invoked",
      "critique_summary": _clean_text((parsed or {}).get("critique_summary")),
      "fallback_detail": call_result.get("detail"),
    },
  }
