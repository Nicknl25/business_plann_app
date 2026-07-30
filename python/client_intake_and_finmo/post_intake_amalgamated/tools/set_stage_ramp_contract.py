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
import math
from typing import Any, Callable, Dict, List, Optional, Tuple


def _string(value: Any) -> str:
  return str(value if value is not None else "").strip()


# Economic envelope (B6). Cheap per-field sanity checks that catch
# malformations the cohort-band check can't see (e.g. a value that
# happens to fall in band but is structurally impossible such as
# a negative cost ratio or a utilization > 1).
_RATIO_FIELDS_STAGE_RAMP = (
  "cogs_max", "marketing_max", "rd_max", "ga_max",
  # P3.41 audit F-C1: was "util_max" (dead -- producer emits "max_util"
  # at post_intake_contracts/runner.py:2017); renamed so the [0, 1]
  # ratio sanity bound actually fires on the real utilization field.
  # "util_floor" removed (no producer emits any such field).
  "max_util",
)


def _is_finite_number(v: Any) -> bool:
  return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _check_envelope_violations(contract: Dict[str, Any]) -> List[Dict[str, Any]]:
  """B6 — economic envelope check for stage_ramp contracts. Returns one
  entry per violation; the band check still runs and adds its own."""
  violations: List[Dict[str, Any]] = []
  if not isinstance(contract, dict):
    return violations
  grid = contract.get("quarter_ramp_grid")
  if not isinstance(grid, list):
    return violations
  prev_rev_max: Optional[float] = None
  for q_idx, row in enumerate(grid, start=1):
    if not isinstance(row, dict):
      continue
    # rev_max (or revenue_qoq_max) — non-negative and finite. Negative
    # revenue is structurally impossible; allow zero (Q1 trough is fine).
    rev_max = row.get("rev_max", row.get("revenue_qoq_max"))
    if rev_max is not None:
      if not _is_finite_number(rev_max):
        violations.append({
          "code": "envelope_violation_rev_max_not_finite",
          "quarter_index": q_idx, "field": "rev_max", "actual": rev_max,
        })
      elif float(rev_max) < 0:
        violations.append({
          "code": "envelope_violation_rev_max_negative",
          "quarter_index": q_idx, "field": "rev_max", "actual": float(rev_max),
        })
      else:
        # Monotonic non-decreasing across quarters (a stage ramp should
        # not regress; if a contract intentionally ramps down it should
        # carry a ramp_down_allowed flag — which we don't yet model, so
        # any decrease is a violation).
        if prev_rev_max is not None and float(rev_max) < prev_rev_max - 1e-9:
          violations.append({
            "code": "envelope_violation_rev_max_non_monotonic",
            "quarter_index": q_idx, "field": "rev_max",
            "actual": float(rev_max), "previous": prev_rev_max,
          })
        prev_rev_max = float(rev_max)
    # Ratio fields — must be in [0, 1] and finite.
    for field in _RATIO_FIELDS_STAGE_RAMP:
      v = row.get(field)
      if v is None:
        continue
      if not _is_finite_number(v):
        violations.append({
          "code": "envelope_violation_ratio_not_finite",
          "quarter_index": q_idx, "field": field, "actual": v,
        })
        continue
      vf = float(v)
      if vf < 0.0 or vf > 1.0:
        violations.append({
          "code": "envelope_violation_ratio_out_of_unit_interval",
          "quarter_index": q_idx, "field": field, "actual": vf,
        })
    # P3.41 audit F-C1: deleted the util_max >= util_floor consistency
    # check -- both referenced fields were wrong/nonexistent (producer
    # emits "max_util", never emits any "util_floor"). The remaining
    # max_util ratio bound above replaces the structural sanity coverage.
    # ni_floor — finite (can be negative). Reject NaN/inf only.
    ni = row.get("ni_floor")
    if ni is not None and not _is_finite_number(ni):
      violations.append({
        "code": "envelope_violation_ni_floor_not_finite",
        "quarter_index": q_idx, "field": "ni_floor", "actual": ni,
      })
  return violations


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
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
  """Cross-check each per-quarter contract value against the
  corresponding cohort/robust band. Returns (violations, advisories).

  OWNERSHIP (Wave 2, three-tier): the cohort band is a fitted statistic
  that doesn't know THIS business. For CEILING fields (*_max) it retains
  its veto (violations). For FLOOR fields (ni_floor, *_floor) the seat is
  OWNED by the planning-mode policy (early quarters; the producer derives
  the floors FROM policy and the envelope/validator enforce them) and by
  the executive-judged ni_margin_floor_q11 at maturity (acceptance gate)
  — so a floor breach of the cohort band DEMOTES to an ADVISORY: recorded
  and persisted (informing band recalibration), never independently
  rejecting. No boundary tolerance exists because none is needed — the
  informant cannot veto the owner.
  """
  violations: List[Dict[str, Any]] = []
  advisories: List[Dict[str, Any]] = []
  if not isinstance(contract, dict) or not isinstance(bands, dict) or not bands:
    return violations, advisories
  grid = contract.get("quarter_ramp_grid") or []
  if not isinstance(grid, list):
    return violations, advisories
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
      # Direction matters (per this function's stated intent): expense
      # CEILINGS (*_max) violate only ABOVE robust_max — a ceiling below
      # the cohort minimum is a lean business, not a violation (raw
      # cohort scale is exactly what fitted bands correct for). FLOORS
      # (ni_floor, *_floor) violate only BELOW robust_min. The original
      # loop applied both bounds to every field; it shipped alongside
      # the schema drift that kept the populator dead, so it first ran
      # against real bands only after the fallback-class fix — and
      # instantly rejected every lean-cost business.
      is_ceiling = field.endswith("_max")
      is_floor = field.endswith("_floor")
      if (
        (is_ceiling or not is_floor)
        and isinstance(r_max, (int, float))
        and float(value) > float(r_max)
      ):
        violations.append({
          "code": "stage_ramp_above_band_max",
          "quarter_index": q_idx,
          "field": field,
          "actual": float(value),
          "band_max": float(r_max),
          "delta": float(value) - float(r_max),
          "units": "fraction",
        })
      if (
        (is_floor or not is_ceiling)
        and isinstance(r_min, (int, float))
        and float(value) < float(r_min)
      ):
        entry = {
          "code": "stage_ramp_below_band_min",
          "quarter_index": q_idx,
          "field": field,
          "actual": float(value),
          "band_min": float(r_min),
          "delta": float(r_min) - float(value),
          "units": "fraction",
        }
        if is_floor:
          entry["code"] = "stage_ramp_floor_below_cohort_band_advisory"
          advisories.append(entry)
        else:
          violations.append(entry)
  return violations, advisories


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

  business_stage = (
    _string((ops_json or {}).get("business_stage"))
    or _string((business_facts or {}).get("business_stage"))
  )
  # Stage rules must match the business's REAL stage (root-disease fix:
  # references GROUND, they don't impose a default law). The builder produces a
  # stage-appropriate grid (e.g. a loss-tolerant startup ramp for a pre-revenue
  # firm) but doesn't always stamp stage_family onto the contract -- so this tool
  # used to DEFAULT expected_family to "operational" and then reject the
  # (correct) loss-tolerant grid against operational-firm profitability rules.
  # Derive the family from business_stage (pre-revenue/startup/launch ->
  # "startup"; early/growth -> "early"; else operational), so a pre-revenue
  # business is graded by a startup posture (negative ni_floor + improving_losses
  # are VALID for a startup, not a violation). Universal.
  from client_intake_and_finmo.post_intake_contracts.runner import (  # type: ignore  # noqa: E501
    _business_stage_family,
  )
  expected_family = (
    _string(expected_stage_family)
    or _string(candidate.get("stage_family"))
    or (_business_stage_family(business_stage) if business_stage else "")
    or "operational"
  )
  business_stage = business_stage or expected_family
  # Stamp the resolved family onto the candidate so the validator's internal
  # stage_family-consistency check agrees with the expected family.
  if not _string(candidate.get("stage_family")):
    candidate["stage_family"] = expected_family
  r_and_d_enabled = True
  if isinstance(r_and_d_applicability, dict) and isinstance(r_and_d_applicability.get("r_and_d_enabled"), bool):
    r_and_d_enabled = bool(r_and_d_applicability["r_and_d_enabled"])

  # 0) Economic envelope (B6) — cheap structural sanity check before band/validator.
  envelope_violations = _check_envelope_violations(candidate)

  # 1) Cohort/robust band check (cross-section coherence with drivers).
  # Ceilings may veto; floor breaches come back as ADVISORIES (the floor
  # seats are owned by policy / the executive judgment — Wave 2).
  band_violations, band_advisories = _check_band_violations(candidate, bands_echoed)
  if band_advisories:
    # Persist the advisory so the statistic keeps informing: (a) a
    # runtime-status trace row (queryable per draft), (b) stamped onto
    # the contract below when accepted, (c) in the return envelope.
    try:
      from client_intake_and_finmo.post_intake_handler_traces import (  # type: ignore
        record_runtime_status,
      )
      record_runtime_status(
        handler="stage_ramp_band_advisory",
        status={
          "draft_id": _string(draft_id),
          "advisories": band_advisories,
          "decision_source": decision_source,
        },
      )
    except Exception:
      pass

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

  # Step 9b-ii — emit ROUND1_STAGE_RAMP_OK/FAIL only when contract=None
  # (round-1 authoring path). Cascade-revision callers supply a
  # contract and are observed via the SessionDriver's CASCADE_PROPOSAL_*
  # emits.
  is_round1 = contract is None
  from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore
    EventCode, PhaseCode, Status, safe_emit,
  )

  violations = envelope_violations + validator_violations + band_violations
  if violations:
    if is_round1:
      safe_emit(
        conn,
        draft_id=_string(draft_id),
        planning_run_id=_string(planning_run_id),
        phase=PhaseCode.ROUND1_AUTHORING,
        event_code=EventCode.ROUND1_STAGE_RAMP_FAIL,
        status=Status.FAILED,
        diagnostic_data={
          "violation_codes": [v.get("code") for v in violations][:10],
          "violation_count": len(violations),
          "decision_source": decision_source,
        },
      )
    return {
      "accepted": False,
      "section": "stage_ramp",
      "contract": None,
      "violations": violations,
      "band_advisories": band_advisories,
      "bands_echoed": bands_echoed,
      "decision_source": decision_source,
    }

  # Accepted. Annotate provenance fields the orchestrator already
  # consumes; the engage helper layers on the same fields today.
  accepted = copy.deepcopy(candidate)
  if band_advisories:
    accepted["band_advisories"] = band_advisories
  accepted.setdefault("decision_source", decision_source)
  accepted.setdefault("business_stage", business_stage)
  accepted.setdefault("planning_mode", _string(planning_mode).lower())
  accepted.setdefault("planning_mode_reason", _string(planning_mode_reason))
  accepted.setdefault("contract_version", "stage_ramp_contract_v2")
  if is_round1:
    safe_emit(
      conn,
      draft_id=_string(draft_id),
      planning_run_id=_string(planning_run_id),
      phase=PhaseCode.ROUND1_AUTHORING,
      event_code=EventCode.ROUND1_STAGE_RAMP_OK,
      status=Status.COMPLETED,
      diagnostic_data={
        "decision_source": decision_source,
        "stage_family": accepted.get("stage_family"),
        "planning_mode": accepted.get("planning_mode"),
      },
    )
  return {
    "accepted": True,
    "section": "stage_ramp",
    "contract": accepted,
    "violations": [],
    "bands_echoed": bands_echoed,
    "decision_source": decision_source,
  }
