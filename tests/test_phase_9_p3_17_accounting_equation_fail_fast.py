"""Phase 9 P3.17 — accounting equation hard fail-fast tests.

Covers the new assert_post_intake_accounting_equation() in
post_intake_fail_fast: passes on a balanced synthetic FINMO,
fires with a named diagnostic on synthetic violation, respects
the $1 tolerance, runs only on live Q1-Q20 (ignores Q0 stub).
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYTHON_DIR = _REPO_ROOT / "python"
if str(_PYTHON_DIR) not in sys.path:
  sys.path.insert(0, str(_PYTHON_DIR))


def _balanced_row(q: int, *, lease: float = 0.0) -> dict:
  """Synthetic FINMO row where A == L+E by construction. With
  optional lease, ROU asset offsets the capital lease obligation."""
  return {
    "quarter_index": q,
    "cash": 100000.0,
    "accounts_receivable": 20000.0,
    "inventory": 10000.0,
    "prepaid_expenses": 0.0,
    "ppe": 50000.0,
    "right_of_use_asset": lease,
    "accounts_payable": 12000.0,
    "short_term_debt": 8000.0,
    "deferred_revenue": 0.0,
    "long_term_debt": 30000.0,
    "capital_lease_obligation": lease,
    "owners_capital": 100000.0,
    "retained_earnings": 30000.0,
    "other_equity": 0.0,
    # Stored totals included for completeness; the new check
    # ignores them and recomputes from components.
    "total_assets": 180000.0 + lease,
    "total_liabilities": 50000.0 + lease,
    "total_equity": 130000.0,
    "total_liabilities_and_equity": 180000.0 + lease,
  }


def _enable_test_mode() -> None:
  os.environ["CONVERGENCE_TEST_MODE"] = "true"


def _disable_test_mode() -> None:
  os.environ.pop("CONVERGENCE_TEST_MODE", None)


class AccountingEquationFailFastTests(unittest.TestCase):
  def setUp(self) -> None:
    _enable_test_mode()

  def tearDown(self) -> None:
    _disable_test_mode()

  def _stage(self) -> str:
    # Use a finalize stage so post_intake_fail_fast_raise raises
    # FailFastError (rather than silently returning a result dict
    # outside finalize stages).
    return "post_intake_finalize_validation_accounting_equation"

  def test_balanced_synthetic_passes(self) -> None:
    from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (
      assert_post_intake_accounting_equation,
    )

    finmo = {"quarter_rows": [_balanced_row(q) for q in range(1, 21)]}
    # Should not raise.
    assert_post_intake_accounting_equation(finmo_json=finmo, stage=self._stage())

  def test_balanced_with_capital_lease_passes(self) -> None:
    from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (
      assert_post_intake_accounting_equation,
    )

    finmo = {"quarter_rows": [_balanced_row(q, lease=54000.0) for q in range(1, 21)]}
    assert_post_intake_accounting_equation(finmo_json=finmo, stage=self._stage())

  def test_violation_at_q5_fires_with_diagnostic(self) -> None:
    from client_intake_and_finmo.fail_fast.common import FailFastError
    from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (
      assert_post_intake_accounting_equation,
    )

    rows = [_balanced_row(q) for q in range(1, 21)]
    # Q5 (index 4 in the rows list because rows start at q=1): break A by adding $1000 to cash without offsetting on L+E
    rows[4]["cash"] = rows[4]["cash"] + 1000.0
    finmo = {"quarter_rows": rows}
    with self.assertRaises(FailFastError) as ctx:
      assert_post_intake_accounting_equation(finmo_json=finmo, stage=self._stage())
    err = ctx.exception
    self.assertEqual(err.code, "accounting_equation_violation")
    # Diagnostic should name Q5 with magnitude ~1000
    violations = err.details.get("violations", [])
    self.assertTrue(any(v.get("quarter_index") == 5 for v in violations))
    largest = err.details.get("largest")
    self.assertIsNotNone(largest)
    self.assertEqual(largest["quarter_index"], 5)
    self.assertAlmostEqual(abs(largest["diff"]), 1000.0, places=2)

  def test_drift_within_tolerance_passes(self) -> None:
    from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (
      assert_post_intake_accounting_equation,
    )

    rows = [_balanced_row(q) for q in range(1, 21)]
    rows[2]["cash"] = rows[2]["cash"] + 0.50  # $0.50 drift at Q3
    finmo = {"quarter_rows": rows}
    # Should not raise — within $1 tolerance.
    assert_post_intake_accounting_equation(finmo_json=finmo, stage=self._stage())

  def test_drift_above_tolerance_fires(self) -> None:
    from client_intake_and_finmo.fail_fast.common import FailFastError
    from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (
      assert_post_intake_accounting_equation,
    )

    rows = [_balanced_row(q) for q in range(1, 21)]
    rows[2]["cash"] = rows[2]["cash"] + 2.0  # $2 drift at Q3
    finmo = {"quarter_rows": rows}
    with self.assertRaises(FailFastError):
      assert_post_intake_accounting_equation(finmo_json=finmo, stage=self._stage())

  def test_q0_stub_is_not_checked(self) -> None:
    """Q0 is the intake stub period and is excluded from the check
    per iter P3.17 §"PHASE 2" (the check covers Q1 through Q20 only).
    """
    from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (
      assert_post_intake_accounting_equation,
    )

    # Q0 row with deliberate violation, Q1-Q20 balanced.
    q0 = _balanced_row(0)
    q0["cash"] = q0["cash"] + 99999.0  # huge violation at Q0
    rows = [q0] + [_balanced_row(q) for q in range(1, 21)]
    finmo = {"quarter_rows": rows}
    # Should NOT raise — Q0 is excluded from the live-quarter check.
    assert_post_intake_accounting_equation(finmo_json=finmo, stage=self._stage())

  def test_multiple_quarter_violations_reported_with_largest(self) -> None:
    from client_intake_and_finmo.fail_fast.common import FailFastError
    from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (
      assert_post_intake_accounting_equation,
    )

    rows = [_balanced_row(q) for q in range(1, 21)]
    rows[2]["cash"] += 5.0   # Q3 +5
    rows[7]["cash"] += 50.0  # Q8 +50
    rows[14]["cash"] += 12.0 # Q15 +12
    finmo = {"quarter_rows": rows}
    with self.assertRaises(FailFastError) as ctx:
      assert_post_intake_accounting_equation(finmo_json=finmo, stage=self._stage())
    err = ctx.exception
    violations = err.details.get("violations", [])
    affected = {v["quarter_index"] for v in violations}
    self.assertEqual(affected, {3, 8, 15})
    self.assertEqual(err.details["largest"]["quarter_index"], 8)


class StoredTotalsMatchComponentsTests(unittest.TestCase):
  """Phase 9 P3.17 Phase 3b — companion fail-fast verifying that
  stored aggregate totals (total_assets, total_liabilities,
  total_equity) match the sum of their displayed component rows
  at every quarter Q0-Q20. Q0 is INCLUDED here because that is
  where the lease-stub-overwrite bug class lives.
  """

  def setUp(self) -> None:
    _enable_test_mode()

  def tearDown(self) -> None:
    _disable_test_mode()

  def _stage(self) -> str:
    return "post_intake_finalize_validation_stored_totals_match_components"

  def _balanced_row_with_stored(self, q: int, *, lease: float = 0.0) -> dict:
    row = _balanced_row(q, lease=lease)
    # Ensure stored totals reflect the component sums by construction.
    asset_sum = (
      row["cash"] + row["accounts_receivable"] + row["inventory"]
      + row["prepaid_expenses"] + row["ppe"] + row["right_of_use_asset"]
    )
    liab_sum = (
      row["accounts_payable"] + row["short_term_debt"]
      + row["deferred_revenue"] + row["long_term_debt"]
      + row["capital_lease_obligation"]
    )
    eq_sum = row["owners_capital"] + row["retained_earnings"] + row["other_equity"]
    row["total_assets"] = asset_sum
    row["total_liabilities"] = liab_sum
    row["total_equity"] = eq_sum
    row["total_liabilities_and_equity"] = liab_sum + eq_sum
    return row

  def test_balanced_synthetic_with_consistent_stored_totals_passes(self) -> None:
    from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (
      assert_post_intake_stored_totals_match_components,
    )

    rows = [self._balanced_row_with_stored(q) for q in range(0, 21)]
    finmo = {"quarter_rows": rows}
    assert_post_intake_stored_totals_match_components(finmo_json=finmo, stage=self._stage())

  def test_lease_present_with_consistent_stored_totals_passes(self) -> None:
    """The Q0 case that Phase 3 fixed — ROU on assets, lease on
    liabilities, stored totals reflect both."""
    from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (
      assert_post_intake_stored_totals_match_components,
    )

    rows = [self._balanced_row_with_stored(q, lease=54000.0) for q in range(0, 21)]
    finmo = {"quarter_rows": rows}
    assert_post_intake_stored_totals_match_components(finmo_json=finmo, stage=self._stage())

  def test_q0_stored_assets_missing_lease_fires(self) -> None:
    """Reproduces the exact pre-Phase-3 Q0 bug: stored total_assets
    drops the $54K ROU while the row-level right_of_use_asset
    field has it. New fail-fast catches it."""
    from client_intake_and_finmo.fail_fast.common import FailFastError
    from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (
      assert_post_intake_stored_totals_match_components,
    )

    rows = [self._balanced_row_with_stored(q, lease=54000.0) for q in range(0, 21)]
    # Pre-Phase-3 Q0 behavior: subtract lease from stored totals only
    rows[0]["total_assets"] -= 54000.0
    rows[0]["total_liabilities"] -= 54000.0
    rows[0]["total_liabilities_and_equity"] -= 54000.0
    finmo = {"quarter_rows": rows}
    with self.assertRaises(FailFastError) as ctx:
      assert_post_intake_stored_totals_match_components(finmo_json=finmo, stage=self._stage())
    err = ctx.exception
    self.assertEqual(err.code, "stored_totals_match_components_violation")
    violations = err.details.get("violations", [])
    affected_pairs = {(v["quarter_index"], v["total"]) for v in violations}
    self.assertIn((0, "assets"), affected_pairs)
    self.assertIn((0, "liabilities"), affected_pairs)
    largest = err.details["largest"]
    self.assertEqual(largest["quarter_index"], 0)
    self.assertAlmostEqual(abs(largest["diff"]), 54000.0, places=2)

  def test_stored_total_assets_off_at_quarter_fires(self) -> None:
    from client_intake_and_finmo.fail_fast.common import FailFastError
    from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (
      assert_post_intake_stored_totals_match_components,
    )

    rows = [self._balanced_row_with_stored(q) for q in range(0, 21)]
    rows[5]["total_assets"] += 5.0  # Q5 stored asset off by $5
    finmo = {"quarter_rows": rows}
    with self.assertRaises(FailFastError) as ctx:
      assert_post_intake_stored_totals_match_components(finmo_json=finmo, stage=self._stage())
    err = ctx.exception
    violations = err.details.get("violations", [])
    affected = {(v["quarter_index"], v["total"]) for v in violations}
    self.assertIn((5, "assets"), affected)

  def test_stored_total_liabilities_off_at_quarter_fires(self) -> None:
    from client_intake_and_finmo.fail_fast.common import FailFastError
    from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (
      assert_post_intake_stored_totals_match_components,
    )

    rows = [self._balanced_row_with_stored(q) for q in range(0, 21)]
    rows[3]["total_liabilities"] += 5.0  # Q3
    finmo = {"quarter_rows": rows}
    with self.assertRaises(FailFastError) as ctx:
      assert_post_intake_stored_totals_match_components(finmo_json=finmo, stage=self._stage())
    err = ctx.exception
    affected = {(v["quarter_index"], v["total"]) for v in err.details["violations"]}
    self.assertIn((3, "liabilities"), affected)

  def test_stored_total_equity_off_at_quarter_fires(self) -> None:
    from client_intake_and_finmo.fail_fast.common import FailFastError
    from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (
      assert_post_intake_stored_totals_match_components,
    )

    rows = [self._balanced_row_with_stored(q) for q in range(0, 21)]
    rows[10]["total_equity"] += 5.0  # Q10
    finmo = {"quarter_rows": rows}
    with self.assertRaises(FailFastError) as ctx:
      assert_post_intake_stored_totals_match_components(finmo_json=finmo, stage=self._stage())
    err = ctx.exception
    affected = {(v["quarter_index"], v["total"]) for v in err.details["violations"]}
    self.assertIn((10, "equity"), affected)

  def test_drift_within_tolerance_passes(self) -> None:
    from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (
      assert_post_intake_stored_totals_match_components,
    )

    rows = [self._balanced_row_with_stored(q) for q in range(0, 21)]
    rows[2]["total_assets"] += 0.50  # $0.50 drift
    finmo = {"quarter_rows": rows}
    assert_post_intake_stored_totals_match_components(finmo_json=finmo, stage=self._stage())

  def test_multi_quarter_violations_reported_with_largest(self) -> None:
    """All violating quarter/total triples are reported; ``largest``
    names the one with the biggest absolute diff."""
    from client_intake_and_finmo.fail_fast.common import FailFastError
    from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (
      assert_post_intake_stored_totals_match_components,
    )

    rows = [self._balanced_row_with_stored(q) for q in range(0, 21)]
    rows[2]["total_assets"] += 5.0    # Q2 assets +5
    rows[7]["total_liabilities"] += 75.0  # Q7 liab +75 (largest)
    rows[14]["total_equity"] += 20.0  # Q14 equity +20
    finmo = {"quarter_rows": rows}
    with self.assertRaises(FailFastError) as ctx:
      assert_post_intake_stored_totals_match_components(finmo_json=finmo, stage=self._stage())
    err = ctx.exception
    violations = err.details.get("violations", [])
    affected = {(v["quarter_index"], v["total"]) for v in violations}
    self.assertEqual(affected, {(2, "assets"), (7, "liabilities"), (14, "equity")})
    self.assertEqual(err.details["largest"]["quarter_index"], 7)
    self.assertEqual(err.details["largest"]["total"], "liabilities")


if __name__ == "__main__":
  unittest.main()
