"""Phase 9 P3.9 — GPT tool-calling session for the exhaustion handler.

Session model:
  - GPT iterates by calling compute_full_trajectory(anchors). The tool
    runs full FINMO under the hood (mini-FINMO is parity-by-construction)
    and returns viability_checks. There is no separate final-commit step.
  - After each tool call where viability_checks.all_pass == True, the
    Python orchestrator saves that tool call's full arguments dict as
    the current verified_commit_candidate. Each later all_pass call
    REPLACES the candidate (most recent verified wins).
  - When GPT stops calling the tool (returns a text response), or when
    the budget is exhausted, the session ends.
  - On session end, the system writes verified_commit_candidate's anchors
    via the shared writer and rebuilds FINMO. Because mini-FINMO already
    rebuilt FINMO on those same anchors, the post-commit Q11 EBITDA is
    structurally identical to what GPT saw — no possibility of
    divergence between probe and commit.

Two-phase budget:
  INITIAL_TOOL_CALL_BUDGET = 5
  EXTENSION_TOOL_CALLS     = 5
  HARD_CAP_TOOL_CALLS      = 10
  If the initial budget is exhausted without verified_commit_candidate,
  the extension is granted with the EXTENSION_PROMPT_TEXT appended.
  If the hard cap is reached without verified_commit_candidate, the
  session selects the best-effort tool call (highest pass-count, then
  highest Q11 EBITDA margin) and commits its anchors. Status reflects
  this as LANDED_BEST_EFFORT_NO_ALL_PASS.

GPT is never asked to produce a final commit JSON. The prompts describe
the tool exploration only.

Imports happen lazily inside functions so this module loads cleanly in
contexts where the orchestrator package isn't on sys.path.
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)


# Phase 9 P3.9 — two-phase budget.
INITIAL_TOOL_CALL_BUDGET = 5
EXTENSION_TOOL_CALLS = 5
HARD_CAP_TOOL_CALLS = INITIAL_TOOL_CALL_BUDGET + EXTENSION_TOOL_CALLS

# Legacy alias kept short-term for any external code that referenced
# MAX_TOOL_CALLS. The session loop itself uses the new constants above.
MAX_TOOL_CALLS = HARD_CAP_TOOL_CALLS

_TOOL_NAME = "compute_full_trajectory"


# Phase 9 P3.7 — scope literals. Restoration loop populates
# RestorationResult.scope with a HandlerScope enum; the handler converts
# to these string values before passing into the session. Tool schema
# and user prompt branch on these. No NAICS / stage / archetype
# branching anywhere.
SCOPE_PNL_PATH = "pnl_path"
SCOPE_BS_ONLY_PATH = "bs_only_path"
_VALID_SCOPES = (SCOPE_PNL_PATH, SCOPE_BS_ONLY_PATH)


def _three_anchor_schema() -> Dict[str, Any]:
  return {
    "type": "object",
    "additionalProperties": False,
    "required": ["q1", "q11", "q20"],
    "properties": {
      "q1": {"type": "number"},
      "q11": {"type": "number"},
      "q20": {"type": "number"},
    },
  }


def _working_capital_schema(*, all_required: bool = True) -> Dict[str, Any]:
  """Working capital drivers are SINGLE values per driver (not 3-anchor
  ramps). They are operationally stable across the 20-quarter horizon;
  the writer stamps each value uniformly across every live quarter.

  When ``all_required=False`` (bs_only_path), each WC field is nullable
  so GPT may author a subset; the writer treats null/None as "skipped".
  """
  if all_required:
    return {
      "type": "object",
      "additionalProperties": False,
      "required": [
        "accounts_receivable_days",
        "accounts_payable_days",
        "inventory_days",
        "deferred_revenue_percent_of_revenue",
        "prepaid_expenses_percent_of_revenue",
      ],
      "properties": {
        "accounts_receivable_days": {"type": "number"},
        "accounts_payable_days": {"type": "number"},
        "inventory_days": {"type": "number"},
        "deferred_revenue_percent_of_revenue": {"type": "number"},
        "prepaid_expenses_percent_of_revenue": {"type": "number"},
      },
    }
  nullable_number = {"type": ["number", "null"]}
  return {
    "type": "object",
    "additionalProperties": False,
    "required": [
      "accounts_receivable_days",
      "accounts_payable_days",
      "inventory_days",
      "deferred_revenue_percent_of_revenue",
      "prepaid_expenses_percent_of_revenue",
    ],
    "properties": {
      "accounts_receivable_days": nullable_number,
      "accounts_payable_days": nullable_number,
      "inventory_days": nullable_number,
      "deferred_revenue_percent_of_revenue": nullable_number,
      "prepaid_expenses_percent_of_revenue": nullable_number,
    },
  }


def _build_tool_definition(scope: str = SCOPE_PNL_PATH) -> Dict[str, Any]:
  """Responses API tool definition for compute_full_trajectory.

  bs_only_path: drops the 7 P&L anchor fields entirely; GPT can probe
  with any subset of the 5 WC values (each nullable). P&L stays at the
  deterministic-solver values for the duration of this run.
  """
  if scope == SCOPE_BS_ONLY_PATH:
    parameters = {
      "type": "object",
      "additionalProperties": False,
      "required": ["working_capital_drivers"],
      "properties": {
        "working_capital_drivers": _working_capital_schema(all_required=False),
      },
    }
    description = (
      "Compute the resulting EBITDA margin trajectory and balance-sheet "
      "realism across 20 quarters from your proposed working capital "
      "driver values. P&L drivers are held at the deterministic-solver "
      "values for this run. Pass null for any working capital driver "
      "you wish to leave at its existing value. Returns EBITDA margins, "
      "gross margin percents, revenues, EBITDA dollars, and PASS/FAIL "
      "on each viability check plus an all_pass aggregate."
    )
  else:
    parameters = {
      "type": "object",
      "additionalProperties": False,
      "required": [
        "unit_price",
        "units_per_period_capacity",
        "utilization_rate",
        "payroll_dollars_per_quarter",
        "cogs_percent_of_revenue",
        "marketing_percent_of_revenue",
        "sga_percent_of_revenue",
        "working_capital_drivers",
      ],
      "properties": {
        "unit_price": _three_anchor_schema(),
        "units_per_period_capacity": _three_anchor_schema(),
        "utilization_rate": _three_anchor_schema(),
        "payroll_dollars_per_quarter": _three_anchor_schema(),
        "cogs_percent_of_revenue": _three_anchor_schema(),
        "marketing_percent_of_revenue": _three_anchor_schema(),
        "sga_percent_of_revenue": _three_anchor_schema(),
        "working_capital_drivers": _working_capital_schema(all_required=True),
      },
    }
    description = (
      "Compute the resulting EBITDA margin trajectory across 20 quarters "
      "from your proposed driver anchors at Q1, Q11, Q20 plus 5 working "
      "capital drivers (single value each). Returns EBITDA margins at "
      "key quarters (Q1/Q5/Q11/Q15/Q20), gross margin percents, "
      "revenues, EBITDA dollars, and PASS/FAIL on each viability check "
      "(ebitda_positive_by_q11, ebitda_recovery_trend_q5_q11, "
      "ebitda_margin_q20_holds_or_improves_vs_q11, "
      "gross_margin_supports_ebitda_recovery, "
      "fixed_cost_burden_reduced_or_scaled_by_q11) plus an all_pass "
      "aggregate. Iterate until all_pass is True."
    )
  return {
    "type": "function",
    "name": _TOOL_NAME,
    "description": description,
    "strict": True,
    "parameters": parameters,
  }


def _format_q1_state(q1_state: Dict[str, Any]) -> str:
  if not isinstance(q1_state, dict) or not q1_state:
    return "(no Q1 actuals available)"
  return "\n".join(f"- {k}: {v}" for k, v in q1_state.items())


def _format_exhaustion_diagnostic(diag: Dict[str, Any]) -> str:
  if not isinstance(diag, dict) or not diag:
    return "(none)"
  parts: List[str] = []
  for k in ("status", "q11_ebitda_margin", "drivers_at_bounds_summary", "reason"):
    v = diag.get(k)
    if v is not None:
      parts.append(f"- {k}: {v}")
  return "\n".join(parts) if parts else "(diagnostic empty)"


def _format_failing_metrics(
  failing_metrics: Optional[List[Dict[str, Any]]],
) -> str:
  if not failing_metrics:
    return "(none)"
  lines: List[str] = []
  for fm in failing_metrics:
    if not isinstance(fm, dict):
      continue
    mk = fm.get("metric_key")
    q = fm.get("quarter_index")
    av = fm.get("actual_value")
    emin = fm.get("effective_min")
    emax = fm.get("effective_max")
    lines.append(
      f"- {mk} (Q{q}): actual={av}, band=[{emin}, {emax}]"
    )
  return "\n".join(lines) if lines else "(none)"


def _format_failing_primary_levers(
  failing_metrics: Optional[List[Dict[str, Any]]],
) -> str:
  if not failing_metrics:
    return "(none)"
  distinct: List[str] = []
  for fm in failing_metrics:
    if not isinstance(fm, dict):
      continue
    for lever in fm.get("primary_levers") or []:
      lever = str(lever).strip()
      if lever and lever not in distinct:
        distinct.append(lever)
  return "\n".join(f"  - {lid}" for lid in distinct) if distinct else "(none)"


def _build_initial_user_prompt(
  *,
  operating_model: Dict[str, Any],
  q1_state: Dict[str, Any],
  exhaustion_diagnostic: Dict[str, Any],
  scope: str = SCOPE_PNL_PATH,
  failing_metrics: Optional[List[Dict[str, Any]]] = None,
) -> str:
  """Phase 9 P3.9 — describes the tool exploration only. No final-commit
  JSON language. GPT iterates with the tool; the system handles commit
  on the backend from the most recent all_pass tool call.
  """
  ops_block = json.dumps(
    operating_model or {}, ensure_ascii=False, indent=2, default=str
  )
  q1_block = _format_q1_state(q1_state)
  diag_block = _format_exhaustion_diagnostic(exhaustion_diagnostic)

  if scope == SCOPE_BS_ONLY_PATH:
    failing_block = _format_failing_metrics(failing_metrics)
    primary_levers_block = _format_failing_primary_levers(failing_metrics)
    return (
      "OPERATING MODEL:\n"
      f"{ops_block}\n\n"
      "CURRENT Q1 STATE FROM INTAKE:\n"
      f"{q1_block}\n\n"
      "RESTORATION-LOOP DIAGNOSTIC:\n"
      f"{diag_block}\n\n"
      "The deterministic solver produced a plan that satisfies "
      "viability but would fail one or more balance-sheet realism "
      "checks. The following realism metrics are forecast to hard-fail "
      "on the post-solver state:\n\n"
      f"{failing_block}\n\n"
      "Their primary_levers (the drivers that materially affect them):\n\n"
      f"{primary_levers_block}\n\n"
      "You have authority over the 5 working capital drivers for this "
      "run. The P&L drivers are operating correctly and are outside "
      "your authority on this path -- the deterministic solver landed "
      "them.\n\n"
      "Iterate with the compute_full_trajectory tool. Author only the "
      "working capital drivers needed to fix the failing metrics. "
      "Leave the others as null; the existing values will be preserved.\n\n"
      "Reason from THIS specific business's operating model -- how it "
      "collects payment, what it sells, how it manages stock, whether "
      "it takes prepayments, what suppliers extend in terms. Iterate "
      f"with the {_TOOL_NAME} tool until viability_checks.all_pass = "
      "True. The system uses your most recent verified tool call as "
      "the committed plan."
    )

  # pnl_path
  return (
    "OPERATING MODEL:\n"
    f"{ops_block}\n\n"
    "CURRENT Q1 STATE FROM INTAKE:\n"
    f"{q1_block}\n\n"
    "EXHAUSTION DIAGNOSTIC (deterministic solver could not bridge to "
    "viability at conservative bounds):\n"
    f"{diag_block}\n\n"
    "TASK:\n"
    "Propose driver anchors at Q1, Q11, Q20 for all 7 P&L drivers and "
    f"call the {_TOOL_NAME} tool to verify the resulting trajectory. "
    "Iterate with adjusted anchors until viability_checks.all_pass = "
    "True. The system uses your most recent verified tool call as the "
    "committed plan.\n\n"
    "WORKING CAPITAL DRIVERS:\n"
    "You also author working capital drivers for this business. These\n"
    "are operationally stable across quarters, so provide a SINGLE\n"
    "value per driver that the system will apply uniformly across all\n"
    "20 quarters:\n\n"
    "- accounts_receivable_days\n"
    "- accounts_payable_days\n"
    "- inventory_days\n"
    "- deferred_revenue_percent_of_revenue\n"
    "- prepaid_expenses_percent_of_revenue\n\n"
    "Reason from this specific business's operating model -- how it\n"
    "collects payment, what it sells, how it manages stock, whether it\n"
    "takes prepayments, what suppliers extend in terms. Different\n"
    "business models produce fundamentally different working capital\n"
    "structures."
  )


@dataclass
class ToolCallRecord:
  call_n: int
  arguments: Dict[str, Any]
  result: Dict[str, Any]
  call_id: str = ""

  def to_dict(self) -> Dict[str, Any]:
    return {
      "call_n": int(self.call_n),
      "call_id": self.call_id,
      "arguments_summary": _summarize_anchors(self.arguments),
      "viability_checks": (self.result or {}).get("viability_checks"),
      "ebitda_margins": (self.result or {}).get("ebitda_margins"),
      "error": (self.result or {}).get("error"),
    }


@dataclass
class ToolCallSessionResult:
  status: str  # "verified", "best_effort_no_all_pass", "failed_precondition"
  final_anchors: Optional[Dict[str, Any]] = None
  tool_calls_used: int = 0
  tool_call_history: List[ToolCallRecord] = field(default_factory=list)
  last_viability_checks: Optional[Dict[str, Any]] = None
  implied_q11_ebitda_margin: Optional[float] = None
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
      "implied_q11_ebitda_margin": self.implied_q11_ebitda_margin,
      "last_viability_checks": self.last_viability_checks,
      "tool_call_history": [r.to_dict() for r in self.tool_call_history],
      "decision_sources": list(self.decision_sources),
      "budget_extension_triggered": bool(self.budget_extension_triggered),
      "verified_commit_call_n": self.verified_commit_call_n,
      "best_effort_call_n": self.best_effort_call_n,
      "detail": self.detail,
    }


def _summarize_anchors(anchors: Dict[str, Any]) -> Dict[str, Any]:
  out: Dict[str, Any] = {}
  for k, v in (anchors or {}).items():
    if isinstance(v, dict):
      out[k] = {
        "q1": v.get("q1"), "q11": v.get("q11"), "q20": v.get("q20"),
      }
    else:
      out[k] = v
  return out


def _viability_pass_count(record: "ToolCallRecord") -> int:
  checks = (record.result or {}).get("viability_checks") or {}
  return sum(
    1 for k, v in checks.items()
    if k != "all_pass" and str(v).upper() == "PASS"
  )


def _q11_from_record(record: "ToolCallRecord") -> Optional[float]:
  em = ((record.result or {}).get("ebitda_margins") or {}).get("q11")
  try:
    return float(em) if em is not None else None
  except Exception:
    return None


def _best_effort_record(
  history: List["ToolCallRecord"],
) -> Optional["ToolCallRecord"]:
  """Select the tool call with the highest count of passing viability
  checks. Tiebreaker: highest Q11 EBITDA margin. Returns None for an
  empty history.
  """
  if not history:
    return None
  def _key(rec: "ToolCallRecord") -> Tuple[int, float]:
    q11 = _q11_from_record(rec)
    return (_viability_pass_count(rec), q11 if q11 is not None else float("-inf"))
  return max(history, key=_key)


def run_tool_calling_session(
  *,
  operating_model: Dict[str, Any],
  q1_state: Dict[str, Any],
  exhaustion_diagnostic: Dict[str, Any],
  operating_context: Dict[str, Any],
  intake_context: Optional[Dict[str, Any]] = None,
  scope: str = SCOPE_PNL_PATH,
  failing_metrics: Optional[List[Dict[str, Any]]] = None,
) -> ToolCallSessionResult:
  """Run the tool-calling session.

  Phase 9 P3.9 — verified-commit-candidate model. The session tracks the
  most recent tool call where viability_checks.all_pass = True. On
  session end, that tool call's arguments are the commit. No separate
  final-answer JSON parsing step. GPT iterates with the tool; the
  system handles commit on the backend.

  Two-phase budget (5 + 5). Extension granted automatically when the
  initial budget is exhausted without verification. Hard cap at 10 tool
  calls; if reached without verification, best-effort selection picks
  the tool call with the highest count of passing checks (tiebreaker:
  highest Q11 EBITDA margin).

  Mutates nothing in the caller's state — the operating_context's
  model_input_template stays frozen across probes. The caller writes
  the committed anchors via the shared writer after this returns.
  """
  from client_intake_and_finmo.post_intake_solver._gpt_critic_io import (  # type: ignore
    call_gpt_responses_api_turn,
  )
  from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.mini_finmo import (  # type: ignore
    compute_trajectory_from_anchors,
  )
  from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.prompts import (  # type: ignore
    SYSTEM_PROMPT,
    EXTENSION_PROMPT_TEXT,
  )

  if scope not in _VALID_SCOPES:
    scope = SCOPE_PNL_PATH
  tool_def = _build_tool_definition(scope=scope)
  initial_user_prompt = _build_initial_user_prompt(
    operating_model=operating_model,
    q1_state=q1_state,
    exhaustion_diagnostic=exhaustion_diagnostic,
    scope=scope,
    failing_metrics=failing_metrics,
  )

  # Responses API input items — the caller appends to this list each
  # turn (assistant function_call wrappers + our function_call_output
  # replies + any nudge messages).
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

  history: List[ToolCallRecord] = []
  tool_calls_used = 0
  gpt_calls_made = 0
  decision_sources: List[str] = []
  budget_extension_triggered = False
  verified_commit_candidate: Optional[ToolCallRecord] = None
  detail = ""

  # Session loop: GPT iterates until either he stops calling the tool
  # OR the hard cap is reached.
  while True:
    # Budget management: extension grant if needed.
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

    turn_resp = call_gpt_responses_api_turn(
      consultant_name=(
        "post_intake_gpt_exhaustion_handler_tool_call_turn_"
        f"{tool_calls_used + 1}"
      ),
      input_items=input_items,
      tools=[tool_def],
      response_schema=None,
      schema_name=None,
    )
    gpt_calls_made += 1
    decision_sources.append(str(turn_resp.get("decision_source") or ""))

    if turn_resp.get("decision_source") != "python_proposer_plus_gpt_critic":
      detail = (
        f"gpt_turn_failed: {turn_resp.get('detail') or turn_resp.get('decision_source')}"
      )
      break

    raw_assistant_items = turn_resp.get("raw_assistant_items") or []
    tool_calls = turn_resp.get("tool_calls") or []

    # Echo assistant items back to the input for the next turn.
    for item in raw_assistant_items:
      input_items.append(item)

    if not tool_calls:
      # GPT issued an assistant message instead of calling the tool —
      # he's decided to stop iterating. Session ends; commit from
      # verified_commit_candidate.
      detail = "gpt_stopped_calling_tool"
      break

    # Process each tool call (Responses API supports parallel calls;
    # typically one per turn, but the loop handles either).
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

      result = compute_trajectory_from_anchors(args, operating_context)
      tool_calls_used += 1
      rec = ToolCallRecord(
        call_n=tool_calls_used,
        arguments=args,
        result=result,
        call_id=str(call.get("call_id") or ""),
      )
      history.append(rec)

      # Verified-commit-candidate tracking. Most recent all_pass wins.
      checks = (result or {}).get("viability_checks") or {}
      if checks.get("all_pass") is True:
        verified_commit_candidate = rec

      input_items.append({
        "type": "function_call_output",
        "call_id": call.get("call_id") or "",
        "output": json.dumps(result, ensure_ascii=False, default=str),
      })
      if tool_calls_used >= HARD_CAP_TOOL_CALLS:
        break

    # Loop back. The while-loop guard handles hard cap on the next pass.

  # Session ended. Decide commit.
  last_viability_checks = (
    history[-1].result.get("viability_checks") if history else None
  )
  if verified_commit_candidate is not None:
    return ToolCallSessionResult(
      status="verified",
      final_anchors=verified_commit_candidate.arguments,
      tool_calls_used=tool_calls_used,
      tool_call_history=history,
      last_viability_checks=last_viability_checks,
      implied_q11_ebitda_margin=_q11_from_record(verified_commit_candidate),
      gpt_calls_made=gpt_calls_made,
      decision_sources=decision_sources,
      budget_extension_triggered=budget_extension_triggered,
      detail=detail or "verified_commit_candidate",
      verified_commit_call_n=verified_commit_candidate.call_n,
    )

  best_effort = _best_effort_record(history)
  if best_effort is not None:
    return ToolCallSessionResult(
      status="best_effort_no_all_pass",
      final_anchors=best_effort.arguments,
      tool_calls_used=tool_calls_used,
      tool_call_history=history,
      last_viability_checks=last_viability_checks,
      implied_q11_ebitda_margin=_q11_from_record(best_effort),
      gpt_calls_made=gpt_calls_made,
      decision_sources=decision_sources,
      budget_extension_triggered=budget_extension_triggered,
      detail=detail or "best_effort_selected",
      best_effort_call_n=best_effort.call_n,
    )

  # No tool calls in history at all -> failed precondition (couldn't
  # even probe). This is rare; happens when GPT never called the tool
  # or every turn errored.
  return ToolCallSessionResult(
    status="failed_precondition",
    tool_calls_used=tool_calls_used,
    tool_call_history=history,
    last_viability_checks=last_viability_checks,
    implied_q11_ebitda_margin=None,
    gpt_calls_made=gpt_calls_made,
    decision_sources=decision_sources,
    budget_extension_triggered=budget_extension_triggered,
    detail=detail or "no_tool_calls_completed",
  )


def execute_tool_calling_session_and_commit(
  *,
  restoration_result: Any,
  exhaustion_diagnostic: Dict[str, Any],
  q1_state: Dict[str, Any],
  model_input: Dict[str, Any],
  operating_model: Dict[str, Any],
  build_finmo: Callable[[Dict[str, Any]], Dict[str, Any]],
  intake_context: Dict[str, Any],
):
  """Run the tool-calling session, write the committed anchors into
  model_input, rebuild FINMO, and return a HandlerResult.

  Phase 9 P3.9 — the committed anchors are the verified_commit_candidate
  from the session (the most recent tool call with all_pass=True), OR
  the best-effort record (highest pass-count) when no all_pass occurred
  within the hard-cap budget.

  Mutates ``model_input`` in place with GPT-authored per-quarter driver
  values under provenance tag "gpt_tool_call_commit_drivers". Returns a
  HandlerResult; caller (handler.run_gpt_exhaustion_handler) returns it
  verbatim.
  """
  from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (  # type: ignore
    HandlerResult,
    HandlerStatus,
    _q11_ebitda_margin,
    _write_gpt_authored_per_quarter_values,
    authored_lever_ids_from_commit,
    compute_metrics_to_mute,
  )

  # Pull scope + failing_metrics off the restoration result. Default to
  # PNL_PATH when restoration_result doesn't carry a scope.
  scope_value = SCOPE_PNL_PATH
  failing_metrics: List[Dict[str, Any]] = []
  scope_raw = getattr(restoration_result, "scope", None)
  if scope_raw is not None:
    scope_str = (
      scope_raw.value if hasattr(scope_raw, "value") else str(scope_raw)
    )
    if scope_str in _VALID_SCOPES:
      scope_value = scope_str
  fm_raw = getattr(restoration_result, "failing_metrics", None)
  if isinstance(fm_raw, list):
    failing_metrics = [
      dict(item) for item in fm_raw if isinstance(item, dict)
    ]

  operating_context = {
    "model_input_template": copy.deepcopy(model_input or {}),
    "build_finmo": build_finmo,
    "operating_model": operating_model or {},
    "q1_state": q1_state,
  }

  session_result = run_tool_calling_session(
    operating_model=operating_model or {},
    q1_state=q1_state,
    exhaustion_diagnostic=exhaustion_diagnostic,
    operating_context=operating_context,
    intake_context=intake_context or {},
    scope=scope_value,
    failing_metrics=failing_metrics,
  )

  provenance: Dict[str, Any] = {
    "phase": "phase_9_p3_9_tool_calling_session",
    "exhaustion_diagnostic": {
      "status": exhaustion_diagnostic.get("status"),
      "q11_ebitda_margin": exhaustion_diagnostic.get("q11_ebitda_margin"),
      "drivers_at_bounds_summary": exhaustion_diagnostic.get(
        "drivers_at_bounds_summary"
      ),
      "reason": exhaustion_diagnostic.get("reason"),
    },
    "q1_state": q1_state,
    "tool_calling_session": session_result.to_dict(),
  }

  # Phase 9 P3.10 Commit 2 — split FAILED_PRECONDITION semantics.
  # When the session produced no anchors AND the failure was a network
  # retry exhaustion (Sunny pattern: DNS outage on first turn), raise
  # PostIntakePreconditionFailed under test mode so the operator sees
  # the network diagnostic in one line. When the failure was something
  # else (parse error, GPT stopped without all_pass on every probe),
  # return FAILED_NO_USABLE_ANCHORS — Commit 3 will convert that
  # receiving end too.
  from client_intake_and_finmo.fail_fast.common import (  # type: ignore
    PostIntakePreconditionFailed,
    convergence_test_mode_enabled,
  )

  if session_result.final_anchors is None:
    detail_text = str(session_result.detail or "")
    if convergence_test_mode_enabled():
      raise PostIntakePreconditionFailed(
        operation="gpt_exhaustion_handler_tool_calling_session_no_anchors",
        pipeline_stage="phase_9_p3_9_tool_calling_session",
        expected="At least one tool call produces usable anchors",
        actual=detail_text[:300] or "no tool calls completed",
        details={
          "tool_calls_used": int(session_result.tool_calls_used),
          "gpt_calls_made": int(session_result.gpt_calls_made),
          "budget_extension_triggered": bool(
            session_result.budget_extension_triggered
          ),
          "decision_sources": list(session_result.decision_sources),
          "last_viability_checks": session_result.last_viability_checks,
        },
      )
    # Production-mode legacy path — return FAILED_NO_USABLE_ANCHORS so
    # downstream can distinguish from genuine preconditions.
    return HandlerResult(
      status=HandlerStatus.FAILED_NO_USABLE_ANCHORS,
      gpt_calls_made=session_result.gpt_calls_made,
      q11_ebitda_target=None,
      q11_ebitda_actual=_q11_ebitda_margin(
        build_finmo(copy.deepcopy(model_input or {})) or {}
      ),
      provenance=provenance,
      reason=(
        f"tool_calling_session_failed: {detail_text or 'unknown'}"
      ),
    )

  # Write committed anchors into the live model_input via the shared
  # writer (FINMO contracts: skip Capacity for labor-driven, integer-
  # round capacity, clip utilization to <= 0.84).
  write_summary = _write_gpt_authored_per_quarter_values(
    model_input=model_input or {},
    driver_anchors=session_result.final_anchors,
    provenance_tag="gpt_tool_call_commit_drivers",
  )
  provenance["commit_write_summary"] = write_summary

  # Rebuild FINMO so downstream sees the updated state.
  # Phase 9 P3.10 Commit 2 — post-commit rebuild failure is a genuine
  # precondition: GPT committed verified anchors, the writer applied
  # them, and the rebuild after the writer must succeed. A failure here
  # means the writer produced an invalid model_input that even mini-
  # FINMO accepted under its probe — a real divergence between probe
  # and commit (the system was supposed to make this structurally
  # impossible per P3.9). Hard-fail under test mode.
  try:
    rebuilt_finmo = build_finmo(copy.deepcopy(model_input or {}))
  except Exception as exc:
    if convergence_test_mode_enabled():
      raise PostIntakePreconditionFailed(
        operation="gpt_exhaustion_handler_post_commit_finmo_rebuild",
        pipeline_stage="phase_9_p3_9_tool_calling_session",
        expected=(
          "build_finmo() succeeds on writer-mutated model_input "
          "(mini-FINMO probe already accepted the same anchors)"
        ),
        actual=f"{type(exc).__name__}: {str(exc)[:200]}",
        details={
          "session_status": session_result.status,
          "tool_calls_used": int(session_result.tool_calls_used),
          "implied_q11_ebitda_margin": session_result.implied_q11_ebitda_margin,
          "verified_commit_call_n": session_result.verified_commit_call_n,
          "best_effort_call_n": session_result.best_effort_call_n,
        },
        cause=exc,
      ) from exc
    return HandlerResult(
      status=HandlerStatus.FAILED_PRECONDITION,
      gpt_calls_made=session_result.gpt_calls_made,
      q11_ebitda_target=session_result.implied_q11_ebitda_margin,
      q11_ebitda_actual=None,
      provenance={
        **provenance,
        "rebuild_error": f"{type(exc).__name__}: {str(exc)[:200]}",
      },
      reason="finmo_rebuild_failed_after_commit",
    )
  q11_actual = _q11_ebitda_margin(rebuilt_finmo or {})
  provenance["post_commit_q11_ebitda_margin"] = q11_actual

  # Mute set derived from what GPT ACTUALLY authored (not from what was
  # authorized). bs_only_path commits mute only metrics whose
  # primary_levers reference the WC drivers GPT supplied a value for.
  authored_lever_ids = authored_lever_ids_from_commit(
    session_result.final_anchors
  )
  provenance["authored_lever_ids"] = sorted(authored_lever_ids)
  provenance["scope"] = scope_value
  metrics_to_mute = compute_metrics_to_mute(
    gpt_authored_lever_ids=authored_lever_ids,
  )

  if session_result.status == "verified":
    return HandlerResult(
      status=HandlerStatus.LANDED_VERIFIED_TOOL_CALL,
      gpt_calls_made=session_result.gpt_calls_made,
      q11_ebitda_target=session_result.implied_q11_ebitda_margin,
      q11_ebitda_actual=float(q11_actual) if q11_actual is not None else None,
      provenance=provenance,
      realism_flags_to_mute=metrics_to_mute,
      reason=(
        "verified_tool_call_committed"
        + (" (extension_budget_used)" if session_result.budget_extension_triggered else "")
      ),
    )

  # best_effort_no_all_pass
  return HandlerResult(
    status=HandlerStatus.LANDED_BEST_EFFORT_NO_ALL_PASS,
    gpt_calls_made=session_result.gpt_calls_made,
    q11_ebitda_target=session_result.implied_q11_ebitda_margin,
    q11_ebitda_actual=float(q11_actual) if q11_actual is not None else None,
    provenance=provenance,
    realism_flags_to_mute=metrics_to_mute,
    reason=(
      "best_effort_no_all_pass_committed_under_hard_cap"
    ),
  )
