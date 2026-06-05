"""Phase 9 P3.33 Phase 3 step 8a — session_factory + audit wrapper.

Hermetic tests for:
  - make_session_driver: builds a SessionDriver wired to the production
    callbacks (responder, revise_fn_for_section, log_fn, etc.).
  - revise_fn_for_section: dispatches section names to the right
    revise_* tool (consistency check with the post-WC-migration
    section vocabulary).
  - current_payload_for: reads from mirror.plan_state with aliases.
  - primitive_kwargs_for_mode: emits the right kwarg shape per
    FailureMode.
  - driver_run_with_audit_wrapper: failure-path helper writes a
    best-effort META row, swallows audit failure to stderr, ALWAYS
    re-raises as amalgamated_session_failed_catastrophically.
"""

from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stderr
from typing import Any, Dict


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)

from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (  # noqa: E402
  CheckResult, EvaluatePlanResult, FailureMode,
)
from client_intake_and_finmo.post_intake_amalgamated.mirror import Mirror  # noqa: E402
from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (  # noqa: E402,E501
  AppliedBy, ReasonCode, StepType,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E402,E501
  ProposalResponse,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.session_factory import (  # noqa: E402,E501
  driver_run_with_audit_wrapper, make_session_driver,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.session_driver import (  # noqa: E402,E501
  SessionDriver, TerminationState,
)


def _passing_result(round_number=1):
  return EvaluatePlanResult(
    all_pass=True, round_number=round_number,
    structural_completeness=True, strictness="full_acceptance_gate",
    checks=[CheckResult(name="ebitda_positive_by_q11", passed=True)],
  )


class MakeSessionDriverTest(unittest.TestCase):
  def test_constructs_driver_with_injected_responder(self) -> None:
    mirror = Mirror(business_facts={"naics_6": "722511"})
    fake_responder = lambda **_: ProposalResponse(kind="confirm")
    driver = make_session_driver(
      conn=None, draft_id="d", planning_run_id="r",
      mirror=mirror, responder=fake_responder,
    )
    self.assertIsInstance(driver, SessionDriver)
    self.assertEqual(driver.state.draft_id, "d")
    self.assertEqual(driver.state.planning_run_id, "r")

  def test_budget_override_passes_through(self) -> None:
    mirror = Mirror()
    driver = make_session_driver(
      conn=None, draft_id="d", planning_run_id="r",
      mirror=mirror, responder=lambda **_: ProposalResponse(kind="confirm"),
      budget=12,
    )
    self.assertEqual(driver.state.tool_call_budget_remaining, 12)


class ReviseFnDispatchTest(unittest.TestCase):
  """Confirm the post-WC-migration section vocabulary maps to the right
  revise_* tools."""

  def _dispatch(self):
    from client_intake_and_finmo.post_intake_amalgamated.protocol.session_factory import (  # noqa: E501
      _build_revise_fn_for_section,
    )
    mirror = Mirror()
    return _build_revise_fn_for_section(
      conn=None, draft_id="d", planning_run_id="r", mirror=mirror,
    )

  def test_drivers_section_dispatches(self) -> None:
    self.assertIsNotNone(self._dispatch()("drivers"))

  def test_stage_ramp_section_dispatches(self) -> None:
    self.assertIsNotNone(self._dispatch()("stage_ramp"))

  def test_payroll_section_dispatches(self) -> None:
    self.assertIsNotNone(self._dispatch()("payroll"))

  def test_balance_sheet_section_dispatches(self) -> None:
    """Post-WC-migration: balance_sheet section -> revise_capex_rd_balance_seed."""
    self.assertIsNotNone(self._dispatch()("balance_sheet"))

  def test_capex_rd_section_dispatches(self) -> None:
    self.assertIsNotNone(self._dispatch()("capex_rd"))

  def test_combined_section_name_dispatches(self) -> None:
    self.assertIsNotNone(self._dispatch()("capex_rd_balance_seed"))

  def test_operating_model_now_dispatches(self) -> None:
    """Fork A B1: operating_model now HAS a revise_* tool
    (revise_operating_model) so the executive's price/utilization/capacity
    moves actually apply (was previously a no-op that returned None)."""
    self.assertIsNotNone(self._dispatch()("operating_model"))

  def test_unknown_section_returns_none(self) -> None:
    """A genuinely unknown section has no revise_* tool; the driver
    handles None gracefully by logging-without-applying and advancing."""
    self.assertIsNone(self._dispatch()("not_a_real_section"))


class CurrentPayloadForTest(unittest.TestCase):
  def _reader(self, plan_state):
    from client_intake_and_finmo.post_intake_amalgamated.protocol.session_factory import (  # noqa: E501
      _build_current_payload_for,
    )
    mirror = Mirror(plan_state=plan_state or {})
    return _build_current_payload_for(mirror)

  def test_drivers_section_read(self) -> None:
    reader = self._reader({"drivers": {"expenses::Cost of Goods Sold": {"q1": 0.72}}})
    self.assertEqual(
      reader("drivers"),
      {"expenses::Cost of Goods Sold": {"q1": 0.72}},
    )

  def test_balance_sheet_aliases_to_capex_rd_balance_seed(self) -> None:
    """If the mirror stored payload under 'capex_rd_balance_seed' but a
    proposal arrives with section='balance_sheet', the reader should
    fall through to the alias."""
    reader = self._reader({"capex_rd_balance_seed": {"prior": "overrides"}})
    self.assertEqual(reader("balance_sheet"), {"prior": "overrides"})

  def test_capex_rd_aliases_to_balance_sheet(self) -> None:
    reader = self._reader({"balance_sheet": {"prior": "overrides"}})
    self.assertEqual(reader("capex_rd"), {"prior": "overrides"})


class PrimitiveKwargsForModeTest(unittest.TestCase):
  def _builder(self, *, mirror=None, model_input=None, finmo=None,
               stage_ramp=None, build_finmo=None):
    from client_intake_and_finmo.post_intake_amalgamated.protocol.session_factory import (  # noqa: E501
      _build_primitive_kwargs_for_mode,
    )
    return _build_primitive_kwargs_for_mode(
      mirror=mirror or Mirror(),
      model_input_json=model_input, finmo_json=finmo,
      stage_ramp_contract=stage_ramp, build_finmo=build_finmo,
    )

  def test_viability_kwargs(self) -> None:
    build = self._builder(model_input={"a": 1}, stage_ramp={"x": 2})
    kw = build(FailureMode.VIABILITY_INVARIANT)
    self.assertEqual(set(kw), {"model_input", "build_finmo", "stage_ramp_contract"})
    self.assertEqual(kw["model_input"], {"a": 1})

  def test_growth_kwargs_include_max_passes(self) -> None:
    build = self._builder()
    kw = build(FailureMode.GROWTH_INVARIANT)
    self.assertEqual(kw["max_passes"], 12)

  def test_capacity_kwargs_pull_from_business_facts(self) -> None:
    mirror = Mirror(business_facts={
      "target_q12_revenue": 1_000_000.0,
      "unit_price": 50.0, "cohort_util_target": 0.7,
    })
    kw = self._builder(mirror=mirror)(FailureMode.CAPACITY_INVARIANT)
    self.assertAlmostEqual(kw["target_q12_revenue"], 1_000_000.0)
    self.assertAlmostEqual(kw["unit_price"], 50.0)
    self.assertAlmostEqual(kw["cohort_util_target"], 0.7)

  def test_band_kwargs_pull_lever_margins_from_validation_state(self) -> None:
    mirror = Mirror(validation_state={"lever_margins": [{"x": 1}]})
    kw = self._builder(mirror=mirror)(FailureMode.BAND_INVARIANT)
    self.assertEqual(kw["lever_margins"], [{"x": 1}])

  def test_coherence_kwargs_use_anchor_order(self) -> None:
    kw = self._builder()(FailureMode.COHERENCE_INVARIANT)
    self.assertEqual(kw["anchor_section"], "stage_ramp")
    self.assertEqual(set(kw["non_anchor_sections"]),
                     {"drivers", "payroll", "capex_rd", "balance_sheet"})


class DriverRunWithAuditWrapperTest(unittest.TestCase):
  def _build_driver(self, *, run_raises=False):
    """Build a driver whose evaluate_plan_fn returns passing immediately
    (so run() succeeds), OR whose responder raises (so run() raises)."""
    if run_raises:
      def fake_eval(*, round_number):
        raise RuntimeError("simulated_evaluate_plan_failure")
    else:
      def fake_eval(*, round_number): return _passing_result(round_number=round_number)
    return SessionDriver(
      draft_id="d", planning_run_id="r",
      evaluate_plan_fn=fake_eval,
      responder=lambda **_: ProposalResponse(kind="confirm"),
      revise_fn_for_section=lambda s: None,
    )

  def test_happy_path_returns_driver_result(self) -> None:
    driver = self._build_driver()
    res = driver_run_with_audit_wrapper(driver=driver, conn=None)
    self.assertEqual(res.termination_state, TerminationState.RESOLVED)

  def test_run_exception_raises_structured_runtime_error(self) -> None:
    driver = self._build_driver(run_raises=True)
    with self.assertRaises(RuntimeError) as ctx:
      driver_run_with_audit_wrapper(driver=driver, conn=None)
    self.assertIn("amalgamated_session_failed_catastrophically", str(ctx.exception))
    self.assertIn("RuntimeError", str(ctx.exception))
    self.assertIn("simulated_evaluate_plan_failure", str(ctx.exception))
    self.assertIsNotNone(ctx.exception.__cause__)

  def test_audit_write_called_on_failure(self) -> None:
    """When driver.run() raises, the wrapper calls log_restructure with
    a META_ESCALATED row before re-raising."""
    captured = {"rows": []}
    def fake_logger(conn=None, **kwargs):
      captured["rows"].append(dict(kwargs))
      return None

    from client_intake_and_finmo.post_intake_amalgamated.protocol import (
      session_factory as sf_mod,
    )
    driver = self._build_driver(run_raises=True)
    original_log_restructure = sf_mod.log_restructure
    sf_mod.log_restructure = fake_logger
    try:
      with self.assertRaises(RuntimeError):
        driver_run_with_audit_wrapper(driver=driver, conn=None)
    finally:
      sf_mod.log_restructure = original_log_restructure
    self.assertEqual(len(captured["rows"]), 1)
    row = captured["rows"][0]
    self.assertEqual(row["failure_mode"], FailureMode.META_INVARIANT)
    self.assertEqual(row["reason_code"], ReasonCode.META_ESCALATED)
    self.assertEqual(row["step_type"], StepType.META)
    self.assertEqual(row["applied_by"], AppliedBy.META_ESCALATION)
    self.assertIn("simulated_evaluate_plan_failure", row["veto_reason"])

  def test_audit_write_failure_logged_to_stderr_does_not_swallow_original(self) -> None:
    """If the audit log_restructure ITSELF raises, the wrapper prints
    to stderr and STILL re-raises the structured RuntimeError. The
    original session exception is preserved as __cause__."""
    from client_intake_and_finmo.post_intake_amalgamated.protocol import (
      session_factory as sf_mod,
    )
    def exploding_logger(conn=None, **kwargs):
      raise RuntimeError("db_connection_lost_during_audit")
    driver = self._build_driver(run_raises=True)
    original_log_restructure = sf_mod.log_restructure
    sf_mod.log_restructure = exploding_logger
    err = io.StringIO()
    try:
      with redirect_stderr(err):
        with self.assertRaises(RuntimeError) as ctx:
          driver_run_with_audit_wrapper(driver=driver, conn=None)
    finally:
      sf_mod.log_restructure = original_log_restructure
    self.assertIn("amalgamated_session_failed_catastrophically", str(ctx.exception))
    self.assertIn("amalgamated_session_audit_write_failed", err.getvalue())
    self.assertIn("db_connection_lost_during_audit", err.getvalue())


if __name__ == "__main__":
  unittest.main()
