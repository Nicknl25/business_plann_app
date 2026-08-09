"""ENGINE WALLS the intake gate can SEE (walls table v1).

PHASE 3 of the live-truth architecture (Nick-approved sequence): the
gate today evaluates its own P&L inequalities, but the ENGINE enforces
additional acceptance walls the intake never discloses - a client can
converge at intake and die deterministically post-intake. Proven live
twice on the payroll-share tier policy (Sparrow x3 runs at 0.72 vs the
"high" class max 0.70; Peachtree).

DOCTRINE (engine frozen):
- This table MIRRORS engine policy; it never couples to it and never
  changes engine behavior. The values are literal copies of
  post_intake_headcount policy (lookup.py payroll_revenue_sanity_bounds)
  - the wall the payload validator enforces raw (no tolerance) in
  post_intake_amalgamated/tools/set_payroll_schedule.py
  _check_band_violations.
- A CONSISTENCY TRIPWIRE compares the mirror against the live policy at
  first use per process: on drift the mirror is reported stale (loud
  log + note in the wall result) so the two can never silently diverge
  - honesty without coupling.
- The wall tests the STATED YEAR-1 ratio (annual payroll / annual
  revenue anchor) because that is the exact number the engine judges
  (round-1 clamps the stated ratio; the schedule validator rejects the
  contract target outside the class band). The gate's Q11 point would
  understate the ratio under growth and miss the kill.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

_LOGGER = logging.getLogger("intake_coherence.walls")

# MIRROR of post_intake_headcount lookup.py payroll_revenue_sanity_bounds
# (literal copy - see module doctrine; the tripwire keeps this honest).
PAYROLL_SHARE_CLASS_BOUNDS: Dict[str, Dict[str, float]] = {
  "low": {"min_pct": 0.06, "max_pct": 0.45},
  "medium": {"min_pct": 0.10, "max_pct": 0.55},
  "high": {"min_pct": 0.16, "max_pct": 0.70},
  "expert": {"min_pct": 0.18, "max_pct": 0.80},
}

LABOR_INTENSITY_CLASSES = tuple(PAYROLL_SHARE_CLASS_BOUNDS.keys())

_TRIPWIRE_RESULT: Optional[Dict[str, Any]] = None


def walls_mirror_tripwire() -> Dict[str, Any]:
  """Compare the mirrored bounds against the LIVE engine policy once per
  process. Returns {"ok": bool, "drift": {...}} - drift is loud-logged.
  A policy read failure is reported (never raised): the mirror keeps
  working on its literals; the tripwire's job is only honesty."""
  global _TRIPWIRE_RESULT
  if _TRIPWIRE_RESULT is not None:
    return _TRIPWIRE_RESULT
  drift: Dict[str, Any] = {}
  try:
    from client_intake_and_finmo.post_intake_headcount.lookup import (
      post_intake_headcount_policy_for,
    )
    policy = post_intake_headcount_policy_for() or {}
    live = policy.get("payroll_revenue_sanity_bounds")
    live = live if isinstance(live, dict) else {}
    for cls, mirrored in PAYROLL_SHARE_CLASS_BOUNDS.items():
      lb = live.get(cls) if isinstance(live.get(cls), dict) else {}
      for bound_key in ("min_pct", "max_pct"):
        lv = lb.get(bound_key)
        if lv is None or abs(float(lv) - mirrored[bound_key]) > 1e-9:
          drift[f"{cls}.{bound_key}"] = {"mirror": mirrored[bound_key], "policy": lv}
    for cls in live:
      if cls not in PAYROLL_SHARE_CLASS_BOUNDS:
        drift[f"{cls}"] = {"mirror": None, "policy": live.get(cls)}
  except Exception as exc:  # policy unreadable: report, don't die
    drift["_policy_read_error"] = str(exc)[:300]
  if drift:
    _LOGGER.error(
      "WALLS MIRROR DRIFT - intake walls table no longer matches engine "
      "payroll policy; the mirror must be re-copied: %s", drift,
    )
  _TRIPWIRE_RESULT = {"ok": not drift, "drift": drift}
  return _TRIPWIRE_RESULT


def payroll_share_wall(
  *,
  labor_intensity_class: Optional[str],
  payroll_annual: Optional[float],
  revenue_annual: Optional[float],
) -> Optional[Dict[str, Any]]:
  """The payroll-share tier wall, on the engine's own judged basis.

  Returns None when the wall cannot be evaluated (no judged class, or
  no stated payroll/revenue) - absence of judgment is never a verdict.
  Otherwise returns:
    {"passed", "value", "max_pct", "min_pct", "class",
     "revenue_to_clear" (annual revenue at which the stated payroll
     obeys the class max), "payroll_to_clear" (annual payroll at which
     the stated revenue obeys it), "mirror_ok"}
  """
  cls = str(labor_intensity_class or "").strip().lower()
  band = PAYROLL_SHARE_CLASS_BOUNDS.get(cls)
  if not band:
    return None
  try:
    pay = float(payroll_annual or 0.0)
    rev = float(revenue_annual or 0.0)
  except (TypeError, ValueError):
    return None
  if pay <= 0.0 or rev <= 0.0:
    return None
  share = pay / rev
  max_pct = float(band["max_pct"])
  tripwire = walls_mirror_tripwire()
  return {
    "passed": share <= max_pct,
    "value": round(share, 6),
    "max_pct": max_pct,
    "min_pct": float(band["min_pct"]),
    "class": cls,
    "revenue_to_clear": round(pay / max_pct, 2),
    "payroll_to_clear": round(rev * max_pct, 2),
    "mirror_ok": bool(tripwire.get("ok")),
  }
