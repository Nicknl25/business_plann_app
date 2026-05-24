"""Phase 9 P3.33 Phase 3 step 5c — deterministic floor + mode primitives.

Hermetic tests for the floor module. The K13-wrapping primitives
(VIABILITY/GROWTH) are tested with the underlying handler functions
injected as fakes so no live model_input is required. The pure-Python
primitives (CAPACITY/BAND/COHERENCE) are tested directly.

Confirms:

  - apply_floor_primitive dispatches by mode.
  - VIABILITY primitive wraps apply_viability_floor and emits a
    VIABILITY_FLOOR_PRIMITIVE step with the applied COGS.
  - GROWTH primitive wraps reconcile_revenue_to_stage_ramp and emits a
    GROWTH_FLOOR_PRIMITIVE step with the applied utilization.
  - CAPACITY primitive computes ceil(target / (52 × price × util)).
  - BAND primitive clips every out-of-band margin to nearest edge.
  - COHERENCE primitive emits one anchor + N non-anchor reauthor steps.
  - floor_for_mode prefers cascade_walker when it returns 'resolved';
    falls back to the primitive otherwise.
"""

from __future__ import annotations

import math
import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)

from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (  # noqa: E402
  FailureMode, LeverMargin,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.floor import (  # noqa: E402
  FloorResult,
  apply_floor_primitive,
  band_floor_primitive,
  capacity_floor_primitive,
  coherence_floor_primitive,
  floor_for_mode,
  growth_floor_primitive,
  viability_floor_primitive,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (  # noqa: E402
  AppliedBy, ReasonCode, StepType,
)


class ViabilityPrimitiveTest(unittest.TestCase):
  def test_wraps_apply_viability_floor(self) -> None:
    def fake_floor(*, model_input, build_finmo, stage_ramp_contract):
      return {"applied_cogs": 0.45, "q11_ebitda_after": 0.02}
    steps = viability_floor_primitive(
      model_input={"any": "shape"},
      _apply_viability_floor=fake_floor,
    )
    self.assertEqual(len(steps), 1)
    s = steps[0]
    self.assertEqual(s.applied_by, AppliedBy.FLOOR_PRIMITIVE)
    self.assertEqual(s.reason_code, ReasonCode.VIABILITY_FLOOR_PRIMITIVE)
    self.assertEqual(s.section, "drivers")
    self.assertEqual(s.field, "expenses::Cost of Goods Sold")
    self.assertAlmostEqual(s.applied_value, 0.45)

  def test_records_exception_as_unaccepted_step(self) -> None:
    def explode(**kwargs): raise RuntimeError("boom")
    steps = viability_floor_primitive(_apply_viability_floor=explode)
    self.assertEqual(len(steps), 1)
    self.assertFalse(steps[0].accepted)
    self.assertIn("boom", steps[0].detail)


class GrowthPrimitiveTest(unittest.TestCase):
  def test_wraps_reconcile_revenue_to_stage_ramp(self) -> None:
    def fake_reconcile(*, model_input, build_finmo, stage_ramp_contract, max_passes):
      return {"applied_utilization": 0.78, "passes_used": 3}
    steps = growth_floor_primitive(
      stage_ramp_contract={"shape": "x"},
      _reconcile=fake_reconcile,
    )
    self.assertEqual(len(steps), 1)
    s = steps[0]
    self.assertEqual(s.reason_code, ReasonCode.GROWTH_FLOOR_PRIMITIVE)
    self.assertEqual(s.section, "operating_model")
    self.assertEqual(s.field, "utilization_rate")
    self.assertAlmostEqual(s.applied_value, 0.78)


class CapacityPrimitiveTest(unittest.TestCase):
  def test_computes_required_capacity_correctly(self) -> None:
    # target_q12_revenue = $1M, unit_price = $50, cohort_util_target = 0.7
    # required = 1_000_000 / (52 × 50 × 0.7) = 549.45 -> ceil = 550
    steps = capacity_floor_primitive(
      target_q12_revenue=1_000_000.0,
      unit_price=50.0,
      cohort_util_target=0.7,
    )
    self.assertEqual(len(steps), 1)
    self.assertEqual(steps[0].section, "operating_model")
    self.assertEqual(steps[0].field, "units_per_week_capacity")
    self.assertAlmostEqual(steps[0].applied_value, 550.0)
    self.assertEqual(steps[0].reason_code, ReasonCode.CAPACITY_FLOOR_PRIMITIVE)

  def test_missing_inputs_emits_unaccepted_step(self) -> None:
    steps = capacity_floor_primitive(
      target_q12_revenue=None, unit_price=50.0, cohort_util_target=0.7,
    )
    self.assertEqual(len(steps), 1)
    self.assertFalse(steps[0].accepted)
    self.assertIn("target_q12_revenue", steps[0].detail)


class BandPrimitiveTest(unittest.TestCase):
  def _margin(self, **kwargs):
    base = dict(lever_id="x", section="drivers", quarter=None,
                current=None, band_min=None, band_target=None, band_max=None,
                distance_to_min=None, distance_to_max=None,
                pinned_min=False, pinned_max=False, outside_band=False)
    base.update(kwargs)
    return LeverMargin(**base)

  def test_clips_above_max_to_band_max(self) -> None:
    m = self._margin(current=0.85, band_min=0.55, band_target=0.65,
                     band_max=0.78, outside_band=True,
                     lever_id="expenses::COGS")
    steps = band_floor_primitive(lever_margins=[m])
    self.assertEqual(len(steps), 1)
    self.assertAlmostEqual(steps[0].applied_value, 0.78)
    self.assertEqual(steps[0].field, "expenses::COGS")

  def test_clips_below_min_to_band_min(self) -> None:
    m = self._margin(current=0.40, band_min=0.55, band_target=0.65,
                     band_max=0.78, outside_band=True,
                     lever_id="expenses::COGS")
    steps = band_floor_primitive(lever_margins=[m])
    self.assertAlmostEqual(steps[0].applied_value, 0.55)

  def test_no_out_of_band_margins_emits_noop_step(self) -> None:
    steps = band_floor_primitive(lever_margins=[])
    self.assertEqual(len(steps), 1)
    self.assertIn("no lever_margins", steps[0].detail)


class CoherencePrimitiveTest(unittest.TestCase):
  def test_default_anchor_is_stage_ramp(self) -> None:
    steps = coherence_floor_primitive()
    self.assertEqual(len(steps), 5)
    sections = [s.section for s in steps]
    self.assertEqual(sections[0], "stage_ramp")
    self.assertEqual(set(sections[1:]),
                     {"drivers", "payroll", "capex_rd", "balance_sheet"})

  def test_explicit_anchor_overrides(self) -> None:
    steps = coherence_floor_primitive(anchor_section="drivers")
    self.assertEqual(steps[0].section, "drivers")
    self.assertEqual(len(steps), 5)


class ApplyPrimitiveDispatchTest(unittest.TestCase):
  def test_capacity_dispatched(self) -> None:
    res = apply_floor_primitive(
      FailureMode.CAPACITY_INVARIANT,
      target_q12_revenue=500_000.0, unit_price=25.0, cohort_util_target=0.65,
    )
    self.assertEqual(res.status, "primitive_applied")
    self.assertEqual(res.primitive_reason, ReasonCode.CAPACITY_FLOOR_PRIMITIVE)

  def test_meta_mode_returns_no_primitive(self) -> None:
    res = apply_floor_primitive(FailureMode.META_INVARIANT)
    self.assertEqual(res.status, "no_primitive")


class FloorForModeTest(unittest.TestCase):
  def test_prefers_walker_when_resolved(self) -> None:
    def walker(*, mode):
      return FloorResult(mode=mode, status="resolved")
    res = floor_for_mode(FailureMode.BAND_INVARIANT, cascade_walker=walker)
    self.assertEqual(res.status, "resolved")

  def test_falls_back_to_primitive(self) -> None:
    def walker(*, mode):
      return FloorResult(mode=mode, status="exhausted")
    res = floor_for_mode(
      FailureMode.CAPACITY_INVARIANT,
      cascade_walker=walker,
      primitive_kwargs={
        "target_q12_revenue": 1_000_000.0,
        "unit_price": 50.0,
        "cohort_util_target": 0.7,
      },
    )
    self.assertEqual(res.status, "primitive_applied")
    self.assertEqual(res.primitive_reason, ReasonCode.CAPACITY_FLOOR_PRIMITIVE)

  def test_no_walker_runs_primitive_directly(self) -> None:
    res = floor_for_mode(
      FailureMode.BAND_INVARIANT,
      primitive_kwargs={"lever_margins": []},
    )
    self.assertEqual(res.status, "primitive_applied")


class FloorStepReasonCodeCoverageTest(unittest.TestCase):
  def test_every_primitive_uses_floor_step_type_and_floor_primitive_applied_by(self) -> None:
    """Sanity: every primitive emits FLOOR step_type and FLOOR_PRIMITIVE applied_by.
    Catches accidental drift where a primitive forgets to set them."""
    capacity_steps = capacity_floor_primitive(
      target_q12_revenue=1_000_000.0, unit_price=50.0, cohort_util_target=0.7,
    )
    band_steps = band_floor_primitive(lever_margins=[])
    coh_steps = coherence_floor_primitive()
    for s in capacity_steps + band_steps + coh_steps:
      self.assertEqual(s.step_type, StepType.FLOOR)
      self.assertEqual(s.applied_by, AppliedBy.FLOOR_PRIMITIVE)


if __name__ == "__main__":
  unittest.main()
