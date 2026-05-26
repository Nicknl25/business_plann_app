"""Acceptance tests for Contract 6 Commit 3 boundary gates.

4 wired gates per F14/F15:
- Producer-side: runner.py:580+ Shape D (PopulationSummary,
  F10 invariant).
- Consumer-side: finmo_bridge.py:339 + driver_movement_assembler.py:97
  Shape A (CascadeResolverPayload, F8/F13 Literals + F4
  fallback_chain).
- Consumer-side: cohort_bands_table.py:386 Shape C
  (GetBandsView, F12 (b) monotonicity).

These tests exercise the 4 enforcement helpers directly with
representative valid + invalid payloads + Adjustment B
end-to-end + best-effort emit.

Spec: ``docs/architecture/p3_40_contract_6_industry_baseline_spec.md`` §6 Commit 3.

6 test classes:
- CohortProducerGateTest (F14): Shape D producer-side gate +
  F10 zero-resolved precondition.
- ShapeAConsumerGateTest (F15): Shape A consumer-side gate at
  Shape A enforcement helper.
- ShapeBPerRowGateTest (R13 defense-in-depth helper).
- ShapeCConsumerGateTest (F15): Shape C consumer-side gate
  with F12 (b) monotonicity.
- ApiCatchPatternEndToEndTest (F17): Adjustment B per Contracts
  3-5 pattern.
- DiagnosticEmitBestEffortTest: gate succeeds when emit raises.
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
ROOT = os.path.abspath(os.path.join(HERE, os.pardir))
for path in (PYTHON_ROOT, ROOT, HERE):
  if path not in sys.path:
    sys.path.insert(0, path)


from client_intake_and_finmo.post_intake_contracts.enforcement import (  # noqa: E402
  INDUSTRY_BASELINE_STAGE_LABEL,
  SIDE_CONSUMER,
  SIDE_PRODUCER,
  validate_industry_baseline_cascade_payload_at_boundary,
  validate_industry_baseline_cohort_sql_row_at_boundary,
  validate_industry_baseline_get_bands_view_at_boundary,
  validate_industry_baseline_population_summary_at_boundary,
)
from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (  # noqa: E402
  ContractViolation,
)
from client_intake_and_finmo.post_intake_contracts.industry_baseline_resolved_contract import (  # noqa: E402
  CascadeResolverPayloadContract,
  CohortSqlRowContract,
  GetBandsViewContract,
  PopulationSummaryContract,
)
from _p3_40_contract_6_fixtures import (  # noqa: E402
  valid_cascade_resolver_payload_dict,
  valid_cohort_sql_row_dict,
  valid_get_bands_view_dict,
  valid_population_summary_dict,
  valid_population_summary_section_dict,
)


# ---------------------------------------------------------------------------
# Shape D producer-side gate (runner.py:580 wiring)
# ---------------------------------------------------------------------------

class CohortProducerGateTest(unittest.TestCase):
  """F14 (a) SHIP cohort producer-side gate. F10 invariant
  (total resolved >= 1) closes v1 §F-2 FAIL_COHORT_BANDS_MISSING
  precondition that today is swallowed by the soft try/except
  at runner.py:556-583."""

  def test_valid_population_summary_returns_parsed_contract(self) -> None:
    contract = validate_industry_baseline_population_summary_at_boundary(
      valid_population_summary_dict(), side=SIDE_PRODUCER,
    )
    self.assertIsInstance(contract, PopulationSummaryContract)
    self.assertIsNotNone(contract.drivers)

  def test_zero_resolved_total_rejected_at_gate_f10(self) -> None:
    """F10 cross-field invariant fires through the gate. Surfaces
    the precondition as ContractViolation rather than silent
    skip."""
    bad_payload = {
      "drivers": valid_population_summary_section_dict(resolved=0, skipped=5),
    }
    with self.assertRaises(ContractViolation) as ctx:
      validate_industry_baseline_population_summary_at_boundary(
        bad_payload, side=SIDE_PRODUCER,
      )
    self.assertEqual(ctx.exception.stage, INDUSTRY_BASELINE_STAGE_LABEL)

  def test_gate_accepts_both_producer_and_consumer_sides(self) -> None:
    """side parameter is opaque to the gate (used only for the
    diagnostic emit's side field)."""
    payload = valid_population_summary_dict()
    validate_industry_baseline_population_summary_at_boundary(
      payload, side=SIDE_PRODUCER,
    )
    validate_industry_baseline_population_summary_at_boundary(
      payload, side=SIDE_CONSUMER,
    )


# ---------------------------------------------------------------------------
# Shape A consumer-side gate (finmo_bridge + driver_movement_assembler)
# ---------------------------------------------------------------------------

class ShapeAConsumerGateTest(unittest.TestCase):
  """F15 (a) per-shape consumer-side gates. Shape A wired at
  2 sites: finmo_bridge.py:339 _attach_seed_provenance +
  driver_movement_assembler.py:97 _resolve_naics_band."""

  def test_valid_cascade_payload_returns_parsed_contract(self) -> None:
    contract = validate_industry_baseline_cascade_payload_at_boundary(
      valid_cascade_resolver_payload_dict(), side=SIDE_CONSUMER,
    )
    self.assertIsInstance(contract, CascadeResolverPayloadContract)
    self.assertEqual(contract.metric_key, "gross_margin_percent")

  def test_invalid_trust_flag_rejected(self) -> None:
    """F13 trust_flag Literal violation surfaces through gate."""
    payload = valid_cascade_resolver_payload_dict()
    payload["trust_flag"] = "made_up_flag"
    with self.assertRaises(ContractViolation) as ctx:
      validate_industry_baseline_cascade_payload_at_boundary(
        payload, side=SIDE_CONSUMER,
      )
    self.assertEqual(ctx.exception.stage, INDUSTRY_BASELINE_STAGE_LABEL)
    self.assertIn("trust_flag", ctx.exception.field)

  def test_naics_level_1_rejected(self) -> None:
    """F13 naics_level_used Literal[0,2,3,4,5,6] -- level 1
    rejected (non-contiguous per trace T5.3)."""
    payload = valid_cascade_resolver_payload_dict(level_used=1)
    with self.assertRaises(ContractViolation):
      validate_industry_baseline_cascade_payload_at_boundary(
        payload, side=SIDE_CONSUMER,
      )


# ---------------------------------------------------------------------------
# Shape B per-row gate (helper exists; production R13 SKIPPED per F15)
# ---------------------------------------------------------------------------

class ShapeBPerRowGateTest(unittest.TestCase):
  """The Shape B per-row enforcement helper exists for test
  paths + future direct-SQL consumers. F15 (a) SKIPS production
  per-row validation inside the populator loop (R13
  defense-in-depth follow-up)."""

  def test_valid_sql_row_returns_parsed_contract(self) -> None:
    contract = validate_industry_baseline_cohort_sql_row_at_boundary(
      valid_cohort_sql_row_dict(), side=SIDE_PRODUCER,
    )
    self.assertIsInstance(contract, CohortSqlRowContract)

  def test_monotonicity_violation_rejected(self) -> None:
    """F12 (a) cross-field invariant fires through the gate."""
    payload = valid_cohort_sql_row_dict(
      benchmark_min=0.99, benchmark_target=0.40, benchmark_max=0.55,
    )
    with self.assertRaises(ContractViolation) as ctx:
      validate_industry_baseline_cohort_sql_row_at_boundary(
        payload, side=SIDE_PRODUCER,
      )
    self.assertEqual(ctx.exception.stage, INDUSTRY_BASELINE_STAGE_LABEL)


# ---------------------------------------------------------------------------
# Shape C consumer-side gate (cohort_bands_table.py:386)
# ---------------------------------------------------------------------------

class ShapeCConsumerGateTest(unittest.TestCase):
  """F15 (a) Shape C wired inside get_bands at
  cohort_bands_table.py:386 immediately before return."""

  def test_valid_get_bands_view_returns_parsed_contract(self) -> None:
    contract = validate_industry_baseline_get_bands_view_at_boundary(
      valid_get_bands_view_dict(), side=SIDE_CONSUMER,
    )
    self.assertIsInstance(contract, GetBandsViewContract)
    self.assertEqual(contract.section, "drivers")

  def test_invalid_section_rejected(self) -> None:
    """F3 section Literal violation surfaces through gate."""
    payload = valid_get_bands_view_dict()
    payload["section"] = "made_up_section"
    with self.assertRaises(ContractViolation):
      validate_industry_baseline_get_bands_view_at_boundary(
        payload, side=SIDE_CONSUMER,
      )

  def test_band_monotonicity_violation_rejected(self) -> None:
    """F12 (b) per-band monotonicity fires through the gate."""
    payload = valid_get_bands_view_dict()
    first_lever_id = next(iter(payload["bands"].keys()))
    payload["bands"][first_lever_id]["benchmark_min"] = 0.99
    payload["bands"][first_lever_id]["benchmark_target"] = 0.40
    payload["bands"][first_lever_id]["benchmark_max"] = 0.55
    with self.assertRaises(ContractViolation) as ctx:
      validate_industry_baseline_get_bands_view_at_boundary(
        payload, side=SIDE_CONSUMER,
      )
    self.assertIn("monotonicity", str(ctx.exception))


# ---------------------------------------------------------------------------
# Adjustment B end-to-end through the API handler catch pattern
# ---------------------------------------------------------------------------

class ApiCatchPatternEndToEndTest(unittest.TestCase):
  """Mirror of Contracts 3-5 ApiCatchPatternEndToEndTest. The 4
  gates are wired in production at runner.py:580 (Shape D),
  finmo_bridge.py:339 + driver_movement_assembler.py:97
  (Shape A), and cohort_bands_table.py:386 (Shape C). All
  ContractViolations propagate through the API handler's
  `except Exception as exc:` (line 7377 region)."""

  def test_violation_is_subclass_of_exception(self) -> None:
    self.assertTrue(issubclass(ContractViolation, Exception))

  def test_violation_is_NOT_subclass_of_runtime_error(self) -> None:
    """Must skip the line-7298 RuntimeError catch so it lands
    in the line-7377 generic catch."""
    self.assertFalse(issubclass(ContractViolation, RuntimeError))

  def test_violation_str_used_by_api_log_carries_stage_and_field(self) -> None:
    """Mirrors intake_consult.py:7377 pattern."""
    bad_payload = {
      "drivers": valid_population_summary_section_dict(resolved=0, skipped=5),
    }
    try:
      validate_industry_baseline_population_summary_at_boundary(
        bad_payload, side=SIDE_PRODUCER,
      )
      self.fail("expected ContractViolation")
    except Exception as exc:  # exact pattern from line 7377
      log_line = str(exc).strip() or "system_run_failed"
      self.assertIn(INDUSTRY_BASELINE_STAGE_LABEL, log_line)
      self.assertNotEqual(log_line, "system_run_failed")


# ---------------------------------------------------------------------------
# Diagnostic emit is best-effort across all 4 helpers
# ---------------------------------------------------------------------------

class DiagnosticEmitBestEffortTest(unittest.TestCase):

  def _broken_emitter(self, **_kwargs):
    raise RuntimeError("simulated diagnostic emission failure")

  def test_cascade_payload_helper_succeeds_when_emit_raises(self) -> None:
    contract = validate_industry_baseline_cascade_payload_at_boundary(
      valid_cascade_resolver_payload_dict(),
      side=SIDE_CONSUMER,
      emit_diagnostic_fn=self._broken_emitter,
    )
    self.assertIsInstance(contract, CascadeResolverPayloadContract)

  def test_population_summary_helper_succeeds_when_emit_raises(self) -> None:
    contract = validate_industry_baseline_population_summary_at_boundary(
      valid_population_summary_dict(),
      side=SIDE_PRODUCER,
      emit_diagnostic_fn=self._broken_emitter,
    )
    self.assertIsInstance(contract, PopulationSummaryContract)


if __name__ == "__main__":
  unittest.main()
