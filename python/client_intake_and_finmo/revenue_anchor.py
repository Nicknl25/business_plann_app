"""THE PLAN'S REVENUE, KEPT APART FROM HERS (Nick ruled 2026-09-14).

current_revenue holds only what the client said. The coherence walk's levers -
a price move, a volume move, custom prices, her retention answer - used to write
their result INTO that field, because the intake's own rescale would otherwise
scale the drivers straight back to her figure and undo the move she agreed. On
the store that rewrote her revenue on three real drafts: Dunmore & Tate
4,600,000 -> 3,450,000; Third Coast 630,000 -> 315,000; Green Meadow 700,000 ->
44,100.

So a lever moves THIS instead: financials._coherence.plan_revenue_anchor
  {value, stated, rule, moves: [{lever, from, to}]}
private (never a stated-fact leaf, never read back, not in door B's explained
set). It is read ONLY where the intake itself would undo an agreed lever: the
post-intro rescale, the walk's own line split, and the anchor-vs-ops hold. The
engine's Q1 anchor and the Q0 stub keep reading current_revenue - "the plan
starts at the level the operator actually reported"; the agreement reaches the
forecast as the solve's directive, and actuals are never edited.

Two rules, stated before the build (Cowork 1103):
  - no stated revenue above zero, no anchor: a pre-revenue business that said
    "nothing yet" plans on its drivers, through the fallbacks that already exist;
  - an anchor built on a stated figure she has since changed is stale and ignored.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

KEY = "plan_revenue_anchor"
RULE = "stated revenue x the ratio of each lever she agreed"


def _f(value: Any) -> Optional[float]:
  try:
    if value is None or isinstance(value, bool):
      return None
    return float(value)
  except (TypeError, ValueError):
    return None


def stated_revenue(financials_json: Optional[Dict[str, Any]]) -> Optional[float]:
  """Her figure, when she has stated one above zero."""
  v = _f((financials_json or {}).get("current_revenue"))
  return v if v is not None and v > 0 else None


def anchor_record(financials_json: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
  """The live anchor record: present, positive, and built on the figure she states now."""
  stated = stated_revenue(financials_json)
  rec = ((financials_json or {}).get("_coherence") or {}).get(KEY)
  if stated is None or not isinstance(rec, dict):
    return None
  value, on = _f(rec.get("value")), _f(rec.get("stated"))
  if value is None or value <= 0 or on is None or abs(on - stated) > max(0.005, abs(stated) * 1e-9):
    return None
  return rec


def plan_revenue(financials_json: Optional[Dict[str, Any]]) -> Optional[float]:
  """The revenue the INTAKE plans on: the live anchor when a lever she agreed moved
  it, else her stated revenue; None when she has stated none above zero."""
  rec = anchor_record(financials_json)
  if rec is not None:
    return float(rec["value"])
  return stated_revenue(financials_json)


def move_plan_revenue(financials_json: Optional[Dict[str, Any]], new_value: Any, *, lever: str) -> Dict[str, Any]:
  """Record a lever's move of the plan's revenue. current_revenue is never touched.
  With no stated revenue above zero nothing is recorded (the drivers carry the plan)."""
  nxt = dict(financials_json or {})
  stated = stated_revenue(nxt)
  nv = _f(new_value)
  if stated is None or nv is None or nv <= 0:
    return nxt
  old = plan_revenue(nxt)
  live = anchor_record(nxt) or {}
  coh = dict(nxt.get("_coherence") or {})
  coh[KEY] = {
    "value": round(nv, 2),
    "stated": stated,
    "rule": RULE,
    "moves": list(live.get("moves") or []) + [{"lever": str(lever), "from": old, "to": round(nv, 2)}],
  }
  nxt["_coherence"] = coh
  return nxt
