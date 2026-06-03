"""Tier 2 — absolute viability gates (Fix #1 spec §3, §4.1b, §4.3, §7).

The gates OWN viability (binary pass/fail). They are firm-internal — no
peer percentile. Failing either gate => the plan is non-viable regardless
of the Tier-1 grade.

GATE A (breakeven): sustained EBITDA-positive (trailing-4-quarter window,
  NOT a single-quarter snapshot) by BUSINESS-quarter-10, age-anchored to
  business_start_date.
    - Deadline is in BUSINESS quarters; the plan's quarters are not the
      firm's first quarters, so deadline_plan_q = 10 - quarters_elapsed.
    - Expanding window before 4 quarters of plan data exist (Q1-Q3 use the
      trailing-available mean); the gate cannot FAIL before business-Q4.
    - +4 quarters (-> business-Q14) under a genuine turnaround posture (§4.3).
    - 2-quarter grace floor for firms already past business-Q10 at plan-Q1.

GATE B (cumulative): cumulative EBITDA >= 0 by Q20. FIRM — posture-independent.

Deadlines/grace are STRUCTURAL constants (locked §3/§7), exposed as
documented-default params, not calibration knobs (those live in policy.py).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .constructs import _f, cumulative_ebitda_series, live_quarter_rows

# Structural constants (locked).
GATE_A_BASE_DEADLINE_BUSINESS_Q = 10          # breakeven by business-Q10
GATE_A_DISTRESS_DEADLINE_EXTENSION_Q = 4      # +4 -> business-Q14 under turnaround
GATE_A_GRACE_PLAN_Q = 2                       # grace floor for firms past business-Q10
GATE_A_MIN_BUSINESS_Q_TO_FIRE = 4             # cannot fail before business-Q4
TRAILING_WINDOW_Q = 4                         # trailing window length (expanding before it fills)
HORIZON_Q = 20


def _trailing_sum(values: List[Optional[float]], end_idx: int) -> Optional[float]:
  """Trailing-window EBITDA sum ending at 0-based end_idx (expanding before
  the window fills). None when no values in the window are known."""
  start = max(0, end_idx - (TRAILING_WINDOW_Q - 1))
  window = [v for v in values[start:end_idx + 1] if v is not None]
  if not window:
    return None
  return sum(window)


def gate_a_deadline_plan_quarter(
  *,
  business_age_quarters: Optional[int],
  distress: bool = False,
) -> int:
  """Plan-quarter by which sustained breakeven must be achieved.

  deadline_business_q (10, or 14 under distress) translated to plan space by
  subtracting quarters already elapsed; floored at the 2-quarter grace for
  firms at/past the business deadline; capped at the 20-quarter horizon.
  """
  deadline_business = GATE_A_BASE_DEADLINE_BUSINESS_Q + (
    GATE_A_DISTRESS_DEADLINE_EXTENSION_Q if distress else 0
  )
  elapsed = int(business_age_quarters) if business_age_quarters is not None else 0
  deadline_plan = deadline_business - elapsed
  if deadline_plan < GATE_A_GRACE_PLAN_Q:
    deadline_plan = GATE_A_GRACE_PLAN_Q
  return min(deadline_plan, HORIZON_Q)


def evaluate_gate_a(
  rows: List[Dict[str, Any]],
  *,
  business_age_quarters: Optional[int],
  distress: bool = False,
) -> Dict[str, Any]:
  """Sustained-EBITDA-positive-by-deadline gate.

  Passes if the trailing-window EBITDA sum is >= 0 at some plan-quarter at or
  before the deadline (and not before business-Q4). Returns provenance.
  """
  ebitda = [_f(r.get("ebitda")) for r in rows]
  n = len(rows)
  elapsed = int(business_age_quarters) if business_age_quarters is not None else 0
  deadline_plan = gate_a_deadline_plan_quarter(
    business_age_quarters=business_age_quarters, distress=distress
  )
  breakeven_plan_q: Optional[int] = None
  for i in range(n):
    plan_q = i + 1
    if plan_q > deadline_plan:
      break
    business_q = elapsed + plan_q
    if business_q < GATE_A_MIN_BUSINESS_Q_TO_FIRE:
      continue  # cannot fire before business-Q4
    tsum = _trailing_sum(ebitda, i)
    if tsum is not None and tsum >= 0.0:
      breakeven_plan_q = plan_q
      break
  # If there is no plan data at/after the deadline yet, the gate is
  # indeterminate rather than failed (no silent fail on missing data).
  evaluable = any(
    (elapsed + (i + 1)) >= GATE_A_MIN_BUSINESS_Q_TO_FIRE and ebitda[i] is not None
    for i in range(min(n, deadline_plan))
  )
  passed = breakeven_plan_q is not None
  return {
    "gate": "A_breakeven",
    "passed": passed,
    "evaluable": evaluable,
    "deadline_business_q": GATE_A_BASE_DEADLINE_BUSINESS_Q + (GATE_A_DISTRESS_DEADLINE_EXTENSION_Q if distress else 0),
    "deadline_plan_q": deadline_plan,
    "business_age_quarters": elapsed,
    "distress_applied": bool(distress),
    "breakeven_plan_q": breakeven_plan_q,
    "breakeven_business_q": (elapsed + breakeven_plan_q) if breakeven_plan_q else None,
    "basis": "trailing_4q_sum_ge_0 (expanding before 4q)",
  }


def evaluate_gate_b(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
  """Cumulative EBITDA >= 0 by the final (Q20) quarter. Posture-independent."""
  cum = cumulative_ebitda_series(rows)
  final = next((c["cumulative_ebitda"] for c in reversed(cum) if c["cumulative_ebitda"] is not None), None)
  final_q = cum[-1]["quarter_index"] if cum else None
  passed = final is not None and final >= 0.0
  return {
    "gate": "B_cumulative",
    "passed": bool(passed),
    "evaluable": final is not None,
    "cumulative_ebitda_final": final,
    "final_quarter": final_q,
  }


def evaluate_gates(
  finmo_json: Optional[Dict[str, Any]],
  *,
  business_age_quarters: Optional[int],
  distress: bool = False,
) -> Dict[str, Any]:
  """Both Tier-2 gates. all_pass requires both to pass."""
  rows = live_quarter_rows(finmo_json)
  gate_a = evaluate_gate_a(rows, business_age_quarters=business_age_quarters, distress=distress)
  gate_b = evaluate_gate_b(rows)
  return {
    "gate_a": gate_a,
    "gate_b": gate_b,
    "all_pass": bool(gate_a["passed"] and gate_b["passed"]),
  }
