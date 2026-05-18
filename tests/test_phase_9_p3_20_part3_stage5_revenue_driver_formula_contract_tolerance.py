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

  def test_passes_when_paths_differ_by_less_than_one_dollar(self) -> None:
    """Float-rounding-boundary case: FINMO=1673073.4999, driver=
    1673073.5001 should NOT trip the contract (residue is float
    noise, sub-$1)."""
    target = 1_673_073.5001
    mi = _model_input_with_revenue_drivers(target)
    # Build FINMO-side rows with a sub-cent skew.
    qr = _quarter_rows_with_revenue(target - 0.0002)
    # No raise expected -- delta is well under $1.
    _fb._enforce_revenue_driver_formula_contract(
      model_input_json=mi,
      quarter_rows_raw=qr,
    )

  def test_passes_when_paths_differ_by_exactly_one_dollar(self) -> None:
    """Boundary: $1 difference is the threshold of the tolerance.
    `abs(delta) > 1.0` means exactly $1 still passes."""
    target = 1_673_073.0
    mi = _model_input_with_revenue_drivers(target)
    qr = _quarter_rows_with_revenue(target + 1.0)
    # No raise expected -- exactly $1 is the upper bound, not strict.
    _fb._enforce_revenue_driver_formula_contract(
      model_input_json=mi,
      quarter_rows_raw=qr,
    )

  def test_raises_when_paths_differ_by_more_than_one_dollar(self) -> None:
    """A divergence > $1 should still fire (e.g., real source bug
    like FINMO applying a stage-ramp modifier the driver formula
    doesn't apply)."""
    target = 1_673_073.0
    mi = _model_input_with_revenue_drivers(target)
    qr = _quarter_rows_with_revenue(target + 100.0)
    with self.assertRaises(ValueError) as ctx:
      _fb._enforce_revenue_driver_formula_contract(
        model_input_json=mi,
        quarter_rows_raw=qr,
      )
    msg = str(ctx.exception)
    self.assertIn("revenue_driver_formula_contract_failed", msg)
    self.assertIn("quarter_index", msg)

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

  def test_source_uses_tolerance_constant_one_dollar(self) -> None:
    """Source-shape sanity: the comparator uses `> 1.0` -- the same
    convention the accounting-equation check uses in the same file
    (`tolerance = 1.0`). If a future refactor changes the threshold
    without an explicit doctrine update, this test catches it."""
    src = Path(_fb.__file__).read_text(encoding="utf-8")
    # The new comparator literal.
    self.assertIn("abs(delta_float) > 1.0", src)
    # The old int-equality comparator must be gone from this contract.
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


if __name__ == "__main__":
  unittest.main()
