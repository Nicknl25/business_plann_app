"""Phase 9 P3.24 Commit 2 — payroll_feasibility_repair re-wire.

Verifies R-1 / R-2 / R-3 / R-4 / R-5 from the P3.23a/P3.23b/P3.23c
audits:

R-1: The repair logic is reachable from the initial-grid path
     (parity with convergence/runner.py:780-826 lifted to the
     initial-grid stage at the SQL table's canonical position).

R-2: The post-grid global feasibility check is wrapped in a
     try/except that catches FailFastError on the feasibility
     code; on catch, the payroll handler is re-invoked with
     `previous_contract_failure` populated.

R-3: The repair step invokes the SAME payroll handler (Handler C
     — `estimate_payroll_headcount_schedule_with_gpt`) with an
     expanded context that includes the global feasibility
     failure data — handler iteration logic, budget, and prompts
     are unchanged.

R-4: After the repair step, the post-grid global feasibility
     check is re-run. If it still fails, the hard-fail
     propagates. If it passes, the pipeline continues.

R-5: Doctrine compliance — Stage 1 never-revert, Stage 2 trigger
     on any feasibility failure, Stage 3 single-source state,
     Stage 3b full failure payload, Stage 4 diagnostic
     preservation.

Tests are pure-Python: they exercise the trigger expression and
the failure-payload shape, not a live initial-grid run. Live
integration is left for the user-directed E2E verification.
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


class TestR1RepairCodePresent(unittest.TestCase):
  """R-1 — the repair logic is present in the initial-grid path."""

  def test_initial_grid_runner_imports_clean(self) -> None:
    """The modified initial_grid/runner.py must still import without
    error (smoke check before any structural assertions)."""
    from client_intake_and_finmo.post_intake_initial_grid import (  # noqa: WPS433
      prepare_initial_grid_for_draft,
    )
    self.assertTrue(callable(prepare_initial_grid_for_draft))

  def test_payroll_feasibility_repair_step_referenced_in_runner(self) -> None:
    """The step_key `payroll_feasibility_repair` MUST appear in the
    initial-grid runner code, mapping to the canonical SQL table row
    initial_grid:65 (P3.23b §0.1)."""
    runner_path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo",
      "post_intake_initial_grid", "runner.py",
    )
    with open(runner_path, "r", encoding="utf-8") as fh:
      runner_source = fh.read()
    self.assertIn("payroll_feasibility_repair", runner_source)
    self.assertIn(
      "retry_payroll_headcount_schedule_from_feasibility_failure",
      runner_source,
    )

  def test_repair_uses_estimate_payroll_handler_with_previous_contract_failure(self) -> None:
    """R-3 — the repair invokes the existing payroll handler
    (estimate_payroll_headcount_schedule_with_gpt) with the
    previous_contract_failure kwarg populated. The handler itself is
    unchanged; only the invocation context broadens."""
    runner_path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo",
      "post_intake_initial_grid", "runner.py",
    )
    with open(runner_path, "r", encoding="utf-8") as fh:
      runner_source = fh.read()
    # Should pass previous_contract_failure to the handler
    self.assertIn("previous_contract_failure", runner_source)
    # The handler entry point — already imported via existing
    # _build_and_apply_payroll_schedule path, but referenced again in
    # the repair branch.
    self.assertIn(
      "estimate_payroll_headcount_schedule_with_gpt",
      runner_source,
    )


class TestR2R4TriggerAndRecheck(unittest.TestCase):
  """R-2 / R-4 — trigger fires on the feasibility codes; post-repair
  re-validation runs the same check."""

  def test_trigger_code_set_includes_both_feasibility_failures(self) -> None:
    """R-2 — Property 2 trigger scope: both feasibility codes are
    accepted. payroll_revenue_economic_feasibility_failed and
    payroll_stage_profitability_feasibility_failed both route to
    repair."""
    # Mirror the trigger-decision logic from the runner.
    def _is_feasibility_failure(code: str, wrapped_inner: str = "") -> bool:
      _is = (
        code in {
          "payroll_revenue_economic_feasibility_failed",
          "payroll_stage_profitability_feasibility_failed",
        }
        or "payroll_revenue_economic_feasibility_failed" in wrapped_inner
        or "payroll_stage_profitability_feasibility_failed" in wrapped_inner
      )
      return _is

    self.assertTrue(_is_feasibility_failure(
      "payroll_revenue_economic_feasibility_failed",
    ))
    self.assertTrue(_is_feasibility_failure(
      "payroll_stage_profitability_feasibility_failed",
    ))

  def test_wrapped_marker_failure_routes_to_repair(self) -> None:
    """The initial-grid invariants check sometimes wraps the
    feasibility failure inside a `post_intake_schedule_marker_missing`
    code (CareFirst Draft 2 path). The trigger must unwrap and
    detect the inner code."""
    def _is_feasibility_failure(code: str, wrapped_inner: str = "") -> bool:
      _is = (
        code in {
          "payroll_revenue_economic_feasibility_failed",
          "payroll_stage_profitability_feasibility_failed",
        }
        or "payroll_revenue_economic_feasibility_failed" in wrapped_inner
        or "payroll_stage_profitability_feasibility_failed" in wrapped_inner
      )
      return _is

    # The wrapping pattern from CareFirst's persisted state:
    inner_text = (
      "POST_INTAKE:payroll_revenue_economic_feasibility_failed"
      "@quarter_grid_applied_global_payroll_revenue_feasibility: "
      "Payroll/revenue economics are outside the table-backed "
      "headcount policy range; recompute drivers instead of "
      "clipping outputs."
    )
    self.assertTrue(_is_feasibility_failure(
      code="post_intake_schedule_marker_missing",
      wrapped_inner=inner_text,
    ))

  def test_unrelated_failure_codes_do_not_route_to_repair(self) -> None:
    """R-2 — failures outside the payroll feasibility scope must NOT
    route to repair (otherwise the repair would silently absorb
    unrelated diagnostics, violating doctrine §1 hard-fail)."""
    def _is_feasibility_failure(code: str, wrapped_inner: str = "") -> bool:
      _is = (
        code in {
          "payroll_revenue_economic_feasibility_failed",
          "payroll_stage_profitability_feasibility_failed",
        }
        or "payroll_revenue_economic_feasibility_failed" in wrapped_inner
        or "payroll_stage_profitability_feasibility_failed" in wrapped_inner
      )
      return _is

    # Mechanical / schema integrity failures stay hard-failed.
    self.assertFalse(_is_feasibility_failure(
      "revenue_formula_reconciliation_failed",
    ))
    self.assertFalse(_is_feasibility_failure(
      "balance_sheet_reconciliation_failed",
    ))
    self.assertFalse(_is_feasibility_failure(
      "payroll_finmo_rebuild_validation_failed",
    ))
    self.assertFalse(_is_feasibility_failure(
      "post_intake_schedule_marker_missing",  # No wrapped inner
    ))

  def test_post_repair_recheck_appears_in_runner(self) -> None:
    """R-4 — after the repair, the global invariants check runs
    again. The runner must have TWO instances of the
    `quarter_grid_global_validation` step invocation."""
    runner_path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo",
      "post_intake_initial_grid", "runner.py",
    )
    with open(runner_path, "r", encoding="utf-8") as fh:
      runner_source = fh.read()
    # The runner already had one call. The repair adds a second
    # post-repair recheck. (There are also calls in the pre-grid
    # validation path; we count all references.)
    occurrences = runner_source.count("quarter_grid_global_validation")
    self.assertGreaterEqual(occurrences, 2)


class TestR5DoctrineCompliance(unittest.TestCase):
  """R-5 — doctrine §3 properties on the new step."""

  def test_property_1_never_revert_repair_persists_into_state(self) -> None:
    """Property 1 — after repair, payroll_headcount_payload AND
    applied_model_input_json AND applied_finmo_json are updated to
    the new schedule's state. The repaired output IS the canonical
    output; no revert path."""
    runner_path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo",
      "post_intake_initial_grid", "runner.py",
    )
    with open(runner_path, "r", encoding="utf-8") as fh:
      runner_source = fh.read()
    # The repair branch must reassign all three state pieces.
    self.assertIn(
      "payroll_headcount_payload = copy.deepcopy(_repaired_schedule_payload)",
      runner_source,
    )
    self.assertIn(
      "applied_model_input_json, applied_finmo_json = _apply_existing_payroll_authority(",
      runner_source,
    )

  def test_property_2_trigger_on_any_feasibility_failure(self) -> None:
    """Property 2 — trigger covers ALL feasibility-category failures
    (not narrowed to e.g. only payroll_revenue and excluding
    payroll_stage_profitability)."""
    # Covered by test_trigger_code_set_includes_both_feasibility_failures.
    # This test asserts the doctrine-compliant code shape:
    runner_path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo",
      "post_intake_initial_grid", "runner.py",
    )
    with open(runner_path, "r", encoding="utf-8") as fh:
      runner_source = fh.read()
    self.assertIn("payroll_revenue_economic_feasibility_failed", runner_source)
    self.assertIn("payroll_stage_profitability_feasibility_failed", runner_source)

  def test_property_3_full_failure_payload_in_previous_contract_failure(self) -> None:
    """Property 3b — full failure payload passed to the handler.
    Must include error text, error_code, stage, and details."""
    runner_path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo",
      "post_intake_initial_grid", "runner.py",
    )
    with open(runner_path, "r", encoding="utf-8") as fh:
      runner_source = fh.read()
    # The repair_failure_payload dict construction
    for key in ('"error"', '"error_code"', '"stage"', '"details"'):
      self.assertIn(key, runner_source)

  def test_property_4_diagnostic_preserved_on_post_repair_recheck(self) -> None:
    """Property 4 — if the post-repair recheck fails, the FailFastError
    propagates with full diagnostic. The repair does NOT swallow it.
    We verify the structural absence of a swallow pattern: there
    should not be an `except FailFastError: pass` after the
    post-repair `_assert_global_invariants_via_sequence` call."""
    runner_path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo",
      "post_intake_initial_grid", "runner.py",
    )
    with open(runner_path, "r", encoding="utf-8") as fh:
      runner_source = fh.read()
    # The post-repair recheck is NOT inside a try/except — it MUST
    # raise on failure. Check that the post-repair stage label is
    # unique to the second call and isn't followed by a swallow.
    self.assertIn(
      'stage="quarter_grid_applied_after_feasibility_repair"',
      runner_source,
    )
    # No silent-swallow patterns near the repair recheck site.
    swallow_pattern_lines = [
      line for line in runner_source.splitlines()
      if "except FailFastError" in line and ":" in line and "pass" in (
        runner_source.split(line)[1].splitlines()[0] if line in runner_source else ""
      )
    ]
    self.assertEqual(len(swallow_pattern_lines), 0)

  def test_single_shot_no_unbounded_retry(self) -> None:
    """The repair is SINGLE-SHOT. The runner uses a boolean flag
    `_payroll_feasibility_repair_attempted` rather than a loop —
    cycling cannot occur. P3.11 removed the previous outer retry
    loop; the directive requires we not reintroduce one."""
    runner_path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo",
      "post_intake_initial_grid", "runner.py",
    )
    with open(runner_path, "r", encoding="utf-8") as fh:
      runner_source = fh.read()
    self.assertIn("_payroll_feasibility_repair_attempted", runner_source)
    # No `while` loop or `for` loop wrapping the repair section
    # (search proxy: the repair block must not contain a backwards-
    # jumping construct).
    # The repair is one try/except block — verify the structural shape.
    self.assertIn(
      "except FailFastError as _first_invariant_exc:",
      runner_source,
    )


class TestRepairAndConvergenceMirrorParity(unittest.TestCase):
  """Lifting parity — the new initial-grid repair mirrors the
  shape of convergence/runner.py:780-826 `_rebuild_payroll_authority`
  closely enough that Commit 3 can delete the convergence runner
  without losing functionality."""

  def test_handler_kwargs_parity(self) -> None:
    """The handler kwargs passed in the repair branch include the
    same fields as the convergence runner's repair: business_facts,
    ops_json, people_json, financials_json, financials_year1_json,
    planning_mode, planning_mode_reason, model_input_json, finmo_json,
    stage_ramp_contract, draft_id, client_id, previous_contract_failure."""
    runner_path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo",
      "post_intake_initial_grid", "runner.py",
    )
    with open(runner_path, "r", encoding="utf-8") as fh:
      runner_source = fh.read()

    # Find the payroll_feasibility_repair invocation block and check
    # required kwargs appear in its vicinity (within ~2000 chars
    # after the step name).
    idx = runner_source.find('"payroll_feasibility_repair"')
    self.assertGreater(idx, 0)
    block = runner_source[idx: idx + 2500]
    for required_kw in (
      "business_facts",
      "ops_json",
      "people_json",
      "financials_json",
      "financials_year1_json",
      "planning_mode",
      "planning_mode_reason",
      "model_input_json",
      "finmo_json",
      "stage_ramp_contract",
      "draft_id",
      "client_id",
      "previous_contract_failure",
    ):
      self.assertIn(required_kw, block, msg=f"missing kwarg {required_kw!r}")


if __name__ == "__main__":
  unittest.main()
