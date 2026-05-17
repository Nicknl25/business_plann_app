"""Iter 19 Stage 3 tests — F6-Pinnacle orchestration fix + specific
pre-cash gate diagnostic.

Per docs/architecture/doctrine.md §3 Pattern 3: when a gate's check
references a lever the handler does not own, the diagnostic must name
the upstream contract owner that skipped its writeback — not "unfixed
after handler".

This stage adds a defensive pre-gate sanity helper
(``_assert_pre_cash_gate_contract_levers_written``) in
post_intake_solver/orchestrator.py. The helper:
  - No-ops when the payroll_headcount has no quarter_totals (no
    contract authored payroll).
  - No-ops when the contract authored zero payroll across the
    horizon (lever zero is correct).
  - No-ops when the Payroll expense row in model_input has non-zero
    values (lever is written).
  - Raises a specific ``payroll_lever_not_applied_before_gate``
    diagnostic naming ``apply_payroll_headcount_payload_to_model_input``
    as the upstream skipped step otherwise.

Also confirms the convergence runner's silent-skip at
``_apply_payroll_authority`` was replaced with a logged trace event.

No MySQL, no live OpenAI. Synthetic in-memory state only.

Run: ``.venv\\Scripts\\python.exe "Test Files\\test_iter_19_stage3.py"``
"""

from __future__ import annotations

import inspect
import logging
import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Tuple

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PY = os.path.join(_ROOT, "python")
if _PY not in sys.path:
  sys.path.insert(0, _PY)

from client_intake_and_finmo.post_intake_solver.orchestrator import (  # noqa: E402
  _assert_pre_cash_gate_contract_levers_written,
)
from client_intake_and_finmo.fail_fast.common import (  # noqa: E402
  PostIntakePreconditionFailed,
)
from client_intake_and_finmo.post_intake_convergence import runner as _conv_runner  # noqa: E402


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


def _build_synthetic_state(
  *,
  payroll_payload_quarter_totals: List[float],
  model_input_payroll_values: List[float],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
  """Build minimal model_input + payroll_headcount pair to drive the
  pre-gate sanity check."""
  model_input = {
    "sections": {
      "expenses": [
        {"label": "Payroll", "values": list(model_input_payroll_values)},
      ],
    },
  }
  payroll_headcount = {
    "quarter_totals": [
      {"quarter_index": idx + 1, "payroll": float(val)}
      for idx, val in enumerate(payroll_payload_quarter_totals)
    ],
  }
  return model_input, payroll_headcount


# --------------------------------------------------------------------------
# Helper no-op cases.
# --------------------------------------------------------------------------


def test_gate_helper_no_op_when_no_payroll_headcount() -> None:
  # No quarter_totals at all → no contract authored payroll → no-op.
  _assert_pre_cash_gate_contract_levers_written(
    model_input_json={"sections": {"expenses": []}},
    payroll_headcount={},
  )


def test_gate_helper_no_op_when_quarter_totals_empty() -> None:
  _assert_pre_cash_gate_contract_levers_written(
    model_input_json={"sections": {"expenses": []}},
    payroll_headcount={"quarter_totals": []},
  )


def test_gate_helper_no_op_when_contract_authored_zero_payroll() -> None:
  # Contract authored zero payroll across the horizon → zero lever is
  # the correct state → no-op.
  model_input, payroll = _build_synthetic_state(
    payroll_payload_quarter_totals=[0.0, 0.0, 0.0],
    model_input_payroll_values=[0.0, 0.0, 0.0, 0.0],
  )
  _assert_pre_cash_gate_contract_levers_written(
    model_input_json=model_input,
    payroll_headcount=payroll,
  )


def test_gate_helper_no_op_when_lever_is_written() -> None:
  # Contract has positive totals; model_input has matching positive
  # values; the gate should proceed.
  model_input, payroll = _build_synthetic_state(
    payroll_payload_quarter_totals=[100_000.0, 110_000.0, 120_000.0],
    model_input_payroll_values=[0.0, 100_000.0, 110_000.0, 120_000.0],
  )
  _assert_pre_cash_gate_contract_levers_written(
    model_input_json=model_input,
    payroll_headcount=payroll,
  )


def test_gate_helper_no_op_when_payroll_expense_row_missing() -> None:
  # If the Payroll expense row itself is missing, that's a different
  # validator's problem; this helper does not double-raise.
  payroll_headcount = {
    "quarter_totals": [
      {"quarter_index": 1, "payroll": 100_000.0},
    ],
  }
  _assert_pre_cash_gate_contract_levers_written(
    model_input_json={"sections": {"expenses": []}},
    payroll_headcount=payroll_headcount,
  )


# --------------------------------------------------------------------------
# Helper raises specific diagnostic.
# --------------------------------------------------------------------------


def test_gate_helper_raises_specific_diagnostic_when_lever_zero() -> None:
  # Contract authored positive payroll across multiple quarters; the
  # model_input Payroll lever is all zero. The helper must raise
  # PostIntakePreconditionFailed with the specific operation key.
  model_input, payroll = _build_synthetic_state(
    payroll_payload_quarter_totals=[100_000.0, 110_000.0, 120_000.0],
    model_input_payroll_values=[0.0, 0.0, 0.0, 0.0],
  )
  raised = None
  try:
    _assert_pre_cash_gate_contract_levers_written(
      model_input_json=model_input,
      payroll_headcount=payroll,
    )
  except PostIntakePreconditionFailed as exc:
    raised = exc
  assert raised is not None, "expected PostIntakePreconditionFailed"
  assert raised.operation == "payroll_lever_not_applied_before_gate"
  assert raised.pipeline_stage == "post_intake_pre_cash_gpt_authorable_gate"
  assert raised.details.get("upstream_skipped_step") == "apply_payroll_headcount_payload_to_model_input"
  assert raised.details.get("upstream_contract_owner") == "payroll_headcount_schedule"
  assert "doctrine.md" in str(raised.details.get("doctrine_reference") or "")
  assert int(raised.details.get("schedule_quarters_with_payroll") or 0) == 3


def test_gate_helper_diagnostic_message_names_upstream_owner() -> None:
  model_input, payroll = _build_synthetic_state(
    payroll_payload_quarter_totals=[50_000.0],
    model_input_payroll_values=[0.0, 0.0],
  )
  raised = None
  try:
    _assert_pre_cash_gate_contract_levers_written(
      model_input_json=model_input,
      payroll_headcount=payroll,
    )
  except PostIntakePreconditionFailed as exc:
    raised = exc
  assert raised is not None
  message = str(raised)
  # The structured message should NOT generically blame the handler.
  assert "unfixed_after_handler" not in message
  assert "payroll_lever_not_applied_before_gate" in message


# --------------------------------------------------------------------------
# Convergence runner: silent-skip replaced with logged trace.
# --------------------------------------------------------------------------


def test_convergence_runner_imports_logger() -> None:
  # The silent fall-through was replaced with a structured logger.info
  # call; the module must therefore import logging.
  assert hasattr(_conv_runner, "_logger")
  assert isinstance(_conv_runner._logger, logging.Logger)


def test_convergence_runner_skip_message_is_traceable() -> None:
  # Source-inspect the runner to confirm the new log message that
  # replaced the silent return is present and references the pre-cash
  # gate's lever-written assertion.
  src = open(_conv_runner.__file__, encoding="utf-8").read()
  assert "convergence_apply_payroll_authority_skipped" in src
  assert "pre-cash gate" in src.lower() or "pre_cash" in src.lower() or "pre cash" in src.lower()
  assert "lever-written" in src.lower() or "lever_written" in src.lower() or "lever written" in src.lower()


# --------------------------------------------------------------------------
# Orchestrator wiring: the helper is called before the gate.
# --------------------------------------------------------------------------


def test_orchestrator_calls_pre_gate_helper_before_evaluating_checks() -> None:
  from client_intake_and_finmo.post_intake_solver import orchestrator as _orch
  src = open(_orch.__file__, encoding="utf-8").read()
  # The call site must appear textually before the first
  # _evaluate_gpt_authorable_pre_cash_checks invocation; confirms the
  # diagnostic fires first.
  assert "_assert_pre_cash_gate_contract_levers_written(" in src
  helper_pos = src.index("_assert_pre_cash_gate_contract_levers_written(")
  first_gate_eval_pos = src.index("gate_violations, gate_scope = _evaluate_gpt_authorable_pre_cash_checks(")
  assert helper_pos < first_gate_eval_pos, "helper must fire before the gate evaluator"


# --------------------------------------------------------------------------
# Run.
# --------------------------------------------------------------------------


def main() -> int:
  print("running test_iter_19_stage3.py")
  print("-" * 70)
  tests = [
    ("gate_helper_no_op_no_headcount", test_gate_helper_no_op_when_no_payroll_headcount),
    ("gate_helper_no_op_empty_quarter_totals", test_gate_helper_no_op_when_quarter_totals_empty),
    ("gate_helper_no_op_zero_payroll_authored", test_gate_helper_no_op_when_contract_authored_zero_payroll),
    ("gate_helper_no_op_lever_written", test_gate_helper_no_op_when_lever_is_written),
    ("gate_helper_no_op_payroll_row_missing", test_gate_helper_no_op_when_payroll_expense_row_missing),
    ("gate_helper_raises_specific_diagnostic", test_gate_helper_raises_specific_diagnostic_when_lever_zero),
    ("gate_helper_diagnostic_names_upstream", test_gate_helper_diagnostic_message_names_upstream_owner),
    ("convergence_runner_imports_logger", test_convergence_runner_imports_logger),
    ("convergence_runner_skip_traceable", test_convergence_runner_skip_message_is_traceable),
    ("orchestrator_calls_pre_gate_helper_first", test_orchestrator_calls_pre_gate_helper_before_evaluating_checks),
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
