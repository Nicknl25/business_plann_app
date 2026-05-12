"""Phase 9 P3.5 — GPT exhaustion handler orchestrator.

Public entry point: ``run_gpt_exhaustion_handler``. Called by the
post-cascade orchestrator when ``run_restoration_loop`` returns
``RestorationStatus.EXHAUSTED``. Lives between the restoration loop
(operating-side deterministic algebra) and the cash strategy
(financing-side, untouched here).

Pipeline inside this handler (Phase 9 P3.5 tool-calling pattern):
  1. Build operating context (Q1 actual state, capacity-driver detection,
     fixed-rent computation, build_finmo callable closure).
  2. Run the GPT tool-calling session: GPT proposes driver anchors and
     calls compute_full_trajectory(anchors) to verify the EBITDA path
     the system would compute. GPT iterates against the tool result
     up to MAX_TOOL_CALLS times, then commits a final answer.
  3. Path-engine-interpolate the committed anchors to 20 quarters.
  4. Write per-driver per-quarter values into model_input with
     provenance tags (FINMO contract compliance: skip Capacity for
     labor-driven businesses, integer-round capacity, clip utilization).
  5. Rebuild FINMO so the rest of the post-cascade tail sees the
     GPT-authored operating model.
  6. Determine which realism metrics to mute for THIS draft (per-draft,
     per-metric — universal viability trajectory checks stay active).

The Call 1 / Call 2 / iteration / snap-into-place pattern is retired.
GPT verifies the math himself before committing — the structural gap
between his anchored target and FINMO's computed result no longer
exists because the tool runs full FINMO under the hood.

Cash strategy is NOT touched. It runs after this handler completes.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)


HORIZON_QUARTERS = 20

# Lever IDs the handler authors. These are the "drivers" GPT returns
# anchors for; the path engine interpolates each driver's 3 anchors into
# a 20-quarter trajectory. Universal across NAICS.
GPT_AUTHORED_LEVER_IDS: Tuple[str, ...] = (
  "revenue::Unit Price",
  "revenue::Capacity",
  "revenue::Utilization",
  "expenses::Payroll",
  "expenses::Cost of Goods Sold",
  "expenses::Marketing",
  "expenses::General & Administrative",
)

# Map GPT driver-anchor key -> lever_id for the model_input write.
_DRIVER_KEY_TO_LEVER_ID: Dict[str, str] = {
  "unit_price": "revenue::Unit Price",
  "units_per_period_capacity": "revenue::Capacity",
  "utilization_rate": "revenue::Utilization",
  "payroll_dollars_per_quarter": "expenses::Payroll",
  "cogs_percent_of_revenue": "expenses::Cost of Goods Sold",
  "marketing_percent_of_revenue": "expenses::Marketing",
  "sga_percent_of_revenue": "expenses::General & Administrative",
}


def authored_lever_ids_from_commit(
  driver_anchors: Optional[Dict[str, Any]],
) -> set:
  """Phase 9 P3.7 — Return the set of lever_ids GPT actually authored
  in this commit payload (drivers with a non-None / non-missing value).

  Used to parameterize compute_metrics_to_mute on the BS-only path:
  GPT may legitimately leave some WC drivers unset (e.g. inventory_days
  for a service business), and muting metrics referencing levers GPT
  did NOT author would silence band-checks that should still apply.
  """
  if not isinstance(driver_anchors, dict):
    return set()
  authored: set = set()
  for key, lever_id in _DRIVER_KEY_TO_LEVER_ID.items():
    if key in driver_anchors and driver_anchors.get(key) is not None:
      authored.add(lever_id)
  wc = driver_anchors.get("working_capital_drivers")
  if isinstance(wc, dict):
    for wc_key, lever_id in _WC_KEY_TO_LEVER_ID.items():
      if wc_key in wc and wc.get(wc_key) is not None:
        authored.add(lever_id)
  return authored


# Phase 9 P3.6 — GPT also authors 5 working capital drivers. These are
# operationally stable across the planning horizon, so GPT provides a
# SINGLE value per driver and the writer stamps it uniformly across all
# 20 quarters. FINMO derives current assets / current liabilities from
# these in its existing AR / Inventory / AP / prepaid / deferred-revenue
# formulas. Universal across NAICS.
GPT_AUTHORED_WORKING_CAPITAL_LEVER_IDS: Tuple[str, ...] = (
  "balance_sheet::Accounts Receivable Days",
  "balance_sheet::Accounts Payable Days",
  "balance_sheet::Inventory Days",
  "balance_sheet::Deferred Revenue (% of Revenue)",
  "balance_sheet::Prepaid Expenses (% of Revenue)",
)


# Map GPT working-capital key -> lever_id.
_WC_KEY_TO_LEVER_ID: Dict[str, str] = {
  "accounts_receivable_days": "balance_sheet::Accounts Receivable Days",
  "accounts_payable_days": "balance_sheet::Accounts Payable Days",
  "inventory_days": "balance_sheet::Inventory Days",
  "deferred_revenue_percent_of_revenue": (
    "balance_sheet::Deferred Revenue (% of Revenue)"
  ),
  "prepaid_expenses_percent_of_revenue": (
    "balance_sheet::Prepaid Expenses (% of Revenue)"
  ),
}


# Universal viability trajectory checks. These evaluate against FINMO
# outputs (revenue, EBITDA dollar amounts), not driver values, and stay
# active in the realism gate even after the handler runs.
_UNIVERSAL_VIABILITY_TRAJECTORY_METRICS = frozenset({
  "ebitda_positive_by_q11",
  "ebitda_recovery_trend_q5_q11",
  "loss_window_funded_through_q5",
  # Phase 9 P3.8 — renamed from no_post_recovery_relapse_q11_q20.
  "ebitda_margin_q20_holds_or_improves_vs_q11",
  "gross_margin_supports_ebitda_recovery",
  "fixed_cost_burden_reduced_or_scaled_by_q11",
})


class HandlerStatus(str, Enum):
  # Phase 9 P3.9 — GPT achieved viability_checks.all_pass on some tool
  # call (initial budget calls 1-5 OR extension calls 6-10). That tool
  # call's anchor arguments were committed verbatim; the post-commit
  # FINMO rebuild operates on identical inputs to mini-FINMO's verified
  # probe, so divergence is structurally impossible. Most common
  # success path.
  LANDED_VERIFIED_TOOL_CALL = "landed_verified_tool_call"
  # Hard cap (10 tool calls) reached without any all_pass. Best-effort
  # commit happened — the tool call with the highest count of passing
  # viability checks (tiebreaker: highest Q11 EBITDA margin) was used.
  # The plan is delivered with this status flagging it as marginal.
  LANDED_BEST_EFFORT_NO_ALL_PASS = "landed_best_effort_no_all_pass"
  # Phase 9 P3.10 split — pre-flight precondition (genuine: FINMO build
  # failure before the session, tool_calling_session import error,
  # post-commit FINMO rebuild raised). Under CONVERGENCE_TEST_MODE=true
  # these sites now raise PostIntakePreconditionFailed instead of
  # returning this status. The status value is preserved for prod-mode
  # callers but is the LEGACY path; new code must raise.
  FAILED_PRECONDITION = "failed_precondition"
  # Phase 9 P3.10 split — post-session result indicating no usable
  # anchors were produced (every turn errored, GPT never called the
  # tool, or network retries exhausted within the session). Under test
  # mode the session-loop receiving end will convert this to a hard
  # fail in Commit 2-3; preserved here as a distinct status so the
  # diagnostic carries the correct kind.
  FAILED_NO_USABLE_ANCHORS = "failed_no_usable_anchors"


@dataclass
class HandlerResult:
  status: HandlerStatus
  gpt_calls_made: int = 0
  q11_ebitda_target: Optional[float] = None
  q11_ebitda_actual: Optional[float] = None
  provenance: Dict[str, Any] = field(default_factory=dict)
  realism_flags_to_mute: List[str] = field(default_factory=list)
  reason: str = ""

  def to_dict(self) -> Dict[str, Any]:
    return {
      "status": (
        self.status.value
        if isinstance(self.status, HandlerStatus)
        else str(self.status)
      ),
      "gpt_calls_made": int(self.gpt_calls_made),
      "q11_ebitda_target": self.q11_ebitda_target,
      "q11_ebitda_actual": self.q11_ebitda_actual,
      "provenance": dict(self.provenance),
      "realism_flags_to_mute": list(self.realism_flags_to_mute),
      "reason": self.reason,
    }


# ---------------------------------------------------------------------------
# Q1 / Q11 actual-state extraction.
# ---------------------------------------------------------------------------


def _q1_actual_state(finmo_json: Dict[str, Any]) -> Dict[str, Any]:
  """Pull Q1 actuals from the FINMO output's quarter_rows[quarter_index=1].
  Used for the operator-baseline state that the tool-calling session
  shows GPT.
  """
  q1: Dict[str, Any] = {}
  rows = (finmo_json or {}).get("quarter_rows") or []
  for row in rows:
    if not isinstance(row, dict):
      continue
    try:
      qi = int(float(row.get("quarter_index") or 0))
    except Exception:
      continue
    if qi != 1:
      continue
    revenue = float(row.get("revenue") or 0.0)
    ebitda = float(row.get("ebitda") or 0.0)
    cogs = float(row.get("cost_of_goods_sold") or 0.0)
    payroll = float(row.get("payroll") or 0.0)
    marketing = float(
      row.get("marketing") or row.get("marketing_expense") or 0.0
    )
    sga = float(row.get("general_and_administrative") or row.get("sga") or 0.0)
    gross_profit = revenue - cogs
    em = (ebitda / revenue) if revenue else 0.0
    q1 = {
      "revenue": revenue,
      "ebitda": ebitda,
      "ebitda_margin": em,
      "cost_of_goods_sold": cogs,
      "gross_profit": gross_profit,
      "payroll": payroll,
      "marketing": marketing,
      "sga": sga,
    }
    break
  return q1


def _q11_ebitda_margin(finmo_json: Dict[str, Any]) -> Optional[float]:
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
    rev = float(row.get("revenue") or 0.0)
    if rev <= 0:
      return None
    eb = float(row.get("ebitda") or 0.0)
    return eb / rev
  return None


# ---------------------------------------------------------------------------
# Path engine — 3-anchor -> 20-quarter linear interpolation.
# ---------------------------------------------------------------------------


def interpolate_three_anchors(
  *, q1: float, q11: float, q20: float, horizon: int = HORIZON_QUARTERS,
) -> List[float]:
  """Two-segment linear ramp Q1->Q11->Q20 across ``horizon`` quarters.

  GPT-authored anchors land EXACTLY at Q1, Q11, Q20. Per-driver path-
  shape doctrine (s_curve / glidepath / etc.) is intentionally
  bypassed: GPT has authored the strategic anchors and this handler
  honors them verbatim.
  """
  h = max(1, int(horizon))
  values: List[float] = [0.0] * h
  q1f = float(q1)
  q11f = float(q11)
  q20f = float(q20)
  for q in range(h):
    if q <= 10:
      frac = q / 10.0 if h > 1 else 0.0
      values[q] = (1.0 - frac) * q1f + frac * q11f
    else:
      span = max(1, (h - 1) - 10)
      frac = (q - 10) / float(span)
      values[q] = (1.0 - frac) * q11f + frac * q20f
  return values


# ---------------------------------------------------------------------------
# Model input writer for GPT-authored drivers.
# ---------------------------------------------------------------------------


def _detect_payroll_supported_capacity(model_input: Dict[str, Any]) -> bool:
  """Return True when the Capacity row is FINMO-derived from payroll
  (capacity_driver=labor in operating_model). In that case, direct
  Capacity writes violate revenue_driver_formula_contract; the writer
  skips Capacity and lets FINMO derive it from payroll.
  """
  from client_intake_and_finmo.post_intake_target_solver.target_solver import (  # type: ignore
    _find_rows_for_lever,
  )
  capacity_rows = _find_rows_for_lever(model_input or {}, "revenue::Capacity")
  return any(
    str(r.get("derived_driver") or "").strip() == "payroll_supported_capacity"
    or isinstance(r.get("payroll_supported_capacity"), dict)
    for r in (capacity_rows or [])
  )


def _write_gpt_authored_working_capital_values(
  *,
  model_input: Dict[str, Any],
  working_capital_drivers: Dict[str, Any],
  provenance_tag: str,
) -> Dict[str, Any]:
  """Stamp each GPT-authored working capital driver as a SINGLE value
  uniformly across all 20 live quarters. These drivers are
  operationally stable across the planning horizon (AR / AP / inventory
  days, prepaid + deferred revenue ratios), so the writer treats them
  as flat across the horizon — no interpolation. Tags each write with
  the same provenance mechanism the P&L writer uses so FINMO seed-
  policy doesn't clobber.
  """
  # Phase 9 P3.10 Commit 3 — WC writer silent-skip conversions. Note
  # that `skipped_no_value` (None in WC dict) is LEGITIMATE on the
  # bs_only_path because the tool schema marks each WC field as
  # nullable — GPT may explicitly null fields it does not wish to
  # change. `skipped_non_numeric` and `skipped_no_rows` are always
  # contract violations and now raise under test mode.
  from client_intake_and_finmo.fail_fast.common import (  # type: ignore
    PostIntakePreconditionFailed,
    convergence_test_mode_enabled,
  )
  from client_intake_and_finmo.post_intake_target_solver.target_solver import (  # type: ignore
    _find_rows_for_lever,
  )
  per_driver_summary: Dict[str, Any] = {}
  test_mode_wc = convergence_test_mode_enabled()
  for wc_key, lever_id in _WC_KEY_TO_LEVER_ID.items():
    raw = (working_capital_drivers or {}).get(wc_key)
    if raw is None:
      per_driver_summary[lever_id] = {
        "status": "skipped_no_value",
        "reason": "wc_value_not_in_commit_payload",
      }
      continue
    try:
      value = float(raw)
    except Exception as exc:
      if test_mode_wc:
        raise PostIntakePreconditionFailed(
          operation="gpt_exhaustion_handler_wc_writer_non_numeric_value",
          pipeline_stage="phase_9_p3_6_wc_writer",
          expected=f"working_capital_drivers.{wc_key} is a numeric value",
          actual=f"raw_value={raw!r} ({type(raw).__name__})",
          details={"wc_key": wc_key, "lever_id": lever_id},
          cause=exc,
        ) from exc
      per_driver_summary[lever_id] = {
        "status": "skipped_non_numeric",
        "raw_value": raw,
      }
      continue

    rows = _find_rows_for_lever(model_input or {}, lever_id)
    if not rows:
      if test_mode_wc:
        raise PostIntakePreconditionFailed(
          operation="gpt_exhaustion_handler_wc_writer_no_rows_for_lever",
          pipeline_stage="phase_9_p3_6_wc_writer",
          expected=f"model_input has at least one row for {lever_id}",
          actual="no rows found",
          details={
            "wc_key": wc_key,
            "lever_id": lever_id,
            "value": value,
          },
        )
      per_driver_summary[lever_id] = {
        "status": "skipped_no_rows",
        "value": value,
      }
      continue

    for row in rows:
      vals = row.get("values")
      if not isinstance(vals, list):
        vals = [0.0] * (HORIZON_QUARTERS + 1)
        row["values"] = vals
      while len(vals) <= HORIZON_QUARTERS:
        vals.append(0.0)
      for q_idx in range(HORIZON_QUARTERS):
        live_idx = 1 + q_idx
        if live_idx < len(vals):
          vals[live_idx] = float(value)

      tag = row.get("applied_by_target_solver_quarters")
      if not isinstance(tag, dict):
        tag = {}
        row["applied_by_target_solver_quarters"] = tag
      for q_idx in range(HORIZON_QUARTERS):
        tag[str(q_idx + 1)] = {
          "target_metric": provenance_tag,
          "applied_value": float(value),
          "gpt_authored": True,
          "lever_id": lever_id,
        }

    per_driver_summary[lever_id] = {
      "status": "written",
      "value": value,
      "rows_written": len(rows),
    }
  return per_driver_summary


def _write_gpt_authored_per_quarter_values(
  *,
  model_input: Dict[str, Any],
  driver_anchors: Dict[str, Any],
  provenance_tag: str,
) -> Dict[str, Any]:
  """Walk each lever in GPT_AUTHORED_LEVER_IDS, interpolate its three
  anchors into a 20-quarter trajectory, and write per-quarter values
  into the model_input rows. Tags every authored quarter with
  ``applied_by_target_solver_quarters[q] = {"target": <provenance_tag>,
  "value": v, "gpt_authored": True}`` so:
    - the derived-driver / FINMO seed-policy shapers skip those quarters
      (existing exclusion mechanism — re-uses target-solver provenance);
    - the realism mute mechanism can find the GPT-authored drivers via
      this tag.

  FINMO contract compliance:
    - For labor-driven capacity (capacity_driver=labor; the Capacity row
      carries derived_driver=payroll_supported_capacity), skip Capacity
      writes — FINMO derives capacity from payroll, and a direct write
      would violate revenue_driver_formula_contract.
    - Clip utilization to <= 0.84 to keep writes from triggering FINMO's
      capacity-expansion branch (utilization_ceiling=0.85), which
      auto-expands capacity and clips utilization back to 0.70 — silently
      undoing the writer's outputs.
    - Round capacity per row to integer so capacity * price * util holds
      under FINMO's revenue_driver_formula_contract.

  Returns a per-driver summary used for provenance.
  """
  # Phase 9 P3.10 Commit 3 — silent-skip patterns are converted to
  # hard-fails under CONVERGENCE_TEST_MODE. The writer must succeed for
  # every anchor GPT committed. Three skip categories:
  #
  #  skipped_no_anchor — GPT did not author this driver. Legitimate
  #    for bs_only_path (P&L drivers absent by schema). For pnl_path
  #    every P&L driver is required by the tool schema, so a missing
  #    P&L anchor while OTHER P&L anchors are present means GPT broke
  #    the schema contract.
  #  skipped_non_numeric_anchor — GPT supplied a non-float value.
  #    Always a contract violation (schema requires number).
  #  skipped_no_rows — model_input has no rows for this lever_id.
  #    Always a setup/contract violation (the lever ID list and the
  #    model_input shape must agree).
  #  skipped_payroll_supported_capacity — preserved (legitimate skip;
  #    capacity is FINMO-derived from payroll, direct write would
  #    violate revenue_driver_formula_contract).
  from client_intake_and_finmo.fail_fast.common import (  # type: ignore
    PostIntakePreconditionFailed,
    convergence_test_mode_enabled,
  )
  from client_intake_and_finmo.post_intake_target_solver.target_solver import (  # type: ignore
    _find_rows_for_lever,
  )
  per_driver_summary: Dict[str, Any] = {}
  test_mode = convergence_test_mode_enabled()

  capacity_is_payroll_supported = _detect_payroll_supported_capacity(
    model_input or {}
  )

  # Detect whether this commit looks like a pnl_path commit (≥1 P&L
  # anchor present). bs_only_path commits omit all 7 P&L drivers; for
  # those, `skipped_no_anchor` is the legitimate path.
  _any_pnl_anchor_present = any(
    isinstance((driver_anchors or {}).get(k), dict)
    for k in _DRIVER_KEY_TO_LEVER_ID.keys()
  )

  _UTILIZATION_CLIP_UPPER = 0.84

  for driver_key, lever_id in _DRIVER_KEY_TO_LEVER_ID.items():
    triple = (driver_anchors or {}).get(driver_key)
    if not isinstance(triple, dict):
      if test_mode and _any_pnl_anchor_present:
        raise PostIntakePreconditionFailed(
          operation="gpt_exhaustion_handler_writer_missing_pnl_anchor",
          pipeline_stage="phase_9_p3_5_gpt_exhaustion_handler_writer",
          expected=(
            f"pnl_path commit contains an anchor for {driver_key}"
          ),
          actual="anchor key missing from driver_anchors payload",
          details={
            "missing_driver_key": driver_key,
            "lever_id": lever_id,
            "present_pnl_driver_keys": sorted([
              k for k in _DRIVER_KEY_TO_LEVER_ID
              if isinstance((driver_anchors or {}).get(k), dict)
            ]),
          },
        )
      per_driver_summary[lever_id] = {
        "status": "skipped_no_anchor",
        "reason": "anchor_not_in_commit_payload",
      }
      continue

    if lever_id == "revenue::Capacity" and capacity_is_payroll_supported:
      per_driver_summary[lever_id] = {
        "status": "skipped_payroll_supported_capacity",
        "anchor": {
          "q1": triple.get("q1"), "q11": triple.get("q11"),
          "q20": triple.get("q20"),
        },
        "reason": (
          "capacity_row.derived_driver=payroll_supported_capacity; "
          "FINMO computes capacity from payroll, direct write would "
          "violate the revenue_driver_formula_contract"
        ),
      }
      continue

    try:
      q1v = float(triple.get("q1"))
      q11v = float(triple.get("q11"))
      q20v = float(triple.get("q20"))
    except Exception as exc:
      if test_mode:
        raise PostIntakePreconditionFailed(
          operation="gpt_exhaustion_handler_writer_non_numeric_anchor",
          pipeline_stage="phase_9_p3_5_gpt_exhaustion_handler_writer",
          expected=(
            f"{driver_key} anchor has numeric q1/q11/q20 values"
          ),
          actual=f"{type(exc).__name__}: {str(exc)[:120]}",
          details={
            "driver_key": driver_key,
            "lever_id": lever_id,
            "anchor_raw": dict(triple),
          },
          cause=exc,
        ) from exc
      per_driver_summary[lever_id] = {
        "status": "skipped_non_numeric_anchor",
        "anchor": dict(triple),
      }
      continue

    if lever_id == "revenue::Utilization":
      q1v = min(q1v, _UTILIZATION_CLIP_UPPER)
      q11v = min(q11v, _UTILIZATION_CLIP_UPPER)
      q20v = min(q20v, _UTILIZATION_CLIP_UPPER)

    per_q_values = interpolate_three_anchors(
      q1=q1v, q11=q11v, q20=q20v, horizon=HORIZON_QUARTERS,
    )

    rows = _find_rows_for_lever(model_input or {}, lever_id)
    if not rows:
      if test_mode:
        raise PostIntakePreconditionFailed(
          operation="gpt_exhaustion_handler_writer_no_rows_for_lever",
          pipeline_stage="phase_9_p3_5_gpt_exhaustion_handler_writer",
          expected=f"model_input has at least one row for {lever_id}",
          actual="no rows found",
          details={
            "driver_key": driver_key,
            "lever_id": lever_id,
            "anchor": {"q1": q1v, "q11": q11v, "q20": q20v},
          },
        )
      per_driver_summary[lever_id] = {
        "status": "skipped_no_rows",
        "anchor": {"q1": q1v, "q11": q11v, "q20": q20v},
      }
      continue

    n_rows = max(1, len(rows))
    write_value_per_row: List[List[float]]
    if lever_id == "revenue::Capacity":
      write_value_per_row = [
        [round(v / float(n_rows)) for v in per_q_values] for _ in range(n_rows)
      ]
    elif lever_id == "revenue::Unit Price" or lever_id == "revenue::Utilization":
      write_value_per_row = [
        [round(v, 6) for v in per_q_values] for _ in range(n_rows)
      ]
    elif lever_id == "expenses::Payroll":
      write_value_per_row = [
        [v / float(n_rows) for v in per_q_values] for _ in range(n_rows)
      ]
    else:
      write_value_per_row = [list(per_q_values) for _ in range(n_rows)]

    for row_idx, row in enumerate(rows):
      vals = row.get("values")
      values_to_write = write_value_per_row[row_idx]
      if not isinstance(vals, list):
        vals = [0.0] * (HORIZON_QUARTERS + 1)
        row["values"] = vals
      while len(vals) <= HORIZON_QUARTERS:
        vals.append(0.0)
      for q_idx, v in enumerate(values_to_write):
        live_idx = 1 + q_idx
        if live_idx < len(vals):
          vals[live_idx] = float(v)

      tag = row.get("applied_by_target_solver_quarters")
      if not isinstance(tag, dict):
        tag = {}
        row["applied_by_target_solver_quarters"] = tag
      for q_idx, v in enumerate(values_to_write):
        tag[str(q_idx + 1)] = {
          "target_metric": provenance_tag,
          "applied_value": float(v),
          "gpt_authored": True,
          "lever_id": lever_id,
        }

    per_driver_summary[lever_id] = {
      "status": "written",
      "anchors": {"q1": q1v, "q11": q11v, "q20": q20v},
      "rows_written": len(rows),
      "per_quarter_values_q1_q11_q20": [
        per_q_values[0], per_q_values[10], per_q_values[-1]
      ],
    }

  # Phase 9 P3.6 — working capital drivers (flat across 20 quarters).
  wc = (driver_anchors or {}).get("working_capital_drivers")
  if isinstance(wc, dict) and wc:
    wc_summary = _write_gpt_authored_working_capital_values(
      model_input=model_input,
      working_capital_drivers=wc,
      provenance_tag=provenance_tag,
    )
    per_driver_summary["_working_capital"] = wc_summary
  return per_driver_summary


# ---------------------------------------------------------------------------
# Realism flag mute computation.
# ---------------------------------------------------------------------------


def compute_metrics_to_mute(
  gpt_authored_lever_ids: Optional[set] = None,
) -> List[str]:
  """Determine which realism metrics to mute for THIS draft.

  Phase 9 P3.7 — signature parameterized. ``gpt_authored_lever_ids`` is
  the set of lever_ids GPT actually authored on this run (derived from
  the commit payload, NOT from what was authorized). A metric is muted
  iff its primary_levers are all in that set, OR iff it is the
  universal viability metric ``ebitda_margin`` (always muted
  post-exhaustion because GPT authored the EBITDA trajectory itself).

  Callers under the BS-only path pass a subset of the WC lever IDs;
  callers under the P&L path pass the full P&L+WC union. This prevents
  over-muting in scoped fires.

  When the argument is None, defaults to the full P&L+WC union (the
  pre-P3.7 behaviour) for backwards compatibility.

  Universal viability trajectory checks (ebitda_positive_by_q11,
  ebitda_recovery_trend_q5_q11, loss_window_funded_through_q5,
  ebitda_margin_q20_holds_or_improves_vs_q11,
  gross_margin_supports_ebitda_recovery,
  fixed_cost_burden_reduced_or_scaled_by_q11) STAY ACTIVE — they
  evaluate against FINMO outputs (revenue, EBITDA dollar amounts), not
  driver values, and MUST still pass for the verdict.

  Per-draft only — metric definitions in lookup.py stay unchanged.
  """
  to_mute: List[str] = ["ebitda_margin"]
  if gpt_authored_lever_ids is None:
    gpt_authored: set = set(GPT_AUTHORED_LEVER_IDS) | set(
      GPT_AUTHORED_WORKING_CAPITAL_LEVER_IDS
    )
  else:
    gpt_authored = set(gpt_authored_lever_ids)

  try:
    from client_intake_and_finmo.post_intake_realism.lookup import (  # type: ignore
      post_intake_finalize_realism_check_rows,
    )
    rows = post_intake_finalize_realism_check_rows() or []
  except Exception:
    rows = []

  for row in rows:
    if not isinstance(row, dict):
      continue
    metric_key = str(row.get("metric_key") or "").strip()
    if not metric_key or metric_key in to_mute:
      continue
    if metric_key in _UNIVERSAL_VIABILITY_TRAJECTORY_METRICS:
      continue
    if not bool(row.get("active", True)):
      continue
    primary_levers = row.get("primary_levers") or []
    if not isinstance(primary_levers, (list, tuple)):
      continue
    if any(
      str(p or "").strip() in gpt_authored for p in primary_levers
    ):
      to_mute.append(metric_key)

  return to_mute


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------


def run_gpt_exhaustion_handler(
  *,
  restoration_result: Any,
  model_input: Dict[str, Any],
  operating_model: Dict[str, Any],
  build_finmo: Callable[[Dict[str, Any]], Dict[str, Any]],
  intake_context: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
) -> HandlerResult:
  """Run the GPT exhaustion handler. Mutates ``model_input`` in place
  with GPT-authored per-quarter driver values; rebuilds FINMO. Returns
  a HandlerResult with status, GPT-call count, provenance, and realism
  metrics to mute.

  Phase 9 P3.5 tool-calling pattern: GPT proposes anchors, calls
  compute_full_trajectory(anchors) to verify the EBITDA path, iterates
  against the tool result until viable, then commits a final answer.

  Phase 1 commit landing point: Phase 2-4 rebuild the runtime in
  mini_finmo.py + tool_calling_session.py + handler-side wiring. Until
  those land, this entry point returns FAILED with reason
  "phase_1_internals_deleted_phase_2_pending" so callers see the wiring
  is observable end-to-end without claiming success the system did not
  deliver.
  """
  exhaustion_diagnostic: Dict[str, Any] = {}
  try:
    if hasattr(restoration_result, "to_dict"):
      exhaustion_diagnostic = restoration_result.to_dict()
    elif isinstance(restoration_result, dict):
      exhaustion_diagnostic = dict(restoration_result)
  except Exception:
    exhaustion_diagnostic = {"note": "restoration_result_not_serializable"}

  # Phase 9 P3.10 Commit 2 — pre-session FINMO build is a genuine
  # precondition. Under CONVERGENCE_TEST_MODE=true a failure here raises
  # PostIntakePreconditionFailed so the operator sees the exact build
  # error in one log line. Production-mode callers continue to receive
  # FAILED_PRECONDITION (legacy path) for backwards compat.
  from client_intake_and_finmo.fail_fast.common import (  # type: ignore
    PostIntakePreconditionFailed,
    convergence_test_mode_enabled,
  )

  if not isinstance(finmo_json, dict) or not finmo_json:
    try:
      finmo_json = build_finmo(copy.deepcopy(model_input or {}))
    except Exception as exc:
      if convergence_test_mode_enabled():
        raise PostIntakePreconditionFailed(
          operation="gpt_exhaustion_handler_pre_session_finmo_build",
          pipeline_stage="phase_9_p3_5_gpt_exhaustion_handler",
          expected="build_finmo(model_input) returns a valid FINMO dict",
          actual=f"{type(exc).__name__}: {str(exc)[:200]}",
          details={
            "model_input_section_count": (
              len((model_input or {}).get("sections") or {})
              if isinstance(model_input, dict) else 0
            ),
            "restoration_status": (
              str(exhaustion_diagnostic.get("status") or "")
            ),
          },
          cause=exc,
        ) from exc
      return HandlerResult(
        status=HandlerStatus.FAILED_PRECONDITION,
        gpt_calls_made=0,
        provenance={
          "phase": "phase_1_pre_session_finmo_failed",
          "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        },
        reason="finmo_rebuild_failed_before_tool_calling_session",
      )

  q1_state = _q1_actual_state(finmo_json or {})
  q11_pre = _q11_ebitda_margin(finmo_json or {})

  try:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.tool_calling_session import (  # type: ignore
      execute_tool_calling_session_and_commit,
    )
  except Exception as exc:
    if convergence_test_mode_enabled():
      raise PostIntakePreconditionFailed(
        operation="gpt_exhaustion_handler_module_import",
        pipeline_stage="phase_9_p3_5_gpt_exhaustion_handler",
        expected="tool_calling_session module importable",
        actual=f"{type(exc).__name__}: {str(exc)[:200]}",
        details={"q1_state": q1_state},
        cause=exc,
      ) from exc
    return HandlerResult(
      status=HandlerStatus.FAILED_PRECONDITION,
      gpt_calls_made=0,
      q11_ebitda_actual=q11_pre,
      provenance={
        "phase": "phase_1_internals_deleted",
        "q1_state": q1_state,
        "exhaustion_diagnostic": {
          "status": exhaustion_diagnostic.get("status"),
          "q11_ebitda_margin": exhaustion_diagnostic.get("q11_ebitda_margin"),
          "drivers_at_bounds_summary": exhaustion_diagnostic.get(
            "drivers_at_bounds_summary"
          ),
          "reason": exhaustion_diagnostic.get("reason"),
        },
        "import_error": f"{type(exc).__name__}: {str(exc)[:200]}",
      },
      reason="phase_1_internals_deleted_phase_2_pending",
    )

  return execute_tool_calling_session_and_commit(
    restoration_result=restoration_result,
    exhaustion_diagnostic=exhaustion_diagnostic,
    q1_state=q1_state,
    model_input=model_input or {},
    operating_model=operating_model or {},
    build_finmo=build_finmo,
    intake_context=intake_context or {},
  )
