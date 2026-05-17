"""Iter 19 Stage 4 correction — Funding handler tool-calling session.

GPT-driven funding correction loop. Mirrors the exhaustion handler's
two-phase budget + verified-commit-candidate model
(post_intake_gpt_exhaustion_handler/tool_calling_session.py):

  - INITIAL_TOOL_CALL_BUDGET = 8; EXTENSION_TOOL_CALLS = 2;
    HARD_CAP_TOOL_CALLS = 10 (doctrine.md §5).
  - counts_against_run_budget=False on every Responses API call (iter
    17 decoupling).
  - GPT iterates by calling ``compute_cash_trajectory(lever_adjustments)``.
    The tool runs :mod:`mini_finmo` under the hood and returns the
    projected ending_cash + per-quarter buffer residual.
  - The session tracks the most recent tool call where
    ``all_violations_resolved == True`` as ``verified_commit_candidate``.
  - When GPT stops calling the tool or the hard cap is reached, the
    session ends and the system uses the verified candidate's
    ``lever_adjustments`` as the committed plan.
  - If no all-resolved call occurred within the budget, the session
    selects the best-effort record (fewest residual quarters,
    tiebreaker: smallest total residual gap).

The deterministic Python allocator
(:func:`post_intake_funding_handler.handler.run_funding_handler`) is
the FIRST line of defense — when the cash post-pass detects
violations, the handler tries Python allocation first. The GPT loop
in this module engages only when Python alone cannot satisfy the
buffer.

Live API integration is unverified pending end-of-iter E2E sweep.
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)


# Mirrors post_intake_gpt_exhaustion_handler/tool_calling_session.py:50-52
# but kept distinct so future tuning of the funding budget does not
# affect the exhaustion handler.
INITIAL_TOOL_CALL_BUDGET: int = 8
EXTENSION_TOOL_CALLS: int = 2
HARD_CAP_TOOL_CALLS: int = INITIAL_TOOL_CALL_BUDGET + EXTENSION_TOOL_CALLS  # 10
MAX_TOOL_CALLS: int = HARD_CAP_TOOL_CALLS


COUNTS_AGAINST_RUN_BUDGET: bool = False


_TOOL_NAME: str = "compute_cash_trajectory"


# Authority mirrors handler.FUNDING_LEVER_AUTHORITY. The schema must
# accept ONLY these lever_ids as keys; lever-write enforces it too.
_FUNDING_LEVER_ID_ENUM: Tuple[str, ...] = (
  "schedules::Debt Issuance (New Borrowing)",
  "schedules::Debt Repayment (Scheduled)",
  "balance_sheet::Owner's Capital",
  "balance_sheet::Other Equity",
  "balance_sheet::Distributions",
)


def _build_tool_definition() -> Dict[str, Any]:
  """Responses API tool definition for compute_cash_trajectory.

  The tool accepts a ``lever_adjustments`` object: per-funding-lever
  per-quarter signed amounts. Returns the projected cash trajectory
  with per-quarter buffer residual and an ``all_violations_resolved``
  aggregate.

  Lever IDs are enumerated explicitly — schema-level enforcement of
  the handler's defined authority (doctrine.md §5). GPT cannot
  propose authoring a lever outside this set.
  """
  # Responses API strict mode requires every property to appear in
  # ``required``. Quarter values are nullable so GPT can leave any
  # quarter unmodified (null) without omitting the key.
  per_lever_per_quarter = {
    "type": "object",
    "additionalProperties": False,
    "required": [str(q) for q in range(1, 21)],
    "properties": {
      str(q): {"type": ["number", "null"]} for q in range(1, 21)
    },
  }
  return {
    "type": "function",
    "name": _TOOL_NAME,
    "description": (
      "Project the cash trajectory under your proposed funding-lever "
      "adjustments. Each lever is a per-quarter signed amount: "
      "positive = increase the lever; negative = decrease. For "
      "Distributions, a NEGATIVE value pulls back planned distributions "
      "(retaining more cash). The tool returns: projected_quarter_rows "
      "(per-quarter projected_ending_cash + cash_delta_from_adjustments), "
      "buffer_residual_violations (quarters where projected_ending_cash "
      "still falls below the buffer requirement), and "
      "all_violations_resolved (True when no residual). Iterate until "
      "all_violations_resolved is True or until you decide no further "
      "adjustments are safe within the lever_bounds."
    ),
    "strict": True,
    "parameters": {
      "type": "object",
      "additionalProperties": False,
      "required": ["lever_adjustments"],
      "properties": {
        "lever_adjustments": {
          "type": "object",
          "additionalProperties": False,
          "required": list(_FUNDING_LEVER_ID_ENUM),
          "properties": {
            lever_id: per_lever_per_quarter for lever_id in _FUNDING_LEVER_ID_ENUM
          },
        },
      },
    },
  }


# Universal system prompt mirroring the exhaustion handler's prompt
# style. Universal across NAICS / stage / archetype per doctrine.md §1.
SYSTEM_PROMPT: str = (
  "You are advising on funding adjustments for a 20-quarter financial "
  "plan. The Python cash-strategy proposer has produced a funding plan "
  "that trips one or more cash_buffer_violations: ending cash falls "
  "below the per-quarter buffer requirement in those quarters. The "
  "deterministic Python allocator has already attempted a first-pass "
  "correction and could not close every violation within the funding "
  "levers' per-quarter bounds.\n"
  "\n"
  "Your authority is strictly limited to:\n"
  "  - schedules::Debt Issuance (New Borrowing)\n"
  "  - schedules::Debt Repayment (Scheduled)\n"
  "  - balance_sheet::Owner's Capital\n"
  "  - balance_sheet::Other Equity\n"
  "  - balance_sheet::Distributions (negative adjustments only — pulling "
  "back planned distributions to retain cash)\n"
  "\n"
  "You have a tool: compute_cash_trajectory(lever_adjustments). Call it "
  "with proposed per-quarter signed amounts. The tool runs the cash "
  "projection mirror and returns the resulting ending_cash + buffer "
  "residual per quarter, plus all_violations_resolved.\n"
  "\n"
  "Iterate. The system uses your most recent tool call where "
  "all_violations_resolved == True as the committed plan; you do not "
  "issue a separate final-commit JSON.\n"
  "\n"
  "Reason from this specific business's funding posture, cash strategy "
  "mode, and per-quarter lever bounds. The deterministic allocator's "
  "priority order (debt issuance → owner's capital → other equity → "
  "distributions pulldown) is a sound default; your job is to find "
  "non-default allocations that satisfy buffer when the default order "
  "leaves residual gaps."
)


EXTENSION_PROMPT_TEXT: str = (
  "You have used several tool calls without resolving every "
  "cash_buffer_violation. Be more aggressive: consider combining "
  "debt issuance with owner's capital injection AND a "
  "distributions pulldown in the same quarter, or shifting funding "
  "to neighboring quarters when the violation quarter's lever "
  "bounds are tight. The plan must satisfy the buffer; if no "
  "combination works the system will hard-fail with a specific "
  "residual diagnostic."
)


@dataclass
class FundingToolCallRecord:
  """One round of tool invocation in the funding session."""

  call_n: int
  arguments: Dict[str, Any]
  result: Dict[str, Any]
  call_id: str = ""

  def to_dict(self) -> Dict[str, Any]:
    return {
      "call_n": int(self.call_n),
      "call_id": self.call_id,
      "lever_adjustments_summary": _summarize_lever_adjustments(self.arguments),
      "buffer_residual_count": len(
        (self.result or {}).get("buffer_residual_violations") or []
      ),
      "all_violations_resolved": (
        self.result or {}
      ).get("all_violations_resolved"),
      "error": (self.result or {}).get("error"),
    }


@dataclass
class FundingToolCallSessionResult:
  status: str  # "verified" | "best_effort_no_all_resolved" | "failed_precondition"
  final_lever_adjustments: Optional[Dict[str, Any]] = None
  tool_calls_used: int = 0
  tool_call_history: List[FundingToolCallRecord] = field(default_factory=list)
  last_residual_count: Optional[int] = None
  gpt_calls_made: int = 0
  decision_sources: List[str] = field(default_factory=list)
  budget_extension_triggered: bool = False
  detail: str = ""
  verified_commit_call_n: Optional[int] = None
  best_effort_call_n: Optional[int] = None

  def to_dict(self) -> Dict[str, Any]:
    return {
      "status": self.status,
      "tool_calls_used": int(self.tool_calls_used),
      "gpt_calls_made": int(self.gpt_calls_made),
      "last_residual_count": self.last_residual_count,
      "tool_call_history": [r.to_dict() for r in self.tool_call_history],
      "decision_sources": list(self.decision_sources),
      "budget_extension_triggered": bool(self.budget_extension_triggered),
      "verified_commit_call_n": self.verified_commit_call_n,
      "best_effort_call_n": self.best_effort_call_n,
      "detail": self.detail,
    }


def _summarize_lever_adjustments(args: Dict[str, Any]) -> Dict[str, Any]:
  out: Dict[str, Any] = {}
  adjustments = args.get("lever_adjustments") if isinstance(args, dict) else {}
  if not isinstance(adjustments, dict):
    return out
  for lever_id, per_q in adjustments.items():
    if not isinstance(per_q, dict):
      continue
    nonzero = {
      str(q): float(v)
      for q, v in per_q.items()
      if v is not None and float(v) != 0.0
    }
    if nonzero:
      out[lever_id] = nonzero
  return out


def _residual_count(record: "FundingToolCallRecord") -> int:
  residual = (record.result or {}).get("buffer_residual_violations") or []
  return len(residual)


def _total_residual_gap(record: "FundingToolCallRecord") -> float:
  residual = (record.result or {}).get("buffer_residual_violations") or []
  total = 0.0
  for item in residual:
    if not isinstance(item, dict):
      continue
    try:
      total += float(item.get("shortfall") or 0.0)
    except Exception:
      pass
  return total


def _best_effort_record(
  history: List["FundingToolCallRecord"],
) -> Optional["FundingToolCallRecord"]:
  """Pick the tool call with the fewest residual quarters; tiebreaker
  is smallest total residual gap (in dollars). Returns None for empty
  history.
  """
  if not history:
    return None
  def _key(rec: "FundingToolCallRecord") -> Tuple[int, float]:
    return (_residual_count(rec), _total_residual_gap(rec))
  return min(history, key=_key)


def _build_initial_user_prompt(
  *,
  cash_buffer_violations: List[Dict[str, Any]],
  lever_bounds: Dict[str, List[Dict[str, Any]]],
  python_allocator_authored: Dict[str, Dict[int, float]],
  python_allocator_residual: List[Dict[str, Any]],
  cash_strategy_mode: str,
) -> str:
  violations_block = json.dumps(
    cash_buffer_violations or [],
    ensure_ascii=False,
    indent=2,
    default=str,
  )
  bounds_block = json.dumps(
    lever_bounds or {},
    ensure_ascii=False,
    indent=2,
    default=str,
  )
  python_block = json.dumps(
    {
      "authored_lever_changes": {
        lever_id: {str(q): float(v) for q, v in per_q.items()}
        for lever_id, per_q in (python_allocator_authored or {}).items()
      },
      "residual_violations": python_allocator_residual,
    },
    ensure_ascii=False,
    indent=2,
    default=str,
  )
  return (
    "CASH_STRATEGY_MODE:\n"
    f"{cash_strategy_mode or '(unset)'}\n\n"
    "CASH_BUFFER_VIOLATIONS (per-quarter ending_cash vs buffer):\n"
    f"{violations_block}\n\n"
    "PER-QUARTER LEVER_BOUNDS (current / max / min for each funding lever):\n"
    f"{bounds_block}\n\n"
    "PYTHON DETERMINISTIC ALLOCATOR FIRST-PASS RESULT:\n"
    f"{python_block}\n\n"
    "TASK:\n"
    "Author additional funding adjustments so every violation resolves. "
    f"Use the {_TOOL_NAME} tool to verify each proposal. The most "
    "recent tool call where all_violations_resolved == True becomes "
    "the committed plan automatically; you do not produce a separate "
    "final answer."
  )


def run_funding_tool_calling_session(
  *,
  cash_buffer_violations: List[Dict[str, Any]],
  lever_bounds: Optional[Dict[str, List[Dict[str, Any]]]] = None,
  pre_handler_finmo_quarter_rows: Optional[List[Dict[str, Any]]] = None,
  buffer_by_quarter: Optional[Dict[int, float]] = None,
  python_allocator_authored: Optional[Dict[str, Dict[int, float]]] = None,
  python_allocator_residual: Optional[List[Dict[str, Any]]] = None,
  cash_strategy_mode: str = "",
  _call_gpt_turn: Optional[Callable[..., Dict[str, Any]]] = None,
  _projector: Optional[Callable[..., Dict[str, Any]]] = None,
  _residual_checker: Optional[Callable[..., List[Dict[str, Any]]]] = None,
) -> FundingToolCallSessionResult:
  """Run the funding handler's GPT tool-calling session.

  Mirrors :func:`post_intake_gpt_exhaustion_handler.tool_calling_session.run_tool_calling_session`
  in shape:
    - Two-phase budget (8 + 2 = 10 hard cap).
    - Verified-commit-candidate tracking. Most recent
      ``all_violations_resolved`` wins.
    - Best-effort selection on hard cap (fewest residual quarters,
      tiebreaker: smallest total residual gap).
    - Hard-fail under test mode when a GPT turn fails with a
      non-success decision_source.

  The ``_call_gpt_turn``, ``_projector``, and ``_residual_checker``
  parameters are seams for testing. Production callers pass None to
  resolve the real implementations lazily; tests inject mocks.
  """
  bounds = lever_bounds if isinstance(lever_bounds, dict) else {}
  pre_rows = (
    pre_handler_finmo_quarter_rows
    if isinstance(pre_handler_finmo_quarter_rows, list)
    else []
  )
  buffer_map = buffer_by_quarter if isinstance(buffer_by_quarter, dict) else {}

  call_gpt_turn = _call_gpt_turn
  if call_gpt_turn is None:
    from client_intake_and_finmo.post_intake_solver._gpt_critic_io import (  # type: ignore
      call_gpt_responses_api_turn,
    )
    call_gpt_turn = call_gpt_responses_api_turn

  projector = _projector
  if projector is None:
    from client_intake_and_finmo.post_intake_funding_handler.mini_finmo import (  # type: ignore
      project_cash_trajectory_with_adjustments,
    )
    projector = project_cash_trajectory_with_adjustments

  residual_checker = _residual_checker
  if residual_checker is None:
    from client_intake_and_finmo.post_intake_funding_handler.mini_finmo import (  # type: ignore
      buffer_residual_after_adjustments,
    )
    residual_checker = buffer_residual_after_adjustments

  tool_def = _build_tool_definition()
  initial_user_prompt = _build_initial_user_prompt(
    cash_buffer_violations=cash_buffer_violations or [],
    lever_bounds=bounds,
    python_allocator_authored=python_allocator_authored or {},
    python_allocator_residual=python_allocator_residual or [],
    cash_strategy_mode=cash_strategy_mode,
  )

  input_items: List[Dict[str, Any]] = [
    {
      "role": "system",
      "content": [{"type": "input_text", "text": SYSTEM_PROMPT.strip()}],
    },
    {
      "role": "user",
      "content": [{"type": "input_text", "text": initial_user_prompt}],
    },
  ]

  history: List[FundingToolCallRecord] = []
  tool_calls_used = 0
  gpt_calls_made = 0
  decision_sources: List[str] = []
  budget_extension_triggered = False
  verified_commit_candidate: Optional[FundingToolCallRecord] = None
  detail = ""

  # Phase 9 P3.12 — initialize the round-count-drift contextvar.
  from client_intake_and_finmo.post_intake_funding_handler.handler import (  # type: ignore
    _FUNDING_HANDLER_GPT_CALL_COUNT,
    _assert_funding_handler_budget_decoupled,
    _assert_funding_handler_round_count_consistent,
    _assert_funding_handler_state_intact,
    _assert_funding_handler_best_effort_selection_consistent,
  )
  _funding_iter_token = _FUNDING_HANDLER_GPT_CALL_COUNT.set(0)
  try:
    loop_round_index = 0
    while True:
      loop_round_index += 1
      # Machinery invariant #3 — state corruption between rounds.
      _assert_funding_handler_state_intact(
        round_n=loop_round_index,
        input_items=input_items,
        history=history,
        verified_commit_candidate=verified_commit_candidate,
      )

      if (
        tool_calls_used >= INITIAL_TOOL_CALL_BUDGET
        and not budget_extension_triggered
        and verified_commit_candidate is None
      ):
        input_items.append({
          "role": "user",
          "content": [{"type": "input_text", "text": EXTENSION_PROMPT_TEXT}],
        })
        budget_extension_triggered = True

      if tool_calls_used >= HARD_CAP_TOOL_CALLS:
        detail = "hard_cap_tool_calls_reached"
        break

      # Machinery invariant #2 — budget decoupling violation.
      _assert_funding_handler_budget_decoupled(
        round_n=loop_round_index,
        counts_against_run_budget_arg=COUNTS_AGAINST_RUN_BUDGET,
      )

      turn_resp = call_gpt_turn(
        consultant_name=(
          f"post_intake_funding_handler_tool_call_turn_{tool_calls_used + 1}"
        ),
        input_items=input_items,
        tools=[tool_def],
        response_schema=None,
        schema_name=None,
        counts_against_run_budget=COUNTS_AGAINST_RUN_BUDGET,
      )
      _FUNDING_HANDLER_GPT_CALL_COUNT.set(
        _FUNDING_HANDLER_GPT_CALL_COUNT.get() + 1
      )
      gpt_calls_made += 1
      # Machinery invariant #1 — round count drift (post-call). The
      # contextvar should now equal loop_round_index (one GPT call
      # per loop iteration). If they diverge, an inner code path
      # made an extra GPT call the loop didn't account for.
      _assert_funding_handler_round_count_consistent(
        loop_round_index=loop_round_index,
        tool_calls_used=gpt_calls_made,
      )
      decision_sources.append(str(turn_resp.get("decision_source") or ""))

      decision_source = str(turn_resp.get("decision_source") or "")
      if decision_source != "python_proposer_plus_gpt_critic":
        from client_intake_and_finmo.fail_fast.common import (  # type: ignore
          PostIntakePreconditionFailed,
          convergence_test_mode_enabled,
        )
        if convergence_test_mode_enabled():
          raise PostIntakePreconditionFailed(
            operation="funding_handler_tool_calling_session_turn_failed",
            pipeline_stage="iter_19_stage_4_funding_handler",
            expected="decision_source=python_proposer_plus_gpt_critic",
            actual=decision_source,
            details={
              "tool_calls_used_before_failure": int(tool_calls_used),
              "gpt_calls_made_before_failure": int(gpt_calls_made),
              "budget_extension_triggered": bool(budget_extension_triggered),
              "turn_detail": str(turn_resp.get("detail") or "")[:500],
              "network_retry_exhausted": turn_resp.get("network_retry_exhausted"),
            },
          )
        detail = (
          f"gpt_turn_failed: {turn_resp.get('detail') or decision_source}"
        )
        break

      raw_assistant_items = turn_resp.get("raw_assistant_items") or []
      tool_calls = turn_resp.get("tool_calls") or []
      for item in raw_assistant_items:
        input_items.append(item)

      if not tool_calls:
        detail = "gpt_stopped_calling_tool"
        break

      for call in tool_calls:
        if str(call.get("name") or "").strip() != _TOOL_NAME:
          input_items.append({
            "type": "function_call_output",
            "call_id": call.get("call_id") or "",
            "output": json.dumps(
              {"error": f"unknown_tool_{call.get('name')}"},
              ensure_ascii=False,
            ),
          })
          continue
        try:
          args = json.loads(call.get("arguments") or "{}")
          if not isinstance(args, dict):
            args = {}
        except Exception as exc:
          input_items.append({
            "type": "function_call_output",
            "call_id": call.get("call_id") or "",
            "output": json.dumps(
              {"error": f"arguments_not_json: {type(exc).__name__}"},
              ensure_ascii=False,
            ),
          })
          continue

        lever_adjustments_raw = args.get("lever_adjustments") if isinstance(args, dict) else {}
        lever_adjustments = _coerce_lever_adjustments(lever_adjustments_raw)
        projection = projector(
          pre_handler_finmo_quarter_rows=pre_rows,
          lever_adjustments=lever_adjustments,
        )
        residual = residual_checker(
          pre_handler_finmo_quarter_rows=pre_rows,
          lever_adjustments=lever_adjustments,
          buffer_by_quarter=buffer_map,
        )
        tool_result = {
          "projected_quarter_rows": projection.get("projected_quarter_rows") if isinstance(projection, dict) else [],
          "total_cash_delta": projection.get("total_cash_delta") if isinstance(projection, dict) else 0.0,
          "buffer_residual_violations": residual,
          "all_violations_resolved": len(residual) == 0,
        }
        tool_calls_used += 1
        rec = FundingToolCallRecord(
          call_n=tool_calls_used,
          arguments=args,
          result=tool_result,
          call_id=str(call.get("call_id") or ""),
        )
        history.append(rec)
        if tool_result["all_violations_resolved"]:
          verified_commit_candidate = rec

        input_items.append({
          "type": "function_call_output",
          "call_id": call.get("call_id") or "",
          "output": json.dumps(tool_result, ensure_ascii=False, default=str),
        })
        if tool_calls_used >= HARD_CAP_TOOL_CALLS:
          break
  finally:
    _FUNDING_HANDLER_GPT_CALL_COUNT.reset(_funding_iter_token)

  last_residual_count: Optional[int] = None
  if history:
    last_residual_count = _residual_count(history[-1])

  if verified_commit_candidate is not None:
    return FundingToolCallSessionResult(
      status="verified",
      final_lever_adjustments=verified_commit_candidate.arguments,
      tool_calls_used=tool_calls_used,
      tool_call_history=history,
      last_residual_count=last_residual_count,
      gpt_calls_made=gpt_calls_made,
      decision_sources=decision_sources,
      budget_extension_triggered=budget_extension_triggered,
      detail=detail or "verified_commit_candidate",
      verified_commit_call_n=verified_commit_candidate.call_n,
    )

  best_effort = _best_effort_record(history)
  # Machinery invariant #6 — best-effort selection drift. If the
  # best-effort record is actually all-resolved, the session loop
  # should have picked it up as the verified commit candidate.
  _assert_funding_handler_best_effort_selection_consistent(
    best_effort_record=best_effort,
    history=history,
  )
  if best_effort is not None:
    return FundingToolCallSessionResult(
      status="best_effort_no_all_resolved",
      final_lever_adjustments=best_effort.arguments,
      tool_calls_used=tool_calls_used,
      tool_call_history=history,
      last_residual_count=last_residual_count,
      gpt_calls_made=gpt_calls_made,
      decision_sources=decision_sources,
      budget_extension_triggered=budget_extension_triggered,
      detail=detail or "best_effort_selected",
      best_effort_call_n=best_effort.call_n,
    )

  return FundingToolCallSessionResult(
    status="failed_precondition",
    tool_calls_used=tool_calls_used,
    tool_call_history=history,
    last_residual_count=last_residual_count,
    gpt_calls_made=gpt_calls_made,
    decision_sources=decision_sources,
    budget_extension_triggered=budget_extension_triggered,
    detail=detail or "no_tool_calls_completed",
  )


def _coerce_lever_adjustments(raw: Any) -> Dict[str, Dict[int, float]]:
  """Convert the schema-shaped lever_adjustments (str quarter keys,
  nullable numbers) into the mini_finmo shape (int quarter keys,
  float values; nulls dropped)."""
  out: Dict[str, Dict[int, float]] = {}
  if not isinstance(raw, dict):
    return out
  for lever_id, per_q in raw.items():
    if not isinstance(per_q, dict):
      continue
    coerced: Dict[int, float] = {}
    for quarter_key, value in per_q.items():
      if value is None:
        continue
      try:
        qi = int(quarter_key)
      except Exception:
        continue
      try:
        coerced[qi] = float(value)
      except Exception:
        continue
    if coerced:
      out[lever_id] = coerced
  return out
