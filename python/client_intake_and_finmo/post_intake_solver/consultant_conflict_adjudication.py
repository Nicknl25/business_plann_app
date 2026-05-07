"""Phase 3 — Intake-vs-band conflict adjudication consultant.

After the band-shaping consultant calibrates the driver envelope, some
intake-implied driver values may fall outside the calibrated band — for
example, intake says R&D is 3% of revenue but the calibrated band for
this business is 8-18%. Per the directive, the assembler does not
silently override either way. Instead, this consultant is invoked once
per detected conflict with (driver, intake_value, calibrated_band,
business_context) and asks GPT for one of three decisions:

  - keep_intake: widen the band so it includes the intake value. The
    intake-implied value flows through Q0 (always preserved) AND becomes
    the Q1+ trajectory anchor; the band is widened to accommodate it.
  - keep_band: override the intake value. Q0 stays at intake (Phase 1's
    invariant — Stub 0 is intake), but Q1+ uses the band's default_value
    and the band stays unchanged.
  - split: explicit Q0/Q1+ split. Q0 stays at intake; Q1+ uses the band
    unchanged. (This is the same outcome as keep_band but recorded with
    a different rationale: GPT believes the intake value reflects
    historical reality that should not propagate into the forecast.)

Stub 0 is never written by the solver (Phase 1 invariant). The
distinction between keep_band and split is provenance: keep_band means
GPT thinks the intake value is implausible even at Q0 (still recorded
but flagged); split means GPT thinks the intake value is plausible at
Q0 but should not propagate.

Conflicts are detected for the levers that have a clear intake-implied
value:
  - balance_sheet::Accounts Receivable Days     (ar_balance / quarter_revenue * 90)
  - balance_sheet::Accounts Payable Days         (ap_balance / quarter_revenue * 90)
  - balance_sheet::Inventory Days                (inventory_balance / quarter_revenue * 90)
  - expenses::Cost of Goods Sold                 (cogs_year_one / revenue_year_one)
  - expenses::Marketing                          (marketing_percent_of_revenue from intake)
  - expenses::Research & Development             (r_and_d_percent from intake)
  - expenses::Taxes                              (taxes_percent from intake)

For levers without a clear intake value, no conflict is even possible
(the band default stands by construction).
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple


_CONFLICT_ADJUDICATION_CONSULTANT_NAME = "solver_intake_band_conflict"
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


_CONFLICT_ADJUDICATION_RESPONSE_SCHEMA: Dict[str, Any] = {
  "type": "object",
  "additionalProperties": False,
  "properties": {
    "decisions": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
          "lever_id": {"type": "string"},
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
          "lever_id", "decision", "resolved_min_allowed",
          "resolved_max_allowed", "resolved_default_value", "rationale",
        ],
      },
    },
    "summary": {"type": "string"},
  },
  "required": ["decisions", "summary"],
}


_CONFLICT_ADJUDICATION_SYSTEM_PROMPT = (
  "You are adjudicating conflicts between intake-implied driver values "
  "and calibrated driver bands for a post-intake target-seeking solver. "
  "Each conflict represents a driver where the value implied by what "
  "the client provided at intake (e.g., AR balance / revenue * 90 = "
  "implied AR days) sits outside the band that band-shaping calibration "
  "produced for this business.\n\n"
  "For each conflict, decide one of three resolutions:\n"
  "  - keep_intake: the intake value is correct for this business; "
  "    widen the band to include it (return resolved_min_allowed / "
  "    resolved_max_allowed that span both the original band and the "
  "    intake value, plus a resolved_default_value at the intake value).\n"
  "  - keep_band: the intake value is implausible (likely a data-entry "
  "    error or a pre-restructure artifact); keep the band unchanged "
  "    (return the original min/max/default unchanged).\n"
  "  - split: the intake value is plausible historically but should not "
  "    propagate to the forecast (e.g., a turnaround business where "
  "    historical operations are not the future operations); keep the "
  "    band unchanged for Q1+ (return the original min/max/default "
  "    unchanged). Stub 0 (Q0) is intake-as-stated and is preserved by "
  "    the solver invariants regardless of your decision.\n\n"
  "Operating rules:\n"
  "1. Output exactly one decision per input conflict. Do NOT add or "
  "drop conflicts.\n"
  "2. resolved_min_allowed <= resolved_default_value <= resolved_max_allowed.\n"
  "3. For decision=keep_band or decision=split, return the original "
  "band's min/max/default unchanged (you may pass null and Python will "
  "preserve the originals).\n"
  "4. For decision=keep_intake, the resolved band must include the "
  "intake value: resolved_min_allowed <= intake_value <= "
  "resolved_max_allowed.\n"
  "5. Default to keep_band when the intake value is plausibly a data "
  "error or the business has clearly changed since the intake snapshot. "
  "Default to keep_intake only when the intake value is well-attested "
  "and characteristic of the business as it will operate going forward."
)


# Per-lever intake-implied value extractors. Each returns a tuple of
# (intake_value, intake_value_provenance) or None when the intake doesn't
# supply enough to compute the value.
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
      continue  # in-band; no conflict
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
    # Widen the band to include the intake value. Use GPT's resolved
    # band when valid; otherwise widen symmetrically by the gap.
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
    if resolved_default < resolved_min:
      resolved_default = resolved_min
    if resolved_default > resolved_max:
      resolved_default = resolved_max
    next_entry["min_allowed"] = round(float(resolved_min), 6)
    next_entry["max_allowed"] = round(float(resolved_max), 6)
    next_entry["default_value"] = round(float(resolved_default), 6)
  # For keep_band and split: the band stays unchanged; only provenance changes.

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
  business_context: Optional[Dict[str, Any]] = None,
  timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
  """Detect intake-vs-band conflicts and adjudicate via GPT.

  Returns:
    {
      "calibrated_envelope": <envelope after applied decisions>,
      "decision_source": str,
      "conflicts_detected": int,
      "decisions_applied": [...],
      "raw_openai_response": dict,
      "fallback_detail": str,
    }

  When no conflicts are detected, GPT is not called. When the GPT call
  fails or returns an unparseable payload, every detected conflict
  defaults to `keep_band` (the conservative-by-default policy: trust
  the calibrated band over a single intake data point) and provenance
  records the fallback.
  """
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
  user_context = {
    "consultant": _CONFLICT_ADJUDICATION_CONSULTANT_NAME,
    "naics_6": envelope.get("naics_6"),
    "business_context": business_context or {},
    "conflicts": conflicts,
  }
  call_result = call_gpt_with_schema_or_fallback(
    consultant_name=_CONFLICT_ADJUDICATION_CONSULTANT_NAME,
    system_prompt=_CONFLICT_ADJUDICATION_SYSTEM_PROMPT,
    user_context=user_context,
    response_schema=_CONFLICT_ADJUDICATION_RESPONSE_SCHEMA,
    schema_name=_CONFLICT_ADJUDICATION_CONSULTANT_NAME,
    timeout_seconds=timeout_seconds,
  )
  decision_source = call_result.get("decision_source") or "python_proposer_only_unknown"
  parsed = call_result.get("parsed") if isinstance(call_result.get("parsed"), dict) else None

  decisions_by_lever: Dict[str, Dict[str, Any]] = {}
  if parsed:
    for item in (parsed.get("decisions") or []):
      if not isinstance(item, dict):
        continue
      lever_id = _clean_text(item.get("lever_id"))
      decisions_by_lever[lever_id] = item

  applied: List[Dict[str, Any]] = []
  for conflict in conflicts:
    lever_id = _clean_text(conflict.get("lever_id"))
    gpt_decision = decisions_by_lever.get(lever_id)
    decision_came_from_gpt = isinstance(gpt_decision, dict)
    if decision_came_from_gpt:
      decision_payload = gpt_decision
    else:
      # No GPT decision for this lever (or GPT call failed). Conservative
      # default: keep_band.
      decision_payload = {
        "lever_id": lever_id,
        "decision": "keep_band",
        "resolved_min_allowed": conflict.get("calibrated_min_allowed"),
        "resolved_max_allowed": conflict.get("calibrated_max_allowed"),
        "resolved_default_value": conflict.get("calibrated_default_value"),
        "rationale": (
          "fallback_keep_band_conservative_default"
          if decision_source == "python_proposer_plus_gpt_critic"
          else f"fallback_keep_band:{decision_source}"
        ),
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
    })

  envelope.setdefault("calibration", {})
  if isinstance(envelope.get("calibration"), dict):
    envelope["calibration"]["conflict_adjudication"] = {
      "consultant_name": _CONFLICT_ADJUDICATION_CONSULTANT_NAME,
      "decision_source": decision_source,
      "conflicts_detected": len(conflicts),
      "decisions_applied": applied,
      "summary": _clean_text((parsed or {}).get("summary")),
      "fallback_detail": call_result.get("detail"),
    }

  return {
    "calibrated_envelope": envelope,
    "decision_source": decision_source,
    "conflicts_detected": len(conflicts),
    "decisions_applied": applied,
    "raw_openai_response": call_result.get("raw_openai_response") or {},
    "fallback_detail": call_result.get("detail") or "",
  }
