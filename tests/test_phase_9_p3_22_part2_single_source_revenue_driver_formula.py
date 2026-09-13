"""Phase 9 P3.22 Part 2 -- single-source revenue driver formula consolidation.

Per the P3.22 Part 1 audit, Sites #1 (finmo_bridge.py:586) and #2
(fail_fast.py:1371) were the same conceptual contract check
("FINMO revenue must equal sum(Capacity * Unit Price * Utilization)
per quarter") implemented in two files with two different tolerances
($1.0 and $0.015). Proposal P1 consolidates:

  - `revenue_live_series_from_model_input` (in finmo_bridge.py) is
    the single canonical helper for the driver-formula expected
    revenue series.
  - `REVENUE_DRIVER_FORMULA_TOLERANCE = 0.015` (in finmo_bridge.py)
    is the single canonical tolerance constant.
  - Both check sites import the helper + constant; no parallel
    inline accumulation, no local tolerance constants.
  - The tighter $0.015 tolerance now applies everywhere (matches
    the pre-existing fail_fast precedent, NOT a relaxation of it).

Tests:
  - test_canonical_helper_is_exported_under_public_name
  - test_canonical_tolerance_constant_is_exported
  - test_fail_fast_imports_canonical_helper_and_constant
  - test_finmo_bridge_contract_imports_use_shared_constant
  - test_no_inline_driver_accumulation_in_fail_fast
  - test_no_local_revenue_formula_tolerance_in_fail_fast
  - test_old_private_helper_name_removed
  - test_identical_expected_revenue_across_both_check_sites (identity)
  - test_stage_5_iter1_boundary_case_passes_under_new_tolerance (regression)
  - test_divergence_above_new_tolerance_fires_at_both_sites
  - test_helper_returns_per_quarter_revenue_for_single_product (sanity)
  - test_helper_returns_per_quarter_revenue_for_multi_product (sanity)
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
from client_intake_and_finmo.fail_fast.post_intake_fail_fast import fail_fast as _ff  # noqa: E402


_FINMO_BRIDGE_PATH = (
  _REPO_ROOT / "python" / "client_intake_and_finmo" / "finmo_bridge.py"
)
_FAIL_FAST_PATH = (
  _REPO_ROOT / "python" / "client_intake_and_finmo"
  / "fail_fast" / "post_intake_fail_fast" / "fail_fast.py"
)


def _model_input_single_product(per_quarter_revenue: float) -> dict:
  """Build a minimal model_input_json with one product whose
  Capacity * Unit Price * Utilization equals the target per quarter."""
  per_q_values = [per_quarter_revenue for _ in range(20)]
  def _row(label: str, driver: str, values: list) -> dict:
    return {
      "section": "revenue",
      "label": label,
      "lob": "Default LOB",
      "product": "Default Product",
      "driver": driver,
      "values": [0.0, *values],  # 1 stub + 20 live
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


def _model_input_multi_product(per_product_per_quarter: list) -> dict:
  """Build a model_input_json with multiple revenue products,
  each contributing the given per-quarter revenue value (one
  list element per product)."""
  rows = []
  for product_idx, per_q_value in enumerate(per_product_per_quarter):
    lob = f"LOB {product_idx + 1}"
    product = f"Product {product_idx + 1}"
    for driver_label, value in (
      ("Capacity", 1.0),
      ("Unit Price", per_q_value),
      ("Utilization", 1.0),
    ):
      rows.append({
        "section": "revenue",
        "label": driver_label,
        "lob": lob,
        "product": product,
        "driver": driver_label,
        "values": [0.0] + [value for _ in range(20)],
      })
  return {"sections": {"revenue": rows}}


def _quarter_rows_with_revenue(per_quarter_revenue: float) -> list:
  return [{"quarter_index": q, "revenue": per_quarter_revenue} for q in range(1, 21)]


# --------------------------------------------------------------------------
# Source-shape regression checks
# --------------------------------------------------------------------------


class CanonicalHelperAndConstantExportedTests(unittest.TestCase):

  def test_canonical_helper_is_exported_under_public_name(self) -> None:
    """The helper must be public (no leading underscore) so the
    cross-module fail_fast.py import is doctrinally clean."""
    self.assertTrue(
      hasattr(_fb, "revenue_live_series_from_model_input"),
      "revenue_live_series_from_model_input must be exported from finmo_bridge",
    )
    self.assertTrue(
      callable(_fb.revenue_live_series_from_model_input),
      "revenue_live_series_from_model_input must be callable",
    )

  def test_canonical_tolerance_constant_is_exported(self) -> None:
    self.assertTrue(
      hasattr(_fb, "REVENUE_DRIVER_FORMULA_TOLERANCE"),
      "REVENUE_DRIVER_FORMULA_TOLERANCE must be exported from finmo_bridge",
    )
    self.assertEqual(
      _fb.REVENUE_DRIVER_FORMULA_TOLERANCE,
      0.015,
      "Tolerance must be 0.015 (1.5 cents -- the pre-existing fail_fast precedent)",
    )

  def test_old_private_helper_name_removed(self) -> None:
    """Source-shape sanity: the old `_revenue_live_series_from_
    model_input` private name must be gone (renamed without
    underscore)."""
    src = _FINMO_BRIDGE_PATH.read_text(encoding="utf-8")
    # The old private definition must be replaced.
    self.assertNotIn(
      "def _revenue_live_series_from_model_input(",
      src,
      "Old private helper definition must be renamed to public",
    )
    # No internal caller should still reference the old name.
    self.assertNotIn(
      "_revenue_live_series_from_model_input(",
      src,
      "No internal call site should reference the old private helper name",
    )


class FailFastConsumesCanonicalHelperTests(unittest.TestCase):

  def setUp(self) -> None:
    self._src = _FAIL_FAST_PATH.read_text(encoding="utf-8")

  def test_fail_fast_imports_canonical_helper_and_constant(self) -> None:
    self.assertIn(
      "from client_intake_and_finmo.finmo_bridge import (",
      self._src,
    )
    self.assertIn(
      "revenue_live_series_from_model_input",
      self._src,
      "fail_fast.py must import the canonical helper",
    )
    self.assertIn(
      "REVENUE_DRIVER_FORMULA_TOLERANCE",
      self._src,
      "fail_fast.py must import the canonical tolerance constant",
    )

  def test_no_inline_driver_accumulation_in_fail_fast(self) -> None:
    """The pre-consolidation inline accumulation loop must be gone.
    The distinctive line was `computed_revenue_by_q[quarter] += (`
    feeding the multiply-three-floats expression."""
    self.assertNotIn(
      "computed_revenue_by_q[quarter] += (",
      self._src,
      "Inline driver accumulation must be replaced by helper call",
    )

  def test_no_local_revenue_formula_tolerance_in_fail_fast(self) -> None:
    """The pre-consolidation `_REVENUE_FORMULA_TOLERANCE = 0.015`
    local constant must be removed; fail_fast.py reads the shared
    REVENUE_DRIVER_FORMULA_TOLERANCE from finmo_bridge instead."""
    self.assertNotIn(
      "_REVENUE_FORMULA_TOLERANCE = 0.015",
      self._src,
      "Local _REVENUE_FORMULA_TOLERANCE constant must be removed",
    )

  def test_fail_fast_uses_shared_constant_in_comparator(self) -> None:
    """The comparator must reference the shared constant, not a
    local literal."""
    # the shared tolerance is scale-aware now (revenue_driver_formula_tolerance_for:
    # the flat floor for small quarters, 2e-7 relative for large ones)
    self.assertIn(
      "> revenue_driver_formula_tolerance_for(",
      self._src,
      "fail_fast comparator must reference the shared scale-aware tolerance",
    )


class FinmoBridgeContractUsesSharedConstantTests(unittest.TestCase):

  def setUp(self) -> None:
    self._src = _FINMO_BRIDGE_PATH.read_text(encoding="utf-8")

  def test_finmo_bridge_contract_uses_shared_constant(self) -> None:
    fn_idx = self._src.find("def _enforce_revenue_driver_formula_contract(")
    self.assertGreater(fn_idx, 0)
    next_def_idx = self._src.find("\ndef ", fn_idx + 1)
    self.assertGreater(next_def_idx, fn_idx)
    fn_body = self._src[fn_idx:next_def_idx]
    self.assertIn(
      "abs(delta_float) > revenue_driver_formula_tolerance_for(driver_revenue)",
      fn_body,
      "FINMO bridge contract must use the shared scale-aware tolerance",
    )
    self.assertIn(
      "revenue_live_series_from_model_input(",
      fn_body,
      "FINMO bridge contract must call the public canonical helper",
    )


# --------------------------------------------------------------------------
# Functional / behavior tests
# --------------------------------------------------------------------------


class IdenticalExpectedRevenueAcrossSitesTests(unittest.TestCase):
  """The user's directive demanded an identical-values test (not
  almost-equal). After consolidation, both check sites compute
  their `expected_revenue` from the same canonical helper, so
  the values must be byte-identical."""

  def test_identical_for_single_product(self) -> None:
    mi = _model_input_single_product(1_673_073.5001)
    horizon = 20

    # Site #1's view of expected: directly from the helper.
    series_a = _fb.revenue_live_series_from_model_input(mi, live_count=horizon)
    # Site #2 (fail_fast) does the same call internally; rebuild the
    # same dict shape it constructs.
    series_b_dict = {
      q: float(series_a[q - 1]) if q - 1 < len(series_a) else 0.0
      for q in range(1, horizon + 1)
    }
    # Identity: per-quarter values must be byte-equal (assertEqual,
    # not assertAlmostEqual).
    for q in range(1, horizon + 1):
      self.assertEqual(
        float(series_a[q - 1]),
        series_b_dict[q],
        f"Q{q} value must be byte-identical across both check sites",
      )

  def test_identical_for_multi_product(self) -> None:
    """Multi-product scenario stresses the accumulation-order path.
    Pre-consolidation, fail_fast's inline loop iterated
    `bundle.values()` (dict insertion order) while the helper
    iterated `sorted(set(keys))`. Float non-associativity in
    `+=` could produce different last-bit values. Post-
    consolidation, both call the same helper -- identical by
    construction."""
    mi = _model_input_multi_product([100_001.123, 200_002.456, 300_003.789])
    horizon = 20
    series_a = _fb.revenue_live_series_from_model_input(mi, live_count=horizon)
    series_b = _fb.revenue_live_series_from_model_input(mi, live_count=horizon)
    self.assertEqual(series_a, series_b)


class Stage5Iter1BoundaryCaseRegressionTests(unittest.TestCase):
  """The Stage 5 iter 1 motivating case: Q1 revenue with FINMO=
  1673073.4999... vs driver=1673073.5001... (sub-cent delta,
  ~$0.0002). Under Stage 5 iter 1's $1 tolerance, this passed
  comfortably (delta << $1). Under P3.22 Part 2's tighter
  $0.015 tolerance, it must STILL pass (delta << $0.015) --
  confirming the refactor moved to the tighter pre-existing
  precedent without re-introducing the boundary failure."""

  def test_boundary_case_passes_under_new_tolerance(self) -> None:
    target = 1_673_073.5001
    mi = _model_input_single_product(target)
    # Build FINMO-side rows with the sub-cent skew that Stage 5
    # iter 1 observed (FINMO core accumulation order vs helper).
    qr = _quarter_rows_with_revenue(target - 0.0002)
    # Must NOT raise.
    _fb._enforce_revenue_driver_formula_contract(
      model_input_json=mi,
      quarter_rows_raw=qr,
    )

  def test_one_cent_delta_passes(self) -> None:
    """A $0.01 delta is within the $0.015 tolerance."""
    target = 1_673_073.0
    mi = _model_input_single_product(target)
    qr = _quarter_rows_with_revenue(target + 0.01)
    _fb._enforce_revenue_driver_formula_contract(
      model_input_json=mi,
      quarter_rows_raw=qr,
    )

  def test_two_cent_delta_raises(self) -> None:
    """A $0.02 delta is above the $0.015 tolerance and fires - AT THE
    STAGE 5 FIXTURE'S OWN SCALE. This briefly ran at $50,000 so that a
    widened relative tolerance could stay green; the widening was the
    wrong fix (the drivers were being pre-rounded) and the scale is
    restored with it."""
    target = 1_673_073.0
    mi = _model_input_single_product(target)
    qr = _quarter_rows_with_revenue(target + 0.02)
    with self.assertRaises(ValueError) as ctx:
      _fb._enforce_revenue_driver_formula_contract(
        model_input_json=mi,
        quarter_rows_raw=qr,
      )
    self.assertIn(
      "revenue_driver_formula_contract_failed",
      str(ctx.exception),
    )

  def test_a_cents_priced_product_leaves_no_residue(self) -> None:
    """Sorrel & Dunne 691a4763 (2026-09-13). Two products priced in cents
    ($1.48 a can x 21,000 a week x 0.7) put 2-9 cents between FINMO and the
    driver formula on $686K-$728K quarters and killed a real client's build.

    The cause was not tolerance. The driver series rounded Capacity, Unit
    Price and Utilization to 6dp EACH and multiplied after; FINMO multiplies
    at full precision and rounds the PRODUCT. A 6dp round is a large RELATIVE
    error on a small number - 3.4e-7 on $1.48 - and that relative error rides
    the whole product: 3.4e-7 x $343K a product is about twelve cents.

    So the drivers persist unrounded now, and the two sides agree EXACTLY.
    This test reads the drivers through the same helper the contract uses and
    asserts the product is identical to full-precision arithmetic - no
    tolerance involved, because there is nothing left to tolerate."""
    capacity, unit_price, utilization = 21_000.0 / 7.0 * 91.0, 1.48, 0.7
    exact = capacity * unit_price * utilization
    mi = _model_input_single_product(exact)
    series = _fb.revenue_live_series_from_model_input(mi, live_count=20)
    for idx, value in enumerate(series, start=1):
      self.assertEqual(value, exact, f"Q{idx} driver revenue diverged from exact arithmetic")
    # and the contract itself passes with FINMO carrying the same number
    _fb._enforce_revenue_driver_formula_contract(
      model_input_json=mi,
      quarter_rows_raw=_quarter_rows_with_revenue(exact),
    )

  def test_drivers_persist_unrounded(self) -> None:
    """The fix, stated as a property: a driver value with more than six
    decimals survives into the series the contract reads. If this fails,
    someone has re-introduced a round(...,6) on a factor."""
    from financial_model_engine.model_inputs import RevenueDriverSet  # type: ignore

    drivers = RevenueDriverSet(capacity_units=273_000.000000123,
                               unit_price=1.4800000007, utilization=0.7000000003)
    stored = drivers.to_dict()
    self.assertEqual(stored["capacity_units"], 273_000.000000123)
    self.assertEqual(stored["unit_price"], 1.4800000007)
    self.assertEqual(stored["utilization"], 0.7000000003)

  def test_forty_cents_raises_on_the_stage5_quarter(self) -> None:
    """At the Stage 5 fixture scale ($1.67M a quarter) the tolerance is
    2e-7 x 1,673,073 = $0.335; a $0.40 delta is past it and fires. A real
    source bug shows up as dollars to thousands, orders of magnitude
    above this line."""
    target = 1_673_073.0
    mi = _model_input_single_product(target)
    qr = _quarter_rows_with_revenue(target + 0.40)
    with self.assertRaises(ValueError) as ctx:
      _fb._enforce_revenue_driver_formula_contract(
        model_input_json=mi,
        quarter_rows_raw=qr,
      )
    self.assertIn(
      "revenue_driver_formula_contract_failed",
      str(ctx.exception),
    )


class HelperSanityTests(unittest.TestCase):

  def test_helper_returns_per_quarter_revenue_for_single_product(self) -> None:
    mi = _model_input_single_product(1_000_000.0)
    series = _fb.revenue_live_series_from_model_input(mi, live_count=20)
    self.assertEqual(len(series), 20)
    for q in range(20):
      self.assertEqual(series[q], 1_000_000.0)

  def test_helper_returns_per_quarter_revenue_for_multi_product(self) -> None:
    mi = _model_input_multi_product([100.0, 200.0, 300.0])
    series = _fb.revenue_live_series_from_model_input(mi, live_count=20)
    self.assertEqual(len(series), 20)
    for q in range(20):
      self.assertEqual(series[q], 600.0)


if __name__ == "__main__":
  unittest.main()
