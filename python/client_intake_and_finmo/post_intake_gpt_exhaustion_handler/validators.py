"""Phase 9 P3.5 — Sanity validation for the tool-calling session's final
commit payload.

The OpenAI Responses API enforces JSON-Schema validity on the commit
output. This module validates the *values* — that anchor numbers fall
in plausible ranges (price > 0, percentages in [0,1], capacity > 0),
catching GPT errors like price=$50 for a donut, cogs%=5.0, capacity<0.
The tool-calling loop already gives GPT continuous feedback on the
viability checks, so the value bands here are deliberately wide.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


_ANCHOR_KEYS = ("q1", "q11", "q20")

_DRIVER_KEYS = (
  "unit_price",
  "units_per_period_capacity",
  "utilization_rate",
  "payroll_dollars_per_quarter",
  "cogs_percent_of_revenue",
  "marketing_percent_of_revenue",
  "sga_percent_of_revenue",
)


# Phase 9 P3.6 — working capital driver sanity bands. Single value
# per driver (not 3-anchor). Bands intentionally wide.
_WC_BANDS: Dict[str, Dict[str, float]] = {
  "accounts_receivable_days": {"lower": 0.0, "upper": 365.0},
  "accounts_payable_days": {"lower": 0.0, "upper": 365.0},
  "inventory_days": {"lower": 0.0, "upper": 365.0},
  "deferred_revenue_percent_of_revenue": {"lower": 0.0, "upper": 1.0},
  "prepaid_expenses_percent_of_revenue": {"lower": 0.0, "upper": 1.0},
}


def _check_triple(
  *,
  driver_name: str,
  triple: Any,
  lower: float,
  upper: float,
  allow_zero: bool,
) -> Optional[str]:
  if not isinstance(triple, dict):
    return f"{driver_name}_not_dict"
  for k in _ANCHOR_KEYS:
    v = triple.get(k)
    if v is None or not isinstance(v, (int, float)):
      return f"{driver_name}_{k}_not_numeric"
    fv = float(v)
    if not allow_zero and fv == 0.0:
      return f"{driver_name}_{k}_is_zero_disallowed"
    if fv < lower or fv > upper:
      return (
        f"{driver_name}_{k}_out_of_range_value={fv}_bounds=[{lower},{upper}]"
      )
  return None


def validate_final_commit(
  parsed: Optional[Dict[str, Any]]
) -> Tuple[bool, Optional[str]]:
  """Validate GPT's final commit payload (driver_anchors + reasoning).

  Sanity ranges are intentionally wide — the tool-calling loop already
  enforces viability via the trajectory pass/fail feedback; this catches
  hard errors only.
  """
  if not isinstance(parsed, dict):
    return False, "commit_payload_not_dict"
  anchors = parsed.get("driver_anchors")
  if not isinstance(anchors, dict):
    return False, "commit_missing_driver_anchors"

  bands: Dict[str, Dict[str, Any]] = {
    "unit_price": {"lower": 0.001, "upper": 1_000_000.0, "allow_zero": False},
    "units_per_period_capacity": {"lower": 1.0, "upper": 1.0e9, "allow_zero": False},
    "utilization_rate": {"lower": 0.0, "upper": 1.0, "allow_zero": True},
    "payroll_dollars_per_quarter": {"lower": 0.0, "upper": 1.0e9, "allow_zero": True},
    "cogs_percent_of_revenue": {"lower": 0.0, "upper": 1.0, "allow_zero": True},
    "marketing_percent_of_revenue": {"lower": 0.0, "upper": 1.0, "allow_zero": True},
    "sga_percent_of_revenue": {"lower": 0.0, "upper": 1.0, "allow_zero": True},
  }

  for driver_name in _DRIVER_KEYS:
    band = bands[driver_name]
    err = _check_triple(
      driver_name=driver_name,
      triple=anchors.get(driver_name),
      lower=float(band["lower"]),
      upper=float(band["upper"]),
      allow_zero=bool(band["allow_zero"]),
    )
    if err:
      return False, err

  cogs = anchors.get("cogs_percent_of_revenue") or {}
  mkt = anchors.get("marketing_percent_of_revenue") or {}
  sga = anchors.get("sga_percent_of_revenue") or {}
  for q_key in _ANCHOR_KEYS:
    s = (
      float(cogs.get(q_key, 0.0))
      + float(mkt.get(q_key, 0.0))
      + float(sga.get(q_key, 0.0))
    )
    if s > 1.05:
      return False, (
        f"commit_cost_ratios_sum_exceeds_revenue_at_{q_key}: "
        f"cogs+mkt+sga={s:.3f}"
      )

  # Phase 9 P3.6 — working capital drivers (single value each).
  wc = anchors.get("working_capital_drivers")
  if not isinstance(wc, dict):
    return False, "commit_missing_working_capital_drivers"
  for wc_key, band in _WC_BANDS.items():
    v = wc.get(wc_key)
    if v is None or not isinstance(v, (int, float)):
      return False, f"wc_{wc_key}_not_numeric"
    fv = float(v)
    lo = float(band["lower"])
    hi = float(band["upper"])
    if fv < lo or fv > hi:
      return False, (
        f"wc_{wc_key}_out_of_range_value={fv}_bounds=[{lo},{hi}]"
      )

  return True, None
