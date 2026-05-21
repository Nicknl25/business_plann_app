"""Phase 9 P3.32 K9 — Handler C tool-calling session.

Migrates Handler C from `text.format.type=json_schema` strict-mode
iterative refinement to a tool-calling session that mirrors the
architecture of the GPT exhaustion (H2), funding (H3), and stage
ramp (H4) handlers.

Three tools are exposed:

  1. get_payroll_revenue_sanity_bounds(labor_intensity_class)
       -> per-class min/max + all-class bounds in one call.
  2. find_classes_accepting_target_payroll_pct(
         target_payroll_percent_of_revenue)
       -> accepting + rejecting class partition for a target value.
  3. propose_payroll_headcount_schedule(<full contract>)
       -> runs Layers A.1 + A.2 + A.3 against the proposal and
          returns validator outcome. K8 alternative-class
          enrichment is IN-LINE in the structured_failures.

Session semantics (matches H2/H3/H4):
  - HARD_CAP_TOOL_CALLS = 10 (flat; no two-phase budget per K9
    design memo Q1).
  - counts_against_run_budget=False on every API call (iter 17
    decoupling; doctrine.md §5 contract).
  - The session tracks the most recent
    propose_payroll_headcount_schedule call where
    validator_accepted=True as verified_commit_candidate. The
    candidate's built schedule_payload (post key-people injection
    + wage resolution) is returned to the caller.
  - Hard-fail on hard-cap-without-verified (per K9 design memo
    Q2 — payroll commits must be validator-accepted; no
    best-effort fallback).

Doctrine: this module is part of the GPT-as-authoring-source
pattern (doctrine.md §6); Handler C is the canonical writer of
expenses::Payroll. The K9 migration is retrospective alignment
of Handler C with the canonical tool-calling pattern used by
H2/H3/H4. See doctrine.md §10.4.

Imports happen lazily inside functions so this module loads
cleanly in contexts where the orchestrator package isn't on
sys.path.
"""

from __future__ import annotations

import contextvars as _payroll_contextvars
import copy
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


logger = logging.getLogger(__name__)


def _emit_handler_c_trace(
  *,
  call_n: int,
  tool_name: str,
  args: Dict[str, Any],
  tool_result: Dict[str, Any],
  became_verified_candidate: bool,
  tool_calls_used: int,
  verified_candidate_present: bool,
) -> None:
  """Phase 9 P3.32 K11 L-4 — durable per-call trace + runtime status for
  Handler C. Captures the tool-call sequence (which tools GPT called, in
  what order, with what arguments) and per-propose validator outcomes,
  so the equal-depth four-draft analysis and the Skyward call-#2 timeout
  diagnosis no longer depend on a completion-time report. Best-effort;
  never raises."""
  try:
    from client_intake_and_finmo.post_intake_handler_traces import (  # type: ignore
      HANDLER_C,
      record_handler_call,
      record_runtime_status,
    )
    res = tool_result or {}
    record_handler_call(
      handler=HANDLER_C,
      call_n=int(call_n),
      payload={
        "tool_name": tool_name,
        "arguments": args,
        "validator_accepted": res.get("validator_accepted"),
        "validator_error_code": res.get("validator_error_code"),
        "validator_error_text": str(res.get("validator_error_text") or "")[:3000],
        "structured_failures": res.get("structured_failures"),
        "tool_result_keys": sorted(str(k) for k in res.keys()),
        "became_verified_candidate": bool(became_verified_candidate),
      },
    )
    record_runtime_status(
      handler=HANDLER_C,
      status={
        "tool_calls_used": int(tool_calls_used),
        "hard_cap": int(HARD_CAP_TOOL_CALLS),
        "budget_remaining": int(HARD_CAP_TOOL_CALLS - tool_calls_used),
        "last_tool_name": tool_name,
        "verified_candidate_present": bool(verified_candidate_present),
        "last_validator_accepted": res.get("validator_accepted"),
      },
    )
  except Exception:
    pass


HARD_CAP_TOOL_CALLS: int = 10
MAX_TOOL_CALLS: int = HARD_CAP_TOOL_CALLS
COUNTS_AGAINST_RUN_BUDGET: bool = False


_TOOL_NAME_GET_BOUNDS: str = "get_payroll_revenue_sanity_bounds"
_TOOL_NAME_FIND_CLASSES: str = "find_classes_accepting_target_payroll_pct"
_TOOL_NAME_PROPOSE: str = "propose_payroll_headcount_schedule"


_PAYROLL_TOOL_SESSION_GPT_CALL_COUNT: "_payroll_contextvars.ContextVar[Optional[int]]" = (
  _payroll_contextvars.ContextVar(
    "payroll_tool_calling_session_gpt_call_count",
    default=None,
  )
)


def _machinery_fail_fast(
  operation: str,
  message: str,
  details: Optional[Dict[str, Any]] = None,
) -> None:
  from client_intake_and_finmo.fail_fast.common import (  # type: ignore
    PostIntakePreconditionFailed,
  )
  raise PostIntakePreconditionFailed(
    operation=str(operation or "").strip() or "payroll_tool_calling_session_machinery_violation",
    pipeline_stage="payroll_tool_calling_session",
    expected="payroll tool-calling-session machinery intact",
    actual=str(message or "").strip()[:600],
    details=details or {},
  )


def _assert_state_intact(
  *,
  loop_round_index: int,
  input_items: Any,
  history: Any,
  verified_commit_candidate: Any,
) -> None:
  if not isinstance(input_items, list):
    _machinery_fail_fast(
      "payroll_tool_calling_session_state_corruption",
      f"loop_round_index={loop_round_index} entered with malformed input_items",
      details={"input_items_type": type(input_items).__name__},
    )
  if not isinstance(history, list):
    _machinery_fail_fast(
      "payroll_tool_calling_session_state_corruption",
      f"loop_round_index={loop_round_index} entered with malformed history",
      details={"history_type": type(history).__name__},
    )
  if verified_commit_candidate is not None and not isinstance(verified_commit_candidate, PayrollToolCallRecord):
    _machinery_fail_fast(
      "payroll_tool_calling_session_state_corruption",
      "verified_commit_candidate has unexpected type",
      details={"candidate_type": type(verified_commit_candidate).__name__},
    )


def _assert_budget_decoupled(
  *,
  loop_round_index: int,
  counts_against_run_budget_arg: bool,
) -> None:
  if bool(counts_against_run_budget_arg):
    _machinery_fail_fast(
      "payroll_tool_calling_session_budget_decoupling_violation",
      (
        f"loop_round_index={loop_round_index} attempted GPT call with "
        "counts_against_run_budget=True; doctrine.md §5 contract is "
        "False for handler tool-calling sessions"
      ),
      details={"loop_round_index": int(loop_round_index)},
    )


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


def _build_get_bounds_tool_definition() -> Dict[str, Any]:
  return {
    "type": "function",
    "name": _TOOL_NAME_GET_BOUNDS,
    "description": (
      "Look up the authoritative per-class min/max target_payroll_"
      "percent_of_revenue bounds for a given labor_intensity_class. "
      "Returns the bounds for the chosen class AND the full all_class_"
      "bounds list (one call gives you the picture for every class in "
      "the policy). Source: post_intake_headcount_policy_lookup."
      "payroll_revenue_sanity_bounds_json."
    ),
    "strict": True,
    "parameters": {
      "type": "object",
      "additionalProperties": False,
      "required": ["labor_intensity_class"],
      "properties": {
        "labor_intensity_class": {
          "type": "string",
          "enum": ["low", "medium", "high", "expert"],
        },
      },
    },
  }


def _build_find_classes_tool_definition() -> Dict[str, Any]:
  return {
    "type": "function",
    "name": _TOOL_NAME_FIND_CLASSES,
    "description": (
      "Given a candidate target_payroll_percent_of_revenue value, "
      "returns the labor_intensity_class options whose policy bounds "
      "ACCEPT the value (accepting_classes) and those that REJECT it "
      "(rejecting_classes). Call this when stuck on a (class, target) "
      "rejection: the result names the alternative classes that would "
      "accept your current target. Or call it before picking a class "
      "if the operating model points you at a specific payroll/revenue "
      "ratio. Source: same policy table as Tool 1."
    ),
    "strict": True,
    "parameters": {
      "type": "object",
      "additionalProperties": False,
      "required": ["target_payroll_percent_of_revenue"],
      "properties": {
        "target_payroll_percent_of_revenue": {"type": "number"},
      },
    },
  }


def _build_propose_tool_definition(*, business_naics: Optional[str]) -> Dict[str, Any]:
  """Tool 3 — propose a full payroll_headcount_schedule for validation.

  Reuses the existing strict-mode contract schema builder verbatim
  (per K9 design memo Q3 approval). No parallel schema definition.
  """
  from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
    post_intake_gpt_contract_openai_schema,
  )
  parameters = post_intake_gpt_contract_openai_schema(
    contract_name="payroll_headcount_schedule",
    business_naics=str(business_naics or "").strip() or None,
  )
  return {
    "type": "function",
    "name": _TOOL_NAME_PROPOSE,
    "description": (
      "Submit a full payroll_headcount_schedule (capacity_labor_model, "
      "labor_intensity_class, wage_positioning_tier, wage_positioning_"
      "multiplier, capacity_units_per_supporting_fte, target_payroll_"
      "percent_of_revenue, payroll_headcount_grid Q1-Q20, rationale) "
      "for validation. The tool runs the same Layers A.1 + A.2 + A.3 "
      "validator chain the production system uses and returns "
      "{validator_accepted: bool, structured_failures: [...]}. When a "
      "target_payroll_percent_of_revenue out_of_range failure fires, "
      "structured_failures[i].alternatives.accepting_classes names the "
      "classes that would accept your value. Iterate until validator_"
      "accepted is true. The system commits your most-recent accepted "
      "proposal automatically; you do not produce a separate final-"
      "answer JSON."
    ),
    "strict": True,
    "parameters": parameters,
  }


# ---------------------------------------------------------------------------
# Tool dispatchers
# ---------------------------------------------------------------------------


def _dispatch_get_bounds(
  args: Dict[str, Any],
  *,
  policy: Dict[str, Any],
) -> Dict[str, Any]:
  cls = str(args.get("labor_intensity_class") or "").strip().lower()
  bounds_map = policy.get("payroll_revenue_sanity_bounds")
  if not isinstance(bounds_map, dict) or not bounds_map:
    return {
      "error": "policy_bounds_missing",
      "detail": "post_intake_headcount_policy_lookup.payroll_revenue_sanity_bounds_json is empty.",
    }
  if cls not in bounds_map:
    return {
      "error": "labor_intensity_class_not_in_policy",
      "labor_intensity_class": cls,
      "valid_classes": sorted(bounds_map.keys()),
    }
  current = bounds_map[cls]
  all_class_bounds: List[Dict[str, Any]] = []
  for name in sorted(bounds_map.keys()):
    item = bounds_map.get(name) or {}
    if not isinstance(item, dict):
      continue
    try:
      mn = float(item.get("min_pct"))
      mx = float(item.get("max_pct"))
    except (TypeError, ValueError):
      continue
    all_class_bounds.append({
      "labor_intensity_class": str(name).lower(),
      "min_pct": round(mn, 6),
      "max_pct": round(mx, 6),
    })
  return {
    "labor_intensity_class": cls,
    "min_pct": round(float(current.get("min_pct") or 0.0), 6),
    "max_pct": round(float(current.get("max_pct") or 0.0), 6),
    "tolerance_pct": round(float(policy.get("payroll_revenue_sanity_tolerance_pct") or 0.0), 6),
    "relative_tolerance": round(float(policy.get("payroll_revenue_sanity_relative_tolerance") or 0.0), 6),
    "all_class_bounds": all_class_bounds,
    "source_table": "post_intake_headcount_policy_lookup",
    "policy_code": str(policy.get("policy_code") or "default"),
  }


def _dispatch_find_classes(args: Dict[str, Any]) -> Dict[str, Any]:
  from client_intake_and_finmo.post_intake_headcount.lookup import (  # type: ignore
    intensity_classes_accepting_target_payroll_pct,
    post_intake_headcount_policy_for,
  )
  raw = args.get("target_payroll_percent_of_revenue")
  try:
    value = float(raw)
  except (TypeError, ValueError):
    return {"error": "target_must_be_numeric", "received": raw}
  accepting = intensity_classes_accepting_target_payroll_pct(value)
  accepting_classes = {entry.get("labor_intensity_class") for entry in accepting}
  policy = post_intake_headcount_policy_for(policy_code="default") or {}
  bounds_map = policy.get("payroll_revenue_sanity_bounds") or {}
  rejecting: List[Dict[str, Any]] = []
  for name in sorted(bounds_map.keys()):
    if name in accepting_classes:
      continue
    item = bounds_map.get(name) or {}
    if not isinstance(item, dict):
      continue
    try:
      mn = float(item.get("min_pct"))
      mx = float(item.get("max_pct"))
    except (TypeError, ValueError):
      continue
    rejecting.append({
      "labor_intensity_class": str(name).lower(),
      "min_pct": round(mn, 6),
      "max_pct": round(mx, 6),
    })
  return {
    "target_payroll_percent_of_revenue": round(value, 6),
    "accepting_classes": accepting,
    "rejecting_classes": rejecting,
    "source_table": "post_intake_headcount_policy_lookup",
  }


@dataclass
class _ProposeDispatchOutcome:
  tool_result: Dict[str, Any]
  schedule_payload: Optional[Dict[str, Any]] = None


def _dispatch_propose(
  args: Dict[str, Any],
  *,
  draft_id: Any,
  client_id: Any,
  model_input_json: Optional[Dict[str, Any]],
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  resolved_people_json: Optional[Dict[str, Any]],
) -> _ProposeDispatchOutcome:
  """Run the full Layer A.1 + A.2 + A.3 validator chain on GPT's
  proposed contract. Returns the tool_result that goes back to GPT,
  plus the built schedule_payload when validation passes.
  """
  from client_intake_and_finmo.fail_fast.common import (  # type: ignore
    PostIntakePreconditionFailed,
  )
  from client_intake_and_finmo.post_intake_headcount.schedule import (  # type: ignore
    _PAYROLL_LAYER_A2_WRAPPER_CODES,
    _PAYROLL_LAYER_A3_CODE,
    _assert_payroll_contract_economic_feasible_for_retry,
    _compact_payroll_failure_for_gpt,
    build_payroll_headcount_payload_from_contract,
    validate_payroll_headcount_contract_payload,
  )
  from client_intake_and_finmo.post_intake_headcount.lookup import (  # type: ignore
    intensity_classes_accepting_target_payroll_pct,
  )
  from client_intake_and_finmo.post_intake_headcount.payroll_validator_translator import (  # type: ignore
    translate_payroll_validator_codes,
  )

  try:
    contract = validate_payroll_headcount_contract_payload(args)
    schedule_payload = build_payroll_headcount_payload_from_contract(
      contract,
      draft_id=draft_id,
      client_id=client_id,
      model_input_json=model_input_json,
      business_facts=business_facts,
      ops_json=ops_json,
      people_json=resolved_people_json,
    )
    _assert_payroll_contract_economic_feasible_for_retry(
      payroll_headcount=copy.deepcopy(schedule_payload),
      model_input_json=copy.deepcopy(model_input_json),
      stage="payroll_headcount_contract_economic_feasibility",
    )
  except PostIntakePreconditionFailed:
    # Machinery violation — not GPT-fixable. Surface as-is.
    raise
  except RuntimeError as exc:
    exc_code = str(getattr(exc, "code", "") or "").strip()
    exc_message = str(exc) or ""
    details_raw = getattr(exc, "details", {})
    details = details_raw if isinstance(details_raw, dict) else {}

    if exc_code == _PAYROLL_LAYER_A3_CODE:
      compact_source: Dict[str, Any] = {
        "error": exc_message,
        "violations": details.get("violations") or [],
      }
      for key, value in details.items():
        if key != "violations":
          compact_source[key] = value
      return _ProposeDispatchOutcome(
        tool_result={
          "validator_accepted": False,
          "validator_error_code": exc_code,
          "validator_error_text": exc_message[:6000],
          "compacted_violations": _compact_payroll_failure_for_gpt(compact_source),
        },
      )

    if exc_code in _PAYROLL_LAYER_A2_WRAPPER_CODES:
      codes = details.get("errors") or []
      translated = translate_payroll_validator_codes(codes)
      if not isinstance(translated, dict) or "structured_failures" not in translated:
        _machinery_fail_fast(
          "payroll_validator_translator_malformed_output",
          "translator returned malformed result",
          details={"translated_type": type(translated).__name__},
        )
      if codes and not translated.get("structured_failures"):
        _machinery_fail_fast(
          "payroll_validator_translator_malformed_output",
          (
            f"translator returned empty structured_failures despite "
            f"{len(codes)} input code(s)"
          ),
          details={"input_codes": list(codes)[:10]},
        )
      structured_failures = translated["structured_failures"]
      # K8 enrichment IN-LINE — for each out_of_range failure on
      # target_payroll_percent_of_revenue, attach the alternative
      # accepting classes directly to the failure entry. This
      # replaces the buried-in-user-JSON enrichment from the
      # pre-K9 iterative refinement loop.
      for failure in structured_failures:
        if not isinstance(failure, dict):
          continue
        if (
          failure.get("field") != "target_payroll_percent_of_revenue"
          or failure.get("category") != "out_of_range"
          or failure.get("actual_value") is None
        ):
          continue
        try:
          alternatives = intensity_classes_accepting_target_payroll_pct(
            float(failure["actual_value"])
          )
        except Exception:
          alternatives = []
        failure["alternatives"] = {"accepting_classes": alternatives}
        failure["guidance"] = (
          "Either move target into the required_range for the "
          "currently-chosen labor_intensity_class, OR switch class "
          "to one in alternatives.accepting_classes (which already "
          "accept your current target). Both resolutions are valid; "
          "choose whichever better fits the operating model."
        )
      return _ProposeDispatchOutcome(
        tool_result={
          "validator_accepted": False,
          "validator_error_code": exc_code,
          "validator_error_text": exc_message[:6000],
          "structured_failures": structured_failures,
        },
      )

    # Class B — verbatim contract-table errors (A.1 + horizon +
    # rationale + sequence checks).
    raw_errors = details.get("errors") or []
    contract_table_errors = [str(item)[:500] for item in raw_errors][:20] or [
      exc_message[:500]
    ]
    return _ProposeDispatchOutcome(
      tool_result={
        "validator_accepted": False,
        "validator_error_code": exc_code,
        "validator_error_text": exc_message[:6000],
        "contract_table_errors": contract_table_errors,
      },
    )

  # Success — return summary + the built schedule_payload (to be
  # remembered by the session as the commit candidate).
  return _ProposeDispatchOutcome(
    tool_result={
      "validator_accepted": True,
      "summary": {
        "labor_intensity_class": contract.get("labor_intensity_class"),
        "target_payroll_percent_of_revenue": contract.get("target_payroll_percent_of_revenue"),
        "wage_positioning_tier": contract.get("wage_positioning_tier"),
        "capacity_labor_model": contract.get("capacity_labor_model"),
        "rows_count": len(schedule_payload.get("rows") or []),
      },
    },
    schedule_payload=schedule_payload,
  )


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


SYSTEM_PROMPT: str = (
  "You are authoring a 20-quarter payroll headcount schedule for a "
  "business plan. The schedule pins capacity_labor_model, labor_"
  "intensity_class, wage_positioning_tier, wage_positioning_"
  "multiplier, capacity_units_per_supporting_fte, target_payroll_"
  "percent_of_revenue, the per-OEWS-title FTE grid (start, hires, "
  "end) for Q1-Q20, and a rationale.\n"
  "\n"
  "You have three tools.\n"
  "\n"
  "1. get_payroll_revenue_sanity_bounds(labor_intensity_class) returns "
  "the authoritative per-class min/max target_payroll_percent_of_"
  "revenue bounds. The result includes the bounds for every class in "
  "the policy, so one call gives you the full picture.\n"
  "\n"
  "2. find_classes_accepting_target_payroll_pct(target_payroll_"
  "percent_of_revenue) returns the classes whose bounds accept a "
  "given target value. Call this when the operating model points you "
  "at a specific payroll/revenue ratio and you need to pick the class "
  "that fits. Or call it when propose_payroll_headcount_schedule has "
  "rejected a (class, target) pairing — the tool names the "
  "alternative classes that accept your target.\n"
  "\n"
  "3. propose_payroll_headcount_schedule(...) submits a full schedule "
  "for validation. The tool returns validator_accepted: true OR false "
  "with structured failures. Iterate until validator_accepted is "
  "true. The system commits your most recent accepted proposal as "
  "the schedule; you do not produce a separate final-answer JSON.\n"
  "\n"
  "You may call the three tools in any order any number of times "
  "within the budget. Class and target are equally mutable. If a "
  "class you selected rejects your target, you may EITHER move the "
  "target into that class's band OR switch to a class whose band "
  "already accepts your target — both resolutions are valid; choose "
  "whichever better fits the operating model.\n"
  "\n"
  "Class selection: match labor_intensity_class to the operating "
  "model's actual labor intensity profile, NOT to the highest "
  "policy-permitted band. The OPERATING CONTEXT carries an "
  "intake_implied_operating_intensity block with the operator's "
  "stated payroll/revenue ratio — one signal among several. When "
  "multiple classes accept a candidate target, prefer the class "
  "whose bounds match the operating model's reality (e.g. simple "
  "commodity production / retail typically operates in the lower "
  "classes; specialized-labor service operations and transportation "
  "typically operate in the higher classes). Do not default to "
  "'high' or 'expert' simply because the policy allows it.\n"
  "\n"
  "When iterating: do not reuse a (class, target) pairing that has "
  "already been rejected. The structured failure names the "
  "alternatives — use them.\n"
  "\n"
  "Decimal vs percent: target_payroll_percent_of_revenue is a "
  "decimal. 0.45 means 45 percent. Do NOT emit 45 (which would be "
  "4500 percent) and do NOT emit 0.045 (which would be 4.5 percent)."
)


def _build_initial_user_prompt(
  *,
  request_context: Dict[str, Any],
  external_seed_text: Optional[str],
) -> str:
  """Pack the per-business operating context into the initial user
  prompt. Replaces the pre-K9 prose paraphrase of per-class bands
  (now via Tool 1) and the "revise only named fields" framing
  (no longer applicable to tool-calling).
  """
  context_block = json.dumps(
    request_context or {}, ensure_ascii=False, indent=2, default=str
  )
  preamble: List[str] = []
  if external_seed_text:
    preamble.append(
      "PRIOR FAILURE CONTEXT (from upstream caller):\n"
      f"{external_seed_text}\n"
      "Use this as Round-1 guidance; the iteration is otherwise open.\n"
    )
  preamble.append("OPERATING CONTEXT:")
  preamble.append(context_block)
  preamble.append("")
  preamble.append(
    "KEY-PEOPLE INJECTION:\n"
    "Python will inject the intake's key-people roster into your "
    "authored grid before final commit. Author supporting-staff OEWS "
    "titles and their FTE schedule only; do not include key people "
    "in your grid."
  )
  preamble.append(
    "\nOEWS TITLE SELECTION:\n"
    "Every oews_occ_title in payroll_headcount_grid must be an exact "
    "title from oews_title_catalog.title_candidates above. Each "
    "title you include must carry positive FTE in at least one "
    "quarter; do not author placeholder zero-FTE rows. Once a title "
    "carries positive FTE, it must continue through Q20 (no "
    "terminations)."
  )
  preamble.append(
    "\nCAPACITY MODEL:\n"
    "capacity_units_per_supporting_fte is your business-specific "
    "productivity assumption. Python derives the supported-capacity "
    "envelope from total average FTE * capacity_units_per_supporting_"
    "fte; revenue is constrained downstream by that envelope. Do not "
    "clip FTE to a hard capacity demand floor."
  )
  preamble.append(
    "\nSTAGE RAMP CONTRACT:\n"
    "The stage_ramp_contract in the OPERATING CONTEXT above is "
    "read-only context. Use it to align ramp shape; do not change "
    "ramp."
  )
  preamble.append(
    f"\nTASK:\n"
    f"Author the payroll headcount schedule. Call "
    f"{_TOOL_NAME_PROPOSE} when you are ready to submit. Iterate "
    f"until the tool returns validator_accepted: true."
  )
  return "\n".join(preamble)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PayrollToolCallRecord:
  call_n: int
  tool_name: str
  arguments: Dict[str, Any]
  result: Dict[str, Any]
  call_id: str = ""
  schedule_payload: Optional[Dict[str, Any]] = None

  def to_dict(self) -> Dict[str, Any]:
    return {
      "call_n": int(self.call_n),
      "call_id": self.call_id,
      "tool_name": self.tool_name,
      "validator_accepted": bool((self.result or {}).get("validator_accepted")),
      "validator_error_code": (self.result or {}).get("validator_error_code"),
    }


@dataclass
class PayrollToolCallSessionResult:
  status: str  # "verified" | "exhausted" | "failed_precondition"
  schedule_payload: Optional[Dict[str, Any]] = None
  tool_calls_used: int = 0
  tool_call_history: List[PayrollToolCallRecord] = field(default_factory=list)
  gpt_calls_made: int = 0
  decision_sources: List[str] = field(default_factory=list)
  last_validator_error_code: Optional[str] = None
  last_validator_error_text: Optional[str] = None
  detail: str = ""
  verified_commit_call_n: Optional[int] = None


# ---------------------------------------------------------------------------
# Session loop
# ---------------------------------------------------------------------------


def run_payroll_tool_calling_session(
  *,
  request_context: Dict[str, Any],
  policy: Dict[str, Any],
  business_naics: Optional[str],
  draft_id: Any,
  client_id: Any,
  model_input_json: Optional[Dict[str, Any]],
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  resolved_people_json: Optional[Dict[str, Any]],
  external_seed_text: Optional[str] = None,
  _call_gpt_turn: Optional[Callable[..., Dict[str, Any]]] = None,
) -> PayrollToolCallSessionResult:
  """Run the payroll tool-calling session.

  - GPT iterates by calling get_payroll_revenue_sanity_bounds,
    find_classes_accepting_target_payroll_pct, and
    propose_payroll_headcount_schedule in any order.
  - The session remembers the most recent propose tool call whose
    result was validator_accepted=True. On hard cap or assistant-
    stop, the candidate's built schedule_payload becomes the commit.
  - No best-effort fallback — hard-fail on hard-cap-without-verified
    (per K9 design memo Q2; payroll commits must be validator-
    accepted).

  Test seam: ``_call_gpt_turn`` for the Responses-API caller.
  """
  call_gpt_turn = _call_gpt_turn
  if call_gpt_turn is None:
    from client_intake_and_finmo.post_intake_solver._gpt_critic_io import (  # type: ignore
      call_gpt_responses_api_turn,
    )
    call_gpt_turn = call_gpt_responses_api_turn

  tool_def_get_bounds = _build_get_bounds_tool_definition()
  tool_def_find_classes = _build_find_classes_tool_definition()
  tool_def_propose = _build_propose_tool_definition(business_naics=business_naics)

  initial_user_prompt = _build_initial_user_prompt(
    request_context=request_context,
    external_seed_text=external_seed_text,
  )
  input_items: List[Dict[str, Any]] = [
    {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT.strip()}]},
    {"role": "user", "content": [{"type": "input_text", "text": initial_user_prompt}]},
  ]

  history: List[PayrollToolCallRecord] = []
  tool_calls_used = 0
  gpt_calls_made = 0
  decision_sources: List[str] = []
  verified_commit_candidate: Optional[PayrollToolCallRecord] = None
  detail = ""

  iter_token = _PAYROLL_TOOL_SESSION_GPT_CALL_COUNT.set(0)
  loop_round_index = 0
  try:
    while True:
      loop_round_index += 1
      _assert_state_intact(
        loop_round_index=loop_round_index,
        input_items=input_items,
        history=history,
        verified_commit_candidate=verified_commit_candidate,
      )
      if tool_calls_used >= HARD_CAP_TOOL_CALLS:
        detail = "hard_cap_tool_calls_reached"
        break

      _assert_budget_decoupled(
        loop_round_index=loop_round_index,
        counts_against_run_budget_arg=COUNTS_AGAINST_RUN_BUDGET,
      )
      turn_resp = call_gpt_turn(
        consultant_name=f"post_intake_payroll_handler_c_tool_call_turn_{tool_calls_used + 1}",
        input_items=input_items,
        tools=[tool_def_get_bounds, tool_def_find_classes, tool_def_propose],
        response_schema=None,
        schema_name=None,
        counts_against_run_budget=COUNTS_AGAINST_RUN_BUDGET,
      )
      _PAYROLL_TOOL_SESSION_GPT_CALL_COUNT.set(
        _PAYROLL_TOOL_SESSION_GPT_CALL_COUNT.get() + 1
      )
      gpt_calls_made += 1
      decision_sources.append(str(turn_resp.get("decision_source") or ""))
      decision_source = str(turn_resp.get("decision_source") or "")
      if decision_source != "python_proposer_plus_gpt_critic":
        from client_intake_and_finmo.fail_fast.common import (  # type: ignore
          PostIntakePreconditionFailed,
          convergence_test_mode_enabled,
        )
        if convergence_test_mode_enabled():
          raise PostIntakePreconditionFailed(
            operation="payroll_tool_calling_session_turn_failed",
            pipeline_stage="payroll_tool_calling_session",
            expected="decision_source=python_proposer_plus_gpt_critic",
            actual=decision_source,
            details={
              "tool_calls_used_before_failure": int(tool_calls_used),
              "gpt_calls_made_before_failure": int(gpt_calls_made),
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
        tool_name = str(call.get("name") or "").strip()
        call_id = str(call.get("call_id") or "")
        try:
          args = json.loads(call.get("arguments") or "{}")
          if not isinstance(args, dict):
            args = {}
        except Exception as exc:
          input_items.append({
            "type": "function_call_output",
            "call_id": call_id,
            "output": json.dumps(
              {"error": f"arguments_not_json: {type(exc).__name__}"},
              ensure_ascii=False,
            ),
          })
          continue

        schedule_payload_for_record: Optional[Dict[str, Any]] = None

        if tool_name == _TOOL_NAME_GET_BOUNDS:
          tool_result = _dispatch_get_bounds(args, policy=policy)
        elif tool_name == _TOOL_NAME_FIND_CLASSES:
          tool_result = _dispatch_find_classes(args)
        elif tool_name == _TOOL_NAME_PROPOSE:
          outcome = _dispatch_propose(
            args,
            draft_id=draft_id,
            client_id=client_id,
            model_input_json=model_input_json,
            business_facts=business_facts,
            ops_json=ops_json,
            resolved_people_json=resolved_people_json,
          )
          tool_result = outcome.tool_result
          schedule_payload_for_record = outcome.schedule_payload
        else:
          tool_result = {"error": f"unknown_tool_{tool_name}"}

        tool_calls_used += 1
        rec = PayrollToolCallRecord(
          call_n=tool_calls_used,
          tool_name=tool_name,
          arguments=args,
          result=tool_result,
          call_id=call_id,
          schedule_payload=schedule_payload_for_record,
        )
        history.append(rec)
        if (
          tool_name == _TOOL_NAME_PROPOSE
          and tool_result.get("validator_accepted") is True
          and schedule_payload_for_record is not None
        ):
          verified_commit_candidate = rec

        _emit_handler_c_trace(
          call_n=tool_calls_used,
          tool_name=tool_name,
          args=args,
          tool_result=tool_result,
          became_verified_candidate=(verified_commit_candidate is rec),
          tool_calls_used=tool_calls_used,
          verified_candidate_present=(verified_commit_candidate is not None),
        )

        input_items.append({
          "type": "function_call_output",
          "call_id": call_id,
          "output": json.dumps(tool_result, ensure_ascii=False, default=str),
        })
        if tool_calls_used >= HARD_CAP_TOOL_CALLS:
          break
  finally:
    _PAYROLL_TOOL_SESSION_GPT_CALL_COUNT.reset(iter_token)

  last_validator_error_code: Optional[str] = None
  last_validator_error_text: Optional[str] = None
  for rec in reversed(history):
    if rec.tool_name == _TOOL_NAME_PROPOSE:
      result = rec.result or {}
      if not result.get("validator_accepted"):
        last_validator_error_code = str(result.get("validator_error_code") or "") or None
        last_validator_error_text = str(result.get("validator_error_text") or "") or None
      break

  if verified_commit_candidate is not None:
    return PayrollToolCallSessionResult(
      status="verified",
      schedule_payload=verified_commit_candidate.schedule_payload,
      tool_calls_used=tool_calls_used,
      tool_call_history=history,
      gpt_calls_made=gpt_calls_made,
      decision_sources=decision_sources,
      last_validator_error_code=last_validator_error_code,
      last_validator_error_text=last_validator_error_text,
      detail=detail or "verified_commit_candidate",
      verified_commit_call_n=verified_commit_candidate.call_n,
    )

  return PayrollToolCallSessionResult(
    status="exhausted",
    schedule_payload=None,
    tool_calls_used=tool_calls_used,
    tool_call_history=history,
    gpt_calls_made=gpt_calls_made,
    decision_sources=decision_sources,
    last_validator_error_code=last_validator_error_code,
    last_validator_error_text=last_validator_error_text,
    detail=detail or "hard_cap_without_verified_commit",
  )
