"""set_payroll_schedule — author the payroll headcount schedule.

Wraps the existing Handler C builder + validator + per-class bounds
lookup. On acceptance the tool returns the validated, payload-shaped
schedule for the caller to write into plan_state['payroll'] and
refresh the mirror. On rejection it returns structured violations the
amalgamated session (step 5) or the deterministic floor will repair
and retry.

The Handler C GPT iteration loop is gone (deleted in this same
commit). The amalgamated session (step 5) calls this tool directly
with a contract payload. During the transition window between this
commit and step 5 the orchestrator's pre-amalgamation entry point
(``estimate_payroll_headcount_schedule_with_gpt``) is a thin shim
that returns a structurally-valid empty payload — payroll authoring
becomes a real GPT activity only once the amalgamated session lands.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Optional


def _string(value: Any) -> str:
  return str(value if value is not None else "").strip()


def _build_violations_from_runtime_error(exc: Exception) -> List[Dict[str, Any]]:
  return [{
    "code": "payroll_schedule_validator_rejected",
    "message": _string(exc)[:1200],
  }]


def _echo_bands_for_section(
  conn,
  *,
  draft_id: str,
  planning_run_id: str,
) -> Dict[str, Any]:
  """Echo Handler C's per-class payroll-percent-of-revenue bounds plus
  whatever payroll section bands the cohort_bands populator may have
  written. Step 3b populates only the per-class policy bounds; the
  cohort populator does not yet write payroll-specific bands (Handler
  C policy bounds, not cohort percentiles, govern this section).
  """
  bounds: Dict[str, Any] = {"by_class": {}, "tolerance": None}
  try:
    from client_intake_and_finmo.post_intake_headcount.lookup import (  # type: ignore
      headcount_payroll_revenue_sanity_bounds,
    )
    raw = headcount_payroll_revenue_sanity_bounds() or {}
    by_class = raw.get("by_class") if isinstance(raw, dict) else None
    if isinstance(by_class, dict):
      bounds["by_class"] = copy.deepcopy(by_class)
    if isinstance(raw, dict):
      bounds["tolerance"] = raw.get("tolerance_pct") or raw.get("relative_tolerance")
  except Exception:
    pass
  # Cohort-table payroll bands (currently empty in step 3b; will fill
  # when payroll section is wired into _SECTION_LEVERS in a later step).
  try:
    if conn is not None and draft_id and planning_run_id:
      from client_intake_and_finmo.post_intake_solver.cohort_bands_table import (  # type: ignore
        get_bands,
      )
      cohort = get_bands(conn, draft_id=draft_id, planning_run_id=planning_run_id, section="payroll")
      if cohort and (cohort.get("bands") or {}):
        bounds["cohort_bands"] = cohort.get("bands")
  except Exception:
    pass
  return bounds


def _check_band_violations(
  contract: Dict[str, Any],
  bands_echoed: Dict[str, Any],
) -> List[Dict[str, Any]]:
  """Verify the contract's target_payroll_percent_of_revenue is inside
  the policy bounds for its labor_intensity_class. Returns one
  violation entry if outside; empty list otherwise.
  """
  violations: List[Dict[str, Any]] = []
  if not isinstance(contract, dict) or not isinstance(bands_echoed, dict):
    return violations
  cls = str(contract.get("labor_intensity_class") or "").strip().lower()
  pct = contract.get("target_payroll_percent_of_revenue")
  if not cls or not isinstance(pct, (int, float)):
    return violations
  by_class = bands_echoed.get("by_class") or {}
  band = by_class.get(cls) if isinstance(by_class, dict) else None
  if not isinstance(band, dict):
    return violations
  bmin = band.get("min_pct") if band.get("min_pct") is not None else band.get("min")
  bmax = band.get("max_pct") if band.get("max_pct") is not None else band.get("max")
  if isinstance(bmin, (int, float)) and float(pct) < float(bmin):
    violations.append({
      "code": "payroll_target_below_class_min",
      "labor_intensity_class": cls,
      "actual": float(pct),
      "band_min": float(bmin),
      "delta": float(bmin) - float(pct),
      "units": "fraction",
    })
  if isinstance(bmax, (int, float)) and float(pct) > float(bmax):
    violations.append({
      "code": "payroll_target_above_class_max",
      "labor_intensity_class": cls,
      "actual": float(pct),
      "band_max": float(bmax),
      "delta": float(pct) - float(bmax),
      "units": "fraction",
    })
  return violations


def set_payroll_schedule(
  *,
  conn=None,
  draft_id: Optional[str] = None,
  planning_run_id: Optional[str] = None,
  contract: Optional[Dict[str, Any]] = None,
  # Builder inputs (used when caller wants the tool to compute the
  # built payload after validation):
  business_facts: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  people_json: Optional[Dict[str, Any]] = None,
  model_input_json: Optional[Dict[str, Any]] = None,
  policy_code: str = "default",
  # Test seams.
  _validator: Optional[Callable[..., Dict[str, Any]]] = None,
  _builder: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
  """Author / validate / commit the payroll headcount schedule.

  Returns the standard authoring-tool envelope::

    {
      "accepted": bool,
      "section": "payroll",
      "contract": <validated normalized contract>|None,
      "payload": <full headcount payload built from contract>|None,
      "violations": [ {...}, ... ],
      "bands_echoed": { "by_class": {...}, "tolerance": ..., "cohort_bands"?: {...} },
      "decision_source": "amalgamated_gpt_supplied" | "amalgamated_session_pending",
    }

  Rejection does NOT mutate state. On acceptance the caller writes
  the returned ``payload`` into plan_state['payroll'] and refreshes
  the mirror's bands echo with ``bands_echoed``.

  When ``contract`` is None the tool currently returns accepted=False
  with code ``payroll_contract_required`` and
  decision_source ``amalgamated_session_pending``. Handler C lacks a
  Python-deterministic contract builder (the prior GPT iteration loop
  was the author); step 5 wires the amalgamated session as the
  author. During the transition the orchestrator's
  ``estimate_payroll_headcount_schedule_with_gpt`` shim returns an
  empty structurally-valid payload directly so the pre-amalgamation
  pipeline continues to make progress.
  """
  validator = _validator
  builder = _builder
  if validator is None:
    from client_intake_and_finmo.post_intake_headcount.schedule import (  # type: ignore
      validate_payroll_headcount_contract_payload,
    )
    validator = validate_payroll_headcount_contract_payload
  if builder is None:
    from client_intake_and_finmo.post_intake_headcount.schedule import (  # type: ignore
      build_payroll_headcount_payload_from_contract,
    )
    builder = build_payroll_headcount_payload_from_contract

  bands_echoed = _echo_bands_for_section(
    conn, draft_id=_string(draft_id), planning_run_id=_string(planning_run_id)
  )

  if not isinstance(contract, dict) or not contract:
    return {
      "accepted": False,
      "section": "payroll",
      "contract": None,
      "payload": None,
      "violations": [{
        "code": "payroll_contract_required",
        "message": (
          "Handler C lacks a Python-deterministic contract builder; the "
          "amalgamated GPT session must supply the contract. The pre-"
          "amalgamation orchestrator uses a transitional empty-payload "
          "shim during step 3b -> step 5."
        ),
      }],
      "bands_echoed": bands_echoed,
      "decision_source": "amalgamated_session_pending",
    }

  candidate = copy.deepcopy(contract)

  # 1) Canonical contract validator (shape + horizon + per-row).
  validator_violations: List[Dict[str, Any]] = []
  normalized: Optional[Dict[str, Any]] = None
  try:
    normalized = validator(payload=candidate)
  except Exception as exc:
    validator_violations = _build_violations_from_runtime_error(exc)

  # 2) Band check (target_payroll_percent_of_revenue against class bounds).
  band_violations = _check_band_violations(candidate, bands_echoed) if not validator_violations else []

  violations = validator_violations + band_violations
  if violations or normalized is None:
    return {
      "accepted": False,
      "section": "payroll",
      "contract": None,
      "payload": None,
      "violations": violations,
      "bands_echoed": bands_echoed,
      "decision_source": "amalgamated_gpt_supplied",
    }

  # 3) Build full payload from the validated contract.
  try:
    payload = builder(
      payroll_headcount_contract=normalized,
      draft_id=_string(draft_id),
      client_id="",
      policy_code=policy_code,
      model_input_json=model_input_json,
      business_facts=business_facts,
      ops_json=ops_json,
      people_json=people_json,
    )
  except Exception as exc:
    return {
      "accepted": False,
      "section": "payroll",
      "contract": None,
      "payload": None,
      "violations": [{
        "code": "payroll_payload_build_failed",
        "message": _string(exc)[:1200],
      }],
      "bands_echoed": bands_echoed,
      "decision_source": "amalgamated_gpt_supplied",
    }

  return {
    "accepted": True,
    "section": "payroll",
    "contract": normalized,
    "payload": payload,
    "violations": [],
    "bands_echoed": bands_echoed,
    "decision_source": "amalgamated_gpt_supplied",
  }
