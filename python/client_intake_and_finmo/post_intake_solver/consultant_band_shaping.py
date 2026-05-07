"""Phase 3 / 5.2 — Per-lever driver-band shaping consultant.

Calibrates the deterministic ``driver_movement_envelope`` produced by the
Phase 2 assembler. Pattern:

  1. Python proposer (assemble_driver_movement_envelope) builds the full
     envelope from NAICS bands + applicability + mapping bounds.
  2. For each applicable, non-schedule-locked lever, this consultant
     resolves a per-lever GPT context dict via ``resolve_consultant_context``
     scoped to that lever_id (Phase 5.2 R1) and asks GPT to amend the
     band for that single lever.
  3. The amendment is run through the buffer-rule validators
     (Phase 5.2 R2) — strict min<max, applicability flip restriction,
     width buffer. Violations fail-fast; the orchestrator's adaptation
     cascade (Tier 1) walks the offending lever back to the Python
     default and continues.
  4. Surviving amendments are stamped onto the envelope with
     calibration_source=``gpt_calibrated``.

GPT temperature is 0.0 (deterministic); each per-lever call has a
small (~3KB) payload focused on one decision. Per-lever scoping was
the explicit Phase 5.2 R1 requirement after Phase 5.1's monolithic
25KB-per-call payload over-influenced GPT into broad zero-outs.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional


_BAND_SHAPING_CONSULTANT_NAME = "driver_movement_envelope_calibration"
_BAND_SHAPING_CONTRACT_NAME = "post_intake_band_shaping_consultant"
_BAND_SHAPING_INCLUDE_PHASE = "band_shaping"
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


_PER_LEVER_RESPONSE_SCHEMA: Dict[str, Any] = {
  "type": "object",
  "additionalProperties": False,
  "properties": {
    "review_status": {"type": "string", "enum": ["accepted", "amended", "rejected"]},
    "applicable": {"type": ["boolean", "null"]},
    "min_allowed": {"type": ["number", "null"]},
    "max_allowed": {"type": ["number", "null"]},
    "default_value": {"type": ["number", "null"]},
    "rationale": {"type": "string"},
  },
  "required": [
    "review_status", "applicable", "min_allowed", "max_allowed",
    "default_value", "rationale",
  ],
}


_PER_LEVER_SYSTEM_PROMPT = (
  "You are calibrating ONE driver band for a post-intake target-seeking "
  "solver. The band has min_allowed, max_allowed, and default_value (the "
  "NAICS / cohort benchmark) plus an applicability decision. Python built "
  "the band from cohort percentiles (when available), the NAICS cascade "
  "resolver, and per-lever applicability rules.\n\n"
  "You receive: the lever's value_kind, the Python proposer's band, the "
  "lever's structural metadata, and a small business-context snapshot. "
  "Decide whether to keep the Python band, tighten it, widen it, or "
  "(when the lever has a declared applicability rule and the business "
  "doesn't use this lever) flip applicable=false.\n\n"
  "Operating rules (NEVER violate):\n"
  "1. min_allowed < max_allowed STRICTLY when applicable=true. Point "
  "bands [x,x] are rejected by the validator. Use min_allowed < "
  "default_value < max_allowed.\n"
  "2. Stay within plausibility for the business profile. Tightening must "
  "leave at least 25% of the Python band width, and at least the "
  "value_kind absolute minimum (e.g. 2 percentage points for "
  "percent-of-revenue, 5 days for day-count metrics).\n"
  "3. Flip applicable=true → applicable=false ONLY if the lever has a "
  "declared applicability rule (the business-context section will tell "
  "you). For levers without a declared rule, never propose "
  "applicable=false; tighten the band instead.\n"
  "4. review_status=accepted means keep the proposal unchanged "
  "(callers ignore the other fields). review_status=amended means use "
  "the supplied min_allowed / max_allowed / default_value / applicable. "
  "review_status=rejected is a strong signal the proposal is "
  "structurally wrong; the system falls back to the Python default."
)


def _build_per_lever_user_context(
  *,
  lever_id: str,
  lever_entry: Dict[str, Any],
  resolver_context: Dict[str, Any],
) -> Dict[str, Any]:
  return {
    "consultant": _BAND_SHAPING_CONSULTANT_NAME,
    "lever_id": lever_id,
    "value_kind": lever_entry.get("value_kind"),
    "metric_key": lever_entry.get("metric_key"),
    "schedule_locked": lever_entry.get("schedule_locked"),
    "python_proposed_band": {
      "applicable": lever_entry.get("applicable"),
      "min_allowed": lever_entry.get("min_allowed"),
      "max_allowed": lever_entry.get("max_allowed"),
      "default_value": lever_entry.get("default_value"),
      "calibration_source": (lever_entry.get("provenance") or {}).get("calibration_source"),
      "applicability_reason": (
        ((lever_entry.get("provenance") or {}).get("applicability") or {}).get("reason")
      ),
    },
    "context": resolver_context,
  }


def _apply_amendment(
  *,
  lever_id: str,
  original_entry: Dict[str, Any],
  parsed: Dict[str, Any],
) -> Dict[str, Any]:
  from client_intake_and_finmo.post_intake_solver.consultant_band_amendment_rules import (  # type: ignore
    validate_band_amendment,
  )

  proposed_applicable = parsed.get("applicable")
  if proposed_applicable is None:
    proposed_applicable = bool(original_entry.get("applicable"))
  proposed_min = _safe_float(parsed.get("min_allowed"))
  proposed_max = _safe_float(parsed.get("max_allowed"))
  proposed_default = _safe_float(parsed.get("default_value"))

  validate_band_amendment(
    lever_id=lever_id,
    original_entry=original_entry,
    proposed_applicable=bool(proposed_applicable),
    proposed_min=proposed_min,
    proposed_max=proposed_max,
    proposed_default=proposed_default,
  )

  next_entry = copy.deepcopy(original_entry)
  next_entry["applicable"] = bool(proposed_applicable)
  if not bool(proposed_applicable):
    next_entry["min_allowed"] = 0.0
    next_entry["max_allowed"] = 0.0
    next_entry["default_value"] = 0.0
  else:
    if proposed_min is not None:
      next_entry["min_allowed"] = round(float(proposed_min), 6)
    if proposed_max is not None:
      next_entry["max_allowed"] = round(float(proposed_max), 6)
    if proposed_default is not None:
      next_entry["default_value"] = round(float(proposed_default), 6)
    # Ensure default sits inside the proposed band even if GPT provided
    # an off-band default value alongside a valid min/max.
    mn = _safe_float(next_entry.get("min_allowed"))
    mx = _safe_float(next_entry.get("max_allowed"))
    dv = _safe_float(next_entry.get("default_value"))
    if mn is not None and dv is not None and dv < mn:
      next_entry["default_value"] = round(float(mn), 6)
    if mx is not None and dv is not None and dv > mx:
      next_entry["default_value"] = round(float(mx), 6)

  original_provenance = (
    original_entry.get("provenance") if isinstance(original_entry.get("provenance"), dict) else {}
  )
  next_provenance = copy.deepcopy(original_provenance) if original_provenance else {}
  next_provenance["calibration_source"] = "gpt_calibrated"
  next_provenance["python_default"] = {
    "applicable": bool(original_entry.get("applicable")),
    "min_allowed": original_entry.get("min_allowed"),
    "max_allowed": original_entry.get("max_allowed"),
    "default_value": original_entry.get("default_value"),
    "calibration_source_before": original_provenance.get("calibration_source"),
  }
  next_provenance["gpt_amendment"] = {
    "rationale": _clean_text(parsed.get("rationale")),
  }
  next_entry["provenance"] = next_provenance
  return next_entry


def _tag_uncalibrated(entry: Dict[str, Any], *, fallback_tag: str) -> None:
  provenance = entry.get("provenance") if isinstance(entry.get("provenance"), dict) else {}
  original_source = _clean_text(provenance.get("calibration_source"))
  if original_source in {"naics_default", "applicability_gate_not_applicable"}:
    return
  if original_source.startswith("cohort_matched_"):
    return
  provenance.setdefault("python_default_calibration_source", original_source)
  provenance["calibration_source"] = fallback_tag
  entry["provenance"] = provenance


def calibrate_driver_movement_envelope_with_gpt(
  *,
  envelope_proposal: Dict[str, Any],
  draft_id: str,
  planning_run_id: str,
  conn: Any,
  runtime_objects: Dict[str, Any],
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
  """Calibrate driver movement envelope band-by-band via GPT.

  The orchestrator passes the conn + draft_id + planning_run_id so the
  resolver can fetch from intake_consult_drafts and the data-query
  registry. ``runtime_objects`` is a small dict of in-memory artifacts
  the resolver dereferences via source_kind=runtime_object (e.g.,
  ``business_facts``, ``envelope_proposal``).

  Returns the same payload shape as before so the orchestrator's
  diagnostic accumulation continues to work.
  """
  proposal = copy.deepcopy(envelope_proposal or {})
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
  from client_intake_and_finmo.post_intake_solver.consultant_context_resolver import (  # type: ignore
    resolve_consultant_context,
  )

  amended_lever_ids: List[str] = []
  per_lever_diagnostics: List[Dict[str, Any]] = []
  any_gpt_call_succeeded = False
  any_gpt_call_failed = False
  first_no_api_key = False

  for lever_id, original_entry in list(drivers.items()):
    if not isinstance(original_entry, dict):
      continue
    if not bool(original_entry.get("applicable")):
      continue
    if bool(original_entry.get("schedule_locked")):
      continue

    scoped_runtime = dict(runtime_objects or {})
    scoped_runtime["lever_entry"] = copy.deepcopy(original_entry)

    resolver_context = resolve_consultant_context(
      contract_name=_BAND_SHAPING_CONTRACT_NAME,
      include_phase=_BAND_SHAPING_INCLUDE_PHASE,
      scope_key={"lever_id": lever_id},
      draft_id=draft_id,
      planning_run_id=planning_run_id,
      conn=conn,
      runtime_objects=scoped_runtime,
    )

    user_context = _build_per_lever_user_context(
      lever_id=lever_id,
      lever_entry=original_entry,
      resolver_context=resolver_context,
    )
    call_result = call_gpt_with_schema_or_fallback(
      consultant_name=_BAND_SHAPING_CONSULTANT_NAME,
      system_prompt=_PER_LEVER_SYSTEM_PROMPT,
      user_context=user_context,
      response_schema=_PER_LEVER_RESPONSE_SCHEMA,
      schema_name=_BAND_SHAPING_CONSULTANT_NAME,
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
      per_lever_diagnostics.append({
        "lever_id": lever_id,
        "decision_source": decision_source,
        "review_status": _clean_text((parsed or {}).get("review_status")),
        "amended": False,
      })
      continue

    next_entry = _apply_amendment(
      lever_id=lever_id, original_entry=original_entry, parsed=parsed,
    )
    drivers[lever_id] = next_entry
    amended_lever_ids.append(lever_id)
    per_lever_diagnostics.append({
      "lever_id": lever_id,
      "decision_source": decision_source,
      "review_status": "amended",
      "amended": True,
    })

  uncalibrated_lever_ids: List[str] = []
  if not any_gpt_call_succeeded:
    fallback_tag = (
      "uncalibrated_due_to_no_api_key" if first_no_api_key
      else "uncalibrated_due_to_gpt_failure"
    )
    for lever_id, entry in drivers.items():
      if not isinstance(entry, dict):
        continue
      _tag_uncalibrated(entry, fallback_tag=fallback_tag)
      uncalibrated_lever_ids.append(lever_id)

  proposal["drivers"] = drivers
  if amended_lever_ids:
    rolling_decision_source = "python_proposer_plus_gpt_critic"
  elif any_gpt_call_succeeded:
    rolling_decision_source = "python_proposer_plus_gpt_critic"
  elif first_no_api_key:
    rolling_decision_source = "python_proposer_only_no_api_key"
  elif any_gpt_call_failed:
    rolling_decision_source = "python_proposer_only_critic_failure"
  else:
    rolling_decision_source = "python_proposer_only_no_levers_to_calibrate"

  proposal["calibration"] = {
    "consultant_name": _BAND_SHAPING_CONSULTANT_NAME,
    "decision_source": rolling_decision_source,
    "amended_lever_ids": amended_lever_ids,
    "uncalibrated_lever_ids": uncalibrated_lever_ids,
    "per_lever_diagnostics": per_lever_diagnostics,
    "scope": "per_lever",
  }

  return {
    "calibrated_envelope": proposal,
    "decision_source": rolling_decision_source,
    "amended_lever_ids": amended_lever_ids,
    "uncalibrated_lever_ids": uncalibrated_lever_ids,
    "raw_openai_response": {},
    "critic_diagnostics": {
      "scope": "per_lever",
      "per_lever_diagnostic_count": len(per_lever_diagnostics),
      "fallback_detail": "" if any_gpt_call_succeeded else rolling_decision_source,
    },
  }
