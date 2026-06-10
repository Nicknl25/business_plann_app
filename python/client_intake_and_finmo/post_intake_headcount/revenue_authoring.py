"""Revenue-authoring pass: GPT authors revenue DRIVERS, Python computes the line.

Orchestrates the revenue-authoring design (settled with Nick):
  1. GPT authors per-quarter revenue drivers from the enriched business compact
     (gpt_revenue_author.gpt_author_revenue_drivers_once).
  2. Python NORMALIZES the 20-quarter grid (fill gaps, non-decreasing capacity,
     clamp utilization) and COMPUTES the revenue line
     (revenue[q] = capacity[q] x utilization[q] x unit_price[q]).
  3. Python WRITES the drivers into the model_input revenue rows by driver
     (Unit Price / Capacity / Utilization), so the rest of the pipeline builds
     on a GPT-authored, business-grounded top line.

Runs FIRST (before the cascade). Re-invokable by the cascade when revenue is the
binding constraint (pass ``failing_state``). On no-key / GPT failure the pass
returns ok=False and leaves the model_input unchanged (caller keeps the intake
baseline).
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

_HORIZON = 20
_DRIVER_BY_FIELD = {
  "unit_price": "Unit Price",
  "capacity_units_per_period": "Capacity",
  "utilization_rate": "Utilization",
}


def _f(v: Any) -> Optional[float]:
  try:
    return float(v)
  except (TypeError, ValueError):
    return None


def normalize_revenue_drivers(drivers: Dict[str, Any]) -> Dict[int, Dict[str, float]]:
  """Return {q (1..20): {unit_price, capacity_units_per_period, utilization_rate}}.

  Fills missing quarters by carrying the last seen value forward (then the
  first value backward for any leading gap), enforces non-decreasing capacity,
  and clamps utilization to [0, 1]. Tolerant of partial GPT output."""
  rows = drivers.get("quarters") if isinstance(drivers, dict) else None
  by_q: Dict[int, Dict[str, float]] = {}
  if isinstance(rows, list):
    for row in rows:
      if not isinstance(row, dict):
        continue
      try:
        q = int(row.get("q"))
      except (TypeError, ValueError):
        continue
      if not 1 <= q <= _HORIZON:
        continue
      entry: Dict[str, float] = {}
      for field in _DRIVER_BY_FIELD:
        val = _f(row.get(field))
        if val is not None:
          entry[field] = val
      if entry:
        by_q[q] = entry

  # Forward/backward fill so every quarter has all three drivers.
  normalized: Dict[int, Dict[str, float]] = {}
  last: Dict[str, float] = {}
  for q in range(1, _HORIZON + 1):
    cur = dict(last)
    cur.update(by_q.get(q, {}))
    normalized[q] = cur
    last = cur
  # Backfill any leading gap from the first fully-populated quarter.
  first_full = next((q for q in range(1, _HORIZON + 1)
                     if all(field in normalized[q] for field in _DRIVER_BY_FIELD)), None)
  if first_full is not None:
    for q in range(1, first_full):
      for field in _DRIVER_BY_FIELD:
        normalized[q].setdefault(field, normalized[first_full][field])

  # Enforce non-decreasing capacity + clamp utilization + non-negative price.
  prev_cap = 0.0
  for q in range(1, _HORIZON + 1):
    e = normalized[q]
    e.setdefault("unit_price", 0.0)
    e.setdefault("capacity_units_per_period", 0.0)
    e.setdefault("utilization_rate", 0.0)
    e["unit_price"] = max(0.0, e["unit_price"])
    e["capacity_units_per_period"] = max(prev_cap, max(0.0, e["capacity_units_per_period"]))
    prev_cap = e["capacity_units_per_period"]
    e["utilization_rate"] = min(1.0, max(0.0, e["utilization_rate"]))
  return normalized


def compute_revenue_line(normalized: Dict[int, Dict[str, float]]) -> List[float]:
  """Quarterly revenue = capacity x utilization x unit_price."""
  return [
    normalized[q]["capacity_units_per_period"]
    * normalized[q]["utilization_rate"]
    * normalized[q]["unit_price"]
    for q in range(1, _HORIZON + 1)
  ]


def current_revenue_reference(model_input_json: Dict[str, Any]) -> Dict[str, Any]:
  """Compact snapshot of the intake-baseline revenue drivers for GPT reference."""
  ref: Dict[str, Any] = {}
  rev = (model_input_json.get("sections", {}) or {}).get("revenue") or []
  for row in rev if isinstance(rev, list) else []:
    if not isinstance(row, dict):
      continue
    driver = str(row.get("driver") or "").strip()
    field = next((f for f, d in _DRIVER_BY_FIELD.items() if d == driver), None)
    if field is None:
      continue
    vals = row.get("values")
    if isinstance(vals, list) and len(vals) > 1:
      ref[field] = {"q1": vals[1], "q20": vals[min(_HORIZON, len(vals) - 1)]}
  return ref


def apply_authored_revenue_to_model_input(
  model_input_json: Dict[str, Any],
  normalized: Dict[int, Dict[str, float]],
) -> Dict[str, Any]:
  """Write the authored per-quarter drivers into the revenue rows by driver.
  Mutates a deep copy and returns it (index 0 is the stub; quarters 1..20)."""
  mi = copy.deepcopy(model_input_json) if isinstance(model_input_json, dict) else {}
  rev = (mi.get("sections", {}) or {}).get("revenue") or []
  if not isinstance(rev, list):
    return mi
  for row in rev:
    if not isinstance(row, dict):
      continue
    driver = str(row.get("driver") or "").strip()
    field = next((f for f, d in _DRIVER_BY_FIELD.items() if d == driver), None)
    if field is None:
      continue
    values = row.get("values")
    if not isinstance(values, list) or not values:
      continue
    for q in range(1, min(_HORIZON + 1, len(values))):
      values[q] = normalized[q][field]
  # DOCTRINE ANCHOR: revenue is the ROOT and is now GPT-authored, so the
  # per-quarter driver ramps written above are AUTHORITATIVE. Mark the
  # model_input so downstream passes that would otherwise rebuild revenue
  # drivers from raw intake scalars (e.g. the feasibility-restoration patch,
  # which flat-overwrites Capacity from ops_json.units_per_period_capacity)
  # do NOT discard the authored ramp. FTE / intake scalars must never
  # back-drive the authored capacity. Universal: set for every authored plan.
  # Carried inside solver_input (Optional[Dict[str,Any]] in
  # FinmoModelInputContract) so it survives the AMALGAMATED_SESSION->MODEL_INPUT
  # contract boundary -- a new top-level key is rejected by extra="forbid".
  si = mi.get("solver_input")
  if not isinstance(si, dict):
    si = {}
    mi["solver_input"] = si
  si["revenue_authored"] = True
  return mi


def run_revenue_authoring_pass(
  *,
  compact: Dict[str, Any],
  model_input_json: Dict[str, Any],
  failing_state: Optional[Dict[str, Any]] = None,
  model: Optional[str] = None,
  max_attempts: int = 2,
  _author_fn=None,
) -> Dict[str, Any]:
  """Author revenue drivers from the compact, compute the line, write model_input.

  Returns ``{ok, model_input_json, normalized, revenue_line, drivers, error}``.
  ok=False (no key / GPT failure) -> model_input_json returned unchanged."""
  author_fn = _author_fn
  if author_fn is None:
    from client_intake_and_finmo.post_intake_headcount.gpt_revenue_author import (  # type: ignore
      gpt_author_revenue_drivers_once,
    )
    author_fn = gpt_author_revenue_drivers_once

  reference = current_revenue_reference(model_input_json)
  violations: Optional[List[Dict[str, Any]]] = None
  last_error: Optional[str] = None
  for _attempt in range(max(1, int(max_attempts))):
    result = author_fn(
      compact=compact,
      current_revenue_reference=reference,
      failing_state=failing_state,
      previous_violations=violations,
      model=model,
    )
    if not result.get("ok"):
      last_error = result.get("error")
      break  # no key / HTTP error -> don't retry, fall back
    drivers = result.get("drivers") or {}
    normalized = normalize_revenue_drivers(drivers)
    revenue_line = compute_revenue_line(normalized)
    if sum(revenue_line) <= 0:
      violations = [{"code": "revenue_line_nonpositive",
                     "message": "computed revenue line is all zero — author positive price/capacity/utilization."}]
      last_error = "revenue_line_nonpositive"
      continue
    applied = apply_authored_revenue_to_model_input(model_input_json, normalized)
    return {
      "ok": True,
      "model_input_json": applied,
      "normalized": normalized,
      "revenue_line": revenue_line,
      "drivers": drivers,
      "error": None,
    }
  return {
    "ok": False,
    "model_input_json": model_input_json,
    "normalized": None,
    "revenue_line": None,
    "drivers": None,
    "error": last_error or "revenue_authoring_failed",
  }


__all__ = [
  "run_revenue_authoring_pass",
  "normalize_revenue_drivers",
  "compute_revenue_line",
  "apply_authored_revenue_to_model_input",
  "current_revenue_reference",
]
