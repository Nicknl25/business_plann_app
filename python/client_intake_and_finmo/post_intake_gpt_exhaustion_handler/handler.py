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
#
# Phase 9 P3.32 K1 (F1+F2): "expenses::Payroll" removed from the
# catalog. Handler C (payroll_headcount.schedule.estimate_payroll_
# headcount_schedule_with_gpt) is the canonical writer for payroll
# dollars via its apply chain. Pre-P3.32 the handler had latent
# authority to write Payroll out-of-band, which produced the P3.25
# CareFirst Mirror Flavor 1 divergence and the Caring Hands latent
# FALSE_PASS surfaced by P3.32's V-4 verifier
# (Cash Q20 = $44,929 off in workbook
# 4207488106054d72afbe16480e1de100.xlsx). Removing the lever from
# the catalog structurally closes Leak A (P3.31 audit) — the path
# engine can no longer write Payroll because no driver key maps to
# it.
GPT_AUTHORED_LEVER_IDS: Tuple[str, ...] = (
  "revenue::Unit Price",
  "revenue::Capacity",
  "revenue::Utilization",
  "expenses::Cost of Goods Sold",
  "expenses::Marketing",
  "expenses::General & Administrative",
  "expenses::Research & Development",
)

# Map GPT driver-anchor key -> lever_id for the model_input write.
# Phase 9 P3.32 K1: payroll_dollars_per_quarter dropped — see
# GPT_AUTHORED_LEVER_IDS comment above.
_DRIVER_KEY_TO_LEVER_ID: Dict[str, str] = {
  "unit_price": "revenue::Unit Price",
  "units_per_period_capacity": "revenue::Capacity",
  "utilization_rate": "revenue::Utilization",
  "cogs_percent_of_revenue": "expenses::Cost of Goods Sold",
  "marketing_percent_of_revenue": "expenses::Marketing",
  "sga_percent_of_revenue": "expenses::General & Administrative",
  "r_and_d_percent_of_revenue": "expenses::Research & Development",
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
  # P3.33 Phase 3 pre-step-8 — WC days are no longer authored via this
  # path. The working_capital_drivers branch + _WC_KEY_TO_LEVER_ID +
  # _write_gpt_authored_working_capital_values were deleted; WC is
  # authored exclusively via set_capex_rd_balance_seed (balance_sheet
  # section).
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

  return per_driver_summary


# ---------------------------------------------------------------------------
# Phase 9 P3.32 K13 Fix 4 (G-B1) — H4<->H2 revenue reconciliation.
# ---------------------------------------------------------------------------


def _stage_ramp_grid_by_quarter(stage_ramp_contract: Optional[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
  out: Dict[int, Dict[str, Any]] = {}
  grid = (stage_ramp_contract or {}).get("quarter_ramp_grid")
  if isinstance(grid, list):
    for row in grid:
      if not isinstance(row, dict):
        continue
      try:
        q = int(row.get("q") if row.get("q") is not None else row.get("quarter_index"))
      except (TypeError, ValueError):
        continue
      out[q] = row
  return out


def _grid_rev_max(row: Dict[str, Any]) -> Optional[float]:
  for k in ("rev_max", "revenue_qoq_max"):
    v = row.get(k)
    if v is not None:
      try:
        return float(v)
      except (TypeError, ValueError):
        return None
  return None


def _grid_max_util(row: Dict[str, Any]) -> Optional[float]:
  for k in ("max_util", "utilization_cap"):
    v = row.get(k)
    if v is not None:
      try:
        return float(v)
      except (TypeError, ValueError):
        return None
  return None


def _live_revenue_by_quarter(finmo_json: Optional[Dict[str, Any]]) -> Dict[int, float]:
  out: Dict[int, float] = {}
  for row in ((finmo_json or {}).get("quarter_rows") or []):
    if not isinstance(row, dict):
      continue
    try:
      q = int(row.get("quarter_index"))
    except (TypeError, ValueError):
      continue
    try:
      out[q] = float(row.get("revenue") or 0.0)
    except (TypeError, ValueError):
      out[q] = 0.0
  return out


def reconcile_revenue_to_stage_ramp(
  *,
  model_input: Dict[str, Any],
  build_finmo: Callable[[Dict[str, Any]], Dict[str, Any]],
  stage_ramp_contract: Optional[Dict[str, Any]],
  max_passes: int = 12,
) -> Dict[str, Any]:
  """Fix 4 / G-B1 (doctrine §10.7): clamp committed live-revenue QoQ
  growth to the H4 stage_ramp band by scaling per-quarter
  revenue::Utilization. H4 ramp is the authority; H2 utilization yields.

  The finalize validator (assert_stage_ramp_revenue_path_applied) rejects
  a run whenever committed revenue QoQ growth (2dp) exceeds rev_max (or,
  with no payroll-supported capacity, falls below rev_target). Revenue is
  capacity*price*utilization with capacity payroll-derived and util
  clipped <=0.84 (no FINMO expansion branch), so revenue scales linearly
  with utilization — the bounded, model-agnostic lever. For each quarter
  whose predicted growth exceeds rev_max we scale that quarter's
  utilization by target/actual (target = prev*(1+rev_max), nudged under
  the 2dp boundary), processing the cascade in one logical pass using
  predicted revenue, then rebuild + verify. Only DOWNWARD scaling (never
  raises the ramp); leaves the model unchanged when already in-band."""
  summary: Dict[str, Any] = {
    "applied": False, "quarters_adjusted": [], "passes": 0,
    "rev_max_relaxed_quarters": [],
  }
  if not isinstance(model_input, dict) or not callable(build_finmo):
    return summary
  grid = _stage_ramp_grid_by_quarter(stage_ramp_contract)
  if not grid:
    return summary
  # Option 1 — RAMP AUTHORITY IS ABSOLUTE. rev_max is never relaxed. The
  # revenue trajectory is brought under the H4 ramp ceiling by reducing
  # the writable revenue knobs (utilization first, then unit price), so
  # capacity-driven over-growth is absorbed by lowering revenue to fit the
  # ramp — never by moving the bound. (Capacity itself is payroll-derived
  # and not directly writable under the revenue_driver_formula_contract,
  # so utilization and price are the deterministic levers.) If even at the
  # floors a quarter still cannot fit, a structured error surfaces the H4
  # <-> Handler-C incompatibility (extremely rare when Fix 2's robust-bound
  # is well-calibrated) rather than silently shipping an over-ramp plan.
  _UTIL_MIN = 0.05
  _PRICE_MIN_FACTOR = 0.25  # price may be reduced to at most this fraction
  from client_intake_and_finmo.post_intake_target_solver.target_solver import (  # type: ignore
    _find_rows_for_lever,
  )
  util_rows = _find_rows_for_lever(model_input or {}, "revenue::Utilization")
  price_rows = _find_rows_for_lever(model_input or {}, "revenue::Unit Price")
  if not util_rows:
    return summary
  price_baseline = {
    q: float(r["values"][q])
    for r in price_rows if isinstance(r.get("values"), list)
    for q in range(1, min(21, len(r["values"])))
    if isinstance(r["values"][q], (int, float))
  }

  def _scale_rows(rows, q: int, factor: float, lo: float, hi: float) -> None:
    for row in rows:
      vals = row.get("values")
      if not isinstance(vals, list) or q >= len(vals):
        continue
      try:
        cur = float(vals[q])
      except (TypeError, ValueError):
        continue
      vals[q] = round(max(lo, min(hi, cur * factor)), 6)

  for _pass in range(max(1, max_passes)):
    finmo = build_finmo(copy.deepcopy(model_input))
    rev = _live_revenue_by_quarter(finmo)
    changed = False
    for q in range(2, 21):
      prev = rev.get(q - 1)
      cur = rev.get(q)
      row = grid.get(q) or {}
      rev_max = _grid_rev_max(row)
      if prev is None or cur is None or prev <= 0.0 or cur <= 0.0 or rev_max is None or rev_max <= 0.0:
        continue
      if round(cur / prev, 2) <= rev_max + 1e-9:
        continue
      max_util = min(_grid_max_util(row) or 0.84, 0.84)
      factor = (prev * (1.0 + rev_max - 0.005)) / cur  # nudge under 2dp ceiling
      # Lever 1: utilization (down to _UTIL_MIN).
      _scale_rows(util_rows, q, factor, _UTIL_MIN, max_util)
      # Lever 2: unit price, only if utilization alone is insufficient
      # (factor very small => util would bottom out). Bounded so price
      # cannot collapse below a fraction of its committed baseline.
      if factor < (_UTIL_MIN / max(max_util, 1e-9)) and price_rows:
        pbase = price_baseline.get(q)
        if pbase:
          _scale_rows(price_rows, q, factor, pbase * _PRICE_MIN_FACTOR, pbase)
      changed = True
      if q not in summary["quarters_adjusted"]:
        summary["quarters_adjusted"].append(q)
    summary["passes"] = _pass + 1
    if changed:
      summary["applied"] = True
    else:
      break  # converged — no quarter violates the ramp ceiling

  # Residual check — surface a structured H4<->Handler-C incompatibility
  # if any quarter still exceeds rev_max after the levers bottomed out.
  final_rev = _live_revenue_by_quarter(build_finmo(copy.deepcopy(model_input)))
  residual = []
  for q in range(2, 21):
    prev, cur = final_rev.get(q - 1), final_rev.get(q)
    rmax = _grid_rev_max(grid.get(q) or {})
    if prev and cur and prev > 0 and rmax and round(cur / prev, 2) > rmax + 1e-9:
      residual.append(q)
  summary["residual_violation_quarters"] = residual
  return summary


def _cost_lever_targets_by_quarter(stage_ramp_contract: Optional[Dict[str, Any]]) -> Dict[str, Dict[int, float]]:
  """Per-quarter realistic cost-ratio targets the viability floor pulls
  DOWN to. cogs uses the contract's per-quarter cogs_target; marketing /
  sga / r&d use conservative deterministic targets (the same defaults
  the Python stage-ramp builder uses) since the grid carries only their
  maxes. These are the realistic viable envelope H4 intends — the floor
  never goes below them (that would be unrealistic), it only pulls an
  over-target committed ratio down to the target."""
  grid = _stage_ramp_grid_by_quarter(stage_ramp_contract)
  cogs_t: Dict[int, float] = {}
  for q, row in grid.items():
    for k in ("cogs_target", "cogs_percent_of_revenue_target"):
      v = row.get(k)
      if v is not None:
        try:
          cogs_t[q] = float(v)
        except (TypeError, ValueError):
          pass
        break
  flat = {q: 0.08 for q in range(1, 21)}
  return {
    "expenses::Cost of Goods Sold": cogs_t,
    "expenses::Marketing": {q: 0.08 for q in range(1, 21)},
    "expenses::General & Administrative": {q: 0.12 for q in range(1, 21)},
    "expenses::Research & Development": {q: 0.04 for q in range(1, 21)},
  }


def apply_viability_floor(
  *,
  model_input: Dict[str, Any],
  build_finmo: Callable[[Dict[str, Any]], Dict[str, Any]],
  stage_ramp_contract: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  """Fix 3 / G-3 (doctrine §10.6): when the committed P&L is not viable
  (EBITDA not positive by Q11), deterministically pull each per-quarter
  cost ratio DOWN to its realistic contract target and re-verify, so the
  handler commits a viable configuration instead of GPT's non-viable
  best-effort. Operates on the reconciled revenue (Fix 4 runs first), so
  the result respects the stage-ramp revenue band AND viability.

  Pull-down-only (never raises a cost ratio): if H2 already set a ratio
  below target, that is kept (better for EBITDA). If even the realistic
  targets do not reach viability, the floor commits the target config
  (the best realistic envelope; §10.2 forbids an infeasibility escape).
  Lock-on-viability: a config that is already viable is left untouched."""
  from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.mini_finmo import (  # type: ignore
    _eval_viability_checks,
  )
  from client_intake_and_finmo.post_intake_target_solver.target_solver import (  # type: ignore
    _find_rows_for_lever,
  )
  summary: Dict[str, Any] = {
    "applied": False, "viable_before": None, "viable_after": None, "steps": 0,
  }
  if not isinstance(model_input, dict) or not callable(build_finmo):
    return summary

  def _viable() -> bool:
    return bool(
      _eval_viability_checks(
        build_finmo(copy.deepcopy(model_input)), stage_ramp_contract
      ).get("ebitda_positive_by_q11")
    )

  summary["viable_before"] = _viable()
  if summary["viable_before"]:
    return summary  # already viable — lock, do nothing

  # Step 1 — pull every cost ratio DOWN to its realistic contract target
  # (never raises one already below). This is the realistic baseline.
  targets = _cost_lever_targets_by_quarter(stage_ramp_contract)
  cost_levers = [
    "expenses::Cost of Goods Sold", "expenses::Marketing",
    "expenses::General & Administrative", "expenses::Research & Development",
  ]
  for lever_id, per_q in targets.items():
    if not per_q:
      continue
    for row in _find_rows_for_lever(model_input or {}, lever_id):
      vals = row.get("values")
      if not isinstance(vals, list):
        continue
      for q in range(1, 21):
        if q >= len(vals) or q not in per_q:
          continue
        try:
          cur = float(vals[q])
        except (TypeError, ValueError):
          continue
        vals[q] = round(min(cur, float(per_q[q])), 6)  # pull DOWN only
  summary["applied"] = True

  # Step 2 — if the reconciled revenue + realistic targets still are not
  # viable (e.g. Fix 4 lowered revenue to respect the ramp ceiling), step
  # COGS DOWN (the dominant viability lever) toward its schema floor (0.20)
  # until Q11 EBITDA turns positive or the floor is reached. Only COGS is
  # stepped: marketing/sga/rd are kept at their realistic step-1 targets
  # (>0) because the finalize mapping-formula validator disallows driving
  # a required cost ratio to <=0. The loop STOPS the moment viability is
  # reached (minimal reduction = lock-on-viability), so the committed
  # config is the least-aggressive COGS cut that achieves it.
  cogs_floor, cogs_step = 0.20, 0.03
  for step in range(1, 26):
    if _viable():
      break
    moved = False
    for row in _find_rows_for_lever(model_input or {}, "expenses::Cost of Goods Sold"):
      vals = row.get("values")
      if not isinstance(vals, list):
        continue
      for q in range(1, min(21, len(vals))):
        try:
          cur = float(vals[q])
        except (TypeError, ValueError):
          continue
        if cur > cogs_floor + 1e-9:
          vals[q] = round(max(cogs_floor, cur - cogs_step), 6)
          moved = True
    summary["steps"] = step
    if not moved:
      break  # COGS at its floor — best feasible committed
  summary["viable_after"] = _viable()
  return summary


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

  # Phase 9 P3.10 Commit 4 — realism lookup load failure raises under
  # test mode. Audit #26: silent rows=[] produces a minimal mute set
  # (just ["ebitda_margin"]), causing spurious realism failures to be
  # attributed to GPT-authored drivers when they shouldn't be muted
  # (under-muting), or vice versa.
  try:
    from client_intake_and_finmo.post_intake_realism.lookup import (  # type: ignore
      post_intake_finalize_realism_check_rows,
    )
    rows = post_intake_finalize_realism_check_rows() or []
  except Exception as exc:
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      PostIntakePreconditionFailed,
      convergence_test_mode_enabled,
    )
    if convergence_test_mode_enabled():
      raise PostIntakePreconditionFailed(
        operation="compute_metrics_to_mute_realism_lookup_failed",
        pipeline_stage="phase_9_p3_5_gpt_exhaustion_handler_post_commit",
        expected="post_intake_finalize_realism_check_rows() returns row list",
        actual=f"{type(exc).__name__}: {str(exc)[:200]}",
        details={
          "gpt_authored_lever_count": len(gpt_authored),
        },
        cause=exc,
      ) from exc
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
  stage_ramp_contract: Optional[Dict[str, Any]] = None,
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
  # P3.33 Phase 3 step 3c transitional shim. The GPT iteration loop
  # (run_tool_calling_session, execute_tool_calling_session_and_commit,
  # prompts.py) is GONE. Authoring authority for the driver anchors
  # belongs to the amalgamated GPT session via
  # ``post_intake_amalgamated.tools.set_drivers``; step 5 wires that
  # session into the orchestrator. Until step 5 lands, this entry
  # returns EXHAUSTED with a transitional diagnostic so the
  # orchestrator's post-exhaustion path (K13 floor — reconcile_revenue_
  # to_stage_ramp + apply_viability_floor below) continues to commit
  # the deterministic driver values.
  exhaustion_diagnostic: Dict[str, Any] = {}
  try:
    if hasattr(restoration_result, "to_dict"):
      exhaustion_diagnostic = restoration_result.to_dict()
    elif isinstance(restoration_result, dict):
      exhaustion_diagnostic = dict(restoration_result)
  except Exception:
    exhaustion_diagnostic = {"note": "restoration_result_not_serializable"}
  return HandlerResult(
    status=HandlerStatus.FAILED_PRECONDITION,
    gpt_calls_made=0,
    provenance={
      "transition": "amalgamated_session_pending",
      "deleted": [
        "post_intake_gpt_exhaustion_handler.tool_calling_session",
        "post_intake_gpt_exhaustion_handler.prompts",
      ],
      "amalgamated_tool": "post_intake_amalgamated.tools.set_drivers",
      "exhaustion_diagnostic": exhaustion_diagnostic,
    },
    reason=(
      "h2_gpt_session_loop_deleted_step_3c_amalgamated_session_pending_step_5"
    ),
  )
