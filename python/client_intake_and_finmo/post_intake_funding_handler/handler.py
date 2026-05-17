"""Iter 19 Stage 4 — Cash-funding handler orchestrator.

Public entry point: :func:`run_funding_handler`. Called when the Python
cash-strategy proposer's output trips ``cash_buffer_violations`` at
post-pass validation.

Per docs/architecture/doctrine.md §5 the handler has six invariants:

1. **Module location**: this package
   (``post_intake_funding_handler``).
2. **Defined authority**: the funding levers enumerated in
   :data:`FUNDING_LEVER_AUTHORITY`. NOT operating-side levers (those
   belong to the exhaustion handler).
3. **Tool-call budget**: ``HARD_CAP_TOOL_CALLS = 10`` per
   :mod:`tool_calling_session`.
4. **Run-budget decoupling**: ``counts_against_run_budget=False`` (iter
   17). Implemented in :mod:`tool_calling_session` for the GPT-driven
   variant.
5. **Specific validator trigger**: non-empty
   ``cash_buffer_violations``.
6. **Specific hard-fail diagnostic**: :class:`FundingHandlerStatus`
   ``EXHAUSTED`` paired with the precise per-quarter residual gap so
   the operator can identify the unfixable cell.

This iter (19) ships the deterministic correction engine. The GPT
tool-calling variant is scaffolded in :mod:`tool_calling_session` and
:mod:`prompts` but not wired into the production engagement path —
that wiring is the next iter's work and is intentionally deferred to
keep the architecture conversion testable in unit + smoke scope.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)


HORIZON_QUARTERS = 20


# Lever IDs the funding handler is authorized to author. Mirrors
# docs/architecture/doctrine.md §6 row "Funding".
FUNDING_LEVER_AUTHORITY: Tuple[str, ...] = (
  "schedules::Debt Issuance (New Borrowing)",
  "schedules::Debt Repayment (Scheduled)",
  "balance_sheet::Owner's Capital",
  "balance_sheet::Other Equity",
  "balance_sheet::Distributions",
)


# Allocation priority order when filling a buffer gap. Debt issuance
# is preferred for short-term fills (interest-bearing but reversible);
# owner's capital and other equity come next; distributions last
# (negative adjustment — pull back planned distributions).
_FUNDING_ALLOCATION_PRIORITY: Tuple[Tuple[str, str], ...] = (
  ("schedules::Debt Issuance (New Borrowing)", "increase"),
  ("balance_sheet::Owner's Capital", "increase"),
  ("balance_sheet::Other Equity", "increase"),
  ("balance_sheet::Distributions", "decrease"),
)


class FundingHandlerStatus(Enum):
  """Outcome of a handler invocation."""

  # Handler authored funding lever changes that closed every
  # cash_buffer_violation. Cash strategy should re-validate and proceed.
  RESOLVED = "resolved"

  # Handler authored some changes but at least one violation remains.
  # Caller should hard-fail with the specific residual diagnostic.
  PARTIALLY_RESOLVED = "partially_resolved"

  # Handler exhausted its tool-call budget without resolving all
  # violations. Hard-fail with the specific diagnostic.
  EXHAUSTED = "exhausted"

  # Handler was invoked with no violations to resolve (no-op).
  NO_VIOLATIONS = "no_violations"


@dataclass
class FundingHandlerResult:
  """Structured result returned by :func:`run_funding_handler`."""

  status: FundingHandlerStatus
  authored_lever_changes: Dict[str, Dict[int, float]] = field(default_factory=dict)
  residual_violations: List[Dict[str, Any]] = field(default_factory=list)
  tool_calls_used: int = 0
  diagnostic: str = ""

  def to_dict(self) -> Dict[str, Any]:
    return {
      "status": self.status.value,
      "authored_lever_changes": {
        lever_id: dict(per_quarter) for lever_id, per_quarter in self.authored_lever_changes.items()
      },
      "residual_violations": list(self.residual_violations),
      "tool_calls_used": int(self.tool_calls_used),
      "diagnostic": self.diagnostic,
    }


def _violation_quarter_index(violation: Dict[str, Any]) -> int:
  try:
    return int(float(violation.get("quarter_index") or 0))
  except Exception:
    return 0


def _violation_shortfall(violation: Dict[str, Any]) -> float:
  """Required additional funding for the quarter, in dollars."""
  try:
    buffer = float(violation.get("buffer") or 0.0)
  except Exception:
    buffer = 0.0
  try:
    ending_cash = float(violation.get("ending_cash") or 0.0)
  except Exception:
    ending_cash = 0.0
  return max(0.0, buffer - ending_cash)


def _bounds_for_lever_quarter(
  lever_bounds: Dict[str, List[Dict[str, Any]]],
  lever_id: str,
  quarter_index: int,
) -> Optional[Dict[str, Any]]:
  rows = lever_bounds.get(lever_id) or []
  for row in rows:
    if not isinstance(row, dict):
      continue
    try:
      qi = int(float(row.get("quarter_index") or 0))
    except Exception:
      continue
    if qi == quarter_index:
      return row
  return None


def _headroom(
  lever_bounds: Dict[str, List[Dict[str, Any]]],
  lever_id: str,
  quarter_index: int,
  direction: str,
) -> float:
  """Compute available headroom for the given lever/quarter.

  ``direction`` = "increase": ``max_value - current_value``.
  ``direction`` = "decrease": ``current_value - min_value``.
  Returns 0.0 when the bounds row is missing or invalid.
  """
  row = _bounds_for_lever_quarter(lever_bounds, lever_id, quarter_index)
  if row is None:
    return 0.0
  try:
    current = float(row.get("current_value") or 0.0)
  except Exception:
    current = 0.0
  try:
    max_value = float(row.get("max_value") or 0.0)
  except Exception:
    max_value = 0.0
  try:
    min_value = float(row.get("min_value") or 0.0)
  except Exception:
    min_value = 0.0
  if direction == "increase":
    return max(0.0, max_value - current)
  if direction == "decrease":
    return max(0.0, current - min_value)
  return 0.0


def _resolve_quarter(
  *,
  quarter_index: int,
  shortfall: float,
  lever_bounds: Dict[str, List[Dict[str, Any]]],
) -> Tuple[Dict[str, float], float]:
  """Deterministic per-quarter allocator.

  Walks :data:`_FUNDING_ALLOCATION_PRIORITY` and fills the shortfall by
  incrementing/decrementing levers up to their per-quarter headroom.
  Returns a (lever_id -> dollars) dict and the residual shortfall
  that could not be allocated.
  """
  authored: Dict[str, float] = {}
  remaining = float(shortfall)
  for lever_id, direction in _FUNDING_ALLOCATION_PRIORITY:
    if remaining <= 0.0:
      break
    headroom = _headroom(lever_bounds, lever_id, quarter_index, direction)
    if headroom <= 0.0:
      continue
    take = min(headroom, remaining)
    signed = take if direction == "increase" else -take
    authored[lever_id] = round(signed, 2)
    remaining -= take
  return authored, max(0.0, remaining)


def run_funding_handler(
  *,
  cash_buffer_violations: List[Dict[str, Any]],
  lever_bounds: Optional[Dict[str, List[Dict[str, Any]]]] = None,
  tool_call_budget: int = 10,
) -> FundingHandlerResult:
  """Run the funding handler against a set of cash-buffer violations.

  Deterministic per-quarter allocator: each violation is filled with
  funding levers in :data:`_FUNDING_ALLOCATION_PRIORITY` order, capped
  at the per-quarter ``lever_bounds`` headroom. When all violations
  are filled, returns :attr:`FundingHandlerStatus.RESOLVED`. When at
  least one residual gap remains, returns
  :attr:`FundingHandlerStatus.EXHAUSTED` paired with the precise
  residual list so callers can hard-fail with a specific diagnostic.

  ``tool_call_budget`` is honored as the maximum number of quarters
  the handler attempts to resolve in one invocation; mirrors the
  exhaustion handler's :data:`HARD_CAP_TOOL_CALLS`. In the
  deterministic path each violation consumes one budget unit. The
  GPT-driven variant (scaffolded in :mod:`tool_calling_session`) will
  consume one unit per ``compute_full_trajectory`` probe.
  """
  bounds = lever_bounds if isinstance(lever_bounds, dict) else {}
  violations = [v for v in (cash_buffer_violations or []) if isinstance(v, dict)]
  if not violations:
    return FundingHandlerResult(
      status=FundingHandlerStatus.NO_VIOLATIONS,
      diagnostic="no_cash_buffer_violations_to_resolve",
    )

  authored_changes: Dict[str, Dict[int, float]] = {}
  residual: List[Dict[str, Any]] = []
  tool_calls_used = 0

  for violation in violations:
    if tool_calls_used >= int(tool_call_budget):
      remaining = violations[violations.index(violation):]
      for rv in remaining:
        residual.append({
          "quarter_index": _violation_quarter_index(rv),
          "shortfall": round(_violation_shortfall(rv), 2),
          "reason": "tool_call_budget_exhausted",
        })
      return FundingHandlerResult(
        status=FundingHandlerStatus.EXHAUSTED,
        authored_lever_changes=authored_changes,
        residual_violations=residual,
        tool_calls_used=tool_calls_used,
        diagnostic=(
          "funding_handler_tool_call_budget_exhausted: "
          f"violations_resolved={tool_calls_used} of {len(violations)}; "
          "see residual_violations for the unresolved quarters."
        ),
      )
    tool_calls_used += 1
    quarter_index = _violation_quarter_index(violation)
    shortfall = _violation_shortfall(violation)
    if shortfall <= 0.0:
      continue
    per_quarter, residual_shortfall = _resolve_quarter(
      quarter_index=quarter_index,
      shortfall=shortfall,
      lever_bounds=bounds,
    )
    for lever_id, amount in per_quarter.items():
      authored_changes.setdefault(lever_id, {})[quarter_index] = float(amount)
    if residual_shortfall > 0.0:
      residual.append({
        "quarter_index": quarter_index,
        "shortfall": round(residual_shortfall, 2),
        "reason": "all_funding_lever_headroom_exhausted",
        "considered_levers": [lever_id for lever_id, _ in _FUNDING_ALLOCATION_PRIORITY],
      })

  if residual:
    return FundingHandlerResult(
      status=FundingHandlerStatus.EXHAUSTED,
      authored_lever_changes=authored_changes,
      residual_violations=residual,
      tool_calls_used=tool_calls_used,
      diagnostic=(
        "funding_handler_residual_buffer_violations: "
        f"{len(residual)} quarter(s) could not be filled within their "
        "lever_bounds. See residual_violations for the precise gaps."
      ),
    )

  return FundingHandlerResult(
    status=FundingHandlerStatus.RESOLVED,
    authored_lever_changes=authored_changes,
    residual_violations=[],
    tool_calls_used=tool_calls_used,
    diagnostic="all_cash_buffer_violations_filled_within_lever_bounds",
  )
