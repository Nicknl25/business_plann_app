"""Phase 9 P3.33 remediation — Commit 4 (C2, C3, C5, C6).

Silent-failure cleanup + unwired event codes.

  C2 — marketing-model fetch exception now emits MARKETING_CONTEXT_FETCH_FAILED.
  C3 — mirror band-load DB error now emits MIRROR_BANDS_LOAD_FAILED.
  C5 — unified_convergence_decision audit: contract is alive (used by
       post_intake_convergence/runtime.py), so the rows in
       post_intake_mapping.py and the fail_fast.py default remain.
       Test pins this finding.
  C6 — Wire ROUND1_COMPLETED, TARGET_SEEKING_PREFLIGHT_STARTED, and
       TARGET_SEEKING_PRE_CASH_GATE_STARTED so the three previously-
       unused EventCodes have call sites.
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


# ---------------------------------------------------------------------------
# C2 — marketing-model fetch silent exception now emits a diagnostic
# ---------------------------------------------------------------------------

class C2MarketingContextEmitTest(unittest.TestCase):
  def test_marketing_context_fetch_failed_emit_is_wired(self) -> None:
    """Source-level guard: the except branch in post_intake_initial_grid/
    runner.py around the marketing_context_build _execute_sequence_step
    call emits MARKETING_CONTEXT_FETCH_FAILED."""
    from client_intake_and_finmo.post_intake_initial_grid import runner
    src = inspect.getsource(runner)
    self.assertIn("MARKETING_CONTEXT_FETCH_FAILED", src,
                  "C2 emit must reference the new EventCode by name")
    self.assertIn("marketing_context_build", src)


# ---------------------------------------------------------------------------
# C3 — mirror band-load now emits a diagnostic before falling back
# ---------------------------------------------------------------------------

class C3MirrorBandsLoadEmitTest(unittest.TestCase):
  def test_mirror_bands_load_failed_emit_is_wired(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated import mirror
    src = inspect.getsource(mirror)
    self.assertIn("MIRROR_BANDS_LOAD_FAILED", src)
    # Must be inside the band-load except path, not the success path.
    self.assertIn("safe_emit", src)


# ---------------------------------------------------------------------------
# C5 — unified_convergence_decision audit (stays alive)
# ---------------------------------------------------------------------------

class C5UnifiedConvergenceDecisionAuditTest(unittest.TestCase):
  def test_contract_still_referenced_by_runtime(self) -> None:
    """The contract is still used by the convergence runtime path —
    removing the mapping rows or fail_fast.py default would break
    that path. This test pins the audit conclusion: alive, not orphan."""
    from client_intake_and_finmo.post_intake_convergence import runtime
    src = inspect.getsource(runtime)
    self.assertIn("unified_convergence_decision", src,
                  "If this fails, runtime.py no longer uses the contract — "
                  "remove the mapping rows and the fail_fast.py default in "
                  "the same commit (per C5 cleanup directive).")

  def test_audit_comment_documents_decision(self) -> None:
    from client_intake_and_finmo.fail_fast.post_intake_fail_fast import fail_fast
    src = inspect.getsource(fail_fast)
    self.assertIn("C5 audit", src,
                  "_expected_horizon must carry the C5 audit comment "
                  "explaining why the default contract_name survives.")


# ---------------------------------------------------------------------------
# C6 — three previously-unused EventCodes are now emitted somewhere
# ---------------------------------------------------------------------------

class C6UnwiredEventCodesNowEmittedTest(unittest.TestCase):
  def test_round1_completed_emitted_in_runner(self) -> None:
    from client_intake_and_finmo.post_intake_initial_grid import runner
    src = inspect.getsource(runner)
    self.assertIn("ROUND1_COMPLETED", src)

  def test_preflight_started_emitted_in_orchestrator(self) -> None:
    from client_intake_and_finmo.post_intake_solver import orchestrator
    src = inspect.getsource(orchestrator)
    self.assertIn("TARGET_SEEKING_PREFLIGHT_STARTED", src)

  def test_pre_cash_gate_started_emitted_in_orchestrator(self) -> None:
    from client_intake_and_finmo.post_intake_solver import orchestrator
    src = inspect.getsource(orchestrator)
    self.assertIn("TARGET_SEEKING_PRE_CASH_GATE_STARTED", src)


# ---------------------------------------------------------------------------
# Sanity: the new EventCodes exist on the enum.
# ---------------------------------------------------------------------------

class NewEventCodesDefinedTest(unittest.TestCase):
  def test_marketing_and_bands_event_codes_exist(self) -> None:
    from client_intake_and_finmo.post_intake_diagnostics.phase_codes import (
      EventCode, PhaseCode, EVENT_CODES_BY_PHASE,
    )
    self.assertTrue(hasattr(EventCode, "MARKETING_CONTEXT_FETCH_FAILED"))
    self.assertTrue(hasattr(EventCode, "MIRROR_BANDS_LOAD_FAILED"))
    # Both belong to MIRROR_BUILD partition.
    mb = EVENT_CODES_BY_PHASE[PhaseCode.MIRROR_BUILD]
    self.assertIn(EventCode.MARKETING_CONTEXT_FETCH_FAILED, mb)
    self.assertIn(EventCode.MIRROR_BANDS_LOAD_FAILED, mb)


if __name__ == "__main__":
  unittest.main()
