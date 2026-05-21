"""Phase 9 P3.26 Commit 2 — payroll feasibility routes to Handler C.

Verifies R-1 through R-6 from the directive:

R-1: Both payroll feasibility fire sites are wrapped — Site A
     (initial-grid quarter_grid_global_validation) and Site B
     (orchestrator finalize global invariants).

R-2: Each site routes to Handler C BEFORE the hard-fail is raised.
     `route_payroll_feasibility_to_handler_c` invokes
     `estimate_payroll_headcount_schedule_with_gpt` with the
     failure context as `previous_contract_failure` feedback.

R-3: Bounded retry — Handler C's existing 10-round internal
     iteration IS the retry mechanism. One external invocation
     per site (single-shot at the site level; no cycling).

R-4: P3.20 Part 3 doctrine applied:
       Stage 1 — never revert: repaired schedule persists into
         downstream state (model_input + finmo + payroll_headcount
         local var + DB column for Site B).
       Stage 2 — any-validator trigger: `is_payroll_feasibility_failure`
         matches the two direct codes AND the wrapping
         `post_intake_schedule_marker_missing` carrying the inner.
       Stage 3 — Mirror Flavor 1: `apply_payroll_schedule_to_state`
         calls the existing apply chain which keeps all four
         payroll surfaces aligned. The existing assertions enforce.
       Stage 3b — full payload: `previous_contract_failure` carries
         the full FailFastError context (code, message, stage,
         details).
       Stage 4 — diagnostic preservation: if Handler C can't
         resolve, the post-repair re-check raises the canonical
         FailFastError with the same diagnostic chain.

R-5: `assert_finmo_payroll_matches_headcount_schedule` fires
     inside `apply_payroll_schedule_to_state` (called via the
     apply chain), enforcing Mirror Flavor 1 alignment after
     each routed repair.

R-6: GPT exhaustion handler's writable_lever_catalog is NOT
     modified by this commit. Handler C remains the canonical
     writer for payroll dollars.

These tests verify the public-API contract of the new helper
module and the wiring presence at the two call sites. Live
integration is verified by the directive's mandatory three-draft
re-run after commit lands.
"""

from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Dict


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


class TestHelperModuleSurface(unittest.TestCase):
  """The helper module exposes exactly the entry points the
  call-site wiring imports. The function signatures are stable;
  changes here trigger downstream wiring updates."""

  def test_helper_module_imports_clean(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.feasibility_repair import (  # noqa: WPS433
      apply_payroll_schedule_to_state,
      is_payroll_feasibility_failure,
      route_payroll_feasibility_to_handler_c,
    )
    self.assertTrue(callable(apply_payroll_schedule_to_state))
    self.assertTrue(callable(is_payroll_feasibility_failure))
    self.assertTrue(callable(route_payroll_feasibility_to_handler_c))

  def test_helper_module_does_not_import_orchestrator(self) -> None:
    """The helper must not depend on the orchestrator; circular
    imports break the call-site wiring. Direct doctrine reason:
    the helper is a leaf utility usable from any pipeline stage."""
    feasibility_repair_path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo", "post_intake_headcount",
      "feasibility_repair.py",
    )
    with open(feasibility_repair_path, "r", encoding="utf-8") as fh:
      source = fh.read()
    self.assertNotIn("post_intake_solver.orchestrator", source)
    self.assertNotIn("post_intake_initial_grid.runner", source)


class TestIsPayrollFeasibilityFailureRecognition(unittest.TestCase):
  """R-2 — trigger recognition. Mirrors the canonical
  `is_payroll_feasibility_failure` predicate behavior."""

  def _make_fail_fast_error(
    self, *, code: str, message: str = "", stage: str = "",
    details: Dict[str, Any] = None,
  ):
    from client_intake_and_finmo.fail_fast.common import FailFastError  # noqa: WPS433
    return FailFastError(
      code, message or code, stage=stage, details=details or {},
    )

  def test_revenue_economic_code_recognized(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.feasibility_repair import (  # noqa: WPS433
      is_payroll_feasibility_failure,
    )
    exc = self._make_fail_fast_error(code="payroll_revenue_economic_feasibility_failed")
    self.assertTrue(is_payroll_feasibility_failure(exc))

  def test_stage_profitability_code_recognized(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.feasibility_repair import (  # noqa: WPS433
      is_payroll_feasibility_failure,
    )
    exc = self._make_fail_fast_error(code="payroll_stage_profitability_feasibility_failed")
    self.assertTrue(is_payroll_feasibility_failure(exc))

  def test_wrapping_marker_code_unwrapped_when_inner_matches(self) -> None:
    """The initial-grid global invariants check wraps the inner
    feasibility code inside `post_intake_schedule_marker_missing`
    with the inner code in `details.exception`. The predicate
    must unwrap and route."""
    from client_intake_and_finmo.post_intake_headcount.feasibility_repair import (  # noqa: WPS433
      is_payroll_feasibility_failure,
    )
    exc = self._make_fail_fast_error(
      code="post_intake_schedule_marker_missing",
      details={
        "exception": (
          "POST_INTAKE:payroll_revenue_economic_feasibility_failed@"
          "quarter_grid_applied_global_payroll_revenue_feasibility: "
          "Payroll/revenue economics are outside the table-backed "
          "headcount policy range; recompute drivers instead of "
          "clipping outputs."
        ),
      },
    )
    self.assertTrue(is_payroll_feasibility_failure(exc))

  def test_wrapping_marker_without_inner_payroll_not_routed(self) -> None:
    """`post_intake_schedule_marker_missing` with a non-payroll
    inner code stays hard-failed."""
    from client_intake_and_finmo.post_intake_headcount.feasibility_repair import (  # noqa: WPS433
      is_payroll_feasibility_failure,
    )
    exc = self._make_fail_fast_error(
      code="post_intake_schedule_marker_missing",
      details={"exception": "POST_INTAKE:something_else_failed@x: details"},
    )
    self.assertFalse(is_payroll_feasibility_failure(exc))

  def test_unrelated_failure_codes_skip_route(self) -> None:
    """Doctrine §1 hard-fail: non-payroll-feasibility failures
    must NOT route to Handler C; routing them would silently
    absorb unrelated diagnostics."""
    from client_intake_and_finmo.post_intake_headcount.feasibility_repair import (  # noqa: WPS433
      is_payroll_feasibility_failure,
    )
    for code in (
      "revenue_formula_reconciliation_failed",
      "balance_sheet_reconciliation_failed",
      "payroll_finmo_rebuild_validation_failed",
      "payroll_headcount_contract_timeout",
      "payroll_tool_calling_session_exhausted",
    ):
      exc = self._make_fail_fast_error(code=code)
      self.assertFalse(
        is_payroll_feasibility_failure(exc),
        msg=f"code {code!r} should NOT route to Handler C",
      )

  def test_non_payroll_runtime_errors_skip_route(self) -> None:
    """A RuntimeError that does NOT carry the payroll feasibility
    code in its message must NOT route."""
    from client_intake_and_finmo.post_intake_headcount.feasibility_repair import (  # noqa: WPS433
      is_payroll_feasibility_failure,
    )
    self.assertFalse(is_payroll_feasibility_failure(RuntimeError("generic error")))
    self.assertFalse(is_payroll_feasibility_failure(ValueError("not a fail fast")))
    self.assertFalse(is_payroll_feasibility_failure(
      RuntimeError("post_intake_finalize_validation_failed: balance_sheet_reconciliation_invalid"),
    ))

  def test_runtime_error_wrap_with_inner_payroll_code_recognized(self) -> None:
    """P3.26 fix1: finalize wraps FailFastError in RuntimeError via
    _raise_if_errors at finalize_post_intake.py:41. The predicate
    must detect the inner feasibility code in the concatenated
    message string — this is Site B's actual failure shape."""
    from client_intake_and_finmo.post_intake_headcount.feasibility_repair import (  # noqa: WPS433
      is_payroll_feasibility_failure,
    )
    # Exact text shape from Anderson & Blake's P3.26 verification run.
    msg = (
      "post_intake_finalize_validation_failed: global_invariants_invalid: "
      "POST_INTAKE:post_intake_schedule_marker_missing@post_intake_finalize_validation_global: "
      "Payroll schedule fail-fast failed; payroll must use the table-backed headcount schedule: "
      "POST_INTAKE:payroll_revenue_economic_feasibility_failed@"
      "post_intake_finalize_validation_global_global_payroll_revenue_feasibility: "
      "Payroll/revenue economics are outside the table-backed headcount policy range; "
      "recompute drivers instead of clipping outputs."
    )
    self.assertTrue(is_payroll_feasibility_failure(RuntimeError(msg)))


class TestSiteAWiring(unittest.TestCase):
  """R-1 + R-2 source-shape verification for Site A
  (initial-grid runner)."""

  def setUp(self) -> None:
    self._src = open(
      os.path.join(
        PYTHON_ROOT, "client_intake_and_finmo", "post_intake_initial_grid", "runner.py",
      ),
      "r", encoding="utf-8",
    ).read()

  def test_site_a_imports_helper(self) -> None:
    self.assertIn("from client_intake_and_finmo.post_intake_headcount.feasibility_repair import", self._src)
    self.assertIn("route_payroll_feasibility_to_handler_c", self._src)
    self.assertIn("is_payroll_feasibility_failure", self._src)

  def test_site_a_invokes_handler_c_route(self) -> None:
    """Direct invocation of the helper at Site A."""
    self.assertIn(
      "route_payroll_feasibility_to_handler_c(",
      self._src,
    )

  def test_site_a_re_runs_global_check_after_repair(self) -> None:
    """Doctrine §3 Stage 4 — diagnostic preservation. After the
    repair, the same global invariants check re-runs with the
    new state. If it still fails, the canonical FailFastError
    propagates with the full chain."""
    self.assertIn(
      "quarter_grid_applied_after_feasibility_repair",
      self._src,
    )

  def test_site_a_updates_local_state_after_repair(self) -> None:
    """R-4 Stage 1 (never revert). Repaired schedule persists
    into the local payroll_headcount_payload + applied_model_input_json
    + applied_finmo_json variables that propagate to Phase B."""
    self.assertIn(
      "payroll_headcount_payload, applied_model_input_json, applied_finmo_json = (",
      self._src,
    )


class TestSiteBWiring(unittest.TestCase):
  """R-1 + R-2 source-shape verification for Site B (orchestrator
  finalize)."""

  def setUp(self) -> None:
    self._src = open(
      os.path.join(
        PYTHON_ROOT, "client_intake_and_finmo", "post_intake_solver", "orchestrator.py",
      ),
      "r", encoding="utf-8",
    ).read()

  def test_site_b_imports_helper(self) -> None:
    self.assertIn(
      "from client_intake_and_finmo.post_intake_headcount.feasibility_repair import",
      self._src,
    )
    self.assertIn("route_payroll_feasibility_to_handler_c", self._src)
    self.assertIn("is_payroll_feasibility_failure", self._src)

  def test_site_b_routes_on_payroll_feasibility_failure(self) -> None:
    """Site B's except branch checks `is_payroll_feasibility_failure(exc)`
    before routing — non-feasibility exceptions stay hard-failed."""
    self.assertIn("is_payroll_feasibility_failure(exc)", self._src)

  def test_site_b_persists_payroll_headcount_to_db(self) -> None:
    """R-4 Stage 1 (never revert) + Mirror Flavor 1: the
    orchestrator's normal persist does NOT write
    payroll_headcount. After routed repair, a direct SQL UPDATE
    keeps the DB column aligned with the repaired in-memory
    state. Without this, the workbook builder would render from
    stale headcount values, recreating the P3.25 divergence."""
    self.assertIn(
      "UPDATE intake_consult_drafts SET payroll_headcount=%s WHERE draft_id=%s",
      self._src,
    )

  def test_site_b_re_runs_finalize_after_repair(self) -> None:
    """Doctrine §3 Stage 4 — diagnostic preservation. After
    repair, finalize re-runs with the repaired state. If it
    still fails, the canonical FailFastError propagates."""
    # The except branch imports run_finalize_post_intake_validation
    # again (aliased as _finalize_post_repair) to re-run with the
    # repaired state.
    self.assertIn(
      "run_finalize_post_intake_validation as _finalize_post_repair",
      self._src,
      msg="Site B should re-run finalize after a repair attempt.",
    )
    self.assertIn(
      "finalize_result = _finalize_post_repair(",
      self._src,
      msg="The re-run call must use the aliased import.",
    )


class TestDoctrineR6HandlerLeverSetUnchanged(unittest.TestCase):
  """R-6 verification: GPT exhaustion handler lever set.

  Original P3.26 Commit 2 doctrine: the writable_lever_catalog is
  NOT modified by that commit. The pre-existing inclusion of
  expenses::Payroll was documented in the P3.25 memo as a separate
  doctrine concern; P3.26 did not address it.

  Phase 9 P3.32 K1 (F1+F2) doctrine evolution (L-3 latitude):
  expenses::Payroll IS now removed from the set. Handler C is
  canonical Payroll writer; the exhaustion handler must not have
  latent authority over Payroll because that authority was the
  vector for the P3.25 CareFirst and P3.32 Caring Hands Mirror
  Flavor 1 divergences (latent FALSE_PASS surfaced by P3.32's
  V-4 verifier).

  This test now pins the POST-K1 set as the authoritative
  invariant. Any future addition of Payroll back to this set must
  be a deliberate doctrine reversion, not an accidental
  re-inclusion."""

  def test_handler_pnl_lever_set_unchanged(self) -> None:
    """Phase 9 P3.32 K1: Payroll removed from the canonical set.
    Other 7 PNL drivers preserved."""
    from client_intake_and_finmo.post_intake_target_solver.restoration_loop import (  # noqa: WPS433
      _GPT_AUTHORED_PNL_LEVER_IDS,
    )
    expected_pnl_set = frozenset({
      "revenue::Unit Price",
      "revenue::Capacity",
      "revenue::Utilization",
      "expenses::Cost of Goods Sold",
      "expenses::Marketing",
      "expenses::General & Administrative",
      "expenses::Research & Development",
    })
    self.assertEqual(_GPT_AUTHORED_PNL_LEVER_IDS, expected_pnl_set)
    self.assertNotIn(
      "expenses::Payroll", _GPT_AUTHORED_PNL_LEVER_IDS,
      msg=(
        "Phase 9 P3.32 K1 doctrine: expenses::Payroll MUST NOT be "
        "in the exhaustion handler's PNL lever set. Handler C "
        "(post_intake_headcount.schedule) is the canonical Payroll "
        "writer. Re-adding payroll here re-introduces Leak A "
        "(P3.31 audit) and re-opens the P3.25 CareFirst / P3.32 "
        "Caring Hands Mirror Flavor 1 divergence vector."
      ),
    )

  def test_handler_wc_lever_set_unchanged(self) -> None:
    """The set of GPT-authored working-capital lever IDs in the
    restoration handler's authority is preserved verbatim."""
    from client_intake_and_finmo.post_intake_target_solver.restoration_loop import (  # noqa: WPS433
      _GPT_AUTHORED_WC_LEVER_IDS,
    )
    expected_wc_set = frozenset({
      "balance_sheet::Accounts Receivable Days",
      "balance_sheet::Accounts Payable Days",
      "balance_sheet::Inventory Days",
      "balance_sheet::Deferred Revenue (% of Revenue)",
      "balance_sheet::Prepaid Expenses (% of Revenue)",
    })
    self.assertEqual(_GPT_AUTHORED_WC_LEVER_IDS, expected_wc_set)


class TestPreviousContractFailurePayloadShape(unittest.TestCase):
  """R-4 Stage 3b: full failure payload passed to Handler C.
  The previous_contract_failure dict must carry error, error_code,
  stage, details — the same fields the iterative refinement loop
  consumes as Round 1's external_caller_seed feedback packet
  (see schedule.py:2397-2404)."""

  def test_payload_includes_required_fields(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.feasibility_repair import (  # noqa: WPS433
      _previous_contract_failure_payload,
    )
    payload = _previous_contract_failure_payload(
      error_code="payroll_revenue_economic_feasibility_failed",
      message="Payroll/revenue economics are outside the table-backed headcount policy range.",
      stage="quarter_grid_applied_global_payroll_revenue_feasibility",
      details={"violation_count": 5, "violations": [{"q": 1, "ratio": 0.8}]},
      source="payroll_feasibility_repair",
    )
    self.assertEqual(payload["error_code"], "payroll_revenue_economic_feasibility_failed")
    self.assertIn("Payroll/revenue economics", payload["error"])
    self.assertEqual(
      payload["stage"],
      "quarter_grid_applied_global_payroll_revenue_feasibility",
    )
    self.assertEqual(payload["details"]["violation_count"], 5)
    self.assertEqual(payload["source"], "payroll_feasibility_repair")


if __name__ == "__main__":
  unittest.main()
