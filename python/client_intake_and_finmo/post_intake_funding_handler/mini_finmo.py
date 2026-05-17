"""Iter 19 Stage 4 — Funding handler mini-FINMO mirror (scaffold).

Lightweight cash-trajectory mirror used by the GPT-driven variant of
the funding handler (see :mod:`tool_calling_session`). Per
docs/architecture/doctrine.md §4 Flavor 3 (mini / shadow object):
GPT calls ``compute_full_trajectory`` to preview the result of
proposed lever adjustments before committing, without paying the
full FINMO rebuild cost.

The mirror is intentionally narrow: it only models the cash account
movements driven by the funding levers under the handler's authority.
Operating-side levers and full balance-sheet reconciliation are out
of scope — those belong to FINMO proper.

Today's deterministic correction path
(:func:`post_intake_funding_handler.handler.run_funding_handler`)
does not invoke the mirror; per-quarter ``lever_bounds`` headroom is
enough information for the deterministic allocator. The mirror is
kept here so the follow-up iter that wires GPT tool-calling has the
correct shape ready.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional


def project_cash_trajectory_with_adjustments(
  *,
  pre_handler_finmo_quarter_rows: List[Dict[str, Any]],
  lever_adjustments: Dict[str, Dict[int, float]],
) -> Dict[str, Any]:
  """Apply funding-lever adjustments to a copy of the pre-handler FINMO
  rows and return the projected per-quarter ending_cash + buffer
  residual.

  This is a SIMPLIFIED projection: it walks the quarters in order,
  applying each adjustment to the corresponding cash inflow/outflow,
  and tracks the running ending_cash. Full FINMO reconciliation
  (balance sheet, working capital deltas, debt schedule rebuild) is
  out of scope; the deterministic correction path does not need it
  because per-quarter ``lever_bounds`` already reflect the
  reconciled headroom upstream.

  Used by the GPT-driven variant of the handler to verify proposed
  adjustments before committing. Today's deterministic path does NOT
  call this function.
  """
  rows_in = pre_handler_finmo_quarter_rows or []
  projected: List[Dict[str, Any]] = []
  running_cash_delta = 0.0
  for row in rows_in:
    if not isinstance(row, dict):
      continue
    try:
      qi = int(float(row.get("quarter_index") or 0))
    except Exception:
      continue
    if qi < 1:
      continue
    new_row = copy.deepcopy(row)
    delta_this_quarter = 0.0
    for lever_id, per_q in lever_adjustments.items():
      if not isinstance(per_q, dict):
        continue
      amount = float(per_q.get(qi) or 0.0)
      if "Distributions" in lever_id:
        # Reducing distributions = adding cash back to the business.
        # A negative amount in the lever adjustment means lower
        # distributions; cash impact is the negated amount.
        delta_this_quarter += -amount
      else:
        delta_this_quarter += amount
    running_cash_delta += delta_this_quarter
    try:
      base_ending_cash = float(row.get("ending_cash") or 0.0)
    except Exception:
      base_ending_cash = 0.0
    new_row["projected_ending_cash"] = round(base_ending_cash + running_cash_delta, 2)
    new_row["cash_delta_from_adjustments"] = round(running_cash_delta, 2)
    projected.append(new_row)
  return {
    "projected_quarter_rows": projected,
    "total_cash_delta": round(running_cash_delta, 2),
  }


def buffer_residual_after_adjustments(
  *,
  pre_handler_finmo_quarter_rows: List[Dict[str, Any]],
  lever_adjustments: Dict[str, Dict[int, float]],
  buffer_by_quarter: Dict[int, float],
) -> List[Dict[str, Any]]:
  """Return the list of quarters where projected ending_cash is still
  below the buffer requirement after applying the proposed
  adjustments.

  Mirror of the post-pass cash_buffer_violations check. Used by the
  GPT-driven variant to decide whether to keep iterating or commit.
  """
  projection = project_cash_trajectory_with_adjustments(
    pre_handler_finmo_quarter_rows=pre_handler_finmo_quarter_rows,
    lever_adjustments=lever_adjustments,
  )
  residual: List[Dict[str, Any]] = []
  for row in projection["projected_quarter_rows"]:
    try:
      qi = int(float(row.get("quarter_index") or 0))
    except Exception:
      continue
    buffer_required = float(buffer_by_quarter.get(qi) or 0.0)
    projected_ec = float(row.get("projected_ending_cash") or 0.0)
    if projected_ec < buffer_required:
      residual.append({
        "quarter_index": qi,
        "projected_ending_cash": projected_ec,
        "buffer": buffer_required,
        "shortfall": round(buffer_required - projected_ec, 2),
      })
  return residual
