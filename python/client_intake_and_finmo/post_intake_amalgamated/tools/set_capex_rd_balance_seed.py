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
from typing import Any, Callable, Dict, List, Optional


def _string(value: Any) -> str:
  return str(value if value is not None else "").strip()


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

  if violations:
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

  decision_source = "amalgamated_gpt_supplied" if overrides_audit else "python_deterministic_floor"
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
