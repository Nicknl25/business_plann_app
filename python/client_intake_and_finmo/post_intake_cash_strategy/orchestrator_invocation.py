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
) -> Dict[str, Any]:
  """Return a deep-copied financials_json with ``cash_strategy`` set.

  ``runner._resolved_cash_strategy`` reads ``cash_strategy`` /
  ``selected_cash_strategy`` off financials_json. The intake captures
  the operator's selection on financials, but if it's missing we copy
  the value from adaptive_policy so the runner sees a non-empty mode.
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

  financials_for_runner = _ensure_cash_strategy_on_financials(financials_json, adaptive_policy)
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

  # Step 10 — post-pass validation (buffer, surplus ceiling, debt
  # schedule). On hard-failure we revert to the pre-cash state.
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
  # in one boolean. The handler's authority is the five funding
  # levers (Owner's Capital, Other Equity, Debt Issuance/Repayment,
  # Distributions); for non-buffer validator failures the handler
  # may or may not have a lever that fixes the specific issue,
  # but it gets a chance to react rather than being skipped
  # entirely. Future stages can broaden the handler's input
  # payload to include the other violation categories so it has
  # full visibility (currently the handler's
  # engage_funding_handler_on_violations API takes only
  # cash_buffer_violations as the violations input).
  #
  # The doctrine principle (per Part 3 directive): severity does
  # not matter -- hard rule vs soft rule does not matter. If the
  # validator pops, the handler runs.
  cash_funding_handler_result: Optional[Dict[str, Any]] = None
  post_handler_post_validation: Optional[Dict[str, Any]] = None
  cash_buffer_violations_for_handler = list(
    cash_post_validation.get("cash_buffer_violations") or []
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

  # Final FINMO rebuild — guarantees cash, interest, debt balance,
  # short_term/long_term split reflect every applied update from the
  # cash sequence above, regardless of which sub-step rebuilt last.
  try:
    rebuilt_finmo = build_python_finmo_json(
      model_input_json=copy.deepcopy(final_model_input_json or {})
    )
    if isinstance(rebuilt_finmo, dict) and rebuilt_finmo:
      final_finmo_json = rebuilt_finmo
  except Exception as exc:
    # Phase 9 P3.10 Commit 4 — final FINMO rebuild failure raises
    # under test mode. The "second guard" justification is correct for
    # production but masks a state divergence when test mode is on.
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      PostIntakePreconditionFailed,
      convergence_test_mode_enabled,
    )
    if convergence_test_mode_enabled():
      raise PostIntakePreconditionFailed(
        operation="cash_strategy_final_finmo_rebuild_failed",
        pipeline_stage="post_intake_cash_strategy",
        expected="build_python_finmo_json rebuilds successfully after cash sequence",
        actual=f"{type(exc).__name__}: {str(exc)[:200]}",
        details={"cash_strategy_mode": cash_strategy_mode},
        cause=exc,
      ) from exc
    # Production-mode legacy path: leave the runner-supplied state in
    # place; the orchestrator's outer rebuild is a second guard.

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
