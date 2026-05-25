"""Phase 9 P3.33 Phase 3 step 8b — orchestrator wiring integration test.

Hermetic test that the amalgamated session block inside
``prepare_initial_grid_for_draft`` invokes a SessionDriver, records
the termination state into ``shared_context``, and tolerates an
exception in the driver without breaking the rest of the pipeline.

The full prepare_initial_grid_for_draft is too heavy to run hermetically
(it requires a live DB + intake state). This test verifies the
integration shape at the SessionDriver level: that make_session_driver +
driver_run_with_audit_wrapper compose end-to-end against a synthetic
mirror + fake evaluate_plan + fake responder, exactly as the orchestrator
block invokes them.

Read alongside test_phase_9_p3_33_phase3_step8a_session_factory.py
which covers the factory + audit wrapper in isolation.
"""

from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)

from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (  # noqa: E402
  CheckResult, EvaluatePlanResult, FailureMode, LeverMargin,
)
from client_intake_and_finmo.post_intake_amalgamated.mirror import (  # noqa: E402
  build_mirror,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E402,E501
  ProposalResponse,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.session_factory import (  # noqa: E402,E501
  driver_run_with_audit_wrapper, make_session_driver,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.session_driver import (  # noqa: E402,E501
  TerminationState,
)


def _passing_result(*, round_number=1):
  return EvaluatePlanResult(
    all_pass=True, round_number=round_number,
    structural_completeness=True, strictness="full_acceptance_gate",
    checks=[CheckResult(name="ebitda_positive_by_q11", passed=True)],
  )


def _viability_failing_then_passing():
  """Sequence: round 1 fails (V1 cascade triggers), then any subsequent
  round returns passing."""
  states = {"calls": 0}
  def fake_eval(*, round_number):
    states["calls"] += 1
    if states["calls"] == 1:
      return EvaluatePlanResult(
        all_pass=False, round_number=round_number,
        structural_completeness=True,
        strictness="full_acceptance_gate",
        checks=[CheckResult(
          name="ebitda_positive_by_q11", passed=False,
          failure_mode=FailureMode.VIABILITY_INVARIANT,
          distance_to_feasibility=-0.04,
        )],
        lever_margins=[LeverMargin(
          lever_id="expenses::Cost of Goods Sold", section="drivers",
          current=0.72, band_min=0.55, band_target=0.65, band_max=0.78,
        )],
        worst_failing_check="ebitda_positive_by_q11",
        worst_failing_distance=-0.04,
      )
    return _passing_result(round_number=round_number)
  return fake_eval


class IntegrationShapeTest(unittest.TestCase):
  """Confirms make_session_driver + driver_run_with_audit_wrapper produce
  a working session against a hermetic mirror+responder pair, matching
  the call shape used inside prepare_initial_grid_for_draft."""

  def _build_mirror(self):
    return build_mirror(
      None,
      draft_id="d", planning_run_id="r",
      business_facts={"naics_6": "722511", "business_stage": "operational"},
      plan_state={"stage_ramp": {}, "payroll": {}, "drivers": {},
                  "capex_rd_balance_seed": {}, "balance_sheet": {}},
      load_bands=False,
    )

  def test_happy_path_all_pass_immediately(self) -> None:
    """When evaluate_plan returns all_pass=True on round 1, the
    session terminates RESOLVED without calling the responder."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
      def never_called(**_): self.fail("responder must not run when all_pass")
      driver = make_session_driver(
        conn=None, draft_id="d", planning_run_id="r",
        mirror=self._build_mirror(),
        responder=never_called,
      )
      # Replace the live evaluate_plan_fn the factory wired with a fake.
      driver._evaluate_plan_fn = lambda *, round_number: _passing_result(
        round_number=round_number,
      )
      res = driver_run_with_audit_wrapper(driver=driver, conn=None)
      self.assertEqual(res.termination_state, TerminationState.RESOLVED)
      self.assertEqual(res.applied_steps, 0)

  def test_cascade_triggers_then_resolves_via_responder(self) -> None:
    """Round 1 returns a VIABILITY failure; V1 cascade fires with a
    confirm response; round 2 returns passing → RESOLVED."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
      driver = make_session_driver(
        conn=None, draft_id="d", planning_run_id="r",
        mirror=self._build_mirror(),
        responder=lambda **_: ProposalResponse(kind="confirm"),
      )
      driver._evaluate_plan_fn = _viability_failing_then_passing()
      # Stub revise_fn so the "drivers" section accepts.
      driver._revise_fn_for_section = lambda section: (
        (lambda **kwargs: {
          "accepted": True, "section": section, "violations": [],
        })
        if section == "drivers" else None
      )
      res = driver_run_with_audit_wrapper(driver=driver, conn=None)
      self.assertEqual(res.termination_state, TerminationState.RESOLVED)

  def test_synthetic_veto_drives_to_floor_when_no_api_key(self) -> None:
    """OPENAI_API_KEY unset → responder returns synthetic veto for
    every proposal → cascade walks all tiers → floor invoked. End
    state: not RESOLVED (mode stays failing); floor_invocations > 0."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
      driver = make_session_driver(
        conn=None, draft_id="d", planning_run_id="r",
        mirror=self._build_mirror(),
        # No responder= -> factory builds the production one, which
        # synthetic-vetos when OPENAI_API_KEY is unset.
      )
      def always_failing(*, round_number):
        return EvaluatePlanResult(
          all_pass=False, round_number=round_number,
          structural_completeness=True,
          strictness="full_acceptance_gate",
          checks=[CheckResult(
            name="ebitda_positive_by_q11", passed=False,
            failure_mode=FailureMode.VIABILITY_INVARIANT,
            distance_to_feasibility=-0.04,
          )],
          lever_margins=[LeverMargin(
            lever_id="expenses::Cost of Goods Sold", section="drivers",
            current=0.72, band_min=0.55, band_target=0.65, band_max=0.78,
          )],
          worst_failing_check="ebitda_positive_by_q11",
          worst_failing_distance=-0.04,
        )
      driver._evaluate_plan_fn = always_failing
      res = driver_run_with_audit_wrapper(driver=driver, conn=None)
      self.assertIn(res.termination_state, (
        TerminationState.STAGNATION_FLOOR_ALL,
        TerminationState.BUDGET_EXHAUSTED_FLOOR,
        TerminationState.MODE_FLOOR,
      ))
      self.assertGreaterEqual(res.floor_invocations, 1)

  def test_driver_exception_propagates_as_structured_runtime_error(self) -> None:
    """If the driver itself raises, the wrapper writes a META audit row
    (best-effort) and re-raises as
    amalgamated_session_failed_catastrophically. The orchestrator catches
    this and continues with the pre-amalgamated state."""
    driver = make_session_driver(
      conn=None, draft_id="d", planning_run_id="r",
      mirror=self._build_mirror(),
      responder=lambda **_: ProposalResponse(kind="confirm"),
    )
    def raising_eval(*, round_number):
      raise RuntimeError("simulated_evaluate_plan_explosion")
    driver._evaluate_plan_fn = raising_eval
    err = io.StringIO()
    with redirect_stderr(err):
      with self.assertRaises(RuntimeError) as ctx:
        driver_run_with_audit_wrapper(driver=driver, conn=None)
    self.assertIn("amalgamated_session_failed_catastrophically", str(ctx.exception))
    self.assertIn("simulated_evaluate_plan_explosion", str(ctx.exception))


class OrchestratorBlockShapeTest(unittest.TestCase):
  """Verifies the integration-block code-shape in
  prepare_initial_grid_for_draft references the right symbols.
  Source-shape regression check; cheap to run."""

  def test_initial_grid_runner_imports_session_factory(self) -> None:
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "python"
           / "client_intake_and_finmo" / "post_intake_initial_grid"
           / "runner.py").read_text(encoding="utf-8")
    self.assertIn(
      "from client_intake_and_finmo.post_intake_amalgamated.protocol.session_factory import",
      src,
    )
    self.assertIn("make_session_driver", src)
    self.assertIn("driver_run_with_audit_wrapper", src)
    self.assertIn("build_mirror", src)
    self.assertIn("amalgamated_session_result", src)

  def test_integration_block_does_not_silently_swallow_driver_exception(self) -> None:
    """P3.33 Phase 3 8b-fix — the orchestrator MUST NOT wrap
    driver_run_with_audit_wrapper in a try/except that records
    EXCEPTION_HALTED and continues. Item D from the step-8 design
    discussion: on driver catastrophe the RuntimeError propagates
    out of prepare_initial_grid_for_draft as a planning_run failure.
    The audit row landing is the wrapper's job; pipeline behavior on
    exception is FAIL, not degrade."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "python"
           / "client_intake_and_finmo" / "post_intake_initial_grid"
           / "runner.py").read_text(encoding="utf-8")
    self.assertIn("driver_run_with_audit_wrapper(", src)
    self.assertNotIn("except Exception as amalgamated_exc:", src)
    self.assertNotIn("EXCEPTION_HALTED", src)

  def test_orchestrator_uses_set_star_contract_none_for_round1(self) -> None:
    """8b-fix REPLACE pattern — round-1 authoring goes through
    set_*(contract=None) calls, not _execute_sequence_step legacy
    GPT authoring."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "python"
           / "client_intake_and_finmo" / "post_intake_initial_grid"
           / "runner.py").read_text(encoding="utf-8")
    self.assertIn("from client_intake_and_finmo.post_intake_amalgamated.tools.set_capex_rd_balance_seed", src)
    self.assertIn("from client_intake_and_finmo.post_intake_amalgamated.tools.set_stage_ramp_contract", src)
    self.assertIn("from client_intake_and_finmo.post_intake_amalgamated.tools.set_payroll_schedule", src)
    # The replaced _execute_sequence_step authoring calls are gone:
    self.assertNotIn(
      'r_and_d_applicability_decision = _execute_sequence_step(\n      "r_and_d_applicability",',
      src,
    )
    self.assertNotIn(
      'balance_sheet_contextual_seed_decision = _execute_sequence_step(\n      "balance_sheet_contextual_seed",',
      src,
    )
    self.assertNotIn(
      'stage_ramp_contract = _execute_sequence_step(\n    "stage_ramp_contract",',
      src,
    )
    self.assertNotIn(
      'schedule_payload = _execute_sequence_step(\n      "payroll_gpt_contract_request",',
      src,
    )


if __name__ == "__main__":
  unittest.main()
