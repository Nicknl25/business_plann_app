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
import math
from typing import Any, Callable, Dict, List, Optional


def _string(value: Any) -> str:
  return str(value if value is not None else "").strip()


def _is_finite_number(v: Any) -> bool:
  return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _check_envelope_violations(contract: Dict[str, Any]) -> List[Dict[str, Any]]:
  """B6 — economic envelope check for payroll contracts. Catches
  malformations the per-class band check misses:
  target_payroll_percent_of_revenue outside [0, 1].

  P3.41 audit F-C2: the original implementation also had role/wage and
  schedule sub-blocks that read fields no producer emits anywhere in
  python/client_intake_and_finmo/ (`roles`/`role_specs`/`headcount`/
  `fte_count`/`wage_per_employee`/`wage`/`schedule`/`quarter_schedule`/
  `total`/`total_headcount`/`total_payroll_dollars` -- all zero
  producer occurrences). Both sub-blocks were dead-on-arrival. Deleted;
  the canonical validator at validate_payroll_headcount_contract_payload
  still enforces structural correctness on the real producer shape
  (payroll_headcount_grid + starting_fte/ending_fte/hires). Adding new
  per-row invariants on the real grid is a separate design task --
  out of scope for the audit batch.
  """
  violations: List[Dict[str, Any]] = []
  if not isinstance(contract, dict):
    return violations
  # target_payroll_percent_of_revenue, when supplied, must be in [0, 1].
  tppor = contract.get("target_payroll_percent_of_revenue")
  if tppor is not None:
    if not _is_finite_number(tppor):
      violations.append({
        "code": "envelope_violation_payroll_target_not_finite",
        "actual": tppor,
      })
    else:
      tppor_f = float(tppor)
      if tppor_f < 0.0 or tppor_f > 1.0:
        violations.append({
          "code": "envelope_violation_payroll_target_out_of_unit_interval",
          "actual": tppor_f,
        })
  return violations


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
  # built payload after validation, or when contract=None and the
  # tool must invoke Handler C internally to author from scratch):
  business_facts: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  people_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  model_input_json: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
  stage_ramp_contract: Optional[Dict[str, Any]] = None,
  planning_mode: str = "",
  planning_mode_reason: str = "",
  policy_code: str = "default",
  # Test seams.
  _validator: Optional[Callable[..., Dict[str, Any]]] = None,
  _builder: Optional[Callable[..., Dict[str, Any]]] = None,
  _handler_c_author: Optional[Callable[..., Dict[str, Any]]] = None,
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
      "decision_source": "amalgamated_gpt_supplied" | "handler_c_internal_authoring",
    }

  Rejection does NOT mutate state. On acceptance the caller writes
  the returned ``payload`` into plan_state['payroll'] and refreshes
  the mirror's bands echo with ``bands_echoed``.

  Round-1 authoring (P3.33 Phase 3 step 8b-fix): when ``contract`` is
  None, the tool internally invokes Handler C
  (``estimate_payroll_headcount_schedule_with_gpt``) to author the
  contract, then validates + builds the payload. This makes
  set_payroll_schedule the orchestrator-side entry point for
  round-1 payroll authoring — replacing the legacy
  _execute_sequence_step("payroll_headcount_schedule", ...) call
  pattern. The internal Handler C invocation can be replaced via the
  ``_handler_c_author`` test seam.
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

  decision_source = "amalgamated_gpt_supplied"
  candidate: Optional[Dict[str, Any]] = (
    copy.deepcopy(contract) if isinstance(contract, dict) and contract else None
  )
  # Labor-scaling enforcement context (round-1 authoring path only): the anchor
  # (revenue-scaled payroll target) + the executive's labor-model judgment.
  _anchor_for_enforcement: Optional[Dict[str, Any]] = None
  _labor_scaling_judgment: Optional[bool] = None
  _labor_scaling_rationale: Optional[str] = None

  if candidate is None:
    # Round-1 authoring path (Lineage B): the EXECUTIVE (GPT) authors the
    # payroll_headcount_schedule, GROUNDED by the revenue-driven anchor
    # (Python's grounding role) and VALIDATED by the canonical validator
    # below (Python's validation role). On a validation failure the
    # executive RE-AUTHORS with the validator's structured feedback
    # (bounded retries). The deterministic producer
    # (author_round1_payroll_contract) is the NO-EXECUTIVE fallback only
    # (no OPENAI_API_KEY / hermetic tests). Authority:
    # docs/architecture/gpt_authors_payroll_anchored_scope.md.
    #
    # The ``_handler_c_author`` test seam remains supported -- when a test
    # passes a custom callable, we invoke it (the legacy interface).
    handler_c = _handler_c_author
    _max_gpt_author_attempts = 4

    from client_intake_and_finmo.post_intake_headcount.schedule import (  # type: ignore
      author_round1_payroll_contract,
      compute_round1_payroll_anchor,
    )

    def _deterministic_fallback() -> Optional[Dict[str, Any]]:
      authored_local = author_round1_payroll_contract(
        business_facts=business_facts or {},
        ops_json=ops_json or {},
        people_json=people_json or {},
        financials_json=financials_json or {},
        financials_year1_json=financials_year1_json or {},
        model_input_json=model_input_json or {},
        finmo_json=finmo_json or {},
        stage_ramp_contract=stage_ramp_contract or {},
        policy_code=policy_code,
      )
      if isinstance(authored_local, dict):
        raw = (
          authored_local.get("payroll_headcount_contract")
          if isinstance(authored_local.get("payroll_headcount_contract"), dict)
          else authored_local
        )
        if isinstance(raw, dict) and raw:
          return copy.deepcopy(raw)
      return None

    try:
      if handler_c is not None:
        # Legacy test seam.
        authored = handler_c(
          business_facts=business_facts or {},
          ops_json=ops_json or {},
          people_json=people_json or {},
          financials_json=financials_json or {},
          financials_year1_json=financials_year1_json or {},
          planning_mode=_string(planning_mode),
          planning_mode_reason=_string(planning_mode_reason),
          model_input_json=model_input_json or {},
          finmo_json=finmo_json or {},
          stage_ramp_contract=stage_ramp_contract or {},
          draft_id=_string(draft_id),
        )
        if isinstance(authored, dict):
          raw_contract = (
            authored.get("payroll_headcount_contract")
            if isinstance(authored.get("payroll_headcount_contract"), dict)
            else authored
          )
          if isinstance(raw_contract, dict) and raw_contract:
            candidate = copy.deepcopy(raw_contract)
        decision_source = "handler_c_internal_authoring"
      else:
        # GROUND: compute the revenue anchor (always; Python's grounding role).
        anchor = compute_round1_payroll_anchor(
          business_facts=business_facts or {},
          ops_json=ops_json or {},
          people_json=people_json or {},
          financials_json=financials_json or {},
          financials_year1_json=financials_year1_json or {},
          model_input_json=model_input_json or {},
          finmo_json=finmo_json or {},
          policy_code=policy_code,
        )
        _anchor_for_enforcement = anchor
        # EXECUTIVE authors, grounded + validated, with bounded retries.
        from client_intake_and_finmo.post_intake_headcount.gpt_payroll_author import (  # type: ignore  # noqa: E501
          gpt_author_payroll_contract_once,
        )
        from client_intake_and_finmo.post_intake_headcount.schedule import (  # type: ignore  # noqa: E501
          _oews_title_catalog_for_business,
        )
        try:
          oews_catalog = _oews_title_catalog_for_business(
            business_facts=business_facts or {}, ops_json=ops_json or {},
            people_json=people_json or {},
          )
        except Exception:
          oews_catalog = {}
        last_violations: Optional[List[Dict[str, Any]]] = None
        gpt_available = False
        for _attempt in range(_max_gpt_author_attempts):
          authored = gpt_author_payroll_contract_once(
            anchor=anchor, oews_catalog=oews_catalog,
            previous_violations=last_violations,
          )
          if not authored.get("ok"):
            err = _string(authored.get("error"))
            if err.startswith("openai_api_key_unset"):
              break  # no executive available -> deterministic fallback
            last_violations = [{
              "code": "payroll_gpt_author_call_failed", "message": err[:400],
            }]
            continue
          gpt_available = True
          cand = authored.get("contract")
          # Validate to decide accept/retry (same checks as the commit path below).
          try:
            env_v = _check_envelope_violations(cand)
            norm_try = validator(payload=cand)
            band_v = _check_band_violations(cand, bands_echoed)
            vlist = env_v + band_v
            if not vlist and norm_try is not None:
              candidate = copy.deepcopy(cand)
              decision_source = "amalgamated_gpt_authored"
              # The executive's labor-model judgment rides in the author's
              # return envelope (not the validated contract).
              if isinstance(authored.get("revenue_scales_with_labor"), bool):
                _labor_scaling_judgment = authored.get("revenue_scales_with_labor")
                _labor_scaling_rationale = authored.get("labor_scaling_rationale")
              break
            last_violations = vlist or [{
              "code": "payroll_contract_invalid",
              "message": "validator produced no normalized contract",
            }]
          except Exception as exc:
            last_violations = _build_violations_from_runtime_error(exc)
        if candidate is None:
          # No-executive (no key) or executive could not land a valid
          # contract within budget -> deterministic producer fallback
          # (still validated below).
          candidate = _deterministic_fallback()
          decision_source = (
            "deterministic_round1_producer_fallback_after_gpt" if gpt_available
            else "deterministic_round1_producer"
          )
    except Exception as exc:
      return {
        "accepted": False,
        "section": "payroll",
        "contract": None,
        "payload": None,
        "violations": [{
          "code": "payroll_round1_producer_authoring_failed",
          "message": _string(exc)[:600],
        }],
        "bands_echoed": bands_echoed,
        "decision_source": (
          "handler_c_internal_authoring" if handler_c is not None
          else "deterministic_round1_producer"
        ),
      }

  if not isinstance(candidate, dict) or not candidate:
    return {
      "accepted": False,
      "section": "payroll",
      "contract": None,
      "payload": None,
      "violations": [{
        "code": "payroll_contract_required",
        "message": (
          "Handler C authoring produced no contract and no contract was "
          "supplied directly. The orchestrator must either pass a "
          "contract or provide enough builder inputs for Handler C to "
          "author one."
        ),
      }],
      "bands_echoed": bands_echoed,
      "decision_source": decision_source,
    }

  # 0) Economic envelope (B6) — structural sanity check.
  envelope_violations = _check_envelope_violations(candidate)

  # 1) Canonical contract validator (shape + horizon + per-row).
  validator_violations: List[Dict[str, Any]] = []
  normalized: Optional[Dict[str, Any]] = None
  try:
    normalized = validator(payload=candidate)
  except Exception as exc:
    validator_violations = _build_violations_from_runtime_error(exc)

  # 2) Band check (target_payroll_percent_of_revenue against class bounds).
  band_violations = _check_band_violations(candidate, bands_echoed) if not validator_violations else []

  violations = envelope_violations + validator_violations + band_violations
  if violations or normalized is None:
    if decision_source in ("handler_c_internal_authoring", "deterministic_round1_producer"):
      from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore
        EventCode, PhaseCode, Status, safe_emit,
      )
      safe_emit(
        conn,
        draft_id=_string(draft_id),
        planning_run_id=_string(planning_run_id),
        phase=PhaseCode.ROUND1_AUTHORING,
        event_code=EventCode.ROUND1_PAYROLL_FAIL,
        status=Status.FAILED,
        diagnostic_data={
          "violation_codes": [v.get("code") for v in violations][:10],
          "violation_count": len(violations),
        },
      )
    return {
      "accepted": False,
      "section": "payroll",
      "contract": None,
      "payload": None,
      "violations": violations,
      "bands_echoed": bands_echoed,
      "decision_source": decision_source,
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
      "decision_source": decision_source,
    }

  # ----- ENFORCE LABOR-SCALING (round-1 path; executive judged the labor model) -----
  # A labor-bound business must meet revenue growth with proportional staffing, or
  # payroll%-of-revenue collapses and EBITDA is inflated by operating leverage the
  # business does not actually have. Resolve the executive's judgment (GPT's
  # revenue_scales_with_labor, else a labor-intensity default) and, if labor-bound,
  # scale the authored payroll UP so each quarter tracks the anchor's revenue-scaled
  # target. Runs only on the round-1 authoring path (where the anchor exists); the
  # downstream cascade then re-solves other levers against the real margin.
  labor_scaling_trace: Optional[Dict[str, Any]] = None
  if isinstance(_anchor_for_enforcement, dict) and isinstance(payload, dict):
    labor_bound = _labor_scaling_judgment
    judgment_source = "executive_gpt" if isinstance(_labor_scaling_judgment, bool) else None
    if labor_bound is None:
      cls = str(_anchor_for_enforcement.get("labor_intensity_class") or "").strip().lower()
      labor_bound = cls in ("medium", "high", "expert")
      judgment_source = "labor_intensity_class_default"
    if labor_bound:
      from client_intake_and_finmo.post_intake_headcount.schedule import (  # type: ignore
        enforce_labor_scaling_on_payload,
      )
      summary = enforce_labor_scaling_on_payload(payload, _anchor_for_enforcement)
      labor_scaling_trace = {
        "revenue_scales_with_labor": True,
        "applied": bool(summary),
        "judgment_source": judgment_source,
        "rationale": _labor_scaling_rationale,
        "target_payroll_percent": (
          float(payload.get("target_payroll_percent_of_revenue"))
          if isinstance(payload.get("target_payroll_percent_of_revenue"), (int, float))
          else None
        ),
        **(summary or {"scaled": False, "reason": "authored payroll already tracks target"}),
      }
    else:
      labor_scaling_trace = {
        "revenue_scales_with_labor": False,
        "applied": False,
        "judgment_source": judgment_source,
        "rationale": _labor_scaling_rationale,
        "reason": "executive judged operating leverage (payroll may stay ~fixed as revenue grows)",
      }

  # Step 9b-ii — emit ROUND1_PAYROLL_OK on the contract=None round-1 path.
  # Cascade revisions pass a contract directly and are observed via the
  # SessionDriver's CASCADE_PROPOSAL_* emits.
  if decision_source in ("handler_c_internal_authoring", "deterministic_round1_producer"):
    from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore
      EventCode, PhaseCode, Status, safe_emit,
    )
    safe_emit(
      conn,
      draft_id=_string(draft_id),
      planning_run_id=_string(planning_run_id),
      phase=PhaseCode.ROUND1_AUTHORING,
      event_code=EventCode.ROUND1_PAYROLL_OK,
      status=Status.COMPLETED,
      diagnostic_data={"decision_source": decision_source},
    )
  return {
    "accepted": True,
    "section": "payroll",
    "contract": normalized,
    "payload": payload,
    "violations": [],
    "bands_echoed": bands_echoed,
    "decision_source": decision_source,
    "labor_scaling": labor_scaling_trace,
  }
