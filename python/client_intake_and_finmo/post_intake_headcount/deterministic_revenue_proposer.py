"""Deterministic revenue-driver proposer (Python proposes; GPT critiques).

The GPT revenue author (gpt_revenue_author) authors the per-quarter revenue
drivers from scratch on gpt-5.1 -- a reasoning model that does not honor `seed`,
so the AUTHORED LEVEL drifts run-to-run (and drifts BELOW the operator's real
revenue, e.g. Q4 ~94k when current_revenue is ~252k/quarter). Once the level is
unanchored, the trajectory swings ~3.4x across identical-input runs, and the
authored curve step-changes (the ~30% Q6 cliff that blows through the model's
own QoQ cap).

This proposer replaces that free authoring with a DETERMINISTIC trajectory
(same inputs -> same drivers, every run), matching the "Python proposes
structure; GPT critiques structure" doctrine:

  * ANCHOR the Q1 level to the intake-baseline (operator-grounded) reference --
    never author the level from scratch.
  * GROW at a deterministic, tapering QoQ rate that never exceeds the stated
    QoQ cap -- so the curve is SMOOTH by construction (no single-quarter cliff).
  * ALLOCATE the growth across the three drivers deterministically: unit_price
    at slow inflation, utilization ramping to a mature ceiling, capacity
    absorbing the remainder (capacity x price x utilization == revenue exactly).

It is a drop-in for ``gpt_author_revenue_drivers_once`` (same
``{ok, drivers, error}`` return, same ``lines_of_business`` shape consumed by
``revenue_authoring._extract_author_lines``), so ``run_revenue_authoring_pass``
uses it via the ``_author_fn`` seam with no other change. The existing
``solver_input.revenue_authored=True`` lock then carries the deterministic
trajectory through the solver/cascade to the final finmo unchanged.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

_HORIZON = 20

# Deterministic growth defaults (fractions of revenue, per quarter). qoq_max is
# the QoQ growth CAP the trajectory must never exceed; qoq_start/qoq_end define a
# gentle taper (fast-but-capped early growth easing to a mature rate) so the
# curve is smooth and front-loaded like a real ramp without ever spiking. These
# are conservative, industry-plausible defaults; a caller may override them with
# NAICS-cohort qoq band values (still deterministic).
_DEFAULT_QOQ_MAX = 0.07
_DEFAULT_QOQ_START = 0.06
_DEFAULT_QOQ_END = 0.025
# Unit-price drift (slow, inflation-like) and utilization ramp shape.
_DEFAULT_PRICE_INFLATION_QOQ = 0.01
_DEFAULT_MATURE_UTILIZATION = 0.85
_UTILIZATION_RAMP_QUARTERS = 10  # reach the mature ceiling by ~Q11, then hold


def _f(value: Any) -> Optional[float]:
  try:
    if value is None:
      return None
    return float(value)
  except (TypeError, ValueError):
    return None


def _anchor_from_reference_entry(entry: Dict[str, Any]) -> Optional[Dict[str, float]]:
  """Pull the Q1 (capacity, unit_price, utilization) anchor from one reference
  line. Returns None when the line lacks a usable positive Q1 revenue."""
  def _q1(field: str) -> Optional[float]:
    block = entry.get(field)
    if isinstance(block, dict):
      return _f(block.get("q1"))
    return _f(block)
  cap = _q1("capacity_units_per_period")
  price = _q1("unit_price")
  util = _q1("utilization_rate")
  if cap is None or price is None or util is None:
    return None
  cap = max(0.0, cap)
  price = max(0.0, price)
  util = min(1.0, max(0.0, util))
  if cap * price * util <= 0.0:
    return None
  return {"capacity_units_per_period": cap, "unit_price": price, "utilization_rate": util}


def _quarterly_growth(qoq_start: float, qoq_max: float, qoq_end: float) -> List[float]:
  """Per-quarter growth fractions g[2..20] (g[1]=0), tapering start->end, each
  clamped to the QoQ cap so no quarter can spike through it."""
  cap = max(0.0, float(qoq_max))
  start = min(max(0.0, float(qoq_start)), cap)
  end = min(max(0.0, float(qoq_end)), cap)
  growth = [0.0]  # q1 has no prior quarter
  span = float(_HORIZON - 2) or 1.0
  for q in range(2, _HORIZON + 1):
    frac = (q - 2) / span  # 0.0 at q2 -> 1.0 at q20
    g = start * (1.0 - frac) + end * frac
    growth.append(min(g, cap))
  return growth


def propose_revenue_drivers_deterministic(
  *,
  current_revenue_reference: Optional[List[Dict[str, Any]]] = None,
  anchor_q1_revenue_total: Optional[float] = None,
  qoq_max: float = _DEFAULT_QOQ_MAX,
  qoq_start: float = _DEFAULT_QOQ_START,
  qoq_end: float = _DEFAULT_QOQ_END,
  price_inflation_qoq: float = _DEFAULT_PRICE_INFLATION_QOQ,
  mature_utilization: float = _DEFAULT_MATURE_UTILIZATION,
  **_ignored: Any,
) -> Dict[str, Any]:
  """Deterministically propose per-LOB revenue drivers. Drop-in for
  ``gpt_author_revenue_drivers_once`` -- returns ``{ok, drivers, error}`` with
  the ``lines_of_business`` shape. ``**_ignored`` absorbs the GPT author's other
  kwargs (compact, failing_state, previous_violations, model, seed, _http).

  ``anchor_q1_revenue_total``: when provided (the operator's stated
  ``current_revenue`` / 4), the whole Q1 level is rescaled so total Q1 revenue
  equals it -- the plan starts at the operator's STATED current revenue, not the
  intake baseline (which can over-state it). The per-LOB mix and each line's
  price/utilization are preserved; only the Q1 capacity level is scaled."""
  reference = current_revenue_reference if isinstance(current_revenue_reference, list) else []
  growth = _quarterly_growth(qoq_start, qoq_max, qoq_end)

  # Rescale factor so total Q1 revenue matches the operator's stated anchor.
  anchor_scale = 1.0
  target_total = _f(anchor_q1_revenue_total)
  if target_total is not None and target_total > 0.0:
    reference_total_q1 = 0.0
    for entry in reference:
      if isinstance(entry, dict):
        a = _anchor_from_reference_entry(entry)
        if a is not None:
          reference_total_q1 += a["capacity_units_per_period"] * a["unit_price"] * a["utilization_rate"]
    if reference_total_q1 > 0.0:
      anchor_scale = target_total / reference_total_q1
      # Float hygiene: an anchor that already matches the intake baseline
      # (e.g. derived from the same stated cogs/marketing pair the baseline
      # was built from) must not perturb the drivers by an ulp and re-key
      # the downstream response locks.
      if abs(anchor_scale - 1.0) <= 1e-9:
        anchor_scale = 1.0
      # CW-033 (Nick's retraction ruling): reconciling the Q1 level to
      # the client's stated revenue - capacity absorbing the factor - is
      # BY DESIGN; the briefly-added 0.5% keep-declared-drivers epsilon
      # is reverted. What remains is visibility: a non-unity factor is
      # stamped into the returned drivers (anchor_reconcile below), so
      # the reconcile is never silent to a reader of the model.

  lines: List[Dict[str, Any]] = []
  for entry in reference:
    if not isinstance(entry, dict):
      continue
    anchor = _anchor_from_reference_entry(entry)
    if anchor is None:
      continue
    price1 = anchor["unit_price"]
    util1 = anchor["utilization_rate"]
    capacity1 = anchor["capacity_units_per_period"] * anchor_scale
    revenue_q1 = capacity1 * price1 * util1
    quarters: List[Dict[str, Any]] = []
    revenue = revenue_q1
    prev_capacity = 0.0
    for q in range(1, _HORIZON + 1):
      if q > 1:
        revenue = revenue * (1.0 + growth[q - 1])
      # unit_price: slow, deterministic inflation off the anchor.
      price = price1 * ((1.0 + price_inflation_qoq) ** (q - 1))
      # utilization: linear ramp from the anchor to the mature ceiling, then flat.
      if q - 1 >= _UTILIZATION_RAMP_QUARTERS:
        util = max(util1, mature_utilization)
      else:
        frac = (q - 1) / float(_UTILIZATION_RAMP_QUARTERS)
        util = util1 + (max(util1, mature_utilization) - util1) * frac
      util = min(1.0, max(0.0, util))
      # capacity absorbs the remainder so capacity*price*util == revenue exactly.
      denom = price * util
      # capacity absorbs the remainder so capacity x price x util == revenue
      # EXACTLY -- but capacity must be non-decreasing (the driver contract).
      # For a line whose price*utilization drifts faster than the revenue
      # growth (e.g. a low-anchor-utilization line whose utilization ramp
      # alone exceeds the QoQ cap), the exact capacity would DIP; if we let
      # the normalizer clamp it back up, the line's revenue would grow above
      # the cap. Instead hold capacity flat and absorb the difference into
      # UTILIZATION (free to move in [0, 1]) so revenue stays exactly on the
      # capped trajectory.
      exact_capacity = (revenue / denom) if denom > 0.0 else capacity1
      capacity = max(prev_capacity, exact_capacity) if q > 1 else exact_capacity
      if capacity > exact_capacity and capacity * price > 0.0:
        util = revenue / (capacity * price)
      prev_capacity = capacity
      quarters.append({
        "q": q,
        "unit_price": round(price, 6),
        "capacity_units_per_period": round(capacity, 6),
        "utilization_rate": round(min(1.0, max(0.0, util)), 6),
      })
    line: Dict[str, Any] = {"quarters": quarters}
    if entry.get("lob"):
      line["lob_name"] = entry.get("lob")
    if entry.get("unit"):
      line["unit_name"] = entry.get("unit")
    lines.append(line)

  if not lines:
    return {"ok": False, "drivers": None, "error": "deterministic_proposer_no_reference_lines"}
  drivers: Dict[str, Any] = {"lines_of_business": lines}
  if anchor_scale != 1.0:
    # CW-033 A-113: a capacity-rescaling anchor factor is never silent -
    # the provenance rides the drivers so any reader (and any auditor)
    # can see that Q1 capacities were scaled to the stated revenue.
    drivers["anchor_reconcile"] = {
      "factor": round(anchor_scale, 9),
      "basis": "stated_revenue_anchor",
      "applied_to": "q1_capacity_all_lines",
    }
  return {"ok": True, "drivers": drivers, "error": None}


__all__ = ["propose_revenue_drivers_deterministic"]
