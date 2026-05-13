"""Phase 9 P3.10 Bug F + Bug D — smoke tests for the pre-cash post-
handler gate that runs GPT-authorable checks moved out of finalize.

Verifies:
  - The moved checks no longer fire from
    assert_post_intake_business_shape_applied (single source of truth).
  - balance_sheet_driver_zero_but_applicable is no longer emitted by
    balance_sheet_driver_finalize_errors (extracted to its own
    function).
  - balance_sheet_driver_zero_but_applicable_errors returns structured
    dicts (not bare error strings) so the gate can translate them.
  - The pre-cash gate's check enumerator
    (_evaluate_gpt_authorable_pre_cash_checks) returns failing_metrics
    in handler-compatible format.
  - _decide_handler_scope_from_failing_metrics picks PNL_PATH when any
    P&L lever is implicated; BS_ONLY_PATH when only WC/BS levers are.
  - _PreCashGateRestorationResult exposes the same shape the handler
    expects (status, scope, failing_metrics, q11_ebitda_margin,
    to_dict).
  - _GPT_AUTHORABLE_PRE_CASH_CHECK_NAMES is the documented constant.
"""

from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Dict, List


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


class BugFDPreCashPostHandlerGateTest(unittest.TestCase):
  def test_module_constant_exposes_three_check_names(self) -> None:
    from client_intake_and_finmo.post_intake_solver.orchestrator import (  # noqa: WPS433
      _GPT_AUTHORABLE_PRE_CASH_CHECK_NAMES,
    )
    self.assertEqual(
      tuple(_GPT_AUTHORABLE_PRE_CASH_CHECK_NAMES),
      (
        "stage_ramp_expense_path_applied",
        "stage_ramp_profitability_path_applied",
        "balance_sheet_driver_zero_but_applicable",
      ),
    )

  def test_business_shape_no_longer_calls_moved_asserts(self) -> None:
    """Source-level: the body of assert_post_intake_business_shape_applied
    must not contain calls to the moved asserts."""
    import pathlib
    p = (
      pathlib.Path(PYTHON_ROOT)
      / "client_intake_and_finmo"
      / "fail_fast"
      / "post_intake_fail_fast"
      / "fail_fast.py"
    )
    text = p.read_text(encoding="utf-8")
    # Find the function body
    start = text.index("def assert_post_intake_business_shape_applied(")
    # Roughly capture the next ~80 lines (the function body)
    body = text[start: start + 4000]
    # Calls to the moved asserts should appear only inside comments (the
    # MOVED-to-pre-cash-gate documentation), not as live function calls.
    for line in body.split("\n"):
      stripped = line.strip()
      if stripped.startswith("#"):
        continue  # comment lines OK
      self.assertNotIn(
        "assert_stage_ramp_expense_path_applied(", stripped,
        f"Live call found: {line!r}",
      )
      self.assertNotIn(
        "assert_stage_ramp_profitability_path_applied(", stripped,
        f"Live call found: {line!r}",
      )

  def test_balance_sheet_finalize_errors_no_longer_emits_zero_but_applicable(self) -> None:
    """Source-level: the zero_but_applicable error string is no longer
    appended to the errors list inside balance_sheet_driver_finalize_errors."""
    import pathlib
    p = (
      pathlib.Path(PYTHON_ROOT)
      / "client_intake_and_finmo"
      / "post_intake_runtime_validation"
      / "balance_sheet_driver_validation.py"
    )
    text = p.read_text(encoding="utf-8")
    start = text.index("def balance_sheet_driver_finalize_errors(")
    end = text.index("def balance_sheet_driver_zero_but_applicable_errors(")
    body = text[start:end]
    self.assertNotIn(
      'errors.append(\n        f"balance_sheet_driver_zero_but_applicable:',
      body,
      "balance_sheet_driver_finalize_errors must no longer emit "
      "balance_sheet_driver_zero_but_applicable errors",
    )

  def test_extracted_zero_but_applicable_function_returns_structured_dicts(self) -> None:
    """The new balance_sheet_driver_zero_but_applicable_errors returns
    structured dicts (not bare strings) so the gate can translate them."""
    from client_intake_and_finmo.post_intake_runtime_validation.balance_sheet_driver_validation import (  # noqa: WPS433
      balance_sheet_driver_zero_but_applicable_errors,
    )
    out = balance_sheet_driver_zero_but_applicable_errors(
      financials_json={},
      ops_json={},
      model_input_json={},
      finmo_json={},
      debt_schedule=None,
      cash_strategy_second_pass_result=None,
    )
    self.assertIsInstance(out, list)
    # Every element is a dict (not a string)
    for item in out:
      self.assertIsInstance(item, dict)

  def test_decide_handler_scope_pnl_path_when_pnl_lever_present(self) -> None:
    from client_intake_and_finmo.post_intake_solver.orchestrator import (  # noqa: WPS433
      _decide_handler_scope_from_failing_metrics,
    )
    from client_intake_and_finmo.post_intake_target_solver import (  # noqa: WPS433
      HandlerScope,
    )
    failing_metrics = [
      {"metric_key": "marketing_percent_of_revenue", "primary_levers": ["expenses::Marketing"]},
    ]
    self.assertEqual(
      _decide_handler_scope_from_failing_metrics(failing_metrics),
      HandlerScope.PNL_PATH,
    )

  def test_decide_handler_scope_bs_only_when_only_bs_levers(self) -> None:
    from client_intake_and_finmo.post_intake_solver.orchestrator import (  # noqa: WPS433
      _decide_handler_scope_from_failing_metrics,
    )
    from client_intake_and_finmo.post_intake_target_solver import (  # noqa: WPS433
      HandlerScope,
    )
    failing_metrics = [
      {"metric_key": "deferred_revenue_percent_of_revenue",
       "primary_levers": ["balance_sheet::Deferred Revenue (% of Revenue)"]},
      {"metric_key": "ar_days_dso",
       "primary_levers": ["balance_sheet::Accounts Receivable Days"]},
    ]
    self.assertEqual(
      _decide_handler_scope_from_failing_metrics(failing_metrics),
      HandlerScope.BS_ONLY_PATH,
    )

  def test_decide_handler_scope_pnl_path_for_mixed(self) -> None:
    from client_intake_and_finmo.post_intake_solver.orchestrator import (  # noqa: WPS433
      _decide_handler_scope_from_failing_metrics,
    )
    from client_intake_and_finmo.post_intake_target_solver import (  # noqa: WPS433
      HandlerScope,
    )
    failing_metrics = [
      {"metric_key": "marketing_percent_of_revenue", "primary_levers": ["expenses::Marketing"]},
      {"metric_key": "ar_days_dso",
       "primary_levers": ["balance_sheet::Accounts Receivable Days"]},
    ]
    self.assertEqual(
      _decide_handler_scope_from_failing_metrics(failing_metrics),
      HandlerScope.PNL_PATH,
    )

  def test_pre_cash_gate_restoration_result_has_handler_compatible_shape(self) -> None:
    from client_intake_and_finmo.post_intake_solver.orchestrator import (  # noqa: WPS433
      _PreCashGateRestorationResult,
    )
    from client_intake_and_finmo.post_intake_target_solver import (  # noqa: WPS433
      HandlerScope,
      RestorationStatus,
    )
    fm: List[Dict[str, Any]] = [
      {"metric_key": "marketing_percent_of_revenue", "primary_levers": ["expenses::Marketing"]},
    ]
    result = _PreCashGateRestorationResult(
      scope=HandlerScope.PNL_PATH,
      failing_metrics=fm,
      q11_ebitda_margin=-0.13,
    )
    self.assertEqual(result.status, RestorationStatus.EXHAUSTED)
    self.assertEqual(result.scope, HandlerScope.PNL_PATH)
    self.assertEqual(result.failing_metrics, fm)
    self.assertAlmostEqual(result.q11_ebitda_margin, -0.13)
    payload = result.to_dict()
    self.assertEqual(payload["status"], "exhausted")
    self.assertEqual(payload["scope"], "pnl_path")
    self.assertEqual(payload["failing_metrics"], fm)
    self.assertEqual(payload["reason"], "pre_cash_gate_gpt_authorable_check_failure")

  def test_q11_ebitda_margin_from_finmo_returns_ratio_when_present(self) -> None:
    from client_intake_and_finmo.post_intake_solver.orchestrator import (  # noqa: WPS433
      _q11_ebitda_margin_from_finmo,
    )
    finmo = {
      "quarter_rows": [
        {"quarter_index": q, "revenue": 1000.0, "ebitda": -130.0 if q == 11 else 0.0}
        for q in range(1, 21)
      ],
    }
    self.assertAlmostEqual(_q11_ebitda_margin_from_finmo(finmo), -0.13)

  def test_q11_ebitda_margin_from_finmo_returns_none_when_revenue_zero(self) -> None:
    from client_intake_and_finmo.post_intake_solver.orchestrator import (  # noqa: WPS433
      _q11_ebitda_margin_from_finmo,
    )
    finmo = {
      "quarter_rows": [
        {"quarter_index": q, "revenue": 0.0, "ebitda": -130.0 if q == 11 else 0.0}
        for q in range(1, 21)
      ],
    }
    self.assertIsNone(_q11_ebitda_margin_from_finmo(finmo))

  def test_evaluate_gpt_authorable_pre_cash_checks_returns_empty_for_clean_state(self) -> None:
    """With empty inputs, the evaluator should return no failing_metrics
    (the asserts can't find violations against an empty stage_ramp /
    finmo). Returns BS_ONLY_PATH scope by default."""
    from client_intake_and_finmo.post_intake_solver.orchestrator import (  # noqa: WPS433
      _evaluate_gpt_authorable_pre_cash_checks,
    )
    from client_intake_and_finmo.post_intake_target_solver import (  # noqa: WPS433
      HandlerScope,
    )
    failing_metrics, scope = _evaluate_gpt_authorable_pre_cash_checks(
      stage_ramp_contract={},
      model_input_json={},
      finmo_json={},
      payroll_headcount={},
      financials_json={},
      ops_json={},
    )
    self.assertEqual(failing_metrics, [])
    self.assertEqual(scope, HandlerScope.BS_ONLY_PATH)


if __name__ == "__main__":
  unittest.main()
