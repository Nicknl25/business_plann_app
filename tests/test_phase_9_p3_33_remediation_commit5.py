"""Phase 9 P3.33 remediation — Commit 5 (C4).

Orphan sweep audit of three convergence helpers:

  - post_intake_convergence/runtime.py::_build_current_cycle_convergence_packet
  - post_intake_contracts/runner.py::_build_retry_scope_payload
  - post_intake_contracts/runner.py::_subset_numeric_solver_contract

Audit outcome: ALL THREE are alive in the new pipeline. Call chain:

  api_handlers.intake_consult._run_planning_system_for_draft_unified
    -> orchestrator.run_target_seeking_orchestrated_system_run
       -> _run_post_cascade_completion
          -> _persist_unified_convergence_state (DI-bound seam)
             -> state.runner._persist_unified_convergence_state
                -> _persist_post_intake_stage_state
                   -> contracts.runner._build_repair_guidance_payload
                      -> _build_current_cycle_convergence_packet
                      -> _build_retry_scope_payload
                      -> _subset_numeric_solver_contract

No code deletion. This commit adds a documentation comment to each
helper explaining why it survived the Phase 3 step 7 orphan sweep
and pinning the call chain as a regression check.
"""

from __future__ import annotations

import inspect
import os
import sys
import unittest

HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


class HelperCallChainAuditTest(unittest.TestCase):
  """The three convergence helpers must each carry a 'C4 audit'
  comment near their def so the live-call-chain rationale is
  preserved as a comment block. Future cleanup commits MUST update
  these comments if the call chain changes."""

  def test_build_current_cycle_convergence_packet_documents_chain(self) -> None:
    from client_intake_and_finmo.post_intake_convergence import runtime
    src = inspect.getsource(runtime._build_current_cycle_convergence_packet)
    self.assertIn("C4 audit", src)
    # Loose check — the comment names the upstream orchestrator entry
    # (line-wrapped in the source, so check the prefix only).
    self.assertIn("run_target_seeking_", src)

  def test_build_retry_scope_payload_documents_chain(self) -> None:
    from client_intake_and_finmo.post_intake_contracts import runner
    src = inspect.getsource(runner._build_retry_scope_payload)
    self.assertIn("C4 audit", src)

  def test_subset_numeric_solver_contract_documents_chain(self) -> None:
    from client_intake_and_finmo.post_intake_contracts import runner
    src = inspect.getsource(runner._subset_numeric_solver_contract)
    self.assertIn("C4 audit", src)


class HelperLiveCallSitesStillExistTest(unittest.TestCase):
  """Regression: if a future commit drops _build_repair_guidance_payload
  or _persist_unified_convergence_state without also dropping the
  helpers, this test fires so the call-chain documentation can be
  refreshed (or the helpers deleted)."""

  def test_build_repair_guidance_payload_still_calls_helpers(self) -> None:
    from client_intake_and_finmo.post_intake_contracts import runner
    src = inspect.getsource(runner._build_repair_guidance_payload)
    self.assertIn("_build_current_cycle_convergence_packet", src)
    self.assertIn("_build_retry_scope_payload", src)
    self.assertIn("_subset_numeric_solver_contract", src)

  def test_state_runner_still_calls_repair_guidance(self) -> None:
    from client_intake_and_finmo.post_intake_state import runner
    src = inspect.getsource(runner._persist_post_intake_stage_state)
    self.assertIn("_build_repair_guidance_payload", src)

  def test_orchestrator_still_invokes_persist(self) -> None:
    from client_intake_and_finmo.post_intake_solver import orchestrator
    src = inspect.getsource(orchestrator)
    self.assertIn("_persist_unified_convergence_state", src)


if __name__ == "__main__":
  unittest.main()
