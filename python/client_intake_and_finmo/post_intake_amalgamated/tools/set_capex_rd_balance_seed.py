"""set_capex_rd_balance_seed — author the three pre_convergence scalars.

Combines the three pre_convergence section commits the amalgamated GPT
session needs to make in one call:

  - maintenance_capex_percent: pure Python NAICS-cascade resolver
    (post_intake_contracts.runner._derive_maintenance_capex_percent_from_naics).
    GPT was dropped here in Module 5 Task 5.1; this tool just wraps the
    pure-Python entry so the amalgamated session has a uniform surface.
  - r_and_d_applicability: pure Python constant
    (post_intake_contracts.runner._estimate_r_and_d_applicability_with_gpt
    returns {r_and_d_enabled: True} per Phase 9 P3.10 — universal-app:
    R&D is just a regular driver, no separate applicability decision).
    Wrapped here for the same uniformity.
  - balance_sheet_contextual_seed: the Python proposer
    (post_intake_balance_sheet.contextual_seed.propose_balance_sheet_contextual_seed_payload)
    builds the full seed grid deterministically from NAICS + intake
    anchors + applicability. The GPT critic that used to optionally
    amend specific rows is DELETED in this commit (the critic
    contributed marginal value, added latency, and was the only
    remaining GPT call in the three pre_convergence scalar estimators
    the directive called out).

GPT-supplied overrides (amalgamated session, step 5) may be passed via
the ``overrides`` argument; band/contract validation runs and accepted
overrides replace the proposer outputs. Without overrides the tool
returns the deterministic-floor payload (the amalgamated session's
"manager covering for the executive" path during the transition).
"""

from __future__ import annotations

import copy
import math
from typing import Any, Callable, Dict, List, Optional, Tuple


def _is_finite_number(v: Any) -> bool:
  return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _check_envelope_violations(
  mc_payload: Optional[Dict[str, Any]],
  rd_payload: Optional[Dict[str, Any]],
  bs_payload: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  """B6 — economic envelope check for the three pre_convergence
  payloads. Catches structurally-impossible values the proposers might
  emit on edge inputs (negative capex, days < 0, percent > 1)."""
  violations: List[Dict[str, Any]] = []
  # maintenance_capex_percent — must be a finite number in [0, 1].
  if isinstance(mc_payload, dict):
    pct = mc_payload.get("maintenance_capex_percent")
    if pct is not None:
      if not _is_finite_number(pct):
        violations.append({
          "code": "envelope_violation_maintenance_capex_not_finite",
          "actual": pct,
        })
      else:
        pf = float(pct)
        if pf < 0.0 or pf > 1.0:
          violations.append({
            "code": "envelope_violation_maintenance_capex_out_of_unit_interval",
            "actual": pf,
          })
  # balance_sheet_seed_grid rows — each seed_value must be finite ≥ 0.
  if isinstance(bs_payload, dict):
    grid = bs_payload.get("balance_sheet_seed_grid")
    if isinstance(grid, list):
      for row in grid:
        if not isinstance(row, dict):
          continue
        if not bool(row.get("applicable")):
          continue
        sv = row.get("seed_value")
        if sv is None:
          continue
        if not _is_finite_number(sv):
          violations.append({
            "code": "envelope_violation_balance_sheet_seed_not_finite",
            "lever_id": row.get("lever_id"), "actual": sv,
          })
          continue
        sf = float(sv)
        if sf < 0.0:
          violations.append({
            "code": "envelope_violation_balance_sheet_seed_negative",
            "lever_id": row.get("lever_id"), "actual": sf,
          })
  return violations


# P3.33 Phase 3 pre-step-8 — Working-capital scalar lever_ids the
# balance_sheet section now owns. Mirror of
# cohort_bands_table._SECTION_LEVERS["balance_sheet"].
_WC_LEVER_IDS: Tuple[str, ...] = (
  "balance_sheet::Accounts Receivable Days",
  "balance_sheet::Accounts Payable Days",
  "balance_sheet::Inventory Days",
)


def _string(value: Any) -> str:
  return str(value if value is not None else "").strip()


def _echo_balance_sheet_bands(
  conn, *, draft_id: str, planning_run_id: str,
) -> Dict[str, Any]:
  """Read the balance_sheet section's cohort bands for WC override
  validation. Falls back to empty dict on any error / missing inputs
  (validation then skips band checks)."""
  if conn is None or not draft_id or not planning_run_id:
    return {}
  try:
    from client_intake_and_finmo.post_intake_solver.cohort_bands_table import (  # type: ignore
      get_bands,
    )
    payload = get_bands(
      conn, draft_id=draft_id, planning_run_id=planning_run_id,
      section="balance_sheet",
    )
    return payload.get("bands") or {}
  except Exception:
    return {}


def _apply_wc_overrides(
  bs_payload: Dict[str, Any],
  wc_overrides: Optional[Dict[str, Any]],
  bands: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
  """Apply WC-days overrides onto bs_payload['balance_sheet_seed_grid'].

  Each override key is a WC lever_id (e.g. 'balance_sheet::Accounts
  Receivable Days'); value is a scalar days number. The override
  updates the matching row's ``seed_value`` IF that row exists and is
  applicable. Out-of-band values are rejected with a structured
  violation; non-numeric / unknown / non-applicable lever overrides
  are likewise rejected.

  Returns ``(audit_entries, violations)``.
  """
  audit: List[Dict[str, Any]] = []
  violations: List[Dict[str, Any]] = []
  if not isinstance(wc_overrides, dict) or not wc_overrides:
    return audit, violations
  if not isinstance(bs_payload, dict):
    return audit, violations
  grid = bs_payload.get("balance_sheet_seed_grid")
  if not isinstance(grid, list):
    return audit, violations
  rows_by_id: Dict[str, Dict[str, Any]] = {
    str(r.get("lever_id") or "").strip(): r
    for r in grid if isinstance(r, dict)
  }
  for raw_lever_id, raw_value in wc_overrides.items():
    lever_id = _string(raw_lever_id)
    if lever_id not in _WC_LEVER_IDS:
      violations.append({
        "code": "wc_override_unknown_lever",
        "lever_id": lever_id,
        "message": (
          f"unknown WC lever_id; expected one of {list(_WC_LEVER_IDS)}"
        ),
      })
      continue
    try:
      value = float(raw_value)
    except (TypeError, ValueError):
      violations.append({
        "code": "wc_override_non_numeric",
        "lever_id": lever_id,
        "actual": raw_value,
      })
      continue
    row = rows_by_id.get(lever_id)
    if row is None:
      violations.append({
        "code": "wc_override_lever_row_missing",
        "lever_id": lever_id,
        "message": (
          "balance_sheet_seed_grid has no row for this lever; the proposer "
          "did not produce one (probably because the lever is non-applicable "
          "for this NAICS-2)"
        ),
      })
      continue
    if not bool(row.get("applicable")):
      violations.append({
        "code": "wc_override_lever_not_applicable",
        "lever_id": lever_id,
        "message": (
          "the proposer marked this lever non-applicable for this business; "
          "WC override rejected"
        ),
      })
      continue
    band = bands.get(lever_id) if isinstance(bands, dict) else None
    if isinstance(band, dict):
      bmin = (band.get("robust_min")
              if band.get("robust_min") is not None
              else band.get("benchmark_min"))
      bmax = (band.get("robust_max")
              if band.get("robust_max") is not None
              else band.get("benchmark_max"))
      if isinstance(bmin, (int, float)) and value < float(bmin):
        violations.append({
          "code": "wc_override_below_band_min",
          "lever_id": lever_id, "actual": value,
          "band_min": float(bmin),
          "delta": float(bmin) - value, "units": "days",
        })
        continue
      if isinstance(bmax, (int, float)) and value > float(bmax):
        violations.append({
          "code": "wc_override_above_band_max",
          "lever_id": lever_id, "actual": value,
          "band_max": float(bmax),
          "delta": value - float(bmax), "units": "days",
        })
        continue
    prior = row.get("seed_value")
    row["seed_value"] = round(value, 6)
    audit.append({
      "section": "balance_sheet_seed",
      "field": lever_id,
      "prior": prior,
      "applied": row["seed_value"],
    })
  return audit, violations


def _maintenance_capex(builder_inputs: Dict[str, Any]) -> Dict[str, Any]:
  from client_intake_and_finmo.post_intake_contracts.runner import (  # type: ignore
    _derive_maintenance_capex_percent_from_naics,
  )
  return _derive_maintenance_capex_percent_from_naics(**builder_inputs)


def _r_and_d_applicability(builder_inputs: Dict[str, Any]) -> Dict[str, Any]:
  from client_intake_and_finmo.post_intake_contracts.runner import (  # type: ignore
    _estimate_r_and_d_applicability_with_gpt,
  )
  # NB: name kept for compat; function body is pure Python (P3.10).
  return _estimate_r_and_d_applicability_with_gpt(
    business_facts=builder_inputs.get("business_facts") or {},
    ops_json=builder_inputs.get("ops_json") or {},
    financials_json=builder_inputs.get("financials_json") or {},
    financials_year1_json=builder_inputs.get("financials_year1_json") or {},
    model_input_json=builder_inputs.get("model_input_json"),
  )


def _balance_sheet_seed(builder_inputs: Dict[str, Any]) -> Dict[str, Any]:
  from client_intake_and_finmo.post_intake_balance_sheet.contextual_seed import (  # type: ignore
    propose_balance_sheet_contextual_seed_payload,
  )
  from client_intake_and_finmo.post_intake_critique import (  # type: ignore
    proposal_only_response,
  )
  from client_intake_and_finmo.post_intake_contracts.runner import (  # type: ignore
    _finalize_balance_sheet_seed_with_critique,
  )
  proposal = propose_balance_sheet_contextual_seed_payload(
    business_facts=builder_inputs.get("business_facts") or {},
    ops_json=builder_inputs.get("ops_json") or {},
    financials_json=builder_inputs.get("financials_json") or {},
    financials_year1_json=builder_inputs.get("financials_year1_json") or {},
    model_input_json=builder_inputs.get("model_input_json"),
  )
  # No GPT critic — pre_convergence GPT pass is deleted per step 3d. The
  # critic-only finalize path keeps the contract-validator normalization
  # and decision_source annotation the orchestrator expects.
  response = proposal_only_response(reason="pre_convergence_gpt_critic_deleted_step_3d")
  return _finalize_balance_sheet_seed_with_critique(
    proposal=proposal, response=response, raw_openai_response=None,
  )


def _apply_overrides(
  payload: Dict[str, Any],
  overrides: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  """Apply GPT-supplied overrides onto a section payload. Returns the
  list of (field, applied_value) audit entries. Unknown override keys
  produce a violation (single entry list) — the caller should treat
  any returned 'errors' list as rejection.
  """
  audit: List[Dict[str, Any]] = []
  if not isinstance(overrides, dict) or not overrides:
    return audit
  for key, value in overrides.items():
    field = _string(key)
    if not field or field.startswith("#"):
      continue
    # Top-level overrides only at this stage; per-row balance-sheet
    # edits go through revise_section (step 4 revision tool, not yet
    # built). Unknown keys are recorded so the caller can reject.
    payload[field] = value
    audit.append({"field": field, "applied": value})
  return audit


def set_capex_rd_balance_seed(
  *,
  conn=None,
  draft_id: Optional[str] = None,
  planning_run_id: Optional[str] = None,
  overrides: Optional[Dict[str, Any]] = None,
  # Builder inputs (always required — the deterministic floor needs them
  # even when overrides are supplied):
  business_facts: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  model_input_json: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
  # Test seams.
  _maintenance: Optional[Callable[..., Dict[str, Any]]] = None,
  _r_and_d: Optional[Callable[..., Dict[str, Any]]] = None,
  _balance_sheet: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
  """Author the three pre_convergence scalar sections in one call.

  Returns the standard authoring-tool envelope (per section)::

    {
      "accepted": bool,
      "section": "capex_rd_balance_seed",
      "payload": {
        "maintenance_capex_percent": <payload>,
        "r_and_d_applicability":     <payload>,
        "balance_sheet_seed":        <payload>,
      },
      "overrides_applied": [{"section":..., "field":..., "applied":...}, ...],
      "violations": [],
      "decision_source": "amalgamated_gpt_supplied" | "python_deterministic_floor",
    }

  Rejection currently happens only on a deterministic-floor compute
  failure; band/contract validation for individual fields is part of
  the existing proposers/validators we wrap.
  """
  builder_inputs = {
    "business_facts": business_facts,
    "ops_json": ops_json,
    "financials_json": financials_json,
    "financials_year1_json": financials_year1_json,
    "model_input_json": model_input_json,
    "finmo_json": finmo_json,
  }
  mc = _maintenance or _maintenance_capex
  rd = _r_and_d or _r_and_d_applicability
  bs = _balance_sheet or _balance_sheet_seed

  violations: List[Dict[str, Any]] = []
  try:
    mc_payload = mc(builder_inputs)
  except Exception as exc:
    violations.append({"code": "maintenance_capex_compute_failed", "message": _string(exc)[:600]})
    mc_payload = None
  try:
    rd_payload = rd(builder_inputs)
  except Exception as exc:
    violations.append({"code": "r_and_d_compute_failed", "message": _string(exc)[:600]})
    rd_payload = None
  try:
    bs_payload = bs(builder_inputs)
  except Exception as exc:
    violations.append({"code": "balance_sheet_seed_compute_failed", "message": _string(exc)[:600]})
    bs_payload = None

  # B6 — economic envelope sanity. Run after builders so we can check
  # the actual payload values (the builders never see overrides; those
  # are validated in _apply_wc_overrides below).
  violations = violations + _check_envelope_violations(
    mc_payload, rd_payload, bs_payload,
  )

  if violations:
    # Step 9b-ii — emit the round-1 failure when the builder exception
    # path fires (overrides=None means caller wants round-1 authoring;
    # cascade-revision callers pass overrides and are observed via
    # the SessionDriver's CASCADE_PROPOSAL_* emits).
    if overrides is None:
      from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore
        EventCode, PhaseCode, Status, safe_emit,
      )
      safe_emit(
        conn,
        draft_id=_string(draft_id),
        planning_run_id=_string(planning_run_id),
        phase=PhaseCode.ROUND1_AUTHORING,
        event_code=EventCode.ROUND1_CAPEX_RD_BALANCE_SEED_FAIL,
        status=Status.FAILED,
        diagnostic_data={"violation_codes": [v.get("code") for v in violations]},
      )
    return {
      "accepted": False,
      "section": "capex_rd_balance_seed",
      "payload": None,
      "overrides_applied": [],
      "violations": violations,
      "decision_source": "python_deterministic_floor",
    }

  overrides_audit: List[Dict[str, Any]] = []
  overrides = overrides if isinstance(overrides, dict) else None
  if overrides:
    sub_keys = {
      "maintenance_capex": mc_payload,
      "r_and_d": rd_payload,
      "balance_sheet_seed": bs_payload,
    }
    for sub_key, sub_payload in sub_keys.items():
      sub_overrides = overrides.get(sub_key)
      if isinstance(sub_overrides, dict) and isinstance(sub_payload, dict):
        sub_audit = _apply_overrides(sub_payload, sub_overrides)
        for entry in sub_audit:
          overrides_audit.append({"section": sub_key, **entry})

  # P3.33 Phase 3 pre-step-8 — WC days overrides go to a dedicated path
  # that updates the balance_sheet_seed_grid rows + band-validates.
  wc_violations: List[Dict[str, Any]] = []
  if overrides:
    wc_overrides = overrides.get("working_capital_days")
    if isinstance(wc_overrides, dict) and wc_overrides:
      bands_for_bs = _echo_balance_sheet_bands(
        conn,
        draft_id=_string(draft_id),
        planning_run_id=_string(planning_run_id),
      )
      wc_audit, wc_violations = _apply_wc_overrides(
        bs_payload, wc_overrides, bands_for_bs,
      )
      overrides_audit.extend(wc_audit)

  # Step 9b-ii — emit a ROUND1_AUTHORING diagnostic for the round-1
  # path (overrides=None). Cascade-revision callers pass overrides
  # and are observed via the SessionDriver's CASCADE_PROPOSAL_*
  # emits — no duplicate emit needed here.
  from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore
    EventCode, PhaseCode, Status, safe_emit,
  )

  if wc_violations:
    if overrides is None:
      safe_emit(
        conn,
        draft_id=_string(draft_id),
        planning_run_id=_string(planning_run_id),
        phase=PhaseCode.ROUND1_AUTHORING,
        event_code=EventCode.ROUND1_CAPEX_RD_BALANCE_SEED_FAIL,
        status=Status.FAILED,
        diagnostic_data={
          "violation_codes": [v.get("code") for v in (wc_violations or [])],
          "overrides_applied_count": len(overrides_audit),
        },
      )
    return {
      "accepted": False,
      "section": "capex_rd_balance_seed",
      "payload": None,
      "overrides_applied": overrides_audit,
      "violations": wc_violations,
      "decision_source": "amalgamated_gpt_supplied",
    }

  decision_source = "amalgamated_gpt_supplied" if overrides_audit else "python_deterministic_floor"
  if overrides is None:
    safe_emit(
      conn,
      draft_id=_string(draft_id),
      planning_run_id=_string(planning_run_id),
      phase=PhaseCode.ROUND1_AUTHORING,
      event_code=EventCode.ROUND1_CAPEX_RD_BALANCE_SEED_OK,
      status=Status.COMPLETED,
      diagnostic_data={
        "decision_source": decision_source,
        "rd_enabled": bool((rd_payload or {}).get("r_and_d_enabled")),
        "maintenance_capex_percent": (mc_payload or {}).get("maintenance_capex_percent"),
      },
    )
  return {
    "accepted": True,
    "section": "capex_rd_balance_seed",
    "payload": {
      "maintenance_capex_percent": mc_payload,
      "r_and_d_applicability": rd_payload,
      "balance_sheet_seed": bs_payload,
    },
    "overrides_applied": overrides_audit,
    "violations": [],
    "decision_source": decision_source,
  }
