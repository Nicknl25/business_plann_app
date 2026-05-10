"""Phase 9 P3.5 — Schema + sanity validation for GPT exhaustion handler
output.

Two checks:
  1. Schema check — required fields, types match.
  2. Sanity check — numeric values in plausible ranges (price > 0,
     percentages between 0 and 1, capacity > 0, etc.).

The handler retries Call 2 / iteration call once on validation failure
with the validation error in-prompt; persistent failure falls through
to deterministic snap-in.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


_CALL_1_REQUIRED_KEYS = ("q1", "q11", "q20")

_CALL_2_DRIVER_KEYS = (
  "unit_price",
  "units_per_period_capacity",
  "utilization_rate",
  "payroll_dollars_per_quarter",
  "cogs_percent_of_revenue",
  "marketing_percent_of_revenue",
  "sga_percent_of_revenue",
)


def validate_call_1(parsed: Optional[Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
  if not isinstance(parsed, dict):
    return False, "call_1_payload_not_dict"
  anchors = parsed.get("ebitda_anchors")
  if not isinstance(anchors, dict):
    return False, "call_1_missing_ebitda_anchors"
  for k in _CALL_1_REQUIRED_KEYS:
    v = anchors.get(k)
    if v is None or not isinstance(v, (int, float)):
      return False, f"call_1_anchor_{k}_not_numeric"
    if not (-2.0 <= float(v) <= 2.0):
      return False, f"call_1_anchor_{k}_out_of_range_{v}"
  q11 = float(anchors.get("q11", 0.0))
  if q11 < -0.001:
    # Q11 must be >= 0 (binding viability). Tiny negative tolerance for
    # rounding; otherwise reject and ask GPT to retry.
    return False, f"call_1_q11_negative_violates_viability_{q11}"
  return True, None


def _sanity_anchor_three_tuple(
  *,
  driver_name: str,
  triple: Any,
  lower: float,
  upper: float,
  allow_zero: bool = False,
) -> Optional[str]:
  if not isinstance(triple, dict):
    return f"{driver_name}_not_dict"
  for k in _CALL_1_REQUIRED_KEYS:
    v = triple.get(k)
    if v is None or not isinstance(v, (int, float)):
      return f"{driver_name}_{k}_not_numeric"
    fv = float(v)
    if not allow_zero and fv == 0.0:
      return f"{driver_name}_{k}_is_zero_disallowed"
    if fv < lower or fv > upper:
      return f"{driver_name}_{k}_out_of_range_value={fv}_bounds=[{lower},{upper}]"
  return None


def validate_call_2(parsed: Optional[Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
  """Schema + sanity check on driver_anchors.

  Sanity ranges are intentionally wide — the goal is to catch GPT
  errors like price = $50 for a donut, cogs% = 5.0, capacity = -10. Not
  to enforce business judgment on the actual values.
  """
  if not isinstance(parsed, dict):
    return False, "call_2_payload_not_dict"
  anchors = parsed.get("driver_anchors")
  if not isinstance(anchors, dict):
    return False, "call_2_missing_driver_anchors"

  # Per-driver sanity bands.
  driver_bands: Dict[str, Dict[str, Any]] = {
    "unit_price": {"lower": 0.001, "upper": 1_000_000.0, "allow_zero": False},
    "units_per_period_capacity": {"lower": 1.0, "upper": 1.0e9, "allow_zero": False},
    "utilization_rate": {"lower": 0.0, "upper": 1.0, "allow_zero": True},
    "payroll_dollars_per_quarter": {"lower": 0.0, "upper": 1.0e9, "allow_zero": True},
    "cogs_percent_of_revenue": {"lower": 0.0, "upper": 1.0, "allow_zero": True},
    "marketing_percent_of_revenue": {"lower": 0.0, "upper": 1.0, "allow_zero": True},
    "sga_percent_of_revenue": {"lower": 0.0, "upper": 1.0, "allow_zero": True},
  }

  for driver_name in _CALL_2_DRIVER_KEYS:
    triple = anchors.get(driver_name)
    band = driver_bands[driver_name]
    err = _sanity_anchor_three_tuple(
      driver_name=driver_name,
      triple=triple,
      lower=float(band["lower"]),
      upper=float(band["upper"]),
      allow_zero=bool(band["allow_zero"]),
    )
    if err:
      return False, err

  # Cross-driver sanity: the three cost ratios shouldn't sum > 1.0 at
  # any anchor (would imply negative gross + opex margin, structurally
  # impossible).
  cogs = anchors.get("cogs_percent_of_revenue") or {}
  mkt = anchors.get("marketing_percent_of_revenue") or {}
  sga = anchors.get("sga_percent_of_revenue") or {}
  for q_key in _CALL_1_REQUIRED_KEYS:
    s = float(cogs.get(q_key, 0.0)) + float(mkt.get(q_key, 0.0)) + float(sga.get(q_key, 0.0))
    if s > 1.05:  # 5% slack for rounding
      return False, (
        f"call_2_cost_ratios_sum_exceeds_revenue_at_{q_key}: "
        f"cogs+mkt+sga={s:.3f}"
      )

  return True, None
