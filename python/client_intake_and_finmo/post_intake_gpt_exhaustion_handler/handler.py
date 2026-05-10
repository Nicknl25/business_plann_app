"""Phase 9 P3.5 — GPT exhaustion handler orchestrator.

Public entry point: ``run_gpt_exhaustion_handler``. Called by the
post-cascade orchestrator when ``run_restoration_loop`` returns
``RestorationStatus.EXHAUSTED``. Lives between the restoration loop
(operating-side deterministic algebra) and the cash strategy
(financing-side, untouched here).

Pipeline inside this handler:
  1. Build operating model + Q1 actual state from intake / FINMO inputs.
  2. Call 1: GPT returns {Q1, Q11, Q20} EBITDA anchors.
  3. Call 2: GPT returns {Q1, Q11, Q20} anchors per driver consistent
     with the EBITDA anchors.
  4. Validate Call 2; on failure, retry once with the validation error
     in-prompt; if still invalid, fall through to deterministic snap-in.
  5. Interpolate driver anchors -> 20-quarter trajectories and write to
     model_input with provenance tags.
  6. Rebuild FINMO. Compare FINMO Q11 EBITDA vs GPT Call 1 Q11 anchor.
  7. If gap <= TOLERANCE_BPS / 10000: LANDED_GPT (or LANDED_ITERATED if
     iterations were used).
  8. Otherwise iterate up to MAX_ITERATIONS; each iteration is a fresh
     GPT call carrying cumulative diagnostic.
  9. If 3 iterations don't converge: deterministic snap-in via
     ``solve_for_target`` with ±15% bounds around GPT's anchored values.
 10. Determine which realism metrics to mute for this draft (the
     metrics whose primary_levers include any GPT-authored driver).

This module is universal across NAICS / stage / archetype. Differences
in output flow from the operating_model JSON, never from code branches.
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants — exposed as module-level so they're easy to find / tune.
# ---------------------------------------------------------------------------

TOLERANCE_BPS = 50          # Q11 EBITDA convergence: |GPT_target - FINMO| <= 50bps
MAX_ITERATIONS = 3          # Iterations before falling through to snap-in
SNAP_IN_DRIVER_TOLERANCE = 0.15  # ±15% around GPT's driver anchors for snap-in
HORIZON_QUARTERS = 20

# Lever IDs the handler authors. These are the "drivers" GPT returns
# anchors for in Call 2; the path engine interpolates each driver's
# 3 anchors into a 20-quarter trajectory. Universal across NAICS.
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


class HandlerStatus(str, Enum):
  LANDED_GPT = "landed_gpt"           # Call 2 succeeded immediately
  LANDED_ITERATED = "landed_iterated"  # 1-3 iterations needed
  LANDED_SNAP = "landed_snap"          # Deterministic snap-in finished
  LANDED_PARTIAL = "landed_partial"    # Snap-in within tolerance window but not exact
  FAILED = "failed"                    # Snap-in couldn't reach target


@dataclass
class HandlerResult:
  status: HandlerStatus
  gpt_calls_made: int = 0
  iterations_used: int = 0
  q11_ebitda_target: Optional[float] = None
  q11_ebitda_actual: Optional[float] = None
  provenance: Dict[str, Any] = field(default_factory=dict)
  realism_flags_to_mute: List[str] = field(default_factory=list)
  reason: str = ""

  def to_dict(self) -> Dict[str, Any]:
    return {
      "status": self.status.value if isinstance(self.status, HandlerStatus) else str(self.status),
      "gpt_calls_made": int(self.gpt_calls_made),
      "iterations_used": int(self.iterations_used),
      "q11_ebitda_target": self.q11_ebitda_target,
      "q11_ebitda_actual": self.q11_ebitda_actual,
      "provenance": dict(self.provenance),
      "realism_flags_to_mute": list(self.realism_flags_to_mute),
      "reason": self.reason,
    }


# ---------------------------------------------------------------------------
# Q1 actual state extraction.
# ---------------------------------------------------------------------------


def _q1_actual_state(finmo_json: Dict[str, Any]) -> Dict[str, Any]:
  """Pull the Q1 actuals the prompts care about — revenue, ebitda_margin,
  total_opex, payroll, cogs, marketing, sga, gross_profit. Read from the
  FINMO output's quarter_rows[quarter_index=1].
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
    marketing = float(row.get("marketing") or row.get("marketing_expense") or 0.0)
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


def _q11_line_items(finmo_json: Dict[str, Any]) -> Dict[str, float]:
  out: Dict[str, float] = {}
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
    revenue = float(row.get("revenue") or 0.0)
    cogs = float(row.get("cost_of_goods_sold") or 0.0)
    payroll = float(row.get("payroll") or 0.0)
    marketing = float(row.get("marketing") or row.get("marketing_expense") or 0.0)
    sga = float(row.get("general_and_administrative") or row.get("sga") or 0.0)
    gross_profit = revenue - cogs
    total_opex = payroll + marketing + sga
    ebitda = float(row.get("ebitda") or (gross_profit - total_opex))
    out = {
      "revenue": revenue,
      "cogs": cogs,
      "gross_profit": gross_profit,
      "payroll": payroll,
      "marketing": marketing,
      "sga": sga,
      "total_opex": total_opex,
      "ebitda": ebitda,
    }
    break
  return out


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
# 3-anchor -> 20-quarter interpolation.
# ---------------------------------------------------------------------------


def interpolate_three_anchors(
  *, q1: float, q11: float, q20: float, horizon: int = HORIZON_QUARTERS,
) -> List[float]:
  """Linear interpolation Q1->Q11->Q20 across ``horizon`` quarters
  (1-indexed semantics: index 0 = Q1, index 10 = Q11, index 19 = Q20).

  This is intentionally a clean two-segment linear ramp so the GPT-
  authored anchors land EXACTLY at Q1, Q11, Q20. Per-driver path-shape
  doctrine (s_curve / glidepath / etc.) is intentionally bypassed: GPT
  has produced the strategic anchors and this handler honors them
  verbatim. The path engine's per-shape variation is a generic-default
  policy when no anchors are GPT-authored; here, GPT is the authority.
  """
  h = max(1, int(horizon))
  values: List[float] = [0.0] * h
  q1f = float(q1)
  q11f = float(q11)
  q20f = float(q20)
  for q in range(h):
    if q <= 10:
      # Segment 1: Q1 (idx 0) -> Q11 (idx 10).
      frac = q / 10.0 if h > 1 else 0.0
      values[q] = (1.0 - frac) * q1f + frac * q11f
    else:
      # Segment 2: Q11 (idx 10) -> Q20 (idx h-1).
      span = max(1, (h - 1) - 10)
      frac = (q - 10) / float(span)
      values[q] = (1.0 - frac) * q11f + frac * q20f
  return values


# ---------------------------------------------------------------------------
# Model input writer for GPT-authored drivers.
# ---------------------------------------------------------------------------


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
    - the realism mute mechanism (Phase 4) can find the GPT-authored
      drivers via this tag.
  Returns a per-driver write summary used by the handler's provenance
  trail.
  """
  from client_intake_and_finmo.post_intake_target_solver.target_solver import (  # type: ignore
    _find_rows_for_lever,
  )
  per_driver_summary: Dict[str, Any] = {}
  for driver_key, lever_id in _DRIVER_KEY_TO_LEVER_ID.items():
    triple = (driver_anchors or {}).get(driver_key)
    if not isinstance(triple, dict):
      per_driver_summary[lever_id] = {
        "status": "skipped_no_anchor",
        "reason": "anchor_not_in_call_2_payload",
      }
      continue
    try:
      q1v = float(triple.get("q1"))
      q11v = float(triple.get("q11"))
      q20v = float(triple.get("q20"))
    except Exception:
      per_driver_summary[lever_id] = {
        "status": "skipped_non_numeric_anchor",
        "anchor": dict(triple),
      }
      continue
    per_q_values = interpolate_three_anchors(
      q1=q1v, q11=q11v, q20=q20v, horizon=HORIZON_QUARTERS,
    )

    rows = _find_rows_for_lever(model_input or {}, lever_id)
    if not rows:
      per_driver_summary[lever_id] = {
        "status": "skipped_no_rows",
        "anchor": {"q1": q1v, "q11": q11v, "q20": q20v},
      }
      continue

    # For revenue-shortcut levers that map to multiple LOB rows, divide
    # the anchor value across rows so the AGGREGATE (sum of LOBs) lands
    # at the GPT-authored value. This mirrors the target solver's
    # combine-by-average read pattern in _read_driver_state.
    write_value_per_row: List[List[float]] = []
    n_rows = max(1, len(rows))
    if lever_id == "revenue::Capacity":
      # Capacity is additive across LOBs -> divide.
      write_value_per_row = [
        [v / float(n_rows) for v in per_q_values] for _ in range(n_rows)
      ]
    elif lever_id == "revenue::Unit Price" or lever_id == "revenue::Utilization":
      # Price/utilization don't sum across LOBs; broadcast same value.
      write_value_per_row = [list(per_q_values) for _ in range(n_rows)]
    elif lever_id == "expenses::Payroll":
      # Total quarterly payroll is divided across payroll rows.
      write_value_per_row = [
        [v / float(n_rows) for v in per_q_values] for _ in range(n_rows)
      ]
    else:
      # Cost-ratio levers — broadcast same percentage to each row.
      write_value_per_row = [list(per_q_values) for _ in range(n_rows)]

    for row_idx, row in enumerate(rows):
      vals = row.get("values")
      values_to_write = write_value_per_row[row_idx]
      if not isinstance(vals, list):
        # Fresh row — initialize with stub at index 0 plus 20 live cells.
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
  with GPT-authored per-quarter driver values; rebuilds FINMO between
  iterations. Returns a HandlerResult with status, GPT-call count,
  provenance, and realism metrics to mute.

  Parameters
  ----------
  restoration_result
    The RestorationResult returned by ``run_restoration_loop``. Used
    for the exhaustion diagnostic and to identify which realism metrics
    triggered exhaustion (those metrics' band-checks get muted on this
    draft because their drivers are now GPT-authored).
  model_input
    The model_input dict the handler will mutate with per-quarter
    driver values. Same dict the cash strategy will read after this
    handler completes (so cash sees the GPT-authored operating model).
  operating_model
    The ops_json — the universal "operating model" structure that
    carries business_stage, business_naics_6, business_type, location,
    capacity, pricing, employees, sales_modality, business_description_summary,
    and all related fields. Passed verbatim into the GPT prompt.
  build_finmo
    Callable mapping model_input -> finmo_json. The handler invokes
    this to recompute Q11 EBITDA margin after GPT-authored writes.
  intake_context
    Optional context dict (financials_json, planning_mode,
    business_naics_6 — looked up only if needed by snap-in's bound
    resolver). The handler does not use this for the GPT prompt; it
    flows into snap-in if reached.
  finmo_json
    Optional pre-computed FINMO output for Q1 actuals. If absent, the
    handler builds it via ``build_finmo``.

  Imports happen lazily inside the function so this module can be
  imported even when the orchestrator package is not on sys.path
  (tests / migrations).

  Phase 1 scaffolding note
  ------------------------
  Phase 1 wires the entry point and provenance plumbing. The actual
  GPT call paths (Phase 2) and iteration / snap-in (Phase 3) are
  filled in as their phases land. In Phase 1, calling this handler
  with no GPT availability returns HandlerStatus.FAILED with reason
  "phase_1_scaffolding_only" so the caller can see the wiring works
  end-to-end without yet attempting a real GPT call.
  """
  # Phase 2/3 implementations live in handler_runtime.py — Phase 1
  # delegates to that module so Phase 1's commit can land cleanly
  # without forward-referencing logic that doesn't exist yet.
  try:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler_runtime import (  # type: ignore
      execute_handler,
    )
  except Exception as exc:
    return HandlerResult(
      status=HandlerStatus.FAILED,
      reason=f"phase_1_scaffolding_only_no_runtime_module_yet: {type(exc).__name__}: {str(exc)[:200]}",
      provenance={"scaffolding_phase": "phase_1"},
    )
  return execute_handler(
    restoration_result=restoration_result,
    model_input=model_input,
    operating_model=operating_model,
    build_finmo=build_finmo,
    intake_context=intake_context or {},
    finmo_json=finmo_json,
  )
