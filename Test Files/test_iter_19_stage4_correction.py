"""Iter 19 Stage 4 correction tests — funding handler full GPT
tool-calling loop + production wiring.

Covers:
  - GPT tool-calling session loop branches (verified commit,
    best-effort no-all-resolved, hard cap, GPT stops calling tool,
    GPT turn failure, extension budget grant).
  - Two-stage handler pipeline: Python allocator first; GPT session
    escalation on residual; merged authoring; specific diagnostics.
  - Production-wiring helper:
    - apply_authored_lever_changes_to_model_input correctly applies
      signed deltas to the right schedule/balance_sheet rows.
    - engage_funding_handler_on_violations dispatches to handler and
      rebuilds FINMO on RESOLVED status.
  - Orchestrator-level wiring: the cash strategy orchestrator
    invokes engage_funding_handler_on_violations when post-pass
    detects buffer violations.

Mocked GPT turns (no real OpenAI calls). Live API integration is
deliberately unverified pending the end-of-iter E2E sweep.

Run: ``.venv\\Scripts\\python.exe "Test Files\\test_iter_19_stage4_correction.py"``
"""

from __future__ import annotations

import copy
import json
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
  apply_authored_lever_changes_to_model_input,
  engage_funding_handler_on_violations,
  run_funding_handler,
)
from client_intake_and_finmo.post_intake_funding_handler import (  # noqa: E402
  handler as _fh_handler,
  tool_calling_session as _fh_session,
)
from client_intake_and_finmo.post_intake_cash_strategy import (  # noqa: E402
  orchestrator_invocation as _cash_orch,
)


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
# Mocks for the GPT tool-calling loop.
# --------------------------------------------------------------------------


def _make_mock_call_gpt_turn(
  scripted_responses: List[Dict[str, Any]],
) -> Callable[..., Dict[str, Any]]:
  """Build a mock for call_gpt_responses_api_turn. Pops scripted
  responses in order. Each response is the raw return dict shape from
  the real API helper."""
  state = {"i": 0}

  def _mock(**kwargs: Any) -> Dict[str, Any]:
    if state["i"] >= len(scripted_responses):
      # Default-empty after the script exhausts — emulates GPT stopping.
      return {
        "tool_calls": [],
        "assistant_message_text": None,
        "raw_assistant_items": [],
        "decision_source": "python_proposer_plus_gpt_critic",
        "detail": "",
      }
    resp = scripted_responses[state["i"]]
    state["i"] += 1
    return resp

  return _mock


def _tool_call_response(
  *,
  lever_adjustments: Dict[str, Dict[int, float]],
  call_id: str = "call_1",
) -> Dict[str, Any]:
  """Synthesize a Responses-API turn with a single function_call."""
  per_lever = {
    lever_id: {str(q): float(v) for q, v in per_q.items()}
    for lever_id, per_q in lever_adjustments.items()
  }
  args_payload = {"lever_adjustments": per_lever}
  return {
    "tool_calls": [
      {
        "name": "compute_cash_trajectory",
        "call_id": call_id,
        "arguments": json.dumps(args_payload),
      }
    ],
    "raw_assistant_items": [
      {
        "type": "function_call",
        "name": "compute_cash_trajectory",
        "call_id": call_id,
        "arguments": json.dumps(args_payload),
      }
    ],
    "decision_source": "python_proposer_plus_gpt_critic",
    "detail": "",
  }


def _stop_response() -> Dict[str, Any]:
  return {
    "tool_calls": [],
    "raw_assistant_items": [{"role": "assistant", "content": [{"type": "output_text", "text": "stopping"}]}],
    "decision_source": "python_proposer_plus_gpt_critic",
    "detail": "",
  }


def _mock_projector_factory(
  *,
  ending_cash_by_quarter: Dict[int, float],
):
  def _projector(*, pre_handler_finmo_quarter_rows: List[Dict[str, Any]], lever_adjustments: Dict[str, Dict[int, float]]) -> Dict[str, Any]:
    projected_rows = []
    running_delta = 0.0
    for qi in sorted(ending_cash_by_quarter.keys()):
      quarter_delta = 0.0
      for lever_id, per_q in lever_adjustments.items():
        amount = float(per_q.get(qi) or 0.0)
        if "Distributions" in lever_id:
          quarter_delta += -amount
        else:
          quarter_delta += amount
      running_delta += quarter_delta
      projected_rows.append({
        "quarter_index": qi,
        "ending_cash": float(ending_cash_by_quarter[qi]),
        "projected_ending_cash": float(ending_cash_by_quarter[qi]) + running_delta,
        "cash_delta_from_adjustments": running_delta,
      })
    return {
      "projected_quarter_rows": projected_rows,
      "total_cash_delta": running_delta,
    }
  return _projector


def _mock_residual_checker_factory(
  *,
  ending_cash_by_quarter: Dict[int, float],
  buffer_by_quarter: Dict[int, float],
):
  def _checker(*, pre_handler_finmo_quarter_rows: List[Dict[str, Any]], lever_adjustments: Dict[str, Dict[int, float]], buffer_by_quarter: Dict[int, float]) -> List[Dict[str, Any]]:
    running_delta = 0.0
    residual: List[Dict[str, Any]] = []
    for qi in sorted(ending_cash_by_quarter.keys()):
      quarter_delta = 0.0
      for lever_id, per_q in lever_adjustments.items():
        amount = float(per_q.get(qi) or 0.0)
        if "Distributions" in lever_id:
          quarter_delta += -amount
        else:
          quarter_delta += amount
      running_delta += quarter_delta
      projected_ec = float(ending_cash_by_quarter[qi]) + running_delta
      buffer_req = float(buffer_by_quarter.get(qi) or 0.0)
      if projected_ec < buffer_req:
        residual.append({
          "quarter_index": qi,
          "projected_ending_cash": projected_ec,
          "buffer": buffer_req,
          "shortfall": buffer_req - projected_ec,
        })
    return residual
  return _checker


# --------------------------------------------------------------------------
# GPT tool-calling session unit tests.
# --------------------------------------------------------------------------


def test_session_verified_commit_when_gpt_resolves_violation() -> None:
  # Synthetic: pre-handler ending_cash=$50k at Q3, buffer=$100k.
  # GPT proposes $60k debt issuance at Q3 → projected=$110k → resolved.
  mock_gpt = _make_mock_call_gpt_turn([
    _tool_call_response(
      lever_adjustments={"schedules::Debt Issuance (New Borrowing)": {3: 60_000.0}},
      call_id="c1",
    ),
    _stop_response(),
  ])
  projector = _mock_projector_factory(
    ending_cash_by_quarter={1: 200_000.0, 2: 150_000.0, 3: 50_000.0, 4: 100_000.0},
  )
  residual = _mock_residual_checker_factory(
    ending_cash_by_quarter={1: 200_000.0, 2: 150_000.0, 3: 50_000.0, 4: 100_000.0},
    buffer_by_quarter={1: 50_000.0, 2: 50_000.0, 3: 100_000.0, 4: 80_000.0},
  )
  result = _fh_session.run_funding_tool_calling_session(
    cash_buffer_violations=[{"quarter_index": 3, "ending_cash": 50_000.0, "buffer": 100_000.0}],
    lever_bounds={},
    pre_handler_finmo_quarter_rows=[],
    buffer_by_quarter={1: 50_000.0, 2: 50_000.0, 3: 100_000.0, 4: 80_000.0},
    _call_gpt_turn=mock_gpt,
    _projector=projector,
    _residual_checker=residual,
  )
  assert result.status == "verified"
  assert result.tool_calls_used == 1
  assert result.verified_commit_call_n == 1
  assert result.final_lever_adjustments is not None


def test_session_hard_cap_with_best_effort() -> None:
  # GPT proposes inadequate adjustments forever; loop hits 10 calls.
  # Best-effort record (lowest residual) wins.
  scripted = []
  for i in range(15):
    scripted.append(_tool_call_response(
      lever_adjustments={"schedules::Debt Issuance (New Borrowing)": {3: 10_000.0 * (i + 1)}},
      call_id=f"c{i+1}",
    ))
  mock_gpt = _make_mock_call_gpt_turn(scripted)
  projector = _mock_projector_factory(ending_cash_by_quarter={3: 0.0})
  residual = _mock_residual_checker_factory(
    ending_cash_by_quarter={3: 0.0},
    buffer_by_quarter={3: 1_000_000.0},  # huge buffer, nothing resolves
  )
  result = _fh_session.run_funding_tool_calling_session(
    cash_buffer_violations=[{"quarter_index": 3, "ending_cash": 0.0, "buffer": 1_000_000.0}],
    lever_bounds={},
    pre_handler_finmo_quarter_rows=[],
    buffer_by_quarter={3: 1_000_000.0},
    _call_gpt_turn=mock_gpt,
    _projector=projector,
    _residual_checker=residual,
  )
  assert result.status == "best_effort_no_all_resolved"
  assert result.tool_calls_used == _fh_session.HARD_CAP_TOOL_CALLS
  assert result.best_effort_call_n is not None
  assert result.budget_extension_triggered is True


def test_session_gpt_stops_calling_tool_returns_best_effort() -> None:
  mock_gpt = _make_mock_call_gpt_turn([
    _tool_call_response(
      lever_adjustments={"schedules::Debt Issuance (New Borrowing)": {3: 20_000.0}},
      call_id="c1",
    ),
    _stop_response(),
  ])
  projector = _mock_projector_factory(ending_cash_by_quarter={3: 0.0})
  residual = _mock_residual_checker_factory(
    ending_cash_by_quarter={3: 0.0},
    buffer_by_quarter={3: 100_000.0},
  )
  result = _fh_session.run_funding_tool_calling_session(
    cash_buffer_violations=[{"quarter_index": 3, "ending_cash": 0.0, "buffer": 100_000.0}],
    lever_bounds={},
    pre_handler_finmo_quarter_rows=[],
    buffer_by_quarter={3: 100_000.0},
    _call_gpt_turn=mock_gpt,
    _projector=projector,
    _residual_checker=residual,
  )
  assert result.status == "best_effort_no_all_resolved"
  assert result.detail == "gpt_stopped_calling_tool"
  assert result.tool_calls_used == 1


def test_session_failed_precondition_when_no_tool_calls() -> None:
  mock_gpt = _make_mock_call_gpt_turn([_stop_response()])
  projector = _mock_projector_factory(ending_cash_by_quarter={3: 0.0})
  residual = _mock_residual_checker_factory(
    ending_cash_by_quarter={3: 0.0},
    buffer_by_quarter={3: 100_000.0},
  )
  result = _fh_session.run_funding_tool_calling_session(
    cash_buffer_violations=[{"quarter_index": 3, "ending_cash": 0.0, "buffer": 100_000.0}],
    lever_bounds={},
    pre_handler_finmo_quarter_rows=[],
    buffer_by_quarter={3: 100_000.0},
    _call_gpt_turn=mock_gpt,
    _projector=projector,
    _residual_checker=residual,
  )
  assert result.status == "failed_precondition"
  assert result.tool_calls_used == 0


def test_session_extension_budget_triggers_after_initial() -> None:
  # 8 failing calls trigger extension; 9th call resolves.
  scripted = []
  for i in range(8):
    scripted.append(_tool_call_response(
      lever_adjustments={"schedules::Debt Issuance (New Borrowing)": {3: 1_000.0 * (i + 1)}},
      call_id=f"c{i+1}",
    ))
  scripted.append(_tool_call_response(
    lever_adjustments={"schedules::Debt Issuance (New Borrowing)": {3: 200_000.0}},
    call_id="c9",
  ))
  scripted.append(_stop_response())
  mock_gpt = _make_mock_call_gpt_turn(scripted)
  projector = _mock_projector_factory(ending_cash_by_quarter={3: 0.0})
  residual = _mock_residual_checker_factory(
    ending_cash_by_quarter={3: 0.0},
    buffer_by_quarter={3: 100_000.0},
  )
  result = _fh_session.run_funding_tool_calling_session(
    cash_buffer_violations=[{"quarter_index": 3, "ending_cash": 0.0, "buffer": 100_000.0}],
    lever_bounds={},
    pre_handler_finmo_quarter_rows=[],
    buffer_by_quarter={3: 100_000.0},
    _call_gpt_turn=mock_gpt,
    _projector=projector,
    _residual_checker=residual,
  )
  assert result.budget_extension_triggered is True
  assert result.status == "verified"
  assert result.verified_commit_call_n == 9


def test_session_tool_definition_enumerates_authority_levers() -> None:
  tool_def = _fh_session._build_tool_definition()
  assert tool_def["name"] == "compute_cash_trajectory"
  assert tool_def["strict"] is True
  lever_props = tool_def["parameters"]["properties"]["lever_adjustments"]["properties"]
  for lever_id in _fh_handler.FUNDING_LEVER_AUTHORITY:
    assert lever_id in lever_props
  # Authority is EXCLUSIVE — operating-side levers must NOT be in the
  # tool schema (doctrine §7 anti-pattern: F6-Pinnacle authority
  # mismatch).
  for forbidden in ("expenses::Payroll", "revenue::Capacity"):
    assert forbidden not in lever_props


# --------------------------------------------------------------------------
# Two-stage handler pipeline tests.
# --------------------------------------------------------------------------


def test_handler_python_resolves_skips_gpt_session() -> None:
  # Python allocator alone can resolve → GPT session never invoked.
  gpt_mock_called = {"flag": False}
  def _mock_gpt(**kwargs: Any) -> Any:
    gpt_mock_called["flag"] = True
    return None
  result = run_funding_handler(
    cash_buffer_violations=[{"quarter_index": 3, "ending_cash": 50_000.0, "buffer": 100_000.0}],
    lever_bounds={
      "schedules::Debt Issuance (New Borrowing)": [
        {"quarter_index": 3, "current_value": 0, "max_value": 100_000, "min_value": 0},
      ],
    },
    pre_handler_finmo_quarter_rows=[],
    buffer_by_quarter={3: 100_000.0},
    _run_gpt_session=_mock_gpt,
  )
  assert result.status == FundingHandlerStatus.RESOLVED
  assert gpt_mock_called["flag"] is False
  assert "filled_by_python_allocator" in result.diagnostic


def test_handler_escalates_to_gpt_on_python_residual() -> None:
  # Python can fill $30k; need $100k. GPT mock returns a verified result.
  def _mock_session(**kwargs: Any) -> Any:
    return _fh_session.FundingToolCallSessionResult(
      status="verified",
      final_lever_adjustments={"lever_adjustments": {
        "schedules::Debt Issuance (New Borrowing)": {"5": 70_000.0},
      }},
      tool_calls_used=2,
      verified_commit_call_n=2,
    )
  result = run_funding_handler(
    cash_buffer_violations=[{"quarter_index": 5, "ending_cash": 0.0, "buffer": 100_000.0}],
    lever_bounds={
      "schedules::Debt Issuance (New Borrowing)": [
        {"quarter_index": 5, "current_value": 0, "max_value": 30_000, "min_value": 0},
      ],
    },
    pre_handler_finmo_quarter_rows=[{"quarter_index": 5, "ending_cash": 0.0}],
    buffer_by_quarter={5: 100_000.0},
    _run_gpt_session=_mock_session,
  )
  assert result.status == FundingHandlerStatus.RESOLVED
  authored = result.authored_lever_changes["schedules::Debt Issuance (New Borrowing)"]
  # Python authored 30k at Q5; GPT overlaid 70k at Q5 → 70k wins.
  assert authored[5] == 70_000.0


def test_handler_exhausted_when_gpt_session_best_effort() -> None:
  def _mock_session(**kwargs: Any) -> Any:
    return _fh_session.FundingToolCallSessionResult(
      status="best_effort_no_all_resolved",
      final_lever_adjustments=None,
      tool_calls_used=10,
      best_effort_call_n=7,
    )
  result = run_funding_handler(
    cash_buffer_violations=[{"quarter_index": 5, "ending_cash": 0.0, "buffer": 100_000.0}],
    lever_bounds={"schedules::Debt Issuance (New Borrowing)": [{"quarter_index": 5, "current_value": 0, "max_value": 1_000, "min_value": 0}]},
    pre_handler_finmo_quarter_rows=[],
    buffer_by_quarter={5: 100_000.0},
    _run_gpt_session=_mock_session,
  )
  assert result.status == FundingHandlerStatus.EXHAUSTED
  assert "gpt_session_best_effort_no_all_resolved" in result.diagnostic


def test_handler_gpt_inputs_missing_returns_exhausted() -> None:
  # No finmo_quarter_rows / buffer_by_quarter passed: handler can't
  # escalate to GPT (no probe ground), returns EXHAUSTED with specific
  # diagnostic.
  result = run_funding_handler(
    cash_buffer_violations=[{"quarter_index": 5, "ending_cash": 0.0, "buffer": 100_000.0}],
    lever_bounds={"schedules::Debt Issuance (New Borrowing)": [{"quarter_index": 5, "current_value": 0, "max_value": 1_000, "min_value": 0}]},
    pre_handler_finmo_quarter_rows=None,
    buffer_by_quarter=None,
  )
  assert result.status == FundingHandlerStatus.EXHAUSTED
  assert "gpt_inputs_missing" in result.diagnostic


def test_handler_gpt_disabled_returns_python_residual() -> None:
  result = run_funding_handler(
    cash_buffer_violations=[{"quarter_index": 5, "ending_cash": 0.0, "buffer": 100_000.0}],
    lever_bounds={"schedules::Debt Issuance (New Borrowing)": [{"quarter_index": 5, "current_value": 0, "max_value": 1_000, "min_value": 0}]},
    pre_handler_finmo_quarter_rows=[],
    buffer_by_quarter={5: 100_000.0},
    enable_gpt_session=False,
  )
  assert result.status == FundingHandlerStatus.EXHAUSTED
  assert "gpt_disabled" in result.diagnostic


# --------------------------------------------------------------------------
# Production-wiring helper tests.
# --------------------------------------------------------------------------


def _minimal_model_input_with_levers() -> Dict[str, Any]:
  # values length 21 = stub-0 + Q1..Q20.
  empty_values = [0.0] * 21
  return {
    "sections": {
      "schedules": [
        {"label": "Debt Issuance (New Borrowing)", "values": list(empty_values)},
        {"label": "Debt Repayment (Scheduled)", "values": list(empty_values)},
      ],
      "balance_sheet": [
        {"label": "Owner's Capital", "values": list(empty_values)},
        {"label": "Other Equity", "values": list(empty_values)},
        {"label": "Distributions", "values": list(empty_values)},
      ],
      "expenses": [],
      "revenue": [],
    },
  }


def test_apply_authored_lever_changes_writes_to_correct_rows() -> None:
  model_input = _minimal_model_input_with_levers()
  changes = {
    "schedules::Debt Issuance (New Borrowing)": {3: 60_000.0},
    "balance_sheet::Owner's Capital": {5: 20_000.0},
    "balance_sheet::Distributions": {10: -15_000.0},
  }
  result = apply_authored_lever_changes_to_model_input(
    model_input_json=model_input,
    authored_lever_changes=changes,
  )
  schedules = result["sections"]["schedules"]
  debt_issuance_row = next(r for r in schedules if r["label"] == "Debt Issuance (New Borrowing)")
  # stub at index 0; Q3 is index 3 (when stub present).
  assert debt_issuance_row["values"][3] == 60_000.0
  assert debt_issuance_row["values"][4] == 0.0
  bs_rows = result["sections"]["balance_sheet"]
  owners_capital = next(r for r in bs_rows if r["label"] == "Owner's Capital")
  assert owners_capital["values"][5] == 20_000.0
  distributions = next(r for r in bs_rows if r["label"] == "Distributions")
  assert distributions["values"][10] == -15_000.0


def test_apply_authored_lever_changes_accumulates_signed_deltas() -> None:
  model_input = _minimal_model_input_with_levers()
  # Pre-seed Q3 debt issuance with 10_000.
  schedules = model_input["sections"]["schedules"]
  debt_row = next(r for r in schedules if r["label"] == "Debt Issuance (New Borrowing)")
  debt_row["values"][3] = 10_000.0
  result = apply_authored_lever_changes_to_model_input(
    model_input_json=model_input,
    authored_lever_changes={"schedules::Debt Issuance (New Borrowing)": {3: 5_000.0}},
  )
  out_debt = next(
    r for r in result["sections"]["schedules"]
    if r["label"] == "Debt Issuance (New Borrowing)"
  )
  # Delta is added to existing value: 10_000 + 5_000 = 15_000.
  assert out_debt["values"][3] == 15_000.0


def test_engage_funding_handler_returns_updated_model_input_and_finmo() -> None:
  # Python allocator alone resolves; engage helper applies and rebuilds.
  build_finmo_called = {"flag": False}
  def _stub_build_finmo(mi: Dict[str, Any]) -> Dict[str, Any]:
    build_finmo_called["flag"] = True
    return {"quarter_rows": [{"quarter_index": 1, "ending_cash": 999_999}]}
  result = engage_funding_handler_on_violations(
    cash_buffer_violations=[{"quarter_index": 3, "ending_cash": 50_000, "buffer": 100_000}],
    pre_handler_model_input_json=_minimal_model_input_with_levers(),
    pre_handler_finmo_json={"quarter_rows": [{"quarter_index": 3, "ending_cash": 50_000}]},
    lever_bounds={
      "schedules::Debt Issuance (New Borrowing)": [
        {"quarter_index": 3, "current_value": 0, "max_value": 100_000, "min_value": 0},
      ],
    },
    buffer_by_quarter={3: 100_000.0},
    cash_strategy_mode="balanced",
    build_finmo=_stub_build_finmo,
  )
  assert result["status"] == "resolved"
  assert build_finmo_called["flag"] is True
  assert isinstance(result["updated_model_input_json"], dict)
  assert isinstance(result["updated_finmo_json"], dict)


def test_engage_funding_handler_returns_exhausted_without_rebuild() -> None:
  build_finmo_called = {"flag": False}
  def _stub_build_finmo(mi: Dict[str, Any]) -> Dict[str, Any]:
    build_finmo_called["flag"] = True
    return {}
  result = engage_funding_handler_on_violations(
    cash_buffer_violations=[{"quarter_index": 5, "ending_cash": 0, "buffer": 100_000}],
    pre_handler_model_input_json=_minimal_model_input_with_levers(),
    pre_handler_finmo_json={"quarter_rows": [{"quarter_index": 5, "ending_cash": 0}]},
    # No headroom anywhere — Python allocator fails; GPT inputs would
    # need to escalate, but with no real GPT seam in this synthetic
    # context the session returns failed_precondition or similar.
    lever_bounds={},
    buffer_by_quarter={5: 100_000.0},
    cash_strategy_mode="balanced",
    build_finmo=_stub_build_finmo,
  )
  # Either exhausted (residual) or partially_resolved — anything but
  # "resolved" must skip the FINMO rebuild.
  assert result["status"] != "resolved"
  assert build_finmo_called["flag"] is False
  assert result["updated_model_input_json"] is None


# --------------------------------------------------------------------------
# Orchestrator wiring — the cash orchestrator calls
# engage_funding_handler_on_violations when post-pass detects violations.
# --------------------------------------------------------------------------


def test_cash_orchestrator_imports_engage_helper() -> None:
  src = open(_cash_orch.__file__, encoding="utf-8").read()
  assert "engage_funding_handler_on_violations" in src
  assert "iter 19 Stage 4 correction" in src


def test_cash_orchestrator_invokes_handler_only_on_violations() -> None:
  src = open(_cash_orch.__file__, encoding="utf-8").read()
  # The call must be gated on cash_buffer_violations being non-empty
  # AND keep_changes being False (the post-pass tripped). This avoids
  # invoking the handler on the happy path.
  assert "if (" in src and "not keep_changes" in src
  assert "cash_buffer_violations_for_handler" in src


def test_cash_orchestrator_revalidates_after_handler_resolution() -> None:
  src = open(_cash_orch.__file__, encoding="utf-8").read()
  # After RESOLVED status, the orchestrator must re-run post-pass on
  # the new model_input + finmo.
  assert "post_handler_post_validation" in src
  assert "_cash_runner._validate_cash_strategy_post_pass" in src
  # Two calls to the validator must be present: original + post-handler.
  assert src.count("_validate_cash_strategy_post_pass") >= 2


# --------------------------------------------------------------------------
# Run.
# --------------------------------------------------------------------------


def main() -> int:
  print("running test_iter_19_stage4_correction.py")
  print("-" * 70)
  tests = [
    ("session_verified_commit", test_session_verified_commit_when_gpt_resolves_violation),
    ("session_hard_cap_best_effort", test_session_hard_cap_with_best_effort),
    ("session_gpt_stops_calling", test_session_gpt_stops_calling_tool_returns_best_effort),
    ("session_failed_precondition", test_session_failed_precondition_when_no_tool_calls),
    ("session_extension_budget", test_session_extension_budget_triggers_after_initial),
    ("session_tool_def_enumerates_authority", test_session_tool_definition_enumerates_authority_levers),
    ("handler_python_skips_gpt", test_handler_python_resolves_skips_gpt_session),
    ("handler_escalates_to_gpt_on_residual", test_handler_escalates_to_gpt_on_python_residual),
    ("handler_exhausted_on_best_effort", test_handler_exhausted_when_gpt_session_best_effort),
    ("handler_gpt_inputs_missing", test_handler_gpt_inputs_missing_returns_exhausted),
    ("handler_gpt_disabled", test_handler_gpt_disabled_returns_python_residual),
    ("apply_lever_changes_correct_rows", test_apply_authored_lever_changes_writes_to_correct_rows),
    ("apply_lever_changes_signed_deltas", test_apply_authored_lever_changes_accumulates_signed_deltas),
    ("engage_returns_updated_artifacts", test_engage_funding_handler_returns_updated_model_input_and_finmo),
    ("engage_exhausted_skips_rebuild", test_engage_funding_handler_returns_exhausted_without_rebuild),
    ("orchestrator_imports_engage_helper", test_cash_orchestrator_imports_engage_helper),
    ("orchestrator_invokes_on_violations_only", test_cash_orchestrator_invokes_handler_only_on_violations),
    ("orchestrator_revalidates_post_handler", test_cash_orchestrator_revalidates_after_handler_resolution),
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
