"""SessionDriver — the §12 state machine.

The session driver composes every other piece of the protocol:

  - The mirror (per-decision context object).
  - ``evaluate_plan`` (the standards check).
  - ``cascades.py`` (per-mode tiered policy).
  - ``restructure_proposer`` (Python proposal builders).
  - ``response_tools`` (the four structured GPT responses).
  - ``floor`` (deterministic floor + §9.2 primitives).
  - ``revise_*`` tools (partial-patch authoring).
  - ``restructuring_log`` (audit row writer).

The driver does NOT call GPT directly. It exposes proposals via the
§6.3 templates and receives ProposalResponse records via a ``responder``
callback. Production wiring (lands after step 5/6 alongside the
amalgamated session loop) supplies a responder that round-trips through
the OpenAI tool-calling API; tests inject fakes.

State machine summary (spec §12):

  ROUND_1_AUTHORING -> EVALUATE -> DISPATCH (mode priority §7.1)
    - all_pass: FINALIZE
    - META failing: META_HALT -> FLOOR_AS_IS -> EXIT
    - failures: CASCADE (smart entry, tiers 1..N-1, bound relaxation)
      - resolved: re-EVALUATE
      - exhausted: FLOOR (mode) -> re-EVALUATE
    - PROGRESS_CHECK after each cascade:
      - 2× no-progress: STAGNATION_FLOOR_ALL -> EXIT
      - budget at floor threshold: BUDGET_EXHAUSTED_FLOOR -> EXIT
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (
  EvaluatePlanResult,
  FailureMode,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
  CascadeTier,
  BOUND_RELAXATION_CUMULATIVE_CAP,
  BOUND_RELAXATION_MAX_ATTEMPTS,
  BUDGET_AWARE_THRESHOLD,
  BUDGET_FLOOR_THRESHOLD,
  DEFAULT_TOOL_CALL_BUDGET,
  MAX_CONSECUTIVE_NO_PROGRESS,
  MODE_PRIORITY,
  PROGRESS_THRESHOLD_FRACTION,
  get_cascade,
  next_tier,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.floor import (
  FloorResult,
  apply_floor_primitive,
  floor_for_mode,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (
  AppliedBy,
  ReasonCode,
  StepType,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (
  ProposalResponse,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.restructure_proposer import (
  Proposal,
  propose_for_tier,
)
# Step 9b diagnostics — closed enums for the post_intake_run_
# diagnostics event stream. The driver uses these to tag every state
# transition emit.
from client_intake_and_finmo.post_intake_diagnostics.phase_codes import (
  EventCode,
  PhaseCode,
  Status,
)


# ---------------------------------------------------------------------------
# Termination states (spec §8.8)
# ---------------------------------------------------------------------------

class TerminationState:
  RESOLVED                  = "RESOLVED"
  MODE_FLOOR                = "MODE_FLOOR"
  STAGNATION_FLOOR_ALL      = "STAGNATION_FLOOR_ALL"
  META_HALTED               = "META_HALTED"
  BUDGET_EXHAUSTED_FLOOR    = "BUDGET_EXHAUSTED_FLOOR"


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

@dataclass
class SessionState:
  draft_id: str
  planning_run_id: str
  tool_call_budget_remaining: int = DEFAULT_TOOL_CALL_BUDGET
  current_tier_by_mode: Dict[FailureMode, Optional[str]] = dc_field(default_factory=dict)
  bound_relaxations_by_band: Dict[str, int] = dc_field(default_factory=dict)
  consecutive_no_progress: int = 0
  last_worst_distance: Optional[float] = None
  last_failing_check_count: Optional[int] = None
  evaluate_plan_round: int = 0
  budget_aware: bool = False

  def consume_budget(self) -> None:
    if self.tool_call_budget_remaining > 0:
      self.tool_call_budget_remaining -= 1
    if self.tool_call_budget_remaining <= BUDGET_AWARE_THRESHOLD:
      self.budget_aware = True


@dataclass
class SessionResult:
  termination_state: str
  evaluate_plan_round_count: int
  budget_remaining: int
  applied_steps: int
  floor_invocations: int
  termination_detail: str = ""


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

class SessionDriver:
  """Walks the §12 state machine. Composition root for the protocol.

  Callable seams (all keyword-only at construction time):

    - ``evaluate_plan_fn(round_number) -> EvaluatePlanResult``
      Runs ``evaluate_plan`` and returns the new diagnostic state.
    - ``responder(proposal_or_options) -> ProposalResponse``
      Returns GPT's response (or floor default during unattended walks).
    - ``revise_fn_for_section(section) -> callable``
      Returns the appropriate ``revise_*`` tool for a section. The
      driver calls it with ``(current, patch, **passthrough)``.
    - ``log_fn(entry)`` writes one ``restructuring_log`` row.
    - ``current_payload_for(section)`` returns the current committed
      contract/payload/anchors for a section (from mirror.plan_state).
  """

  def __init__(
    self, *,
    draft_id: str,
    planning_run_id: str,
    evaluate_plan_fn: Callable[..., EvaluatePlanResult],
    responder: Callable[..., ProposalResponse],
    revise_fn_for_section: Callable[..., Optional[Callable[..., Dict[str, Any]]]],
    log_fn: Optional[Callable[..., Any]] = None,
    current_payload_for: Optional[Callable[[str], Any]] = None,
    primitive_kwargs_for_mode: Optional[Callable[[FailureMode], Dict[str, Any]]] = None,
    emit_diagnostic_fn: Optional[Callable[..., Any]] = None,
    budget: int = DEFAULT_TOOL_CALL_BUDGET,
  ) -> None:
    self.state = SessionState(
      draft_id=draft_id,
      planning_run_id=planning_run_id,
      tool_call_budget_remaining=budget,
    )
    self._evaluate_plan_fn = evaluate_plan_fn
    self._responder = responder
    self._revise_fn_for_section = revise_fn_for_section
    self._log_fn = log_fn or (lambda **kw: None)
    self._current_payload_for = current_payload_for or (lambda s: None)
    self._primitive_kwargs_for_mode = primitive_kwargs_for_mode or (lambda m: {})
    # Step 9b — diagnostic emitter for state transitions. The factory
    # binds this to post_intake_run_diagnostics.emit_diagnostic with
    # conn/draft_id/planning_run_id closure-captured; tests pass a
    # recorder fake. When None, emissions are silently dropped (a
    # no-op preserves driver behavior for code paths that don't yet
    # wire diagnostics).
    self._emit_diagnostic_fn = emit_diagnostic_fn or (lambda **kw: None)
    self._applied_steps = 0
    self._floor_invocations = 0
    self._last_result: Optional[EvaluatePlanResult] = None

  # --- diagnostic emit helper (Step 9b) ---------------------------------

  def _emit(
    self,
    *,
    phase: PhaseCode,
    event_code: EventCode,
    status: Status = Status.COMPLETED,
    diagnostic_data: Optional[Dict[str, Any]] = None,
  ) -> None:
    """Best-effort diagnostic emit. The factory wires
    emit_diagnostic_fn to post_intake_diagnostics.emit_diagnostic with
    conn/draft_id/planning_run_id closure-bound; tests pass a fake.
    Swallows exceptions so observability never breaks the driver."""
    try:
      self._emit_diagnostic_fn(
        phase=phase, event_code=event_code, status=status,
        diagnostic_data=diagnostic_data,
      )
    except Exception:
      pass

  # --- top-level entry --------------------------------------------------

  def run(self) -> SessionResult:
    """Walk the state machine to a terminal state. Returns a SessionResult."""
    self.state.consecutive_no_progress = 0
    while True:
      result = self._evaluate()
      if self._meta_failing(result):
        return self._meta_halt(result)
      if result.all_pass:
        return self._terminate(TerminationState.RESOLVED, result)
      mode = self._pick_next_failing_mode(result)
      if mode is None:
        return self._terminate(TerminationState.RESOLVED, result)
      self._emit(
        phase=PhaseCode.CASCADE_WALK,
        event_code=EventCode.CASCADE_ENTERED,
        status=Status.STARTED,
        diagnostic_data={"mode": mode.value, "round_number": self.state.evaluate_plan_round},
      )

      pre_distance = result.worst_failing_distance
      pre_count    = self._failing_count(result)

      cascade_outcome = self._walk_cascade(mode, result)
      post_result = cascade_outcome.get("post_result", result)

      progress = self._made_progress(pre_distance, pre_count, post_result)
      if progress:
        self.state.consecutive_no_progress = 0
      else:
        self.state.consecutive_no_progress += 1

      if self.state.consecutive_no_progress >= MAX_CONSECUTIVE_NO_PROGRESS:
        return self._floor_all(post_result, ReasonCode.STAGNATION_FLOOR_ALL,
                               TerminationState.STAGNATION_FLOOR_ALL)
      if self.state.tool_call_budget_remaining <= BUDGET_FLOOR_THRESHOLD:
        return self._floor_all(post_result, ReasonCode.BUDGET_EXHAUSTED_FLOOR,
                               TerminationState.BUDGET_EXHAUSTED_FLOOR)

  # --- cascade walk -----------------------------------------------------

  def _walk_cascade(
    self, mode: FailureMode, result: EvaluatePlanResult,
  ) -> Dict[str, Any]:
    """Walk a single mode's cascade until resolved / exhausted / budget-floor.

    Returns ``{"post_result": EvaluatePlanResult, "outcome": str}`` where
    outcome is "resolved" | "exhausted" | "floor_applied".
    """
    self.state.current_tier_by_mode.setdefault(mode, None)
    current = next_tier(mode, self.state.current_tier_by_mode[mode])
    while current is not None:
      if current.is_floor:
        floor_res = self._invoke_floor_for_mode(mode)
        self._floor_invocations += 1
        post = self._evaluate()
        return {"post_result": post, "outcome": "floor_applied",
                "floor_result": floor_res}

      proposal = propose_for_tier(mode, current, result)
      if proposal is None:
        # Smart entry: every lever pinned. Advance to next tier.
        self._emit(
          phase=PhaseCode.CASCADE_WALK,
          event_code=EventCode.CASCADE_SMART_ENTRY_SKIPPED,
          status=Status.SKIPPED,
          diagnostic_data={"mode": mode.value, "tier_id": current.tier_id,
                           "tier_name": current.name},
        )
        self.state.current_tier_by_mode[mode] = current.tier_id
        current = next_tier(mode, current.tier_id)
        continue

      self._emit(
        phase=PhaseCode.CASCADE_WALK,
        event_code=EventCode.CASCADE_TIER_WALKED,
        status=Status.STARTED,
        diagnostic_data={"mode": mode.value, "tier_id": current.tier_id,
                         "tier_name": current.name,
                         "step_type": current.step_type.value},
      )
      apply_outcome = self._apply_tier(mode, current, proposal)
      self.state.current_tier_by_mode[mode] = current.tier_id

      if apply_outcome.get("re_evaluate"):
        result = self._evaluate()
        if not self._mode_failing(mode, result):
          self._emit(
            phase=PhaseCode.CASCADE_WALK,
            event_code=EventCode.CASCADE_RESOLVED,
            status=Status.COMPLETED,
            diagnostic_data={"mode": mode.value,
                             "resolved_at_tier": current.tier_id},
          )
          return {"post_result": result, "outcome": "resolved"}

      if self.state.tool_call_budget_remaining <= BUDGET_FLOOR_THRESHOLD:
        floor_res = self._invoke_floor_for_mode(mode)
        self._floor_invocations += 1
        post = self._evaluate()
        return {"post_result": post, "outcome": "floor_applied",
                "floor_result": floor_res}

      current = next_tier(mode, current.tier_id)

    self._emit(
      phase=PhaseCode.CASCADE_WALK,
      event_code=EventCode.CASCADE_EXHAUSTED,
      status=Status.COMPLETED,
      diagnostic_data={"mode": mode.value},
    )
    return {"post_result": result, "outcome": "exhausted"}

  # --- per-tier apply ---------------------------------------------------

  def _apply_tier(
    self,
    mode: FailureMode,
    tier: CascadeTier,
    proposal_or_options: Union[Proposal, List[Proposal]],
  ) -> Dict[str, Any]:
    """Apply one tier — present to responder, dispatch on response,
    write the audit row, optionally invoke revise_* to actually mutate.

    Returns ``{"re_evaluate": bool, "applied": bool, "row_id": Optional[int]}``.
    """
    # §8.7 budget-aware mode: skip the responder for Type A tiers and
    # auto-confirm the Python proposal. Type B tiers still consult GPT
    # because the choice is a real business judgment — that's why
    # Type B exists.
    if self.state.budget_aware and tier.step_type == StepType.TYPE_A:
      chosen = _first(proposal_or_options)
      self.state.consume_budget()
      return self._commit_proposal(
        mode, tier, chosen,
        applied_by=AppliedBy.BUDGET_AWARE_AUTO_CONFIRM,
      )

    response: ProposalResponse = self._responder(
      mode=mode, tier=tier, proposal_or_options=proposal_or_options,
      state=self.state,
    )
    self.state.consume_budget()

    tier_diag = {"mode": mode.value, "tier_id": tier.tier_id,
                 "tier_name": tier.name}

    if response.kind == "veto" and response.validated:
      self._log(
        proposal=_first(proposal_or_options),
        applied_by=AppliedBy.AMALGAMATED_GPT_VETOED,
        applied_value=None,
        veto_reason=response.reason or "",
      )
      self._emit(
        phase=PhaseCode.CASCADE_WALK,
        event_code=EventCode.CASCADE_PROPOSAL_VETOED,
        diagnostic_data={**tier_diag, "veto_reason": (response.reason or "")[:480]},
      )
      return {"re_evaluate": False, "applied": False, "row_id": None}

    if response.kind == "confirm" and response.validated:
      chosen = _first(proposal_or_options)
      self._emit(
        phase=PhaseCode.CASCADE_WALK,
        event_code=EventCode.CASCADE_PROPOSAL_CONFIRMED,
        diagnostic_data={**tier_diag,
                         "section": getattr(chosen, "section", None),
                         "field": getattr(chosen, "field", None),
                         "proposed_value": getattr(chosen, "proposed_value", None)},
      )
      return self._commit_proposal(mode, tier, chosen,
                                   applied_by=AppliedBy.AMALGAMATED_GPT_CONFIRMED)

    if response.kind == "choose" and response.validated:
      options = _as_list(proposal_or_options)
      chosen = next((o for o in options if o.option_id == response.option_id), None)
      if chosen is None:
        return {"re_evaluate": False, "applied": False, "row_id": None}
      self._emit(
        phase=PhaseCode.CASCADE_WALK,
        event_code=EventCode.CASCADE_PROPOSAL_CHOSEN,
        diagnostic_data={**tier_diag, "option_id": response.option_id,
                         "section": chosen.section,
                         "field": chosen.field,
                         "proposed_value": chosen.proposed_value},
      )
      return self._commit_proposal(mode, tier, chosen,
                                   applied_by=AppliedBy.AMALGAMATED_GPT_CHOSE)

    if response.kind == "other":
      if not response.validated:
        # Treat as veto (response_tools validation failed).
        self._log(
          proposal=_first(proposal_or_options),
          applied_by=AppliedBy.AMALGAMATED_GPT_OTHER_OUT_BAND,
          applied_value=None,
          veto_reason=";".join(e["code"] for e in response.validation_errors)[:512],
        )
        self._emit(
          phase=PhaseCode.CASCADE_WALK,
          event_code=EventCode.CASCADE_PROPOSAL_OUT_OF_BAND,
          diagnostic_data={**tier_diag,
                           "validation_errors": [e.get("code") for e in response.validation_errors]},
        )
        return {"re_evaluate": False, "applied": False, "row_id": None}
      synthetic = Proposal(
        mode=mode, tier_id=tier.tier_id, tier_name=tier.name,
        step_type=tier.step_type, reason_code=tier.reason_code,
        section=response.section or "*",
        field=response.field or "*",
        proposed_value=response.value,
        rationale_text=response.reason or "",
      )
      self._emit(
        phase=PhaseCode.CASCADE_WALK,
        event_code=EventCode.CASCADE_PROPOSAL_OTHER,
        diagnostic_data={**tier_diag,
                         "section": response.section, "field": response.field,
                         "proposed_value": response.value,
                         "reason": (response.reason or "")[:200]},
      )
      return self._commit_proposal(mode, tier, synthetic,
                                   applied_by=AppliedBy.AMALGAMATED_GPT_OTHER)

    # No structured response — treat as veto, advance (spec §6.4).
    self._log(
      proposal=_first(proposal_or_options),
      applied_by=AppliedBy.AMALGAMATED_GPT_VETOED,
      applied_value=None,
      veto_reason="no_structured_response",
    )
    self._emit(
      phase=PhaseCode.CASCADE_WALK,
      event_code=EventCode.CASCADE_PROPOSAL_VETOED,
      diagnostic_data={**tier_diag, "veto_reason": "no_structured_response"},
    )
    return {"re_evaluate": False, "applied": False, "row_id": None}

  def _commit_proposal(
    self, mode: FailureMode, tier: CascadeTier, proposal: Proposal,
    *, applied_by: AppliedBy,
  ) -> Dict[str, Any]:
    """Apply ``proposal`` via the section's revise_* tool and log."""
    revise_fn = self._revise_fn_for_section(proposal.section)
    accepted = False
    applied_value: Optional[float] = None
    if revise_fn is None:
      # Section has no registered revise_* (e.g. operating_model levers
      # via stage_ramp tools); log as confirmed but not applied here.
      # Floor-as-walker paths will pick this up via primitives instead.
      pass
    else:
      current = self._current_payload_for(proposal.section)
      patch = _patch_from_proposal(proposal)
      try:
        envelope = revise_fn(current=current, patch=patch, proposal=proposal)
      except TypeError:
        envelope = revise_fn(proposal=proposal)
      if isinstance(envelope, dict) and envelope.get("accepted"):
        accepted = True
        applied_value = proposal.proposed_value
        self._applied_steps += 1
    row_id = self._log(
      proposal=proposal,
      applied_by=applied_by,
      applied_value=applied_value if accepted else None,
    )
    return {"re_evaluate": accepted, "applied": accepted, "row_id": row_id}

  # --- floor ------------------------------------------------------------

  def _invoke_floor_for_mode(self, mode: FailureMode) -> FloorResult:
    """Route through floor_for_mode so the §9.1 cascade-as-floor walker
    runs before the §9.2 primitive (per spec §9: same machinery,
    unattended; primitive only fires if the unattended walk doesn't
    resolve the mode)."""
    self._emit(
      phase=PhaseCode.FLOOR_INVOCATION,
      event_code=EventCode.FLOOR_WALKER_ENTERED,
      status=Status.STARTED,
      diagnostic_data={"mode": mode.value},
    )
    res = floor_for_mode(
      mode,
      cascade_walker=self._unattended_cascade_pass,
      primitive_kwargs=self._primitive_kwargs_for_mode(mode),
    )
    for step in res.steps:
      self._log_floor_step(mode, step)
      self._emit(
        phase=PhaseCode.FLOOR_INVOCATION,
        event_code=EventCode.FLOOR_PRIMITIVE_APPLIED,
        diagnostic_data={"mode": mode.value, "section": step.section,
                         "field": step.field,
                         "applied_value": step.applied_value,
                         "reason_code": step.reason_code.value},
      )
    self._emit(
      phase=PhaseCode.FLOOR_INVOCATION,
      event_code=(
        EventCode.FLOOR_WALKER_RESOLVED if res.status == "resolved"
        else EventCode.FLOOR_COMPLETED
      ),
      status=Status.COMPLETED,
      diagnostic_data={"mode": mode.value, "floor_status": res.status,
                       "step_count": len(res.steps)},
    )
    return res

  def _unattended_cascade_pass(self, *, mode: FailureMode) -> FloorResult:
    """Walk the cascade unattended with Python defaults at every step.

    Spec §9.1 step 1: Type A auto-confirmed, Type B picks option A
    (the first option in priority order — least-disruptive per the
    cascade tables). Each commit goes through the same revise_* tools
    the GPT-driven cascade uses. After each commit re-evaluate; if the
    mode now passes, return status='resolved' so floor_for_mode skips
    the §9.2 primitive.
    """
    floor_steps: List[Any] = []
    self.state.current_tier_by_mode.setdefault(mode, None)
    current = next_tier(mode, None)
    result = self._evaluate()
    while current is not None and not current.is_floor:
      proposal = propose_for_tier(mode, current, result)
      if proposal is None:
        current = next_tier(mode, current.tier_id)
        continue
      chosen = _first(proposal)
      outcome = self._commit_proposal(
        mode, current, chosen, applied_by=AppliedBy.DETERMINISTIC_FLOOR,
      )
      if outcome.get("re_evaluate"):
        result = self._evaluate()
        if not self._mode_failing(mode, result):
          return FloorResult(
            mode=mode, status="resolved", steps=floor_steps,
            detail=f"cascade-as-floor resolved at {current.tier_id}",
          )
      current = next_tier(mode, current.tier_id)
    return FloorResult(
      mode=mode, status="exhausted", steps=floor_steps,
      detail="cascade-as-floor exhausted; primitive will fire",
    )

  def _floor_all(
    self, result: EvaluatePlanResult,
    meta_reason: ReasonCode,
    termination: str,
  ) -> SessionResult:
    """Invoke primitives for every still-failing restructurable mode and
    record a META row with the meta_reason. Exit with the named
    termination state."""
    # Log the META row first so the audit ordering is clear.
    self._log_meta(meta_reason, detail=termination)
    for mode in MODE_PRIORITY:
      if self._mode_failing(mode, result):
        res = self._invoke_floor_for_mode(mode)
        self._floor_invocations += 1
    return self._terminate(termination, result, detail=meta_reason.value)

  def _meta_halt(self, result: EvaluatePlanResult) -> SessionResult:
    self._log_meta(ReasonCode.META_ESCALATED, detail="meta_check_failed")
    return self._terminate(TerminationState.META_HALTED, result,
                           detail="META check failed")

  # --- evaluation + diagnostics ----------------------------------------

  def _evaluate(self) -> EvaluatePlanResult:
    self.state.evaluate_plan_round += 1
    self._emit(
      phase=PhaseCode.EVALUATE_PLAN,
      event_code=EventCode.EVALUATE_PLAN_STARTED,
      status=Status.STARTED,
      diagnostic_data={"round_number": self.state.evaluate_plan_round},
    )
    result = self._evaluate_plan_fn(round_number=self.state.evaluate_plan_round)
    self.state.last_worst_distance = result.worst_failing_distance
    self.state.last_failing_check_count = self._failing_count(result)
    self._last_result = result
    self.state.consume_budget()
    failing_count = self._failing_count(result)
    self._emit(
      phase=PhaseCode.EVALUATE_PLAN,
      event_code=(
        EventCode.EVALUATE_PLAN_ALL_PASS if result.all_pass
        else EventCode.EVALUATE_PLAN_FAILURES_DETECTED
      ),
      status=Status.COMPLETED,
      diagnostic_data={
        "round_number": self.state.evaluate_plan_round,
        "all_pass": bool(result.all_pass),
        "failing_check_count": failing_count,
        "worst_failing_check": result.worst_failing_check,
        "worst_failing_distance": result.worst_failing_distance,
      },
    )
    return result

  @staticmethod
  def _failing_count(result: EvaluatePlanResult) -> int:
    return sum(1 for c in result.checks if not c.passed)

  @staticmethod
  def _meta_failing(result: EvaluatePlanResult) -> bool:
    for c in result.checks:
      if not c.passed and c.failure_mode == FailureMode.META_INVARIANT:
        return True
    return False

  @staticmethod
  def _mode_failing(mode: FailureMode, result: EvaluatePlanResult) -> bool:
    return any(
      (not c.passed) and c.failure_mode == mode for c in result.checks
    )

  @staticmethod
  def _pick_next_failing_mode(result: EvaluatePlanResult) -> Optional[FailureMode]:
    for mode in MODE_PRIORITY:
      if SessionDriver._mode_failing(mode, result):
        return mode
    return None

  @staticmethod
  def _made_progress(
    pre_distance: Optional[float],
    pre_count: int,
    post: EvaluatePlanResult,
  ) -> bool:
    post_count = SessionDriver._failing_count(post)
    if post_count < pre_count:
      return True
    post_distance = post.worst_failing_distance
    if pre_distance is None or post_distance is None:
      return False
    pre_mag  = abs(pre_distance)
    post_mag = abs(post_distance)
    if pre_mag <= 0:
      return False
    improvement = (pre_mag - post_mag) / pre_mag
    return improvement >= PROGRESS_THRESHOLD_FRACTION

  # --- logging helpers --------------------------------------------------

  def _log(
    self, *, proposal: Optional[Proposal],
    applied_by: AppliedBy,
    applied_value: Optional[float] = None,
    veto_reason: Optional[str] = None,
  ) -> Optional[int]:
    if proposal is None:
      return None
    return self._log_fn(
      draft_id=self.state.draft_id,
      planning_run_id=self.state.planning_run_id,
      failure_mode=proposal.mode,
      cascade_tier=proposal.tier_id,
      cascade_tier_name=proposal.tier_name,
      reason_code=proposal.reason_code,
      section=proposal.section,
      field=proposal.field,
      original_value=proposal.current_value,
      proposed_value=proposal.proposed_value,
      applied_value=applied_value,
      step_type=proposal.step_type,
      applied_by=applied_by,
      veto_reason=veto_reason,
      evaluate_plan_round=self.state.evaluate_plan_round,
    )

  def _log_floor_step(self, mode: FailureMode, step: Any) -> None:
    self._log_fn(
      draft_id=self.state.draft_id,
      planning_run_id=self.state.planning_run_id,
      failure_mode=mode,
      cascade_tier=step.tier_id,
      cascade_tier_name=step.tier_name,
      reason_code=step.reason_code,
      section=step.section,
      field=step.field,
      applied_value=step.applied_value,
      step_type=step.step_type,
      applied_by=step.applied_by,
      evaluate_plan_round=self.state.evaluate_plan_round,
    )

  def _log_meta(self, reason: ReasonCode, *, detail: str = "") -> None:
    self._log_fn(
      draft_id=self.state.draft_id,
      planning_run_id=self.state.planning_run_id,
      failure_mode=FailureMode.META_INVARIANT,
      cascade_tier="--",
      cascade_tier_name=detail or reason.value,
      reason_code=reason,
      section="protocol",
      step_type=StepType.META,
      applied_by=AppliedBy.META_ESCALATION,
      evaluate_plan_round=self.state.evaluate_plan_round,
    )

  def _terminate(
    self, state: str, result: EvaluatePlanResult, *, detail: str = "",
  ) -> SessionResult:
    # Step 9b — emit a session_terminated row tagged with the
    # terminal state so observability captures the exit reason.
    state_to_event = {
      TerminationState.RESOLVED:               EventCode.SESSION_RESOLVED,
      TerminationState.MODE_FLOOR:             EventCode.SESSION_FLOOR_ALL,
      TerminationState.STAGNATION_FLOOR_ALL:   EventCode.SESSION_FLOOR_ALL,
      TerminationState.META_HALTED:            EventCode.SESSION_META_HALTED,
      TerminationState.BUDGET_EXHAUSTED_FLOOR: EventCode.SESSION_BUDGET_EXHAUSTED,
    }
    event = state_to_event.get(state, EventCode.SESSION_RESOLVED)
    self._emit(
      phase=PhaseCode.SESSION_TERMINATED,
      event_code=event,
      status=(Status.COMPLETED if state == TerminationState.RESOLVED
              else Status.FAILED),
      diagnostic_data={
        "termination_state": state,
        "evaluate_plan_round_count": self.state.evaluate_plan_round,
        "budget_remaining": self.state.tool_call_budget_remaining,
        "applied_steps": self._applied_steps,
        "floor_invocations": self._floor_invocations,
        "termination_detail": detail or None,
      },
    )
    return SessionResult(
      termination_state=state,
      evaluate_plan_round_count=self.state.evaluate_plan_round,
      budget_remaining=self.state.tool_call_budget_remaining,
      applied_steps=self._applied_steps,
      floor_invocations=self._floor_invocations,
      termination_detail=detail,
    )

  # --- finalize_authoring ------------------------------------------------

  def finalize_authoring(self) -> Dict[str, Any]:
    """Spec §3.3 finalize_authoring — declare the session done.

    Allowed only when the most recent ``evaluate_plan`` returned
    ``all_pass=True`` OR the protocol terminated in a floor state
    (FLOOR-state plans are committed, in-bounds, viable-in-the-floor's-
    sense per doctrine §10.6). Returns ``{"accepted": bool, "reason":
    str|None}``.

    Wrapped as a free-standing helper too (``finalize_authoring`` below)
    so callers outside a live SessionDriver can validate the same
    pre-condition against an EvaluatePlanResult.
    """
    last = self._last_result
    if last is None:
      return {"accepted": False,
              "reason": "no evaluate_plan result yet; cannot finalize"}
    return finalize_authoring(last)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _first(proposal_or_options: Union[Proposal, List[Proposal]]) -> Optional[Proposal]:
  if proposal_or_options is None:
    return None
  if isinstance(proposal_or_options, list):
    return proposal_or_options[0] if proposal_or_options else None
  return proposal_or_options


def _as_list(proposal_or_options: Union[Proposal, List[Proposal]]) -> List[Proposal]:
  if isinstance(proposal_or_options, list):
    return proposal_or_options
  return [proposal_or_options] if proposal_or_options is not None else []


# P3.33 Phase 3 pre-step-8 — WC scalar lever_ids owned by the
# balance_sheet section. The patch shape revise_capex_rd_balance_seed
# expects routes WC overrides under the "working_capital_days" sub-key
# of its overrides dict (matches set_capex_rd_balance_seed's
# _apply_wc_overrides input shape).
_WC_SCALAR_BALANCE_SHEET_LEVERS = frozenset({
  "balance_sheet::Accounts Receivable Days",
  "balance_sheet::Accounts Payable Days",
  "balance_sheet::Inventory Days",
})


def _patch_from_proposal(proposal: Proposal) -> Dict[str, Any]:
  """Turn a Proposal into a sparse patch dict the revise_* tools accept.

  Section shapes:
    - ``drivers``: P&L levers (COGS, R&D, G&A, Marketing) emit a
      per-anchor dict ``{lever_id: {"q1": v, "q11": v, "q20": v}}``.
    - ``balance_sheet``: WC days (AR/AP/Inventory) emit a nested patch
      ``{"working_capital_days": {lever_id: v}}`` matching the
      revise_capex_rd_balance_seed -> set_capex_rd_balance_seed
      overrides shape.
    - Other sections: flat ``{field: value}``.
  """
  if proposal.section == "drivers":
    return {
      proposal.field: {
        "q1":  proposal.proposed_value,
        "q11": proposal.proposed_value,
        "q20": proposal.proposed_value,
      },
    }
  if (proposal.section == "balance_sheet"
      and proposal.field in _WC_SCALAR_BALANCE_SHEET_LEVERS):
    return {"working_capital_days": {proposal.field: proposal.proposed_value}}
  return {proposal.field: proposal.proposed_value}


def finalize_authoring(result: EvaluatePlanResult) -> Dict[str, Any]:
  """Spec §3.3 finalize_authoring — validate that authoring is allowed
  to declare done.

  Allowed when ``result.all_pass == True``. Returns:
    {"accepted": True,  "reason": None}        if all_pass
    {"accepted": False, "reason": "<detail>"}  otherwise (with the
    failing-check count + worst-failing-check name when present).

  The session driver's terminal state (FLOOR-equivalent terminations
  like STAGNATION_FLOOR_ALL / BUDGET_EXHAUSTED_FLOOR / META_HALTED)
  is the alternate finalize path — those commit an in-bounds plan
  via the floor primitives and exit the session; ``finalize_authoring``
  is the GPT-driven "I'm done" check the responder uses while the
  cascade is still running.
  """
  if result is None:
    return {"accepted": False,
            "reason": "no evaluate_plan result supplied"}
  if result.all_pass:
    return {"accepted": True, "reason": None}
  failing = sum(1 for c in result.checks if not c.passed)
  worst = result.worst_failing_check or "(unknown)"
  return {
    "accepted": False,
    "reason": (
      f"evaluate_plan still failing: {failing} check(s), worst "
      f"= {worst} (distance {result.worst_failing_distance!r}). "
      "finalize_authoring requires all_pass=True (spec §3.3)."
    ),
  }


__all__ = [
  "TerminationState",
  "SessionState",
  "SessionResult",
  "SessionDriver",
  "finalize_authoring",
]
