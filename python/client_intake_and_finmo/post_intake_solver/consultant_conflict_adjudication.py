"""Phase 3 / 5.2 — Per-conflict intake-vs-band adjudication consultant.

After band shaping calibrates the driver envelope, the intake-implied
value for some levers may fall outside the calibrated band. Per
Phase 5.2 R1, GPT is invoked once per detected conflict with a
per-conflict scoped context dict resolved by
``resolve_consultant_context``.

Three legal decisions per conflict:
  - keep_intake: widen the calibrated band to include the intake value.
    Q0 stub stays at intake AND Q1+ trajectory anchors near intake too.
  - keep_band: keep the calibrated band; the intake value is implausible
    (data-entry error, pre-restructure artifact). Q0 stays at intake
    (per the solver's Phase 1 invariant) but Q1+ uses the band default.
  - split: explicit Q0/Q1+ split. Same band as keep_band but with a
    different rationale: the intake value is plausible historically but
    should not propagate to the forecast.

Buffer rules (Phase 5.2 R2):
  - For keep_intake amendments, the resulting band must satisfy
    min_allowed < max_allowed strictly. The Python proposer's band
    already satisfies this and keep_intake only widens, so this is
    a sanity assertion rather than a normal rejection path.
  - keep_band / split don't change the band, so no buffer check fires.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple


_CONFLICT_ADJUDICATION_CONSULTANT_NAME = "solver_intake_band_conflict"
_CONFLICT_ADJUDICATION_CONTRACT_NAME = "post_intake_conflict_adjudication_consultant"
_CONFLICT_ADJUDICATION_INCLUDE_PHASE = "conflict_adjudication"
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


_PER_CONFLICT_RESPONSE_SCHEMA: Dict[str, Any] = {
  "type": "object",
  "additionalProperties": False,
  "properties": {
    "decision": {
      "type": "string",
      "enum": ["keep_intake", "keep_band", "split"],
    },
    "resolved_min_allowed": {"type": ["number", "null"]},
    "resolved_max_allowed": {"type": ["number", "null"]},
    "resolved_default_value": {"type": ["number", "null"]},
    "rationale": {"type": "string"},
  },
  "required": [
    "decision", "resolved_min_allowed", "resolved_max_allowed",
    "resolved_default_value", "rationale",
  ],
}


_PER_CONFLICT_SYSTEM_PROMPT = (
  "You are adjudicating ONE conflict between an intake-implied driver "
  "value and the calibrated band for that driver. Decide one of three "
  "resolutions:\n"
  "  - keep_intake: the intake value is correct for this business; "
  "    widen the band to include it (return resolved_min_allowed / "
  "    resolved_max_allowed that span both the original band and the "
  "    intake value, plus a resolved_default_value at the intake value).\n"
  "  - keep_band: the intake value is implausible (data-entry error or "
  "    pre-restructure artifact); keep the band unchanged (return "
  "    nulls and Python preserves the originals).\n"
  "  - split: the intake value is plausible historically but should "
  "    not propagate to the forecast; keep the band unchanged for Q1+. "
  "    Q0 stub stays at intake regardless.\n\n"
  "Operating rules:\n"
  "1. resolved_min_allowed < resolved_max_allowed strictly.\n"
  "2. For keep_band / split, return null for resolved_* fields.\n"
  "3. For keep_intake, the resolved band must include the intake value: "
  "   resolved_min_allowed <= intake_value <= resolved_max_allowed.\n"
  "4. Default to keep_band when the intake value looks like a data "
  "   entry error or the business has clearly changed since the intake "
  "   snapshot. Default to keep_intake only when the intake value is "
  "   well-attested and characteristic of forward operations."
)


def _intake_implied_for_lever(
  *,
  lever_id: str,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Optional[Tuple[float, Dict[str, Any]]]:
  fin = financials_json if isinstance(financials_json, dict) else {}
  year1 = financials_year1_json if isinstance(financials_year1_json, dict) else {}
  revenue_year_one = (
    _safe_float(year1.get("company_revenue_total_year1"))
    or _safe_float(year1.get("revenue_total_year1"))
    or _safe_float(fin.get("current_revenue"))
  )
  quarter_revenue = float(revenue_year_one) / 4.0 if revenue_year_one and revenue_year_one > 0 else None

  if lever_id == "balance_sheet::Accounts Receivable Days":
    ar = _safe_float(fin.get("ar_balance"))
    if ar is None or ar <= 0 or quarter_revenue is None:
      return None
    return (ar / quarter_revenue) * 90.0, {"formula": "ar_balance / quarter_revenue * 90"}
  if lever_id == "balance_sheet::Accounts Payable Days":
    ap = _safe_float(fin.get("ap_balance"))
    if ap is None or ap <= 0 or quarter_revenue is None:
      return None
    return (ap / quarter_revenue) * 90.0, {"formula": "ap_balance / quarter_revenue * 90"}
  if lever_id == "balance_sheet::Inventory Days":
    inv = _safe_float(fin.get("inventory_balance"))
    if inv is None or inv <= 0 or quarter_revenue is None:
      return None
    return (inv / quarter_revenue) * 90.0, {"formula": "inventory_balance / quarter_revenue * 90"}
  if lever_id == "expenses::Cost of Goods Sold":
    cogs = _safe_float(fin.get("cogs_year_one")) or _safe_float(fin.get("current_cogs"))
    if cogs is None or cogs <= 0 or revenue_year_one is None or revenue_year_one <= 0:
      pct = _safe_float(fin.get("cogs_percent_of_revenue"))
      if pct is None:
        return None
      return float(pct), {"formula": "cogs_percent_of_revenue (intake)"}
    return float(cogs) / float(revenue_year_one), {"formula": "cogs_year_one / revenue_year_one"}
  if lever_id == "expenses::Marketing":
    pct = _safe_float(fin.get("marketing_percent_of_revenue"))
    if pct is None:
      return None
    return float(pct), {"formula": "marketing_percent_of_revenue (intake)"}
  if lever_id == "expenses::Research & Development":
    pct = (
      _safe_float(fin.get("r_and_d_percent"))
      or _safe_float(fin.get("research_and_development_percent"))
      or _safe_float(fin.get("rd_percent_of_revenue"))
    )
    if pct is None:
      return None
    return float(pct), {"formula": "r_and_d_percent_of_revenue (intake)"}
  if lever_id == "expenses::Taxes":
    pct = _safe_float(fin.get("taxes_percent"))
    if pct is None:
      return None
    return float(pct), {"formula": "taxes_percent (intake)"}
  return None


def _detect_conflicts(
  *,
  envelope_payload: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> List[Dict[str, Any]]:
  drivers = envelope_payload.get("drivers") if isinstance(envelope_payload.get("drivers"), dict) else {}
  conflicts: List[Dict[str, Any]] = []
  for lever_id, entry in drivers.items():
    if not isinstance(entry, dict) or not entry.get("applicable"):
      continue
    mn = _safe_float(entry.get("min_allowed"))
    mx = _safe_float(entry.get("max_allowed"))
    if mn is None or mx is None:
      continue
    intake = _intake_implied_for_lever(
      lever_id=lever_id,
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
    )
    if intake is None:
      continue
    intake_value, intake_provenance = intake
    if mn <= intake_value <= mx:
      continue
    conflicts.append({
      "lever_id": lever_id,
      "intake_value": round(float(intake_value), 6),
      "intake_provenance": intake_provenance,
      "calibrated_min_allowed": round(float(mn), 6),
      "calibrated_max_allowed": round(float(mx), 6),
      "calibrated_default_value": entry.get("default_value"),
      "value_kind": entry.get("value_kind"),
      "metric_key": entry.get("metric_key"),
      "side": "below" if intake_value < mn else "above",
    })
  return conflicts


def _apply_decision(
  *,
  envelope_payload: Dict[str, Any],
  conflict: Dict[str, Any],
  decision: Dict[str, Any],
  decision_came_from_gpt: bool,
) -> Dict[str, Any]:
  drivers = envelope_payload.get("drivers") if isinstance(envelope_payload.get("drivers"), dict) else {}
  if not isinstance(drivers, dict):
    return envelope_payload
  lever_id = _clean_text(conflict.get("lever_id"))
  entry = drivers.get(lever_id)
  if not isinstance(entry, dict):
    return envelope_payload
  decision_kind = _clean_text(decision.get("decision")).lower()
  rationale = _clean_text(decision.get("rationale"))
  intake_value = _safe_float(conflict.get("intake_value"))
  resolved_min = _safe_float(decision.get("resolved_min_allowed"))
  resolved_max = _safe_float(decision.get("resolved_max_allowed"))
  resolved_default = _safe_float(decision.get("resolved_default_value"))

  next_entry = copy.deepcopy(entry)
  if decision_kind == "keep_intake" and intake_value is not None:
    original_min = _safe_float(entry.get("min_allowed"))
    original_max = _safe_float(entry.get("max_allowed"))
    if resolved_min is None or resolved_max is None or resolved_default is None:
      resolved_min = min(original_min if original_min is not None else intake_value, intake_value)
      resolved_max = max(original_max if original_max is not None else intake_value, intake_value)
      resolved_default = intake_value
    if resolved_min > intake_value:
      resolved_min = intake_value
    if resolved_max < intake_value:
      resolved_max = intake_value
    if resolved_max <= resolved_min:
      # Buffer rule mechanic 1: strict inequality. Adjudication may not
      # produce a point band; treat as a fall-back to keep_band.
      decision_kind = "keep_band"
      provenance = next_entry.get("provenance") if isinstance(next_entry.get("provenance"), dict) else {}
      provenance["intake_band_conflict_keep_intake_rejected_point_band"] = True
      next_entry["provenance"] = provenance
    else:
      if resolved_default < resolved_min:
        resolved_default = resolved_min
      if resolved_default > resolved_max:
        resolved_default = resolved_max
      next_entry["min_allowed"] = round(float(resolved_min), 6)
      next_entry["max_allowed"] = round(float(resolved_max), 6)
      next_entry["default_value"] = round(float(resolved_default), 6)

  provenance = next_entry.get("provenance") if isinstance(next_entry.get("provenance"), dict) else {}
  provenance.setdefault("python_default_calibration_source", provenance.get("calibration_source"))
  provenance["calibration_source"] = (
    "gpt_calibrated_via_conflict_adjudication"
    if decision_came_from_gpt
    else "conservative_fallback_keep_band_no_gpt_adjudication"
  )
  provenance["intake_band_conflict"] = {
    "intake_value": conflict.get("intake_value"),
    "intake_provenance": conflict.get("intake_provenance"),
    "side": conflict.get("side"),
    "calibrated_band_before": {
      "min_allowed": conflict.get("calibrated_min_allowed"),
      "max_allowed": conflict.get("calibrated_max_allowed"),
      "default_value": conflict.get("calibrated_default_value"),
    },
    "decision": decision_kind,
    "rationale": rationale,
  }
  next_entry["provenance"] = provenance
  drivers[lever_id] = next_entry
  envelope_payload["drivers"] = drivers
  return envelope_payload


def adjudicate_intake_vs_band_conflicts_with_gpt(
  *,
  envelope_payload: Dict[str, Any],
  financials_json: Optional[Dict[str, Any]],
  financials_year1_json: Optional[Dict[str, Any]],
  draft_id: str,
  planning_run_id: str,
  conn: Any,
  runtime_objects: Dict[str, Any],
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
  """Detect intake-vs-band conflicts and adjudicate per-conflict via GPT."""
  envelope = copy.deepcopy(envelope_payload or {})
  fin = financials_json or {}
  year1 = financials_year1_json or {}
  conflicts = _detect_conflicts(
    envelope_payload=envelope,
    financials_json=fin,
    financials_year1_json=year1,
  )

  if not conflicts:
    return {
      "calibrated_envelope": envelope,
      "decision_source": "no_conflicts_detected",
      "conflicts_detected": 0,
      "decisions_applied": [],
      "raw_openai_response": {},
      "fallback_detail": "",
    }

  from client_intake_and_finmo.post_intake_solver._gpt_critic_io import (  # type: ignore
    call_gpt_with_schema_or_fallback,
  )
  from client_intake_and_finmo.post_intake_solver.consultant_context_resolver import (  # type: ignore
    resolve_consultant_context,
  )

  applied: List[Dict[str, Any]] = []
  any_gpt_call_succeeded = False
  any_gpt_call_failed = False
  first_no_api_key = False

  for conflict in conflicts:
    lever_id = _clean_text(conflict.get("lever_id"))

    scoped_runtime = dict(runtime_objects or {})
    scoped_runtime["conflict"] = copy.deepcopy(conflict)
    drivers = envelope.get("drivers") if isinstance(envelope.get("drivers"), dict) else {}
    scoped_runtime["lever_entry"] = copy.deepcopy(drivers.get(lever_id) or {})

    resolver_context = resolve_consultant_context(
      contract_name=_CONFLICT_ADJUDICATION_CONTRACT_NAME,
      include_phase=_CONFLICT_ADJUDICATION_INCLUDE_PHASE,
      scope_key={"lever_id": lever_id},
      draft_id=draft_id,
      planning_run_id=planning_run_id,
      conn=conn,
      runtime_objects=scoped_runtime,
    )

    user_context = {
      "consultant": _CONFLICT_ADJUDICATION_CONSULTANT_NAME,
      "lever_id": lever_id,
      "value_kind": conflict.get("value_kind"),
      "metric_key": conflict.get("metric_key"),
      "intake_value": conflict.get("intake_value"),
      "intake_provenance": conflict.get("intake_provenance"),
      "calibrated_band": {
        "min_allowed": conflict.get("calibrated_min_allowed"),
        "max_allowed": conflict.get("calibrated_max_allowed"),
        "default_value": conflict.get("calibrated_default_value"),
      },
      "side": conflict.get("side"),
      "context": resolver_context,
    }
    call_result = call_gpt_with_schema_or_fallback(
      consultant_name=_CONFLICT_ADJUDICATION_CONSULTANT_NAME,
      system_prompt=_PER_CONFLICT_SYSTEM_PROMPT,
      user_context=user_context,
      response_schema=_PER_CONFLICT_RESPONSE_SCHEMA,
      schema_name=_CONFLICT_ADJUDICATION_CONSULTANT_NAME,
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

    decision_came_from_gpt = bool(parsed)
    if decision_came_from_gpt:
      decision_payload = {
        "lever_id": lever_id,
        "decision": parsed.get("decision"),
        "resolved_min_allowed": parsed.get("resolved_min_allowed"),
        "resolved_max_allowed": parsed.get("resolved_max_allowed"),
        "resolved_default_value": parsed.get("resolved_default_value"),
        "rationale": _clean_text(parsed.get("rationale")),
      }
    else:
      decision_payload = {
        "lever_id": lever_id,
        "decision": "keep_band",
        "resolved_min_allowed": None,
        "resolved_max_allowed": None,
        "resolved_default_value": None,
        "rationale": f"fallback_keep_band:{decision_source}",
      }
    envelope = _apply_decision(
      envelope_payload=envelope,
      conflict=conflict,
      decision=decision_payload,
      decision_came_from_gpt=decision_came_from_gpt,
    )
    applied.append({
      "lever_id": lever_id,
      "intake_value": conflict.get("intake_value"),
      "calibrated_band_before": {
        "min_allowed": conflict.get("calibrated_min_allowed"),
        "max_allowed": conflict.get("calibrated_max_allowed"),
        "default_value": conflict.get("calibrated_default_value"),
      },
      "decision": _clean_text(decision_payload.get("decision")),
      "rationale": _clean_text(decision_payload.get("rationale")),
      "decision_source": decision_source,
    })

  if any_gpt_call_succeeded:
    rolling_decision_source = "python_proposer_plus_gpt_critic"
  elif first_no_api_key:
    rolling_decision_source = "python_proposer_only_no_api_key"
  elif any_gpt_call_failed:
    rolling_decision_source = "python_proposer_only_critic_failure"
  else:
    rolling_decision_source = "no_conflicts_detected"

  envelope.setdefault("calibration", {})
  if isinstance(envelope.get("calibration"), dict):
    envelope["calibration"]["conflict_adjudication"] = {
      "consultant_name": _CONFLICT_ADJUDICATION_CONSULTANT_NAME,
      "decision_source": rolling_decision_source,
      "conflicts_detected": len(conflicts),
      "decisions_applied": applied,
      "scope": "per_conflict",
    }

  return {
    "calibrated_envelope": envelope,
    "decision_source": rolling_decision_source,
    "conflicts_detected": len(conflicts),
    "decisions_applied": applied,
    "raw_openai_response": {},
    "fallback_detail": "" if any_gpt_call_succeeded else rolling_decision_source,
  }
