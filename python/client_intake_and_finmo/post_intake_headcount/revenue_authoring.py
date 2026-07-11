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


def _extract_author_lines(drivers: Dict[str, Any]) -> List[Dict[str, Any]]:
  """Normalize the GPT tool output into a list of per-line driver blocks, each
  carrying ``lob_name``/``unit_name``/``quarters``. Accepts the multi-line shape
  (``lines_of_business``) and the legacy single-line shape (top-level
  ``quarters``) so single-LOB authoring keeps working unchanged."""
  if not isinstance(drivers, dict):
    return []
  lob_list = drivers.get("lines_of_business")
  if isinstance(lob_list, list) and lob_list:
    return [e for e in lob_list if isinstance(e, dict) and e.get("quarters")]
  if drivers.get("quarters"):
    return [drivers]
  return []


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
  """Quarterly revenue for ONE line = capacity x utilization x unit_price."""
  return [
    normalized[q]["capacity_units_per_period"]
    * normalized[q]["utilization_rate"]
    * normalized[q]["unit_price"]
    for q in range(1, _HORIZON + 1)
  ]


def compute_total_revenue_line(
  normalized_lines: List[Dict[int, Dict[str, float]]],
) -> List[float]:
  """Total quarterly revenue = SUM of each line's revenue. Multi-LOB businesses
  (e.g. Corporate Legal + Individual Legal) sum their distinct lines; a
  single-line business is just that one line."""
  total = [0.0] * _HORIZON
  for normalized in normalized_lines:
    line = compute_revenue_line(normalized)
    for i in range(_HORIZON):
      total[i] += line[i]
  return total


def _norm_key(lob: Any, unit: Any) -> Tuple[str, str]:
  return (str(lob or "").strip().lower(), str(unit or "").strip().lower())


def current_revenue_reference(model_input_json: Dict[str, Any]) -> List[Dict[str, Any]]:
  """PER-LINE snapshot of the intake-baseline revenue drivers for GPT reference.

  One entry per distinct (lob, product) so GPT sees each line's DISTINCT intake
  price/capacity (e.g. Corporate $12k vs Individual $6k) and can author each
  line from its own baseline — never a single collapsed top-level reference."""
  rev = (model_input_json.get("sections", {}) or {}).get("revenue") or []
  by_group: Dict[Tuple[Any, Any], Dict[str, Any]] = {}
  order: List[Tuple[Any, Any]] = []
  for row in rev if isinstance(rev, list) else []:
    if not isinstance(row, dict):
      continue
    driver = str(row.get("driver") or "").strip()
    field = next((f for f, d in _DRIVER_BY_FIELD.items() if d == driver), None)
    if field is None:
      continue
    vals = row.get("values")
    if not (isinstance(vals, list) and len(vals) > 1):
      continue
    key = (row.get("lob"), row.get("product"))
    if key not in by_group:
      by_group[key] = {}
      order.append(key)
    by_group[key][field] = {"q1": vals[1], "q20": vals[min(_HORIZON, len(vals) - 1)]}
  ref: List[Dict[str, Any]] = []
  for key in order:
    entry: Dict[str, Any] = {}
    if key[0]:
      entry["lob"] = key[0]
    if key[1]:
      entry["unit"] = key[1]
    entry.update(by_group[key])
    ref.append(entry)
  return ref


def _match_lines_to_groups(
  lines_normalized: List[Dict[str, Any]],
  groups: List[Tuple[Any, Any]],
) -> Dict[Tuple[Any, Any], Dict[int, Dict[str, float]]]:
  """Map each model_input (lob, product) group to an authored line's normalized
  ramp. Match by (lob, unit) name first; assign any leftover lines to leftover
  groups by order (GPT authors lines in the compact's order). Robust to GPT not
  echoing names exactly while still keeping distinct lines distinct."""
  assigned: Dict[int, Dict[int, Dict[str, float]]] = {}
  line_used = [False] * len(lines_normalized)
  group_keys = [_norm_key(g[0], g[1]) for g in groups]
  for li, line in enumerate(lines_normalized):
    lk = _norm_key(line.get("lob"), line.get("unit"))
    for gi in range(len(groups)):
      if gi not in assigned and group_keys[gi] == lk:
        assigned[gi] = line["normalized"]
        line_used[li] = True
        break
  free_g = [gi for gi in range(len(groups)) if gi not in assigned]
  free_l = [li for li in range(len(lines_normalized)) if not line_used[li]]
  for gi, li in zip(free_g, free_l):
    assigned[gi] = lines_normalized[li]["normalized"]
  return {groups[gi]: assigned[gi] for gi in assigned}


def apply_authored_revenue_to_model_input(
  model_input_json: Dict[str, Any],
  lines_normalized: List[Dict[str, Any]],
) -> Dict[str, Any]:
  """Write each authored line's per-quarter drivers into the revenue rows for
  its MATCHING (lob, product). ``lines_normalized`` is a list of
  ``{"lob","unit","normalized": {q: {field: value}}}`` — one per authored line.
  Multi-LOB businesses write each line into its own rows (so Corporate $12k and
  Individual $6k stay distinct); a single-line business writes its one line.
  Mutates a deep copy and returns it (index 0 is the stub; quarters 1..20)."""
  mi = copy.deepcopy(model_input_json) if isinstance(model_input_json, dict) else {}
  rev = (mi.get("sections", {}) or {}).get("revenue") or []
  if not isinstance(rev, list) or not lines_normalized:
    return mi
  # Distinct (lob, product) groups in row order, then match authored lines to them.
  groups: List[Tuple[Any, Any]] = []
  for row in rev:
    if not isinstance(row, dict):
      continue
    key = (row.get("lob"), row.get("product"))
    if key not in groups:
      groups.append(key)
  group_norm = _match_lines_to_groups(lines_normalized, groups)
  # Single-line fallback: if exactly one line authored, it applies to every row
  # (covers rows without lob/product identifiers).
  only_norm = lines_normalized[0]["normalized"] if len(lines_normalized) == 1 else None
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
    normalized = group_norm.get((row.get("lob"), row.get("product"))) or only_norm
    if normalized is None:
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

  # NOTE: the model-row reference is the CORRECT anchor source -- the K10
  # grid normalizes ops product anchors to QUARTERLY units (ops entries can
  # be per-week; using them raw here would mis-scale Q1 by the cadence
  # factor). Do not "helpfully" re-anchor from ops_json product entries.
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
    author_lines = _extract_author_lines(drivers)
    if not author_lines:
      violations = [{"code": "no_lines_of_business",
                     "message": "author at least one line of business, each with all 20 quarters."}]
      last_error = "no_author_lines"
      continue
    lines_normalized = [
      {
        "lob": ln.get("lob_name") or ln.get("lob"),
        "unit": ln.get("unit_name") or ln.get("unit"),
        "normalized": normalize_revenue_drivers(ln),
      }
      for ln in author_lines
    ]
    revenue_line = compute_total_revenue_line([x["normalized"] for x in lines_normalized])
    if sum(revenue_line) <= 0:
      violations = [{"code": "revenue_line_nonpositive",
                     "message": "computed revenue line is all zero — author positive price/capacity/utilization for every line."}]
      last_error = "revenue_line_nonpositive"
      continue
    applied = apply_authored_revenue_to_model_input(model_input_json, lines_normalized)
    return {
      "ok": True,
      "model_input_json": applied,
      "normalized": lines_normalized,
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
  "compute_total_revenue_line",
  "apply_authored_revenue_to_model_input",
  "current_revenue_reference",
]
