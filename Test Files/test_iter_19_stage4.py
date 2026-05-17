"""Iter 19 Stage 4 tests — cash adaptation + funding handler.

Covers:
  - The routine GPT critic in ``_run_cash_strategy_review_openai`` is
    dropped; Python proposer's output stands.
  - The new ``post_intake_funding_handler`` module is importable, has
    the doctrine-required shape (10-tool-call budget, run-budget
    decoupling flag, defined lever authority, specific diagnostics).
  - The deterministic ``run_funding_handler`` resolves resolvable
    violations and hard-fails with a specific diagnostic when bounds
    are exhausted.
  - The mini_finmo mirror projects cash trajectories correctly.

No MySQL, no live OpenAI. Synthetic in-memory state only.

Run: ``.venv\\Scripts\\python.exe "Test Files\\test_iter_19_stage4.py"``
"""

from __future__ import annotations

import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Tuple

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PY = os.path.join(_ROOT, "python")
if _PY not in sys.path:
  sys.path.insert(0, _PY)

from client_intake_and_finmo.post_intake_funding_handler import (  # noqa: E402
  FundingHandlerResult,
  FundingHandlerStatus,
  run_funding_handler,
)
from client_intake_and_finmo.post_intake_funding_handler import (  # noqa: E402
  handler as _fh_handler,
  mini_finmo as _fh_mini_finmo,
  prompts as _fh_prompts,
  tool_calling_session as _fh_session,
)
from client_intake_and_finmo.post_intake_cash import runner as _cash_runner  # noqa: E402


_RESULTS: List[Tuple[str, bool, str]] = []


def _run(name: str, fn: Callable[[], None]) -> None:
  try:
    fn()
    _RESULTS.append((name, True, ""))
    print(f"  PASS  {name}")
  except AssertionError as exc:
    _RESULTS.append((name, False, str(exc)))
    print(f"  FAIL  {name}: {exc}")
  except Exception as exc:
    _RESULTS.append((name, False, f"{type(exc).__name__}: {exc}"))
    print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
    traceback.print_exc()


# --------------------------------------------------------------------------
# (A) Routine GPT critic dropped in cash strategy review.
# --------------------------------------------------------------------------


def test_cash_strategy_review_short_circuits_before_gpt_call() -> None:
  src = open(_cash_runner.__file__, encoding="utf-8").read()
  # The legacy unconditional GPT critic path was moved below the
  # short-circuit return; the marker comment must reference iter 19.
  assert "iter 19 Stage 4" in src
  assert "routine GPT critic disabled" in src
  assert "critic_disabled_iter_19" in src


def test_cash_strategy_review_unreachable_marker_present() -> None:
  src = open(_cash_runner.__file__, encoding="utf-8").read()
  # The legacy GPT path is preserved below a comment marker so a
  # follow-up iter can wire the funding handler in its place.
  assert "Legacy GPT critic path (kept for reference; unreachable)" in src


# --------------------------------------------------------------------------
# (B) Funding handler module shape — doctrine §5 invariants.
# --------------------------------------------------------------------------


def test_funding_handler_module_has_required_files() -> None:
  module_dir = os.path.dirname(_fh_handler.__file__)
  for filename in ("__init__.py", "handler.py", "tool_calling_session.py", "prompts.py", "mini_finmo.py"):
    path = os.path.join(module_dir, filename)
    assert os.path.exists(path), f"missing: {path}"


def test_funding_handler_session_carries_doctrine_constants() -> None:
  assert _fh_session.HARD_CAP_TOOL_CALLS == 10
  assert _fh_session.INITIAL_TOOL_CALL_BUDGET == 8
  assert _fh_session.EXTENSION_TOOL_CALLS == 2
  assert _fh_session.COUNTS_AGAINST_RUN_BUDGET is False


def test_funding_handler_authority_is_explicit() -> None:
  authority = set(_fh_handler.FUNDING_LEVER_AUTHORITY)
  assert "schedules::Debt Issuance (New Borrowing)" in authority
  assert "schedules::Debt Repayment (Scheduled)" in authority
  assert "balance_sheet::Owner's Capital" in authority
  assert "balance_sheet::Other Equity" in authority
  assert "balance_sheet::Distributions" in authority
  # Authority MUST NOT include operating-side levers (F6-Pinnacle
  # pattern). Spot-check a few.
  for forbidden in (
    "expenses::Payroll",
    "expenses::Cost of Goods Sold",
    "revenue::Capacity",
  ):
    assert forbidden not in authority, f"out-of-scope lever in authority: {forbidden}"


def test_funding_handler_session_is_runnable_with_mocked_seam() -> None:
  # Stage 4 correction — the session is no longer a NotImplementedError
  # stub. Calling it with a mock _call_gpt_turn seam exercises the loop
  # without touching OpenAI; the function returns a structured result.
  def _mock_turn(**kwargs):
    return {
      "tool_calls": [],
      "raw_assistant_items": [],
      "decision_source": "python_proposer_plus_gpt_critic",
      "detail": "",
    }
  result = _fh_session.run_funding_tool_calling_session(
    cash_buffer_violations=[],
    _call_gpt_turn=_mock_turn,
    _projector=lambda **k: {"projected_quarter_rows": [], "total_cash_delta": 0.0},
    _residual_checker=lambda **k: [],
  )
  # No violations to chew on AND GPT stopped immediately ->
  # failed_precondition (no tool calls completed).
  assert result.status == "failed_precondition"


def test_funding_handler_prompts_carry_authority_list() -> None:
  prompt = _fh_prompts.FUNDING_HANDLER_SYSTEM_PROMPT
  for lever_id in _fh_handler.FUNDING_LEVER_AUTHORITY:
    assert lever_id in prompt, f"prompt missing lever_id: {lever_id}"


# --------------------------------------------------------------------------
# (C) Deterministic handler engagement and exhaustion paths.
# --------------------------------------------------------------------------


def _violation(quarter: int, ending_cash: float, buffer: float) -> Dict[str, Any]:
  return {
    "quarter_index": quarter,
    "ending_cash": float(ending_cash),
    "buffer": float(buffer),
  }


def _bounds_row(
  quarter: int,
  current: float = 0.0,
  max_value: float = 0.0,
  min_value: float = 0.0,
) -> Dict[str, Any]:
  return {
    "quarter_index": quarter,
    "current_value": float(current),
    "max_value": float(max_value),
    "min_value": float(min_value),
  }


def test_funding_handler_no_op_when_no_violations() -> None:
  result = run_funding_handler(cash_buffer_violations=[])
  assert result.status == FundingHandlerStatus.NO_VIOLATIONS
  assert result.authored_lever_changes == {}
  assert result.residual_violations == []


def test_funding_handler_resolves_violation_within_debt_issuance_headroom() -> None:
  # One quarter short by $50k. Debt issuance headroom is $100k.
  violation = _violation(quarter=3, ending_cash=200_000.0, buffer=250_000.0)
  bounds = {
    "schedules::Debt Issuance (New Borrowing)": [
      _bounds_row(3, current=0.0, max_value=100_000.0),
    ],
  }
  result = run_funding_handler(
    cash_buffer_violations=[violation],
    lever_bounds=bounds,
  )
  assert result.status == FundingHandlerStatus.RESOLVED
  authored = result.authored_lever_changes
  assert "schedules::Debt Issuance (New Borrowing)" in authored
  assert authored["schedules::Debt Issuance (New Borrowing)"][3] == 50_000.0
  assert result.residual_violations == []
  assert result.tool_calls_used == 1


def test_funding_handler_falls_through_priority_when_debt_capped() -> None:
  # $80k shortfall. Debt headroom $30k, owner's capital $30k, other
  # equity $25k — total $85k available; $80k fits.
  violation = _violation(quarter=5, ending_cash=10_000.0, buffer=90_000.0)
  bounds = {
    "schedules::Debt Issuance (New Borrowing)": [_bounds_row(5, current=0, max_value=30_000)],
    "balance_sheet::Owner's Capital": [_bounds_row(5, current=0, max_value=30_000)],
    "balance_sheet::Other Equity": [_bounds_row(5, current=0, max_value=25_000)],
  }
  result = run_funding_handler(cash_buffer_violations=[violation], lever_bounds=bounds)
  assert result.status == FundingHandlerStatus.RESOLVED
  authored = result.authored_lever_changes
  assert authored["schedules::Debt Issuance (New Borrowing)"][5] == 30_000.0
  assert authored["balance_sheet::Owner's Capital"][5] == 30_000.0
  assert authored["balance_sheet::Other Equity"][5] == 20_000.0


def test_funding_handler_exhausts_with_specific_residual_diagnostic() -> None:
  # $100k shortfall, but cumulative funding headroom only $40k. With
  # GPT escalation disabled the handler returns the Python residual
  # immediately (Stage 4 correction shape).
  violation = _violation(quarter=7, ending_cash=0.0, buffer=100_000.0)
  bounds = {
    "schedules::Debt Issuance (New Borrowing)": [_bounds_row(7, current=0, max_value=20_000)],
    "balance_sheet::Owner's Capital": [_bounds_row(7, current=0, max_value=20_000)],
  }
  result = run_funding_handler(
    cash_buffer_violations=[violation],
    lever_bounds=bounds,
    enable_gpt_session=False,
  )
  assert result.status == FundingHandlerStatus.EXHAUSTED
  assert "gpt_disabled" in result.diagnostic
  assert len(result.residual_violations) == 1
  residual = result.residual_violations[0]
  assert residual["quarter_index"] == 7
  assert residual["shortfall"] == 60_000.0
  assert "all_funding_lever_headroom_exhausted" in residual["reason"]


def test_funding_handler_respects_tool_call_budget() -> None:
  # Many violations, tight budget: deterministic allocator stops after
  # the budget. With GPT disabled, residual is surfaced immediately.
  violations = [_violation(quarter=q, ending_cash=0.0, buffer=10_000.0) for q in range(1, 16)]
  bounds = {
    "schedules::Debt Issuance (New Borrowing)": [
      _bounds_row(q, current=0, max_value=10_000) for q in range(1, 16)
    ],
  }
  result = run_funding_handler(
    cash_buffer_violations=violations,
    lever_bounds=bounds,
    tool_call_budget=10,
    enable_gpt_session=False,
  )
  assert result.status == FundingHandlerStatus.EXHAUSTED
  assert result.tool_calls_used == 10
  # 5 quarters past the budget — each surfaces in residuals with the
  # budget-exhausted reason from the Python allocator.
  budget_residuals = [
    r for r in result.residual_violations
    if r.get("reason") == "tool_call_budget_exhausted"
  ]
  assert len(budget_residuals) == 5


def test_funding_handler_uses_distributions_pulldown_after_increases() -> None:
  # Headroom from increase-direction levers is zero; the handler must
  # reach for distributions decrease.
  violation = _violation(quarter=10, ending_cash=100.0, buffer=20_100.0)
  bounds = {
    "schedules::Debt Issuance (New Borrowing)": [_bounds_row(10, current=0, max_value=0)],
    "balance_sheet::Owner's Capital": [_bounds_row(10, current=0, max_value=0)],
    "balance_sheet::Other Equity": [_bounds_row(10, current=0, max_value=0)],
    "balance_sheet::Distributions": [_bounds_row(10, current=20_000, max_value=20_000, min_value=0)],
  }
  result = run_funding_handler(cash_buffer_violations=[violation], lever_bounds=bounds)
  assert result.status == FundingHandlerStatus.RESOLVED
  authored = result.authored_lever_changes
  assert authored["balance_sheet::Distributions"][10] == -20_000.0


# --------------------------------------------------------------------------
# (D) Mini-FINMO mirror — preview projection.
# --------------------------------------------------------------------------


def test_mini_finmo_applies_increase_lever_to_running_cash() -> None:
  rows = [
    {"quarter_index": 1, "ending_cash": 100_000.0},
    {"quarter_index": 2, "ending_cash": 120_000.0},
    {"quarter_index": 3, "ending_cash": 130_000.0},
  ]
  adjustments = {
    "schedules::Debt Issuance (New Borrowing)": {2: 50_000.0},
  }
  result = _fh_mini_finmo.project_cash_trajectory_with_adjustments(
    pre_handler_finmo_quarter_rows=rows,
    lever_adjustments=adjustments,
  )
  projected = result["projected_quarter_rows"]
  assert projected[0]["projected_ending_cash"] == 100_000.0
  assert projected[1]["projected_ending_cash"] == 170_000.0
  assert projected[2]["projected_ending_cash"] == 180_000.0  # delta carries forward


def test_mini_finmo_distributions_pulldown_negates_cash_impact() -> None:
  rows = [{"quarter_index": 1, "ending_cash": 50_000.0}]
  # Negative distribution adjustment = pulling back distributions =
  # MORE cash retained.
  adjustments = {"balance_sheet::Distributions": {1: -10_000.0}}
  result = _fh_mini_finmo.project_cash_trajectory_with_adjustments(
    pre_handler_finmo_quarter_rows=rows,
    lever_adjustments=adjustments,
  )
  assert result["projected_quarter_rows"][0]["projected_ending_cash"] == 60_000.0


def test_mini_finmo_buffer_residual_flags_uncovered_quarters() -> None:
  rows = [
    {"quarter_index": 1, "ending_cash": 40_000.0},
    {"quarter_index": 2, "ending_cash": 50_000.0},
  ]
  adjustments: Dict[str, Dict[int, float]] = {}
  buffer_by_q = {1: 60_000.0, 2: 30_000.0}
  residual = _fh_mini_finmo.buffer_residual_after_adjustments(
    pre_handler_finmo_quarter_rows=rows,
    lever_adjustments=adjustments,
    buffer_by_quarter=buffer_by_q,
  )
  assert len(residual) == 1
  assert residual[0]["quarter_index"] == 1
  assert residual[0]["shortfall"] == 20_000.0


# --------------------------------------------------------------------------
# Run.
# --------------------------------------------------------------------------


def main() -> int:
  print("running test_iter_19_stage4.py")
  print("-" * 70)
  tests = [
    ("cash_strategy_short_circuit_marker", test_cash_strategy_review_short_circuits_before_gpt_call),
    ("cash_strategy_legacy_unreachable_marker", test_cash_strategy_review_unreachable_marker_present),
    ("funding_handler_files_present", test_funding_handler_module_has_required_files),
    ("funding_handler_session_constants", test_funding_handler_session_carries_doctrine_constants),
    ("funding_handler_explicit_authority", test_funding_handler_authority_is_explicit),
    ("funding_handler_session_runnable_with_mock", test_funding_handler_session_is_runnable_with_mocked_seam),
    ("funding_handler_prompt_carries_authority", test_funding_handler_prompts_carry_authority_list),
    ("handler_no_op_no_violations", test_funding_handler_no_op_when_no_violations),
    ("handler_resolves_within_debt_headroom", test_funding_handler_resolves_violation_within_debt_issuance_headroom),
    ("handler_falls_through_priority", test_funding_handler_falls_through_priority_when_debt_capped),
    ("handler_exhausts_specific_residual", test_funding_handler_exhausts_with_specific_residual_diagnostic),
    ("handler_respects_tool_call_budget", test_funding_handler_respects_tool_call_budget),
    ("handler_uses_distributions_pulldown", test_funding_handler_uses_distributions_pulldown_after_increases),
    ("mini_finmo_increase_lever_carries_forward", test_mini_finmo_applies_increase_lever_to_running_cash),
    ("mini_finmo_distributions_negates", test_mini_finmo_distributions_pulldown_negates_cash_impact),
    ("mini_finmo_buffer_residual", test_mini_finmo_buffer_residual_flags_uncovered_quarters),
  ]
  for name, fn in tests:
    _run(name, fn)
  print("-" * 70)
  passed = sum(1 for _, ok, _ in _RESULTS if ok)
  failed = [(n, why) for n, ok, why in _RESULTS if not ok]
  print(f"{passed}/{len(_RESULTS)} passed")
  if failed:
    print("FAILURES:")
    for name, why in failed:
      print(f"  {name}: {why}")
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
