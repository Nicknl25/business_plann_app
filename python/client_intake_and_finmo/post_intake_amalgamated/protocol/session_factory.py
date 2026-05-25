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

import sys
from typing import Any, Callable, Dict, Optional

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

  table: Dict[str, Callable[..., Dict[str, Any]]] = {
    "drivers":               _drivers,
    "stage_ramp":            _stage_ramp,
    "payroll":               _payroll,
    "balance_sheet":         _balance_sheet,
    "capex_rd":              _balance_sheet,
    "capex_rd_balance_seed": _balance_sheet,
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


def _build_evaluate_plan_fn(
  *,
  conn,
  draft_id: str,
  planning_run_id: str,
  mirror: Mirror,
  operating_context: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
) -> Callable[..., EvaluatePlanResult]:
  """Wrap evaluate_plan with the orchestrator-side inputs already known
  at session-entry time. The driver calls evaluate_plan_fn(round_number=N)
  and expects an EvaluatePlanResult back."""
  from client_intake_and_finmo.post_intake_amalgamated.evaluate_plan import (
    evaluate_plan,
  )

  def evaluate_plan_fn(*, round_number: int) -> EvaluatePlanResult:
    # The mirror is the live plan_state source; evaluate_plan re-reads
    # plan_state from the mirror so it sees the most-recent revisions.
    return evaluate_plan(
      conn=conn,
      draft_id=draft_id,
      planning_run_id=planning_run_id,
      plan_state=dict(mirror.plan_state) if isinstance(mirror.plan_state, dict) else {},
      structural_completeness=True,
      round_number=int(round_number),
      anchors=None,
      operating_context=operating_context,
      finmo_json=finmo_json,
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

  evaluate_plan_fn = _build_evaluate_plan_fn(
    conn=conn, draft_id=draft_id, planning_run_id=planning_run_id,
    mirror=mirror, operating_context=operating_context,
    finmo_json=finmo_json,
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
  def apply_to_plan_state_fn(section: str, payload: Any) -> None:
    mirror.set_plan_state_section(section, payload)
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
