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


def _eval_viability_checks(finmo_json: Dict[str, Any]) -> Dict[str, Any]:
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
  checks["all_pass"] = all(v == "PASS" for v in checks.values())
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
    GPT's proposed driver anchors. Shape:
      {"unit_price": {"q1": ..., "q11": ..., "q20": ...},
       "units_per_period_capacity": {...},
       "utilization_rate": {...},
       "payroll_dollars_per_quarter": {...},
       "cogs_percent_of_revenue": {...},
       "marketing_percent_of_revenue": {...},
       "sga_percent_of_revenue": {...},
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

  return _eval_viability_checks(finmo or {})
