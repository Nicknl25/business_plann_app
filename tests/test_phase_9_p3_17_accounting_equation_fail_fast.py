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


if __name__ == "__main__":
  unittest.main()
