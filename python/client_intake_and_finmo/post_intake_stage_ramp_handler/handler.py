"""P3.33 Phase 3 step 3a — H4 stage-ramp handler shim.

Historical (pre-amalgamation): this module owned a GPT tool-calling
session that refined a Python-built stage_ramp_contract when the
canonical validator rejected the Python output. The session loop, the
in-handler machinery fail-fasts, the per-session prompts, and the
verified-commit-candidate model lived in
``tool_calling_session.py`` and the rest of this package.

Now (P3.33 Phase 3 step 3a): all of that is gone. Authoring authority
for the stage_ramp_contract belongs to the amalgamated GPT session
(forthcoming step 5) via the
``set_stage_ramp_contract`` tool
(``post_intake_amalgamated.tools.set_stage_ramp_contract``). The tool
is the single canonical entry point: it builds the Python contract
when no GPT-supplied contract is provided, applies the K13 robust-
bound clip, cross-checks every per-quarter value against the cohort
bands stored in ``post_intake_cohort_bands``, and validates with
``_validate_stage_ramp_contract_payload``.

This module retains only ONE export — ``engage_stage_ramp_handler_on_validator_failure``
— because ``api_handlers/intake_consult.py`` still wires it as the
orchestrator's stage_ramp authoring callable. It is now a thin shim
that delegates to ``set_stage_ramp_contract``. The orchestrator's
behavior is preserved: the Python builder is tried first; if its
output fails the validator, the deterministic-floor path commits a
robust-bound contract; if even that rejects, RuntimeError is raised.

When step 5 wires the amalgamated session into the orchestrator, this
shim will be removed entirely and the orchestrator will call
``set_stage_ramp_contract`` directly.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, Optional


def engage_stage_ramp_handler_on_validator_failure(
  *,
  build_python_contract: Callable[..., Dict[str, Any]],
  validator: Callable[..., Dict[str, Any]],
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  financials_year1_json: Optional[Dict[str, Any]],
  people_json: Optional[Dict[str, Any]] = None,
  planning_mode: str = "",
  planning_mode_reason: str = "",
  model_input_json: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
  r_and_d_applicability: Optional[Dict[str, Any]] = None,
  stage_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Orchestrator wiring entry point (preserved API).

  1. Build the Python deterministic contract via ``build_python_contract``.
  2. Try the canonical ``validator`` on it. If it passes, return the
     Python contract annotated with provenance — happy path, no GPT.
  3. If it rejects, call ``set_stage_ramp_contract`` with no GPT
     contract: the tool re-builds, applies the robust-bound clip, and
     re-validates. If the floor contract passes, return it. If it does
     not, raise RuntimeError with the validator's residual diagnostic
     (no silent ship — doctrine §1 / §10.2).
  """
  from client_intake_and_finmo.post_intake_amalgamated.tools import (  # type: ignore
    set_stage_ramp_contract,
  )

  python_contract = build_python_contract(
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
  expected_family = str(python_contract.get("stage_family") or "operational")
  business_stage = (
    str((ops_json or {}).get("business_stage") or "").strip().lower()
    or str((business_facts or {}).get("business_stage") or "").strip().lower()
    or expected_family
  )
  r_and_d_enabled = (
    bool(r_and_d_applicability.get("r_and_d_enabled"))
    if isinstance(r_and_d_applicability, dict)
    and isinstance(r_and_d_applicability.get("r_and_d_enabled"), bool)
    else True
  )

  def _annotate(contract: Dict[str, Any], *, decision_source: str) -> Dict[str, Any]:
    annotated = copy.deepcopy(contract)
    annotated["decision_source"] = decision_source
    annotated["business_stage"] = business_stage
    annotated["business_stage_source"] = (
      "ops.business_stage"
      if (ops_json or {}).get("business_stage")
      else "business_start_date_inferred"
    )
    annotated["planning_mode"] = str(planning_mode or "").strip().lower()
    annotated["planning_mode_reason"] = str(planning_mode_reason or "").strip()
    annotated["r_and_d_applicability"] = copy.deepcopy(r_and_d_applicability or {})
    annotated["contract_version"] = "stage_ramp_contract_v2"
    return annotated

  try:
    validator(
      payload=python_contract,
      expected_stage_family=expected_family,
      business_stage=business_stage,
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      r_and_d_enabled=r_and_d_enabled,
    )
    return _annotate(python_contract, decision_source="python_deterministic_builder")
  except RuntimeError as python_validator_exc:
    # Deterministic-floor path via the canonical tool.
    tool_result = set_stage_ramp_contract(
      contract=None,
      business_facts=business_facts,
      ops_json=ops_json,
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
      people_json=people_json,
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      model_input_json=model_input_json,
      finmo_json=finmo_json,
      r_and_d_applicability=r_and_d_applicability,
      expected_stage_family=expected_family,
      _builder=build_python_contract,
      _validator=validator,
    )
    if tool_result.get("accepted") and isinstance(tool_result.get("contract"), dict):
      annotated = _annotate(tool_result["contract"], decision_source="python_deterministic_floor")
      annotated["python_proposal_diagnostic"] = {
        "validator_error_text": str(python_validator_exc),
        "floor_committed": True,
        "tool_violations": tool_result.get("violations") or [],
      }
      return annotated
    # Floor itself rejected — surface the diagnostic.
    floor_violations = tool_result.get("violations") or []
    raise RuntimeError(
      f"stage_ramp_floor_rejected_after_python_builder_rejected: "
      f"python_validator={str(python_validator_exc)[:300]} "
      f"floor_violations={floor_violations[:3]}"
    ) from python_validator_exc
