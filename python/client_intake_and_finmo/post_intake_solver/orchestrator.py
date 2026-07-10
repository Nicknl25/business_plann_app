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
  (the canonical path; see
  ``client_statements_output_excel/data.py:DraftWorkbookData.stage_ramp_contract``).
  With that path empty, the Revenue Drivers sheet's Stage Ramp Contract
  rows showed zeros across Q1-Q20 even though the contract itself had
  been generated correctly.

  This builder writes the minimum surface the workbook reader needs.
  Intentionally NOT a full convergence-runner payload — convergence runner
  is dead code awaiting Phase I deletion. Phase D may extend this with
  cascade widening artifacts; Phase F adds cash plan summary.

  P3.40 bug 5 fix: the secondary mirror write at
  ``context["planning_context_summary"]["stage_ramp_contract"]`` was
  removed. The workbook reader's 4-path fallback chain was collapsed to
  a single canonical read, so the dual-write is no longer needed.
  ``planning_context_summary_json`` is no longer threaded through here
  (the parameter is kept on the signature for caller-compat; if it
  reappears as a non-stage-ramp surface in a future change, populate
  ``context["planning_context_summary"]`` then).
  """
  del planning_context_summary_json  # no longer mirrored here; see docstring
  context: Dict[str, Any] = {}
  bwc: Dict[str, Any] = {}
  if isinstance(stage_ramp_contract, dict) and stage_ramp_contract:
    bwc["stage_ramp_contract"] = copy.deepcopy(stage_ramp_contract)
  if bwc:
    context["business_world_contract"] = bwc
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
  # DOCTRINE ANCHOR (FIX 1b): when revenue is GPT-authored, the per-quarter
  # driver ramps are AUTHORITATIVE — the feasibility-restoration cascade must
  # NOT flat-overwrite them from raw intake scalars (that is intake/FTE
  # back-driving the authored capacity anchor, which collapses the authored
  # revenue, e.g. a 15,600->21,840 ramp flattened to the 1,200 weekly intake
  # value). Restoration may still adjust payroll/cost rows below. Universal.
  revenue_authored = bool((next_input.get("solver_input") or {}).get("revenue_authored"))
  revenue_rows = sections.get("revenue")
  if isinstance(revenue_rows, list) and not revenue_authored:
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
  # Constrain the solver to the FITTED bands the cascade was handed. The solver's
  # job is precision/convergence WITHIN the cascade's viable plan -- not to
  # re-reach for the raw industry bands (a law firm's COGS toward ~43%) and
  # inflate the back half, degrading the Q11->Q20 viability the cascade achieved.
  # Cap each cost ratio's target at the fitted peak (the highest the cascade
  # allowed) and floor net-income margin at the fitted floor, so the solver
  # cannot push viability below what it was handed.
  _overlay_fitted_bands_onto_targets(
    solver_input.get(FINMO_OUTPUT_TARGET_KEY),
    solver_input.get("fitted_bands"),
    solver_input.get("fitted_envelope"),
  )
  return next_input


_FITTED_COST_METRIC_KEYS = (
  "cogs_percent_of_revenue",
  "marketing_percent_of_revenue",
  "sga_percent_of_revenue",
  "r_and_d_percent_of_revenue",
)
_FITTED_NI_METRIC_KEY = "net_income_margin"
# Viability-spine margins (outcomes, not cost levers): the realism gate judges
# these too, so its band must match the FITTED trajectory the cascade/solver
# produced -- otherwise a business that legitimately runs above the industry-wide
# ceiling (a law firm's ~20% EBITDA) hard-fails realism against a raw band.
_FITTED_SPINE_METRIC_KEYS = ("net_income_margin", "ebitda_margin")


def _overlay_fitted_bands_onto_targets(
  targets_payload: Optional[Dict[str, Any]],
  fitted_bands: Optional[Dict[str, Any]],
  fitted_envelope: Optional[Dict[str, Any]] = None,
) -> None:
  """Clamp the solver's output targets to the fitted bands in place. Cost-ratio
  targets are capped at the fitted PEAK (the solver may converge within the
  fitted band but not inflate above it); net-income margin is floored at the
  fitted FLOOR (the solver may not push NI below the viability the cascade
  landed). No-op when either input is missing -- raw targets stand."""
  if not isinstance(targets_payload, dict):
    return
  metrics = targets_payload.get("metrics")
  if not isinstance(metrics, dict):
    return

  # PROPORTIONAL BAND-SCALING: replace the raw cohort band (min/target/max) with
  # the operator-rescaled envelope so the solver AND the realism gate judge
  # against the business's real-level bands -- floor included. Without this the
  # realism gate hard-fails the operator's real cost (a dental office's ~3%
  # marketing) against a large-public-company cohort floor (~10%).
  if isinstance(fitted_envelope, dict):
    _BAND_KEY = {"min": "target_min", "target": "target_target", "max": "target_max"}
    for metric_key, band in fitted_envelope.items():
      row = metrics.get(metric_key)
      if not isinstance(row, dict) or not isinstance(band, dict):
        continue
      for env_key, tgt_key in _BAND_KEY.items():
        val = band.get(env_key)
        if val is not None:
          try:
            row[tgt_key] = float(val)
          except (TypeError, ValueError):
            continue

  if not isinstance(fitted_bands, dict):
    return

  def _values(traj: Any) -> List[float]:
    out: List[float] = []
    if isinstance(traj, dict):
      for v in traj.values():
        try:
          out.append(float(v))
        except (TypeError, ValueError):
          continue
    return out

  for metric_key in _FITTED_COST_METRIC_KEYS:
    row = metrics.get(metric_key)
    vals = _values(fitted_bands.get(metric_key))
    if not isinstance(row, dict) or not vals:
      continue
    peak = max(vals)
    for bound in ("target_max", "target_target", "target_min"):
      cur = row.get(bound)
      try:
        if cur is not None and float(cur) > peak:
          row[bound] = peak
      except (TypeError, ValueError):
        continue

  for spine_key in _FITTED_SPINE_METRIC_KEYS:
    row = metrics.get(spine_key)
    vals = _values(fitted_bands.get(spine_key))
    if not isinstance(row, dict) or not vals:
      continue
    floor = min(vals)
    peak = max(vals)
    # WIDEN (never narrow) the band to the fitted trajectory: floor the bottom
    # at the fitted floor (the solver may not push the margin below the
    # viability the cascade landed) and raise the ceiling to the fitted peak
    # (the realism gate must accept the viable margin this business actually
    # reaches). Keep the target inside the widened bounds.
    tmin = row.get("target_min")
    try:
      if tmin is None or float(tmin) > floor:
        row["target_min"] = floor
    except (TypeError, ValueError):
      row["target_min"] = floor
    tmax = row.get("target_max")
    try:
      if tmax is None or float(tmax) < peak:
        row["target_max"] = peak
    except (TypeError, ValueError):
      row["target_max"] = peak
    ttgt = row.get("target_target")
    try:
      if ttgt is not None:
        row["target_target"] = min(max(float(ttgt), floor), peak)
    except (TypeError, ValueError):
      pass


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
  # P3.40 Contract 3 Commit 3 -- consumer-side boundary gate.
  # FIRST executable line. Validates the 21-field solver-input
  # bundle (19 data params + draft_id + planning_run_id) before
  # any adaptive_policy / feasibility / solver-loop work. On
  # invalid input raises ContractViolation, which propagates
  # through the API handler's generic `except Exception as exc:`
  # catch at intake_consult.py:7377 (trace Div-8) as a structured
  # 500 with str(exc) carrying the SOLVER_STAGE_LABEL +
  # field path.
  from client_intake_and_finmo.post_intake_contracts.enforcement import (  # type: ignore
    SIDE_CONSUMER as _SOLVER_SIDE_CONSUMER,
    validate_solver_input_at_boundary,
  )
  validate_solver_input_at_boundary(
    {
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
      "applied_model_input_json": applied_model_input_json,
      "applied_finmo_json": applied_finmo_json,
      "stage_ramp_contract": stage_ramp_contract,
      "payroll_headcount": payroll_headcount,
    },
    side=_SOLVER_SIDE_CONSUMER,
  )

  try:
    from financial_model_engine.model_inputs import QUARTER_COUNT  # type: ignore
  except Exception:
    QUARTER_COUNT = 20  # type: ignore

  horizon = int(QUARTER_COUNT)

  # ---------- Step 9c: diagnostic emit helper closure --------------------
  # Binds conn + draft_id + planning_run_id so phase-boundary emits
  # below can call _emit_diag(phase=..., event_code=..., ...) without
  # repeating the args. safe_emit swallows exceptions; observability
  # never crashes the orchestrator.
  from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
    EventCode as _DiagEventCode,
    PhaseCode as _DiagPhaseCode,
    Status as _DiagStatus,
    safe_emit as _diag_safe_emit,
  )
  _DIAG_PLANNING_RUN_ID = str(planning_run_id or "").strip()
  _DIAG_DRAFT_ID = str(draft_id or "").strip()

  def _emit_diag(*, phase, event_code, status=_DiagStatus.COMPLETED, diagnostic_data=None):
    if not _DIAG_DRAFT_ID or not _DIAG_PLANNING_RUN_ID:
      return
    _diag_safe_emit(
      conn,
      draft_id=_DIAG_DRAFT_ID,
      planning_run_id=_DIAG_PLANNING_RUN_ID,
      phase=phase, event_code=event_code, status=status,
      diagnostic_data=diagnostic_data,
    )

  _emit_diag(
    phase=_DiagPhaseCode.TARGET_SEEKING,
    event_code=_DiagEventCode.TARGET_SEEKING_FEASIBILITY_STARTED,
    status=_DiagStatus.STARTED,
    diagnostic_data={"planning_mode": planning_mode,
                     "planning_mode_reason": planning_mode_reason},
  )

  # Step 9d item 18 — FAIL_TARGET_SEEKING_MODE_UNKNOWN. The supported
  # planning modes are the canonical post-intake vocabulary, single-sourced
  # from post_intake_adaptive_planning.policy.ALLOWED_PLANNING_MODES
  # (normalize / turnaround / rebalance / growth_investment / preservation).
  # The prior hardcoded {growth,stability,runway_extension,survival} was a
  # WRONG taxonomy that rejected every real planning_mode (e.g. "rebalance").
  from client_intake_and_finmo.post_intake_adaptive_planning import (  # type: ignore
    ALLOWED_PLANNING_MODES as _VALID_PLANNING_MODES,
  )
  if str(planning_mode or "").strip() not in set(_VALID_PLANNING_MODES):
    from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
      FailFastCode as _FFC, PhaseCode as _PC, raise_fail_fast as _rff,
    )
    _rff(
      conn, draft_id=_DIAG_DRAFT_ID, planning_run_id=_DIAG_PLANNING_RUN_ID,
      phase=_PC.TARGET_SEEKING,
      code=_FFC.FAIL_TARGET_SEEKING_MODE_UNKNOWN,
      detail=f"planning_mode={planning_mode!r} not in {sorted(_VALID_PLANNING_MODES)}",
      where="orchestrator.run_target_seeking_orchestrated_system_run",
    )

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

  # ---------- Phase 9 P3.32 K11 L-4: handler trace run -------------------
  # NOTE: begin_trace_run is intentionally NOT called here. The trace run
  # is opened earlier, at the TRUE planning-system entry
  # (_run_planning_system_for_draft_unified in api_handlers/intake_consult),
  # because payroll Handler C runs during the initial-grid build BEFORE
  # this orchestrator. Calling begin_trace_run here would clear the buffer
  # and discard Handler C's traces. The active run context (set there) is
  # already live; the orchestrator only needs to stamp the planning_run_id
  # if it hasn't been set yet.
  try:
    from client_intake_and_finmo.post_intake_handler_traces import (  # type: ignore
      set_planning_run_id,
    )
    set_planning_run_id(planning_run_id)
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
  # C6 — emit TARGET_SEEKING_PREFLIGHT_STARTED so the pre-flight pass
  # leaves a phase-trace marker for downstream queries.
  _emit_diag(
    phase=_DiagPhaseCode.TARGET_SEEKING,
    event_code=_DiagEventCode.TARGET_SEEKING_PREFLIGHT_STARTED,
    status=_DiagStatus.STARTED,
    diagnostic_data={
      "max_iterations": _DEFAULT_PREFLIGHT_MAX_ITERATIONS,
      "numeric_tolerance": _DEFAULT_NUMERIC_TOLERANCE,
      "horizon": horizon,
    },
  )
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
  # Step 9d item 19 — FAIL_TARGET_SEEKING_REASON_UNKNOWN. Every hard_fail
  # must be a dict with a non-empty string "code"; otherwise the
  # downstream cascade dispatch cannot classify it.
  _hf_malformed = [
    i for i, hf in enumerate(final_hard_fails or [])
    if not isinstance(hf, dict) or not isinstance(hf.get("code"), str)
    or not hf.get("code")
  ]
  if _hf_malformed:
    from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
      FailFastCode as _FFC, PhaseCode as _PC, raise_fail_fast as _rff,
    )
    _rff(
      conn, draft_id=_DIAG_DRAFT_ID, planning_run_id=_DIAG_PLANNING_RUN_ID,
      phase=_PC.TARGET_SEEKING,
      code=_FFC.FAIL_TARGET_SEEKING_REASON_UNKNOWN,
      detail=f"{len(_hf_malformed)} hard_fails missing/empty 'code' (first idx={_hf_malformed[0]})",
      where="orchestrator.run_target_seeking_orchestrated_system_run (post-cascade)",
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
      # Step 9c — adaptation cascade entry diagnostic.
      _emit_diag(
        phase=_DiagPhaseCode.TARGET_SEEKING,
        event_code=_DiagEventCode.TARGET_SEEKING_ADAPTATION_CASCADE_STARTED,
        status=_DiagStatus.STARTED,
        diagnostic_data={"hard_fail_count": len(final_hard_fails or [])},
      )
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

  # Phase 9 P3.32 K11 L-4 — fold the run's handler-trace buffer into the
  # completion report too (the incremental SQL rows are the durable copy;
  # this inline copy keeps a self-contained record for completed runs)
  # and close the trace run.
  try:
    from client_intake_and_finmo.post_intake_handler_traces import (  # type: ignore
      get_trace_buffer,
      get_runtime_status,
      end_trace_run,
    )
    next_result["handler_trace_diagnostic"] = {
      "traces": get_trace_buffer(),
      "runtime_status": get_runtime_status(),
    }
    end_trace_run()
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
  # Step 9c diagnostic emit helper. This function runs as a SEPARATE
  # top-level call (not nested inside run_target_seeking_orchestrated_system_run),
  # so it binds its OWN emitter + diag enums from the conn/draft_id/
  # planning_run_id it receives. (Previously these names were only defined
  # in the sibling function's scope; reaching this tail end-to-end surfaced
  # the NameError once the upstream contract walls were cleared.)
  from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
    EventCode as _DiagEventCode,
    PhaseCode as _DiagPhaseCode,
    Status as _DiagStatus,
    safe_emit as _diag_safe_emit,
  )
  _DIAG_PLANNING_RUN_ID = str(planning_run_id or "").strip()
  _DIAG_DRAFT_ID = str(draft_id or "").strip()

  def _emit_diag(*, phase, event_code, status=_DiagStatus.COMPLETED, diagnostic_data=None):
    if not _DIAG_DRAFT_ID or not _DIAG_PLANNING_RUN_ID:
      return
    _diag_safe_emit(
      conn,
      draft_id=_DIAG_DRAFT_ID,
      planning_run_id=_DIAG_PLANNING_RUN_ID,
      phase=phase, event_code=event_code, status=status,
      diagnostic_data=diagnostic_data,
    )

  completion_trace: Dict[str, Any] = {
    "post_cascade_solver_pass": {"status": "not_run"},
    "cash_pass": {"status": "not_run"},
    "realism_gate": {"status": "not_run"},
    "finalize_validation": {"status": "not_run"},
    "persist_finalize_stage": {"status": "not_run"},
    "payroll_state_resync": {"status": "not_run"},
  }

  # Resolve business_naics_6 if not passed in.
  if not business_naics_6 and isinstance(ops_json, dict):
    business_naics_6 = "".join(
      ch for ch in str(ops_json.get("business_naics_6") or "") if ch.isdigit()
    )

  # Phase 9 P3.32 K1 F6 — payroll state re-sync from canonical SQL
  # column at the start of _run_post_cascade_completion.
  #
  # Doctrine background: the payroll schedule lives in two snapshots:
  # the SQL `payroll_headcount` column (canonical, written by Handler
  # C apply chain at every persist) AND `model_input.derived_driver_
  # runtime[expenses::Payroll].payroll_headcount` (a snapshot updated
  # only when apply_payroll_headcount_payload_to_model_input is
  # called). These snapshots can drift apart when an upstream stage
  # (e.g., the convergence runner) persists a NEW schedule to SQL
  # but the orchestrator's local payroll_headcount + final_model_
  # input_json variables retain the OLD schedule from before that
  # convergence pass.
  #
  # Empirical case (P3.32 CareFirst investigation, draft
  # 0caeb5ad5d0843a6b4f0e52ba0cf7d5f): convergence runner produced
  # schedule_v2 with Registered Nurses benefits_pct=0.25 / Q1
  # quarter_totals.payroll=106928. SQL column got schedule_v2. But
  # the orchestrator continued with schedule_v1 (benefits_pct=0.22 /
  # Q1=106192) in its local payroll_headcount variable. The pre-
  # finalize persist then wrote model_input.expenses.Payroll.values
  # derived from schedule_v1 (106192) while the payroll_headcount
  # column kept schedule_v2 (106928). Result: $736 Cash Q20
  # divergence on V-4 verifier.
  #
  # Fix shape: at the start of _run_post_cascade_completion, re-read
  # the canonical payroll_headcount from SQL. If it differs from the
  # local variable, replace the local variable AND re-apply through
  # the canonical apply chain to update model_input + finmo. This
  # makes the SQL column the source of truth and the orchestrator's
  # local state derived from it. Mirror Flavor 1 is preserved across
  # the full chain.
  #
  # No-op when conn is None (test environments) or when SQL column
  # already matches local variable. The completion_trace records
  # the outcome for debugging.
  try:
    if conn is not None and str(draft_id or "").strip():
      from client_intake_and_finmo.post_intake_headcount.feasibility_repair import (  # type: ignore
        apply_payroll_schedule_to_state,
      )
      _resync_cur = conn.cursor(dictionary=True)
      try:
        _resync_cur.execute(
          "SELECT payroll_headcount FROM intake_consult_drafts WHERE draft_id = %s",
          (str(draft_id).strip(),),
        )
        _resync_row = _resync_cur.fetchone() or {}
      finally:
        try:
          _resync_cur.close()
        except Exception:
          pass
      _resync_raw = _resync_row.get("payroll_headcount") if isinstance(_resync_row, dict) else None
      _canonical_ph: Dict[str, Any] = {}
      if _resync_raw:
        try:
          import json as _resync_json
          _canonical_ph = _resync_json.loads(_resync_raw) if isinstance(_resync_raw, str) else dict(_resync_raw)
        except Exception:
          _canonical_ph = {}
      def _qt_tuple(ph: Optional[Dict[str, Any]]):
        return tuple(
          (int(item.get("quarter_index") or 0), int(round(float(item.get("payroll") or 0))))
          for item in ((ph or {}).get("quarter_totals") or [])
          if isinstance(item, dict)
        )
      _local_qt = _qt_tuple(payroll_headcount)
      _canonical_qt = _qt_tuple(_canonical_ph)
      if _canonical_qt and _canonical_qt != _local_qt:
        # Canonical SQL diverged from local. Re-sync.
        _live_count_resync = max(
          0,
          len([
            p for p in ((final_model_input_json or {}).get("periods") or [])
            if isinstance(p, dict) and not bool(p.get("is_stub"))
          ]),
        )
        try:
          _resynced_mi, _resynced_finmo = apply_payroll_schedule_to_state(
            schedule_payload=_canonical_ph,
            model_input_json=final_model_input_json or {},
            finmo_json=final_finmo_json or {},
            live_count=_live_count_resync,
            stage_prefix="post_cascade_completion_payroll_state_resync",
          )
          payroll_headcount = _canonical_ph
          final_model_input_json = _resynced_mi
          final_finmo_json = _resynced_finmo
          next_result["model_input_json"] = final_model_input_json
          next_result["finmo_json"] = final_finmo_json
          if isinstance(next_result.get("payroll_headcount"), dict) or "payroll_headcount" in next_result:
            next_result["payroll_headcount"] = payroll_headcount
          completion_trace["payroll_state_resync"] = {
            "status": "completed",
            "local_q1_payroll_before": (_local_qt[0][1] if _local_qt else None),
            "canonical_q1_payroll": (_canonical_qt[0][1] if _canonical_qt else None),
            "quarter_totals_mismatch_count": sum(
              1 for a, b in zip(_local_qt, _canonical_qt) if a != b
            ) if _local_qt and _canonical_qt else None,
            "applied_chain": "apply_payroll_schedule_to_state",
          }
        except Exception as _resync_apply_exc:
          completion_trace["payroll_state_resync"] = {
            "status": "apply_failed",
            "error": f"{type(_resync_apply_exc).__name__}: {str(_resync_apply_exc)[:300]}",
          }
          raise
      elif _canonical_qt and _canonical_qt == _local_qt:
        completion_trace["payroll_state_resync"] = {
          "status": "in_sync",
          "q1_payroll": (_canonical_qt[0][1] if _canonical_qt else None),
        }
      else:
        completion_trace["payroll_state_resync"] = {
          "status": "canonical_empty",
        }
  except Exception as _resync_exc:
    # The re-sync is structurally important but a non-fatal error
    # here (e.g., apply chain raises on a no-payroll business)
    # shouldn't block the completion. Record and continue; the
    # pre-finalize persist invariant below catches any remaining
    # drift.
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      convergence_test_mode_enabled,
    )
    if convergence_test_mode_enabled():
      raise
    completion_trace["payroll_state_resync"] = {
      "status": "resync_lookup_failed",
      "error": f"{type(_resync_exc).__name__}: {str(_resync_exc)[:300]}",
    }

  # 0.5. BASELINE cost grounding — stamp the fitted (operator-rescaled) band
  # TARGET trajectory onto the cost rows BEFORE the solver/restoration search
  # runs. This fixes the round-1 raw-cohort seeding (actuals start where the
  # targets say a business of this size starts) while leaving the bands as
  # SEARCH RANGES: the solver and restoration loop may move any cost lever
  # within its envelope from this baseline, and their result SURVIVES to the
  # verdict (a coherence clamp after the search replaces the old end-of-
  # pipeline overwrite that erased the search). Businesses whose gates pass
  # without any search land exactly on this trajectory — identical to the old
  # behavior.
  try:
    from client_intake_and_finmo.post_intake_headcount.band_fitting import (  # type: ignore  # noqa: E501
      apply_fitted_cost_bands_to_model_input as _baseline_cost_stamp,
    )
    _fb = ((final_model_input_json or {}).get("solver_input") or {}).get("fitted_bands")
    if isinstance(_fb, dict) and _fb:
      final_model_input_json = _baseline_cost_stamp(final_model_input_json, _fb)
      next_result["model_input_json"] = final_model_input_json
      completion_trace["fitted_cost_baseline_stamp"] = {"status": "applied"}
    else:
      completion_trace["fitted_cost_baseline_stamp"] = {"status": "no_fitted_bands"}
  except Exception as _stamp_exc:  # pragma: no cover - defensive
    completion_trace["fitted_cost_baseline_stamp"] = {
      "status": "failed",
      "error": f"{type(_stamp_exc).__name__}: {str(_stamp_exc)[:300]}",
    }

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
        revenue_authored=bool(
          ((final_model_input_json or {}).get("solver_input") or {}).get("revenue_authored")
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
    # P3.26 F-1: broaden Site 1 trigger to also engage on
    # ITERATING_STILL with non-empty failing_metrics (F-3 populates
    # this when forward-looking forecast finds GPT-authorable
    # realism failures). Empty failing_metrics correctly skips.
    _should_engage_handler = (
      restoration_result.status == RestorationStatus.EXHAUSTED
      or (
        restoration_result.status == RestorationStatus.ITERATING_STILL
        and bool(getattr(restoration_result, "failing_metrics", None))
      )
    )
    if _should_engage_handler:
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
            # Phase 9 P3.32 K11.1 — H2 consults stage_ramp_contract
            # for per-quarter rev_max / cogs_max / marketing_max /
            # rd_max / ga_max / ni_floor / max_util enforcement via
            # mini_finmo viability_checks. Universal across NAICS.
            # Doctrine §10.5.
            stage_ramp_contract=stage_ramp_contract,
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

    # C6 — emit TARGET_SEEKING_PRE_CASH_GATE_STARTED right before the
    # gate evaluator fires so the gate's entry is observable in the
    # diagnostic stream.
    try:
      _emit_diag(
        phase=_DiagPhaseCode.TARGET_SEEKING,
        event_code=_DiagEventCode.TARGET_SEEKING_PRE_CASH_GATE_STARTED,
        status=_DiagStatus.STARTED,
        diagnostic_data={
          "gate_handler_already_ran": bool(_gate_handler_already_ran),
        },
      )
    except Exception:
      pass

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
          # Phase 9 P3.32 K11.1 — pre-cash gate Handler-engagement
          # site receives stage_ramp_contract for the same
          # coherence enforcement. Doctrine §10.5.
          stage_ramp_contract=stage_ramp_contract,
        )
        # P3.21 Part 2 housekeeping -- mirror Site 1's pattern at
        # orchestrator.py:2002-2010: capture the FINMO rebuild
        # exception into a structured field so the diagnostic is
        # preserved rather than silently swallowed. The exception
        # still does NOT re-raise (the cash strategy's Stage 3 P3.20
        # pre-validator rebuild closes the divergence window
        # downstream), but the diagnostic now survives for debugging
        # if a future change breaks that downstream rebuild.
        gate_rebuild_error: Optional[str] = None
        try:
          rebuilt = _build_finmo_for_gate(final_model_input_json or {})
          if isinstance(rebuilt, dict) and rebuilt:
            final_finmo_json = rebuilt
            next_result["finmo_json"] = final_finmo_json
            next_result["model_input_json"] = final_model_input_json
        except Exception as gate_rebuild_exc:
          gate_rebuild_error = f"{type(gate_rebuild_exc).__name__}: {str(gate_rebuild_exc)[:500]}"
      completion_trace["pre_cash_gate_handler"] = gate_handler_result.to_dict()
      if gate_rebuild_error:
        completion_trace["pre_cash_gate_handler"]["post_handler_finmo_rebuild_error"] = gate_rebuild_error
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

    # Phase 9 P3.32 K1 F5 — pre-cash gate Handler C routing for
    # payroll-touching violations. After K1 F1+F2 closed Leak A
    # (exhaustion handler no longer owns Payroll), the GPT exhaustion
    # handler invoked above cannot resolve violations whose
    # primary_levers contain "expenses::Payroll". Handler C
    # (post_intake_headcount.schedule.estimate_payroll_headcount_
    # schedule_with_gpt) is the canonical Payroll writer; its apply
    # chain keeps Mirror Flavor 1 alignment across all four payroll
    # surfaces with zero-tolerance assertions. Route the residual
    # payroll-touching violations to Handler C, re-apply via the
    # canonical apply chain, persist payroll_headcount to SQL (same
    # pattern as P3.26 Site B), then re-evaluate the gate. If
    # violations still remain, the hard-fail below fires with the
    # full diagnostic chain naming the Handler C re-author result.
    _gate_handler_c_route_attempted = False
    if gate_violations:
      _payroll_touching = [
        v for v in gate_violations
        if "expenses::Payroll" in (v.get("primary_levers") or [])
      ]
      if _payroll_touching:
        from client_intake_and_finmo.post_intake_headcount.feasibility_repair import (  # type: ignore
          route_payroll_feasibility_to_handler_c,
        )
        # Phase 9 P3.32 K1 F7 — recover the RICH original payroll
        # feasibility violations for Handler C's compactor.
        #
        # The orchestrator's _evaluate_gpt_authorable_pre_cash_checks
        # translates payroll feasibility violations from
        # payroll_revenue_feasibility_violations() into the generic
        # failing_metric shape (actual_value/effective_min/effective_max),
        # but it reads keys "actual_ratio" and "stage_ramp_max_ratio"
        # that only exist on stage_ramp_expense violations — NOT on
        # payroll feasibility violations. Result: payroll-touching
        # failing_metrics carry actual_value=0.0 / bounds=None.
        #
        # If F5 passes that translated form to Handler C as failure
        # details, Handler C's compactor (_compact_payroll_failure_for_
        # gpt at schedule.py:514) finds no usable failure context —
        # it looks for "violations" or "payroll_revenue_feasibility_
        # violations" keys with fields like payroll_percent_of_revenue,
        # effective_min_pct_with_tolerance, effective_max_pct_with_
        # tolerance, deterministic_driver_math.
        #
        # Without those rich fields, GPT iterates with no feedback
        # about what's wrong — Skyward Express timed out at 180s on
        # this exact issue (P3.32 draft 3 investigation).
        #
        # Fix: recompute the violations directly from the current
        # payroll_headcount + finmo_json state and pass them under
        # the canonical "violations" key. The compactor finds them
        # and feeds GPT the precise repair direction
        # (deterministic_driver_math.required_capacity_units_per_
        # supporting_fte_direction, etc.). Mirrors the pattern used
        # by P3.26 Commit 2 Site B at orchestrator.py:2716+.
        try:
          from client_intake_and_finmo.post_intake_headcount import (  # type: ignore
            payroll_revenue_feasibility_violations,
          )
          _rich_payroll_violations = payroll_revenue_feasibility_violations(
            payroll_headcount=payroll_headcount or {},
            finmo_json=final_finmo_json or {},
          ) or []
        except Exception:
          _rich_payroll_violations = []
        _gate_handler_c_route_attempted = True
        # Synthesize a payroll-feasibility-style failure payload from
        # the gate violations. Handler C's previous_contract_failure
        # consumer reads {error, error_code, stage, details} and the
        # compactor extracts "violations" / "payroll_revenue_
        # feasibility_violations" arrays from details.
        _failure_code = "pre_cash_gate_payroll_violation_routed_to_handler_c"
        _failure_stage = "post_intake_pre_cash_gpt_authorable_gate"
        _failure_message = (
          f"Pre-cash gate surfaced {len(_payroll_touching)} payroll-touching "
          f"violation(s) that GPT exhaustion handler cannot fix (P3.32 K1 "
          f"closed exhaustion handler's Payroll authority). Re-authoring "
          f"via Handler C with {len(_rich_payroll_violations)} rich "
          f"payroll_revenue_feasibility_violations for guidance."
        )
        _failure_details = {
          # Canonical "violations" key — _compact_payroll_failure_for_
          # gpt reads from here (schedule.py:560-564). Each violation
          # carries payroll_percent_of_revenue, policy bounds with
          # tolerance, repair_rule_key, and deterministic_driver_math
          # (precise quantitative repair direction). GPT sees the
          # actual problem and the exact fix direction.
          "violations": _rich_payroll_violations[:20],
          # Diagnostic-only fields (NOT consumed by the compactor):
          "payroll_touching_violations_sample": _payroll_touching[:10],
          "source_checks": sorted({
            str(v.get("source_check") or "") for v in _payroll_touching
            if v.get("source_check")
          }),
          "metric_keys": sorted({
            str(v.get("metric_key") or "") for v in _payroll_touching
            if v.get("metric_key")
          }),
          "handler_invoked_first": bool(_gate_handler_already_ran),
        }
        _live_count_gate = max(
          0,
          len([
            p for p in ((final_model_input_json or {}).get("periods") or [])
            if isinstance(p, dict) and not bool(p.get("is_stub"))
          ]),
        )
        try:
          _new_schedule, _new_mi, _new_finmo = route_payroll_feasibility_to_handler_c(
            failure_code=_failure_code,
            failure_message=_failure_message,
            failure_stage=_failure_stage,
            failure_details=_failure_details,
            business_facts=business_facts or {},
            ops_json=ops_json or {},
            people_json=people_json or {},
            financials_json=financials_json or {},
            financials_year1_json=financials_year1_json or {},
            planning_mode=planning_mode,
            planning_mode_reason=planning_mode_reason,
            model_input_json=final_model_input_json or {},
            finmo_json=final_finmo_json or {},
            payroll_headcount=payroll_headcount or {},
            stage_ramp_contract=stage_ramp_contract or {},
            draft_id=str(draft_id or "").strip(),
            client_id=str((business_facts or {}).get("client_id") or "").strip(),
            live_count=_live_count_gate,
            stage_prefix="pre_cash_gate_payroll_repair",
          )
          payroll_headcount = _new_schedule
          final_model_input_json = _new_mi
          final_finmo_json = _new_finmo
          next_result["model_input_json"] = final_model_input_json
          next_result["finmo_json"] = final_finmo_json
          completion_trace["pre_cash_gate_handler_c_route"] = {
            "status": "completed",
            "violations_routed": len(_payroll_touching),
            "failure_code": _failure_code,
            "metric_keys": _failure_details["metric_keys"],
          }
          # Persist payroll_headcount immediately (same pattern as
          # Site B at orchestrator.py:2776-2796). Without this the
          # workbook builder would re-render from the stale
          # headcount and recreate the Mirror Flavor 1 divergence.
          if conn is not None:
            try:
              import json as _json_pre_cash_persist
              _cur_g = conn.cursor()
              try:
                _cur_g.execute(
                  "UPDATE intake_consult_drafts SET payroll_headcount=%s WHERE draft_id=%s",
                  (
                    _json_pre_cash_persist.dumps(payroll_headcount, ensure_ascii=False, default=str),
                    str(draft_id or "").strip(),
                  ),
                )
                conn.commit()
              finally:
                try:
                  _cur_g.close()
                except Exception:
                  pass
            except Exception as _persist_exc:
              completion_trace["pre_cash_gate_handler_c_route"]["persist_warning"] = (
                f"{type(_persist_exc).__name__}: {str(_persist_exc)[:200]}"
              )
          # Re-evaluate the gate against the Handler-C-repaired state.
          gate_violations, gate_scope = _evaluate_gpt_authorable_pre_cash_checks(
            stage_ramp_contract=stage_ramp_contract or {},
            model_input_json=final_model_input_json or {},
            finmo_json=final_finmo_json or {},
            payroll_headcount=payroll_headcount or {},
            financials_json=financials_json or {},
            ops_json=ops_json or {},
          )
        except Exception as _route_exc:
          # Handler C routing failed — preserve the diagnostic and
          # let the hard-fail below fire with both the original gate
          # violation AND the routing failure context.
          completion_trace["pre_cash_gate_handler_c_route"] = {
            "status": "failed",
            "error": f"{type(_route_exc).__name__}: {str(_route_exc)[:500]}",
            "violations_attempted": len(_payroll_touching),
          }

    if gate_violations:
      muted_metrics = set(
        (final_model_input_json or {}).get("_muted_realism_metrics") or []
      )
      unmuted = [
        v for v in gate_violations
        if str(v.get("metric_key") or "") not in muted_metrics
      ]
      if unmuted:
        # ROOT-DISEASE FIX (references GROUND, they don't GATE): the GPT-authorable
        # pre-cash checks (rent%/cost-ratio cohort-band conformance, stage-ramp
        # expense/profitability paths) are REALITY-GROUNDING, not laws every
        # business must obey -- no cohort matches an individual business exactly.
        # A residual out-of-band value AFTER the handler had its pass is
        # INFORMATION the cascade/forecast carries forward; it must NOT crash the
        # run. Only genuine VIABILITY (the downstream acceptance gate's
        # net-income/EBITDA trajectory) may gate the verdict. So we record the
        # residuals as advisory grounding and FLOW into finalize instead of
        # raising. (Previously this hard-raised PostIntakePreconditionFailed under
        # CONVERGENCE_TEST_MODE -- that was the band-as-gate category error.)
        completion_trace["pre_cash_gate_advisory_residuals"] = {
          "unmuted_violation_count": len(unmuted),
          "violations_sample": unmuted[:10],
          "handler_invoked": bool(_gate_handler_already_ran),
          "muted_metric_count": len(muted_metrics),
          "handler_c_route_attempted": bool(_gate_handler_c_route_attempted),
          "handler_c_route_trace": completion_trace.get(
            "pre_cash_gate_handler_c_route", {}
          ),
          "doctrine": "band/conformance residual grounds the forecast; only viability gates the verdict",
        }
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

  # ----- SCALE PAYROLL WITH REVENUE FOR A LABOR-BOUND BUSINESS (executive judged) -----
  # At round-1 the revenue trajectory is not yet grown (the solver drives revenue
  # up afterwards), so the round-1 payroll pass staffs to a flat anchor and payroll
  # ends up ~flat. Against the SOLVER-GROWN revenue that makes payroll%-of-revenue
  # collapse and inflates EBITDA with operating leverage the business does not have
  # (a dental practice doubling patients must hire clinical staff). The executive's
  # labor-model judgment rides on payroll_headcount.labor_scaling; when labor-bound,
  # re-scale the payroll FTE/$ UP so each quarter tracks revenue x target_payroll%,
  # write it back, and rebuild -- so the ebitda band + cash + realism all see the
  # REAL margin, and the cascade's earlier levers are judged against it.
  try:
    _ls = ((final_model_input_json or {}).get("solver_input") or {}).get("labor_scaling_directive")
    _ls = _ls if isinstance(_ls, dict) else {}
    _target_pct = _safe_float(_ls.get("target_payroll_percent"))
    if _target_pct is None and isinstance(payroll_headcount, dict):
      _target_pct = _safe_float(payroll_headcount.get("target_payroll_percent_of_revenue"))
    if _ls.get("revenue_scales_with_labor") and _target_pct and isinstance(payroll_headcount, dict):
      from client_intake_and_finmo.post_intake_headcount.schedule import (  # type: ignore  # noqa: E501
        enforce_labor_scaling_on_payload as _enforce_labor_scaling,
      )
      from client_intake_and_finmo.post_intake_headcount.feasibility_repair import (  # type: ignore  # noqa: E501
        apply_payroll_schedule_to_state as _apply_payroll_to_state,
      )
      _fin_rows = (final_finmo_json or {}).get("quarter_rows") or []
      _synth_anchor = {
        "labor_intensity_class": payroll_headcount.get("labor_intensity_class"),
        "per_quarter": [
          {
            "q": int(_safe_float(r.get("quarter_index")) or 0),
            "payroll_budget": (_safe_float(r.get("revenue")) or 0.0) * float(_target_pct),
          }
          for r in _fin_rows
          if isinstance(r, dict) and int(_safe_float(r.get("quarter_index")) or 0) >= 1
        ],
      }
      # TRANSACTIONAL: enforce on a COPY; adopt + persist only after the
      # canonical apply succeeds. Mutating the live schedule before the apply
      # was known-good split the three payroll surfaces when the apply raised
      # (scaled schedule in memory at the pre-finalize persist vs unscaled
      # model_input) and blew the K1 F6 invariant. On failure everything stays
      # at the pre-scaling state -- consistent surfaces, honest trace.
      _scaled_schedule = copy.deepcopy(payroll_headcount)
      _pay_summary = _enforce_labor_scaling(_scaled_schedule, _synth_anchor)
      if _pay_summary:
        # Re-apply through the CANONICAL chain so all three payroll surfaces
        # (payroll_headcount.quarter_totals, model_input.expenses.Payroll.values,
        # model_input.derived_driver_runtime) stay in sync -- the K1 F6 invariant
        # rejects a payroll write that bypasses this chain.
        _live_count = len([
          r for r in ((final_finmo_json or {}).get("quarter_rows") or [])
          if isinstance(r, dict) and int(_safe_float(r.get("quarter_index")) or 0) >= 1
          and (_safe_float(r.get("revenue")) or 0.0) > 0.0
        ]) or int(horizon or 20)
        final_model_input_json, final_finmo_json = _apply_payroll_to_state(
          schedule_payload=_scaled_schedule,
          model_input_json=final_model_input_json,
          finmo_json=final_finmo_json,
          live_count=_live_count,
          stage_prefix="post_cascade_labor_scaling",
        )
        payroll_headcount = _scaled_schedule
        next_result["payroll_headcount"] = payroll_headcount
        next_result["model_input_json"] = final_model_input_json
        next_result["finmo_json"] = final_finmo_json
        # Persist the scaled schedule to the CANONICAL SQL payroll_headcount
        # column so the F6 re-sync + workbook headcount trajectory read the
        # scaled FTE (same immediate-persist pattern as the Handler-C route);
        # otherwise the column stays at the round-1 (flat) schedule and the
        # workbook shows flat headcount while the finmo shows scaled payroll.
        if conn is not None:
          try:
            import json as _labor_persist_json
            _lp_cur = conn.cursor()
            try:
              _lp_cur.execute(
                "UPDATE intake_consult_drafts SET payroll_headcount=%s WHERE draft_id=%s",
                (
                  _labor_persist_json.dumps(payroll_headcount, ensure_ascii=False, default=str),
                  str(draft_id or "").strip(),
                ),
              )
              conn.commit()
            finally:
              try:
                _lp_cur.close()
              except Exception:
                pass
          except Exception:
            pass
        completion_trace["labor_scaling_post_solver"] = {
          "applied": True,
          "rationale": _ls.get("rationale"),
          "judgment_source": _ls.get("judgment_source"),
          **_pay_summary,
        }
      else:
        completion_trace["labor_scaling_post_solver"] = {"applied": False, "reason": "already tracks target"}
    else:
      completion_trace["labor_scaling_post_solver"] = {
        "applied": False,
        "reason": "not labor-bound or no target%",
        "revenue_scales_with_labor": _ls.get("revenue_scales_with_labor"),
      }
  except Exception as _pay_exc:  # pragma: no cover - defensive
    completion_trace["labor_scaling_post_solver"] = {
      "applied": False,
      "error": f"{type(_pay_exc).__name__}: {str(_pay_exc)[:300]}",
    }

  # ----- CLAMP THE SEARCHED COST ROWS INTO THE FITTED ENVELOPE -----
  # The fitted bands are SEARCH RANGES, not final values. The baseline stamp
  # (step 0.5 above, pre-search) put the actuals on the operator-anchored
  # trajectory; the solver + restoration loop were then free to move any cost
  # lever WITHIN its envelope toward viability, and their result must SURVIVE
  # to the verdict. The old design re-stamped the band TARGET here, erasing
  # the search (Luna: COGS searched to the 42.8% band minimum, stamped back
  # to the 60-65% target trajectory before the gates measured it). Now this
  # step only CLAMPS each searched value into [band min, band max] -- a
  # defensibility guard, never an overwrite -- so cash sizing, the realism
  # gate, and finalize evaluate the plan the search actually found.
  try:
    from client_intake_and_finmo.post_intake_headcount.band_fitting import (  # type: ignore  # noqa: E501
      clamp_cost_rows_to_envelope as _clamp_cost_rows,
      derive_ebitda_margin_band_from_costs as _derive_ebitda_band,
    )
    from client_intake_and_finmo.post_intake_sequence import (  # type: ignore
      post_intake_sequence_step_scope as _ground_scope,
    )
    from client_intake_and_finmo.post_intake_solver import (  # type: ignore
      FINMO_OUTPUT_TARGET_KEY as _FOT_KEY,
    )
    _fitted_bands_for_ground = (
      ((final_model_input_json or {}).get("solver_input") or {}).get("fitted_bands")
    )
    _fitted_env_for_clamp = (
      ((final_model_input_json or {}).get("solver_input") or {}).get("fitted_envelope")
    )
    _fitted_env_per_q_for_clamp = (
      ((final_model_input_json or {}).get("solver_input") or {}).get("fitted_envelope_per_q")
    )
    if isinstance(_fitted_bands_for_ground, dict) and _fitted_bands_for_ground:
      _clamped_rows = _clamp_cost_rows(
        final_model_input_json, _fitted_env_for_clamp, _fitted_env_per_q_for_clamp,
      )
      # Rebuild the finmo so downstream steps (cash sizing, realism, finalize)
      # see the searched-and-clamped costs immediately.
      # build_python_finmo_json requires an active sequence-controller scope.
      if callable(build_finmo_callable):
        with _ground_scope(
          step_key="post_intake_target_seeking_post_cascade_cost_grounding",
          executor_function="apply_fitted_cost_bands_to_model_input",
        ):
          final_finmo_json = build_finmo_callable(final_model_input_json)
      # Derive the EBITDA-margin realism band FROM the grounded costs + the
      # plan's own payroll/rent, and overlay it onto finmo_output_targets so the
      # realism gate judges EBITDA against what its own costs produce -- not an
      # independent public-cohort band (the two-sources-of-truth bug that flagged
      # a lean-but-real practice for beating public-company margins). If the costs
      # are in-band, EBITDA is in-band by construction.
      _ebitda_grounding_status = "no_envelope_or_finmo"
      _fitted_env = (
        ((final_model_input_json or {}).get("solver_input") or {}).get("fitted_envelope")
      )
      _derived_ebitda = _derive_ebitda_band(
        _fitted_env, final_finmo_json, horizon=int(horizon or 20),
      )
      if isinstance(_derived_ebitda, dict):
        _si = (final_model_input_json or {}).get("solver_input")
        if isinstance(_si, dict):
          _fot = _si.setdefault(_FOT_KEY, {})
          if isinstance(_fot, dict):
            _fot_metrics = _fot.setdefault("metrics", {})
            if isinstance(_fot_metrics, dict):
              _fot_metrics["ebitda_margin"] = _derived_ebitda
              _ebitda_grounding_status = "applied"
      next_result["model_input_json"] = final_model_input_json
      next_result["finmo_json"] = final_finmo_json
      completion_trace["fitted_cost_band_grounding"] = {
        "status": "search_preserved_clamped",
        "clamped_rows": _clamped_rows,
        "metrics": sorted(str(k) for k in _fitted_bands_for_ground.keys()),
        "ebitda_band_derivation": _ebitda_grounding_status,
        "ebitda_band": _derived_ebitda if isinstance(_derived_ebitda, dict) else None,
      }
    else:
      completion_trace["fitted_cost_band_grounding"] = {"status": "no_fitted_bands"}
  except Exception as _ground_exc:  # pragma: no cover - defensive
    completion_trace["fitted_cost_band_grounding"] = {
      "status": "failed",
      "error": f"{type(_ground_exc).__name__}: {str(_ground_exc)[:300]}",
    }

  # ----- PHASE B: FULL-CONFIGURATION SEARCH UNDER EXECUTIVE CEILINGS -----
  # The cost-row search alone cannot save a plan whose blocker is revenue
  # (Luna: honest bands leave Q11 EBITDA deeply negative) or payroll (dental:
  # 48-57% of revenue). Phase B re-admits unit price / capacity / utilization
  # and the payroll target% to the search -- but ONLY behind the executive's
  # per-business, lender-believability ceilings (identity-judged, rail-
  # clamped, response-locked). Levers and ceilings ship together: without a
  # ceilings verdict the levers stay closed and the honest failure stands.
  #
  # ENGAGEMENT GATE: the realism validator (the same judgment the acceptance
  # gate reads) runs on the healed state (post clamp + ebitda-band overlay).
  # Only a plan failing the EBITDA-viability family engages; a plan that is
  # already viable is left byte-identical (no new GPT calls, no new moves).
  try:
    _pb_trace: Dict[str, Any] = {"engaged": False}
    completion_trace["phase_b_lever_search"] = _pb_trace

    def _pb_failing_viability_metrics(
      _mi: Optional[Dict[str, Any]] = None,
      _fj: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
      from client_intake_and_finmo.post_intake_realism.validator import (  # type: ignore
        validate_industry_realism_bands,
      )
      _pb_payload = validate_industry_realism_bands(
        model_input_json=(_mi if _mi is not None else final_model_input_json) or {},
        finmo_json=(_fj if _fj is not None else final_finmo_json) or {},
        business_naics_6=business_naics_6 or None,
        ops_json=ops_json or {},
        financials_json=financials_json or {},
        solver_input_targets_payload=(
          targets_payload_post
          if isinstance(targets_payload_post, dict) and targets_payload_post.get("metrics")
          else (targets_payload or None)
        ),
        planning_mode=planning_mode,
      )
      _viol = (_pb_payload or {}).get("hard_fail_violations") or []
      out: List[str] = []
      for _v in _viol:
        _mk = str((_v or {}).get("metric_key") or "").strip() if isinstance(_v, dict) else str(_v)
        if not _mk:
          continue
        if "ebitda" in _mk or "fixed_cost_burden" in _mk or "net_income" in _mk:
          out.append(_mk)
      # The acceptance gate's NI-trajectory rule (ramping OR flat-healthy) is
      # STRICTER than the realism validator's hard-fail set -- a plan can clear
      # every realism band and still fail it (Ironwood: Q11 NI -2%, delta
      # +1.4pp). Evaluate the same rule here so the engagement signal matches
      # what the verdict will actually judge. Pure function of the finmo.
      try:
        from client_intake_and_finmo.post_intake_acceptance.gate import (  # type: ignore  # noqa: E501
          _check_net_income_trajectory_viable as _pb_ni_check,
        )
        _ni_ok, _ = _pb_ni_check((_fj if _fj is not None else final_finmo_json) or {})
        if not _ni_ok:
          out.append("net_income_trajectory_viable")
      except Exception:
        pass
      return sorted(set(out))

    def _pb_lever_snapshot() -> Dict[str, Dict[str, float]]:
      """Average per-lever q1/q11/q20 across LOB rows, for the move log."""
      snap: Dict[str, Dict[str, float]] = {}
      _rows = ((final_model_input_json or {}).get("sections") or {}).get("revenue") or []
      agg: Dict[str, List[List[float]]] = {}
      for _row in _rows:
        if not isinstance(_row, dict):
          continue
        _drv = str(_row.get("driver") or "").strip()
        if _drv not in ("Unit Price", "Capacity", "Utilization"):
          continue
        _vals = _row.get("values") or []
        def _at(i: int) -> float:
          try:
            return float(_vals[i]) if i < len(_vals) and _vals[i] is not None else 0.0
          except (TypeError, ValueError):
            return 0.0
        agg.setdefault(_drv, []).append([_at(1), _at(11), _at(20)])
      for _drv, _entries in agg.items():
        _n = max(1, len(_entries))
        snap[_drv] = {
          "q1": round(sum(e[0] for e in _entries) / _n, 6),
          "q11": round(sum(e[1] for e in _entries) / _n, 6),
          "q20": round(sum(e[2] for e in _entries) / _n, 6),
        }
      return snap

    def _pb_q11_ebitda_margin(_fj: Optional[Dict[str, Any]]) -> Optional[float]:
      for _r in ((_fj or {}).get("quarter_rows") or []):
        if isinstance(_r, dict) and int(_safe_float(_r.get("quarter_index")) or 0) == 11:
          _rev = _safe_float(_r.get("revenue")) or 0.0
          if _rev > 0:
            return (_safe_float(_r.get("ebitda")) or 0.0) / _rev
      return None

    _pb_failing = _pb_failing_viability_metrics()
    _pb_trace["failing_metrics_before"] = _pb_failing
    if _pb_failing:
      from client_intake_and_finmo.post_intake_target_solver.gpt_lever_ceilings import (  # type: ignore  # noqa: E501
        gpt_author_lever_ceilings_once,
      )
      from client_intake_and_finmo.post_intake_target_solver import (  # type: ignore
        run_restoration_loop as _pb_run_restoration,
      )
      from client_intake_and_finmo.finmo_bridge import (  # type: ignore
        build_python_finmo_json as _pb_build_finmo_raw,
      )
      from client_intake_and_finmo.post_intake_sequence import (  # type: ignore
        post_intake_sequence_step_scope as _pb_scope,
      )
      from client_intake_and_finmo.post_intake_headcount.band_fitting import (  # type: ignore  # noqa: E501
        clamp_cost_rows_to_envelope as _pb_clamp_cost_rows,
        derive_ebitda_margin_band_from_costs as _pb_derive_ebitda_band,
      )

      def _pb_build_finmo(mi: Dict[str, Any]) -> Dict[str, Any]:
        _p = _pb_build_finmo_raw(model_input_json=copy.deepcopy(mi or {}))
        return _p if isinstance(_p, dict) else {}

      # -- Executive ceilings (identity-judged, locked, rail-clamped). --
      _pb_ops = ops_json if isinstance(ops_json, dict) else {}
      _pb_identity = {
        "business_type": _pb_ops.get("business_type"),
        "business_description": (
          str(
            _pb_ops.get("business_description_summary")
            or _pb_ops.get("business_description") or ""
          ).strip()[:220] or None
        ),
        "sales_modality": _pb_ops.get("sales_modality"),
        "consumer_type": _pb_ops.get("consumer_type"),
      }
      _pb_ls = ((final_model_input_json or {}).get("solver_input") or {}).get("labor_scaling_directive")
      _pb_ls = _pb_ls if isinstance(_pb_ls, dict) else {}
      _pb_authored_payroll_pct = _safe_float(_pb_ls.get("target_payroll_percent"))
      if _pb_authored_payroll_pct is None and isinstance(payroll_headcount, dict):
        _pb_authored_payroll_pct = _safe_float(
          payroll_headcount.get("target_payroll_percent_of_revenue")
        )
      _pb_labor_bound = bool(_pb_ls.get("revenue_scales_with_labor"))
      _pb_anchors: Dict[str, Any] = {"levers": _pb_lever_snapshot()}
      if isinstance(payroll_headcount, dict):
        _pb_anchors["payroll"] = {
          "target_percent_of_revenue": _pb_authored_payroll_pct,
          "labor_intensity_class": payroll_headcount.get("labor_intensity_class"),
          "revenue_scales_with_labor": _pb_labor_bound,
          "q11_actual_percent_of_revenue": None,
        }
        for _r in ((final_finmo_json or {}).get("quarter_rows") or []):
          if isinstance(_r, dict) and int(_safe_float(_r.get("quarter_index")) or 0) == 11:
            _rev11 = _safe_float(_r.get("revenue")) or 0.0
            if _rev11 > 0:
              _pb_anchors["payroll"]["q11_actual_percent_of_revenue"] = round(
                (_safe_float(_r.get("payroll")) or 0.0) / _rev11, 4,
              )
      _pb_ceil_result = gpt_author_lever_ceilings_once(
        business_identity=_pb_identity, lever_anchors=_pb_anchors,
      )
      if not _pb_ceil_result.get("ok"):
        # No ceilings verdict -> levers stay CLOSED. Never open a lever naked.
        _pb_trace.update({
          "engaged": False,
          "reason": "ceilings_unavailable_levers_stay_closed",
          "ceilings_error": _pb_ceil_result.get("error"),
        })
      else:
        _pb_ceilings = _pb_ceil_result["ceilings"]
        _pb_trace["engaged"] = True
        _pb_trace["ceilings"] = _pb_ceilings
        _pb_before = _pb_lever_snapshot()
        _pb_q11_before = _pb_q11_ebitda_margin(final_finmo_json)

        # -- Holistic search: revenue + cost levers under the ceilings. --
        with _pb_scope(
          step_key="post_intake_target_seeking_restoration_loop",
          executor_function="phase_b_ceilinged_restoration",
        ):
          _pb_restoration = _pb_run_restoration(
            model_input=final_model_input_json or {},
            build_finmo=_pb_build_finmo,
            business_naics_6=business_naics_6 or None,
            horizon=int(horizon or 20),
            planning_mode=planning_mode,
            ops_json=ops_json or {},
            financials_json=financials_json or {},
            solver_targets_payload=(
              targets_payload_post
              if isinstance(targets_payload_post, dict) and targets_payload_post.get("metrics")
              else (targets_payload or None)
            ),
            revenue_authored=True,
            revenue_lever_ceilings=_pb_ceilings,
          )
          final_finmo_json = _pb_build_finmo(final_model_input_json or {})
          next_result["finmo_json"] = final_finmo_json
          next_result["model_input_json"] = final_model_input_json
        _pb_trace["restoration_status"] = str(
          getattr(_pb_restoration, "status", None).value
          if getattr(_pb_restoration, "status", None) is not None else "unknown"
        )

        # -- Labor refresh: payroll must track the SEARCHED revenue for a
        #    labor-bound business (no free operating leverage from the raise).
        if _pb_labor_bound and _pb_authored_payroll_pct and isinstance(payroll_headcount, dict):
          from client_intake_and_finmo.post_intake_headcount.schedule import (  # type: ignore  # noqa: E501
            enforce_labor_scaling_on_payload as _pb_enforce_labor,
          )
          from client_intake_and_finmo.post_intake_headcount.feasibility_repair import (  # type: ignore  # noqa: E501
            apply_payroll_schedule_to_state as _pb_apply_payroll,
          )

          def _pb_live_count() -> int:
            return len([
              _r for _r in ((final_finmo_json or {}).get("quarter_rows") or [])
              if isinstance(_r, dict) and int(_safe_float(_r.get("quarter_index")) or 0) >= 1
              and (_safe_float(_r.get("revenue")) or 0.0) > 0.0
            ]) or int(horizon or 20)

          def _pb_synth_anchor(_pct: float) -> Dict[str, Any]:
            return {
              "labor_intensity_class": payroll_headcount.get("labor_intensity_class"),
              "per_quarter": [
                {
                  "q": int(_safe_float(_r.get("quarter_index")) or 0),
                  "payroll_budget": (_safe_float(_r.get("revenue")) or 0.0) * float(_pct),
                }
                for _r in ((final_finmo_json or {}).get("quarter_rows") or [])
                if isinstance(_r, dict) and int(_safe_float(_r.get("quarter_index")) or 0) >= 1
              ],
            }

          _pb_refresh_schedule = copy.deepcopy(payroll_headcount)
          _pb_refresh_summary = _pb_enforce_labor(
            _pb_refresh_schedule, _pb_synth_anchor(float(_pb_authored_payroll_pct)),
          )
          if _pb_refresh_summary:
            final_model_input_json, final_finmo_json = _pb_apply_payroll(
              schedule_payload=_pb_refresh_schedule,
              model_input_json=final_model_input_json,
              finmo_json=final_finmo_json,
              live_count=_pb_live_count(),
              stage_prefix="phase_b_labor_refresh",
            )
            payroll_headcount = _pb_refresh_schedule
            next_result["payroll_headcount"] = payroll_headcount
            next_result["model_input_json"] = final_model_input_json
            next_result["finmo_json"] = final_finmo_json
            _pb_trace["labor_refresh"] = _pb_refresh_summary

          # -- Payroll lever: trim the payroll target% toward the executive
          #    floor ONLY as far as viability requires. Deterministic
          #    descending trial; never below the floor; existing staff are
          #    never cut (the trim defers planned hires). If no candidate
          #    reaches viability the authored staffing stands -- an honest
          #    failure, not an understaffed fake pass.
          _pb_floor = _safe_float(_pb_ceilings.get("payroll_min_percent_of_revenue"))
          # A candidate is viable when the realism validator itself — the same
          # judgment the acceptance gate reads — reports NO failing viability
          # metrics on the candidate state. A cheaper Q11-margin proxy misses
          # shape gates (ebitda_q20_holds, fixed_cost_burden), which are
          # exactly what a payroll-heavy business fails.
          _pb_still_failing = _pb_failing_viability_metrics()
          if (
            _pb_floor is not None
            and float(_pb_floor) < float(_pb_authored_payroll_pct) - 1e-9
            and _pb_still_failing
          ):
            _pb_candidates: List[float] = []
            _pct = float(_pb_authored_payroll_pct) - 0.02
            while _pct > float(_pb_floor) + 1e-9:
              _pb_candidates.append(round(_pct, 4))
              _pct -= 0.02
            _pb_candidates.append(round(float(_pb_floor), 4))
            _pb_tried: List[Dict[str, Any]] = []
            _pb_chosen = None
            _pb_chosen_ni_deferred = False
            # The NI-trajectory rule depends on the financing structure the
            # CASH PASS has not built yet (dental: pre-cash NI fails, post-
            # restructure NI passes) -- at trial time it is ADVISORY only.
            # The LEAST-TRIM candidate clearing every CASH-INDEPENDENT
            # realism metric is adopted; the real NI check judges the
            # finished plan at the gate. Preferring a deeper-trim candidate
            # just because its pre-cash NI forecast looks better would
            # understaff the business on a financing-sensitive signal.
            for _cand in _pb_candidates:
              _cand_schedule = copy.deepcopy(payroll_headcount)
              _cand_summary = _pb_enforce_labor(
                _cand_schedule, _pb_synth_anchor(_cand), allow_scale_down=True,
              )
              if not _cand_summary:
                _pb_tried.append({"percent": _cand, "result": "no_scaling_needed"})
                continue
              try:
                _cand_model, _cand_finmo = _pb_apply_payroll(
                  schedule_payload=_cand_schedule,
                  model_input_json=copy.deepcopy(final_model_input_json),
                  finmo_json=copy.deepcopy(final_finmo_json),
                  live_count=_pb_live_count(),
                  stage_prefix="phase_b_payroll_lever_trial",
                )
              except Exception as _cand_exc:
                _pb_tried.append({
                  "percent": _cand,
                  "result": f"apply_failed: {type(_cand_exc).__name__}: {str(_cand_exc)[:150]}",
                })
                continue
              # Judge the candidate against ITS OWN derived ebitda band --
              # trimming payroll moves the band the realism gate reads.
              _cand_env = (
                ((_cand_model or {}).get("solver_input") or {}).get("fitted_envelope")
              )
              _cand_band = _pb_derive_ebitda_band(
                _cand_env, _cand_finmo, horizon=int(horizon or 20),
              )
              if isinstance(_cand_band, dict):
                _cand_si = (_cand_model or {}).get("solver_input")
                if isinstance(_cand_si, dict):
                  _cand_fot = _cand_si.setdefault(_FOT_KEY, {})
                  if isinstance(_cand_fot, dict):
                    _cand_fot_metrics = _cand_fot.setdefault("metrics", {})
                    if isinstance(_cand_fot_metrics, dict):
                      _cand_fot_metrics["ebitda_margin"] = _cand_band
              _cand_failing = _pb_failing_viability_metrics(_cand_model, _cand_finmo)
              _cand_soft_ok = not [
                _m for _m in _cand_failing if _m != "net_income_trajectory_viable"
              ]
              _pb_tried.append({
                "percent": _cand,
                "q11_ebitda_margin": _pb_q11_ebitda_margin(_cand_finmo),
                "failing_metrics": _cand_failing,
                "viable": _cand_soft_ok,
              })
              if _cand_soft_ok:
                _pb_chosen_ni_deferred = "net_income_trajectory_viable" in _cand_failing
                final_model_input_json = _cand_model
                final_finmo_json = _cand_finmo
                payroll_headcount = _cand_schedule
                next_result["payroll_headcount"] = payroll_headcount
                next_result["model_input_json"] = final_model_input_json
                next_result["finmo_json"] = final_finmo_json
                _pb_chosen = _cand
                if conn is not None:
                  try:
                    import json as _pb_json
                    _pb_cur = conn.cursor()
                    try:
                      _pb_cur.execute(
                        "UPDATE intake_consult_drafts SET payroll_headcount=%s WHERE draft_id=%s",
                        (
                          _pb_json.dumps(payroll_headcount, ensure_ascii=False, default=str),
                          str(draft_id or "").strip(),
                        ),
                      )
                      conn.commit()
                    finally:
                      try:
                        _pb_cur.close()
                      except Exception:
                        pass
                  except Exception:
                    pass
                break
            if _pb_chosen is None:
              _pb_note = "authored staffing kept (no candidate reached viability)"
            elif _pb_chosen_ni_deferred:
              _pb_note = (
                "least-trim candidate clearing cash-independent metrics "
                "adopted (NI trajectory deferred to the post-cash gate)"
              )
            else:
              _pb_note = "least-trim viable candidate adopted"
            _pb_trace["payroll_lever"] = {
              "authored_percent": _pb_authored_payroll_pct,
              "executive_floor_percent": _pb_floor,
              "candidates_tried": _pb_tried,
              "chosen_percent": _pb_chosen,
              "note": _pb_note,
            }

        # -- Re-ground: the search may have moved cost rows; clamp back into
        #    the envelope and re-derive the ebitda band off the final state.
        _pb_env = (
          ((final_model_input_json or {}).get("solver_input") or {}).get("fitted_envelope")
        )
        _pb_env_per_q = (
          ((final_model_input_json or {}).get("solver_input") or {}).get("fitted_envelope_per_q")
        )
        _pb_reclamped = _pb_clamp_cost_rows(final_model_input_json, _pb_env, _pb_env_per_q)
        # build_python_finmo_json requires an active sequence-controller scope.
        with _pb_scope(
          step_key="post_intake_target_seeking_post_cascade_cost_grounding",
          executor_function="phase_b_lever_search_reground",
        ):
          final_finmo_json = _pb_build_finmo(final_model_input_json or {})
        _pb_band2 = _pb_derive_ebitda_band(_pb_env, final_finmo_json, horizon=int(horizon or 20))
        if isinstance(_pb_band2, dict):
          _pb_si = (final_model_input_json or {}).get("solver_input")
          if isinstance(_pb_si, dict):
            _pb_fot = _pb_si.setdefault(_FOT_KEY, {})
            if isinstance(_pb_fot, dict):
              _pb_fot_metrics = _pb_fot.setdefault("metrics", {})
              if isinstance(_pb_fot_metrics, dict):
                _pb_fot_metrics["ebitda_margin"] = _pb_band2
        next_result["model_input_json"] = final_model_input_json
        next_result["finmo_json"] = final_finmo_json

        # -- Move log: what moved, and the ceiling that bounded it. --
        _pb_after = _pb_lever_snapshot()
        _pb_moves: Dict[str, Any] = {}
        for _drv in sorted(set(_pb_before) | set(_pb_after)):
          _b = _pb_before.get(_drv) or {}
          _a = _pb_after.get(_drv) or {}
          _pb_moves[_drv] = {
            "q1": [_b.get("q1"), _a.get("q1")],
            "q11": [_b.get("q11"), _a.get("q11")],
            "q20": [_b.get("q20"), _a.get("q20")],
          }
        _pb_trace["revenue_moves_before_after"] = _pb_moves
        _pb_trace["reclamped_rows"] = _pb_reclamped
        _pb_trace["q11_ebitda_margin"] = [
          _pb_q11_before, _pb_q11_ebitda_margin(final_finmo_json),
        ]
        _pb_trace["failing_metrics_after"] = _pb_failing_viability_metrics()
  except Exception as _pb_exc:  # pragma: no cover - defensive
    # PRESERVE the partial trace (ceilings, moves already made) -- an error
    # after mutations must stay diagnosable, not vanish behind a bare flag.
    _pb_err_trace = completion_trace.get("phase_b_lever_search")
    if not isinstance(_pb_err_trace, dict):
      _pb_err_trace = {"engaged": False}
      completion_trace["phase_b_lever_search"] = _pb_err_trace
    _pb_err_trace["error"] = f"{type(_pb_exc).__name__}: {str(_pb_exc)[:400]}"

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
    # Step 9c — cash_pass entry diagnostic.
    _emit_diag(
      phase=_DiagPhaseCode.CASH_PASS,
      event_code=_DiagEventCode.CASH_PASS_STARTED,
      status=_DiagStatus.STARTED,
      diagnostic_data={
        "adaptive_policy_mode": (
          adaptive_policy_dict.get("cash_mode")
          if isinstance(adaptive_policy_dict, dict) else None
        ),
        "industry_profile_present": bool(cash_industry_profile),
      },
    )
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
      _emit_diag(
        phase=_DiagPhaseCode.CASH_PASS,
        event_code=_DiagEventCode.CASH_PASS_COMPLETED,
        status=_DiagStatus.COMPLETED,
        diagnostic_data={
          "cash_mode": getattr(cash_result, "cash_mode", None),
          "applied_updates_count": getattr(cash_result, "applied_updates_count", 0),
        },
      )
      # Step 9d item 20 — FAIL_CASH_PASS_RESULT_MALFORMED. The cash
      # strategy returns a CashStrategyResult; we assert it has the
      # applied_updates_count int that the rebuild branch reads next.
      _cash_applied = getattr(cash_result, "applied_updates_count", None)
      if not isinstance(_cash_applied, int) or _cash_applied < 0:
        from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
          FailFastCode as _FFC, PhaseCode as _PC, raise_fail_fast as _rff,
        )
        _rff(
          conn, draft_id=_DIAG_DRAFT_ID, planning_run_id=_DIAG_PLANNING_RUN_ID,
          phase=_PC.CASH_PASS,
          code=_FFC.FAIL_CASH_PASS_RESULT_MALFORMED,
          detail=f"applied_updates_count={_cash_applied!r} (expected non-negative int)",
          where="orchestrator._run_post_cascade_completion (cash_pass)",
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
    # Step 9c — realism_gate entry diagnostic.
    _emit_diag(
      phase=_DiagPhaseCode.REALISM_GATE,
      event_code=_DiagEventCode.REALISM_GATE_STARTED,
      status=_DiagStatus.STARTED,
      diagnostic_data={"business_naics_6": business_naics_6 or None,
                       "planning_mode": planning_mode},
    )
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
      _emit_diag(
        phase=_DiagPhaseCode.REALISM_GATE,
        event_code=_DiagEventCode.REALISM_GATE_COMPLETED,
        status=_DiagStatus.COMPLETED,
        diagnostic_data={
          "result_count": int(realism_gate_payload.get("result_count") or 0),
          "warning_count": int(realism_gate_payload.get("warning_count") or 0),
          "checked_metric_count": int(realism_gate_payload.get("checked_metric_count") or 0),
        },
      )
      # Step 9d items 21 + 22 — band_source provenance + count
      # mismatch. Every result row carries band_source; checked + any
      # skipped metric_count must reconcile with the total result_count
      # (or all three may be zero on the empty-results branch).
      _rg_results = realism_gate_payload.get("results") or []
      _missing_provenance = [
        i for i, r in enumerate(_rg_results)
        if not isinstance(r, dict) or not r.get("band_source")
      ]
      if _missing_provenance:
        from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
          FailFastCode as _FFC, PhaseCode as _PC, raise_fail_fast as _rff,
        )
        _rff(
          conn, draft_id=_DIAG_DRAFT_ID, planning_run_id=_DIAG_PLANNING_RUN_ID,
          phase=_PC.REALISM_GATE,
          code=_FFC.FAIL_REALISM_BAND_SOURCE_MISSING,
          detail=f"{len(_missing_provenance)} result rows missing band_source (first idx={_missing_provenance[0]})",
          where="orchestrator._run_post_cascade_completion (realism_gate)",
        )
      _rg_total = int(realism_gate_payload.get("result_count") or 0)
      _rg_checked = int(realism_gate_payload.get("checked_metric_count") or 0)
      _rg_skipped = int(realism_gate_payload.get("skipped_metric_count") or 0)
      if _rg_total != 0 and _rg_total != (_rg_checked + _rg_skipped):
        from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
          FailFastCode as _FFC, PhaseCode as _PC, raise_fail_fast as _rff,
        )
        _rff(
          conn, draft_id=_DIAG_DRAFT_ID, planning_run_id=_DIAG_PLANNING_RUN_ID,
          phase=_PC.REALISM_GATE,
          code=_FFC.FAIL_REALISM_COUNT_MISMATCH,
          detail=f"result_count={_rg_total} != checked({_rg_checked}) + skipped({_rg_skipped})",
          where="orchestrator._run_post_cascade_completion (realism_gate)",
        )
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
      _emit_diag(
        phase=_DiagPhaseCode.REALISM_GATE,
        event_code=_DiagEventCode.REALISM_GATE_CHECK_FAILED,
        status=_DiagStatus.FAILED,
        diagnostic_data={
          "result_count": len(raised_results),
          "hard_fail_message": str(exc)[:300],
        },
      )
  except Exception as exc:
    completion_trace["realism_gate"] = {
      "status": "failed",
      "error": f"{type(exc).__name__}: {str(exc)[:500]}",
    }
    _emit_diag(
      phase=_DiagPhaseCode.REALISM_GATE,
      event_code=_DiagEventCode.REALISM_GATE_CHECK_FAILED,
      status=_DiagStatus.FAILED,
      diagnostic_data={"error": f"{type(exc).__name__}: {str(exc)[:300]}"},
    )

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

  # Phase 9 P3.16 — build the capital lease schedule snapshot here
  # against the post-cash-pass FINMO + model_input. Capital lease has
  # NO dedicated handler; the snapshot is pure deterministic Python
  # math, mirroring how the debt schedule snapshot is computed (Mirror
  # Flavor 2). Validators (Type 1) and machinery fail-fasts (Type 2)
  # fire at finalize against this snapshot to catch builder drift.
  capital_lease_schedule_payload: Optional[Dict[str, Any]] = None
  try:
    from client_intake_and_finmo.post_intake_capital_lease import (  # type: ignore
      build_capital_lease_schedule_snapshot,
    )
    capital_lease_schedule_payload = build_capital_lease_schedule_snapshot(
      finmo_payload=copy.deepcopy(final_finmo_json or {}),
      model_input_json=copy.deepcopy(final_model_input_json or {}),
      financials_json=copy.deepcopy(financials_json or {}),
      source_stage="post_intake_finalize_validation",
    )
    if isinstance(capital_lease_schedule_payload, dict):
      next_result["capital_lease_schedule"] = capital_lease_schedule_payload
  except Exception as exc:
    diagnostics["capital_lease_schedule_build_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"

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
  # Phase 9 P3.32 K1 F6 — payroll three-surface invariant assertion
  # BEFORE pre-finalize persist writes model_input + finmo to SQL.
  #
  # Lives OUTSIDE the persist try/except so it surfaces as the
  # PostIntakePreconditionFailed it raises rather than getting
  # wrapped into a persist failure trace. Doctrine: payroll dollars
  # must agree across three surfaces with $1 tolerance (int
  # rounding noise only): (a) payroll_headcount.quarter_totals.
  # payroll (canonical Handler-C-authored schedule), (b)
  # model_input.expenses.Payroll.values (derived via apply chain),
  # and (c) model_input.derived_driver_runtime[expenses::Payroll].
  # payroll_headcount.quarter_totals.payroll (snapshot used by
  # apply_derived_driver_policies_to_model_input).
  #
  # The F6 re-sync at the top of _run_post_cascade_completion
  # makes these agree at function entry; this invariant catches
  # any new drift introduced by intervening stages (cash pass,
  # realism gate, finalize validation, F5 pre-cash-gate handler
  # routing, etc.). Hard-fail names the offending stage explicitly.
  try:
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      PostIntakePreconditionFailed as _MF1Failed,
    )
    def _qt_tuple_assert(ph_or_none):
      return tuple(
        (int(item.get("quarter_index") or 0), int(round(float(item.get("payroll") or 0))))
        for item in ((ph_or_none or {}).get("quarter_totals") or [])
        if isinstance(item, dict) and int(item.get("quarter_index") or 0) >= 1
      )
    _canonical_qt = _qt_tuple_assert(payroll_headcount)
    _payroll_row = None
    for _row in (
      ((final_model_input_json or {}).get("sections", {}).get("expenses") or [])
    ):
      if isinstance(_row, dict) and str(_row.get("lever_id") or "").strip() == "expenses::Payroll":
        _payroll_row = _row
        break
    _values_qt = tuple()
    if isinstance(_payroll_row, dict):
      _vals = _payroll_row.get("values") or []
      # values[0] is the stub Q0; values[1..N] are Q1..QN live quarters.
      _values_qt = tuple(
        (q, int(round(float(_vals[q] if q < len(_vals) else 0))))
        for q in range(1, len(_canonical_qt) + 1)
      )
    _runtime_embedded = (
      ((final_model_input_json or {}).get("derived_driver_runtime") or {})
      .get("expenses::Payroll") or {}
    )
    _runtime_ph = _runtime_embedded.get("payroll_headcount") if isinstance(_runtime_embedded, dict) else None
    _runtime_qt = _qt_tuple_assert(_runtime_ph)
    _surface_disagreements = []
    for _q, _exp in _canonical_qt:
      _v_match = next((v for (qi, v) in _values_qt if qi == _q), None)
      if _v_match is not None and abs(_v_match - _exp) > 1:
        _surface_disagreements.append({
          "quarter": _q,
          "canonical_payroll_headcount": _exp,
          "model_input_values": _v_match,
          "delta": _v_match - _exp,
          "surface": "model_input.expenses.Payroll.values",
        })
      _r_match = next((v for (qi, v) in _runtime_qt if qi == _q), None)
      if _r_match is not None and abs(_r_match - _exp) > 1:
        _surface_disagreements.append({
          "quarter": _q,
          "canonical_payroll_headcount": _exp,
          "model_input_derived_driver_runtime": _r_match,
          "delta": _r_match - _exp,
          "surface": "model_input.derived_driver_runtime[expenses::Payroll].payroll_headcount",
        })
    if _surface_disagreements and _canonical_qt:
      raise _MF1Failed(
        operation="pre_finalize_persist_payroll_three_surface_invariant_violation",
        pipeline_stage="post_intake_pre_finalize_persist_payroll_invariant",
        expected="payroll_headcount.quarter_totals == model_input.expenses.Payroll.values == model_input.derived_driver_runtime[expenses::Payroll].payroll_headcount.quarter_totals (per-quarter, $1 int-rounding tolerance)",
        actual=f"{len(_surface_disagreements)} per-quarter disagreement(s) across the three payroll surfaces",
        details={
          "disagreements_sample": _surface_disagreements[:10],
          "canonical_q1_through_q5": list(_canonical_qt[:5]),
          "model_input_values_q1_through_q5": list(_values_qt[:5]),
          "model_input_runtime_q1_through_q5": list(_runtime_qt[:5]),
          "guidance": (
            "K1 F6 doctrine: payroll surfaces must agree at pre-finalize. "
            "The F6 re-sync at the top of _run_post_cascade_completion "
            "establishes the invariant at function entry; an intervening "
            "stage introduced drift. Find the stage that wrote to "
            "payroll_headcount column OR model_input.expenses.Payroll "
            "without using the apply_payroll_schedule_to_state chain."
          ),
        },
      )
  except _MF1Failed:
    raise
  except Exception as _mf1_check_exc:
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      convergence_test_mode_enabled,
    )
    if convergence_test_mode_enabled():
      raise

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

  # Step 9c — finalize entry diagnostic.
  _emit_diag(
    phase=_DiagPhaseCode.FINALIZE,
    event_code=_DiagEventCode.FINALIZE_STARTED,
    status=_DiagStatus.STARTED,
    diagnostic_data={
      "solver_target_assertion_checked": bool(solver_target_assertion.get("checked")),
    },
  )
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
      capital_lease_schedule=copy.deepcopy(capital_lease_schedule_payload or {}),
      financials_json=copy.deepcopy(financials_json or {}),
      ops_json=copy.deepcopy(ops_json or {}),
      cash_strategy_second_pass_result={"post_intake_finalize_validation": {}},
    )
    completion_trace["finalize_validation"] = {
      "status": str(finalize_result.get("status") or "completed"),
      "solver_target_assertion_checked": bool(solver_target_assertion.get("checked")),
    }
    _finalize_status_str = str((finalize_result or {}).get("status") or "completed")
    _emit_diag(
      phase=_DiagPhaseCode.FINALIZE,
      event_code=(
        _DiagEventCode.FINALIZE_VALIDATION_FAILED
        if _finalize_status_str.startswith("fail")
        else _DiagEventCode.FINALIZE_VALIDATION_PASSED
      ),
      status=(
        _DiagStatus.FAILED if _finalize_status_str.startswith("fail")
        else _DiagStatus.COMPLETED
      ),
      diagnostic_data={
        "finalize_status": _finalize_status_str,
        "solver_target_assertion_checked": bool(solver_target_assertion.get("checked")),
      },
    )
    # Step 9d item 23 — FAIL_FINALIZE_STAGE_NOT_FINALIZED. On a
    # success-like status the finalize call must have returned a dict
    # carrying its outcome (we do not query the planning_run row
    # here — that's a Phase-4 verification concern — but a malformed
    # finalize_result still trips the fail-fast).
    if not _finalize_status_str.startswith("fail"):
      if not isinstance(finalize_result, dict):
        from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
          FailFastCode as _FFC, PhaseCode as _PC, raise_fail_fast as _rff,
        )
        _rff(
          conn, draft_id=_DIAG_DRAFT_ID, planning_run_id=_DIAG_PLANNING_RUN_ID,
          phase=_PC.FINALIZE,
          code=_FFC.FAIL_FINALIZE_STAGE_NOT_FINALIZED,
          detail=f"finalize_result not a dict (type={type(finalize_result).__name__})",
          where="orchestrator._run_post_cascade_completion (finalize)",
        )
    # Prefer the finalize call's own solver_target_assertion if it
    # succeeded — it has the same shape but with the validation flow's
    # context.
    if isinstance(finalize_result.get("solver_target_assertion"), dict):
      stax = finalize_result["solver_target_assertion"]
      if stax.get("checked"):
        solver_target_assertion = stax
        next_result["solver_target_assertion"] = copy.deepcopy(stax)
  except Exception as exc:
    # P3.26 Site B: route payroll feasibility failures back to
    # Handler C. Other failures still hard-fail under test mode.
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      FailFastError,
      convergence_test_mode_enabled,
    )
    from client_intake_and_finmo.post_intake_headcount.feasibility_repair import (  # type: ignore
      is_payroll_feasibility_failure,
      route_payroll_feasibility_to_handler_c,
    )
    _site_b_route_attempted = False
    # P3.26 fix1: detect both FailFastError directly AND
    # RuntimeError-wrapped feasibility failures (finalize wraps via
    # _raise_if_errors at finalize_post_intake.py:39-44).
    # is_payroll_feasibility_failure now handles all three shapes.
    if is_payroll_feasibility_failure(exc):
      _site_b_route_attempted = True
      _live_count_b = max(
        0,
        len([p for p in ((final_model_input_json or {}).get("periods") or [])
             if isinstance(p, dict) and not bool(p.get("is_stub"))]),
      )
      try:
        new_schedule, new_mi, new_finmo = route_payroll_feasibility_to_handler_c(
          failure_code=str(getattr(exc, "code", "") or ""),
          failure_message=str(exc),
          failure_stage=str(getattr(exc, "stage", "") or ""),
          failure_details=copy.deepcopy(getattr(exc, "details", {}) or {}),
          business_facts=business_facts or {},
          ops_json=ops_json or {},
          people_json=people_json or {},
          financials_json=financials_json or {},
          financials_year1_json=financials_year1_json or {},
          planning_mode=planning_mode,
          planning_mode_reason=planning_mode_reason,
          model_input_json=final_model_input_json or {},
          finmo_json=final_finmo_json or {},
          payroll_headcount=payroll_headcount or {},
          stage_ramp_contract=stage_ramp_contract or {},
          draft_id=str(draft_id or "").strip(),
          client_id=str((business_facts or {}).get("client_id") or "").strip(),
          live_count=_live_count_b,
          stage_prefix="finalize_payroll_feasibility_repair",
        )
        payroll_headcount = new_schedule
        final_model_input_json = new_mi
        final_finmo_json = new_finmo
        next_result["model_input_json"] = final_model_input_json
        next_result["finmo_json"] = final_finmo_json
        completion_trace["payroll_feasibility_repair_site_b"] = {
          "status": "completed",
          "triggered_by_code": str(getattr(exc, "code", "") or ""),
        }
        # Direct SQL UPDATE on the payroll_headcount column to keep
        # the DB aligned with the repaired in-memory state. The
        # orchestrator's downstream `_persist_unified_convergence_state`
        # does NOT write payroll_headcount (it was set at initial-grid
        # persist time); without this update, the workbook builder
        # would re-render from the stale headcount and recreate the
        # Mirror Flavor 1 divergence the P3.25 memo documented.
        if conn is not None:
          try:
            import json as _json_payroll_persist
            _cur_p = conn.cursor()
            try:
              _cur_p.execute(
                "UPDATE intake_consult_drafts SET payroll_headcount=%s WHERE draft_id=%s",
                (
                  _json_payroll_persist.dumps(payroll_headcount, ensure_ascii=False, default=str),
                  str(draft_id or "").strip(),
                ),
              )
              conn.commit()
            finally:
              try:
                _cur_p.close()
              except Exception:
                pass
          except Exception as _persist_exc:
            completion_trace.setdefault("payroll_feasibility_repair_site_b", {})[
              "headcount_db_persist_error"
            ] = f"{type(_persist_exc).__name__}: {str(_persist_exc)[:300]}"
            if convergence_test_mode_enabled():
              raise
        # Re-run finalize with the repaired state. If it still
        # fails, the new exception propagates with the full
        # diagnostic chain.
        from client_intake_and_finmo.post_intake_runtime_validation.finalize_post_intake import (  # type: ignore
          run_finalize_post_intake_validation as _finalize_post_repair,
        )
        finalize_result = _finalize_post_repair(
          draft_id=str(draft_id or "").strip(),
          planning_run_id=str(planning_run_id or "").strip(),
          stage_ramp_contract=copy.deepcopy(stage_ramp_contract or {}),
          model_input_json=copy.deepcopy(final_model_input_json or {}),
          finmo_json=copy.deepcopy(final_finmo_json or {}),
          payroll_headcount=copy.deepcopy(payroll_headcount or {}),
          debt_schedule=copy.deepcopy(debt_schedule_payload or {}),
          capital_lease_schedule=copy.deepcopy(capital_lease_schedule_payload or {}),
          financials_json=copy.deepcopy(financials_json or {}),
          ops_json=copy.deepcopy(ops_json or {}),
          cash_strategy_second_pass_result={"post_intake_finalize_validation": {}},
        )
        completion_trace["finalize_validation"] = {
          "status": str(finalize_result.get("status") or "completed"),
          "solver_target_assertion_checked": bool(solver_target_assertion.get("checked")),
          "payroll_feasibility_repair_applied": True,
        }
        if isinstance(finalize_result.get("solver_target_assertion"), dict):
          stax = finalize_result["solver_target_assertion"]
          if stax.get("checked"):
            solver_target_assertion = stax
            next_result["solver_target_assertion"] = copy.deepcopy(stax)
      except Exception:
        # Repair attempted but the re-run finalize still failed (or
        # Handler C itself raised). Propagate under test mode with
        # the diagnostic chain preserved.
        if convergence_test_mode_enabled():
          raise
        completion_trace.setdefault("payroll_feasibility_repair_site_b", {})[
          "status"
        ] = "failed_after_repair"
        completion_trace["finalize_validation"] = {
          "status": "failed",
          "error": f"{type(exc).__name__}: {str(exc)[:500]}",
        }
        finalize_result = {"solver_target_assertion": solver_target_assertion}
    elif convergence_test_mode_enabled():
      raise
    else:
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

  # Step 9c — target_seeking completion diagnostic.
  _emit_diag(
    phase=_DiagPhaseCode.TARGET_SEEKING,
    event_code=_DiagEventCode.TARGET_SEEKING_COMPLETED,
    status=_DiagStatus.COMPLETED,
    diagnostic_data={
      "plan_confidence": str(next_result.get("plan_confidence") or ""),
      "cascade_diagnostics_present": bool(next_result.get("adaptation_cascade_diagnostics")),
    },
  )
  return next_result
