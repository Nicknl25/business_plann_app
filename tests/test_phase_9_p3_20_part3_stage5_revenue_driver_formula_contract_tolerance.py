"""Phase 9 P3.20 Part 3 Stage 5 -- revenue driver formula contract tolerance.

The FINMO bridge's `_enforce_revenue_driver_formula_contract` asserts
that FINMO's per-quarter revenue equals the model-input driver-
formula revenue (sum of Capacity * Unit Price * Utilization across
products) for every live quarter.

Pre-Stage-5 the comparator was `int(round(finmo)) != int(round(
driver))`. That comparator trips on float-rounding-boundary noise --
e.g., FINMO core's accumulation produces 1673073.4999 while the
driver formula path produces 1673073.5001 (a $0.0002 difference),
which integer-rounds to 1673073 and 1673074 respectively. The
underlying floats agree to within a cent, but the int-equality
fires.

Stage 5 replaces the comparator with `abs(finmo - driver) > 1.0`
matching the existing FINMO-coherence tolerance convention (the
accounting-equation check in the same file uses `tolerance = 1.0`).
A larger divergence (e.g., FINMO applying a stage-ramp modifier
the driver formula doesn't) still fires above the $1 floor.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYTHON_DIR = _REPO_ROOT / "python"
if str(_PYTHON_DIR) not in sys.path:
  sys.path.insert(0, str(_PYTHON_DIR))

from client_intake_and_finmo import finmo_bridge as _fb  # noqa: E402


def _model_input_with_revenue_drivers(per_quarter_revenue: float) -> dict:
  """Build a minimal model_input_json with one product whose Capacity
  * Unit Price * Utilization equals `per_quarter_revenue` per quarter
  for 20 live quarters."""
  # Pick decomposable factors. cap*price*util = target. Use util=1.0
  # and cap=1.0, then price = target.
  per_q_values = [per_quarter_revenue for _ in range(20)]
  # Use a single-product driver triple so the driver-formula sum
  # walk reduces to a single multiplication per quarter.
  def _row(label: str, driver: str, values: list) -> dict:
    return {
      "section": "revenue",
      "label": label,
      "lob": "Default LOB",
      "product": "Default Product",
      "driver": driver,
      # Use 21 slots: 1 stub + 20 live. Stub = 0 to make _row_stub_and_live_values
      # treat all 20 live values as the forecast.
      "values": [0.0, *values],
    }
  return {
    "sections": {
      "revenue": [
        _row("Capacity", "Capacity", [1.0 for _ in range(20)]),
        _row("Unit Price", "Unit Price", per_q_values),
        _row("Utilization", "Utilization", [1.0 for _ in range(20)]),
      ],
    },
  }


def _quarter_rows_with_revenue(per_quarter_revenue: float) -> list:
  return [{"quarter_index": q, "revenue": per_quarter_revenue} for q in range(1, 21)]


class RevenueDriverFormulaContractToleranceTests(unittest.TestCase):

  def test_passes_when_paths_agree_exactly(self) -> None:
    target = 1_673_073.0
    mi = _model_input_with_revenue_drivers(target)
    qr = _quarter_rows_with_revenue(target)
    # No raise expected.
    _fb._enforce_revenue_driver_formula_contract(
      model_input_json=mi,
      quarter_rows_raw=qr,
    )

  def test_passes_when_paths_differ_by_sub_cent_float_noise(self) -> None:
    """Float-rounding-boundary case (the canonical Stage 5 iter 1
    motivating scenario): FINMO=1673073.4999, driver=1673073.5001.
    A sub-cent (~$0.0002) delta -- well below the P3.22 Part 2
    consolidated $0.015 tolerance. No raise expected."""
    target = 1_673_073.5001
    mi = _model_input_with_revenue_drivers(target)
    # Build FINMO-side rows with a sub-cent skew.
    qr = _quarter_rows_with_revenue(target - 0.0002)
    # No raise expected -- delta is well under $0.015.
    _fb._enforce_revenue_driver_formula_contract(
      model_input_json=mi,
      quarter_rows_raw=qr,
    )

  def test_passes_when_paths_differ_at_boundary(self) -> None:
    """Boundary: a $0.014 delta (just below the $0.015 P3.22 Part
    2 tolerance) must still pass. P3.22 Part 2 replaced Stage 5
    iter 1's $1.0 escape with the existing pre-existing fail_fast
    convention of $0.015 (1.5 cents), matching the genuine float-
    rounding-mode noise scale."""
    target = 1_673_073.0
    mi = _model_input_with_revenue_drivers(target)
    qr = _quarter_rows_with_revenue(target + 0.014)
    # No raise expected -- $0.014 is below the $0.015 threshold.
    _fb._enforce_revenue_driver_formula_contract(
      model_input_json=mi,
      quarter_rows_raw=qr,
    )

  def test_raises_when_paths_differ_above_tolerance(self) -> None:
    """A divergence > $0.015 should fire (e.g., a real source bug
    like FINMO applying a stage-ramp modifier the driver formula
    doesn't apply). P3.22 Part 2 tightened from Stage 5 iter 1's
    $1.0 to $0.015 (matching the pre-existing fail_fast precedent),
    so multi-dollar divergences fire much more aggressively than
    they did under Stage 5 iter 1."""
    target = 1_673_073.0
    mi = _model_input_with_revenue_drivers(target)
    # A $100 divergence is far above the $0.015 boundary.
    qr = _quarter_rows_with_revenue(target + 100.0)
    with self.assertRaises(ValueError) as ctx:
      _fb._enforce_revenue_driver_formula_contract(
        model_input_json=mi,
        quarter_rows_raw=qr,
      )
    msg = str(ctx.exception)
    self.assertIn("revenue_driver_formula_contract_failed", msg)
    self.assertIn("quarter_index", msg)

  def test_raises_when_paths_differ_by_one_dollar_under_new_tolerance(self) -> None:
    """P3.22 Part 2 regression: pre-refactor, $1 delta passed
    Stage 5 iter 1's $1 tolerance. Post-refactor, $1 delta FAILS
    the tighter $0.015 tolerance. Confirms the consolidation
    actually moved to the tighter pre-existing fail_fast precedent
    rather than relaxing fail_fast to Stage 5's looser value."""
    target = 1_673_073.0
    mi = _model_input_with_revenue_drivers(target)
    qr = _quarter_rows_with_revenue(target + 1.0)
    with self.assertRaises(ValueError) as ctx:
      _fb._enforce_revenue_driver_formula_contract(
        model_input_json=mi,
        quarter_rows_raw=qr,
      )
    msg = str(ctx.exception)
    self.assertIn("revenue_driver_formula_contract_failed", msg)

  def test_diagnostic_payload_reports_true_float_delta(self) -> None:
    """Stage 4 diagnostic-preservation rule: the delta field must
    report the true float delta, not an int-rounded zero (which
    was the pre-Stage-5 behavior that made sub-dollar boundary
    failures look like delta=0)."""
    target = 1_673_073.0
    mi = _model_input_with_revenue_drivers(target)
    # Skew enough to trip the tolerance, with a precise sub-integer delta.
    qr = _quarter_rows_with_revenue(target + 5.25)
    with self.assertRaises(ValueError) as ctx:
      _fb._enforce_revenue_driver_formula_contract(
        model_input_json=mi,
        quarter_rows_raw=qr,
      )
    msg = str(ctx.exception)
    # The actual float delta should appear (5.25), not 5 (the int-rounded).
    self.assertIn('"delta": 5.25', msg)

  def test_source_uses_shared_tolerance_constant(self) -> None:
    """Source-shape sanity. P3.22 Part 2 consolidated the comparator
    to use the shared `REVENUE_DRIVER_FORMULA_TOLERANCE` constant
    (= $0.015) defined in finmo_bridge.py, replacing Stage 5 iter
    1's literal $1.0 threshold. Both check sites (this contract +
    fail_fast.assert_post_intake_revenue_driver_integrity) now
    read from the same constant. If a future refactor changes the
    comparator without an explicit doctrine update, this test
    catches it."""
    src = Path(_fb.__file__).read_text(encoding="utf-8")
    # New shared-constant comparator literal.
    self.assertIn("abs(delta_float) > REVENUE_DRIVER_FORMULA_TOLERANCE", src)
    # Constant defined in finmo_bridge as $0.015.
    self.assertIn("REVENUE_DRIVER_FORMULA_TOLERANCE: float = 0.015", src)
    # Stage 5 iter 1's literal `> 1.0` comparator must be gone from
    # this contract (the literal may still appear elsewhere in the
    # file, e.g. for unrelated checks; we only care about THIS one).
    fn_idx = src.find("def _enforce_revenue_driver_formula_contract(")
    self.assertGreater(fn_idx, 0)
    next_def_idx = src.find("\ndef ", fn_idx + 1)
    self.assertGreater(next_def_idx, fn_idx)
    fn_body = src[fn_idx:next_def_idx]
    self.assertNotIn(
      "int(round(finmo_revenue)) != int(round(driver_revenue))",
      fn_body,
      "Pre-Stage-5 int-equality comparator must be removed",
    )
    self.assertNotIn(
      "abs(delta_float) > 1.0",
      fn_body,
      "Stage 5 iter 1's literal $1.0 comparator must be replaced by "
      "the shared REVENUE_DRIVER_FORMULA_TOLERANCE constant",
    )


if __name__ == "__main__":
  unittest.main()
