"""Phase 9 Phase F — mode-based cash strategy entry point.

Restored f949316 invocation flow. Calls the runner.py cash-strategy
functions in the same order the convergence runner used at the golden
tag, so the cash pass:

  1. Seeds a minimum debt schedule (covers any negative-cash quarter
     with new long-term debt at the industry rate, leaves operator-
     stated opening debt at its operator-stated rate).
  2. Seeds the short-term debt current portion (splits LTD into
     short_term_debt + long_term_debt per the cash policy).
  3. Builds the cash strategy review context (per-quarter cash policy
     envelope, funding source policy, lever bounds, debt schedule
     snapshot, numeric solver contract). Mode is carried through
     ``selected_cash_strategy`` from financials_json.
  4. Runs the cash strategy review (Python proposer + GPT critic).
  5. Translates the GPT decision into an exact-update plan.
  6. Applies the exact updates against model_input + rebuilds FINMO.
  7. Re-applies the minimum debt schedule (post-cash floor).
  8. Re-applies the short-term debt current portion (post-cash floor).
  9. Surplus cleanup — distributions / debt repayment of true surplus
     above the cash ceiling per cash policy weights.
  10. Validates the post-pass state (buffer, surplus ceiling, debt
      schedule rules). Reverts to the pre-cash state on failure.

The funding source policy that excludes debt_issuance under chronic
gaps + material drag, and excludes other_equity when not justified by
chronic gaps or material leverage, is exercised inside step 3 (it
lives on ``runner._cash_strategy_funding_source_policy`` and runs
inside ``_build_cash_strategy_review_context_payload``).

Doctrine binding (unchanged from f949316):
  - Cash pass MAY adjust: debt_issuance, debt_repayment, owners_capital,
    other_equity, distributions, minimum cash buffer, short_term_debt_pct
  - Cash pass MAY NOT adjust: revenue, COGS, payroll, G&A, marketing,
    R&D, lease, pricing, utilization, capacity, EBITDA target tolerances
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


_DEFAULT_HORIZON = 20


@dataclass
class CashStrategyResult:
  cash_strategy_mode: str
  status: str = "completed"
  reason: Optional[str] = None
  applied_updates_count: int = 0
  total_debt_issued: float = 0.0
  total_distributions: float = 0.0
  total_owners_capital_added: float = 0.0
  total_other_equity_added: float = 0.0
  per_quarter: List[Dict[str, Any]] = field(default_factory=list)
  funding_source_policy: Dict[str, Any] = field(default_factory=dict)
  review_decision: Dict[str, Any] = field(default_factory=dict)
  second_pass_plan: Dict[str, Any] = field(default_factory=dict)
  second_pass_result: Dict[str, Any] = field(default_factory=dict)
  post_validation: Dict[str, Any] = field(default_factory=dict)

  def to_dict(self) -> Dict[str, Any]:
    return asdict(self)


def _ensure_cash_strategy_on_financials(
  financials_json: Optional[Dict[str, Any]],
  adaptive_policy: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Return a deep-copied financials_json with ``cash_strategy`` set.

  ``runner._resolved_cash_strategy`` reads ``cash_strategy`` /
  ``selected_cash_strategy`` off financials_json. Precedence:
    1. The OPERATOR'S intake selection (a stated fact — never overridden).
    2. adaptive_policy's carried value.
    3. EXECUTIVE CASH JUDGMENT posture — the manager's coherent-for-this-
       stage-and-leverage call, applied ONLY when intake left the posture
       empty (posture_applies is stamped False by the validator whenever
       the operator selected).
    4. The runner's own "balanced" default (no-judgment fallback).
  """
  out = copy.deepcopy(financials_json) if isinstance(financials_json, dict) else {}
  if str(out.get("cash_strategy") or "").strip() or str(out.get("selected_cash_strategy") or "").strip():
    return out
  if isinstance(adaptive_policy, dict):
    raw = (
      adaptive_policy.get("selected_cash_strategy")
      or adaptive_policy.get("cash_strategy")
      or ""
    )
    if str(raw or "").strip():
      out["cash_strategy"] = str(raw).strip()
      return out
  try:
    from client_intake_and_finmo.post_intake_cash.gpt_cash_judgment import (  # type: ignore
      cash_judgment_from_model_input,
    )
    judgment = cash_judgment_from_model_input(model_input_json)
    if (
      isinstance(judgment, dict)
      and bool(judgment.get("posture_applies"))
      and str(judgment.get("posture") or "").strip()
    ):
      out["cash_strategy"] = str(judgment["posture"]).strip()
  except Exception:
    pass
  return out


def _summarize_applied_totals(
  *,
  exact_updates: List[Dict[str, Any]],
) -> Dict[str, float]:
  """Walk applied_updates and bucket totals by lever role.

  We resolve lever_id → driver_key via the mapping module and
  accumulate the numeric flows that the Phase 9 acceptance gate /
  workbook reports surface.
  """
  from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
    post_intake_driver_target_single_lever_id_for_target_driver,
  )

  debt_issuance_lever = (
    post_intake_driver_target_single_lever_id_for_target_driver("debt_issuance") or ""
  ).strip()
  distributions_lever = (
    post_intake_driver_target_single_lever_id_for_target_driver("distributions") or ""
  ).strip()
  owners_capital_lever = (
    post_intake_driver_target_single_lever_id_for_target_driver("owners_capital") or ""
  ).strip()
  other_equity_lever = (
    post_intake_driver_target_single_lever_id_for_target_driver("other_equity") or ""
  ).strip()

  totals = {
    "total_debt_issued": 0.0,
    "total_distributions": 0.0,
    "total_owners_capital_added": 0.0,
    "total_other_equity_added": 0.0,
  }
  for update in exact_updates:
    if not isinstance(update, dict):
      continue
    lever_id = str(update.get("lever_id") or "").strip()
    try:
      value = float(update.get("exact_value") or 0.0)
    except Exception:
      value = 0.0
    if not lever_id:
      continue
    if lever_id == debt_issuance_lever:
      totals["total_debt_issued"] += value
    elif lever_id == distributions_lever:
      totals["total_distributions"] += value
    elif lever_id == owners_capital_lever:
      totals["total_owners_capital_added"] += value
    elif lever_id == other_equity_lever:
      totals["total_other_equity_added"] += value
  return totals


def run_mode_based_cash_strategy(
  *,
  draft_id: Optional[str] = None,
  planning_run_id: Optional[str] = None,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  industry_profile: Optional[Dict[str, Any]] = None,
  adaptive_policy: Optional[Dict[str, Any]] = None,
  business_facts: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  planning_mode: Optional[str] = None,
  planning_mode_reason: Optional[str] = None,
  prompt_file: Optional[str] = None,
  conn: Any = None,
  horizon: int = _DEFAULT_HORIZON,
  finmo_rebuild_callable: Optional[Any] = None,
) -> CashStrategyResult:
  """Phase 9 cash strategy entry point.

  Wires the runner.py cash-strategy sequence from f949316. Mutates
  ``model_input_json`` and ``finmo_json`` in place (matches the prior
  Phase 9 entry-point contract; downstream code expects the in-place
  effect). Returns a CashStrategyResult that carries the totals,
  the GPT decision, and the post-pass validation payload for the
  acceptance gate / completion trace.
  """
  del planning_run_id, industry_profile, conn  # unused in the runner-driven flow
  del finmo_rebuild_callable  # FINMO rebuild now happens inside the runner steps

  from client_intake_and_finmo.post_intake_cash import runner as _cash_runner  # type: ignore
  from client_intake_and_finmo.finmo_bridge import build_python_finmo_json  # type: ignore

  financials_for_runner = _ensure_cash_strategy_on_financials(
    financials_json, adaptive_policy, model_input_json=model_input_json,
  )
  cash_strategy_mode = _cash_runner._resolved_cash_strategy(financials_for_runner, adaptive_policy or {})

  pre_cash_model_input_json = copy.deepcopy(model_input_json or {})
  pre_cash_finmo_json = copy.deepcopy(finmo_json or {})

  draft_id_str = str(draft_id or "").strip()
  business_facts_dict = copy.deepcopy(business_facts) if isinstance(business_facts, dict) else {}
  ops_json_dict = copy.deepcopy(ops_json) if isinstance(ops_json, dict) else {}
  planning_mode_str = str(planning_mode or "").strip()
  planning_mode_reason_str = str(planning_mode_reason or "").strip()
  prompt_file_str = str(prompt_file or "").strip()

  # Step 1 — minimum debt schedule (pre-review seed). Covers any
  # negative-cash quarter with new long-term debt at the industry
  # rate. Does NOT touch operator-stated opening debt — only adds
  # incremental issuance.
  seed_after_min_debt = _cash_runner._apply_cash_pass_minimum_debt_schedule(
    cash_strategy_result={
      "updated_model_input_json": copy.deepcopy(pre_cash_model_input_json),
      "updated_finmo_json": copy.deepcopy(pre_cash_finmo_json),
      "applied_updates": [],
    },
    financials_json=copy.deepcopy(financials_for_runner),
  )
  if isinstance(seed_after_min_debt.get("updated_model_input_json"), dict):
    pre_cash_model_input_json = copy.deepcopy(seed_after_min_debt["updated_model_input_json"])
  if isinstance(seed_after_min_debt.get("updated_finmo_json"), dict):
    pre_cash_finmo_json = copy.deepcopy(seed_after_min_debt["updated_finmo_json"])

  # Phase 9 P3.10 STD canonical-source layer 3 hotfix — Step 2 (short-
  # term debt current portion seed) was removed. FINMO and the workbook
  # now derive short_term_debt directly from the schedule's per-quarter
  # principal repayment for q+1..q+4 (Layers 1+2). The STD% lever is no
  # longer written by anyone.

  # Step 3 — build the cash strategy review context. Internally invokes
  # _cash_strategy_funding_source_policy() for the smart funding source
  # gate (excludes debt_issuance under chronic gaps + material drag,
  # excludes other_equity when not justified). Mode is read off
  # financials_for_runner["cash_strategy"].
  try:
    cash_strategy_review_context = _cash_runner._build_cash_strategy_review_context_payload(
      draft_id=draft_id_str,
      business_facts=business_facts_dict,
      ops_json=ops_json_dict,
      financials_json=copy.deepcopy(financials_for_runner),
      planning_mode=planning_mode_str,
      planning_mode_reason=planning_mode_reason_str,
      prompt_file=prompt_file_str,
      solved_model_input_json=copy.deepcopy(pre_cash_model_input_json),
      solved_finmo_json=copy.deepcopy(pre_cash_finmo_json),
      controller_resolution_state={},
      prior_numeric_feedback={},
    )
  except Exception as exc:
    # Phase 9 P3.10 Commit 3 — under test mode, cash-strategy step
    # failures hard-fail. The cash strategy has no Python floor — if
    # context build fails, every downstream step operates on garbage.
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      PostIntakePreconditionFailed,
      convergence_test_mode_enabled,
    )
    if convergence_test_mode_enabled():
      raise PostIntakePreconditionFailed(
        operation="cash_strategy_build_context_failed",
        pipeline_stage="post_intake_cash_strategy",
        expected="_build_cash_strategy_review_context_payload returns context dict",
        actual=f"{type(exc).__name__}: {str(exc)[:200]}",
        details={
          "cash_strategy_mode": cash_strategy_mode,
          "draft_id": draft_id_str,
        },
        cause=exc,
      ) from exc
    return _failure_result(
      cash_strategy_mode=cash_strategy_mode,
      reason=f"build_context_failed: {type(exc).__name__}: {str(exc)[:300]}",
    )
  funding_source_policy_payload = (
    cash_strategy_review_context.get("funding_source_policy") or {}
    if isinstance(cash_strategy_review_context, dict)
    else {}
  )

  # Step 4 — run cash strategy review (Python proposer + GPT critic).
  try:
    cash_strategy_review_decision = _cash_runner._run_cash_strategy_review_openai(
      draft_id=draft_id_str,
      business_facts=business_facts_dict,
      ops_json=ops_json_dict,
      financials_json=copy.deepcopy(financials_for_runner),
      planning_mode=planning_mode_str,
      planning_mode_reason=planning_mode_reason_str,
      planning_mode_prompt_file=prompt_file_str,
      first_pass_handoff={},
      cash_strategy_review_context=copy.deepcopy(cash_strategy_review_context),
      solved_model_input_json=copy.deepcopy(pre_cash_model_input_json),
      solved_finmo_json=copy.deepcopy(pre_cash_finmo_json),
      prior_numeric_feedback={},
      controller_retry_context={},
    )
  except Exception as exc:
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      PostIntakePreconditionFailed,
      convergence_test_mode_enabled,
    )
    if convergence_test_mode_enabled():
      raise PostIntakePreconditionFailed(
        operation="cash_strategy_review_openai_failed",
        pipeline_stage="post_intake_cash_strategy",
        expected="_run_cash_strategy_review_openai returns decision dict",
        actual=f"{type(exc).__name__}: {str(exc)[:200]}",
        details={
          "cash_strategy_mode": cash_strategy_mode,
          "draft_id": draft_id_str,
        },
        cause=exc,
      ) from exc
    return _failure_result(
      cash_strategy_mode=cash_strategy_mode,
      funding_source_policy=funding_source_policy_payload,
      reason=f"review_failed: {type(exc).__name__}: {str(exc)[:300]}",
    )
  if not isinstance(cash_strategy_review_decision, dict):
    cash_strategy_review_decision = {}
  # Mirror the f949316 pattern of attaching the context to the decision so
  # the second-pass plan builder can lift lever_bounds / required-funding
  # quarters / numeric solver contract from a single payload.
  review_payload_with_context = copy.deepcopy(cash_strategy_review_decision)
  review_payload_with_context["cash_strategy_review_context"] = copy.deepcopy(cash_strategy_review_context)
  review_payload_with_context["numeric_solver_contract"] = copy.deepcopy(
    cash_strategy_review_context.get("numeric_solver_contract")
    if isinstance(cash_strategy_review_context.get("numeric_solver_contract"), dict)
    else {}
  )

  # Step 5 — translate GPT decision into exact-update plan. Internally
  # invokes _translate_cash_strategy_adjustment per quarter against the
  # lever_bounds in the review context.
  try:
    cash_strategy_second_pass_plan = _cash_runner._build_cash_strategy_second_pass_plan(
      review_decision_payload=copy.deepcopy(review_payload_with_context),
      solved_model_input_json=copy.deepcopy(pre_cash_model_input_json),
      financials_json=copy.deepcopy(financials_for_runner),
      numeric_solver_contract=copy.deepcopy(
        cash_strategy_review_context.get("numeric_solver_contract")
        if isinstance(cash_strategy_review_context.get("numeric_solver_contract"), dict)
        else {}
      ),
    )
  except Exception as exc:
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      PostIntakePreconditionFailed,
      convergence_test_mode_enabled,
    )
    if convergence_test_mode_enabled():
      raise PostIntakePreconditionFailed(
        operation="cash_strategy_second_pass_plan_failed",
        pipeline_stage="post_intake_cash_strategy",
        expected="_build_cash_strategy_second_pass_plan returns plan dict",
        actual=f"{type(exc).__name__}: {str(exc)[:200]}",
        details={"cash_strategy_mode": cash_strategy_mode},
        cause=exc,
      ) from exc
    return _failure_result(
      cash_strategy_mode=cash_strategy_mode,
      funding_source_policy=funding_source_policy_payload,
      review_decision=cash_strategy_review_decision,
      reason=f"plan_failed: {type(exc).__name__}: {str(exc)[:300]}",
    )

  # Step 6 — apply the exact updates against model_input and rebuild FINMO.
  try:
    cash_strategy_second_pass_result = _cash_runner._apply_cash_strategy_exact_updates(
      review_plan=copy.deepcopy(cash_strategy_second_pass_plan),
      current_model_input_json=copy.deepcopy(pre_cash_model_input_json),
      current_finmo_json=copy.deepcopy(pre_cash_finmo_json),
    )
  except Exception as exc:
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      PostIntakePreconditionFailed,
      convergence_test_mode_enabled,
    )
    if convergence_test_mode_enabled():
      raise PostIntakePreconditionFailed(
        operation="cash_strategy_apply_exact_updates_failed",
        pipeline_stage="post_intake_cash_strategy",
        expected="_apply_cash_strategy_exact_updates returns updated state dict",
        actual=f"{type(exc).__name__}: {str(exc)[:200]}",
        details={"cash_strategy_mode": cash_strategy_mode},
        cause=exc,
      ) from exc
    return _failure_result(
      cash_strategy_mode=cash_strategy_mode,
      funding_source_policy=funding_source_policy_payload,
      review_decision=cash_strategy_review_decision,
      second_pass_plan=cash_strategy_second_pass_plan,
      reason=f"apply_failed: {type(exc).__name__}: {str(exc)[:300]}",
    )

  # Step 7 — re-apply the minimum debt schedule on the post-update state.
  cash_strategy_second_pass_result = _cash_runner._apply_cash_pass_minimum_debt_schedule(
    cash_strategy_result=copy.deepcopy(cash_strategy_second_pass_result),
    financials_json=copy.deepcopy(financials_for_runner),
  )

  # Phase 9 P3.10 STD canonical-source layer 3 hotfix — Step 8 (re-apply
  # short-term debt current portion) was removed. STD is derived from
  # the schedule's per-quarter principal repayment, not from a written-
  # back ratio lever.

  # Step 9 — surplus cleanup (distributions / debt repayment of true
  # surplus above the cash ceiling per cash policy weights).
  cash_strategy_second_pass_result = _cash_runner._apply_cash_policy_surplus_cleanup(
    cash_strategy_result=copy.deepcopy(cash_strategy_second_pass_result),
    financials_json=copy.deepcopy(financials_for_runner),
  )

  # Phase 9 P3.20 Part 3 Stage 3 — Mirror Flavor 1 single source of
  # truth for FINMO. Rebuild FINMO ONCE from the cash strategy's
  # updated_model_input_json BEFORE the post-pass validator runs.
  # Store the rebuilt FINMO back into cash_strategy_second_pass_result
  # so the validator, the handler trigger, the handler itself, and
  # the downstream final state ALL see the same FINMO.
  #
  # Pre-Stage-3 flow:
  #   1. Cash sub-steps produce cash_strategy_second_pass_result with
  #      updated_finmo_json (sub-step's internal rebuild).
  #   2. Validator validates that FINMO.
  #   3. Handler (if invoked) operates on that FINMO; handler's
  #      internal rebuild via build_finmo callback produces its own
  #      updated_finmo_json.
  #   4. Final state inherits whichever FINMO won.
  #   5. OUTER REBUILD at end of function: build_python_finmo_json
  #      from final_model_input_json OVERWRITES final_finmo_json.
  #      If this rebuild produces a different result than steps 1-4
  #      saw, the validator/handler made decisions on a stale view
  #      and downstream sees a different state.
  #
  # Post-Stage-3 flow:
  #   1. Cash sub-steps produce cash_strategy_second_pass_result.
  #   2. [NEW] Rebuild FINMO ONCE from updated_model_input_json.
  #      Store in cash_strategy_second_pass_result. This is the
  #      canonical FINMO for everything that follows.
  #   3. Validator validates that canonical FINMO.
  #   4. Handler operates on the canonical FINMO; handler's internal
  #      rebuild is consistent by construction.
  #   5. Final state reads cash_strategy_second_pass_result
  #      (already canonical).
  #   6. Outer rebuild REMOVED -- redundant.
  #
  # If the rebuild itself fails, raise under test mode so machinery
  # divergence is surfaced loudly; under production fall through and
  # let the validator observe whatever broken state the cash sub-steps
  # emitted. This preserves the Phase 9 P3.10 Commit 4 intent (final
  # FINMO rebuild failure raises under test mode) the previous outer
  # rebuild encoded -- now applied at the hoisted pre-validator site.
  try:
    from client_intake_and_finmo.finmo_bridge import (  # type: ignore
      build_python_finmo_json as _build_python_finmo_json,
    )
    _rebuilt_pre_validation = _build_python_finmo_json(
      model_input_json=copy.deepcopy(
        cash_strategy_second_pass_result.get("updated_model_input_json") or {}
      )
    )
    if isinstance(_rebuilt_pre_validation, dict) and _rebuilt_pre_validation:
      cash_strategy_second_pass_result["updated_finmo_json"] = _rebuilt_pre_validation
  except Exception as _stage3_rebuild_exc:
    # Phase 9 P3.10 Commit 4 — final FINMO rebuild failure raises
    # under test mode. The "second guard" justification is correct for
    # production but masks a state divergence when test mode is on.
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      PostIntakePreconditionFailed as _Stage3PostIntakePreconditionFailed,
      convergence_test_mode_enabled as _stage3_convergence_test_mode_enabled,
    )
    if _stage3_convergence_test_mode_enabled():
      raise _Stage3PostIntakePreconditionFailed(
        operation="cash_strategy_final_finmo_rebuild_failed",
        pipeline_stage="post_intake_cash_strategy",
        expected="build_python_finmo_json rebuilds successfully before post-pass validation",
        actual=f"{type(_stage3_rebuild_exc).__name__}: {str(_stage3_rebuild_exc)[:200]}",
        details={"cash_strategy_mode": cash_strategy_mode},
        cause=_stage3_rebuild_exc,
      ) from _stage3_rebuild_exc
    # Production-mode legacy path: fall through; the validator will
    # see whatever broken state the cash sub-steps emitted and
    # surface it through normal error paths.

  # Step 10 — post-pass validation (buffer, surplus ceiling, debt
  # schedule). Phase 9 P3.20 Part 3 Stage 1 -- never revert on
  # validation failure. Stage 3 -- validator sees the canonical
  # rebuilt FINMO from above; same FINMO that downstream consumes.
  try:
    cash_post_validation = _cash_runner._validate_cash_strategy_post_pass(
      ops_json=ops_json_dict,
      financials_json=copy.deepcopy(financials_for_runner),
      baseline_issue_ledger=[],
      candidate_model_input_json=copy.deepcopy(
        cash_strategy_second_pass_result.get("updated_model_input_json") or {}
      ),
      candidate_finmo_json=copy.deepcopy(
        cash_strategy_second_pass_result.get("updated_finmo_json") or {}
      ),
      iteration=1,
      planning_mode=planning_mode_str or None,
    )
  except Exception as exc:
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      PostIntakePreconditionFailed,
      convergence_test_mode_enabled,
    )
    if convergence_test_mode_enabled():
      raise PostIntakePreconditionFailed(
        operation="cash_strategy_post_pass_validation_failed",
        pipeline_stage="post_intake_cash_strategy",
        expected="_validate_cash_strategy_post_pass returns validation dict",
        actual=f"{type(exc).__name__}: {str(exc)[:200]}",
        details={"cash_strategy_mode": cash_strategy_mode},
        cause=exc,
      ) from exc
    cash_post_validation = {
      "status": "validation_failed",
      "keep_changes": False,
      "error": f"{type(exc).__name__}: {str(exc)[:300]}",
    }

  keep_changes = bool(cash_post_validation.get("keep_changes", True))

  # iter 19 Stage 4 correction — funding handler engagement.
  # Phase 9 P3.20 Part 3 Stage 2 — trigger condition relaxed.
  # Pre-Stage-2 the handler was invoked ONLY when
  # `cash_buffer_violations_for_handler` was non-empty. That gate
  # was wrong: the P3.19 Phase 3a FAIL run had keep_changes=False
  # from a peripheral cash_contract_failure with empty buffer
  # violations -- so the handler never engaged, the orchestrator
  # reverted (pre-Stage-1) or kept the proposer outputs (post-
  # Stage-1) but never gave the handler a chance to refine the
  # state when other validators popped. The Part 2b memo
  # confirmed this gap definitively.
  #
  # Stage 2 fix: engage the handler on ANY validator failure.
  # `not keep_changes` is the canonical "ANY validator popped"
  # signal -- it captures buffer violations OR distribution
  # violations OR contract failures OR hard rule failures, all
  # in one boolean.
  #
  # Stage 3b -- broaden the handler's INPUT PAYLOAD. Pre-Stage-3b
  # the orchestrator passed only `cash_buffer_violations` to
  # engage_funding_handler_on_violations even though the trigger
  # fired on ANY validator failure. The handler had a blind spot:
  # invoked but unaware of WHY (which non-buffer category tripped
  # keep_changes). Stage 3b passes every category from
  # cash_post_validation (distribution / surplus ceiling /
  # contract / hard-rule). The handler's lever authority is
  # UNCHANGED (five funding levers); the GPT session now sees the
  # full failure picture and can reason about combined fixes within
  # those levers (e.g. negative Distributions adjustment to satisfy
  # a cash_distribution_violation while also closing a buffer gap).
  # The deterministic Python allocator still only fills buffer
  # shortfalls -- it has no per-quarter "shortfall in dollars"
  # primitive for the other categories the priority-order walk
  # could fill.
  #
  # The doctrine principle (per Part 3 directive): severity does
  # not matter -- hard rule vs soft rule does not matter. If the
  # validator pops, the handler runs WITH FULL VISIBILITY.
  cash_funding_handler_result: Optional[Dict[str, Any]] = None
  post_handler_post_validation: Optional[Dict[str, Any]] = None
  cash_buffer_violations_for_handler = list(
    cash_post_validation.get("cash_buffer_violations") or []
  )
  # Stage 3b -- collect every validator failure category from
  # cash_post_validation so the handler sees the full picture.
  cash_distribution_violations_for_handler = list(
    cash_post_validation.get("cash_distribution_violations") or []
  )
  cash_surplus_ceiling_violations_for_handler = list(
    cash_post_validation.get("cash_surplus_ceiling_violations") or []
  )
  cash_contract_failures_for_handler = list(
    cash_post_validation.get("cash_contract_failures") or []
  )
  hard_rule_assessment_for_handler = (
    cash_post_validation.get("hard_rule_assessment")
    if isinstance(cash_post_validation.get("hard_rule_assessment"), dict)
    else None
  )
  if (
    not keep_changes
    and isinstance(cash_strategy_second_pass_result, dict)
  ):
    from client_intake_and_finmo.post_intake_funding_handler import (  # type: ignore
      engage_funding_handler_on_violations,
    )
    from client_intake_and_finmo.finmo_bridge import (  # type: ignore
      build_python_finmo_json,
    )
    lever_bounds_payload = (
      (cash_strategy_review_context.get("lever_bounds") or {}).get("lever_bounds")
      if isinstance(cash_strategy_review_context, dict)
      else {}
    )
    if not isinstance(lever_bounds_payload, dict):
      lever_bounds_payload = {}
    # THE JUDGED FUNDING ACCESS GATES EVERY FUNDING LEG. The funding-
    # source policy (executive judgment when present) narrowed the
    # PROPOSER's sources, but the handler received the RAW lever bounds
    # and could fund with sources the executive judged unavailable —
    # Cedar's handler injected ~$21M of Owner's Capital against a
    # judgment of owner_equity_available=false ("owners of a capital-
    # intensive infrastructure asset cannot realistically add capital"),
    # a fundability-not-need breach that made the plan pass dishonestly.
    # Filter the handler's bounds to the policy's allowed FUNDING
    # sources; non-source levers (debt repayment, distributions) pass
    # through untouched.
    _fsp = (
      cash_strategy_review_context.get("funding_source_policy")
      if isinstance(cash_strategy_review_context, dict) else {}
    ) or {}
    _fsp_excluded = {
      str(item).strip()
      for item in (_fsp.get("excluded_funding_source_lever_ids") or [])
      if str(item or "").strip()
    }
    if _fsp_excluded:
      lever_bounds_payload = {
        lever_id: rows
        for lever_id, rows in lever_bounds_payload.items()
        if str(lever_id).strip() not in _fsp_excluded
      }
    buffer_by_q: Dict[int, float] = {}
    cve = (
      cash_post_validation.get("cash_validation_envelope") or {}
      if isinstance(cash_post_validation, dict)
      else {}
    )
    for envelope_row in (cve.get("quarter_envelopes") or []):
      if not isinstance(envelope_row, dict):
        continue
      try:
        qi = int(float(envelope_row.get("quarter_index") or 0))
      except Exception:
        continue
      if qi < 1:
        continue
      try:
        buffer_val = float(envelope_row.get("buffer") or 0.0)
      except Exception:
        buffer_val = 0.0
      buffer_by_q[qi] = buffer_val
    pre_handler_mi = (
      cash_strategy_second_pass_result.get("updated_model_input_json")
      if isinstance(cash_strategy_second_pass_result.get("updated_model_input_json"), dict)
      else copy.deepcopy(pre_cash_model_input_json)
    )
    pre_handler_finmo = (
      cash_strategy_second_pass_result.get("updated_finmo_json")
      if isinstance(cash_strategy_second_pass_result.get("updated_finmo_json"), dict)
      else copy.deepcopy(pre_cash_finmo_json)
    )
    cash_funding_handler_result = engage_funding_handler_on_violations(
      cash_buffer_violations=cash_buffer_violations_for_handler,
      pre_handler_model_input_json=pre_handler_mi,
      pre_handler_finmo_json=pre_handler_finmo,
      lever_bounds=lever_bounds_payload,
      buffer_by_quarter=buffer_by_q,
      cash_strategy_mode=cash_strategy_mode,
      build_finmo=lambda mi: build_python_finmo_json(model_input_json=mi),
      # Stage 3b -- broadened input payload.
      cash_distribution_violations=cash_distribution_violations_for_handler,
      cash_surplus_ceiling_violations=cash_surplus_ceiling_violations_for_handler,
      cash_contract_failures=cash_contract_failures_for_handler,
      hard_rule_assessment=hard_rule_assessment_for_handler,
    )
    if (
      cash_funding_handler_result.get("status") == "resolved"
      and isinstance(cash_funding_handler_result.get("updated_model_input_json"), dict)
      and isinstance(cash_funding_handler_result.get("updated_finmo_json"), dict)
    ):
      # Re-validate the post-handler state.
      try:
        post_handler_post_validation = _cash_runner._validate_cash_strategy_post_pass(
          ops_json=ops_json_dict,
          financials_json=copy.deepcopy(financials_for_runner),
          baseline_issue_ledger=[],
          candidate_model_input_json=copy.deepcopy(
            cash_funding_handler_result["updated_model_input_json"]
          ),
          candidate_finmo_json=copy.deepcopy(
            cash_funding_handler_result["updated_finmo_json"]
          ),
          iteration=2,
          planning_mode=planning_mode_str or None,
        )
      except Exception:
        post_handler_post_validation = None
      if post_handler_post_validation and bool(
        post_handler_post_validation.get("keep_changes")
      ):
        # Handler resolved violations AND post-pass agrees.
        cash_strategy_second_pass_result = dict(cash_strategy_second_pass_result)
        cash_strategy_second_pass_result["updated_model_input_json"] = (
          cash_funding_handler_result["updated_model_input_json"]
        )
        cash_strategy_second_pass_result["updated_finmo_json"] = (
          cash_funding_handler_result["updated_finmo_json"]
        )
        cash_strategy_second_pass_result["funding_handler_engagement"] = (
          cash_funding_handler_result
        )
        cash_post_validation = post_handler_post_validation
        keep_changes = True
        # ORDERING HOLE — the handler runs AFTER Step 9's surplus
        # cleanup, so its adopted state (which may inject funding that
        # CREATES surplus, or simply carry the pre-cleanup cash) never
        # got a surplus pass: Orion parked $21B (7.95x opex) that the
        # cleanup, run on this exact state, deploys correctly (debt to
        # zero, cash to 3.1x). Re-run Step 9 on the handler's state,
        # rebuild FINMO once (Stage-3 discipline), and re-validate so
        # the recorded verdict matches the state downstream consumes.
        cash_strategy_second_pass_result = _cash_runner._apply_cash_policy_surplus_cleanup(
          cash_strategy_result=copy.deepcopy(cash_strategy_second_pass_result),
          financials_json=copy.deepcopy(financials_for_runner),
        )
        try:
          from client_intake_and_finmo.finmo_bridge import (  # type: ignore
            build_python_finmo_json as _post_handler_rebuild,
          )
          _rebuilt_post_handler = _post_handler_rebuild(
            model_input_json=copy.deepcopy(
              cash_strategy_second_pass_result.get("updated_model_input_json") or {}
            )
          )
          if isinstance(_rebuilt_post_handler, dict) and _rebuilt_post_handler:
            cash_strategy_second_pass_result["updated_finmo_json"] = _rebuilt_post_handler
        except Exception:
          from client_intake_and_finmo.fail_fast.common import (  # type: ignore
            convergence_test_mode_enabled as _ph_test_mode,
          )
          if _ph_test_mode():
            raise
        try:
          _post_cleanup_validation = _cash_runner._validate_cash_strategy_post_pass(
            ops_json=ops_json_dict,
            financials_json=copy.deepcopy(financials_for_runner),
            baseline_issue_ledger=[],
            candidate_model_input_json=copy.deepcopy(
              cash_strategy_second_pass_result.get("updated_model_input_json") or {}
            ),
            candidate_finmo_json=copy.deepcopy(
              cash_strategy_second_pass_result.get("updated_finmo_json") or {}
            ),
            iteration=3,
            planning_mode=planning_mode_str or None,
          )
          if isinstance(_post_cleanup_validation, dict):
            cash_post_validation = _post_cleanup_validation
        except Exception:
          pass

  # FUNDING HANDSHAKE — the cash pass's ONE JOB is that a fundable
  # business never ends a quarter with negative cash, and an unfundable
  # one fails on an explicit verdict, never a silent negative balance.
  # The single-pass plan (and the handler) size gaps on a pre-funding
  # snapshot, so cumulative interest drag leaves residual gaps the old
  # machinery silently shipped (Cedar: judged debt ACCESS AVAILABLE with
  # per-quarter headroom, yet cash ran to -$2.9M). This bounded
  # deterministic refill loop closes the handshake: re-measure gaps on
  # the REBUILT state, fund them through the JUDGED-allowed sources
  # only (the executive's fundability call gates every dollar), repeat
  # until cash holds or the allowed sources are truly exhausted — in
  # which case the trace records UNFUNDABLE and the acceptance gate's
  # cash_never_negative check renders the honest non-viable verdict.
  try:
    _refill_trace: List[Dict[str, Any]] = []
    _refill_unfundable = False
    _fsp_refill = (
      cash_strategy_review_context.get("funding_source_policy")
      if isinstance(cash_strategy_review_context, dict) else {}
    ) or {}
    _refill_allowed = [
      str(item).strip()
      for item in (_fsp_refill.get("allowed_funding_source_lever_ids") or [])
      if str(item or "").strip()
    ]
    _refill_bounds = (
      (cash_strategy_review_context.get("lever_bounds") or {}).get("lever_bounds")
      if isinstance(cash_strategy_review_context, dict) else {}
    ) or {}
    _refill_bound_max: Dict[tuple, float] = {}
    for _rb_lever, _rb_rows in _refill_bounds.items():
      for _rb_row in (_rb_rows or []):
        if not isinstance(_rb_row, dict):
          continue
        try:
          _rb_q = int(float(_rb_row.get("quarter_index") or 0))
          _rb_max = float(_rb_row.get("max_value") or 0.0)
        except Exception:
          continue
        if _rb_q >= 1:
          _refill_bound_max[(str(_rb_lever).strip(), _rb_q)] = _rb_max
    if _refill_allowed:
      from client_intake_and_finmo.numeric_execution import execute_numeric_plan  # type: ignore
      for _refill_pass in range(1, 7):
        _refill_mi = cash_strategy_second_pass_result.get("updated_model_input_json") or {}
        _refill_fj = cash_strategy_second_pass_result.get("updated_finmo_json") or {}
        _refill_env = _cash_runner._cash_strategy_validation_violation_envelope(
          selected_cash_strategy=cash_strategy_mode,
          finmo_payload=copy.deepcopy(_refill_fj),
          model_input_json=copy.deepcopy(_refill_mi),
        )
        _refill_gaps = []
        for _rq in (_refill_env.get("quarter_envelopes") or []):
          if not isinstance(_rq, dict):
            continue
          _rq_i = int(float(_rq.get("quarter_index") or 0))
          _rq_gap = int(round(float(_rq.get("residual_funding_gap") or 0.0)))
          _rq_end = int(round(float(_rq.get("ending_cash") or 0.0)))
          if _rq_i >= 1 and (_rq_gap > 0 or _rq_end < 0):
            _refill_gaps.append((_rq_i, max(_rq_gap, -_rq_end)))
        if not _refill_gaps:
          break
        _refill_lever_values = _cash_runner._solved_lever_value_map(_refill_mi)
        _refill_updates: List[Dict[str, Any]] = []
        # CARRY-FORWARD: funding a quarter lifts every later quarter's
        # ending cash, so each gap is funded only INCREMENTALLY beyond
        # what earlier fills already carry forward — funding every
        # quarter's full standalone gap over-funds the tail massively
        # (Cedar: cash ballooned to 9.7x opex in one pass).
        _carry_forward = 0.0
        for _rq_i, _rq_gap in _refill_gaps:
          _remaining_gap = max(0.0, float(_rq_gap) - _carry_forward)
          if _remaining_gap <= 0:
            continue
          for _lever in _refill_allowed:
            if _remaining_gap <= 0:
              break
            _cur_series = _refill_lever_values.get(_lever) or []
            _cur = float(_cur_series[_rq_i - 1]) if _rq_i - 1 < len(_cur_series) else 0.0
            _maxv = _refill_bound_max.get((_lever, _rq_i))
            _headroom = (float(_maxv) - _cur) if _maxv is not None else 0.0
            if _headroom <= 0:
              continue
            _mult = 1.0
            if _lever == _cash_runner._CASH_STRATEGY_DEBT_ISSUANCE_LEVER_ID:
              _mult = _cash_runner._cash_strategy_debt_cash_support_multiplier(
                lever_map=_refill_lever_values, quarter_index=_rq_i,
              ) or 1.0
            _need = _remaining_gap / max(0.5, float(_mult))
            _add = min(_headroom, _need)
            if _add < 1.0:
              continue
            _refill_updates.append({
              "lever_id": _lever,
              "quarter_index": _rq_i,
              "exact_value": int(round(_cur + _add)),
              "issue_codes": ["liquidity_failure"],
              "rationale": (
                "Funding handshake refill: residual liquidity gap after "
                "drag, funded through executive-judged available sources."
              ),
            })
            _remaining_gap -= _add * float(_mult)
            _carry_forward += _add * float(_mult)
        if not _refill_updates:
          _refill_unfundable = True
          break
        _refill_exec = execute_numeric_plan(
          model_input_json=copy.deepcopy(_refill_mi),
          exact_updates=copy.deepcopy(_refill_updates),
          numeric_solver_contract={
            "pass_name": "cash_strategy_review",
            "contract_scope": "cash_pass_funding_handshake_refill",
            "solver_phase_status": "phase_6_cash_strategy_solver_live",
            "solver_settings": {"max_solver_attempts_per_pass": 1},
          },
          review_plan=None,
          phase_status="phase_6_cash_strategy_solver_live",
          executor_context={
            "source": "post_intake_cash_strategy.funding_handshake_refill",
            "execution_mode": "deterministic_refill",
          },
        )
        if isinstance(_refill_exec.get("updated_model_input_json"), dict):
          cash_strategy_second_pass_result["updated_model_input_json"] = (
            _refill_exec["updated_model_input_json"]
          )
        if isinstance(_refill_exec.get("updated_finmo_json"), dict):
          cash_strategy_second_pass_result["updated_finmo_json"] = (
            _refill_exec["updated_finmo_json"]
          )
        _refill_trace.append({
          "pass": _refill_pass,
          "gaps": len(_refill_gaps),
          "updates": len(_refill_updates),
        })
      else:
        # Loop exhausted its passes with gaps still present.
        _refill_unfundable = True
    if _refill_trace:
      # The refill can still overshoot (drag gross-up + integer floors);
      # a final surplus pass deploys the excess back — for a judged
      # deleverage-first business that means repaying the revolver, so
      # the cash the refill parked above the ceiling never sits idle.
      cash_strategy_second_pass_result = _cash_runner._apply_cash_policy_surplus_cleanup(
        cash_strategy_result=copy.deepcopy(cash_strategy_second_pass_result),
        financials_json=copy.deepcopy(financials_for_runner),
      )
      # New issuance needs its amortization floor + a canonical rebuild
      # so downstream validators see coherent schedule rows.
      cash_strategy_second_pass_result = _cash_runner._apply_cash_pass_minimum_debt_schedule(
        cash_strategy_result=copy.deepcopy(cash_strategy_second_pass_result),
        financials_json=copy.deepcopy(financials_for_runner),
      )
      try:
        from client_intake_and_finmo.finmo_bridge import (  # type: ignore
          build_python_finmo_json as _refill_rebuild,
        )
        _refill_rebuilt = _refill_rebuild(
          model_input_json=copy.deepcopy(
            cash_strategy_second_pass_result.get("updated_model_input_json") or {}
          )
        )
        if isinstance(_refill_rebuilt, dict) and _refill_rebuilt:
          cash_strategy_second_pass_result["updated_finmo_json"] = _refill_rebuilt
      except Exception:
        pass
    cash_strategy_second_pass_result["funding_handshake_refill"] = {
      "passes": _refill_trace,
      "allowed_sources": _refill_allowed,
      "unfundable_under_judged_access": _refill_unfundable,
    }
  except Exception as _refill_exc:
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      convergence_test_mode_enabled as _refill_test_mode,
    )
    if _refill_test_mode():
      raise
    cash_strategy_second_pass_result["funding_handshake_refill"] = {
      "error": f"{type(_refill_exc).__name__}: {str(_refill_exc)[:300]}",
    }

  # Phase 9 P3.20 Part 3 Stage 1 -- NEVER revert. The cash strategy
  # proposer + (optional) funding handler outputs ALWAYS become the
  # final state. Pre-iter, when `keep_changes` was False the
  # orchestrator's else branch discarded `cash_strategy_second_pass_
  # result.updated_model_input_json` and reverted to the pre-cash
  # state. That atomic revert was the root cause of the P3.19 Phase
  # 3a lease-bearing ExpressLogix FAIL run: the proposer had closed
  # all 20-quarter cash buffer violations by injecting $4.28M Owner's
  # Capital Q1, but a peripheral cash_contract_failure flipped
  # keep_changes to False and the revert threw away the equity
  # injection along with the contract failure metadata. The pre-cash
  # state (still buffer-violating) then carried through to finalize
  # and hard-failed.
  #
  # With the revert removed: the proposer's good work persists, and
  # any cash_contract_failure metadata stays visible in
  # cash_strategy_second_pass_result for downstream inspection.
  # `keep_changes` is still computed and consulted by the handler
  # trigger (line 449-453) -- Stage 1 leaves the trigger logic
  # unchanged. Stage 2 will relax that trigger to engage on ANY
  # validator failure.
  #
  # The pre_cash_* fallback is preserved for the (rare) case where
  # the proposer didn't produce an updated_model_input_json or
  # updated_finmo_json at all (e.g. it errored before completing).
  final_model_input_json = (
    cash_strategy_second_pass_result.get("updated_model_input_json")
    if isinstance(cash_strategy_second_pass_result.get("updated_model_input_json"), dict)
    else copy.deepcopy(pre_cash_model_input_json)
  )
  final_finmo_json = (
    cash_strategy_second_pass_result.get("updated_finmo_json")
    if isinstance(cash_strategy_second_pass_result.get("updated_finmo_json"), dict)
    else copy.deepcopy(pre_cash_finmo_json)
  )

  # Phase 9 P3.20 Part 3 Stage 3 -- outer FINMO rebuild REMOVED.
  # Pre-Stage-3 this site rebuilt FINMO from final_model_input_json
  # ("Final FINMO rebuild -- guarantees cash, interest, debt balance,
  # short_term/long_term split reflect every applied update from the
  # cash sequence above, regardless of which sub-step rebuilt last").
  # That outer rebuild ran AFTER the validator and handler had already
  # made decisions on the pre-rebuild FINMO; if the outer rebuild
  # produced different numbers than the validator saw, the system had
  # silent state drift between "what was validated" and "what
  # persists". Stage 3 hoists the rebuild to BEFORE the validator
  # (single source of truth -- Mirror Flavor 1 per doctrine §3
  # Pattern 1). The validator, handler trigger, handler invocation,
  # and downstream consumers all see the same FINMO. The outer
  # rebuild is now redundant -- removed entirely.
  #
  # If FINMO needs another rebuild for any reason, the right place
  # is the SINGLE pre-validator rebuild above; do not re-introduce
  # an after-the-fact rebuild here.

  # Mutate caller-supplied dicts in place (matches the prior contract).
  if isinstance(model_input_json, dict):
    model_input_json.clear()
    model_input_json.update(final_model_input_json or {})
  if isinstance(finmo_json, dict):
    finmo_json.clear()
    finmo_json.update(final_finmo_json or {})

  applied_updates_list = [
    item for item in (cash_strategy_second_pass_result.get("applied_updates") or [])
    if isinstance(item, dict)
  ]
  totals = _summarize_applied_totals(exact_updates=applied_updates_list)

  return CashStrategyResult(
    cash_strategy_mode=cash_strategy_mode,
    status=str(cash_strategy_second_pass_result.get("status") or "completed"),
    applied_updates_count=int(cash_strategy_second_pass_result.get("applied_update_count") or len(applied_updates_list)),
    total_debt_issued=round(totals["total_debt_issued"], 2),
    total_distributions=round(totals["total_distributions"], 2),
    total_owners_capital_added=round(totals["total_owners_capital_added"], 2),
    total_other_equity_added=round(totals["total_other_equity_added"], 2),
    per_quarter=[],
    funding_source_policy=copy.deepcopy(funding_source_policy_payload),
    review_decision=copy.deepcopy(cash_strategy_review_decision),
    second_pass_plan=copy.deepcopy(cash_strategy_second_pass_plan),
    second_pass_result=copy.deepcopy(cash_strategy_second_pass_result),
    post_validation=copy.deepcopy(cash_post_validation),
  )


def _failure_result(
  *,
  cash_strategy_mode: str,
  reason: str,
  funding_source_policy: Optional[Dict[str, Any]] = None,
  review_decision: Optional[Dict[str, Any]] = None,
  second_pass_plan: Optional[Dict[str, Any]] = None,
  second_pass_result: Optional[Dict[str, Any]] = None,
) -> CashStrategyResult:
  return CashStrategyResult(
    cash_strategy_mode=cash_strategy_mode,
    status="failed",
    reason=reason,
    applied_updates_count=0,
    funding_source_policy=copy.deepcopy(funding_source_policy or {}),
    review_decision=copy.deepcopy(review_decision or {}),
    second_pass_plan=copy.deepcopy(second_pass_plan or {}),
    second_pass_result=copy.deepcopy(second_pass_result or {}),
  )
