"""Phase 9 P3.5 — GPT tool-calling session for the exhaustion handler.

GPT proposes driver anchors, calls compute_full_trajectory(anchors) to
verify the EBITDA path the system would compute, iterates against the
tool result, then commits a final answer. Replaces the retired Call 1 /
Call 2 / iteration / snap-into-place pattern.

Session flow:
  1. Build initial input (system prompt + user prompt + tool definition).
  2. Loop up to MAX_TOOL_CALLS (5):
     - Issue one Responses-API turn with tools enabled.
     - If GPT returns a function_call, run compute_trajectory_from_anchors
       locally, append function_call_output to the input, continue.
     - If GPT returns an assistant message (final commit), parse it as
       the driver_anchors schema, exit.
  3. If the loop exhausted MAX_TOOL_CALLS without a commit, force a
     final answer by re-issuing the turn WITHOUT tools (so GPT has no
     option but to emit an assistant message).
  4. Return ToolCallSessionResult carrying status, final anchors, the
     full tool-call history, and the implied Q11 EBITDA from GPT's last
     compute_full_trajectory result (used downstream for provenance).

MAX_TOOL_CALLS is Python-enforced. GPT is not told the count — the
prompt language "up to a few iterations" keeps him from hedging.

Imports happen lazily inside functions so this module loads cleanly in
contexts where the orchestrator package isn't on sys.path.
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


logger = logging.getLogger(__name__)


# Python-enforced budget on tool calls within a single session. GPT
# does not know this count. Each tool call runs full FINMO under the
# hood, so 5 is a meaningful upper bound that still keeps the global
# 8-call run budget intact (5 tool calls + 1 final commit + 1 cash
# strategy review + 1 realism critique = 8).
MAX_TOOL_CALLS = 5

_TOOL_NAME = "compute_full_trajectory"


def _build_tool_definition() -> Dict[str, Any]:
  """Responses API tool definition for compute_full_trajectory."""
  three_anchor_schema = {
    "type": "object",
    "additionalProperties": False,
    "required": ["q1", "q11", "q20"],
    "properties": {
      "q1": {"type": "number"},
      "q11": {"type": "number"},
      "q20": {"type": "number"},
    },
  }
  return {
    "type": "function",
    "name": _TOOL_NAME,
    "description": (
      "Compute the resulting EBITDA margin trajectory across 20 quarters "
      "from your proposed driver anchors at Q1, Q11, Q20. Returns EBITDA "
      "margins at key quarters (Q1/Q5/Q11/Q15/Q20), gross margin "
      "percents, revenues, EBITDA dollars, and PASS/FAIL on each "
      "viability check (ebitda_positive_by_q11, "
      "ebitda_recovery_trend_q5_q11, no_post_recovery_relapse_q11_q20, "
      "gross_margin_supports_ebitda_recovery, "
      "fixed_cost_burden_reduced_or_scaled_by_q11) plus an all_pass "
      "aggregate. Use this to verify your anchors produce a viable plan "
      "before committing your final answer."
    ),
    "strict": True,
    "parameters": {
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
      ],
      "properties": {
        "unit_price": three_anchor_schema,
        "units_per_period_capacity": three_anchor_schema,
        "utilization_rate": three_anchor_schema,
        "payroll_dollars_per_quarter": three_anchor_schema,
        "cogs_percent_of_revenue": three_anchor_schema,
        "marketing_percent_of_revenue": three_anchor_schema,
        "sga_percent_of_revenue": three_anchor_schema,
      },
    },
  }


def _build_commit_schema() -> Dict[str, Any]:
  """Strict JSON schema for GPT's final commit assistant message."""
  three_anchor_schema = {
    "type": "object",
    "additionalProperties": False,
    "required": ["q1", "q11", "q20"],
    "properties": {
      "q1": {"type": "number"},
      "q11": {"type": "number"},
      "q20": {"type": "number"},
    },
  }
  return {
    "type": "object",
    "additionalProperties": False,
    "required": ["driver_anchors", "reasoning"],
    "properties": {
      "driver_anchors": {
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
        ],
        "properties": {
          "unit_price": three_anchor_schema,
          "units_per_period_capacity": three_anchor_schema,
          "utilization_rate": three_anchor_schema,
          "payroll_dollars_per_quarter": three_anchor_schema,
          "cogs_percent_of_revenue": three_anchor_schema,
          "marketing_percent_of_revenue": three_anchor_schema,
          "sga_percent_of_revenue": three_anchor_schema,
        },
      },
      "reasoning": {"type": "string"},
    },
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


def _build_initial_user_prompt(
  *,
  operating_model: Dict[str, Any],
  q1_state: Dict[str, Any],
  exhaustion_diagnostic: Dict[str, Any],
) -> str:
  ops_block = json.dumps(
    operating_model or {}, ensure_ascii=False, indent=2, default=str
  )
  q1_block = _format_q1_state(q1_state)
  diag_block = _format_exhaustion_diagnostic(exhaustion_diagnostic)
  return (
    "OPERATING MODEL:\n"
    f"{ops_block}\n\n"
    "CURRENT Q1 STATE FROM INTAKE:\n"
    f"{q1_block}\n\n"
    "EXHAUSTION DIAGNOSTIC (deterministic solver could not bridge to "
    "viability at conservative bounds):\n"
    f"{diag_block}\n\n"
    "QUESTION:\n"
    "Propose driver anchors at Q1, Q11, Q20 for all 7 drivers and call "
    f"the {_TOOL_NAME} tool to verify the resulting trajectory. Iterate "
    "by adjusting anchors and calling the tool again until all viability "
    "checks PASS. Then commit your final answer.\n\n"
    "Final-answer schema (your assistant message when you commit):\n"
    "{\n"
    '  "driver_anchors": {\n'
    '    "unit_price": {"q1": float, "q11": float, "q20": float},\n'
    '    "units_per_period_capacity": {"q1": int, "q11": int, "q20": int},\n'
    '    "utilization_rate": {"q1": float, "q11": float, "q20": float},\n'
    '    "payroll_dollars_per_quarter": {"q1": float, "q11": float, "q20": float},\n'
    '    "cogs_percent_of_revenue": {"q1": float, "q11": float, "q20": float},\n'
    '    "marketing_percent_of_revenue": {"q1": float, "q11": float, "q20": float},\n'
    '    "sga_percent_of_revenue": {"q1": float, "q11": float, "q20": float}\n'
    "  },\n"
    '  "reasoning": "short prose explaining the path for this business"\n'
    "}\n"
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
  status: str  # "committed", "committed_after_budget_hit", "failed"
  final_anchors: Optional[Dict[str, Any]] = None
  reasoning: str = ""
  tool_calls_used: int = 0
  tool_call_history: List[ToolCallRecord] = field(default_factory=list)
  last_viability_checks: Optional[Dict[str, Any]] = None
  implied_q11_ebitda_margin: Optional[float] = None
  gpt_calls_made: int = 0
  decision_sources: List[str] = field(default_factory=list)
  detail: str = ""

  def to_dict(self) -> Dict[str, Any]:
    return {
      "status": self.status,
      "tool_calls_used": int(self.tool_calls_used),
      "gpt_calls_made": int(self.gpt_calls_made),
      "implied_q11_ebitda_margin": self.implied_q11_ebitda_margin,
      "last_viability_checks": self.last_viability_checks,
      "tool_call_history": [r.to_dict() for r in self.tool_call_history],
      "decision_sources": list(self.decision_sources),
      "reasoning_chars": len(self.reasoning or ""),
      "detail": self.detail,
    }


def _summarize_anchors(anchors: Dict[str, Any]) -> Dict[str, Any]:
  out: Dict[str, Any] = {}
  for k, v in (anchors or {}).items():
    if isinstance(v, dict):
      out[k] = {
        "q1": v.get("q1"), "q11": v.get("q11"), "q20": v.get("q20"),
      }
  return out


def _last_viable_implied_q11(history: List[ToolCallRecord]) -> Optional[float]:
  """Return the Q11 EBITDA margin from the most recent tool result that
  passed every check, or from the most recent tool result if none
  passed.
  """
  for rec in reversed(history):
    checks = (rec.result or {}).get("viability_checks") or {}
    if checks.get("all_pass"):
      em = ((rec.result or {}).get("ebitda_margins") or {}).get("q11")
      if em is not None:
        return float(em)
  for rec in reversed(history):
    em = ((rec.result or {}).get("ebitda_margins") or {}).get("q11")
    if em is not None:
      return float(em)
  return None


def run_tool_calling_session(
  *,
  operating_model: Dict[str, Any],
  q1_state: Dict[str, Any],
  exhaustion_diagnostic: Dict[str, Any],
  operating_context: Dict[str, Any],
  intake_context: Optional[Dict[str, Any]] = None,
) -> ToolCallSessionResult:
  """Run the tool-calling session. Returns the full session result.

  The caller (handler.execute_tool_calling_session_and_commit) takes
  the committed driver_anchors and writes them into model_input via the
  shared writer, then rebuilds FINMO and decides the HandlerStatus.
  This function does NOT mutate model_input — it only orchestrates the
  GPT/tool dialogue.
  """
  from client_intake_and_finmo.post_intake_solver._gpt_critic_io import (  # type: ignore
    call_gpt_responses_api_turn,
  )
  from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.mini_finmo import (  # type: ignore
    compute_trajectory_from_anchors,
  )
  from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.prompts import (  # type: ignore
    SYSTEM_PROMPT,
  )
  from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.validators import (  # type: ignore
    validate_final_commit,
  )

  tool_def = _build_tool_definition()
  commit_schema = _build_commit_schema()
  initial_user_prompt = _build_initial_user_prompt(
    operating_model=operating_model,
    q1_state=q1_state,
    exhaustion_diagnostic=exhaustion_diagnostic,
  )

  # Responses API input items. The caller appends to this list each
  # turn — assistant raw items (function_call wrappers) and our
  # function_call_output replies.
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
  last_assistant_text: Optional[str] = None
  parsed_commit: Optional[Dict[str, Any]] = None
  status_label = "failed"
  detail = ""

  while True:
    # If we've used the tool budget, force a final answer this turn:
    # remove tools from the request and append a user nudge so GPT
    # commits a json_schema-conformant assistant message.
    tools_for_turn: Optional[List[Dict[str, Any]]] = None
    schema_for_turn: Optional[Dict[str, Any]] = None
    schema_name_for_turn: Optional[str] = None
    if tool_calls_used < MAX_TOOL_CALLS:
      tools_for_turn = [tool_def]
      # Don't constrain text-format when tools are available — GPT may
      # emit a tool_call instead of text, and a text.format constraint
      # only applies to text output. We attach the commit schema for
      # the FINAL turn only (when tools are removed).
      schema_for_turn = None
      schema_name_for_turn = None
    else:
      # Final-commit turn: no tools, strict json_schema, plus an
      # explicit user nudge.
      input_items.append({
        "role": "user",
        "content": [{
          "type": "input_text",
          "text": (
            "You have used your final tool call. Commit to your best "
            "answer now based on what you have learned across the "
            "tool calls so far. Return the final JSON schema with "
            "driver_anchors and reasoning."
          ),
        }],
      })
      tools_for_turn = None
      schema_for_turn = commit_schema
      schema_name_for_turn = (
        "post_intake_gpt_exhaustion_handler_final_commit"
      )

    consultant_label = (
      "post_intake_gpt_exhaustion_handler_tool_call_turn_"
      f"{tool_calls_used + 1}"
    ) if tools_for_turn else (
      "post_intake_gpt_exhaustion_handler_final_commit_after_budget"
    )
    turn_resp = call_gpt_responses_api_turn(
      consultant_name=consultant_label,
      input_items=input_items,
      tools=tools_for_turn,
      response_schema=schema_for_turn,
      schema_name=schema_name_for_turn,
    )
    gpt_calls_made += 1
    decision_sources.append(str(turn_resp.get("decision_source") or ""))

    if turn_resp.get("decision_source") != "python_proposer_plus_gpt_critic":
      # Hard fail (no api key, http error, timeout, budget). Exit.
      status_label = "failed"
      detail = str(turn_resp.get("detail") or "") or str(
        turn_resp.get("decision_source") or ""
      )
      break

    raw_assistant_items = turn_resp.get("raw_assistant_items") or []
    tool_calls = turn_resp.get("tool_calls") or []
    assistant_text = turn_resp.get("assistant_message_text")
    parsed_assistant_json = turn_resp.get("parsed_assistant_json")

    # Always echo the assistant items back to the input so the next
    # turn has the full conversation history.
    for item in raw_assistant_items:
      input_items.append(item)

    if tool_calls and tools_for_turn is not None:
      # Process each tool call; append a function_call_output reply
      # for each. (GPT typically emits one call per turn but Responses
      # API allows parallel calls — handle them all.)
      for call in tool_calls:
        if str(call.get("name") or "").strip() != _TOOL_NAME:
          # Unknown tool — feed back an error and continue.
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
        history.append(ToolCallRecord(
          call_n=tool_calls_used,
          arguments=args,
          result=result,
          call_id=str(call.get("call_id") or ""),
        ))
        input_items.append({
          "type": "function_call_output",
          "call_id": call.get("call_id") or "",
          "output": json.dumps(result, ensure_ascii=False, default=str),
        })
        if tool_calls_used >= MAX_TOOL_CALLS:
          break
      # Loop back; next iteration will either send tools again (if
      # budget left) or force the final-commit turn.
      continue

    # No tool calls in this turn -> GPT either committed or stalled.
    if isinstance(parsed_assistant_json, dict):
      ok, err = validate_final_commit(parsed_assistant_json)
      if ok:
        parsed_commit = parsed_assistant_json
        last_assistant_text = assistant_text
        if tools_for_turn is None:
          status_label = "committed_after_budget_hit"
        else:
          status_label = "committed"
        break
      else:
        # Schema-valid JSON but failed sanity. Append a user nudge
        # asking GPT to fix and emit a valid final answer.
        input_items.append({
          "role": "user",
          "content": [{
            "type": "input_text",
            "text": (
              f"Your commit failed sanity validation: {err}. "
              "Re-emit the final JSON schema with values in plausible "
              "ranges. Do not call the tool again — return the final "
              "answer now."
            ),
          }],
        })
        # Force tools_for_turn=None on next pass via budget exhaustion;
        # here we explicitly mark budget hit to drive the next loop.
        tool_calls_used = max(tool_calls_used, MAX_TOOL_CALLS)
        continue

    # No tool call AND no parseable assistant JSON. Give GPT one
    # explicit nudge; if we already nudged, fail.
    if tools_for_turn is None:
      status_label = "failed"
      detail = "no_tool_call_and_no_parseable_commit_after_force"
      last_assistant_text = assistant_text
      break
    input_items.append({
      "role": "user",
      "content": [{
        "type": "input_text",
        "text": (
          "Return your final answer in the JSON schema now. If you "
          "still need to verify, call compute_full_trajectory; "
          "otherwise emit driver_anchors + reasoning."
        ),
      }],
    })
    # Promote to final-commit turn.
    tool_calls_used = max(tool_calls_used, MAX_TOOL_CALLS)

  # Build the result.
  if parsed_commit is None:
    return ToolCallSessionResult(
      status="failed",
      tool_calls_used=tool_calls_used,
      tool_call_history=history,
      gpt_calls_made=gpt_calls_made,
      decision_sources=decision_sources,
      detail=detail or "no_parsed_commit",
      last_viability_checks=(
        history[-1].result.get("viability_checks") if history else None
      ),
      implied_q11_ebitda_margin=_last_viable_implied_q11(history),
    )

  return ToolCallSessionResult(
    status=status_label,
    final_anchors=parsed_commit.get("driver_anchors"),
    reasoning=str(parsed_commit.get("reasoning") or ""),
    tool_calls_used=tool_calls_used,
    tool_call_history=history,
    last_viability_checks=(
      history[-1].result.get("viability_checks") if history else None
    ),
    implied_q11_ebitda_margin=_last_viable_implied_q11(history),
    gpt_calls_made=gpt_calls_made,
    decision_sources=decision_sources,
    detail=detail,
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

  Mutates ``model_input`` in place with GPT-authored per-quarter driver
  values (under provenance tag "gpt_tool_call_commit_drivers"). Returns
  a HandlerResult; caller (handler.run_gpt_exhaustion_handler) returns
  it verbatim.
  """
  from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (  # type: ignore
    HandlerResult,
    HandlerStatus,
    _q11_ebitda_margin,
    _write_gpt_authored_per_quarter_values,
    compute_metrics_to_mute,
  )

  # The mini-FINMO probe runs against a frozen template (the model_input
  # at the moment the session starts). Tool calls during the session see
  # the SAME starting state — they don't accumulate writes from previous
  # tool calls. This matches the user's intent: each tool call is "if I
  # used these anchors, what would the system compute?".
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
  )

  provenance: Dict[str, Any] = {
    "phase": "phase_9_p3_5_tool_calling_session",
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

  if session_result.status == "failed" or not session_result.final_anchors:
    return HandlerResult(
      status=HandlerStatus.FAILED,
      gpt_calls_made=session_result.gpt_calls_made,
      q11_ebitda_target=session_result.implied_q11_ebitda_margin,
      q11_ebitda_actual=_q11_ebitda_margin(
        build_finmo(copy.deepcopy(model_input or {})) or {}
      ),
      provenance=provenance,
      reason=(
        f"tool_calling_session_failed: {session_result.detail or 'unknown'}"
      ),
    )

  # Write committed anchors into model_input via the shared writer
  # (FINMO contracts: skip Capacity for labor-driven, integer-round
  # capacity, clip utilization to <= 0.84).
  write_summary = _write_gpt_authored_per_quarter_values(
    model_input=model_input or {},
    driver_anchors=session_result.final_anchors,
    provenance_tag="gpt_tool_call_commit_drivers",
  )
  provenance["commit_write_summary"] = write_summary

  # Rebuild FINMO so downstream sees the updated state.
  try:
    rebuilt_finmo = build_finmo(copy.deepcopy(model_input or {}))
  except Exception as exc:
    return HandlerResult(
      status=HandlerStatus.FAILED,
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

  # Decide final status. FINMO Q11 should match what GPT saw in his
  # last viable tool call (mini-FINMO uses full FINMO under the hood).
  # If it doesn't satisfy Q11 >= 0, that's a FAILED (rare — implies a
  # writer / contract drift).
  q11_viable = q11_actual is not None and float(q11_actual) >= 0.0
  metrics_to_mute = compute_metrics_to_mute()

  if not q11_viable:
    return HandlerResult(
      status=HandlerStatus.FAILED,
      gpt_calls_made=session_result.gpt_calls_made,
      q11_ebitda_target=session_result.implied_q11_ebitda_margin,
      q11_ebitda_actual=q11_actual,
      provenance=provenance,
      realism_flags_to_mute=metrics_to_mute,
      reason=(
        "post_commit_q11_below_zero: implied="
        f"{session_result.implied_q11_ebitda_margin} actual={q11_actual}"
      ),
    )

  if session_result.status == "committed_after_budget_hit":
    final_status = HandlerStatus.LANDED_TOOL_CALL_BUDGET_HIT
    reason = "tool_call_budget_hit_committed_under_pressure"
  else:
    final_status = HandlerStatus.LANDED_TOOL_CALL_COMMIT
    reason = "tool_call_session_committed_with_viable_trajectory"

  return HandlerResult(
    status=final_status,
    gpt_calls_made=session_result.gpt_calls_made,
    q11_ebitda_target=session_result.implied_q11_ebitda_margin,
    q11_ebitda_actual=float(q11_actual),
    provenance=provenance,
    realism_flags_to_mute=metrics_to_mute,
    reason=reason,
  )
