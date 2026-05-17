"""Iter 19 Stage 5 — Stage ramp handler tool-calling session.

GPT-driven stage ramp refinement loop. Mirrors the exhaustion handler
+ funding handler session pattern:

  - INITIAL_TOOL_CALL_BUDGET = 8; EXTENSION_TOOL_CALLS = 2;
    HARD_CAP_TOOL_CALLS = 10.
  - counts_against_run_budget=False on every API call (iter 17).
  - GPT iterates by calling ``probe_stage_ramp_contract(refined_grid)``.
    The tool runs the mini validator (mirror of
    ``_validate_stage_ramp_contract_payload``) and returns the
    accepted/rejected status + error text.
  - The session tracks the most recent tool call where
    ``validator_accepted == True`` as ``verified_commit_candidate``.

The mini validator does NOT call the production validator directly to
avoid circular imports; instead it captures the validator dependency
via dependency injection inside :mod:`mini_finmo`.

Live API integration is unverified pending end-of-iter E2E sweep.
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)


INITIAL_TOOL_CALL_BUDGET: int = 8
EXTENSION_TOOL_CALLS: int = 2
HARD_CAP_TOOL_CALLS: int = INITIAL_TOOL_CALL_BUDGET + EXTENSION_TOOL_CALLS  # 10
MAX_TOOL_CALLS: int = HARD_CAP_TOOL_CALLS


COUNTS_AGAINST_RUN_BUDGET: bool = False


_TOOL_NAME: str = "probe_stage_ramp_contract"


def _build_grid_row_schema() -> Dict[str, Any]:
  """One quarter_ramp_grid row in strict-mode JSON schema."""
  return {
    "type": "object",
    "additionalProperties": False,
    "required": [
      "q",
      "rev_target",
      "rev_max",
      "rev_spike",
      "rev_spike_max",
      "max_util",
      "cogs_target",
      "cogs_max",
      "marketing_max",
      "rd_max",
      "ga_max",
      "lease_max",
      "ni_floor",
      "posture",
    ],
    "properties": {
      "q": {"type": "integer", "minimum": 1, "maximum": 20},
      "rev_target": {"type": "number"},
      "rev_max": {"type": "number"},
      "rev_spike": {"type": "boolean"},
      "rev_spike_max": {"type": "number"},
      "max_util": {"type": "number"},
      "cogs_target": {"type": "number"},
      "cogs_max": {"type": "number"},
      "marketing_max": {"type": "number"},
      "rd_max": {"type": "number"},
      "ga_max": {"type": "number"},
      "lease_max": {"type": "number"},
      "ni_floor": {"type": "number"},
      "posture": {
        "type": "string",
        "enum": ["loss_allowed", "improving_losses", "near_breakeven", "positive"],
      },
    },
  }


def _build_tool_definition() -> Dict[str, Any]:
  return {
    "type": "function",
    "name": _TOOL_NAME,
    "description": (
      "Probe a candidate stage_ramp_contract refinement. The tool runs "
      "the same validator the production system uses and returns "
      "{validator_accepted: bool, validator_error_text: string|null}. "
      "Iterate by adjusting the contract fields you author until the "
      "validator accepts. The system commits your most recent "
      "validator-accepted candidate automatically; you do not produce "
      "a separate final-answer JSON."
    ),
    "strict": True,
    "parameters": {
      "type": "object",
      "additionalProperties": False,
      "required": [
        "stage_family",
        "utilization_high_watermark",
        "quarter_ramp_grid",
        "rationale",
      ],
      "properties": {
        "stage_family": {
          "type": "string",
          "enum": ["startup", "early", "operational"],
        },
        "utilization_high_watermark": {"type": "number"},
        "quarter_ramp_grid": {
          "type": "array",
          "minItems": 20,
          "maxItems": 20,
          "items": _build_grid_row_schema(),
        },
        "rationale": {"type": "string"},
      },
    },
  }


SYSTEM_PROMPT: str = (
  "You are refining a stage ramp contract for a 20-quarter financial "
  "plan. The Python deterministic builder produced a contract from "
  "NAICS cohort bands + stage policy defaults; that contract failed "
  "the realism validator. Your job is to refine the contract fields "
  "so the validator accepts the next probe.\n"
  "\n"
  "Your authority is strictly limited to the stage_ramp_contract "
  "fields: stage_family, utilization_high_watermark, "
  "quarter_ramp_grid rows (rev_target, rev_max, rev_spike, "
  "rev_spike_max, max_util, cogs_target/_max, marketing_max, rd_max, "
  "ga_max, lease_max, ni_floor, posture), and rationale.\n"
  "\n"
  "You have a tool: probe_stage_ramp_contract(refined_contract). Call "
  "it with your proposed full contract. The tool runs the validator "
  "and returns {validator_accepted, validator_error_text}.\n"
  "\n"
  "Iterate. The system commits your most recent validator-accepted "
  "candidate automatically. Reason from the validator's error text: "
  "every rejection names the specific field and the rule that tripped, "
  "so the refinement is targeted, not blind.\n"
)


EXTENSION_PROMPT_TEXT: str = (
  "You have used several tool calls without the validator accepting "
  "your refinement. Be more aggressive: relax cost-ratio maxes within "
  "the stage policy's allowed bands, push utilization caps closer to "
  "the high watermark, or revisit posture/ni_floor placements. The "
  "validator's error text names the specific failure; match the "
  "refinement directly to that field."
)


@dataclass
class StageRampToolCallRecord:
  call_n: int
  arguments: Dict[str, Any]
  result: Dict[str, Any]
  call_id: str = ""

  def to_dict(self) -> Dict[str, Any]:
    return {
      "call_n": int(self.call_n),
      "call_id": self.call_id,
      "validator_accepted": bool((self.result or {}).get("validator_accepted")),
      "validator_error_text": str((self.result or {}).get("validator_error_text") or "")[:200],
      "error": (self.result or {}).get("error"),
    }


@dataclass
class StageRampToolCallSessionResult:
  status: str  # "verified" | "best_effort_no_acceptance" | "failed_precondition"
  refined_contract: Optional[Dict[str, Any]] = None
  tool_calls_used: int = 0
  tool_call_history: List[StageRampToolCallRecord] = field(default_factory=list)
  last_validator_error: Optional[str] = None
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
      "last_validator_error": self.last_validator_error,
      "tool_call_history": [r.to_dict() for r in self.tool_call_history],
      "decision_sources": list(self.decision_sources),
      "budget_extension_triggered": bool(self.budget_extension_triggered),
      "verified_commit_call_n": self.verified_commit_call_n,
      "best_effort_call_n": self.best_effort_call_n,
      "detail": self.detail,
    }


def _build_initial_user_prompt(
  *,
  python_contract: Dict[str, Any],
  validator_error_text: str,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  stage_policy: Dict[str, Any],
  r_and_d_enabled: bool,
) -> str:
  contract_block = json.dumps(
    python_contract or {}, ensure_ascii=False, indent=2, default=str
  )
  ops_block = json.dumps(
    {
      "business_naics_6": str(ops_json.get("business_naics_6") or ""),
      "business_stage": str(ops_json.get("business_stage") or ""),
      "business_type": str(ops_json.get("business_type") or ""),
    },
    ensure_ascii=False,
    indent=2,
  )
  policy_block = json.dumps(
    {
      "stage_family": stage_policy.get("stage_family"),
      "profitability_postures": stage_policy.get("profitability_postures"),
      "validator_rules": stage_policy.get("validator_rules"),
      "qoq_growth_band": stage_policy.get("qoq_growth_band"),
    },
    ensure_ascii=False,
    indent=2,
    default=str,
  )
  return (
    "PYTHON DETERMINISTIC STAGE RAMP CONTRACT (rejected by validator):\n"
    f"{contract_block}\n\n"
    "VALIDATOR ERROR TEXT:\n"
    f"{validator_error_text or '(none)'}\n\n"
    "BUSINESS OPS CONTEXT:\n"
    f"{ops_block}\n\n"
    "STAGE POLICY (postures, ni_floor thresholds, qoq band):\n"
    f"{policy_block}\n\n"
    f"R&D APPLICABILITY: {'enabled' if r_and_d_enabled else 'disabled (rd_max must be 0.00 throughout)'}\n\n"
    "TASK:\n"
    f"Author a refined stage_ramp_contract and call {_TOOL_NAME} to "
    "verify it. Iterate against the validator's error text until the "
    "validator accepts the probe."
  )


def run_stage_ramp_tool_calling_session(
  *,
  python_contract: Dict[str, Any],
  validator_error_text: str,
  business_facts: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  stage_policy: Optional[Dict[str, Any]] = None,
  r_and_d_enabled: bool = True,
  _call_gpt_turn: Optional[Callable[..., Dict[str, Any]]] = None,
  _validator: Optional[Callable[..., Dict[str, Any]]] = None,
) -> StageRampToolCallSessionResult:
  """Run the stage ramp GPT tool-calling session.

  Mirrors the exhaustion + funding handler session shape; uses the
  production stage ramp validator (or an injected mock) as the
  per-turn acceptance probe.

  Test seams: ``_call_gpt_turn`` (Responses-API caller),
  ``_validator`` (the stage ramp validator).
  """
  call_gpt_turn = _call_gpt_turn
  if call_gpt_turn is None:
    from client_intake_and_finmo.post_intake_solver._gpt_critic_io import (  # type: ignore
      call_gpt_responses_api_turn,
    )
    call_gpt_turn = call_gpt_responses_api_turn

  validator = _validator
  if validator is None:
    from client_intake_and_finmo.post_intake_contracts.runner import (  # type: ignore
      _validate_stage_ramp_contract_payload,
    )
    validator = _validate_stage_ramp_contract_payload

  expected_family = str((stage_policy or {}).get("stage_family") or python_contract.get("stage_family") or "operational")
  business_stage = str(python_contract.get("business_stage") or "")
  planning_mode = str(python_contract.get("planning_mode") or "")
  planning_mode_reason = str(python_contract.get("planning_mode_reason") or "")

  tool_def = _build_tool_definition()
  initial_user_prompt = _build_initial_user_prompt(
    python_contract=python_contract,
    validator_error_text=validator_error_text,
    business_facts=business_facts or {},
    ops_json=ops_json or {},
    stage_policy=stage_policy or {},
    r_and_d_enabled=r_and_d_enabled,
  )
  input_items: List[Dict[str, Any]] = [
    {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT.strip()}]},
    {"role": "user", "content": [{"type": "input_text", "text": initial_user_prompt}]},
  ]

  history: List[StageRampToolCallRecord] = []
  tool_calls_used = 0
  gpt_calls_made = 0
  decision_sources: List[str] = []
  budget_extension_triggered = False
  verified_commit_candidate: Optional[StageRampToolCallRecord] = None
  detail = ""

  # Phase 9 P3.12 — machinery fail-fast contextvar setup.
  from client_intake_and_finmo.post_intake_stage_ramp_handler.handler import (  # type: ignore
    _STAGE_RAMP_HANDLER_GPT_CALL_COUNT,
    _assert_stage_ramp_handler_budget_decoupled,
    _assert_stage_ramp_handler_round_count_consistent,
    _assert_stage_ramp_handler_state_intact,
  )
  _stage_ramp_iter_token = _STAGE_RAMP_HANDLER_GPT_CALL_COUNT.set(0)
  loop_round_index = 0
  try:
    while True:
      loop_round_index += 1
      _assert_stage_ramp_handler_state_intact(
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

      _assert_stage_ramp_handler_budget_decoupled(
        round_n=loop_round_index,
        counts_against_run_budget_arg=COUNTS_AGAINST_RUN_BUDGET,
      )
      turn_resp = call_gpt_turn(
        consultant_name=f"post_intake_stage_ramp_handler_tool_call_turn_{tool_calls_used + 1}",
        input_items=input_items,
        tools=[tool_def],
        response_schema=None,
        schema_name=None,
        counts_against_run_budget=COUNTS_AGAINST_RUN_BUDGET,
      )
      _STAGE_RAMP_HANDLER_GPT_CALL_COUNT.set(
        _STAGE_RAMP_HANDLER_GPT_CALL_COUNT.get() + 1
      )
      gpt_calls_made += 1
      _assert_stage_ramp_handler_round_count_consistent(
        loop_round_index=loop_round_index,
        gpt_calls_made=gpt_calls_made,
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
            operation="stage_ramp_handler_tool_calling_session_turn_failed",
            pipeline_stage="iter_19_stage_5_stage_ramp_handler",
            expected="decision_source=python_proposer_plus_gpt_critic",
            actual=decision_source,
            details={
              "tool_calls_used_before_failure": int(tool_calls_used),
              "gpt_calls_made_before_failure": int(gpt_calls_made),
              "budget_extension_triggered": bool(budget_extension_triggered),
              "turn_detail": str(turn_resp.get("detail") or "")[:500],
            },
          )
        detail = f"gpt_turn_failed: {turn_resp.get('detail') or decision_source}"
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
            "output": json.dumps({"error": f"unknown_tool_{call.get('name')}"}, ensure_ascii=False),
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

        try:
          validator(
            payload=args,
            expected_stage_family=expected_family,
            business_stage=business_stage,
            planning_mode=planning_mode,
            planning_mode_reason=planning_mode_reason,
            r_and_d_enabled=r_and_d_enabled,
          )
          tool_result = {
            "validator_accepted": True,
            "validator_error_text": None,
          }
        except RuntimeError as exc:
          tool_result = {
            "validator_accepted": False,
            "validator_error_text": str(exc),
          }

        tool_calls_used += 1
        rec = StageRampToolCallRecord(
          call_n=tool_calls_used,
          arguments=args,
          result=tool_result,
          call_id=str(call.get("call_id") or ""),
        )
        history.append(rec)
        if tool_result["validator_accepted"]:
          verified_commit_candidate = rec

        input_items.append({
          "type": "function_call_output",
          "call_id": call.get("call_id") or "",
          "output": json.dumps(tool_result, ensure_ascii=False, default=str),
        })
        if tool_calls_used >= HARD_CAP_TOOL_CALLS:
          break
  finally:
    _STAGE_RAMP_HANDLER_GPT_CALL_COUNT.reset(_stage_ramp_iter_token)

  last_validator_error: Optional[str] = None
  if history:
    last_validator_error = str(history[-1].result.get("validator_error_text") or "") or None

  if verified_commit_candidate is not None:
    return StageRampToolCallSessionResult(
      status="verified",
      refined_contract=verified_commit_candidate.arguments,
      tool_calls_used=tool_calls_used,
      tool_call_history=history,
      last_validator_error=last_validator_error,
      gpt_calls_made=gpt_calls_made,
      decision_sources=decision_sources,
      budget_extension_triggered=budget_extension_triggered,
      detail=detail or "verified_commit_candidate",
      verified_commit_call_n=verified_commit_candidate.call_n,
    )

  if history:
    # Best-effort: most recent non-accepted call (no useful candidate
    # but we surface the residual error).
    return StageRampToolCallSessionResult(
      status="best_effort_no_acceptance",
      refined_contract=None,
      tool_calls_used=tool_calls_used,
      tool_call_history=history,
      last_validator_error=last_validator_error,
      gpt_calls_made=gpt_calls_made,
      decision_sources=decision_sources,
      budget_extension_triggered=budget_extension_triggered,
      detail=detail or "best_effort_no_acceptance",
      best_effort_call_n=history[-1].call_n,
    )

  return StageRampToolCallSessionResult(
    status="failed_precondition",
    refined_contract=None,
    tool_calls_used=tool_calls_used,
    tool_call_history=history,
    last_validator_error=last_validator_error,
    gpt_calls_made=gpt_calls_made,
    decision_sources=decision_sources,
    budget_extension_triggered=budget_extension_triggered,
    detail=detail or "no_tool_calls_completed",
  )
