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
   17). Implemented in :mod:`tool_calling_session`.
5. **Specific validator trigger**: non-empty
   ``cash_buffer_violations``.
6. **Specific hard-fail diagnostic**: :class:`FundingHandlerStatus`
   ``EXHAUSTED`` paired with the precise per-quarter residual gap so
   the operator can identify the unfixable cell.

Flow (Stage 4 correction):
  - Deterministic Python allocator runs FIRST. When it resolves every
    violation, the handler returns RESOLVED with the authored
    changes; the GPT session is never invoked (Python-first per
    doctrine §1).
  - When the Python allocator leaves residual violations OR exhausts
    its tool-call budget, :func:`run_funding_handler` invokes the
    GPT tool-calling session
    (:mod:`tool_calling_session.run_funding_tool_calling_session`).
    The GPT session iterates within the same 10-call budget,
    proposing non-default allocations the priority-order allocator
    could not consider.
  - If the GPT session verifies a commit, the handler returns
    RESOLVED with the GPT-authored adjustments overlaying the
    Python allocator's first-pass changes.
  - If the GPT session reaches the hard cap without verification
    OR returns best-effort, the handler returns EXHAUSTED with a
    specific residual_violations list naming the unfillable
    quarters (doctrine §1 — hard-fail with diagnostic over silent
    recovery).

Live API integration is unverified pending end-of-iter E2E sweep.
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


def _run_python_allocator(
  *,
  cash_buffer_violations: List[Dict[str, Any]],
  lever_bounds: Dict[str, List[Dict[str, Any]]],
  tool_call_budget: int,
) -> Tuple[Dict[str, Dict[int, float]], List[Dict[str, Any]], int]:
  """Deterministic per-quarter allocator. Returns
  (authored_changes, residual_violations, tool_calls_used)."""
  authored_changes: Dict[str, Dict[int, float]] = {}
  residual: List[Dict[str, Any]] = []
  tool_calls_used = 0

  for violation in cash_buffer_violations:
    if tool_calls_used >= int(tool_call_budget):
      remaining = cash_buffer_violations[cash_buffer_violations.index(violation):]
      for rv in remaining:
        residual.append({
          "quarter_index": _violation_quarter_index(rv),
          "shortfall": round(_violation_shortfall(rv), 2),
          "reason": "tool_call_budget_exhausted",
        })
      break
    tool_calls_used += 1
    quarter_index = _violation_quarter_index(violation)
    shortfall = _violation_shortfall(violation)
    if shortfall <= 0.0:
      continue
    per_quarter, residual_shortfall = _resolve_quarter(
      quarter_index=quarter_index,
      shortfall=shortfall,
      lever_bounds=lever_bounds,
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

  return authored_changes, residual, tool_calls_used


def run_funding_handler(
  *,
  cash_buffer_violations: List[Dict[str, Any]],
  lever_bounds: Optional[Dict[str, List[Dict[str, Any]]]] = None,
  tool_call_budget: int = 10,
  # GPT-session inputs (Stage 4 correction). When the Python allocator
  # leaves residual gaps, the handler optionally escalates to the GPT
  # tool-calling session. Callers must pass the FINMO quarter rows and
  # buffer requirements; absent these, the GPT escalation is skipped
  # and the deterministic residual is returned as EXHAUSTED.
  pre_handler_finmo_quarter_rows: Optional[List[Dict[str, Any]]] = None,
  buffer_by_quarter: Optional[Dict[int, float]] = None,
  cash_strategy_mode: str = "",
  enable_gpt_session: bool = True,
  # Test seam: callers (and tests) can inject the session implementation
  # to mock the GPT loop without monkey-patching.
  _run_gpt_session: Optional[Any] = None,
) -> FundingHandlerResult:
  """Run the funding handler against a set of cash-buffer violations.

  Per the Stage 4 correction the handler is a two-stage pipeline:

    1. Python deterministic allocator (Python-first per doctrine §1).
    2. GPT tool-calling session — engages only when Python's
       allocation leaves residual violations.

  When both stages succeed (no residual), returns
  :attr:`FundingHandlerStatus.RESOLVED` with the merged lever changes.
  When GPT cannot resolve (or is disabled), returns
  :attr:`FundingHandlerStatus.EXHAUSTED` with the specific residual
  diagnostic.
  """
  bounds = lever_bounds if isinstance(lever_bounds, dict) else {}
  violations = [v for v in (cash_buffer_violations or []) if isinstance(v, dict)]
  if not violations:
    return FundingHandlerResult(
      status=FundingHandlerStatus.NO_VIOLATIONS,
      diagnostic="no_cash_buffer_violations_to_resolve",
    )

  # Step 1 — Python deterministic allocator.
  python_authored, python_residual, python_tool_calls = _run_python_allocator(
    cash_buffer_violations=violations,
    lever_bounds=bounds,
    tool_call_budget=tool_call_budget,
  )

  if not python_residual:
    # Python alone resolved every violation. Doctrine §1: prefer
    # deterministic over GPT — skip the GPT session.
    return FundingHandlerResult(
      status=FundingHandlerStatus.RESOLVED,
      authored_lever_changes=python_authored,
      residual_violations=[],
      tool_calls_used=python_tool_calls,
      diagnostic="all_cash_buffer_violations_filled_by_python_allocator",
    )

  # Step 2 — escalate to GPT tool-calling session.
  if not enable_gpt_session:
    return FundingHandlerResult(
      status=FundingHandlerStatus.EXHAUSTED,
      authored_lever_changes=python_authored,
      residual_violations=python_residual,
      tool_calls_used=python_tool_calls,
      diagnostic=(
        "funding_handler_python_residual_gpt_disabled: "
        f"{len(python_residual)} quarter(s) unresolved after Python "
        "allocator; GPT escalation disabled by caller."
      ),
    )

  if pre_handler_finmo_quarter_rows is None or buffer_by_quarter is None:
    # Caller did not supply the inputs the GPT session needs to probe
    # the cash trajectory. Hard-fail with a specific diagnostic.
    return FundingHandlerResult(
      status=FundingHandlerStatus.EXHAUSTED,
      authored_lever_changes=python_authored,
      residual_violations=python_residual,
      tool_calls_used=python_tool_calls,
      diagnostic=(
        "funding_handler_gpt_inputs_missing: "
        "GPT session escalation requires pre_handler_finmo_quarter_rows "
        "and buffer_by_quarter from the caller. Python residual stands."
      ),
    )

  session_runner = _run_gpt_session
  if session_runner is None:
    from client_intake_and_finmo.post_intake_funding_handler.tool_calling_session import (  # type: ignore
      run_funding_tool_calling_session,
    )
    session_runner = run_funding_tool_calling_session

  session_result = session_runner(
    cash_buffer_violations=violations,
    lever_bounds=bounds,
    pre_handler_finmo_quarter_rows=pre_handler_finmo_quarter_rows,
    buffer_by_quarter=buffer_by_quarter,
    python_allocator_authored=python_authored,
    python_allocator_residual=python_residual,
    cash_strategy_mode=cash_strategy_mode,
  )

  combined_tool_calls = python_tool_calls + int(
    getattr(session_result, "tool_calls_used", 0) or 0
  )

  if getattr(session_result, "status", "") == "verified":
    # GPT-authored lever_adjustments win on conflict (most recent
    # verified). Merge: start with Python's first-pass, overlay GPT's.
    final_changes = _merge_lever_changes(
      python_authored,
      _extract_lever_adjustments(session_result.final_lever_adjustments),
    )
    return FundingHandlerResult(
      status=FundingHandlerStatus.RESOLVED,
      authored_lever_changes=final_changes,
      residual_violations=[],
      tool_calls_used=combined_tool_calls,
      diagnostic=(
        "all_cash_buffer_violations_filled_by_gpt_session"
        + (" (extension_budget_used)" if getattr(session_result, "budget_extension_triggered", False) else "")
      ),
    )

  # Best-effort or failed_precondition — hard-fail with the residual
  # diagnostic. The GPT session may have authored partial changes;
  # we still surface them so the operator can see what was attempted.
  best_effort_changes = _extract_lever_adjustments(
    getattr(session_result, "final_lever_adjustments", None)
  )
  merged = _merge_lever_changes(python_authored, best_effort_changes)
  return FundingHandlerResult(
    status=FundingHandlerStatus.EXHAUSTED,
    authored_lever_changes=merged,
    residual_violations=python_residual,
    tool_calls_used=combined_tool_calls,
    diagnostic=(
      f"funding_handler_gpt_session_{getattr(session_result, 'status', 'unknown')}: "
      f"{len(python_residual)} python-residual quarter(s) remained "
      "unfilled and the GPT session did not produce a verified "
      "all-resolved commit. See residual_violations for the precise "
      "gaps."
    ),
  )


def _extract_lever_adjustments(
  final_lever_adjustments: Optional[Dict[str, Any]],
) -> Dict[str, Dict[int, float]]:
  """Pull the raw ``lever_adjustments`` map out of the GPT session
  result and coerce quarter keys to int + filter nulls."""
  if not isinstance(final_lever_adjustments, dict):
    return {}
  raw = final_lever_adjustments.get("lever_adjustments")
  if not isinstance(raw, dict):
    return {}
  out: Dict[str, Dict[int, float]] = {}
  for lever_id, per_q in raw.items():
    if not isinstance(per_q, dict):
      continue
    coerced: Dict[int, float] = {}
    for quarter_key, value in per_q.items():
      if value is None:
        continue
      try:
        qi = int(quarter_key)
      except Exception:
        continue
      try:
        coerced[qi] = float(value)
      except Exception:
        continue
    if coerced:
      out[lever_id] = coerced
  return out


def _merge_lever_changes(
  base: Dict[str, Dict[int, float]],
  overlay: Dict[str, Dict[int, float]],
) -> Dict[str, Dict[int, float]]:
  """Overlay merge — ``overlay`` wins on lever/quarter conflicts."""
  merged: Dict[str, Dict[int, float]] = {
    lever_id: dict(per_q) for lever_id, per_q in (base or {}).items()
  }
  for lever_id, per_q in (overlay or {}).items():
    if not isinstance(per_q, dict):
      continue
    merged.setdefault(lever_id, {})
    for qi, amount in per_q.items():
      merged[lever_id][int(qi)] = float(amount)
  return merged


# ---------------------------------------------------------------------------
# Production wiring helpers (Stage 4 correction).
# ---------------------------------------------------------------------------


_LEVER_SECTION_MAP: Dict[str, Tuple[str, str]] = {
  "schedules::Debt Issuance (New Borrowing)": ("schedules", "Debt Issuance (New Borrowing)"),
  "schedules::Debt Repayment (Scheduled)": ("schedules", "Debt Repayment (Scheduled)"),
  "balance_sheet::Owner's Capital": ("balance_sheet", "Owner's Capital"),
  "balance_sheet::Other Equity": ("balance_sheet", "Other Equity"),
  "balance_sheet::Distributions": ("balance_sheet", "Distributions"),
}


def _safe_float(value: Any) -> float:
  try:
    return float(value)
  except Exception:
    return 0.0


def apply_authored_lever_changes_to_model_input(
  *,
  model_input_json: Dict[str, Any],
  authored_lever_changes: Dict[str, Dict[int, float]],
) -> Dict[str, Any]:
  """Apply the handler's authored per-quarter lever deltas to a copy of
  model_input. ``amount`` is a SIGNED DELTA from the current value:
  positive = add to the lever; negative = subtract. The stub-0 slot is
  preserved; live quarter values are the trailing slots in the
  ``values`` array.

  Mutates a deep copy; returns the new model_input.
  """
  import copy as _copy
  next_payload = _copy.deepcopy(model_input_json or {})
  if not isinstance(authored_lever_changes, dict) or not authored_lever_changes:
    return next_payload
  sections = next_payload.get("sections") if isinstance(next_payload.get("sections"), dict) else {}
  for lever_id, per_q in authored_lever_changes.items():
    if lever_id not in _LEVER_SECTION_MAP or not isinstance(per_q, dict):
      continue
    section_key, label = _LEVER_SECTION_MAP[lever_id]
    rows = sections.get(section_key) if isinstance(sections.get(section_key), list) else []
    target_row = next(
      (row for row in rows if isinstance(row, dict) and str(row.get("label") or "").strip() == label),
      None,
    )
    if target_row is None:
      continue
    values = list(target_row.get("values") or [])
    if not values:
      continue
    # Values array convention: optional stub-0 at index 0, live
    # quarter values at indices 1..N when stub present, else 0..N-1.
    # Detect by length: 21 = stub + 20 live, 20 = 20 live only.
    has_stub = len(values) >= 21
    for qi, signed_delta in per_q.items():
      try:
        qi_int = int(qi)
      except Exception:
        continue
      if qi_int < 1:
        continue
      idx = qi_int if has_stub else qi_int - 1
      if idx < 0 or idx >= len(values):
        continue
      current = _safe_float(values[idx])
      values[idx] = round(current + _safe_float(signed_delta), 6)
    target_row["values"] = values
  return next_payload


def engage_funding_handler_on_violations(
  *,
  cash_buffer_violations: List[Dict[str, Any]],
  pre_handler_model_input_json: Dict[str, Any],
  pre_handler_finmo_json: Dict[str, Any],
  lever_bounds: Dict[str, List[Dict[str, Any]]],
  buffer_by_quarter: Dict[int, float],
  cash_strategy_mode: str = "",
  build_finmo: Optional[Any] = None,
) -> Dict[str, Any]:
  """Production-wired entry point. Called from the cash orchestrator
  AFTER cash strategy post-pass detects buffer violations.

  Pipeline:
    1. Invoke :func:`run_funding_handler` (Python allocator + GPT
       session escalation).
    2. If handler returns RESOLVED, apply the authored lever changes
       to a copy of model_input_json and rebuild FINMO via
       ``build_finmo``.
    3. Return a structured result dict carrying:
         status, authored_lever_changes, residual_violations,
         tool_calls_used, diagnostic, updated_model_input_json,
         updated_finmo_json.

  When handler returns EXHAUSTED, the orchestrator should hard-fail
  with the specific residual diagnostic (doctrine §1).
  """
  pre_rows = (pre_handler_finmo_json or {}).get("quarter_rows") or []
  if not isinstance(pre_rows, list):
    pre_rows = []
  result = run_funding_handler(
    cash_buffer_violations=cash_buffer_violations or [],
    lever_bounds=lever_bounds,
    pre_handler_finmo_quarter_rows=pre_rows,
    buffer_by_quarter=buffer_by_quarter,
    cash_strategy_mode=cash_strategy_mode,
    enable_gpt_session=True,
  )

  if result.status != FundingHandlerStatus.RESOLVED:
    return {
      "status": result.status.value,
      "authored_lever_changes": dict(result.authored_lever_changes),
      "residual_violations": list(result.residual_violations),
      "tool_calls_used": int(result.tool_calls_used),
      "diagnostic": result.diagnostic,
      "updated_model_input_json": None,
      "updated_finmo_json": None,
    }

  # RESOLVED — apply authored changes and rebuild FINMO.
  updated_model_input = apply_authored_lever_changes_to_model_input(
    model_input_json=pre_handler_model_input_json,
    authored_lever_changes=result.authored_lever_changes,
  )
  updated_finmo: Optional[Dict[str, Any]] = None
  if callable(build_finmo):
    try:
      import copy as _copy
      updated_finmo = build_finmo(_copy.deepcopy(updated_model_input))
    except Exception as exc:
      logger.exception(
        "engage_funding_handler_on_violations: FINMO rebuild failed: "
        "%s: %s",
        type(exc).__name__, str(exc)[:200],
      )
      updated_finmo = None
  return {
    "status": result.status.value,
    "authored_lever_changes": dict(result.authored_lever_changes),
    "residual_violations": [],
    "tool_calls_used": int(result.tool_calls_used),
    "diagnostic": result.diagnostic,
    "updated_model_input_json": updated_model_input,
    "updated_finmo_json": updated_finmo,
  }
