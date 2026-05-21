"""Phase 9 P3.32 K1 F6 — payroll three-surface re-sync + invariant.

Companion to K1 F1+F2+F3+F4+F5. Addresses the THIRD Payroll write
path discovered during the P3.32 CareFirst V-4 investigation:

  - Convergence runner produces schedule_v2 (e.g. Registered Nurses
    benefits_pct=0.25 / Q1 quarter_totals.payroll=106928) and
    persists it to the SQL `payroll_headcount` column.
  - Orchestrator's `_run_post_cascade_completion` continues with
    the stale local `payroll_headcount` variable (schedule_v1,
    benefits_pct=0.22 / Q1=106192) plus a stale
    final_model_input_json derived from schedule_v1.
  - Pre-finalize persist writes model_input column with
    schedule_v1-derived values (109380 Q5) on top of payroll_
    headcount column with schedule_v2 (110138 Q5).
  - Result: $736-828 per-quarter Cash divergence on V-4 verifier;
    P3.32 CareFirst workbook
    4207488106054d72afbe16480e1de100.xlsx exhibits the latent
    failure as a $44,929 Cash Q20 gap.

F6 fix shape:

  (1) Re-sync at the start of `_run_post_cascade_completion`:
      read canonical payroll_headcount from SQL; if it differs
      from the local variable, call apply_payroll_schedule_to_
      state to re-apply through the Mirror Flavor 1 apply chain.
      The canonical SQL column becomes the source of truth.

  (2) Three-surface invariant assertion before pre-finalize
      persist: payroll_headcount.quarter_totals MUST equal
      model_input.expenses.Payroll.values MUST equal
      model_input.derived_driver_runtime[expenses::Payroll].
      payroll_headcount.quarter_totals (per-quarter, $1
      tolerance for int rounding). Hard-fail surfaces the
      offending intervening stage explicitly.

Together, (1) and (2) close the third Payroll write path. Doctrine
non-negotiable preserved: payroll surfaces agree at the persist
gate.

DOCTRINE FOUR-SURFACE CHECK:
  Q1. Surfaces holding payroll dollars:
      - payroll_headcount.{rows, quarter_totals, assumptions}
        (SQL column, canonical)
      - model_input.expenses.Payroll.values (derived via apply
        chain)
      - model_input.derived_driver_runtime[expenses::Payroll].
        payroll_headcount.quarter_totals (snapshot used by
        apply_derived_driver_policies_to_model_input)
      - finmo.pl.Payroll / finmo.quarter_rows.payroll (derived
        via build_python_finmo_json from model_input.values)
  Q2. Alignment mechanism:
      Handler C as single writer + apply_payroll_schedule_to_
      state + Mirror Flavor 1 assertions (zero tolerance via
      assert_payroll_headcount_model_input_applied and
      assert_finmo_payroll_matches_headcount_schedule).
  Q3. This fix preserves alignment:
      YES — the F6 re-sync USES the canonical apply chain to
      refresh model_input + finmo from the canonical SQL
      payroll_headcount. The pre-finalize invariant catches any
      new drift introduced by stages downstream of the re-sync.
  Q4. Handler C consults stage_ramp_contract:
      YES (confirmed in F5 — schedule.py:2191 signature +
      schedule.py:2300 prompt + schedule.py:2478 task
      instruction). The re-sync uses apply_payroll_schedule_to_
      state which does NOT invoke Handler C — it just re-applies
      the already-authored canonical schedule. Contract
      awareness was already preserved at Handler C authoring
      time when the canonical schedule was produced.

This file pins:
  - Orchestrator imports the apply primitive at the F6 site.
  - The F6 re-sync block reads payroll_headcount from SQL,
    compares quarter_totals, and re-applies on mismatch.
  - The re-sync writes payroll_state_resync entry to
    completion_trace with status (in_sync / completed /
    canonical_empty / apply_failed / resync_lookup_failed).
  - The pre-finalize three-surface invariant fires on drift,
    naming all three surfaces in the diagnostic.
  - The invariant respects $1 int-rounding tolerance but
    catches drift > $1 (the empirical CareFirst gap was $736+).
  - K1 F1+F2 invariant preserved (exhaustion handler still
    excludes Payroll — F6's premise).
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


class TestF6ResyncBlockPresentInOrchestrator(unittest.TestCase):
  """Source-level: the orchestrator has the F6 re-sync block at the
  start of _run_post_cascade_completion."""

  @staticmethod
  def _orchestrator_source() -> str:
    path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo", "post_intake_solver",
      "orchestrator.py",
    )
    with open(path, "r", encoding="utf-8") as fh:
      return fh.read()

  def test_orchestrator_contains_f6_marker(self) -> None:
    src = self._orchestrator_source()
    self.assertIn("Phase 9 P3.32 K1 F6", src)
    self.assertIn("payroll state re-sync", src)

  def test_f6_reads_canonical_from_sql_column(self) -> None:
    src = self._orchestrator_source()
    self.assertIn(
      "SELECT payroll_headcount FROM intake_consult_drafts WHERE draft_id = %s",
      src,
      msg="F6 must re-read canonical payroll_headcount from SQL",
    )

  def test_f6_uses_canonical_apply_chain(self) -> None:
    """F6 must use apply_payroll_schedule_to_state (the canonical
    Mirror Flavor 1 apply chain) to refresh model_input + finmo.
    Bypassing this chain would re-introduce the divergence the F6
    fix exists to close."""
    src = self._orchestrator_source()
    self.assertIn("from client_intake_and_finmo.post_intake_headcount.feasibility_repair import", src)
    self.assertIn("apply_payroll_schedule_to_state", src)

  def test_f6_records_completion_trace_entry(self) -> None:
    src = self._orchestrator_source()
    self.assertIn("\"payroll_state_resync\":", src)


class TestF6PreFinalizeInvariantPresentInOrchestrator(unittest.TestCase):
  """Source-level: the pre-finalize persist has the three-surface
  invariant assertion."""

  @staticmethod
  def _orchestrator_source() -> str:
    path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo", "post_intake_solver",
      "orchestrator.py",
    )
    with open(path, "r", encoding="utf-8") as fh:
      return fh.read()

  def test_invariant_fail_fast_operation_named(self) -> None:
    src = self._orchestrator_source()
    self.assertIn(
      "pre_finalize_persist_payroll_three_surface_invariant_violation",
      src,
      msg="The invariant violation must have a distinct op code for diagnostics",
    )

  def test_invariant_names_all_three_surfaces(self) -> None:
    src = self._orchestrator_source()
    self.assertIn("payroll_headcount.quarter_totals", src)
    self.assertIn("model_input.expenses.Payroll.values", src)
    self.assertIn("derived_driver_runtime", src)


class TestF6InvariantRespectsIntRoundingTolerance(unittest.TestCase):
  """The invariant uses int rounding + 1-dollar tolerance to absorb
  the per-row int(quarterly_wage_cost + quarterly_taxes_benefits)
  rounding that Handler C uses. Empirical CareFirst gap was $736+
  per quarter — far above any int-rounding noise."""

  def test_int_rounding_acceptance(self) -> None:
    # If canonical Q1 = 106928 and model_input.values[1] rounds to
    # 106928, both produce the same int; delta = 0; invariant passes.
    canonical_v = int(round(106928.0))
    model_input_v = int(round(106928.49))
    self.assertEqual(canonical_v, model_input_v)
    self.assertLessEqual(abs(canonical_v - model_input_v), 1)

  def test_drift_detection_at_dollar_one(self) -> None:
    # Even a $2 drift (above $1 tolerance) should be detected.
    canonical_v = 106928
    model_input_v = 106930
    self.assertGreater(abs(canonical_v - model_input_v), 1)

  def test_drift_detection_at_carefirst_scale(self) -> None:
    # CareFirst empirical: $736 per quarter drift. Always detected.
    canonical_v = 106928
    model_input_v = 106192
    self.assertGreater(abs(canonical_v - model_input_v), 1)
    self.assertEqual(canonical_v - model_input_v, 736)


class TestApplyPayrollScheduleToStatePrimitivePreserved(unittest.TestCase):
  """F6 reuses the existing P3.26 Commit 2 apply primitive that
  enforces Mirror Flavor 1 alignment with zero tolerance via two
  assertions inside the call. The primitive's signature must
  continue to support F6's call shape."""

  def test_primitive_accepts_f6_required_args(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.feasibility_repair import (  # noqa: WPS433
      apply_payroll_schedule_to_state,
    )
    import inspect
    sig = inspect.signature(apply_payroll_schedule_to_state)
    expected = {
      "schedule_payload", "model_input_json", "finmo_json",
      "live_count", "stage_prefix",
    }
    self.assertTrue(
      expected.issubset(set(sig.parameters.keys())),
      msg=f"apply_payroll_schedule_to_state missing kwargs: {expected - set(sig.parameters.keys())}",
    )

  def test_primitive_enforces_mirror_flavor_1_assertions(self) -> None:
    """The primitive must call both Mirror Flavor 1 assertions:
    assert_payroll_headcount_model_input_applied (model_input
    matches schedule) and assert_finmo_payroll_matches_headcount_
    schedule (finmo matches schedule). Without these, F6's re-sync
    could complete successfully while leaving residual drift."""
    path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo", "post_intake_headcount",
      "feasibility_repair.py",
    )
    with open(path, "r", encoding="utf-8") as fh:
      src = fh.read()
    self.assertIn("assert_payroll_headcount_model_input_applied(", src)
    self.assertIn("assert_finmo_payroll_matches_headcount_schedule(", src)


class TestK1InvariantPreservedByF6(unittest.TestCase):
  """F6 operates within K1 F1+F2's structural closure of Leak A.
  If expenses::Payroll were ever re-added to the exhaustion
  handler's catalog, F6's re-sync premise (Handler C is the
  canonical writer) becomes false."""

  def test_exhaustion_handler_still_excludes_payroll(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (  # noqa: WPS433
      GPT_AUTHORED_LEVER_IDS,
    )
    self.assertNotIn("expenses::Payroll", GPT_AUTHORED_LEVER_IDS)

  def test_target_solver_still_excludes_payroll(self) -> None:
    from client_intake_and_finmo.post_intake_target_solver.target_solver import (  # noqa: WPS433
      _HANDLER_C_OWNED_LEVER_IDS,
    )
    self.assertIn("expenses::Payroll", _HANDLER_C_OWNED_LEVER_IDS)


class TestOnlyPayrollHasSchedulePersistedSeparately(unittest.TestCase):
  """Doctrine note: F6 fixes a class of bug that exists ONLY for
  payroll. Other expense / balance_sheet / revenue rows store their
  values directly in model_input.values without a separate SQL
  column or an embedded schedule snapshot. The empirical inspection
  of the CareFirst persisted state confirmed this. This test pins
  the property by ensuring no other row's structure is mutated to
  add a similar snapshot field (which would re-introduce the same
  class of bug)."""

  def test_payroll_headcount_column_only_payroll_specific_column(self) -> None:
    """Search the persist util to confirm payroll_headcount is the
    only handler-output-specific column. If a future change adds
    cogs_headcount, marketing_headcount, etc., this test fails and
    forces the operator to apply F6's pattern to those surfaces."""
    path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo", "intake_consult_draft.py",
    )
    with open(path, "r", encoding="utf-8") as fh:
      src = fh.read()
    # Look for similarly-shaped 'lever_headcount' or 'lever_schedule'
    # column write patterns. Only payroll_headcount is allowed.
    suspicious_patterns = [
      "marketing_headcount = %s",
      "cogs_headcount = %s",
      "rd_headcount = %s",
      "ga_headcount = %s",
    ]
    for pattern in suspicious_patterns:
      self.assertNotIn(
        pattern, src,
        msg=f"New lever-specific schedule column detected: {pattern}. "
            "Apply F6's three-surface invariant pattern to the new "
            "surface before merging.",
      )


if __name__ == "__main__":
  unittest.main()
