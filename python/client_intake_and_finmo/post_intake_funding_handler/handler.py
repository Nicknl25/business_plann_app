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

import contextvars
import copy
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase 9 P3.12 — machinery fail-fast helpers for the funding handler.
#
# Distinct from FundingHandlerStatus.EXHAUSTED (a planned hard-fail
# when the handler can't resolve the business problem within its
# budget): these fail-fasts fire when the iteration/handler
# infrastructure itself malfunctions. Per doctrine.md §5b, both
# kinds are required.
# ---------------------------------------------------------------------------


# Tracks GPT calls inside the session scope (round-count-drift invariant).
_FUNDING_HANDLER_GPT_CALL_COUNT: "contextvars.ContextVar[Optional[int]]" = (
  contextvars.ContextVar(
    "funding_handler_gpt_call_count",
    default=None,
  )
)


def _funding_handler_machinery_fail_fast(
  operation: str,
  message: str,
  details: Optional[Dict[str, Any]] = None,
) -> None:
  """Hard-stop on a funding-handler machinery malfunction."""
  from client_intake_and_finmo.fail_fast.common import (  # type: ignore
    PostIntakePreconditionFailed,
  )
  raise PostIntakePreconditionFailed(
    operation=str(operation or "").strip() or "funding_handler_machinery_violation",
    pipeline_stage="funding_handler",
    expected="funding handler iteration/handler machinery intact",
    actual=str(message or "").strip()[:600],
    details=details or {},
  )


def _assert_funding_handler_state_intact(
  *,
  round_n: int,
  input_items: Any,
  history: Any,
  verified_commit_candidate: Any,
) -> None:
  """Machinery invariant #3 — state corruption between rounds."""
  if not isinstance(input_items, list) or not input_items:
    _funding_handler_machinery_fail_fast(
      "funding_handler_state_corruption_between_rounds",
      f"round {round_n} entered with malformed input_items",
      details={"round_n": int(round_n), "input_items_type": type(input_items).__name__},
    )
  for idx, item in enumerate(input_items):
    if not isinstance(item, dict):
      _funding_handler_machinery_fail_fast(
        "funding_handler_state_corruption_between_rounds",
        f"round {round_n} input_items[{idx}] is not a dict (got {type(item).__name__})",
        details={"round_n": int(round_n), "bad_index": idx},
      )
  if not isinstance(history, list):
    _funding_handler_machinery_fail_fast(
      "funding_handler_state_corruption_between_rounds",
      f"round {round_n} history is not a list",
      details={"round_n": int(round_n), "history_type": type(history).__name__},
    )
  if verified_commit_candidate is not None and not hasattr(verified_commit_candidate, "arguments"):
    _funding_handler_machinery_fail_fast(
      "funding_handler_state_corruption_between_rounds",
      f"round {round_n} verified_commit_candidate set but lacks 'arguments' attr",
      details={"round_n": int(round_n)},
    )


def _assert_funding_handler_budget_decoupled(
  *,
  round_n: int,
  counts_against_run_budget_arg: bool,
) -> None:
  """Machinery invariant #2 — budget decoupling violation. Every GPT
  call inside the session must pass ``counts_against_run_budget=
  False`` (iter 17 fix). Runtime guard against future refactors that
  reintroduce budget commingling."""
  if counts_against_run_budget_arg is not False:
    _funding_handler_machinery_fail_fast(
      "funding_handler_budget_decoupling_violation",
      (
        f"round {round_n} GPT call site passed counts_against_run_budget="
        f"{counts_against_run_budget_arg!r}; the funding handler's "
        "session must always pass False to bound calls by the "
        "handler's HARD_CAP_TOOL_CALLS=10 rather than the run-wide budget."
      ),
      details={"round_n": int(round_n), "passed_value": counts_against_run_budget_arg},
    )


def _assert_funding_handler_round_count_consistent(
  *,
  loop_round_index: int,
  tool_calls_used: int,
) -> None:
  """Machinery invariant #1 — round count drift."""
  expected = _FUNDING_HANDLER_GPT_CALL_COUNT.get()
  if expected is None:
    _funding_handler_machinery_fail_fast(
      "funding_handler_round_count_drift",
      f"contextvar not initialized at loop round {loop_round_index}",
      details={"loop_round_index": int(loop_round_index)},
    )
  if int(expected) != int(tool_calls_used):
    _funding_handler_machinery_fail_fast(
      "funding_handler_round_count_drift",
      (
        f"loop round {loop_round_index}: contextvar gpt_call_count="
        f"{expected} but tool_calls_used={tool_calls_used}; counter divergence"
      ),
      details={
        "loop_round_index": int(loop_round_index),
        "contextvar_count": int(expected),
        "tool_calls_used": int(tool_calls_used),
      },
    )


def _assert_funding_handler_authority_respected(
  *,
  authored_lever_changes: Dict[str, Dict[int, float]],
) -> None:
  """Machinery invariant #4 — authority violation. Every authored
  lever_id must be in ``FUNDING_LEVER_AUTHORITY``. Previously the
  lever-write helper silently skipped out-of-authority ids; this
  guard raises instead, enforcing doctrine §3 Pattern 3 at runtime."""
  authority = set(FUNDING_LEVER_AUTHORITY)
  out_of_authority = [
    str(lever_id) for lever_id in (authored_lever_changes or {}).keys()
    if str(lever_id) not in authority
  ]
  if out_of_authority:
    _funding_handler_machinery_fail_fast(
      "funding_handler_authority_violation",
      (
        f"authored_lever_changes includes {len(out_of_authority)} "
        "lever_id(s) outside the funding handler's declared authority"
      ),
      details={
        "out_of_authority_lever_ids": out_of_authority[:10],
        "authority": sorted(authority),
      },
    )


def _assert_funding_handler_output_well_formed(
  *,
  result: "FundingHandlerResult",
) -> None:
  """Machinery invariant #5 — output malformation."""
  if result.status == FundingHandlerStatus.RESOLVED:
    if not result.authored_lever_changes:
      _funding_handler_machinery_fail_fast(
        "funding_handler_output_malformed",
        "RESOLVED status with empty authored_lever_changes",
        details={"status": result.status.value, "diagnostic": result.diagnostic},
      )
  if result.status == FundingHandlerStatus.EXHAUSTED:
    if not result.residual_violations and not result.diagnostic:
      _funding_handler_machinery_fail_fast(
        "funding_handler_output_malformed",
        "EXHAUSTED status with no residual_violations and no diagnostic",
        details={"status": result.status.value},
      )


def _assert_funding_handler_best_effort_selection_consistent(
  *,
  best_effort_record: Any,
  history: List[Any],
) -> None:
  """Machinery invariant #6 — best-effort selection drift. The best-
  effort record on hard cap must NOT be a record the commit-verifier
  would have accepted (otherwise it should have been the verified
  commit candidate). If it IS all-resolved, the session loop has a
  logic bug."""
  if best_effort_record is None:
    return
  result = getattr(best_effort_record, "result", None)
  if not isinstance(result, dict):
    return
  if bool(result.get("all_violations_resolved")):
    _funding_handler_machinery_fail_fast(
      "funding_handler_best_effort_selection_drift",
      (
        "best-effort record reports all_violations_resolved=True; "
        "this record should have been picked up as the verified "
        "commit candidate"
      ),
      details={
        "best_effort_call_n": getattr(best_effort_record, "call_n", None),
        "history_length": len(history) if isinstance(history, list) else None,
      },
    )


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
  # Phase 9 P3.20 Part 3 Stage 3b — broaden the handler's failure
  # input beyond cash_buffer_violations. The Python deterministic
  # allocator still only fills buffer shortfalls (it has no lever
  # primitive for distribution / surplus / contract / hard-rule
  # categories). But the GPT session sees ALL categories as context
  # so it can reason about combined fixes -- e.g., pulling back
  # Distributions to satisfy a cash_distribution_violation while
  # also closing a buffer gap. Lever authority is UNCHANGED (the
  # five funding levers).
  cash_distribution_violations: Optional[List[Dict[str, Any]]] = None,
  cash_surplus_ceiling_violations: Optional[List[Dict[str, Any]]] = None,
  cash_contract_failures: Optional[List[Dict[str, Any]]] = None,
  hard_rule_assessment: Optional[Dict[str, Any]] = None,
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
    # Stage 3b — broaden the GPT session's context with the other
    # validator failure categories so it can reason about combined
    # fixes within its existing 5-lever authority.
    cash_distribution_violations=cash_distribution_violations,
    cash_surplus_ceiling_violations=cash_surplus_ceiling_violations,
    cash_contract_failures=cash_contract_failures,
    hard_rule_assessment=hard_rule_assessment,
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
  # Phase 9 P3.12 — machinery invariant #4: authority violation.
  # Previously this loop silently skipped lever_ids outside
  # _LEVER_SECTION_MAP; per doctrine §3 Pattern 3 the silent skip is
  # a machinery bug. Fail-fast instead.
  _assert_funding_handler_authority_respected(
    authored_lever_changes=authored_lever_changes,
  )
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
  # Phase 9 P3.20 Part 3 Stage 3b — broaden the handler's failure
  # input beyond cash_buffer_violations. The orchestrator passes
  # every validator failure category from cash_post_validation so
  # the handler has full visibility into ANY cash problem (not just
  # buffer shortfalls). The deterministic Python allocator still
  # only fills buffer shortfalls (other categories lack a per-
  # quarter "shortfall in dollars" primitive the priority-order
  # walk can fill). But the GPT session sees ALL categories and
  # can reason about combined fixes within its existing 5-lever
  # authority -- e.g. negative Distributions adjustment to satisfy
  # a cash_distribution_violation while still closing buffer gaps.
  cash_distribution_violations: Optional[List[Dict[str, Any]]] = None,
  cash_surplus_ceiling_violations: Optional[List[Dict[str, Any]]] = None,
  cash_contract_failures: Optional[List[Dict[str, Any]]] = None,
  hard_rule_assessment: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Production-wired entry point. Called from the cash orchestrator
  AFTER cash strategy post-pass detects ANY validator failure
  (Phase 9 P3.20 Part 3 Stage 2 relaxed trigger; Stage 3b broadened
  input payload).

  Pipeline:
    1. Invoke :func:`run_funding_handler` (Python allocator + GPT
       session escalation). The Python allocator only operates on
       cash_buffer_violations; the GPT session sees ALL categories.
    2. If handler returns RESOLVED, apply the authored lever changes
       to a copy of model_input_json and rebuild FINMO via
       ``build_finmo``.
    3. Return a structured result dict carrying:
         status, authored_lever_changes, residual_violations,
         tool_calls_used, diagnostic, updated_model_input_json,
         updated_finmo_json, failures_input_summary.

  When handler returns EXHAUSTED, the orchestrator preserves the
  proposer's outputs in downstream state (Stage 1's never-revert)
  with the residual failures still visible for finalize-stage
  diagnostics.
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
    cash_distribution_violations=cash_distribution_violations,
    cash_surplus_ceiling_violations=cash_surplus_ceiling_violations,
    cash_contract_failures=cash_contract_failures,
    hard_rule_assessment=hard_rule_assessment,
  )

  # Machinery invariant #5 — output malformation. RESOLVED must
  # carry authored changes; EXHAUSTED must carry residual_violations
  # or a diagnostic. Fires on logic-drift in run_funding_handler.
  _assert_funding_handler_output_well_formed(result=result)

  # Stage 3b — per-category input summary so the orchestrator and
  # downstream diagnostics can see which validator categories the
  # handler was engaged against. Resolution per category is
  # determined by the orchestrator's post-handler re-validation
  # (the handler itself cannot re-run the validator).
  failures_input_summary = {
    "cash_buffer_violations": len(cash_buffer_violations or []),
    "cash_distribution_violations": len(cash_distribution_violations or []),
    "cash_surplus_ceiling_violations": len(cash_surplus_ceiling_violations or []),
    "cash_contract_failures": len(cash_contract_failures or []),
    "all_hard_rules_cleared": bool(
      (hard_rule_assessment or {}).get("all_hard_rules_cleared")
    ) if isinstance(hard_rule_assessment, dict) else None,
  }

  if result.status != FundingHandlerStatus.RESOLVED:
    return {
      "status": result.status.value,
      "authored_lever_changes": dict(result.authored_lever_changes),
      "residual_violations": list(result.residual_violations),
      "tool_calls_used": int(result.tool_calls_used),
      "diagnostic": result.diagnostic,
      "updated_model_input_json": None,
      "updated_finmo_json": None,
      "failures_input_summary": failures_input_summary,
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
    "failures_input_summary": failures_input_summary,
  }
