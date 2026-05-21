"""Phase 9 P3.5 — Mini-FINMO computation for the GPT tool-calling
session.

`compute_trajectory_from_anchors(anchors, operating_context)` accepts
GPT's proposed driver anchors at Q1, Q11, Q20 and returns the resulting
20-quarter EBITDA trajectory plus pass/fail for the universal viability
checks. This is the tool GPT calls to verify his anchors produce a
viable plan BEFORE committing to a final answer — eliminating the
structural gap between his anchored target and FINMO's computed result
that the retired Call 1 / Call 2 / iteration pattern had to close after
the fact via diagnostic feedback.

Design choice: parity with full FINMO is by construction. The function
deep-copies the operator's model_input, writes the anchors using the
same writer the post-commit handler uses (which interpolates Q1->Q11->Q20
and applies FINMO contracts: skip Capacity for labor-driven, integer-
round capacity, clip utilization to <= 0.84), and rebuilds FINMO via the
same build_finmo callable the orchestrator uses. The viability checks
read FINMO's actual revenue/EBITDA outputs — there is no separate
mini-implementation that could diverge from full FINMO's math.

Universal across NAICS / stage / archetype: the same function runs for
every business; differences flow from the operating model + intake
state, not from code branches.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Callable, Dict, List, Optional


logger = logging.getLogger(__name__)


# Quarter indices used for trajectory check-points.
_Q1, _Q5, _Q11, _Q15, _Q20 = 1, 5, 11, 15, 20

# Phase 9 P3.8 — tolerance for the ebitda_margin_q20_holds_or_improves_vs_q11
# check. Q20 EBITDA margin must be at most 1pp below Q11 (1pp is a
# math-noise buffer, not a doctrinal allowance for decline). Matches the
# realism gate's universal-viability threshold exactly.
_EBITDA_Q20_HOLDS_OR_IMPROVES_TOLERANCE = 0.01


def _row_for_quarter(
  finmo_json: Dict[str, Any],
  quarter_index: int,
) -> Optional[Dict[str, Any]]:
  for row in (finmo_json or {}).get("quarter_rows") or []:
    if not isinstance(row, dict):
      continue
    try:
      qi = int(float(row.get("quarter_index") or 0))
    except Exception:
      continue
    if qi == int(quarter_index):
      return row
  return None


def _ebitda_margin(row: Optional[Dict[str, Any]]) -> Optional[float]:
  if not isinstance(row, dict):
    return None
  rev = float(row.get("revenue") or 0.0)
  if rev <= 0:
    return None
  return float(row.get("ebitda") or 0.0) / rev


def _gross_margin(row: Optional[Dict[str, Any]]) -> Optional[float]:
  if not isinstance(row, dict):
    return None
  rev = float(row.get("revenue") or 0.0)
  if rev <= 0:
    return None
  cogs = float(row.get("cost_of_goods_sold") or 0.0)
  return (rev - cogs) / rev


def _fixed_cost_burden(row: Optional[Dict[str, Any]]) -> Optional[float]:
  """Fraction (payroll + lease/rent) / revenue. Used for the
  fixed-cost-reduction-or-scaled-by-Q11 check.
  """
  if not isinstance(row, dict):
    return None
  rev = float(row.get("revenue") or 0.0)
  if rev <= 0:
    return None
  payroll = float(row.get("payroll") or 0.0)
  lease = float(
    row.get("lease_rent")
    or row.get("rent")
    or row.get("lease")
    or 0.0
  )
  return (payroll + lease) / rev


def _stage_ramp_rows_by_quarter(
  stage_ramp_contract: Optional[Dict[str, Any]],
) -> Dict[int, Dict[str, Any]]:
  """Phase 9 P3.32 K11.1 — index stage_ramp_contract quarter rows by
  quarter_index. Accepts both the long-form keys
  (`revenue_qoq_max`, `cogs_percent_of_revenue_max`, etc.) and the
  short-form keys (`rev_max`, `cogs_max`, etc.) — the H4-authored
  contract uses long-form; the Python deterministic builder uses
  short-form; both shapes appear in sweep evidence.
  """
  out: Dict[int, Dict[str, Any]] = {}
  contract = stage_ramp_contract if isinstance(stage_ramp_contract, dict) else {}
  for row in contract.get("quarter_ramp_grid") or []:
    if not isinstance(row, dict):
      continue
    quarter_index = row.get("quarter_index")
    if quarter_index is None:
      quarter_index = row.get("q")
    try:
      quarter_index = int(quarter_index)
    except (TypeError, ValueError):
      continue
    if quarter_index < 1 or quarter_index > 20:
      continue
    out[quarter_index] = row
  return out


def _bound_value(row: Dict[str, Any], *keys: str) -> Optional[float]:
  for key in keys:
    if key in row and row[key] is not None:
      try:
        return float(row[key])
      except (TypeError, ValueError):
        continue
  return None


def _ni_margin(row: Optional[Dict[str, Any]]) -> Optional[float]:
  if not isinstance(row, dict):
    return None
  rev = float(row.get("revenue") or 0.0)
  if rev <= 0:
    return None
  return float(row.get("net_income") or 0.0) / rev


def _ratio_of_revenue(row: Optional[Dict[str, Any]], field: str) -> Optional[float]:
  if not isinstance(row, dict):
    return None
  rev = float(row.get("revenue") or 0.0)
  if rev <= 0:
    return None
  value = row.get(field)
  if value is None:
    return None
  try:
    return float(value) / rev
  except (TypeError, ValueError):
    return None


def _eval_stage_ramp_coherence_checks(
  finmo_json: Dict[str, Any],
  stage_ramp_contract: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  """Phase 9 P3.32 K11.1 — check actual FINMO trajectory against
  H4-authored per-quarter bounds. Returns:
    {
      "checks": {"stage_ramp_rev_max_respected": "PASS"|"FAIL"|"SKIPPED",
                 "stage_ramp_cogs_max_respected": ...,
                 "stage_ramp_marketing_max_respected": ...,
                 "stage_ramp_rd_max_respected": ...,
                 "stage_ramp_ga_max_respected": ...,
                 "stage_ramp_ni_floor_respected": ...,
                 "stage_ramp_max_util_respected": ...},
      "violations": [{"quarter_index": ..., "field": ...,
                       "actual": ..., "bound": ...,
                       "bound_kind": "max"|"floor"|"target_min"}],
    }

  When ``stage_ramp_contract`` is missing or empty (or quarter_ramp_grid
  is empty), all checks are SKIPPED and the viability_checks aggregate
  ignores them. This preserves the pre-K11 behavior for any call site
  that has not threaded the contract.

  Universal across NAICS / stage / archetype. The bounds come from
  H4's per-quarter authoring; this function applies them mechanically.

  Tolerance: bounds are checked at 2dp rounding to match the
  finalize-validator at fail_fast.py:506 — actual_growth rounded to
  2 decimals must be <= allowed_growth rounded to 2 decimals. Avoids
  flagging float-noise violations.
  """
  ramp_rows = _stage_ramp_rows_by_quarter(stage_ramp_contract)
  if not ramp_rows:
    return {
      "checks": {
        "stage_ramp_rev_max_respected": "SKIPPED",
        "stage_ramp_cogs_max_respected": "SKIPPED",
        "stage_ramp_marketing_max_respected": "SKIPPED",
        "stage_ramp_rd_max_respected": "SKIPPED",
        "stage_ramp_ga_max_respected": "SKIPPED",
        "stage_ramp_ni_floor_respected": "SKIPPED",
        "stage_ramp_max_util_respected": "SKIPPED",
      },
      "violations": [],
    }
  finmo_rows_by_q: Dict[int, Dict[str, Any]] = {}
  for row in (finmo_json or {}).get("quarter_rows") or []:
    if not isinstance(row, dict):
      continue
    try:
      q = int(float(row.get("quarter_index") or 0))
    except Exception:
      continue
    if 1 <= q <= 20:
      finmo_rows_by_q[q] = row

  violations: List[Dict[str, Any]] = []
  fields_violated: Dict[str, bool] = {}

  def _record_violation(*, q: int, field: str, actual: float, bound: float, bound_kind: str) -> None:
    violations.append(
      {
        "quarter_index": q,
        "field": field,
        "actual": round(float(actual), 6),
        "bound": round(float(bound), 6),
        "bound_kind": bound_kind,
      }
    )
    fields_violated[field] = True

  # Revenue growth (rev_max). Iterate Q2..Q20 since Q1 has no prior.
  for q in range(2, 21):
    cur_row = finmo_rows_by_q.get(q) or {}
    prev_row = finmo_rows_by_q.get(q - 1) or {}
    ramp_row = ramp_rows.get(q) or {}
    cur_rev = float(cur_row.get("revenue") or 0.0)
    prev_rev = float(prev_row.get("revenue") or 0.0)
    if prev_rev <= 0.0 or cur_rev <= 0.0:
      continue
    growth_ratio = cur_rev / prev_rev
    rev_max_rate = _bound_value(ramp_row, "revenue_qoq_max", "rev_max")
    if rev_max_rate is not None and rev_max_rate > 0.0:
      allowed_ratio = 1.0 + float(rev_max_rate)
      # Match finalize validator's 2-decimal rounding so we don't
      # flag float-noise.
      actual_2dp = round(growth_ratio, 2)
      allowed_2dp = round(allowed_ratio, 2)
      if actual_2dp > allowed_2dp:
        _record_violation(
          q=q,
          field="rev_max",
          actual=growth_ratio - 1.0,
          bound=rev_max_rate,
          bound_kind="max",
        )

  # Ratio ceilings (cogs_max, marketing_max, rd_max, ga_max,
  # max_util). Iterate Q1..Q20.
  ratio_field_map = [
    ("cogs_max", ("cogs_percent_of_revenue_max", "cogs_max"), "cost_of_goods_sold"),
    ("marketing_max", ("marketing_percent_of_revenue_max", "marketing_max"), "marketing"),
    ("rd_max", ("rd_percent_of_revenue_max", "rd_max"), "research_and_development"),
    ("ga_max", ("g_and_a_percent_of_revenue_max", "ga_max"), "general_and_administrative"),
  ]
  for q in range(1, 21):
    finmo_row = finmo_rows_by_q.get(q) or {}
    ramp_row = ramp_rows.get(q) or {}
    if not finmo_row or not ramp_row:
      continue
    for check_field, contract_keys, finmo_key in ratio_field_map:
      bound = _bound_value(ramp_row, *contract_keys)
      if bound is None or bound <= 0.0:
        continue
      actual_ratio = _ratio_of_revenue(finmo_row, finmo_key)
      if actual_ratio is None:
        continue
      # Allow small tolerance (0.5pp) for float noise; matches H4's
      # validator tolerances.
      if actual_ratio > float(bound) + 0.005:
        _record_violation(
          q=q,
          field=check_field,
          actual=actual_ratio,
          bound=bound,
          bound_kind="max",
        )

  # NI floor — universal_viability_doctrine threshold. ni_floor=0
  # in early quarters means "NI margin >= 0%"; later quarters may
  # have ni_floor >= 0.05 or 0.07.
  for q in range(1, 21):
    ramp_row = ramp_rows.get(q) or {}
    floor = _bound_value(ramp_row, "net_income_margin_floor", "ni_floor")
    if floor is None:
      continue
    ni = _ni_margin(finmo_rows_by_q.get(q))
    if ni is None:
      continue
    # Allow small tolerance for float noise (0.5pp).
    if ni + 0.005 < float(floor):
      _record_violation(
        q=q,
        field="ni_floor",
        actual=ni,
        bound=floor,
        bound_kind="floor",
      )

  # Utilization cap (max_util). Read utilization_rate from model_input
  # via finmo if present; otherwise from the finmo row.
  for q in range(1, 21):
    ramp_row = ramp_rows.get(q) or {}
    cap = _bound_value(ramp_row, "utilization_cap", "max_util")
    if cap is None or cap <= 0.0:
      continue
    finmo_row = finmo_rows_by_q.get(q) or {}
    util = finmo_row.get("utilization_rate") or finmo_row.get("utilization")
    if util is None:
      continue
    try:
      util_value = float(util)
    except (TypeError, ValueError):
      continue
    if util_value > float(cap) + 0.005:
      _record_violation(
        q=q,
        field="max_util",
        actual=util_value,
        bound=cap,
        bound_kind="max",
      )

  def _verdict(field: str) -> str:
    return "FAIL" if fields_violated.get(field) else "PASS"

  return {
    "checks": {
      "stage_ramp_rev_max_respected": _verdict("rev_max"),
      "stage_ramp_cogs_max_respected": _verdict("cogs_max"),
      "stage_ramp_marketing_max_respected": _verdict("marketing_max"),
      "stage_ramp_rd_max_respected": _verdict("rd_max"),
      "stage_ramp_ga_max_respected": _verdict("ga_max"),
      "stage_ramp_ni_floor_respected": _verdict("ni_floor"),
      "stage_ramp_max_util_respected": _verdict("max_util"),
    },
    "violations": violations,
  }


def _eval_viability_checks(
  finmo_json: Dict[str, Any],
  stage_ramp_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  q1_row = _row_for_quarter(finmo_json, _Q1)
  q5_row = _row_for_quarter(finmo_json, _Q5)
  q11_row = _row_for_quarter(finmo_json, _Q11)
  q15_row = _row_for_quarter(finmo_json, _Q15)
  q20_row = _row_for_quarter(finmo_json, _Q20)

  q1_em = _ebitda_margin(q1_row)
  q5_em = _ebitda_margin(q5_row)
  q11_em = _ebitda_margin(q11_row)
  q15_em = _ebitda_margin(q15_row)
  q20_em = _ebitda_margin(q20_row)

  q1_gm = _gross_margin(q1_row)
  q5_gm = _gross_margin(q5_row)
  q11_gm = _gross_margin(q11_row)
  q20_gm = _gross_margin(q20_row)

  q1_fcb = _fixed_cost_burden(q1_row)
  q11_fcb = _fixed_cost_burden(q11_row)

  # Universal viability checks GPT can verify pre-commit. The cash-side
  # check (loss_window_funded_through_q5) is left to the cash strategy
  # which runs after this handler — GPT is told that explicitly in the
  # system prompt so he doesn't try to hit it here.

  ebitda_positive_by_q11 = (
    q11_em is not None and q11_em >= 0.0
  )
  ebitda_recovery_trend_q5_q11 = (
    q5_em is not None and q11_em is not None and q11_em > q5_em
  )
  ebitda_margin_q20_holds_or_improves_vs_q11 = (
    q11_em is not None
    and q20_em is not None
    and q20_em >= q11_em - _EBITDA_Q20_HOLDS_OR_IMPROVES_TOLERANCE
  )
  # Gross margin "supports" EBITDA recovery: Q11 GM not lower than
  # Q5 GM (gross margin stable or improving across the recovery window).
  gross_margin_supports_ebitda_recovery = (
    q5_gm is not None and q11_gm is not None and q11_gm >= q5_gm
  )
  # Fixed-cost burden reduced or scaled by Q11.
  fixed_cost_burden_reduced_or_scaled_by_q11 = (
    q1_fcb is not None and q11_fcb is not None and q11_fcb < q1_fcb
  )

  checks = {
    "ebitda_positive_by_q11": (
      "PASS" if ebitda_positive_by_q11 else "FAIL"
    ),
    "ebitda_recovery_trend_q5_q11": (
      "PASS" if ebitda_recovery_trend_q5_q11 else "FAIL"
    ),
    "ebitda_margin_q20_holds_or_improves_vs_q11": (
      "PASS" if ebitda_margin_q20_holds_or_improves_vs_q11 else "FAIL"
    ),
    "gross_margin_supports_ebitda_recovery": (
      "PASS" if gross_margin_supports_ebitda_recovery else "FAIL"
    ),
    "fixed_cost_burden_reduced_or_scaled_by_q11": (
      "PASS" if fixed_cost_burden_reduced_or_scaled_by_q11 else "FAIL"
    ),
  }
  # Phase 9 P3.32 K11.1 — fold stage_ramp_contract coherence checks
  # into the viability_checks aggregate. SKIPPED entries (when the
  # contract is absent) are treated as PASS for the all_pass logic
  # so pre-K11 call sites without contract threading keep their
  # behavior.
  stage_ramp_outcome = _eval_stage_ramp_coherence_checks(
    finmo_json,
    stage_ramp_contract,
  )
  for stage_field, verdict in (stage_ramp_outcome.get("checks") or {}).items():
    checks[stage_field] = verdict
  stage_ramp_violations = stage_ramp_outcome.get("violations") or []
  def _is_pass_or_skipped(v: str) -> bool:
    return str(v).upper() in {"PASS", "SKIPPED"}
  checks["all_pass"] = all(
    _is_pass_or_skipped(v) for k, v in checks.items() if k != "all_pass"
  )
  return {
    "ebitda_margins": {
      "q1": q1_em, "q5": q5_em, "q11": q11_em, "q15": q15_em, "q20": q20_em,
    },
    "gross_margin_percents": {
      "q1": q1_gm, "q5": q5_gm, "q11": q11_gm, "q20": q20_gm,
    },
    "revenues": {
      "q1": float(q1_row.get("revenue") or 0.0) if q1_row else None,
      "q11": float(q11_row.get("revenue") or 0.0) if q11_row else None,
      "q20": float(q20_row.get("revenue") or 0.0) if q20_row else None,
    },
    "ebitda_dollars": {
      "q1": float(q1_row.get("ebitda") or 0.0) if q1_row else None,
      "q11": float(q11_row.get("ebitda") or 0.0) if q11_row else None,
      "q20": float(q20_row.get("ebitda") or 0.0) if q20_row else None,
    },
    "viability_checks": checks,
    "stage_ramp_violations": stage_ramp_violations,
  }


def compute_trajectory_from_anchors(
  anchors: Dict[str, Dict[str, float]],
  operating_context: Dict[str, Any],
) -> Dict[str, Any]:
  """Compute the 20-quarter EBITDA trajectory that would result from
  GPT's proposed driver anchors. Returns a structured result with
  EBITDA margins at key quarters, revenues, EBITDA dollars, gross
  margin percents, and pass/fail for the 5 P&L-side viability checks
  (loss_window_funded_through_q5 is cash-side and evaluated by the
  cash strategy after this handler).

  Parameters
  ----------
  anchors
    GPT's proposed driver anchors. Shape (Phase 9 P3.32 K1 — no
    payroll_dollars_per_quarter; Handler C is canonical Payroll
    writer):
      {"unit_price": {"q1": ..., "q11": ..., "q20": ...},
       "units_per_period_capacity": {...},
       "utilization_rate": {...},
       "cogs_percent_of_revenue": {...},
       "marketing_percent_of_revenue": {...},
       "sga_percent_of_revenue": {...},
       "r_and_d_percent_of_revenue": {...},
       "working_capital_drivers": {                  # Phase 9 P3.6
         "accounts_receivable_days": <number>,
         "accounts_payable_days": <number>,
         "inventory_days": <number>,
         "deferred_revenue_percent_of_revenue": <decimal>,
         "prepaid_expenses_percent_of_revenue": <decimal>
       }}
    Working capital drivers are SINGLE values per driver (no Q1/Q11/Q20
    ramp) — operationally stable across the planning horizon; the
    writer stamps them uniformly across all 20 live quarters.
  operating_context
    {
      "model_input_template": Dict[str, Any]    # deepcopy source
      "build_finmo": Callable                    # model_input -> finmo_json
    }

  The function is non-mutating with respect to the operating_context's
  model_input_template (it deep-copies before writing). The returned
  dict carries everything GPT needs to decide whether to commit or
  iterate.
  """
  # Phase 9 P3.10 Commit 3 — mini-FINMO is a probe; an error here is
  # NOT "anchor rejected by viability checks" — it's a code bug (writer
  # contract violation or FINMO math failure on inputs mini-FINMO is
  # supposed to accept). Previously the error masqueraded as a probe
  # with all_pass=False, GPT iterated against the phantom, and the
  # real failure stayed invisible.
  from client_intake_and_finmo.fail_fast.common import (  # type: ignore
    PostIntakePreconditionFailed,
    convergence_test_mode_enabled,
  )

  template = operating_context.get("model_input_template")
  build_finmo = operating_context.get("build_finmo")
  if not isinstance(template, dict) or not callable(build_finmo):
    if convergence_test_mode_enabled():
      raise PostIntakePreconditionFailed(
        operation="mini_finmo_compute_trajectory_invalid_context",
        pipeline_stage="phase_9_p3_9_tool_calling_session",
        expected="operating_context has dict model_input_template + callable build_finmo",
        actual=(
          f"template_is_dict={isinstance(template, dict)} "
          f"build_finmo_callable={callable(build_finmo)}"
        ),
        details={},
      )
    return {
      "error": "operating_context_invalid",
      "viability_checks": {"all_pass": False},
    }

  # Lazy-import to avoid circular deps when handler.py is imported in
  # contexts where the orchestrator hasn't finished wiring.
  from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (  # type: ignore
    _write_gpt_authored_per_quarter_values,
  )

  probe_input = copy.deepcopy(template)
  try:
    _write_gpt_authored_per_quarter_values(
      model_input=probe_input,
      driver_anchors=anchors or {},
      provenance_tag="tool_call_probe",
    )
  except Exception as exc:
    if convergence_test_mode_enabled():
      raise PostIntakePreconditionFailed(
        operation="mini_finmo_writer_failed",
        pipeline_stage="phase_9_p3_9_tool_calling_session",
        expected="writer applies GPT-authored anchors without raising",
        actual=f"{type(exc).__name__}: {str(exc)[:200]}",
        details={"anchor_keys": sorted(list((anchors or {}).keys()))},
        cause=exc,
      ) from exc
    return {
      "error": f"writer_failed: {type(exc).__name__}: {str(exc)[:200]}",
      "viability_checks": {"all_pass": False},
    }

  try:
    finmo = build_finmo(probe_input)
  except Exception as exc:
    if convergence_test_mode_enabled():
      raise PostIntakePreconditionFailed(
        operation="mini_finmo_build_finmo_failed",
        pipeline_stage="phase_9_p3_9_tool_calling_session",
        expected="build_finmo(writer-mutated probe input) returns FINMO dict",
        actual=f"{type(exc).__name__}: {str(exc)[:200]}",
        details={"anchor_keys": sorted(list((anchors or {}).keys()))},
        cause=exc,
      ) from exc
    return {
      "error": f"finmo_rebuild_failed: {type(exc).__name__}: {str(exc)[:200]}",
      "viability_checks": {"all_pass": False},
    }

  # Phase 9 P3.32 K11.1 — stage_ramp_contract coherence checks
  # apply when the contract was threaded into operating_context.
  # Absent contract (None or {}) skips the new checks; pre-K11
  # behavior preserved.
  return _eval_viability_checks(
    finmo or {},
    stage_ramp_contract=operating_context.get("stage_ramp_contract"),
  )
