"""P3.41 NexGen E2E iter 11 — regression tests for the round-1
payroll-stub decoupling (option 3).

Background: estimate_payroll_headcount_schedule_with_gpt (the legacy
shim at post_intake_headcount/schedule.py:2156) asserts a
PostIntakeSequenceController context before returning the pending
payroll stub. The amalgamated round-1 entry
``set_payroll_schedule(contract=None)`` was calling the shim directly
and tripping the gate (NexGen iter 11).

Fix: extracted the post-gate build-and-stamp body into a shared
ungated helper ``build_pending_payroll_stub`` in
post_intake_headcount/lookup.py. The shim still gates (preserves
the contract for its legacy controller callers); the canonical
amalgamated entry calls the helper directly without going through
the gate. Single source for the stub shape + metadata.

Note on the metadata stamps: the original shim used .setdefault()
for ``decision_source`` / ``contract_version`` / ``python_proposal_
diagnostic``. ``build_empty_payroll_headcount_payload`` already
sets ``decision_source`` and ``contract_version`` to OTHER values
("payroll_headcount_schedule.payroll_headcount_grid" / "payroll_
headcount_schedule_v1"), so the setdefaults were no-ops in the
original code. The helper preserves that behavior exactly (faithful
single-source extraction). The only stamp that actually lands is
``python_proposal_diagnostic`` (the empty payload doesn't carry it).
A latent semantics bug -- noted but NOT fixed in this commit
(scope-controlled extraction).
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


# ---------------------------------------------------------------------------
# Helper produces a structurally-valid stub without any gate
# ---------------------------------------------------------------------------

class BuildPendingPayrollStubTest(unittest.TestCase):

  def test_helper_runs_without_sequence_controller_context(self) -> None:
    """The helper must be callable without any PostIntakeSequence-
    Controller context active -- it's the WHOLE point of the fix.
    Pre-fix the only way to get this stub was through the gated shim."""
    from client_intake_and_finmo.post_intake_headcount.lookup import (
      build_pending_payroll_stub,
    )
    stub = build_pending_payroll_stub(draft_id="d1", client_id="c1")
    self.assertIsInstance(stub, dict)
    self.assertIn("draft_id", stub)
    self.assertEqual(stub["draft_id"], "d1")
    self.assertEqual(stub["client_id"], "c1")

  def test_helper_threads_previous_contract_failure_metadata(self) -> None:
    """python_proposal_diagnostic.previous_contract_failure is the
    transitional-shim signal; the helper must thread it through."""
    from client_intake_and_finmo.post_intake_headcount.lookup import (
      build_pending_payroll_stub,
    )
    failure = {"code": "test_failure", "message": "smoke"}
    stub = build_pending_payroll_stub(
      draft_id="d1", client_id="c1",
      previous_contract_failure=failure,
    )
    diag = stub.get("python_proposal_diagnostic")
    self.assertIsInstance(diag, dict)
    self.assertEqual(diag.get("previous_contract_failure"), failure)
    self.assertIn("transition_note", diag)

  def test_helper_carries_horizon_quarter_totals_and_empty_rows(self) -> None:
    """Structural sanity: the stub carries the 20-quarter totals and
    empty rows -- the shape downstream consumers expect of a 'pending
    amalgamated session' payload."""
    from client_intake_and_finmo.post_intake_headcount.lookup import (
      build_pending_payroll_stub,
    )
    stub = build_pending_payroll_stub(draft_id="d1", client_id="c1")
    self.assertIsInstance(stub.get("rows"), list)
    self.assertEqual(stub.get("rows"), [])
    self.assertIsInstance(stub.get("quarter_totals"), list)
    self.assertEqual(len(stub["quarter_totals"]), stub["schedule_horizon_quarters"])


# ---------------------------------------------------------------------------
# Canonical amalgamated entry: set_payroll_schedule(contract=None)
# now produces a stub without tripping the legacy gate
# ---------------------------------------------------------------------------

class SetPayrollScheduleRound1UngatedTest(unittest.TestCase):

  def test_round1_authoring_accepted_without_sequence_controller(self) -> None:
    """The iter-11 regression: set_payroll_schedule(contract=None)
    invoked OUTSIDE a PostIntakeSequenceController context must NOT
    raise post_intake_sequence_controller_required anymore."""
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_payroll_schedule import (
      set_payroll_schedule,
    )
    result = set_payroll_schedule(
      contract=None,
      draft_id="nexgen_iter11_test",
      planning_mode="normalize",
      planning_mode_reason="iter11_regression",
    )
    self.assertIsInstance(result, dict)
    violation_codes = {
      v.get("code") for v in (result.get("violations") or [])
      if isinstance(v, dict)
    }
    # The specific iter-11 violation code must NOT appear.
    self.assertNotIn("payroll_handler_c_authoring_failed", violation_codes)
    # No "post_intake_sequence_controller_required" appears in any
    # violation message either.
    for v in (result.get("violations") or []):
      msg = str((v or {}).get("message") or "")
      self.assertNotIn("post_intake_sequence_controller_required", msg)


# ---------------------------------------------------------------------------
# Gate preserved on the legacy shim for its legacy controller callers
# ---------------------------------------------------------------------------

class LegacyShimStillGatedTest(unittest.TestCase):

  def test_shim_still_raises_outside_controller(self) -> None:
    """estimate_payroll_headcount_schedule_with_gpt must still raise
    post_intake_sequence_controller_required when called directly
    (no controller context active). Removing the gate would change
    the contract for the legacy callers at schedule.py:2408 / :2540."""
    from client_intake_and_finmo.post_intake_headcount.schedule import (
      estimate_payroll_headcount_schedule_with_gpt,
    )
    with self.assertRaises(RuntimeError) as ctx:
      estimate_payroll_headcount_schedule_with_gpt(
        business_facts={},
        ops_json={},
        people_json={},
        financials_json={},
        financials_year1_json={},
        planning_mode="normalize",
        planning_mode_reason="gate_preservation_test",
        model_input_json={},
        finmo_json={},
        stage_ramp_contract={},
        draft_id="test",
        client_id="test",
      )
    self.assertIn("post_intake_sequence_controller_required", str(ctx.exception))


# ---------------------------------------------------------------------------
# Single-source parity: helper and shim produce identical stub
# ---------------------------------------------------------------------------

class HelperAndShimParityTest(unittest.TestCase):

  def test_helper_output_matches_shim_output_when_run_through_controller(
    self,
  ) -> None:
    """When the shim IS reached through a valid controller context,
    its output should be byte-identical to the helper called with the
    same draft_id/client_id -- proving the single-source extraction
    preserves behavior."""
    import contextvars
    from client_intake_and_finmo.post_intake_headcount.lookup import (
      build_pending_payroll_stub,
    )
    from client_intake_and_finmo.post_intake_headcount.schedule import (
      estimate_payroll_headcount_schedule_with_gpt,
    )
    from client_intake_and_finmo.post_intake_sequence import (
      _ACTIVE_SEQUENCE_CONTEXT,
    )
    # Push a fake controller context that satisfies the shim's gate.
    fake_context = {
      "step_key": "payroll_gpt_contract_request",
      "executor_function": "estimate_payroll_headcount_schedule_with_gpt",
    }
    token = _ACTIVE_SEQUENCE_CONTEXT.set((fake_context,))
    try:
      shim_output = estimate_payroll_headcount_schedule_with_gpt(
        business_facts={},
        ops_json={},
        people_json={},
        financials_json={},
        financials_year1_json={},
        planning_mode="normalize",
        planning_mode_reason="parity_test",
        model_input_json={},
        finmo_json={},
        stage_ramp_contract={},
        draft_id="parity_d1",
        client_id="parity_c1",
      )
    finally:
      _ACTIVE_SEQUENCE_CONTEXT.reset(token)
    helper_output = build_pending_payroll_stub(
      draft_id="parity_d1", client_id="parity_c1",
    )
    self.assertEqual(shim_output, helper_output,
                     "shim must produce the same stub as direct helper call")


if __name__ == "__main__":
  unittest.main()
