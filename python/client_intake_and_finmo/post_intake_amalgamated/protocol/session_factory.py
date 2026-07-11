"""Factory that constructs a SessionDriver wired to production sources.

Step 8a deliverable: builds the driver from the orchestrator-side
inputs (conn, draft_id, planning_run_id, mirror, model_input_json,
finmo_json, stage_ramp_contract) and registers the production
callbacks the driver needs:

  - evaluate_plan_fn      -> post_intake_amalgamated.evaluate_plan.evaluate_plan
  - responder             -> protocol.responder.make_amalgamated_responder
  - revise_fn_for_section -> the four revise_* tools, dispatched by
                             proposal.section
  - log_fn                -> protocol.restructuring_log_table.log_restructure
                             (bound to conn)
  - current_payload_for   -> mirror.plan_state[section]
  - primitive_kwargs_for_mode -> per-mode floor primitive inputs
                             extracted from mirror/model_input/finmo

Plus ``driver_run_with_audit_wrapper`` — the failure-path helper
spec'd in the step-8 design discussion (item D). Wraps
``driver.run()`` in try/except, writes a best-effort META_ESCALATED
audit row, and re-raises a structured RuntimeError. Both the audit-
write try/except and the re-raise are visible in the code from day
one.

No orchestrator edits in this commit — step 8b wires the factory
into prepare_initial_grid_for_draft.
"""

from __future__ import annotations

import copy
import sys
from typing import Any, Callable, Dict, List, Optional

from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (
  EvaluatePlanResult,
  FailureMode,
)
from client_intake_and_finmo.post_intake_amalgamated.mirror import Mirror
from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
  coherence_anchor_order,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (
  AppliedBy,
  ReasonCode,
  StepType,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.responder import (
  make_amalgamated_responder,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.restructuring_log_table import (
  log_restructure,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.session_driver import (
  SessionDriver,
)
# Step 9b — diagnostic emitter. The factory binds emit_diagnostic with
# conn/draft_id/planning_run_id closure-captured and hands the callable
# to SessionDriver for state-transition emits.
from client_intake_and_finmo.post_intake_diagnostics.run_diagnostics_table import (  # type: ignore  # noqa: E501
  emit_diagnostic,
)


# Section name -> revise_* tool. The post-WC-migration mapping (pre-step-8
# commit 1613fd1):
#   drivers       -> revise_drivers
#   stage_ramp    -> revise_stage_ramp_contract
#   payroll       -> revise_payroll_schedule
#   balance_sheet -> revise_capex_rd_balance_seed   (capex + R&D + balance
#                                                    sheet seed all live
#                                                    here; WC days routed
#                                                    via the new
#                                                    "working_capital_days"
#                                                    overrides sub-key)
#   capex_rd      -> revise_capex_rd_balance_seed
#   capex_rd_balance_seed -> revise_capex_rd_balance_seed
#
# operating_model levers (unit_price, utilization_rate, capacity) have
# no dedicated revise_* tool today; revise_fn_for_section returns None
# for those sections, the driver logs the proposal but does not apply,
# and the cascade advances. (Spec §11.3 — these are authored via the
# existing operating_model writers inside the orchestrator's model_input
# update path; a future commit can add a revise_operating_model wrapper
# if cascade V3/V4/V5/G2/G3/G4/C1/C2 need direct mutation.)


def _build_revise_fn_for_section(
  *,
  conn,
  draft_id: str,
  planning_run_id: str,
  mirror: Mirror,
  operating_context: Optional[Dict[str, Any]] = None,
  business_facts: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  model_input_json: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
) -> Callable[[str], Optional[Callable[..., Dict[str, Any]]]]:
  """Return a dispatcher mapping section name -> revise_* wrapper.

  The returned dispatch closure-binds the per-session inputs the
  revise_* tools need (conn, draft_id, planning_run_id, business_facts,
  etc.). The session driver calls revise_fn(current=..., patch=...,
  proposal=...) per spec §11.3.
  """
  from client_intake_and_finmo.post_intake_amalgamated.tools.revise_drivers import (
    revise_drivers,
  )
  from client_intake_and_finmo.post_intake_amalgamated.tools.revise_stage_ramp_contract import (  # noqa: E501
    revise_stage_ramp_contract,
  )
  from client_intake_and_finmo.post_intake_amalgamated.tools.revise_payroll_schedule import (  # noqa: E501
    revise_payroll_schedule,
  )
  from client_intake_and_finmo.post_intake_amalgamated.tools.revise_capex_rd_balance_seed import (  # noqa: E501
    revise_capex_rd_balance_seed,
  )

  def _drivers(*, current, patch, proposal, **_):
    return revise_drivers(
      conn=conn, draft_id=draft_id, planning_run_id=planning_run_id,
      current_anchors=current, patch=patch,
      operating_context=operating_context,
    )

  def _stage_ramp(*, current, patch, proposal, **_):
    return revise_stage_ramp_contract(
      conn=conn, draft_id=draft_id, planning_run_id=planning_run_id,
      current_contract=current, patch=patch,
      business_facts=business_facts, ops_json=ops_json,
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
      model_input_json=model_input_json, finmo_json=finmo_json,
    )

  def _payroll(*, current, patch, proposal, **_):
    return revise_payroll_schedule(
      conn=conn, draft_id=draft_id, planning_run_id=planning_run_id,
      current_contract=current, patch=patch,
      business_facts=business_facts, ops_json=ops_json,
      model_input_json=model_input_json,
    )

  def _balance_sheet(*, current, patch, proposal, **_):
    return revise_capex_rd_balance_seed(
      conn=conn, draft_id=draft_id, planning_run_id=planning_run_id,
      current_overrides=current, patch=patch,
      business_facts=business_facts, ops_json=ops_json,
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
      model_input_json=model_input_json, finmo_json=finmo_json,
    )

  def _operating_model(*, current, patch, proposal, **_):
    # Fork A B1: apply pricing / utilization / capacity / productivity levers
    # (was a no-op -- the executive's V3/V4/V5/G2/G3/G4/C1/C2/C3/C5 choices
    # never mutated the plan).
    from client_intake_and_finmo.post_intake_amalgamated.tools.revise_operating_model import (  # noqa: E501
      revise_operating_model,
    )
    return revise_operating_model(
      conn=conn, draft_id=draft_id, planning_run_id=planning_run_id,
      current=current, patch=patch, proposal=proposal,
      operating_context=operating_context,
    )

  table: Dict[str, Callable[..., Dict[str, Any]]] = {
    "drivers":               _drivers,
    "stage_ramp":            _stage_ramp,
    "payroll":               _payroll,
    "balance_sheet":         _balance_sheet,
    "capex_rd":              _balance_sheet,
    "capex_rd_balance_seed": _balance_sheet,
    "operating_model":       _operating_model,
  }

  def dispatch(section: str) -> Optional[Callable[..., Dict[str, Any]]]:
    return table.get(section)

  return dispatch


def _build_current_payload_for(mirror: Mirror) -> Callable[[str], Any]:
  """Reader for current section state — lifts from mirror.plan_state.

  Section name aliasing: revise_capex_rd_balance_seed expects the
  current_overrides dict to be the prior overrides payload (or empty
  for the first revision). The mirror's plan_state["balance_sheet"]
  may carry either the seed payload or the overrides dict; we
  conservatively return whatever is there and let the revise tool's
  deep_merge_patch handle it.
  """
  def current_payload_for(section: str) -> Any:
    if mirror is None:
      return None
    aliases = (section,)
    if section in ("capex_rd", "capex_rd_balance_seed"):
      aliases = (section, "balance_sheet")
    elif section == "balance_sheet":
      aliases = (section, "capex_rd_balance_seed")
    for key in aliases:
      value = mirror.plan_state.get(key) if isinstance(mirror.plan_state, dict) else None
      if value is not None:
        return value
    return None
  return current_payload_for


def _interp_anchor(anchor_vals: Dict[int, Any], quarter_index: int) -> Optional[float]:
  """Linear interpolation across {1: q1, 11: q11, 20: q20} driver anchors.
  Cascade driver proposals are flat (q1==q11==q20) so this returns that
  flat value; it stays correct for the general non-flat anchor case too."""
  pts = sorted((q, float(v)) for q, v in anchor_vals.items() if v is not None)
  if not pts:
    return None
  if quarter_index <= pts[0][0]:
    return pts[0][1]
  if quarter_index >= pts[-1][0]:
    return pts[-1][1]
  for i in range(1, len(pts)):
    q0, v0 = pts[i - 1]
    q1, v1 = pts[i]
    if q0 <= quarter_index <= q1:
      if q1 == q0:
        return v1
      frac = (quarter_index - q0) / (q1 - q0)
      return v0 + frac * (v1 - v0)
  return pts[-1][1]


def _drivers_anchors_to_exact_updates(anchors: Dict[str, Any]) -> List[Dict[str, Any]]:
  """drivers plan_state (``{lever_id: {q1, q11, q20}}``) -> per-quarter exact
  lever updates for apply_exact_lever_updates_to_model_input."""
  updates: List[Dict[str, Any]] = []
  for lever_id, spec in (anchors or {}).items():
    if not isinstance(spec, dict):
      continue
    anchor_vals = {1: spec.get("q1"), 11: spec.get("q11"), 20: spec.get("q20")}
    if all(v is None for v in anchor_vals.values()):
      continue
    for q in range(1, 21):
      v = _interp_anchor(anchor_vals, q)
      if v is not None:
        updates.append({"lever_id": str(lever_id), "quarter_index": q, "exact_value": float(v)})
  return updates


def _propagate_committed_section_to_model_input(
  live_ref: Dict[str, Any], section: str, payload: Any,
) -> None:
  """Fork A — after a cascade commit, propagate the committed section into
  the LIVE model_input so the next round's recompute reflects the executive's
  move (REAL per-round deltas). Mirrors round-1's appliers. Raises on a
  propagation failure (caught + emitted by SessionDriver._commit_proposal's
  mirror-refresh handler) so a no-propagation bug is never silent."""
  mi = live_ref.get("mi")
  if not isinstance(mi, dict) or not isinstance(section, str):
    return
  # The model_input appliers are sequence-controller-guarded; the cascade is
  # a legitimate orchestration-level caller (see post_intake_sequence_step_scope).
  from client_intake_and_finmo.post_intake_sequence import (  # type: ignore
    post_intake_sequence_step_scope,
  )
  from client_intake_and_finmo.quarter_grid import (  # type: ignore
    apply_exact_lever_updates_to_model_input,
  )
  with post_intake_sequence_step_scope(
    step_key="amalgamated_in_cascade_propagate",
    phase="post_intake_target_seeking",
    executor_function="amalgamated_in_cascade_propagate",
  ):
    if section == "drivers" and isinstance(payload, dict):
      updates = _drivers_anchors_to_exact_updates(payload)
      # REVENUE IS NOT THE CASCADE'S LEVER when deterministically authored:
      # the market-grounded growth judgment owns the trajectory and the
      # ceilinged viability search owns adaptation above it. Without this
      # guard the executive's set_drivers anchors re-authored per-LOB
      # utilization ramps (Anderson: judged 8->4%/yr rewritten to ~34%/yr
      # via Q1/Q11/Q20 anchors interpolated onto the revenue rows).
      if bool(((mi or {}).get("solver_input") or {}).get("revenue_authored")):
        updates = [
          u for u in (updates or [])
          if not str((u or {}).get("lever_id") or "").strip().startswith("revenue::")
        ]
      if updates:
        live_ref["mi"] = apply_exact_lever_updates_to_model_input(
          model_input_json=mi, exact_updates=updates,
        )
    elif section == "payroll" and isinstance(payload, dict):
      from client_intake_and_finmo.post_intake_headcount.schedule import (  # type: ignore
        apply_payroll_supported_capacity_to_model_input,
        apply_payroll_headcount_payload_to_model_input,
      )
      mi2 = apply_payroll_supported_capacity_to_model_input(
        copy.deepcopy(mi), copy.deepcopy(payload), live_count=20,
      )
      mi2 = apply_payroll_headcount_payload_to_model_input(
        mi2, copy.deepcopy(payload), live_count=20,
      )
      live_ref["mi"] = mi2
    elif section in ("balance_sheet", "capex_rd", "capex_rd_balance_seed") and isinstance(payload, dict):
      from client_intake_and_finmo.finmo_bridge import (  # type: ignore
        apply_balance_sheet_contextual_seed_to_model_input,
      )
      seed = payload.get("balance_sheet_seed") if isinstance(payload.get("balance_sheet_seed"), dict) else payload
      live_ref["mi"] = apply_balance_sheet_contextual_seed_to_model_input(
        copy.deepcopy(mi), copy.deepcopy(seed), live_count=20,
      )
    elif section == "operating_model" and isinstance(payload, dict):
      # B1: map operating_model levers (unit_price/utilization_rate/
      # units_per_week_capacity) onto the live revenue rows by driver, so the
      # next round's recompute reflects the executive's pricing/util/capacity
      # move. (per_employee_productivity is carried but not a revenue row;
      # capacity re-derivation from it is a follow-up.)
      from client_intake_and_finmo.post_intake_amalgamated.tools.revise_operating_model import (  # noqa: E501
        apply_operating_model_levers_to_model_input,
      )
      live_ref["mi"] = apply_operating_model_levers_to_model_input(mi, payload)
  # stage_ramp propagation: the stage-ramp contract reshapes the revenue/util
  # path through its own builder; per-commit model_input propagation for it is
  # a follow-up (tracked). plan_state IS updated regardless, so the final
  # build still reflects it; in-loop deltas for stage-ramp-only tiers may lag.


def _finmo_parity_key(finmo_json: Optional[Dict[str, Any]]) -> str:
  """Canonical comparison key = the economic substance (quarter_rows)."""
  import json as _json
  rows = (finmo_json or {}).get("quarter_rows") if isinstance(finmo_json, dict) else None
  return _json.dumps(rows or [], sort_keys=True, default=str)


def _assert_round1_finmo_parity(
  entry_finmo: Optional[Dict[str, Any]],
  recomputed_finmo: Optional[Dict[str, Any]],
  *, conn, draft_id: str, planning_run_id: str,
) -> None:
  """MANDATORY (Fork A): on round 1 (unchanged plan_state) the in-cascade
  recompute MUST reproduce the round-1 finmo. A mismatch means the live
  model_input assembly is wrong and any later 'convergence' is FAKE -> fail
  loud and stop."""
  if _finmo_parity_key(entry_finmo) == _finmo_parity_key(recomputed_finmo):
    return
  e_rows = len((entry_finmo or {}).get("quarter_rows") or []) if isinstance(entry_finmo, dict) else 0
  r_rows = len((recomputed_finmo or {}).get("quarter_rows") or []) if isinstance(recomputed_finmo, dict) else 0
  detail = (
    f"in-cascade recompute != round-1 finmo on UNCHANGED plan_state "
    f"(entry_quarter_rows={e_rows}, recompute_quarter_rows={r_rows}); "
    f"the live model_input assembly is wrong -- convergence would be fake."
  )
  try:
    from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore
      FailFastCode as _FFC, PhaseCode as _PC, raise_fail_fast as _rff,
    )
    _rff(
      conn, draft_id=str(draft_id or ""), planning_run_id=str(planning_run_id or ""),
      phase=_PC.EVALUATE_PLAN, code=_FFC.FAIL_EVALUATE_PLAN_MALFORMED,
      detail=f"fork_a_round1_finmo_parity_failed: {detail}",
      where="session_factory.evaluate_plan_fn (parity)",
    )
  except Exception:
    raise RuntimeError(f"fork_a_round1_finmo_parity_failed: {detail}")


def _build_evaluate_plan_fn(
  *,
  conn,
  draft_id: str,
  planning_run_id: str,
  mirror: Mirror,
  operating_context: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
  live_model_input_ref: Optional[Dict[str, Any]] = None,
  build_finmo: Optional[Callable[..., Any]] = None,
  business_naics_6: Optional[str] = None,
) -> Callable[..., EvaluatePlanResult]:
  """Fork A in-cascade standard: each round, rebuild the LIVE finmo from the
  current ``live_model_input`` (mutated per commit) and score the
  restructurable economic checks on it (in_cascade=True). On round 1 the
  recompute MUST equal the round-1 finmo (mandatory parity assertion)."""
  from client_intake_and_finmo.post_intake_amalgamated.evaluate_plan import (
    evaluate_plan,
  )
  _bf = build_finmo
  if _bf is None:
    from client_intake_and_finmo.finmo_bridge import (  # type: ignore
      build_python_finmo_json as _bf,
    )
  entry_finmo = copy.deepcopy(finmo_json) if isinstance(finmo_json, dict) else {}
  _ref = live_model_input_ref if isinstance(live_model_input_ref, dict) else {"mi": {}}
  parity_state = {"checked": False}

  def evaluate_plan_fn(*, round_number: int) -> EvaluatePlanResult:
    # The in-cascade FINMO rebuild calls sequence-controller-guarded helpers
    # (payroll capacity derivation, validators, etc.). The amalgamated
    # cascade is a legitimate orchestration-level caller per
    # post_intake_sequence_step_scope's contract, so we push a synthetic
    # scope that honestly identifies the recompute step.
    from client_intake_and_finmo.post_intake_sequence import (  # type: ignore
      post_intake_sequence_step_scope,
    )
    with post_intake_sequence_step_scope(
      step_key="amalgamated_in_cascade_evaluate",
      phase="post_intake_target_seeking",
      executor_function="amalgamated_in_cascade_evaluate",
    ):
      live_mi = _ref.get("mi") or {}
      live_finmo = _bf(model_input_json=copy.deepcopy(live_mi))
      if not parity_state["checked"]:
        parity_state["checked"] = True
        _assert_round1_finmo_parity(
          entry_finmo, live_finmo,
          conn=conn, draft_id=draft_id, planning_run_id=planning_run_id,
        )
      return evaluate_plan(
        conn=conn,
        draft_id=draft_id,
        planning_run_id=planning_run_id,
        plan_state=dict(mirror.plan_state) if isinstance(mirror.plan_state, dict) else {},
        in_cascade=True,
        round_number=int(round_number),
        anchors=None,
        operating_context=operating_context,
        finmo_json=live_finmo,
        business_naics_6=business_naics_6,
      )

  return evaluate_plan_fn


def _build_primitive_kwargs_for_mode(
  *,
  mirror: Mirror,
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  stage_ramp_contract: Optional[Dict[str, Any]],
  build_finmo: Optional[Callable[..., Any]] = None,
) -> Callable[[FailureMode], Dict[str, Any]]:
  """Per-mode kwargs for the §9.2 floor primitives. Pulls
  target_q12_revenue / unit_price / cohort_util_target from the mirror
  + model_input at primitive-invocation time."""

  def primitive_kwargs_for_mode(mode: FailureMode) -> Dict[str, Any]:
    if mode == FailureMode.VIABILITY_INVARIANT:
      return {
        "model_input": model_input_json,
        "build_finmo": build_finmo,
        "stage_ramp_contract": stage_ramp_contract,
      }
    if mode == FailureMode.GROWTH_INVARIANT:
      return {
        "model_input": model_input_json,
        "build_finmo": build_finmo,
        "stage_ramp_contract": stage_ramp_contract,
        "max_passes": 12,
      }
    if mode == FailureMode.CAPACITY_INVARIANT:
      target_rev = None
      unit_price = None
      cohort_util = None
      if isinstance(mirror.business_facts, dict):
        target_rev = mirror.business_facts.get("target_q12_revenue")
        unit_price = mirror.business_facts.get("unit_price")
        cohort_util = mirror.business_facts.get("cohort_util_target")
      return {
        "target_q12_revenue": target_rev,
        "unit_price": unit_price,
        "cohort_util_target": cohort_util,
      }
    if mode == FailureMode.BAND_INVARIANT:
      lever_margins = []
      validation = getattr(mirror, "validation_state", None) or {}
      if isinstance(validation, dict):
        lever_margins = validation.get("lever_margins") or []
      return {"lever_margins": lever_margins}
    if mode == FailureMode.COHERENCE_INVARIANT:
      order = coherence_anchor_order()
      return {
        "anchor_section": order[0] if order else "stage_ramp",
        "non_anchor_sections": list(order[1:]) if len(order) > 1 else [],
      }
    return {}

  return primitive_kwargs_for_mode


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def make_session_driver(
  *,
  conn,
  draft_id: str,
  planning_run_id: str,
  mirror: Mirror,
  operating_context: Optional[Dict[str, Any]] = None,
  business_facts: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  model_input_json: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
  stage_ramp_contract: Optional[Dict[str, Any]] = None,
  build_finmo: Optional[Callable[..., Any]] = None,
  responder: Optional[Callable[..., Any]] = None,
  budget: Optional[int] = None,
) -> SessionDriver:
  """Build a fully-wired SessionDriver for one amalgamated session.

  ``responder=None`` constructs the production responder
  (make_amalgamated_responder bound to this session). Tests pass a
  callable directly. ``budget`` overrides the default (35) when
  supplied.
  """
  effective_responder = responder if responder is not None else make_amalgamated_responder(
    conn=conn,
    draft_id=draft_id,
    planning_run_id=planning_run_id,
    mirror=mirror,
  )

  # Fork A — the LIVE model_input the in-cascade standard recomputes finmo
  # from each round. Seeded to the round-1 applied_model_input_json so the
  # mandatory round-1 parity assertion holds by construction
  # (build_python_finmo_json is deterministic and the runner built
  # applied_finmo_json from this same model_input). Mutated per commit by
  # _propagate_committed_section_to_model_input so the executive's moves
  # produce REAL per-round finmo deltas.
  live_model_input_ref: Dict[str, Any] = {"mi": copy.deepcopy(model_input_json or {})}

  _session_naics_6 = "".join(
    ch for ch in str(
      (ops_json or {}).get("business_naics_6")
      or (business_facts or {}).get("naics_6")
      or (business_facts or {}).get("business_naics_6")
      or ""
    ) if ch.isdigit()
  )
  evaluate_plan_fn = _build_evaluate_plan_fn(
    conn=conn, draft_id=draft_id, planning_run_id=planning_run_id,
    mirror=mirror, operating_context=operating_context,
    finmo_json=finmo_json,
    live_model_input_ref=live_model_input_ref,
    build_finmo=build_finmo,
    business_naics_6=_session_naics_6,
  )
  revise_fn_for_section = _build_revise_fn_for_section(
    conn=conn, draft_id=draft_id, planning_run_id=planning_run_id,
    mirror=mirror, operating_context=operating_context,
    business_facts=business_facts, ops_json=ops_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    model_input_json=model_input_json, finmo_json=finmo_json,
  )
  current_payload_for = _build_current_payload_for(mirror)
  # P3.40 bug 2 fix: bind the mirror's plan_state setter so SessionDriver
  # can refresh the in-memory snapshot after each revise_* commit.
  # Fork A: ALSO propagate the committed section into live_model_input so the
  # next round's recompute reflects the move (real per-round deltas).
  def apply_to_plan_state_fn(section: str, payload: Any) -> None:
    mirror.set_plan_state_section(section, payload)
    _propagate_committed_section_to_model_input(live_model_input_ref, section, payload)
  # P3.40 bug 3 fix: bind the mirror's validation_state setter so
  # SessionDriver propagates each evaluate_plan result into the mirror.
  # Without this, the responder's render_mirror_for_proposal always sees
  # an empty validation_state (the setter existed since session-1 but
  # had zero callers).
  def apply_to_validation_state_fn(evaluate_plan_result: Any) -> None:
    mirror.set_validation_state(evaluate_plan_result)
  primitive_kwargs_for_mode = _build_primitive_kwargs_for_mode(
    mirror=mirror, model_input_json=model_input_json,
    finmo_json=finmo_json, stage_ramp_contract=stage_ramp_contract,
    build_finmo=build_finmo,
  )

  # Step 9b — diagnostic emitter wired with conn/draft_id/planning_
  # run_id closure-captured. The driver calls it at every state
  # transition. Best-effort writes (the driver's _emit swallows
  # exceptions so observability never breaks the protocol).
  def _emit_diagnostic_fn(**kw: Any) -> Any:
    return emit_diagnostic(
      conn,
      draft_id=draft_id,
      planning_run_id=planning_run_id,
      **kw,
    )

  driver_kwargs: Dict[str, Any] = dict(
    draft_id=draft_id,
    planning_run_id=planning_run_id,
    evaluate_plan_fn=evaluate_plan_fn,
    responder=effective_responder,
    revise_fn_for_section=revise_fn_for_section,
    log_fn=lambda **kw: log_restructure(conn, **kw),
    current_payload_for=current_payload_for,
    apply_to_plan_state_fn=apply_to_plan_state_fn,
    apply_to_validation_state_fn=apply_to_validation_state_fn,
    primitive_kwargs_for_mode=primitive_kwargs_for_mode,
    emit_diagnostic_fn=_emit_diagnostic_fn,
  )
  if budget is not None:
    driver_kwargs["budget"] = int(budget)

  return SessionDriver(**driver_kwargs)


# ---------------------------------------------------------------------------
# Failure-path helper (item D from step 8 design discussion)
# ---------------------------------------------------------------------------

def driver_run_with_audit_wrapper(
  *,
  driver: SessionDriver,
  conn=None,
) -> Any:
  """Run ``driver.run()`` inside a structured failure-handler.

  On unhandled exception:
    1. Attempt to write a META_ESCALATED row to post_intake_
       restructuring_log with the exception type+message in
       veto_reason. The audit write is BEST-EFFORT — wrapped in its
       own try/except; on audit failure, logs to stderr but does NOT
       swallow the original exception.
    2. ALWAYS re-raise as a structured RuntimeError with prefix
       ``amalgamated_session_failed_catastrophically:`` so callers
       have a stable error code to match against. The original
       exception is preserved via ``raise ... from``.

  Per spec discussion item D — both behaviors visible in the code
  from day one; not a tack-on.
  """
  try:
    return driver.run()
  except Exception as session_exc:
    try:
      log_restructure(
        conn,
        draft_id=driver.state.draft_id,
        planning_run_id=driver.state.planning_run_id,
        failure_mode=FailureMode.META_INVARIANT,
        cascade_tier="--",
        cascade_tier_name="session_exception",
        reason_code=ReasonCode.META_ESCALATED,
        section="protocol",
        step_type=StepType.META,
        applied_by=AppliedBy.META_ESCALATION,
        veto_reason=(
          f"{type(session_exc).__name__}: {str(session_exc)[:480]}"
        ),
        evaluate_plan_round=getattr(driver.state, "evaluate_plan_round", 0),
      )
    except Exception as audit_exc:
      print(
        f"amalgamated_session_audit_write_failed: "
        f"{type(audit_exc).__name__}: {audit_exc}",
        file=sys.stderr,
      )
    raise RuntimeError(
      f"amalgamated_session_failed_catastrophically: "
      f"{type(session_exc).__name__}: {str(session_exc)[:300]}"
    ) from session_exc


__all__ = [
  "make_session_driver",
  "driver_run_with_audit_wrapper",
]
