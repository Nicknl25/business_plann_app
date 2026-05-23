"""set_stage_ramp_contract — author the 20-quarter stage ramp grid.

Wraps the existing Python builder + robust-bound clip + canonical
validator (post_intake_contracts/runner.py). On acceptance the tool
returns the validated, provenance-annotated contract for the caller to
write into plan_state['stage_ramp'] and refresh the mirror. On
rejection it returns structured violations so GPT (step 5) or the
deterministic floor can repair and retry.

Two input modes:
  - ``contract=<full grid dict>``: GPT (or the floor) supplied an
    explicit contract; validate it and either accept or reject.
  - ``contract=None`` with builder inputs: the tool builds the Python
    deterministic contract itself, applies the robust-bound clip, and
    validates. This is the manager-only path that runs when no
    executive (GPT) has authored a contract yet — e.g. during the
    Phase 3 step 3a / step 5 transition window.

The H4 GPT iteration loop is gone (deleted in this same commit). The
amalgamated GPT session (step 5) calls this tool directly with a
contract payload; the deterministic floor calls it with
``contract=None`` and the same builder inputs.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Optional


def _string(value: Any) -> str:
  return str(value if value is not None else "").strip()


def _build_violations_from_runtime_error(exc: RuntimeError) -> List[Dict[str, Any]]:
  """The canonical validator raises RuntimeError with a structured
  message; surface it as a single violation entry. Future commits may
  enrich this by parsing the message into per-field entries.
  """
  return [{
    "code": "stage_ramp_validator_rejected",
    "message": _string(exc)[:1200],
  }]


def _echo_bands_for_run(conn, *, draft_id: str, planning_run_id: str) -> Dict[str, Any]:
  """Return the cohort bands stored for the stage_ramp section, in the
  tool-shaped form GPT expects (lever_id → band dict). Empty if no
  bands have been populated yet — caller can still proceed.
  """
  if conn is None or not draft_id or not planning_run_id:
    return {}
  try:
    from client_intake_and_finmo.post_intake_solver.cohort_bands_table import (  # type: ignore
      get_bands,
    )
    payload = get_bands(conn, draft_id=draft_id, planning_run_id=planning_run_id, section="stage_ramp")
    return payload.get("bands") or {}
  except Exception:
    return {}


def _check_band_violations(
  contract: Dict[str, Any],
  bands: Dict[str, Any],
) -> List[Dict[str, Any]]:
  """Cross-check each per-quarter contract value against the
  corresponding cohort/robust band. Cogs/marketing/rd/ga maxes that
  exceed the robust_max are flagged; ni_floor values below robust_min
  similarly. Returns one entry per (quarter, field) violation.
  """
  violations: List[Dict[str, Any]] = []
  if not isinstance(contract, dict) or not isinstance(bands, dict) or not bands:
    return violations
  grid = contract.get("quarter_ramp_grid") or []
  if not isinstance(grid, list):
    return violations
  # Map lever_id -> band dict; we expect "stage_ramp::<field>" lever ids
  # (populated by the cohort_bands populator in this commit's update).
  by_field: Dict[str, Dict[str, Any]] = {}
  for lever_id, band in bands.items():
    if not isinstance(lever_id, str):
      continue
    field = lever_id.split("::", 1)[1] if "::" in lever_id else lever_id
    by_field[field] = band if isinstance(band, dict) else {}
  for q_idx, row in enumerate(grid, start=1):
    if not isinstance(row, dict):
      continue
    for field, band in by_field.items():
      value = row.get(field)
      if not isinstance(value, (int, float)):
        continue
      r_min = band.get("robust_min")
      r_max = band.get("robust_max")
      if isinstance(r_max, (int, float)) and float(value) > float(r_max):
        violations.append({
          "code": "stage_ramp_above_band_max",
          "quarter_index": q_idx,
          "field": field,
          "actual": float(value),
          "band_max": float(r_max),
          "delta": float(value) - float(r_max),
          "units": "fraction",
        })
      if isinstance(r_min, (int, float)) and float(value) < float(r_min):
        violations.append({
          "code": "stage_ramp_below_band_min",
          "quarter_index": q_idx,
          "field": field,
          "actual": float(value),
          "band_min": float(r_min),
          "delta": float(r_min) - float(value),
          "units": "fraction",
        })
  return violations


def set_stage_ramp_contract(
  *,
  conn=None,
  draft_id: Optional[str] = None,
  planning_run_id: Optional[str] = None,
  contract: Optional[Dict[str, Any]] = None,
  # Builder inputs (used when contract is None — deterministic-floor path):
  business_facts: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  people_json: Optional[Dict[str, Any]] = None,
  planning_mode: str = "",
  planning_mode_reason: str = "",
  model_input_json: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
  r_and_d_applicability: Optional[Dict[str, Any]] = None,
  expected_stage_family: str = "",
  # Test seams — production callers pass None.
  _builder: Optional[Callable[..., Dict[str, Any]]] = None,
  _validator: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
  """Author / validate / commit the stage ramp contract.

  Returns the standard authoring-tool envelope::

    {
      "accepted": bool,
      "section": "stage_ramp",
      "contract": <validated contract>|None,  # only when accepted
      "violations": [ {...}, ... ],
      "bands_echoed": { lever_id: band_dict, ... },
      "decision_source": "amalgamated_gpt_supplied" | "python_deterministic_floor",
    }

  Rejection does NOT mutate state. On acceptance the caller writes the
  returned contract into plan_state['stage_ramp'] and refreshes the
  mirror's bands echo with bands_echoed.
  """
  builder = _builder
  validator = _validator
  if builder is None:
    from client_intake_and_finmo.post_intake_contracts.runner import (  # type: ignore
      build_python_stage_ramp_contract,
    )
    builder = build_python_stage_ramp_contract
  if validator is None:
    from client_intake_and_finmo.post_intake_contracts.runner import (  # type: ignore
      _validate_stage_ramp_contract_payload,
    )
    validator = _validate_stage_ramp_contract_payload

  bands_echoed = _echo_bands_for_run(conn, draft_id=_string(draft_id), planning_run_id=_string(planning_run_id))

  decision_source = "amalgamated_gpt_supplied"
  candidate: Optional[Dict[str, Any]] = copy.deepcopy(contract) if isinstance(contract, dict) else None

  if candidate is None:
    # Deterministic-floor path: build the Python contract and apply the
    # robust-bound clip so an out-of-the-box envelope is committable.
    decision_source = "python_deterministic_floor"
    built = builder(
      business_facts=business_facts or {},
      ops_json=ops_json or {},
      financials_json=financials_json or {},
      financials_year1_json=financials_year1_json or {},
      people_json=people_json or {},
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      model_input_json=model_input_json or {},
      finmo_json=finmo_json or {},
      r_and_d_applicability=r_and_d_applicability or {},
    )
    from client_intake_and_finmo.post_intake_contracts.runner import (  # type: ignore
      robust_bound_stage_ramp_contract,
    )
    candidate = robust_bound_stage_ramp_contract(copy.deepcopy(built))

  expected_family = _string(expected_stage_family) or _string(candidate.get("stage_family")) or "operational"
  business_stage = (
    _string((ops_json or {}).get("business_stage"))
    or _string((business_facts or {}).get("business_stage"))
    or expected_family
  )
  r_and_d_enabled = True
  if isinstance(r_and_d_applicability, dict) and isinstance(r_and_d_applicability.get("r_and_d_enabled"), bool):
    r_and_d_enabled = bool(r_and_d_applicability["r_and_d_enabled"])

  # 1) Cohort/robust band check (cross-section coherence with drivers).
  band_violations = _check_band_violations(candidate, bands_echoed)

  # 2) Canonical schema/structure validator.
  validator_violations: List[Dict[str, Any]] = []
  try:
    validator(
      payload=candidate,
      expected_stage_family=expected_family,
      business_stage=business_stage,
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      r_and_d_enabled=r_and_d_enabled,
    )
  except RuntimeError as exc:
    validator_violations = _build_violations_from_runtime_error(exc)

  violations = validator_violations + band_violations
  if violations:
    return {
      "accepted": False,
      "section": "stage_ramp",
      "contract": None,
      "violations": violations,
      "bands_echoed": bands_echoed,
      "decision_source": decision_source,
    }

  # Accepted. Annotate provenance fields the orchestrator already
  # consumes; the engage helper layers on the same fields today.
  accepted = copy.deepcopy(candidate)
  accepted.setdefault("decision_source", decision_source)
  accepted.setdefault("business_stage", business_stage)
  accepted.setdefault("planning_mode", _string(planning_mode).lower())
  accepted.setdefault("planning_mode_reason", _string(planning_mode_reason))
  accepted.setdefault("contract_version", "stage_ramp_contract_v2")
  return {
    "accepted": True,
    "section": "stage_ramp",
    "contract": accepted,
    "violations": [],
    "bands_echoed": bands_echoed,
    "decision_source": decision_source,
  }
