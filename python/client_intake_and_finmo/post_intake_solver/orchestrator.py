"""Top-level target-seeking orchestrator — Phase 2.5.

Makes the target-seeking outer loop the authoritative entry point of the
post-intake convergence pipeline. The existing scipy/issue-code solver
(numeric_solver.py + post_intake_convergence/runtime.py) is repositioned
as an inner tool the outer loop calls when single-driver bisection cannot
close a numeric gap.

Shape:
  intake_consult._run_unified_post_grid_system_run
    -> run_target_seeking_orchestrated_system_run (THIS MODULE)
        |- pre-flight target-seeking pass on applied_model_input_json
        |   bisects single drivers within their envelopes to land FINMO
        |   outputs in target ranges as a starting point
        |- inner: post_intake_convergence.runner.run_unified_post_grid_system_run
        |   (the existing 3451-line orchestrator handles payroll headcount,
        |   convergence cycles, cash pass, finalize). The outer loop has
        |   already pre-shaped the model so the inner sees envelope-respecting
        |   inputs.
        |- post-flight sanity assertion + repair pass
        |   If hard_fail residuals remain, runs the target-seeking loop one
        |   more time, this time with the inner-tool adapter available so
        |   joint multi-lever fitting can close gaps single-lever bisection
        |   cannot. After the repair pass, raises on:
        |     - stuck_pinned (a driver pinned at envelope edge with the gap
        |       still open -> envelope is too tight or target too narrow)
        |     - no_candidate_levers (no influence-map lever covers the
        |       failing metric -> mapping table gap)
        |     - max_iterations_reached (loop diverged or oscillated)
        |     - hard_fail residuals after repair (target jointly infeasible)
        |   These are the band-respecting failure modes that prove the shift
        |   is real: the system fails when targets are unreachable, instead
        |   of producing implausible plans.

The existing issue-code infrastructure remains usable. It is invoked as
the inner-tool adapter when the outer loop wants joint multi-lever
fitting on a constrained scope. The outer loop is the gate; the inner
runner is one of its tools.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Optional


_DEFAULT_PREFLIGHT_MAX_ITERATIONS = 12
_DEFAULT_POSTFLIGHT_MAX_ITERATIONS = 16
_DEFAULT_NUMERIC_TOLERANCE = 1e-6


# Phase 9 P3.10 Bug F + Bug D — names of the GPT-authorable checks
# moved out of finalize into the pre-cash post-handler gate. Single
# source of truth. Each name corresponds to a check the handler's
# existing toolset (driver anchors, working_capital_drivers,
# realism_flags_to_mute) can resolve.
_GPT_AUTHORABLE_PRE_CASH_CHECK_NAMES = (
  "stage_ramp_expense_path_applied",
  "stage_ramp_profitability_path_applied",
  "balance_sheet_driver_zero_but_applicable",
)


# Map FINMO-field names (as emitted by the stage_ramp_expense violations)
# to (realism metric_key, primary lever_id). Used to translate
# stage_ramp_expense_path_applied violations into handler-compatible
# failing_metrics. Universal-app: every business uses the same map.
_STAGE_RAMP_EXPENSE_FINMO_FIELD_TO_METRIC_LEVER = {
  "cost_of_goods_sold": ("cogs_percent_of_revenue", "expenses::Cost of Goods Sold"),
  "marketing": ("marketing_percent_of_revenue", "expenses::Marketing"),
  "research_and_development": ("r_and_d_percent_of_revenue", "expenses::Research & Development"),
  "lease_rent": ("rent_percent_of_revenue", "expenses::Lease"),
  "general_and_administrative": ("sga_percent_of_revenue", "expenses::General & Administrative"),
  "payroll": ("payroll_percent_of_revenue", "expenses::Payroll"),
}


# Map balance_sheet lever_ids to their realism metric_key for
# zero_but_applicable violation translation.
_BALANCE_SHEET_LEVER_TO_METRIC = {
  "balance_sheet::Deferred Revenue (% of Revenue)": "deferred_revenue_percent_of_revenue",
  "balance_sheet::Prepaid Expenses (% of Revenue)": "prepaid_expenses_percent_of_revenue",
  "balance_sheet::Accounts Receivable Days": "ar_days_dso",
  "balance_sheet::Accounts Payable Days": "ap_days_dpo",
  "balance_sheet::Inventory Days": "inventory_days",
}


# P&L lever set — used to decide handler scope (PNL_PATH vs BS_ONLY_PATH).
_PNL_LEVER_IDS = frozenset({
  "expenses::Cost of Goods Sold",
  "expenses::Marketing",
  "expenses::Research & Development",
  "expenses::Lease",
  "expenses::General & Administrative",
  "expenses::Payroll",
  "revenue::Unit Price",
  "revenue::Capacity",
  "revenue::Utilization",
})


class _PreCashGateRestorationResult:
  """Synthetic restoration_result for the pre-cash post-handler gate.

  The handler's run_gpt_exhaustion_handler entry point expects a
  RestorationResult-shaped object with `.scope`, `.failing_metrics`,
  `.q11_ebitda_margin`, and `.to_dict()`. The gate fabricates one of
  these from the GPT-authorable check violations so the handler runs
  with the same callable, signature, and contract used by the
  restoration-EXHAUSTED → handler path.
  """

  def __init__(self, *, scope, failing_metrics, q11_ebitda_margin) -> None:
    from client_intake_and_finmo.post_intake_target_solver import (  # type: ignore
      RestorationStatus,
    )
    self.status = RestorationStatus.EXHAUSTED
    self.scope = scope
    self.failing_metrics = list(failing_metrics or [])
    self.q11_ebitda_margin = q11_ebitda_margin
    self.outer_passes_used = 0
    self.per_pass_diagnostics = []
    self.final_viability_state = {}
    self.drivers_at_bounds_summary = {}
    self.per_target_results = []
    self.reason = "pre_cash_gate_gpt_authorable_check_failure"

  def to_dict(self) -> Dict[str, Any]:
    return {
      "status": "exhausted",
      "scope": (
        self.scope.value
        if hasattr(self.scope, "value")
        else (self.scope or None)
      ),
      "failing_metrics": list(self.failing_metrics),
      "reason": self.reason,
      "q11_ebitda_margin": self.q11_ebitda_margin,
      "outer_passes_used": self.outer_passes_used,
      "per_pass_diagnostics": list(self.per_pass_diagnostics),
      "final_viability_state": dict(self.final_viability_state),
      "drivers_at_bounds_summary": dict(self.drivers_at_bounds_summary),
      "per_target_results": list(self.per_target_results),
    }


def _q11_ebitda_margin_from_finmo(finmo_json: Optional[Dict[str, Any]]) -> Optional[float]:
  rows = (finmo_json or {}).get("quarter_rows") or []
  for row in rows:
    if not isinstance(row, dict):
      continue
    try:
      qi = int(float(row.get("quarter_index") or 0))
    except Exception:
      continue
    if qi != 11:
      continue
    revenue = float(_safe_float(row.get("revenue")) or 0.0)
    if revenue <= 0:
      return None
    ebitda = float(_safe_float(row.get("ebitda")) or 0.0)
    return ebitda / revenue
  return None


def _decide_handler_scope_from_failing_metrics(failing_metrics: List[Dict[str, Any]]):
  from client_intake_and_finmo.post_intake_target_solver import (  # type: ignore
    HandlerScope,
  )
  has_pnl = False
  for fm in failing_metrics or []:
    for lid in (fm.get("primary_levers") or []):
      if str(lid).strip() in _PNL_LEVER_IDS:
        has_pnl = True
        break
    if has_pnl:
      break
  return HandlerScope.PNL_PATH if has_pnl else HandlerScope.BS_ONLY_PATH


# iter 19 Stage 3 (F6-Pinnacle) — pre-gate sanity check.
#
# The motivating case from iter 18: pre-cash gate's stage-ramp
# profitability check listed `expenses::Payroll` as a primary_lever.
# The payroll_headcount payload had positive quarter_totals but the
# model_input's expenses::Payroll values were all zero (the upstream
# writeback was skipped). The gate handler does not own the payroll
# lever, so handler invocation reported "unfixed_after_handler" — a
# misleading diagnostic that blamed the handler instead of the
# upstream contract owner.
#
# Per doctrine.md §3 Pattern 3 ("Diagnostic blames the wrong layer"):
# this helper asserts that, when a contract has authored values, the
# matching model_input lever is non-zero before the gate runs. On
# violation it raises a specific diagnostic naming the upstream step
# that was skipped, not the handler that can't fix what it doesn't
# own.

_PAYROLL_LEVER_ID: str = "expenses::Payroll"


def _assert_pre_cash_gate_contract_levers_written(
  *,
  model_input_json: Optional[Dict[str, Any]],
  payroll_headcount: Optional[Dict[str, Any]],
) -> None:
  schedule = payroll_headcount if isinstance(payroll_headcount, dict) else {}
  quarter_totals = schedule.get("quarter_totals") if isinstance(schedule, dict) else None
  if not isinstance(quarter_totals, list) or not quarter_totals:
    return  # no contract authored payroll; nothing to assert
  schedule_quarters_with_payroll = sum(
    1 for item in quarter_totals
    if isinstance(item, dict) and float(_safe_float(item.get("payroll")) or 0.0) > 0.0
  )
  if schedule_quarters_with_payroll <= 0:
    return  # contract authored zero payroll across the horizon; lever zero is correct
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  expense_rows = [
    row for row in (sections.get("expenses") or [])
    if isinstance(row, dict) and str(row.get("label") or "").strip() == "Payroll"
  ]
  if not expense_rows:
    return  # different problem; let downstream surface it
  payroll_row = expense_rows[0]
  values = list(payroll_row.get("values") or [])
  # values may include a stub-0 slot; live quarters are the trailing
  # positions. Treat the full series as the lever's writeback signal.
  live_nonzero = sum(1 for v in values if abs(float(_safe_float(v) or 0.0)) > 0.0)
  if live_nonzero > 0:
    return  # lever is written; gate can proceed
  from client_intake_and_finmo.fail_fast.common import (  # type: ignore
    PostIntakePreconditionFailed,
  )
  raise PostIntakePreconditionFailed(
    operation="payroll_lever_not_applied_before_gate",
    pipeline_stage="post_intake_pre_cash_gpt_authorable_gate",
    expected=(
      "model_input.sections.expenses::Payroll has non-zero values for "
      "quarters where payroll_headcount.quarter_totals.payroll > 0."
    ),
    actual=(
      "All Payroll lever values are zero despite the payroll_headcount "
      f"contract authoring positive totals across {schedule_quarters_with_payroll} quarter(s)."
    ),
    details={
      "upstream_skipped_step": "apply_payroll_headcount_payload_to_model_input",
      "upstream_contract_owner": "payroll_headcount_schedule",
      "remediation": (
        "Trace payroll_headcount_schedule construction and orchestration "
        "to identify where the writeback was dropped. The pre-cash gate "
        "handler does NOT have payroll lever authority and cannot fix "
        "this; the upstream writeback must run."
      ),
      "doctrine_reference": "docs/architecture/doctrine.md §3 Pattern 3",
      "schedule_quarters_with_payroll": schedule_quarters_with_payroll,
      "live_value_count": len(values),
    },
  )


def _evaluate_gpt_authorable_pre_cash_checks(
  *,
  stage_ramp_contract: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  payroll_headcount: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
):
  """Run the moved GPT-authorable checks. Returns (failing_metrics, scope).

  Translates each check's native violation shape into the
  realism-metric-style failing_metrics dict the handler consumes.
  Picks scope based on whether any P&L lever is implicated.
  """
  failing_metrics: List[Dict[str, Any]] = []

  # Check 1 + 2: stage_ramp_expense_path + stage_ramp_profitability_path.
  # Both raise FailFastError on violation. We invoke them with stage
  # set to "post_intake_pre_cash_gate" (which contains "post_" but not
  # "final"/"finalize"); the existing assertion bodies key on stage so
  # we use the finalize-style stage label inside a try/except to
  # capture violations as failing_metrics rather than re-raising.
  try:
    from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (  # type: ignore
      assert_stage_ramp_expense_path_applied,
      assert_stage_ramp_profitability_path_applied,
    )
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      FailFastError,
    )
  except Exception:
    assert_stage_ramp_expense_path_applied = None  # type: ignore
    assert_stage_ramp_profitability_path_applied = None  # type: ignore
    FailFastError = RuntimeError  # type: ignore

  if assert_stage_ramp_expense_path_applied is not None:
    try:
      assert_stage_ramp_expense_path_applied(
        stage_ramp_contract=stage_ramp_contract or {},
        model_input_json=model_input_json or {},
        finmo_json=finmo_json or {},
        payroll_headcount=payroll_headcount or {},
        stage="post_intake_pre_cash_gate_finalize",
      )
    except FailFastError as exc:
      details_violations = (exc.details or {}).get("violations") or []
      for v in details_violations:
        finmo_field = str(v.get("finmo_field") or "").strip().lower()
        if finmo_field not in _STAGE_RAMP_EXPENSE_FINMO_FIELD_TO_METRIC_LEVER:
          continue
        metric_key, lever_id = _STAGE_RAMP_EXPENSE_FINMO_FIELD_TO_METRIC_LEVER[finmo_field]
        failing_metrics.append({
          "metric_key": metric_key,
          "quarter_index": int(v.get("quarter_index") or 0) or None,
          "actual_value": float(v.get("actual_ratio") or 0.0),
          "effective_min": None,
          "effective_max": (
            float(v.get("stage_ramp_max_ratio")) if v.get("stage_ramp_max_ratio") is not None else None
          ),
          "primary_levers": [lever_id],
          "source_check": "stage_ramp_expense_path_applied",
        })

  if assert_stage_ramp_profitability_path_applied is not None:
    try:
      assert_stage_ramp_profitability_path_applied(
        stage_ramp_contract=stage_ramp_contract or {},
        finmo_json=finmo_json or {},
        stage="post_intake_pre_cash_gate_finalize",
      )
    except FailFastError as exc:
      details_violations = (exc.details or {}).get("violations") or []
      for v in details_violations:
        # Profitability violations affect overall margin; attribute to
        # ebitda_margin metric and span all P&L levers as the handler's
        # toolset can adjust any of them.
        failing_metrics.append({
          "metric_key": "ebitda_margin",
          "quarter_index": int(v.get("quarter_index") or 0) or None,
          "actual_value": float(v.get("actual_net_income_margin") or 0.0),
          "effective_min": (
            float(v.get("stage_ramp_net_income_margin_floor"))
            if v.get("stage_ramp_net_income_margin_floor") is not None else None
          ),
          "effective_max": None,
          "primary_levers": [
            "expenses::Cost of Goods Sold",
            "expenses::Marketing",
            "expenses::General & Administrative",
            "expenses::Payroll",
          ],
          "source_check": "stage_ramp_profitability_path_applied",
        })

  # Check 3: balance_sheet_driver_zero_but_applicable. Returns structured
  # dicts (not error strings) since C2.
  try:
    from client_intake_and_finmo.post_intake_runtime_validation.balance_sheet_driver_validation import (  # type: ignore
      balance_sheet_driver_zero_but_applicable_errors,
    )
  except Exception:
    balance_sheet_driver_zero_but_applicable_errors = None  # type: ignore

  if balance_sheet_driver_zero_but_applicable_errors is not None:
    bs_errors = balance_sheet_driver_zero_but_applicable_errors(
      financials_json=financials_json or {},
      ops_json=ops_json or {},
      model_input_json=model_input_json or {},
      finmo_json=finmo_json or {},
      debt_schedule=None,
      cash_strategy_second_pass_result=None,
    )
    for entry in bs_errors:
      lever_id = str(entry.get("lever_id") or "").strip()
      metric_key = _BALANCE_SHEET_LEVER_TO_METRIC.get(lever_id, "")
      if not metric_key:
        continue
      failing_metrics.append({
        "metric_key": metric_key,
        "quarter_index": None,
        "actual_value": 0.0,
        "effective_min": 0.0,
        "effective_max": None,
        "primary_levers": [lever_id],
        "source_check": "balance_sheet_driver_zero_but_applicable",
        "applicability_key": entry.get("applicability_key"),
        "zero_allowed_reason_key": entry.get("zero_allowed_reason_key"),
      })

  scope = _decide_handler_scope_from_failing_metrics(failing_metrics)
  return failing_metrics, scope


def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  try:
    number = float(value)
  except Exception:
    return None
  if number != number:
    return None
  return number


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


def _build_minimal_convergence_context(
  *,
  stage_ramp_contract: Optional[Dict[str, Any]],
  adaptive_policy_dict: Optional[Dict[str, Any]],
  planning_context_summary_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  """Phase 9 Phase C1 — populate the unified_convergence_context payload.

  Phase 8 persisted ``unified_convergence_context={}``, which orphaned the
  stage_ramp_contract in the planning_run_json blob. Workbook export reads
  via ``payload.unified_convergence_context.business_world_contract.stage_ramp_contract``
  (see client_statements_output_excel/data.py:146-160). With that path
  empty, the Revenue Drivers sheet's Stage Ramp Contract rows showed zeros
  across Q1-Q20 even though the contract itself had been generated correctly.

  This builder writes the minimum surface the workbook reader needs.
  Intentionally NOT a full convergence-runner payload — convergence runner
  is dead code awaiting Phase I deletion. Phase D may extend this with
  cascade widening artifacts; Phase F adds cash plan summary.
  """
  context: Dict[str, Any] = {}
  bwc: Dict[str, Any] = {}
  if isinstance(stage_ramp_contract, dict) and stage_ramp_contract:
    bwc["stage_ramp_contract"] = copy.deepcopy(stage_ramp_contract)
  if bwc:
    context["business_world_contract"] = bwc
  # Mirror at planning_context_summary path for the alternate fallback the
  # workbook reader walks at data.py:151.
  if isinstance(stage_ramp_contract, dict) and stage_ramp_contract:
    pcs: Dict[str, Any] = {}
    if isinstance(planning_context_summary_json, dict):
      pcs.update(copy.deepcopy(planning_context_summary_json))
    pcs["stage_ramp_contract"] = copy.deepcopy(stage_ramp_contract)
    context["planning_context_summary"] = pcs
  if isinstance(adaptive_policy_dict, dict) and adaptive_policy_dict:
    context["adaptive_policy"] = copy.deepcopy(adaptive_policy_dict)
  return context


def _validate_composite_revenue_against_contract(
  *,
  model_input_json: Dict[str, Any],
  stage_ramp_contract: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  """Phase 9 Phase C4 — observation-only composite revenue trajectory check.

  Reads model_input revenue rows (per-product Capacity / Unit Price /
  Utilization), multiplies them per quarter into a composite revenue
  trajectory, and compares each quarter's QoQ growth to the contract's
  revenue_qoq_target / revenue_qoq_max envelope. Records per-quarter
  in/out-of-band status so the Phase D adaptation cascade has a trace
  to route revenue_achievability remediations from. Does NOT mutate
  model_input. Auto-repair is Phase D's responsibility.
  """
  if not isinstance(stage_ramp_contract, dict) or not stage_ramp_contract:
    return {"status": "skipped", "reason": "missing_stage_ramp_contract"}
  rows = stage_ramp_contract.get("quarter_ramp_grid")
  if not isinstance(rows, list) or not rows:
    return {"status": "skipped", "reason": "missing_quarter_ramp_grid"}

  contract_by_q: Dict[int, Dict[str, Any]] = {}
  for row in rows:
    if not isinstance(row, dict):
      continue
    qi = _safe_float(row.get("quarter_index"))
    if qi is None:
      continue
    contract_by_q[int(round(qi))] = row

  sections = (model_input_json or {}).get("sections")
  if not isinstance(sections, dict):
    return {"status": "skipped", "reason": "missing_model_input_sections"}
  rev_rows = sections.get("revenue")
  if not isinstance(rev_rows, list) or not rev_rows:
    return {"status": "skipped", "reason": "missing_revenue_rows"}

  slots: Dict[str, Dict[str, List[float]]] = {}
  for row in rev_rows:
    if not isinstance(row, dict):
      continue
    driver = str(row.get("driver") or "").strip().lower()
    if driver not in {"capacity", "unit price", "utilization"}:
      continue
    slot_key = str(row.get("revenue_slot_key") or row.get("lever_id") or "").strip()
    if not slot_key:
      continue
    if "::" in slot_key and driver in slot_key.lower():
      slot_key = slot_key.rsplit("::", 1)[0]
    values = [float(v) if isinstance(v, (int, float)) else 0.0 for v in (row.get("values") or [])]
    slots.setdefault(slot_key, {})[driver] = values
  if not slots:
    return {"status": "skipped", "reason": "no_revenue_formula_bundle"}

  horizon = max(len(v) for slot in slots.values() for v in slot.values())
  composite: List[float] = []
  for q in range(horizon):
    total = 0.0
    for slot in slots.values():
      cap = (slot.get("capacity") or [0.0] * horizon)[q] if q < len(slot.get("capacity") or []) else 0.0
      price = (slot.get("unit price") or [0.0] * horizon)[q] if q < len(slot.get("unit price") or []) else 0.0
      util = (slot.get("utilization") or [0.0] * horizon)[q] if q < len(slot.get("utilization") or []) else 0.0
      total += max(0.0, float(cap)) * max(0.0, float(price)) * max(0.0, float(util))
    composite.append(total)

  per_quarter_status: List[Dict[str, Any]] = []
  in_band_count = 0
  out_of_band_count = 0
  for q in range(2, len(composite) + 1):
    prior = composite[q - 2]
    current = composite[q - 1]
    if prior <= 0.0:
      per_quarter_status.append({
        "quarter": q,
        "status": "skipped",
        "reason": "prior_revenue_zero",
      })
      continue
    realized_qoq = current / prior if prior > 0.0 else 0.0
    contract_row = contract_by_q.get(q) or {}
    target = _safe_float(contract_row.get("revenue_qoq_target") or contract_row.get("rev_target"))
    cap = _safe_float(contract_row.get("revenue_qoq_max") or contract_row.get("rev_max"))
    spike = _safe_float(contract_row.get("revenue_qoq_spike") or contract_row.get("rev_spike"))
    bounds_target = target if target and target > 0 else None
    bounds_max = cap if cap and cap > 0 else (spike if spike and spike > 0 else bounds_target)
    if bounds_target is None:
      per_quarter_status.append({
        "quarter": q,
        "status": "no_contract_bound",
        "realized_qoq": round(realized_qoq, 4),
      })
      continue
    in_band = (
      realized_qoq >= bounds_target - 1e-3
      and (bounds_max is None or realized_qoq <= bounds_max + 1e-3)
    )
    if in_band:
      in_band_count += 1
    else:
      out_of_band_count += 1
    per_quarter_status.append({
      "quarter": q,
      "status": "in_band" if in_band else "out_of_band",
      "realized_qoq": round(realized_qoq, 4),
      "contract_target": round(bounds_target, 4),
      "contract_max": round(bounds_max, 4) if bounds_max else None,
    })

  return {
    "status": "completed",
    "in_band_quarters": in_band_count,
    "out_of_band_quarters": out_of_band_count,
    "per_quarter": per_quarter_status,
  }


# Cash-pass-owned levers: written per-quarter (with stock carry-forward
# for equity) by run_mode_based_cash_strategy. The Phase 9 P3 target-
# driven restoration loop must NOT include these in its driver list —
# cash strategy owns financing-side authority end-to-end. Validated at
# the entry to target_solver.solve_for_target by hard-erroring if any
# of these appear in the input driver_lever_ids.
_CASH_PASS_OWNED_LEVER_IDS = frozenset({
  "balance_sheet::Owner's Capital",
  "balance_sheet::Other Equity",
  "balance_sheet::Distributions",
  "balance_sheet::Short Term Debt (% of LTD)",
  "schedules::Debt Issuance (New Borrowing)",
  "schedules::Debt Repayment (Scheduled)",
})


# Phase 9 P3 — the silo'd cascade-remediation logic that lived here was
# retired in commit phase_9_p3_retire_old_cascade. The replacement is
# the target-driven restoration loop in
# python/client_intake_and_finmo/post_intake_target_solver/, called from
# _run_post_cascade_completion in the new pipeline order:
#   1. Target-seeking solver pass
#   2. Target-driven restoration loop (NEW — replaces the old per-metric
#      flat-stamp adaptation; coordinates 4 solver targets across all
#      operating drivers)
#   3. Cash strategy (unchanged)
#   4. Realism gate (final check)
#   5. Finalize validation
#   6. Persist
#
# Deleted along with the cascade: _classify_metric_for_direction,
# _classify_lever_kind, _resolve_lever_direction, _remediate_realism_hard_fails,
# and the per-metric-kind / per-lever-kind classification frozensets
# (_MARGIN_METRICS, _COST_RATIO_METRICS, _DAYS_METRICS, _LEVERAGE_METRICS,
# _TRAJECTORY_UNIVERSAL_METRICS), plus the _GAP_B_INCREASE_FACTOR /
# _GAP_B_DECREASE_FACTOR / _GAP_B_MAX_ITERATIONS direction-only knobs.




def _build_finmo_callable(
  *,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  fulfillment_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
  """Closure over build_python_finmo_json that the outer loop uses to
  evaluate FINMO from a candidate model_input. Heavy imports are lazy so
  this module loads cleanly during Phase 2.5 wiring."""

  # The auxiliary kwargs (business_facts, ops_json, etc.) aren't part of
  # build_python_finmo_json's signature — they're already stamped onto
  # model_input_json by the time _build_model_input_overlay runs. The
  # closure-captured args are kept here only for potential future use
  # (e.g. if FINMO build grows side-channel inputs); today they are
  # intentionally unused.
  _ = (business_facts, ops_json, people_json, financials_json,
       financials_year1_json, fulfillment_json, marketing_model_json)

  def _build(model_input_json: Dict[str, Any]) -> Dict[str, Any]:
    from client_intake_and_finmo.finmo_bridge import (  # type: ignore
      build_python_finmo_json,
    )
    payload = build_python_finmo_json(
      model_input_json=copy.deepcopy(model_input_json or {}),
    )
    return payload if isinstance(payload, dict) else {}

  return _build


def _build_apply_lever_callable(
  *,
  horizon: int,
  stage_ramp_contract: Optional[Dict[str, Any]] = None,
  adaptive_policy_dict: Optional[Dict[str, Any]] = None,
  industry_targets: Optional[Dict[str, float]] = None,
) -> Callable[[Dict[str, Any], str, float], Dict[str, Any]]:
  """Path-aware lever writer (Phase 9 Phase C3).

  Pre-Phase-C this closure broadcast a single scalar across Q1..Q<horizon>.
  Per the Real ramp rule that violated the doctrine for every driver
  except genuinely flat ones (rent, distributions, statutory tax).

  Phase C3 routes every solver lever movement through the path engine.
  ``base_value`` is now the Q1 starting value the solver chose; the path
  engine reinterprets it as the ramp's amplitude and returns Q1..Q<horizon>
  values consistent with the registered shape (s_curve, glidepath,
  capacity_expansion, linear_to_mature, industry_convergence_decay).

  Non-writable shapes (hiring_schedule, stock_carryforward, calculated,
  schedule_locked) preserve the pre-Phase-C broadcast behavior so the
  solver doesn't loop trying to move drivers the path engine declines
  to write. Phase D's issue router will tighten this when influence_map
  is rebuilt to exclude non-writable lever_ids.

  ``industry_targets`` is an optional ``lever_id -> mature target`` map.
  Phase E populates it from the unified industry profile; Phase C falls
  back to the contract's quarter_ramp_grid where available, then to a
  flat broadcast when no target can be resolved.
  """

  resolved_industry_targets: Dict[str, float] = (
    {str(k): float(v) for k, v in industry_targets.items() if v is not None}
    if isinstance(industry_targets, dict)
    else {}
  )

  def _apply(
    model_input_json: Dict[str, Any], lever_id: str, value: float
  ) -> Dict[str, Any]:
    from client_intake_and_finmo.quarter_grid import (  # type: ignore
      apply_exact_lever_updates_to_model_input,
    )
    from client_intake_and_finmo.post_intake_adaptive_planning import (  # type: ignore
      WRITABLE_SHAPES,
      compute_per_quarter_values,
    )

    h = max(1, int(horizon))
    industry_target = resolved_industry_targets.get(str(lever_id or "").strip())

    path = compute_per_quarter_values(
      lever_id=str(lever_id or "").strip(),
      base_value=float(value),
      horizon=h,
      stage_ramp_contract=stage_ramp_contract,
      adaptive_policy=adaptive_policy_dict,
      industry_target=industry_target,
    )

    if (
      path.shape_kind in WRITABLE_SHAPES
      and isinstance(path.per_quarter_values, list)
      and path.per_quarter_values
    ):
      updates = [
        {
          "lever_id": str(lever_id or "").strip(),
          "quarter_index": int(q + 1),
          "exact_value": float(v),
        }
        for q, v in enumerate(path.per_quarter_values)
      ]
    else:
      # Non-writable shape — fall back to the pre-Phase-C broadcast so
      # the solver loop's expectation that every move lands somewhere
      # holds. The path engine's skip_write_reason explains why a
      # path wasn't computed; the broadcast keeps the system convergent
      # while Phase D rewires influence_map.
      updates = [
        {
          "lever_id": str(lever_id or "").strip(),
          "quarter_index": int(q),
          "exact_value": float(value),
        }
        for q in range(1, h + 1)
      ]

    return apply_exact_lever_updates_to_model_input(
      model_input_json=model_input_json or {},
      exact_updates=updates,
    )

  return _apply


def _solver_input_payloads(
  model_input_json: Optional[Dict[str, Any]],
) -> Dict[str, Optional[Dict[str, Any]]]:
  from client_intake_and_finmo.post_intake_solver import (  # type: ignore
    DRIVER_MOVEMENT_ENVELOPE_KEY,
    FINMO_OUTPUT_TARGET_KEY,
  )
  source = model_input_json if isinstance(model_input_json, dict) else {}
  solver_input = source.get("solver_input") if isinstance(source.get("solver_input"), dict) else {}
  return {
    "envelope": solver_input.get(DRIVER_MOVEMENT_ENVELOPE_KEY) if isinstance(solver_input, dict) else None,
    "targets": solver_input.get(FINMO_OUTPUT_TARGET_KEY) if isinstance(solver_input, dict) else None,
  }


def _stamp_solver_inputs(
  *,
  model_input_json: Dict[str, Any],
  envelope_payload: Optional[Dict[str, Any]],
  targets_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  """Persist the (possibly calibrated) envelope + targets back onto the
  model_input under solver_input. Downstream finmo rebuilds will read
  these calibrated payloads instead of re-running the Python proposers.
  """
  from client_intake_and_finmo.post_intake_solver import (  # type: ignore
    DRIVER_MOVEMENT_ENVELOPE_KEY,
    FINMO_OUTPUT_TARGET_KEY,
  )
  next_input = copy.deepcopy(model_input_json or {})
  solver_input = next_input.setdefault("solver_input", {})
  if not isinstance(solver_input, dict):
    solver_input = {}
    next_input["solver_input"] = solver_input
  if isinstance(envelope_payload, dict):
    solver_input[DRIVER_MOVEMENT_ENVELOPE_KEY] = copy.deepcopy(envelope_payload)
  if isinstance(targets_payload, dict):
    solver_input[FINMO_OUTPUT_TARGET_KEY] = copy.deepcopy(targets_payload)
  return next_input


def _apply_restoration_to_model_input(
  *,
  model_input_json: Dict[str, Any],
  adjusted_ops_json: Dict[str, Any],
  adjusted_payroll_headcount: Dict[str, Any],
  horizon: int,
) -> Dict[str, Any]:
  """Patch model_input revenue rows + payroll rows to match the Phase
  7.2 restoration cascade adjustments.

  Revenue drivers (Capacity / Unit Price / Utilization) get their q1-q20
  values rewritten from adjusted_ops_json scalars. Payroll expense rows
  get their q1-q20 values rewritten from adjusted_payroll_headcount
  quarter_totals. q0 stub stays at the original intake-fact value.
  """
  next_input = copy.deepcopy(model_input_json or {})
  sections = next_input.get("sections")
  if not isinstance(sections, dict):
    return next_input

  # Revenue rows
  revenue_rows = sections.get("revenue")
  if isinstance(revenue_rows, list):
    new_capacity = (
      _safe_float(adjusted_ops_json.get("units_per_period_capacity"))
      or _safe_float(adjusted_ops_json.get("units_per_week_capacity"))
    )
    new_price = _safe_float(adjusted_ops_json.get("unit_price"))
    new_util = _safe_float(adjusted_ops_json.get("utilization_rate"))
    for row in revenue_rows:
      if not isinstance(row, dict):
        continue
      driver = str(row.get("driver") or "").strip()
      values = row.get("values")
      if not isinstance(values, list) or not values:
        continue
      if driver == "Capacity" and new_capacity is not None and new_capacity > 0:
        for idx in range(1, min(horizon + 1, len(values))):
          values[idx] = float(new_capacity)
      elif driver == "Unit Price" and new_price is not None and new_price > 0:
        for idx in range(1, min(horizon + 1, len(values))):
          values[idx] = float(new_price)
      elif driver == "Utilization" and new_util is not None and new_util > 0:
        for idx in range(1, min(horizon + 1, len(values))):
          values[idx] = float(new_util)

  # Payroll rows (in expenses section)
  expenses_rows = sections.get("expenses")
  if isinstance(expenses_rows, list):
    quarter_totals = adjusted_payroll_headcount.get("quarter_totals")
    if isinstance(quarter_totals, list) and quarter_totals:
      payroll_per_quarter = []
      for row in quarter_totals[:horizon]:
        if isinstance(row, dict):
          payroll = _safe_float(row.get("payroll"))
          payroll_per_quarter.append(float(payroll) if payroll is not None else 0.0)
      for row in expenses_rows:
        if not isinstance(row, dict):
          continue
        lever_id = str(row.get("lever_id") or "").strip()
        if "Payroll" not in lever_id:
          continue
        values = row.get("values")
        if not isinstance(values, list) or not values:
          continue
        for idx, payroll_q in enumerate(payroll_per_quarter, start=1):
          if idx < len(values):
            values[idx] = payroll_q

  return next_input


def _ensure_solver_inputs(
  *,
  model_input_json: Dict[str, Any],
  ops_json: Optional[Dict[str, Any]],
  horizon: int,
  business_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Guarantees model_input_json carries solver_input.envelope and
  solver_input.finmo_output_targets even if upstream skipped finmo_bridge.
  """
  from client_intake_and_finmo.post_intake_solver import (  # type: ignore
    DRIVER_MOVEMENT_ENVELOPE_KEY,
    FINMO_OUTPUT_TARGET_KEY,
    assemble_driver_movement_envelope,
    assemble_finmo_output_targets,
  )
  next_input = copy.deepcopy(model_input_json or {})
  solver_input = next_input.setdefault("solver_input", {})
  if not isinstance(solver_input, dict):
    solver_input = {}
    next_input["solver_input"] = solver_input
  naics_6 = ""
  if isinstance(ops_json, dict):
    naics_6 = "".join(ch for ch in str(ops_json.get("business_naics_6") or "") if ch.isdigit())
  if not solver_input.get(DRIVER_MOVEMENT_ENVELOPE_KEY):
    solver_input[DRIVER_MOVEMENT_ENVELOPE_KEY] = assemble_driver_movement_envelope(
      business_naics_6=naics_6 or None,
      live_count=horizon,
      business_profile=business_profile,
    )
  if not solver_input.get(FINMO_OUTPUT_TARGET_KEY):
    solver_input[FINMO_OUTPUT_TARGET_KEY] = assemble_finmo_output_targets(
      business_naics_6=naics_6 or None,
      live_count=horizon,
      business_profile=business_profile,
    )
  return next_input


def _run_target_seeking_pass(
  *,
  pass_label: str,
  model_input_json: Dict[str, Any],
  build_finmo_callable: Callable[[Dict[str, Any]], Dict[str, Any]],
  apply_lever_callable: Callable[[Dict[str, Any], str, float], Dict[str, Any]],
  envelope_payload: Optional[Dict[str, Any]],
  targets_payload: Optional[Dict[str, Any]],
  influence_payload: Optional[Dict[str, Any]],
  max_iterations: int,
  numeric_tolerance: float,
  enable_inner_joint_fit: bool,
  horizon: int,
) -> Dict[str, Any]:
  from client_intake_and_finmo.post_intake_solver import (  # type: ignore
    run_target_seeking_solver,
  )
  from client_intake_and_finmo.post_intake_sequence import (  # type: ignore
    post_intake_sequence_step_scope,
  )
  inner_callable = None
  if enable_inner_joint_fit:
    from client_intake_and_finmo.post_intake_solver.inner_joint_fit_adapter import (  # type: ignore
      build_inner_joint_fit_adapter,
    )
    inner_callable = build_inner_joint_fit_adapter(
      influence_map_payload=influence_payload,
      envelope_payload=envelope_payload,
      horizon=horizon,
    )
  # Phase 4 fix: target-seeking passes invoke FINMO build via
  # build_finmo_callable, which requires an active post-intake sequence
  # context. The orchestrator is a top-level convergence step; we push a
  # synthetic scope for the duration of the pass so the sequence-gated
  # helpers (payroll capacity derivation, etc.) accept the call.
  with post_intake_sequence_step_scope(
    step_key=f"post_intake_target_seeking_{pass_label}",
    executor_function=f"target_seeking_solver_{pass_label}",
  ):
    result = run_target_seeking_solver(
      model_input_json=model_input_json,
      build_finmo_callable=build_finmo_callable,
      apply_lever_value_callable=apply_lever_callable,
      output_targets_payload=targets_payload,
      driver_envelope_payload=envelope_payload,
      influence_map_payload=influence_payload,
      max_iterations=max_iterations,
      numeric_tolerance=numeric_tolerance,
      inner_joint_fit_callable=inner_callable,
    )
  result["pass_label"] = pass_label
  return result


def _band_respecting_failure_diagnostic(
  *,
  pass_result: Dict[str, Any],
  envelope_payload: Optional[Dict[str, Any]],
  targets_payload: Optional[Dict[str, Any]],
) -> Optional[str]:
  status = _clean_text(pass_result.get("status"))
  if status == "converged":
    return None
  worst = pass_result.get("worst_unresolved") or {}
  metric_key = _clean_text(worst.get("metric_key")) or "<unknown>"
  quarter = worst.get("quarter_index")
  produced = worst.get("produced")
  target_min = worst.get("target_min")
  target_max = worst.get("target_max")
  residual = worst.get("residual")
  trace = pass_result.get("trace") or []
  pinned_drivers: List[Dict[str, Any]] = []
  if isinstance(envelope_payload, dict):
    drivers = envelope_payload.get("drivers") or {}
    for entry in trace[-6:]:
      if not isinstance(entry, dict):
        continue
      lever_id = _clean_text(entry.get("chosen_lever"))
      driver = drivers.get(lever_id)
      if isinstance(driver, dict) and driver.get("applicable"):
        mn = _safe_float(driver.get("min_allowed"))
        mx = _safe_float(driver.get("max_allowed"))
        cur = _safe_float(entry.get("new_value"))
        if cur is None or mn is None or mx is None:
          continue
        if cur <= mn + 1e-9 or cur >= mx - 1e-9:
          pinned_drivers.append({
            "lever_id": lever_id,
            "side": "at_min" if cur <= mn + 1e-9 else "at_max",
            "current_value": cur,
            "envelope_min": mn,
            "envelope_max": mx,
          })
  if status == "stuck_pinned":
    return (
      f"target_seeking_stuck_pinned: metric={metric_key} quarter={quarter} "
      f"produced={produced} target=[{target_min},{target_max}] residual={residual} "
      f"pinned_drivers={pinned_drivers or 'unspecified'}"
    )
  if status == "no_candidate_levers":
    return (
      f"target_seeking_no_candidate_levers: metric={metric_key} quarter={quarter} "
      f"produced={produced} target=[{target_min},{target_max}] residual={residual} "
      "(influence-map gap)"
    )
  if status == "max_iterations_reached":
    return (
      f"target_seeking_max_iterations_reached: pass produced no convergence within "
      f"max_iterations. trace_len={len(trace)}"
    )
  return f"target_seeking_unknown_status: status={status!r} pass={pass_result.get('pass_label')!r}"


def _hard_fail_violations_from_assertion(
  *,
  finmo_json: Dict[str, Any],
  envelope_payload: Optional[Dict[str, Any]],
  targets_payload: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  from client_intake_and_finmo.post_intake_solver import (  # type: ignore
    assert_solver_respected_targets,
  )
  assertion = assert_solver_respected_targets(
    finmo_json=finmo_json,
    output_targets_payload=targets_payload,
    driver_envelope_payload=envelope_payload,
  )
  return [
    v for v in (assertion.get("violations") or [])
    if str((v or {}).get("gate_kind") or "").lower() == "hard_fail"
  ]


def run_target_seeking_orchestrated_system_run(
  *,
  conn,
  draft_id: str,
  planning_run_id: Optional[str],
  business_facts: Dict[str, Any],
  planning_context_summary_json: Optional[Dict[str, Any]],
  ops_json: Dict[str, Any],
  target_market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  fulfillment_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  planning_mode: str,
  planning_mode_reason: str,
  planning_result: Dict[str, Any],
  grid_application_summary: Optional[Dict[str, Any]],
  catalog_source_model_input_json: Dict[str, Any],
  applied_model_input_json: Dict[str, Any],
  applied_finmo_json: Dict[str, Any],
  stage_ramp_contract: Optional[Dict[str, Any]] = None,
  payroll_headcount: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Top-level target-seeking orchestrator.

  Same signature as post_intake_convergence.runner.run_unified_post_grid_system_run
  so it can be slotted in as a drop-in replacement at the intake_consult
  call site. Returns the same payload shape, with an additional
  `target_seeking_diagnostics` section.
  """
  try:
    from financial_model_engine.model_inputs import QUARTER_COUNT  # type: ignore
  except Exception:
    QUARTER_COUNT = 20  # type: ignore

  horizon = int(QUARTER_COUNT)

  # ---------- Phase 9 Phase H: reset GPT call budget for this run --------
  # Doctrine Q4: maximum 4 GPT calls per planning run, hard runtime cap.
  # Reset the counter at the top of every orchestrator invocation so
  # consecutive runs don't bleed budget. The counter is enforced at the
  # call_gpt_with_schema_or_fallback chokepoint — when the budget is
  # exhausted, subsequent calls fall through to the consultant's
  # python_proposer fallback path.
  try:
    from client_intake_and_finmo.post_intake_solver._gpt_critic_io import (  # type: ignore
      reset_gpt_call_budget,
    )
    reset_gpt_call_budget()
  except Exception:
    pass

  # ---------- Phase 9 Phase B Step 0: adaptive policy contract -----------
  # Single source of truth for stage profile, planning mode, loss-tolerance
  # window, viability deadlines, allowed adaptation families, and per-driver
  # client-input authority. Computed deterministically from intake + FINMO
  # snapshot + (later) industry profile. Every downstream consumer reads
  # from this contract instead of inferring stage / mode locally.
  from client_intake_and_finmo.post_intake_adaptive_planning import (  # type: ignore
    compute_adaptive_policy,
  )
  adaptive_policy = compute_adaptive_policy(
    business_facts=business_facts or {},
    ops_json=ops_json or {},
    financials_json=financials_json or {},
    financials_year1_json=financials_year1_json or {},
    finmo_snapshot=applied_finmo_json or {},
    industry_profile=None,  # Phase E populates this once industry_profile.py lands.
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
  )

  # Phase 3.5: build the business_profile that the cohort-matched band
  # resolver consumes. NAICS comes from ops; target_annual_revenue is
  # capacity-driven mature-state revenue (capacity * price * periods *
  # upper-bound utilization) — the structural answer to "what cohort
  # cap-category is this business?" The operator's Year-1 ramp projection
  # is a planning expectation, not a cohort-bucket key; using it
  # under-buckets ramping businesses and returns bands that are too tight.
  from client_intake_and_finmo.post_intake_solver.structural_feasibility_check import (  # type: ignore
    authoritative_annual_revenue,
  )
  _bf_template = (business_facts or {}).get("fact_template") if isinstance(business_facts, dict) else {}
  if not isinstance(_bf_template, dict):
    _bf_template = {}
  _target_annual_revenue = authoritative_annual_revenue(
    ops_json=ops_json or {},
    financials_year1_json=financials_year1_json or {},
    financials_json=financials_json or {},
  )
  business_profile_for_cohort = {
    "naics_6": (
      "".join(ch for ch in str((ops_json or {}).get("business_naics_6") or "") if ch.isdigit())
      if isinstance(ops_json, dict)
      else None
    ),
    "target_annual_revenue": _target_annual_revenue,
    "stage": (
      _clean_text(_bf_template.get("business_stage"))
      or _clean_text((business_facts or {}).get("business_stage"))
      or None
    ),
    "business_model": _clean_text(_bf_template.get("business_model")) or None,
  }

  pre_input = _ensure_solver_inputs(
    model_input_json=applied_model_input_json or {},
    ops_json=ops_json,
    horizon=horizon,
    business_profile=business_profile_for_cohort,
  )
  inputs = _solver_input_payloads(pre_input)
  envelope_payload = inputs["envelope"]
  targets_payload = inputs["targets"]

  # ---------- Phase 6 Step 9: pre-flight structural feasibility check ----
  # Before Phase 3 calibration, before pre-flight bisection, before the
  # inner runner: verify the business as configured can be modeled at
  # all. If revenue at maximum plausible utilization cannot cover
  # lower-bound fixed costs (payroll + lease + debt service), no
  # combination of band-internal lever values produces a viable plan.
  # The cascade's Tier 7 used to paper this case as success; Step 9
  # produces structured recommended_adjustments so the cascade /
  # consultants see actionable guidance. Per Phase 7.2 directive: the
  # check NEVER halts the run — the system's job is to adapt and produce
  # a feasible plan, not to refuse to plan. Infeasibility becomes context
  # the cascade uses to know which bands to widen (capacity / price) and
  # which costs to push down (payroll headcount when over-staffed).
  from client_intake_and_finmo.post_intake_solver.structural_feasibility_check import (  # type: ignore
    verify_structural_feasibility,
  )
  structural_feasibility = verify_structural_feasibility(
    ops_json=ops_json or {},
    financials_json=financials_json or {},
    financials_year1_json=financials_year1_json or {},
    payroll_headcount=payroll_headcount or {},
    business_profile=business_profile_for_cohort,
  )
  structural_feasibility_diagnostic: Dict[str, Any] = (
    structural_feasibility.to_dict() if not structural_feasibility.feasible else {}
  )
  feasibility_restoration_diagnostic: Dict[str, Any] = {}
  if not structural_feasibility.feasible:
    # Phase 7.2: feasibility restoration cascade. Hard-fail catalyst from
    # the structural check is what triggers adaptation here. Levers are
    # tried in priority (headcount rationalization, unit price within
    # band, utilization within band, capacity expansion as final
    # unbounded guarantee). Customer always gets a plan; the cascade
    # adjusts the inputs and downstream Phase 3 / solver continue with
    # the adapted configuration.
    from client_intake_and_finmo.post_intake_solver.feasibility_restoration import (  # type: ignore
      restore_feasibility,
    )
    naics_6 = business_profile_for_cohort.get("naics_6") if isinstance(business_profile_for_cohort, dict) else None
    restoration = restore_feasibility(
      structural_result=structural_feasibility,
      ops_json=ops_json or {},
      financials_json=financials_json or {},
      financials_year1_json=financials_year1_json or {},
      payroll_headcount=payroll_headcount or {},
      business_naics_6=naics_6,
    )
    feasibility_restoration_diagnostic = restoration.to_dict()
    if restoration.applied_adjustments:
      # Swap in the adapted intake. ops_json and payroll_headcount are
      # consumed downstream by Phase 3 consultants (via resolver_runtime_objects)
      # and by the band assemblers; updating them here propagates the
      # adapted configuration across every site that reads these payloads.
      if isinstance(restoration.adjusted_ops_json, dict):
        ops_json = restoration.adjusted_ops_json
      if isinstance(restoration.adjusted_payroll_headcount, dict):
        payroll_headcount = restoration.adjusted_payroll_headcount
      # Patch the in-memory model_input_json revenue rows + payroll rows
      # so downstream FINMO computations see the adapted values.
      applied_model_input_json = _apply_restoration_to_model_input(
        model_input_json=applied_model_input_json or {},
        adjusted_ops_json=ops_json,
        adjusted_payroll_headcount=payroll_headcount,
        horizon=horizon,
      )
      # Recompute capacity-driven cohort revenue / envelope payload to
      # match the adapted scale (capacity expansion lever changes the
      # cohort target_annual_revenue too).
      _target_annual_revenue = authoritative_annual_revenue(
        ops_json=ops_json or {},
        financials_year1_json=financials_year1_json or {},
        financials_json=financials_json or {},
      )
      business_profile_for_cohort["target_annual_revenue"] = _target_annual_revenue
      pre_input = _ensure_solver_inputs(
        model_input_json=applied_model_input_json or {},
        ops_json=ops_json,
        horizon=horizon,
        business_profile=business_profile_for_cohort,
      )
      inputs = _solver_input_payloads(pre_input)
      envelope_payload = inputs["envelope"]
      targets_payload = inputs["targets"]

  # ---------- Phase 9 P3.5: Phase 3 GPT consultants RETIRED -----
  # The three Phase 3 consultants (band_shaping, target_shaping,
  # conflict_adjudication) used to fire here. They were retired in
  # Phase 9 P3.5 because they put GPT INSIDE the deterministic solver
  # loop — they amended `envelope_payload.drivers` and
  # `targets_payload.metrics` per-lever / per-metric / per-conflict,
  # and those amended payloads were read by the pre-flight target
  # seeking pass, the cascade, the post-cascade target seeking pass,
  # and the realism gate. The Phase 9 P3 architecture says the solver
  # loop is deterministic algebra; GPT lives at intake, cash strategy,
  # path engine ramps, and the new exhaustion handler.
  #
  # The consultants were structurally dormant from authoring through
  # commit 4a09142 because the OpenAI Responses API rejects the
  # `seed` parameter the chokepoint was sending; every consultant
  # call returned the python-proposer-only fallback. The 16/16
  # ExpressLogix passes happened with consultants effectively absent.
  # Removing them returns the system to its tested-working baseline.
  #
  # Deterministic Python proposers — `assemble_driver_movement_envelope`
  # (drivers / bands) and `assemble_finmo_output_targets` (per-metric
  # target ranges) — are the sole source of envelope_payload and
  # targets_payload. The pre-solver joint feasibility check
  # (`verify_joint_feasibility`) and the cascade still run below.
  calibration_diagnostics: Dict[str, Any] = {
    "phase_3_consultants": "retired_phase_9_p3_5",
  }

  # ---------- Phase 5.2 R3: pre-solver joint feasibility check -----
  # Verify the calibrated bands collectively admit a feasible solution
  # for the calibrated target ranges. Infeasibility triggers the
  # pre-solver adaptation cascade (Tier 1 walk-back -> Tier 2 cohort
  # fallback). If the cascade restores feasibility we proceed; if not,
  # the post-flight cascade takes over and Tier 7 always lands a plan.
  if envelope_payload and targets_payload:
    from client_intake_and_finmo.post_intake_solver.joint_feasibility_check import (  # type: ignore
      verify_joint_feasibility,
    )
    from client_intake_and_finmo.post_intake_solver.adaptation_cascade import (  # type: ignore
      run_pre_solver_feasibility_cascade,
    )
    feasibility = verify_joint_feasibility(
      envelope_payload=envelope_payload,
      targets_payload=targets_payload,
      business_profile=business_profile_for_cohort,
    )
    calibration_diagnostics["joint_feasibility_initial"] = feasibility.to_dict()
    if not feasibility.feasible:
      cascade_outcome = run_pre_solver_feasibility_cascade(
        envelope_payload=envelope_payload,
        targets_payload=targets_payload,
        business_profile=business_profile_for_cohort,
        initial_diagnostic=feasibility,
      )
      envelope_payload = cascade_outcome.get("envelope_payload") or envelope_payload
      targets_payload = cascade_outcome.get("targets_payload") or targets_payload
      calibration_diagnostics["joint_feasibility_cascade"] = cascade_outcome.get("diagnostic", {})

  # Re-stamp the calibrated envelope + targets onto the model_input so
  # downstream callers (sanity assertion, finmo_bridge re-builds) see
  # the calibrated payloads, not the deterministic Python defaults.
  pre_input = _stamp_solver_inputs(
    model_input_json=pre_input,
    envelope_payload=envelope_payload,
    targets_payload=targets_payload,
  )

  build_finmo_callable = _build_finmo_callable(
    business_facts=business_facts or {},
    ops_json=ops_json or {},
    people_json=people_json or {},
    financials_json=financials_json or {},
    financials_year1_json=financials_year1_json or {},
    fulfillment_json=fulfillment_json or {},
    marketing_model_json=marketing_model_json or {},
  )
  apply_lever_callable = _build_apply_lever_callable(
    horizon=horizon,
    stage_ramp_contract=stage_ramp_contract,
    adaptive_policy_dict=adaptive_policy.to_dict(),
  )

  from client_intake_and_finmo.post_intake_solver import (  # type: ignore
    driver_influence_map,
  )
  influence_payload = driver_influence_map()

  # ---------- Pre-flight target-seeking pass ----------
  # Single-driver bisection only — no inner joint fit. The pre-flight pass
  # exists to envelope-shape the starting state before handing off to the
  # inner runner; deep multi-lever fitting belongs in the inner runner or
  # in the post-flight repair pass.
  pre_pass = _run_target_seeking_pass(
    pass_label="pre_flight",
    model_input_json=pre_input,
    build_finmo_callable=build_finmo_callable,
    apply_lever_callable=apply_lever_callable,
    envelope_payload=envelope_payload,
    targets_payload=targets_payload,
    influence_payload=influence_payload,
    max_iterations=_DEFAULT_PREFLIGHT_MAX_ITERATIONS,
    numeric_tolerance=_DEFAULT_NUMERIC_TOLERANCE,
    enable_inner_joint_fit=False,
    horizon=horizon,
  )
  pre_shaped_model_input = pre_pass.get("final_model_input_json") or pre_input
  pre_shaped_finmo = pre_pass.get("final_finmo_json") or {}

  # ---------- Inner runner — Phase 8 bypass ----------
  # The legacy convergence runner is broken post-deletion of the issue
  # machinery: every fail-fast the legacy GPT loop's authority-
  # reapplication used to suppress now fires (revenue formula
  # validators, payroll schedule rollups, etc.). The orchestrator-
  # driven post-cascade tail (cash pass + realism gate + finalize +
  # persist) is the new authoritative path. Skip the legacy inner
  # runner and use a passthrough so the cascade has a starting state
  # to work from. The acceptance gate's verdict is the authority on
  # whether the resulting plan is sensible.
  inner_result = {
    "status": "phase_8_inner_runner_bypassed",
    "model_input_json": copy.deepcopy(pre_shaped_model_input or {}),
    "finmo_json": copy.deepcopy(pre_shaped_finmo or applied_finmo_json or {}),
    "abort_reason": "phase_8_legacy_convergence_runner_skipped",
  }

  # Phase 6 Step 7 — band-respecting failures from the inner runner now
  # return status="abort_for_cascade" with an abort_reason instead of
  # raising. The orchestrator detects the signal and forces hard_fails
  # so the post-flight cascade fires below. Step 8 makes the cascade
  # reason-aware (start at the tier matched to the abort_reason instead
  # of always Tier 1).
  inner_runner_abort_reason: Optional[str] = None
  inner_runner_abort_diagnostics: Optional[Dict[str, Any]] = None
  if (
    isinstance(inner_result, dict)
    and _clean_text(inner_result.get("status")) == "abort_for_cascade"
  ):
    inner_runner_abort_reason = _clean_text(inner_result.get("abort_reason")) or "unknown_abort"
    inner_runner_abort_diagnostics = (
      copy.deepcopy(inner_result.get("diagnostics"))
      if isinstance(inner_result.get("diagnostics"), dict) else {}
    )

  inner_model_input_json = inner_result.get("model_input_json") if isinstance(inner_result, dict) else None
  inner_finmo_json = inner_result.get("finmo_json") if isinstance(inner_result, dict) else None

  # Refresh solver_input on the post-inner model so post-flight reads the
  # current envelope/targets the inner runner may have re-stamped.
  post_inner_model = _ensure_solver_inputs(
    model_input_json=inner_model_input_json or {},
    ops_json=ops_json,
    horizon=horizon,
    business_profile=business_profile_for_cohort,
  )
  post_inputs = _solver_input_payloads(post_inner_model)
  envelope_payload_post = post_inputs["envelope"] or envelope_payload
  targets_payload_post = post_inputs["targets"] or targets_payload

  # ---------- Post-flight assertion + repair pass ----------
  hard_fails = _hard_fail_violations_from_assertion(
    finmo_json=inner_finmo_json or {},
    envelope_payload=envelope_payload_post,
    targets_payload=targets_payload_post,
  )

  repair_pass: Optional[Dict[str, Any]] = None
  final_model_input_json = inner_model_input_json
  final_finmo_json = inner_finmo_json
  if hard_fails:
    # Post-flight repair invokes the inner joint-fit adapter when single-
    # driver bisection stagnates. The adapter delegates joint multi-lever
    # fitting to numeric_solver.solve_review_plan; the existing scipy /
    # issue-code infrastructure becomes the gap-closer the outer loop
    # calls when bisection alone is insufficient.
    repair_pass = _run_target_seeking_pass(
      pass_label="post_flight_repair",
      model_input_json=post_inner_model,
      build_finmo_callable=build_finmo_callable,
      apply_lever_callable=apply_lever_callable,
      envelope_payload=envelope_payload_post,
      targets_payload=targets_payload_post,
      influence_payload=influence_payload,
      max_iterations=_DEFAULT_POSTFLIGHT_MAX_ITERATIONS,
      numeric_tolerance=_DEFAULT_NUMERIC_TOLERANCE,
      enable_inner_joint_fit=True,
      horizon=horizon,
    )
    final_model_input_json = repair_pass.get("final_model_input_json") or inner_model_input_json
    final_finmo_json = repair_pass.get("final_finmo_json") or inner_finmo_json

  # Final hard-fail evaluation. By construction the outer loop is the
  # authoritative gate — if we still have hard_fail residuals here, raise
  # a band-respecting diagnostic. The structural failure modes are:
  #   - stuck_pinned    -> envelope too tight or target too narrow
  #   - no_candidate_levers -> influence-map gap
  #   - max_iterations_reached -> diverged/oscillated
  #   - hard_fail residuals after repair -> target jointly infeasible
  final_hard_fails = _hard_fail_violations_from_assertion(
    finmo_json=final_finmo_json or {},
    envelope_payload=envelope_payload_post,
    targets_payload=targets_payload_post,
  )

  diagnostics: Dict[str, Any] = {
    "calibration": calibration_diagnostics,
    "pre_flight": {
      "status": pre_pass.get("status"),
      "iterations_used": pre_pass.get("iterations_used"),
      "trace_length": len(pre_pass.get("trace") or []),
    },
    "inner_runner_invoked": True,
    "inner_runner_abort_reason": inner_runner_abort_reason,
    "inner_runner_abort_diagnostics": inner_runner_abort_diagnostics,
    "post_flight_repair": (
      {
        "status": repair_pass.get("status"),
        "iterations_used": repair_pass.get("iterations_used"),
        "trace_length": len(repair_pass.get("trace") or []),
      }
      if repair_pass
      else None
    ),
    "final_hard_fail_count": len(final_hard_fails),
  }

  # Phase 3.7 + 6 Step 7: cascade fires on either of two signals:
  #   (a) post-flight repair left hard_fail residuals (existing behavior)
  #   (b) inner runner returned status=abort_for_cascade with a
  #       band-respecting reason — Tier 1+ adaptation is the designed
  #       remediation path, replacing the prior raise-and-die.
  # Tier 7 is structurally guaranteed to produce a plan; Step 8 makes
  # the cascade pick its starting tier based on abort_reason instead of
  # always Tier 1.
  plan_confidence: str = "high_no_adaptation"
  cascade_diagnostics: Optional[Dict[str, Any]] = None
  if final_hard_fails or inner_runner_abort_reason is not None:
    from client_intake_and_finmo.post_intake_solver.adaptation_cascade import (  # type: ignore
      run_adaptation_cascade,
    )
    inner_runner_kwargs = {
      "conn": conn,
      "draft_id": draft_id,
      "planning_run_id": planning_run_id,
      "business_facts": business_facts,
      "planning_context_summary_json": planning_context_summary_json,
      "ops_json": ops_json,
      "target_market_json": target_market_json,
      "people_json": people_json,
      "financials_json": financials_json,
      "financials_year1_json": financials_year1_json,
      "fulfillment_json": fulfillment_json,
      "marketing_model_json": marketing_model_json,
      "planning_mode": planning_mode,
      "planning_mode_reason": planning_mode_reason,
      "planning_result": planning_result,
      "grid_application_summary": grid_application_summary,
      "catalog_source_model_input_json": catalog_source_model_input_json,
      "applied_finmo_json": applied_finmo_json,
      "stage_ramp_contract": stage_ramp_contract,
      "payroll_headcount": payroll_headcount,
    }
    original_stage_family: Optional[str] = None
    if isinstance(stage_ramp_contract, dict):
      original_stage_family = _clean_text(stage_ramp_contract.get("stage_family")) or None
    business_naics_6_for_cascade = ""
    if isinstance(ops_json, dict):
      business_naics_6_for_cascade = "".join(
        ch for ch in str(ops_json.get("business_naics_6") or "") if ch.isdigit()
      )
    business_stage_for_cascade = (
      _clean_text((business_facts or {}).get("fact_template", {}).get("business_stage"))
      if isinstance(business_facts, dict) else ""
    )
    try:
      final_payload, plan_confidence, cascade_diagnostics = run_adaptation_cascade(
        pre_input=pre_input,
        post_inner_model=post_inner_model,
        inner_result=inner_result,
        final_finmo_json=final_finmo_json or {},
        envelope_payload_post=envelope_payload_post or {},
        targets_payload_post=targets_payload_post or {},
        influence_payload=influence_payload or {},
        final_hard_fails=final_hard_fails,
        pre_pass=pre_pass,
        repair_pass=repair_pass,
        build_finmo_callable=build_finmo_callable,
        apply_lever_callable=apply_lever_callable,
        run_target_seeking_pass_callable=_run_target_seeking_pass,
        hard_fail_violations_callable=_hard_fail_violations_from_assertion,
        inner_runner_callable=_inner_runner,
        inner_runner_kwargs=inner_runner_kwargs,
        original_planning_mode=planning_mode,
        original_planning_mode_reason=planning_mode_reason or "",
        original_stage_family=original_stage_family,
        original_stage_ramp_contract=stage_ramp_contract,
        business_naics_6=business_naics_6_for_cascade or None,
        business_stage=business_stage_for_cascade or None,
        horizon=horizon,
        abort_reason=inner_runner_abort_reason,
      )
    except Exception as cascade_exc:
      # Phase 9 Phase D — catch CascadeAndRestorationExhausted (terminal
      # cause #7). Surface the diagnostic to the orchestrator's result
      # so the consultant sees what was tried; do NOT let this become an
      # unhandled exception (which would be terminal cause #6).
      from client_intake_and_finmo.post_intake_solver.adaptation_cascade import (  # type: ignore
        CascadeAndRestorationExhausted,
      )
      if isinstance(cascade_exc, CascadeAndRestorationExhausted):
        cascade_diagnostics = {
          "tier_landed": None,
          "tier_landed_name": "terminal_cause_7_cascade_and_restoration_exhausted",
          "plan_confidence": "terminal_cause_7",
          "diagnostic": cascade_exc.diagnostic_payload,
        }
        final_payload = copy.deepcopy(inner_result if isinstance(inner_result, dict) else {})
        if final_model_input_json is not None:
          final_payload["model_input_json"] = final_model_input_json
        if final_finmo_json:
          final_payload["finmo_json"] = final_finmo_json
        plan_confidence = "terminal_cause_7"
      else:
        # Unexpected exception — re-raise (becomes doctrine cause #6).
        raise
    diagnostics["adaptation_cascade"] = cascade_diagnostics
    final_model_input_json = final_payload.get("model_input_json") or final_model_input_json
    final_finmo_json = final_payload.get("finmo_json") or final_finmo_json
    inner_result = final_payload if isinstance(final_payload, dict) else inner_result

  # Successful run — augment inner_result with diagnostics and the
  # potentially-repaired final state.
  next_result = copy.deepcopy(inner_result if isinstance(inner_result, dict) else {})
  if final_model_input_json is not None:
    next_result["model_input_json"] = final_model_input_json
  if final_finmo_json:
    next_result["finmo_json"] = final_finmo_json
  next_result["target_seeking_diagnostics"] = diagnostics
  next_result["plan_confidence"] = plan_confidence
  if cascade_diagnostics is not None:
    next_result["adaptation_cascade_diagnostics"] = cascade_diagnostics
  # Phase 9 Phase B: stamp the adaptive policy contract on the result so
  # downstream consumers (acceptance gate, workbook export, run report)
  # see the same policy the cascade saw. Single source of truth.
  next_result["adaptive_policy"] = adaptive_policy.to_dict()

  # Phase 9 Phase H: stamp the GPT call diagnostic so the acceptance gate
  # sees how much of the 4-call budget was used and which consultants ran.
  try:
    from client_intake_and_finmo.post_intake_solver._gpt_critic_io import (  # type: ignore
      get_gpt_call_count,
      get_gpt_call_log,
    )
    next_result["gpt_call_budget_diagnostic"] = {
      "calls_used": get_gpt_call_count(),
      "budget": 4,
      "log": get_gpt_call_log(),
    }
  except Exception:
    pass

  # Phase 9 P3.10 Bug A fix — debt_schedule snapshot is no longer built
  # here. The pre-cascade snapshot reflected pre-cash-pass model_input
  # (DEBT_REPAYMENT_LEVER values all zero, so total_principal_payment=0
  # and closing_debt unchanged across 20 quarters). The finalize
  # validator caught the resulting flat-principal violation while the
  # cash pass had ALREADY produced the proper amortization in memory —
  # the validator was just looking at a stale snapshot.
  #
  # The build now runs inside _run_post_cascade_completion, immediately
  # before run_finalize_post_intake_validation, against the post-cash-
  # pass final_model_input_json + final_finmo_json. Single source of
  # truth. The draft.debt_schedule SQL column is updated by that same
  # post-cash-pass build site.

  if isinstance(payroll_headcount, dict) and payroll_headcount:
    next_result.setdefault("payroll_headcount", payroll_headcount)

  # Phase 8 step 4f: drive the post-cascade tail (target-seeking solver
  # + cash pass + realism gate + finalize + persist) directly from the
  # orchestrator. The convergence runner used to do this on its
  # normal-success path (runner.py:2489-3483), but when the runner
  # returned status=abort_for_cascade the cycle loop exited before
  # reaching cash + finalize. The cascade landing a final state is a
  # successful run — it must complete the post-cascade tail or the
  # acceptance gate will (rightly) refuse to call it passed.
  next_result = _run_post_cascade_completion(
    conn=conn,
    draft_id=draft_id,
    planning_run_id=planning_run_id,
    next_result=next_result,
    final_model_input_json=final_model_input_json,
    final_finmo_json=final_finmo_json,
    payroll_headcount=payroll_headcount,
    business_facts=business_facts,
    ops_json=ops_json,
    target_market_json=target_market_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    fulfillment_json=fulfillment_json,
    marketing_model_json=marketing_model_json,
    planning_context_summary_json=planning_context_summary_json,
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    grid_application_summary=grid_application_summary,
    stage_ramp_contract=stage_ramp_contract,
    plan_confidence=plan_confidence,
    cascade_diagnostics=cascade_diagnostics,
    diagnostics=diagnostics,
    business_naics_6=business_naics_6_for_cascade if "business_naics_6_for_cascade" in dir() else None,
    build_finmo_callable=build_finmo_callable,
    apply_lever_callable=apply_lever_callable,
    envelope_payload_post=envelope_payload_post,
    targets_payload_post=targets_payload_post,
    influence_payload=influence_payload,
    horizon=horizon,
    adaptive_policy_dict=adaptive_policy.to_dict(),
  )

  return next_result


def _run_post_cascade_completion(
  *,
  conn,
  draft_id: str,
  planning_run_id: str,
  next_result: Dict[str, Any],
  final_model_input_json: Optional[Dict[str, Any]],
  final_finmo_json: Optional[Dict[str, Any]],
  payroll_headcount: Optional[Dict[str, Any]],
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  target_market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  fulfillment_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  planning_context_summary_json: Dict[str, Any],
  planning_mode: str,
  planning_mode_reason: str,
  grid_application_summary: Dict[str, Any],
  stage_ramp_contract: Optional[Dict[str, Any]],
  plan_confidence: str,
  cascade_diagnostics: Optional[Dict[str, Any]],
  diagnostics: Dict[str, Any],
  business_naics_6: Optional[str] = None,
  build_finmo_callable: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
  apply_lever_callable: Optional[Callable[[Dict[str, Any], str, float], Dict[str, Any]]] = None,
  envelope_payload_post: Optional[Dict[str, Any]] = None,
  targets_payload_post: Optional[Dict[str, Any]] = None,
  influence_payload: Optional[Dict[str, Any]] = None,
  horizon: int = 20,
  adaptive_policy_dict: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Phase 8 — orchestrator-driven post-cascade tail.

  After the cascade lands a final state, this function runs:
    1. Target-seeking solver (post-cascade pass) — drives model_input
       toward the cascade's final calibrated targets. Without this,
       revenue stays at the operator-stated baseline (acceptance gate's
       revenue_not_flat check fails on every Sunny-style steady-state
       plan).
    2. Cash pass (minimum debt schedule) — covers negative cash
       quarters so the FINMO output reflects a fundable plan.
    3. Realism gate (`validate_industry_realism_bands`) — produces the
       per-metric provenance the acceptance gate checks for.
    4. Finalize validation (`run_finalize_post_intake_validation`) —
       runs the solver_target_assertion, global invariants, balance-
       sheet driver finalize, cash phase trace.
    5. Persist with stage="post_intake_finalize_validation_completed",
       status="completed".

  Each step has its own try/except and records its outcome in
  `next_result["post_cascade_completion"]`. A failure in any step
  surfaces in the acceptance gate's verdict; this function never
  swallows failures into a fake success.
  """
  completion_trace: Dict[str, Any] = {
    "post_cascade_solver_pass": {"status": "not_run"},
    "cash_pass": {"status": "not_run"},
    "realism_gate": {"status": "not_run"},
    "finalize_validation": {"status": "not_run"},
    "persist_finalize_stage": {"status": "not_run"},
  }

  # Resolve business_naics_6 if not passed in.
  if not business_naics_6 and isinstance(ops_json, dict):
    business_naics_6 = "".join(
      ch for ch in str(ops_json.get("business_naics_6") or "") if ch.isdigit()
    )

  # 1. Target-seeking solver pass — drives model_input toward the
  # cascade's final calibrated targets using single-driver bisection
  # (with inner joint fit available for multi-lever fitting). The
  # pre-flight pass at orchestrator.py:737 ran the same machinery on
  # the pre-cascade state; this re-run on the cascade's final state
  # uses the (possibly walked-back) targets the cascade landed on.
  if (
    callable(build_finmo_callable)
    and callable(apply_lever_callable)
    and isinstance(targets_payload_post, dict) and targets_payload_post.get("metrics")
  ):
    try:
      solver_pass = _run_target_seeking_pass(
        pass_label="post_cascade",
        model_input_json=copy.deepcopy(final_model_input_json or {}),
        build_finmo_callable=build_finmo_callable,
        apply_lever_callable=apply_lever_callable,
        envelope_payload=envelope_payload_post,
        targets_payload=targets_payload_post,
        influence_payload=influence_payload,
        max_iterations=_DEFAULT_POSTFLIGHT_MAX_ITERATIONS,
        numeric_tolerance=_DEFAULT_NUMERIC_TOLERANCE,
        enable_inner_joint_fit=True,
        horizon=horizon,
      )
      solver_final_model = solver_pass.get("final_model_input_json")
      solver_final_finmo = solver_pass.get("final_finmo_json")
      if isinstance(solver_final_model, dict):
        final_model_input_json = solver_final_model
        next_result["model_input_json"] = final_model_input_json
      if isinstance(solver_final_finmo, dict) and solver_final_finmo:
        final_finmo_json = solver_final_finmo
        next_result["finmo_json"] = final_finmo_json
      completion_trace["post_cascade_solver_pass"] = {
        "status": str(solver_pass.get("status") or "unknown"),
        "iterations_used": solver_pass.get("iterations_used"),
        "trace_length": len(solver_pass.get("trace") or []),
      }
    except Exception as exc:
      completion_trace["post_cascade_solver_pass"] = {
        "status": "failed",
        "error": f"{type(exc).__name__}: {str(exc)[:500]}",
      }
  else:
    completion_trace["post_cascade_solver_pass"] = {
      "status": "skipped",
      "reason": "missing_callables_or_targets_payload",
    }

  # 1.5. Phase 9 Phase C3: the 1% per-quarter unit_price ramp deleted
  # here. The post-cascade solver's apply_lever_callable is now path-
  # aware (Phase C3), so Unit Price moves with industry_convergence_decay
  # shape, Capacity uses capacity_expansion, Utilization uses s_curve,
  # COGS / Marketing / R&D / G&A use glidepath, and AR/AP/Inventory days
  # use linear_to_mature. Path shapes are computed against the persisted
  # stage_ramp_contract.quarter_ramp_grid and the adaptive policy's
  # viability deadlines. The Phase 8 1% nudge was a band-aid for the
  # flat-write problem; the path-aware writer makes it unnecessary.
  completion_trace["unit_price_ramp"] = {
    "status": "deleted_phase_9_c3",
    "reason": "path_aware_writer_replaces_post_cascade_ramp",
  }

  # 1.55. Phase 9 Gap A — post-cascade path stamp pass.
  #
  # When the cascade lands tier-0 (no movement needed because operator-
  # baseline already satisfies targets), the in-solver path engine never
  # fires for un-moved levers. Result: model_input keeps flat Q1-Q20
  # values for capacity / unit_price / utilization / cogs% / marketing% /
  # ar_days / etc. — the universal-flat regime the doctrine forbids.
  #
  # This pass walks every solver-controlled row and applies the doctrinal
  # shape. Universal across business types: stage_profile reads from the
  # adaptive policy contract (Phase B), per-driver shape from the path
  # engine registry (Phase C2), industry mature target from the
  # IndustryProfile (Phase E). Q1 anchor = stage_anchor_fraction × target.
  try:
    from client_intake_and_finmo.post_intake_adaptive_planning import (  # type: ignore
      apply_path_stamp_pass,
      get_industry_profile,
    )
    from client_intake_and_finmo.finmo_bridge import (  # type: ignore
      build_python_finmo_json,
    )
    from client_intake_and_finmo.post_intake_sequence import (  # type: ignore
      post_intake_sequence_step_scope,
    )
    naics_for_stamp = ""
    if isinstance(ops_json, dict):
      naics_for_stamp = "".join(
        ch for ch in str(ops_json.get("business_naics_6") or "") if ch.isdigit()
      )
    stamp_industry_profile = get_industry_profile(
      naics_6=naics_for_stamp or None,
      stage_profile=(adaptive_policy_dict or {}).get("stage_profile", "operational"),
      target_annual_revenue=None,
    ).to_dict()
    with post_intake_sequence_step_scope(
      step_key="post_intake_target_seeking_post_cascade_path_stamp",
      executor_function="phase_9_gap_a_path_stamp_pass",
    ):
      stamp_result = apply_path_stamp_pass(
        model_input_json=final_model_input_json or {},
        stage_ramp_contract=stage_ramp_contract,
        adaptive_policy=adaptive_policy_dict,
        industry_profile=stamp_industry_profile,
        horizon=int(horizon or 20),
      )
      if stamp_result.get("applied_updates_count", 0) > 0:
        # Rebuild FINMO so the rest of the post-cascade tail (composite
        # revenue check, cash strategy, realism gate, finalize) sees the
        # path-shaped state.
        rebuilt = build_python_finmo_json(
          model_input_json=copy.deepcopy(final_model_input_json or {}),
        )
        if isinstance(rebuilt, dict) and rebuilt:
          final_finmo_json = rebuilt
          next_result["finmo_json"] = final_finmo_json
          next_result["model_input_json"] = final_model_input_json
    completion_trace["path_stamp_pass"] = stamp_result
  except Exception as exc:
    completion_trace["path_stamp_pass"] = {
      "status": "failed",
      "error": f"{type(exc).__name__}: {str(exc)[:500]}",
    }

  # 1.6. Phase 9 Phase C4: composite revenue trajectory check against
  # stage_ramp_contract.quarter_ramp_grid. Per-driver path shaping
  # (Capacity × Unit Price × Utilization) does not guarantee that the
  # composite revenue stays inside the contract's revenue_qoq_target /
  # revenue_qoq_max envelope — three glidepaths multiplied together can
  # diverge. This check records, per-quarter, whether the realized
  # composite is inside the contract bounds.
  #
  # Phase D5: out-of-band quarters are routed through the issue_router
  # to the revenue_achievability adaptation family. Routes are stamped
  # on completion_trace so the cascade and the acceptance gate see the
  # remediation queue.
  try:
    composite_check = _validate_composite_revenue_against_contract(
      model_input_json=final_model_input_json or {},
      stage_ramp_contract=stage_ramp_contract,
    )
    completion_trace["composite_revenue_check"] = composite_check
    out_of_band = [
      q for q in (composite_check.get("per_quarter") or [])
      if isinstance(q, dict) and q.get("status") == "out_of_band"
    ]
    if out_of_band:
      from client_intake_and_finmo.post_intake_adaptive_planning import (  # type: ignore
        route_composite_revenue_violation,
      )
      composite_routes = route_composite_revenue_violation(
        out_of_band_quarters=out_of_band,
        adaptive_policy=adaptive_policy_dict,
      )
      completion_trace["composite_revenue_routes"] = [
        r.to_dict() for r in composite_routes
      ]
  except Exception as exc:
    # Phase 9 P3.10 Commit 4 — composite revenue trajectory check
    # exception raises under test mode. Audit #15: silent failure
    # skips the drift check; downstream sees no remediation routes
    # and the cascade has no idea the revenue path violates the
    # stage_ramp_contract.
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      convergence_test_mode_enabled,
    )
    if convergence_test_mode_enabled():
      raise
    completion_trace["composite_revenue_check"] = {
      "status": "failed",
      "error": f"{type(exc).__name__}: {str(exc)[:500]}",
    }

  # 1.7. Phase 9 P3 — Target-driven restoration loop.
  #
  # Replaces the silo'd _remediate_realism_hard_fails. Iterates 4 solver
  # targets in priority order (gross_margin, ebitda_margin,
  # current_assets_minus_cash, current_liabilities_to_revenue) across
  # all 20 quarters at once, allocating per-quarter delta across
  # operating-side drivers proportional to slack-to-bound. Cash strategy
  # runs AFTER this loop with the new operating model — financing
  # decisions size against the restored trajectory.
  #
  # The loop's authority is operating-side only — it hard-errors on
  # cash-pass-owned levers in any driver list (Owner's Capital,
  # Other Equity, Distributions, Short Term Debt %, Debt Issuance,
  # Debt Repayment).
  try:
    from client_intake_and_finmo.post_intake_target_solver import (  # type: ignore
      run_restoration_loop,
    )
    from client_intake_and_finmo.finmo_bridge import (  # type: ignore
      build_python_finmo_json,
    )
    from client_intake_and_finmo.post_intake_sequence import (  # type: ignore
      post_intake_sequence_step_scope,
    )

    naics_for_restoration = business_naics_6
    if not naics_for_restoration and isinstance(ops_json, dict):
      naics_for_restoration = "".join(
        ch for ch in str(ops_json.get("business_naics_6") or "") if ch.isdigit()
      )

    def _build_finmo_for_restoration(mi: Dict[str, Any]) -> Dict[str, Any]:
      payload = build_python_finmo_json(
        model_input_json=copy.deepcopy(mi or {}),
      )
      return payload if isinstance(payload, dict) else {}

    with post_intake_sequence_step_scope(
      step_key="post_intake_target_seeking_restoration_loop",
      executor_function="phase_9_p3_target_driven_restoration_loop",
    ):
      restoration_result = run_restoration_loop(
        model_input=final_model_input_json or {},
        build_finmo=_build_finmo_for_restoration,
        business_naics_6=naics_for_restoration or None,
        horizon=int(horizon or 20),
        planning_mode=planning_mode,
        # Phase 9 P3.7 — forward-looking exhaustion classifier needs
        # ops/financials/targets so the realism validator runs with
        # the same band-resolution context the post-cascade gate will
        # use (phase_3_calibrated bands, applicability skip, etc.).
        ops_json=ops_json or {},
        financials_json=financials_json or {},
        solver_targets_payload=(
          targets_payload_post
          if isinstance(targets_payload_post, dict)
          and targets_payload_post.get("metrics")
          else (targets_payload or None)
        ),
      )
      # Rebuild FINMO so subsequent steps (cash strategy, realism gate,
      # finalize) see the restored operating model.
      restored_finmo = _build_finmo_for_restoration(final_model_input_json or {})
      if isinstance(restored_finmo, dict) and restored_finmo:
        final_finmo_json = restored_finmo
        next_result["finmo_json"] = final_finmo_json
        next_result["model_input_json"] = final_model_input_json
    completion_trace["restoration_loop"] = restoration_result.to_dict()

    # Phase 9 P3.5 — GPT exhaustion handler.
    #
    # When the deterministic restoration loop returns EXHAUSTED, every
    # operating-side driver is pinned at its conservative bound and
    # viability is still failing. Without this handoff the realism gate
    # rejects the plan. The exhaustion handler asks GPT for EBITDA
    # anchors and consistent driver anchors, interpolates Q1/Q11/Q20 to
    # 20 quarters, recomputes FINMO, iterates if needed, and falls
    # through to a deterministic snap-in if 3 iterations don't land.
    # The handler then publishes a list of realism metric_keys to mute
    # for THIS draft (per-draft, per-metric — not global).
    #
    # Cash strategy is NOT touched. It runs after the handler completes.
    from client_intake_and_finmo.post_intake_target_solver import (  # type: ignore
      RestorationStatus,
    )
    if restoration_result.status == RestorationStatus.EXHAUSTED:
      try:
        from client_intake_and_finmo.post_intake_gpt_exhaustion_handler import (  # type: ignore
          run_gpt_exhaustion_handler,
        )
        with post_intake_sequence_step_scope(
          step_key="post_intake_target_seeking_gpt_exhaustion_handler",
          executor_function="phase_9_p3_5_gpt_exhaustion_handler",
        ):
          handler_result = run_gpt_exhaustion_handler(
            restoration_result=restoration_result,
            model_input=final_model_input_json or {},
            operating_model=ops_json or {},
            build_finmo=_build_finmo_for_restoration,
            intake_context={
              "business_naics_6": naics_for_restoration or None,
              "planning_mode": planning_mode,
              "financials_json": financials_json,
            },
            finmo_json=final_finmo_json,
          )
          # Rebuild FINMO so the rest of the post-cascade tail sees the
          # GPT-authored operating model. Wrapped in its own try so a
          # contract violation here doesn't blow up the run — the
          # handler_result still records what the handler did.
          rebuild_error: Optional[str] = None
          try:
            rebuilt = _build_finmo_for_restoration(final_model_input_json or {})
            if isinstance(rebuilt, dict) and rebuilt:
              final_finmo_json = rebuilt
              next_result["finmo_json"] = final_finmo_json
              next_result["model_input_json"] = final_model_input_json
          except Exception as rebuild_exc:
            rebuild_error = f"{type(rebuild_exc).__name__}: {str(rebuild_exc)[:500]}"
        completion_trace["gpt_exhaustion_handler"] = handler_result.to_dict()
        if rebuild_error:
          completion_trace["gpt_exhaustion_handler"]["post_handler_finmo_rebuild_error"] = rebuild_error
        # Persist the muted realism metrics so the realism gate skips
        # band-checks for those keys on this draft. Per-draft, per-metric.
        muted = list(handler_result.realism_flags_to_mute or [])
        if muted and isinstance(final_model_input_json, dict):
          existing = final_model_input_json.get("_muted_realism_metrics")
          if isinstance(existing, list):
            merged = list(existing)
            for m in muted:
              if m not in merged:
                merged.append(m)
            final_model_input_json["_muted_realism_metrics"] = merged
          else:
            final_model_input_json["_muted_realism_metrics"] = list(muted)
      except Exception as exc:
        # Phase 9 P3.10 Commit 2 — under CONVERGENCE_TEST_MODE the
        # handler exception must propagate. Without this, every
        # PostIntakePreconditionFailed raised from the handler (#19,
        # #27) would be swallowed here and the run would silently
        # continue past the broken plan — the canonical Sunny pattern.
        from client_intake_and_finmo.fail_fast.common import (  # type: ignore
          convergence_test_mode_enabled,
        )
        if convergence_test_mode_enabled():
          raise
        completion_trace["gpt_exhaustion_handler"] = {
          "status": "failed",
          "error": f"{type(exc).__name__}: {str(exc)[:500]}",
        }
  except Exception as exc:
    # Phase 9 P3.10 Commit 2 — same propagation rule for the
    # restoration-loop wrapper. The combined block (loop + handler)
    # must hard-fail under test mode so failures land at the API
    # boundary with a clear diagnostic.
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      convergence_test_mode_enabled,
    )
    if convergence_test_mode_enabled():
      raise
    completion_trace["restoration_loop"] = {
      "status": "failed",
      "error": f"{type(exc).__name__}: {str(exc)[:500]}",
    }

  # 1.9. Phase 9 P3.10 Bug F + Bug D — pre-cash post-handler gate for
  # GPT-authorable checks.
  #
  # Several finalize-stage checks are GPT-authorable: the handler's
  # existing toolset (driver anchors + working_capital_drivers +
  # realism_flags_to_mute) can resolve their failures. But they fire at
  # finalize, AFTER the handler's existing window (restoration EXHAUSTED
  # → handler). The handler is structurally impossible to trigger for
  # these checks today.
  #
  # This gate runs the moved checks against current
  # final_model_input_json + final_finmo_json. If any fail AND the
  # handler has not already run (restoration was not EXHAUSTED), invoke
  # the handler with a synthetic restoration_result carrying the
  # failing checks as failing_metrics. Re-evaluate after handler. If
  # checks still fail (or handler already ran and they still fail),
  # hard-fail HERE before cash pass — the cash pass cannot fix
  # GPT-authorable issues, and surfacing them at finalize is too late.
  #
  # _GPT_AUTHORABLE_PRE_CASH_CHECK_NAMES is the single source of truth
  # for which checks moved.
  _gate_handler_already_ran = False
  try:
    from client_intake_and_finmo.post_intake_target_solver import (  # type: ignore
      RestorationStatus as _GateRestorationStatus,
    )
    _gate_handler_already_ran = bool(
      getattr(restoration_result, "status", None) == _GateRestorationStatus.EXHAUSTED
    )
  except Exception:
    _gate_handler_already_ran = False

  try:
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      PostIntakePreconditionFailed,
      convergence_test_mode_enabled,
    )
    from client_intake_and_finmo.post_intake_target_solver import (  # type: ignore
      HandlerScope,
    )

    def _build_finmo_for_gate(mi: Dict[str, Any]) -> Dict[str, Any]:
      from client_intake_and_finmo.finmo_bridge import (  # type: ignore
        build_python_finmo_json,
      )
      return build_python_finmo_json(model_input_json=copy.deepcopy(mi or {}))

    # iter 19 Stage 3 (F6-Pinnacle) — defensive pre-gate sanity check.
    # Before the GPT-authorable pre-cash gate runs, assert that any
    # contract-derived lever the gate's checks reference is actually
    # WRITTEN in model_input. The motivating case: the gate's stage-ramp
    # profitability check has `expenses::Payroll` in primary_levers; if
    # the payroll_headcount has positive quarter_totals but
    # model_input expenses::Payroll values are all zero, the writeback
    # was skipped upstream. The generic "unfixed_after_handler"
    # diagnostic that the cascade would raise is misleading — the
    # handler does not have payroll lever authority (F6 pattern from
    # iter 18 investigation). Instead raise a specific diagnostic
    # naming the upstream contract owner.
    _assert_pre_cash_gate_contract_levers_written(
      model_input_json=final_model_input_json or {},
      payroll_headcount=payroll_headcount or {},
    )

    gate_violations, gate_scope = _evaluate_gpt_authorable_pre_cash_checks(
      stage_ramp_contract=stage_ramp_contract or {},
      model_input_json=final_model_input_json or {},
      finmo_json=final_finmo_json or {},
      payroll_headcount=payroll_headcount or {},
      financials_json=financials_json or {},
      ops_json=ops_json or {},
    )

    if gate_violations and not _gate_handler_already_ran:
      from client_intake_and_finmo.post_intake_gpt_exhaustion_handler import (  # type: ignore
        run_gpt_exhaustion_handler,
      )
      from client_intake_and_finmo.post_intake_sequence import (  # type: ignore
        post_intake_sequence_step_scope,
      )
      synthetic_result = _PreCashGateRestorationResult(
        scope=gate_scope,
        failing_metrics=gate_violations,
        q11_ebitda_margin=_q11_ebitda_margin_from_finmo(final_finmo_json),
      )
      with post_intake_sequence_step_scope(
        step_key="post_intake_target_seeking_pre_cash_gate_handler",
        executor_function="phase_9_p3_10_pre_cash_gate_handler",
      ):
        gate_handler_result = run_gpt_exhaustion_handler(
          restoration_result=synthetic_result,
          model_input=final_model_input_json or {},
          operating_model=ops_json or {},
          build_finmo=_build_finmo_for_gate,
          intake_context={
            "business_naics_6": (
              business_naics_6_for_cascade
              if "business_naics_6_for_cascade" in dir() else None
            ),
            "planning_mode": planning_mode,
            "financials_json": financials_json,
          },
          finmo_json=final_finmo_json,
        )
        try:
          rebuilt = _build_finmo_for_gate(final_model_input_json or {})
          if isinstance(rebuilt, dict) and rebuilt:
            final_finmo_json = rebuilt
            next_result["finmo_json"] = final_finmo_json
            next_result["model_input_json"] = final_model_input_json
        except Exception:
          pass
      completion_trace["pre_cash_gate_handler"] = gate_handler_result.to_dict()
      muted = list(gate_handler_result.realism_flags_to_mute or [])
      if muted and isinstance(final_model_input_json, dict):
        existing = final_model_input_json.get("_muted_realism_metrics")
        if isinstance(existing, list):
          merged = list(existing)
          for m in muted:
            if m not in merged:
              merged.append(m)
          final_model_input_json["_muted_realism_metrics"] = merged
        else:
          final_model_input_json["_muted_realism_metrics"] = list(muted)
      _gate_handler_already_ran = True
      gate_violations, gate_scope = _evaluate_gpt_authorable_pre_cash_checks(
        stage_ramp_contract=stage_ramp_contract or {},
        model_input_json=final_model_input_json or {},
        finmo_json=final_finmo_json or {},
        payroll_headcount=payroll_headcount or {},
        financials_json=financials_json or {},
        ops_json=ops_json or {},
      )

    if gate_violations:
      muted_metrics = set(
        (final_model_input_json or {}).get("_muted_realism_metrics") or []
      )
      unmuted = [
        v for v in gate_violations
        if str(v.get("metric_key") or "") not in muted_metrics
      ]
      if unmuted and convergence_test_mode_enabled():
        raise PostIntakePreconditionFailed(
          operation=(
            "pre_cash_gate_gpt_authorable_checks_unfixed_after_handler"
            if _gate_handler_already_ran
            else "pre_cash_gate_gpt_authorable_checks_handler_unavailable"
          ),
          pipeline_stage="post_intake_pre_cash_gpt_authorable_gate",
          expected="GPT-authorable checks pass after handler invocation (or muted post-commit)",
          actual=f"{len(unmuted)} unmuted check violation(s) remain",
          details={
            "violations_sample": unmuted[:10],
            "handler_invoked": bool(_gate_handler_already_ran),
            "muted_metric_count": len(muted_metrics),
          },
        )
  except PostIntakePreconditionFailed:
    raise
  except Exception as gate_exc:
    # Same propagation rule as restoration loop wrapper above.
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      convergence_test_mode_enabled,
    )
    if convergence_test_mode_enabled():
      raise
    completion_trace["pre_cash_gate"] = {
      "status": "failed",
      "error": f"{type(gate_exc).__name__}: {str(gate_exc)[:500]}",
    }

  # 2. Cash pass — Phase 9 Phase F mode-based cash strategy.
  #
  # Replaces the Phase 8 minimal cash strategy (Q1 lump-sum dump) with
  # per-quarter mode-driven funding policy. Reads industry-derived
  # buffer + interest rate + loan term from the unified industry profile
  # (Phase E). Three modes per the doctrine:
  #   preserve_cash      - fund only when buffer breached, prefer non-debt
  #   balanced           - just-in-time funding, modest distributions
  #   shareholder_return - protect buffer first, distribute surplus
  # Mode is read from adaptive_policy.selected_cash_strategy (intake's
  # cash_strategy attribute); defaults to "balanced" if unset.
  try:
    from client_intake_and_finmo.post_intake_cash_strategy import (  # type: ignore
      run_mode_based_cash_strategy,
    )
    from client_intake_and_finmo.post_intake_adaptive_planning import (  # type: ignore
      get_industry_profile,
    )
    from client_intake_and_finmo.finmo_bridge import (  # type: ignore
      build_python_finmo_json,
    )
    from client_intake_and_finmo.post_intake_sequence import (  # type: ignore
      post_intake_sequence_step_scope,
    )
    naics_for_cash = ""
    if isinstance(ops_json, dict):
      naics_for_cash = "".join(
        ch for ch in str(ops_json.get("business_naics_6") or "") if ch.isdigit()
      )
    cash_industry_profile = get_industry_profile(
      naics_6=naics_for_cash or None,
      stage_profile=(adaptive_policy_dict or {}).get("stage_profile", "operational"),
      target_annual_revenue=None,
    ).to_dict()
    # Phase 9 Phase F — sequence-controller scope is required for the
    # cash strategy's apply_exact_lever_updates_to_model_input call and
    # FINMO rebuild. Same scope the Phase 8 minimal cash strategy used.
    with post_intake_sequence_step_scope(
      step_key="post_intake_target_seeking_post_cascade_cash",
      executor_function="phase_9_mode_based_cash_strategy",
    ):
      cash_result = run_mode_based_cash_strategy(
        draft_id=str(draft_id or "").strip(),
        planning_run_id=str(planning_run_id or "").strip(),
        model_input_json=final_model_input_json or {},
        finmo_json=final_finmo_json or {},
        industry_profile=cash_industry_profile,
        adaptive_policy=adaptive_policy_dict,
        business_facts=business_facts,
        ops_json=ops_json,
        financials_json=financials_json,
        planning_mode=planning_mode,
        planning_mode_reason=planning_mode_reason,
        conn=conn,
        horizon=int(horizon or 20),
      )
      if cash_result.applied_updates_count > 0:
        # Rebuild FINMO so cash, interest, debt balance reflect the
        # per-quarter mode-based decisions.
        rebuilt = build_python_finmo_json(
          model_input_json=copy.deepcopy(final_model_input_json or {}),
        )
        if isinstance(rebuilt, dict) and rebuilt:
          final_finmo_json = rebuilt
          next_result["finmo_json"] = final_finmo_json
          next_result["model_input_json"] = final_model_input_json
    completion_trace["cash_pass"] = cash_result.to_dict()
  except Exception as exc:
    # Phase 9 P3.10 STD canonical-source layer 3 hotfix — under
    # CONVERGENCE_TEST_MODE, a cash-pass exception must hard-fail. The
    # legacy silent stamp let the iter 4 Layer 3 regression run all the
    # way through to finalize with stale FINMO state, producing four
    # cascading downstream errors instead of the actual AttributeError.
    # The doctrine work P3.10 already did (28 hard-fails, no silent
    # paths) belongs here too.
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      convergence_test_mode_enabled,
    )
    if convergence_test_mode_enabled():
      raise
    completion_trace["cash_pass"] = {
      "status": "failed",
      "error": f"{type(exc).__name__}: {str(exc)[:500]}",
    }

  # 2. Realism gate — produces the per-metric provenance the acceptance
  # gate looks for (band_source field on each result row). The gate
  # raises RealismBandViolation on the FIRST hard_fail, with the partial
  # results (everything computed up to the violation) attached to
  # exc.results. Catching the violation specifically lets us preserve
  # those results in realism_memo_json so the acceptance gate sees the
  # provenance and the hard_fail count, instead of an empty memo.
  realism_gate_payload: Dict[str, Any] = {}
  try:
    from client_intake_and_finmo.post_intake_realism import (  # type: ignore
      validate_industry_realism_bands,
      RealismBandViolation,
    )
    # Phase 9 Gap C — extract the Phase 3 calibrated targets payload from
    # final_model_input_json["solver_input"][FINMO_OUTPUT_TARGET_KEY] so
    # the validator can resolve phase_3_calibrated bands instead of
    # falling back to wide NAICS baselines for every metric. Without
    # this, the gate's phase_3_calibrated_bands_consulted check always
    # fails (zero calibrated bands) and the cascade never has tighter
    # bands to aim at.
    from client_intake_and_finmo.post_intake_solver import (  # type: ignore
      FINMO_OUTPUT_TARGET_KEY,
    )
    solver_input = (final_model_input_json or {}).get("solver_input")
    realism_solver_input_targets_payload: Optional[Dict[str, Any]] = None
    if isinstance(solver_input, dict):
      candidate = solver_input.get(FINMO_OUTPUT_TARGET_KEY)
      if isinstance(candidate, dict) and candidate:
        realism_solver_input_targets_payload = copy.deepcopy(candidate)
    try:
      realism_gate_payload = validate_industry_realism_bands(
        model_input_json=copy.deepcopy(final_model_input_json or {}),
        finmo_json=copy.deepcopy(final_finmo_json or {}),
        business_naics_6=business_naics_6 or None,
        ops_json=copy.deepcopy(ops_json or {}),
        financials_json=copy.deepcopy(financials_json or {}),
        solver_input_targets_payload=realism_solver_input_targets_payload,
        planning_mode=planning_mode,
      )
      completion_trace["realism_gate"] = {
        "status": "completed",
        "result_count": int(realism_gate_payload.get("result_count") or 0),
        "warning_count": int(realism_gate_payload.get("warning_count") or 0),
        "checked_metric_count": int(realism_gate_payload.get("checked_metric_count") or 0),
      }
    except RealismBandViolation as exc:
      # Hard_fail tripped. Preserve the partial results (each row has
      # band_source provenance) so the acceptance gate can read them
      # and surface the violation in its verdict instead of seeing an
      # empty memo. The realism gate stops at the first hard_fail by
      # design, so this is expected when one fires; the gate's verdict
      # then names which metric+quarter triggered.
      raised_results = list(exc.results or [])
      realism_gate_payload = {
        "results": raised_results,
        "warnings": [],
        "result_count": len(raised_results),
        "warning_count": 0,
        "checked_metric_count": len({
          r.get("metric_key") for r in raised_results
          if isinstance(r, dict) and r.get("metric_key")
        }),
        "halted_on_hard_fail": True,
        "hard_fail_message": str(exc)[:500],
      }
      completion_trace["realism_gate"] = {
        "status": "hard_fail_violation",
        "result_count": len(raised_results),
        "hard_fail_message": str(exc)[:500],
      }
  except Exception as exc:
    completion_trace["realism_gate"] = {
      "status": "failed",
      "error": f"{type(exc).__name__}: {str(exc)[:500]}",
    }

  # Phase 9 P3 — silo'd cascade re-fire on realism hard_fails RETIRED.
  #
  # The Gap B remediation that lived here adapted each realism hard_fail
  # in a silo (one metric -> one family -> primary_levers move toward
  # the band) and could not coordinate across drivers, leaving Q11
  # EBITDA negative for ExpressLogix. The replacement is the target-
  # driven restoration loop in post_intake_target_solver/, wired into
  # _run_post_cascade_completion above the cash strategy step. The new
  # loop iterates 4 solver targets (gross_margin, ebitda_margin,
  # current_assets_minus_cash, current_liabilities_to_revenue) across
  # all 20 quarters at once, allocating per-quarter delta across
  # operating-side drivers proportional to slack-to-bound. Cash
  # strategy still runs after restoration, unchanged.
  completion_trace["realism_remediation"] = {
    "attempted": False,
    "status": "retired_phase_9_p3",
    "reason": "silod_cascade_replaced_by_target_driven_restoration_loop",
  }

  # Build the realism_memo_json that gets persisted with the run.
  try:
    from client_intake_and_finmo.post_intake_resolution_state import (  # type: ignore
      build_realism_memo,
    )
    realism_memo_json = build_realism_memo(
      realism_gate_payload=realism_gate_payload,
    )
  except Exception:
    realism_memo_json = {}

  # 3. Finalize validation — global invariants, balance-sheet finalize,
  # solver_target_assertion. Runs against the post-cash final state.
  # Phase 8: when finalize raises (errors in global_invariants /
  # cash_buffer / revenue_formula_reconcile / etc.), we still want
  # solver_target_assertion captured separately. So call assert_solver_
  # respected_targets directly first (safe; never raises if inputs are
  # well-formed), then run the full finalize as a best-effort pass.
  finalize_result: Dict[str, Any] = {}
  solver_target_assertion: Dict[str, Any] = {
    "checked": False,
    "status": "skipped",
    "reason": "phase_8_solver_target_assertion_not_run",
  }
  try:
    from client_intake_and_finmo.post_intake_solver import (  # type: ignore
      DRIVER_MOVEMENT_ENVELOPE_KEY,
      FINMO_OUTPUT_TARGET_KEY,
      assemble_finmo_output_targets,
      assert_solver_respected_targets,
    )
    business_naics_for_assert = business_naics_6 or ""
    solver_input = (
      (final_model_input_json or {}).get("solver_input")
      if isinstance(final_model_input_json, dict)
      else None
    )
    target_payload_for_assert: Optional[Dict[str, Any]] = None
    envelope_payload_for_assert: Optional[Dict[str, Any]] = None
    if isinstance(solver_input, dict):
      target_payload_for_assert = solver_input.get(FINMO_OUTPUT_TARGET_KEY)
      envelope_payload_for_assert = solver_input.get(DRIVER_MOVEMENT_ENVELOPE_KEY)
    if not isinstance(target_payload_for_assert, dict) or not target_payload_for_assert.get("metrics"):
      target_payload_for_assert = (
        targets_payload_post
        if isinstance(targets_payload_post, dict) and targets_payload_post.get("metrics")
        else assemble_finmo_output_targets(
          business_naics_6=business_naics_for_assert or None,
        )
      )
    if not isinstance(envelope_payload_for_assert, dict):
      envelope_payload_for_assert = envelope_payload_post or {}
    assertion = assert_solver_respected_targets(
      finmo_json=copy.deepcopy(final_finmo_json or {}),
      output_targets_payload=target_payload_for_assert,
      driver_envelope_payload=envelope_payload_for_assert,
    )
    solver_target_assertion = {
      "checked": True,
      "status": assertion.get("status"),
      "checked_metric_count": assertion.get("checked_metric_count"),
      "violations": assertion.get("violations") or [],
      "pinned_drivers": assertion.get("pinned_drivers") or [],
    }
  except Exception as exc:
    solver_target_assertion = {
      "checked": False,
      "status": "skipped",
      "reason": f"phase_8_assertion_call_failed: {type(exc).__name__}: {str(exc)[:200]}",
    }
  completion_trace["solver_target_assertion"] = copy.deepcopy(solver_target_assertion)
  next_result["solver_target_assertion"] = copy.deepcopy(solver_target_assertion)

  # Phase 9 P3.10 Bug A fix — build the debt_schedule snapshot HERE,
  # against post-cash-pass final_model_input_json + final_finmo_json.
  # The pre-cascade build site (deleted) reflected zero DEBT_REPAYMENT
  # values; the cash pass's apply_minimum_debt_schedule populates them
  # in memory; this build site captures the proper amortization. Same
  # SQL UPDATE as the deleted site so workbook export reads the correct
  # post-cash-pass version.
  debt_schedule_payload: Optional[Dict[str, Any]] = None
  try:
    from client_intake_and_finmo.post_intake_debt_schedule import (  # type: ignore
      build_debt_schedule_snapshot,
    )
    debt_schedule_payload = build_debt_schedule_snapshot(
      finmo_payload=copy.deepcopy(final_finmo_json or {}),
      model_input_json=copy.deepcopy(final_model_input_json or {}),
      source_stage="post_intake_finalize_validation",
    )
    if isinstance(debt_schedule_payload, dict):
      debt_schedule_payload["persisted_column"] = "intake_consult_drafts.debt_schedule"
      next_result["debt_schedule"] = debt_schedule_payload
  except Exception as exc:
    diagnostics["debt_schedule_build_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"

  if isinstance(debt_schedule_payload, dict) and debt_schedule_payload and conn is not None:
    try:
      import json as _json
      cur = conn.cursor()
      try:
        cur.execute(
          "UPDATE intake_consult_drafts SET debt_schedule=%s WHERE draft_id=%s",
          (
            _json.dumps(debt_schedule_payload, ensure_ascii=False, default=str),
            str(draft_id or "").strip(),
          ),
        )
        conn.commit()
      finally:
        try:
          cur.close()
        except Exception:
          pass
    except Exception as exc:
      diagnostics["debt_schedule_persist_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"

  # Phase 9 P3.10 iter 12 Piece A — direct SQL persist of pre-finalize
  # state with read-back verification + hard-fail under test mode.
  #
  # Pre-fix, the de3de02 persist used `_persist_unified_convergence_state`
  # which routes through a deep abstraction (planning_run_payload,
  # checkpoint rows, repair_guidance, etc.). The SQL UPDATE that hits
  # `intake_consult_drafts.model_input_json` and `finmo_json` happens
  # via `append_messages` — but only when the heavy-checkpoint
  # store policy permits. Iter 12's failure snapshot showed the
  # pre-finalize state did NOT land, leaving us blind to what
  # finalize actually validated.
  #
  # This direct UPDATE bypasses the abstraction. It writes the two
  # JSON columns the failure snapshot reader (_persist_failed_system_run_snapshot
  # at post_intake_state/runner.py:1119-1120) actually consults,
  # then SELECTS them back and asserts the marker round-trips.
  #
  # Embeds a `_pre_finalize_persist_marker` field inside both
  # model_input and finmo so post-mortem readers can verify which
  # state generation they're looking at. Marker includes a tag,
  # the orchestrator's stage label, and a content hash sample so
  # we can tell at a glance whether the pre-finalize snapshot
  # landed or whether the failure snapshot re-wrote stale data.
  try:
    import json as _json_for_pre_finalize_persist
    import time as _time_for_pre_finalize_persist
    _pre_finalize_marker = {
      "tag": "pre_finalize_persist",
      "stage": "pre_finalize_validation",
      "wrote_at_epoch_seconds": int(_time_for_pre_finalize_persist.time()),
      "draft_id": str(draft_id or "").strip(),
      "planning_run_id": str(planning_run_id or "").strip(),
      "q1_ending_cash_sample": int(round(float(_safe_float(
        ((final_finmo_json or {}).get("quarter_rows") or [{}])[0].get("ending_cash")
        if isinstance((final_finmo_json or {}).get("quarter_rows"), list)
        and len((final_finmo_json or {}).get("quarter_rows")) > 0
        else 0
      ) or 0.0))),
    }
    # Embed the marker without removing existing keys (deep copies first).
    _model_input_to_persist = copy.deepcopy(final_model_input_json or {})
    _finmo_to_persist = copy.deepcopy(final_finmo_json or {})
    _model_input_to_persist["_pre_finalize_persist_marker"] = copy.deepcopy(_pre_finalize_marker)
    _finmo_to_persist["_pre_finalize_persist_marker"] = copy.deepcopy(_pre_finalize_marker)
    _draft_id_clean = str(draft_id or "").strip()
    if not _draft_id_clean:
      raise RuntimeError("pre_finalize_persist_missing_draft_id")
    _cur = conn.cursor()
    try:
      _cur.execute(
        "UPDATE intake_consult_drafts SET model_input_json=%s, finmo_json=%s WHERE draft_id=%s",
        (
          _json_for_pre_finalize_persist.dumps(_model_input_to_persist, ensure_ascii=False, default=str),
          _json_for_pre_finalize_persist.dumps(_finmo_to_persist, ensure_ascii=False, default=str),
          _draft_id_clean,
        ),
      )
      conn.commit()
      # Read-back verification: SELECT both columns and confirm the
      # marker round-trips. If the UPDATE silently no-op'd (wrong
      # draft_id, wrong column, transactional issue), this catches it.
      _cur.execute(
        "SELECT model_input_json, finmo_json FROM intake_consult_drafts WHERE draft_id=%s",
        (_draft_id_clean,),
      )
      _row = _cur.fetchone()
      if not _row:
        raise RuntimeError("pre_finalize_persist_readback_no_row")
      _readback_model_input = _json_for_pre_finalize_persist.loads(_row[0]) if _row[0] else {}
      _readback_finmo = _json_for_pre_finalize_persist.loads(_row[1]) if _row[1] else {}
      _readback_mi_marker = (_readback_model_input or {}).get("_pre_finalize_persist_marker") or {}
      _readback_fm_marker = (_readback_finmo or {}).get("_pre_finalize_persist_marker") or {}
      if _readback_mi_marker.get("tag") != "pre_finalize_persist":
        raise RuntimeError(
          f"pre_finalize_persist_readback_marker_missing_in_model_input: "
          f"got_tag={_readback_mi_marker.get('tag')!r}"
        )
      if _readback_fm_marker.get("tag") != "pre_finalize_persist":
        raise RuntimeError(
          f"pre_finalize_persist_readback_marker_missing_in_finmo: "
          f"got_tag={_readback_fm_marker.get('tag')!r}"
        )
      if int(_readback_mi_marker.get("wrote_at_epoch_seconds") or 0) != int(_pre_finalize_marker["wrote_at_epoch_seconds"]):
        raise RuntimeError(
          f"pre_finalize_persist_readback_epoch_mismatch: "
          f"wrote={_pre_finalize_marker['wrote_at_epoch_seconds']} "
          f"read={_readback_mi_marker.get('wrote_at_epoch_seconds')}"
        )
    finally:
      try:
        _cur.close()
      except Exception:
        pass
    completion_trace["persist_pre_finalize_state"] = {
      "status": "completed",
      "writer": "direct_sql_update_intake_consult_drafts",
      "marker_tag": "pre_finalize_persist",
      "marker_epoch": int(_pre_finalize_marker["wrote_at_epoch_seconds"]),
      "q1_ending_cash_sample": int(_pre_finalize_marker["q1_ending_cash_sample"]),
      "readback_verified": True,
    }
  except Exception as _pre_finalize_persist_exc:
    # Phase 9 P3.10 discipline: under CONVERGENCE_TEST_MODE, a failed
    # diagnostic persist is a hard fail. Without visibility into what
    # finalize sees, every downstream failure is opaque.
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      convergence_test_mode_enabled,
    )
    completion_trace["persist_pre_finalize_state"] = {
      "status": "failed",
      "writer": "direct_sql_update_intake_consult_drafts",
      "error": f"{type(_pre_finalize_persist_exc).__name__}: {str(_pre_finalize_persist_exc)[:500]}",
    }
    if convergence_test_mode_enabled():
      raise

  try:
    from client_intake_and_finmo.post_intake_runtime_validation.finalize_post_intake import (  # type: ignore
      run_finalize_post_intake_validation,
    )
    finalize_result = run_finalize_post_intake_validation(
      draft_id=str(draft_id or "").strip(),
      planning_run_id=str(planning_run_id or "").strip(),
      stage_ramp_contract=copy.deepcopy(stage_ramp_contract or {}),
      model_input_json=copy.deepcopy(final_model_input_json or {}),
      finmo_json=copy.deepcopy(final_finmo_json or {}),
      payroll_headcount=copy.deepcopy(payroll_headcount or {}),
      debt_schedule=copy.deepcopy(debt_schedule_payload or {}),
      financials_json=copy.deepcopy(financials_json or {}),
      ops_json=copy.deepcopy(ops_json or {}),
      cash_strategy_second_pass_result={"post_intake_finalize_validation": {}},
    )
    completion_trace["finalize_validation"] = {
      "status": str(finalize_result.get("status") or "completed"),
      "solver_target_assertion_checked": bool(solver_target_assertion.get("checked")),
    }
    # Prefer the finalize call's own solver_target_assertion if it
    # succeeded — it has the same shape but with the validation flow's
    # context.
    if isinstance(finalize_result.get("solver_target_assertion"), dict):
      stax = finalize_result["solver_target_assertion"]
      if stax.get("checked"):
        solver_target_assertion = stax
        next_result["solver_target_assertion"] = copy.deepcopy(stax)
  except Exception as exc:
    # Phase 9 P3.10 Commit 2 — the legacy Phase-8 finalize warning
    # downgrade is removed. Under test mode the finalize fail-fast
    # (which IS the existing fail-fast layer) must not be undone at
    # the orchestrator level. The legacy Phase 8 note explained why
    # this downgrade existed; with the acceptance gate in place,
    # downgrading produces exactly the misleading 13/16 outcomes the
    # P3.10 overhaul is fixing.
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      convergence_test_mode_enabled,
    )
    if convergence_test_mode_enabled():
      raise
    completion_trace["finalize_validation"] = {
      "status": "failed",
      "error": f"{type(exc).__name__}: {str(exc)[:500]}",
      "note": (
        "Production-mode legacy path: finalize exception captured but "
        "not raised. Test mode (CONVERGENCE_TEST_MODE=true) propagates "
        "the exception to the API boundary."
      ),
    }
    finalize_result = {"solver_target_assertion": solver_target_assertion}

  # 4. Persist with stage=post_intake_finalize_validation_completed,
  # status=completed. Without this, planning_runs.current_stage stays at
  # convergence_running and the acceptance gate's stage_reached_finalize
  # check fails.
  try:
    from client_intake_and_finmo.post_intake_state.runner import (  # type: ignore
      _persist_unified_convergence_state,
    )
    from client_intake_and_finmo.post_intake_resolution_state import (  # type: ignore
      build_controller_resolution_state,
      build_resolution_summary,
    )
    # Ensure solver_target_assertion is in the persisted blob even if
    # finalize raised — the gate's _solver_target_assertion accessor
    # walks cash_strategy_second_pass_result.post_intake_finalize_validation.solver_target_assertion.
    finalize_blob = copy.deepcopy(finalize_result) if isinstance(finalize_result, dict) else {}
    if not isinstance(finalize_blob.get("solver_target_assertion"), dict) or not finalize_blob["solver_target_assertion"].get("checked"):
      finalize_blob["solver_target_assertion"] = copy.deepcopy(solver_target_assertion)
    cash_strategy_second_pass_result = {
      "post_intake_finalize_validation": finalize_blob,
    }
    _persist_unified_convergence_state(
      conn=conn,
      draft_id=str(draft_id or "").strip(),
      stage="post_intake_finalize_validation_completed",
      status="completed",
      planning_context_summary_json=copy.deepcopy(planning_context_summary_json or {}),
      controller_resolution_state=build_controller_resolution_state(
        realism_gate_payload=realism_gate_payload,
        cascade_diagnostics=cascade_diagnostics,
      ),
      resolution_summary=build_resolution_summary(
        realism_gate_payload=realism_gate_payload,
        cascade_diagnostics=cascade_diagnostics,
      ),
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      prompt_file="",
      grid_application_summary=copy.deepcopy(grid_application_summary or {}),
      realism_memo_before_resolution={},
      realism_memo_json=copy.deepcopy(realism_memo_json),
      # Phase 9 Phase C1: populate unified_convergence_context so the
      # workbook reader (data.py:146-160 fallback chain) finds the
      # stage_ramp_contract instead of returning zeros. Phase 8 wrote
      # `{}` here, orphaning the contract.
      unified_convergence_context=_build_minimal_convergence_context(
        stage_ramp_contract=stage_ramp_contract,
        adaptive_policy_dict=adaptive_policy_dict,
        planning_context_summary_json=planning_context_summary_json,
      ),
      unified_convergence_decision={},
      unified_convergence_plan={},
      unified_convergence_result={},
      unified_convergence_iterations=[],
      unified_convergence_cycle_count=0,
      model_input_json=copy.deepcopy(final_model_input_json or {}),
      finmo_json=copy.deepcopy(final_finmo_json or {}),
      cash_strategy_review_context={},
      cash_strategy_review_decision={},
      cash_strategy_second_pass_plan={},
      cash_strategy_second_pass_result=cash_strategy_second_pass_result,
      cash_strategy_effect_summary={},
    )
    completion_trace["persist_finalize_stage"] = {"status": "completed"}
  except Exception as exc:
    # Phase 9 P3.10 Commit 4 — persist_finalize_stage failure now
    # raises under test mode. Audit #41: SQL UPDATE failure here
    # leaves the draft stuck at convergence_running, the acceptance
    # gate's stage_reached_finalize check fails, but the run continues
    # and the operator sees a confusing acceptance failure instead of
    # the persistence root cause.
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      convergence_test_mode_enabled,
    )
    if convergence_test_mode_enabled():
      raise
    completion_trace["persist_finalize_stage"] = {
      "status": "failed",
      "error": f"{type(exc).__name__}: {str(exc)[:500]}",
    }

  diagnostics["post_cascade_completion"] = completion_trace
  next_result["post_cascade_completion"] = completion_trace
  next_result["realism_memo_json"] = realism_memo_json
  next_result["target_seeking_diagnostics"] = diagnostics

  # Phase 8: also persist the post_cascade_completion trace directly
  # into the draft's planning_run_json column so future diagnostic
  # queries can read it without round-tripping through the orchestrator
  # return value. _persist_unified_convergence_state above writes a
  # planning_run_json snapshot but doesn't have a slot for arbitrary
  # diagnostic blobs from this layer; this small UPDATE merges the
  # trace + realism_memo summary into the persisted blob.
  if conn is not None:
    try:
      import json as _json
      cur = conn.cursor(dictionary=True)
      try:
        cur.execute(
          "SELECT planning_run_json FROM intake_consult_drafts WHERE draft_id = %s",
          (str(draft_id or "").strip(),),
        )
        row = cur.fetchone()
      finally:
        try:
          cur.close()
        except Exception:
          pass
      existing = {}
      if row and isinstance(row.get("planning_run_json"), (str, bytes, bytearray)):
        try:
          raw = row["planning_run_json"]
          if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
          existing = _json.loads(raw) if raw else {}
        except Exception:
          existing = {}
      if not isinstance(existing, dict):
        existing = {}
      existing["post_cascade_completion"] = copy.deepcopy(completion_trace)
      tsd = existing.get("target_seeking_diagnostics")
      tsd_dict = tsd if isinstance(tsd, dict) else {}
      tsd_dict["post_cascade_completion"] = copy.deepcopy(completion_trace)
      existing["target_seeking_diagnostics"] = tsd_dict
      # Phase 9 Phase C1: write stage_ramp_contract and adaptive_policy at
      # the top level of planning_run_json so the workbook reader's first
      # fallback path (data.py:149) finds the contract directly.
      if isinstance(stage_ramp_contract, dict) and stage_ramp_contract:
        existing["stage_ramp_contract"] = copy.deepcopy(stage_ramp_contract)
      if isinstance(adaptive_policy_dict, dict) and adaptive_policy_dict:
        existing["adaptive_policy"] = copy.deepcopy(adaptive_policy_dict)
      cur = conn.cursor()
      try:
        cur.execute(
          "UPDATE intake_consult_drafts SET planning_run_json=%s WHERE draft_id=%s",
          (
            _json.dumps(existing, ensure_ascii=False, default=str),
            str(draft_id or "").strip(),
          ),
        )
        conn.commit()
      finally:
        try:
          cur.close()
        except Exception:
          pass
    except Exception as exc:
      diagnostics["post_cascade_completion_persist_error"] = (
        f"{type(exc).__name__}: {str(exc)[:200]}"
      )

  return next_result
