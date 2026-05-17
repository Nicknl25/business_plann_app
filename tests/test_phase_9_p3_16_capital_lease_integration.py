"""Phase 9 P3.16 — capital lease integration tests.

Coverage:
  - Builder math: clean amortization, declining-balance interest,
    20-quarter straight-line depreciation
  - Builder edge: no-lease business produces inert schedule
  - Snapshot agrees with FINMO output
  - Type 1 validators fire on synthetic violations
  - Type 2 machinery fail-fasts fire on synthetic malfunctions
  - FINMO ROU + lease interest + lease depreciation wiring
  - BS reconciliation invariant preserved
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYTHON_DIR = _REPO_ROOT / "python"
if str(_PYTHON_DIR) not in sys.path:
  sys.path.insert(0, str(_PYTHON_DIR))


class CapitalLeaseBuilderTests(unittest.TestCase):
  def test_builder_amortizes_cleanly_with_interest_and_straight_line_depreciation(self) -> None:
    from client_intake_and_finmo.post_intake_capital_lease import (
      CAPITAL_LEASE_DEPRECIATION_QUARTERS,
      build_capital_lease_schedule,
    )

    opening = 20000.0
    # Pay $1000/quarter principal — lease pays off in 20 quarters.
    payments = [1000.0 for _ in range(CAPITAL_LEASE_DEPRECIATION_QUARTERS)]
    rate = 0.025  # quarterly
    payload = build_capital_lease_schedule(
      opening_balance=opening,
      principal_payments_per_quarter=payments,
      interest_rate=rate,
    )
    self.assertEqual(payload["status"], "ready")
    self.assertEqual(payload["opening_balance_seed"], 20000)
    self.assertEqual(payload["horizon_quarters"], 20)
    rows = payload["rows"]
    self.assertEqual(len(rows), 20)
    # Q1: opening = 20000, principal = 1000, interest = 20000 * 0.025 = 500, closing = 19000
    self.assertEqual(rows[0]["opening_balance"], 20000)
    self.assertEqual(rows[0]["principal_payment"], 1000)
    self.assertEqual(rows[0]["interest_payment"], 500)
    self.assertEqual(rows[0]["closing_balance"], 19000)
    # ROU: Q1 closing = 20000 - 20000/20 = 19000
    self.assertEqual(rows[0]["rou_asset_closing"], 19000)
    # Q20: closing balance reaches 0, ROU closing reaches 0
    self.assertEqual(rows[19]["closing_balance"], 0)
    self.assertEqual(rows[19]["rou_asset_closing"], 0)

  def test_builder_clips_principal_to_remaining_balance(self) -> None:
    from client_intake_and_finmo.post_intake_capital_lease import build_capital_lease_schedule

    # Opening 5000, requested principal $10000 in Q1 — must clip to 5000.
    payload = build_capital_lease_schedule(
      opening_balance=5000.0,
      principal_payments_per_quarter=[10000.0] + [0.0 for _ in range(19)],
      interest_rate=0.025,
    )
    rows = payload["rows"]
    self.assertEqual(rows[0]["principal_payment"], 5000)
    self.assertEqual(rows[0]["closing_balance"], 0)
    # Q2 onward: opening = 0, no further principal needed
    self.assertEqual(rows[1]["opening_balance"], 0)
    self.assertEqual(rows[1]["principal_payment"], 0)

  def test_builder_with_zero_opening_returns_skipped(self) -> None:
    from client_intake_and_finmo.post_intake_capital_lease import build_capital_lease_schedule

    payload = build_capital_lease_schedule(
      opening_balance=0.0,
      principal_payments_per_quarter=[0.0 for _ in range(20)],
      interest_rate=0.025,
    )
    self.assertEqual(payload["status"], "skipped_no_lease")
    self.assertEqual(payload["opening_balance_seed"], 0)
    for row in payload["rows"]:
      self.assertEqual(row["opening_balance"], 0)
      self.assertEqual(row["closing_balance"], 0)
      self.assertEqual(row["interest_payment"], 0)
      self.assertEqual(row["rou_asset_closing"], 0)

  def test_lease_obligation_pays_off_before_rou_fully_depreciates(self) -> None:
    """North Ridge case from iter spec: $54K, paid off by Q4.
    ROU continues to depreciate over the full 20 quarters."""
    from client_intake_and_finmo.post_intake_capital_lease import build_capital_lease_schedule

    payload = build_capital_lease_schedule(
      opening_balance=54000.0,
      principal_payments_per_quarter=[15000.0] * 4 + [0.0] * 16,
      interest_rate=0.025,
    )
    rows = payload["rows"]
    # Lease obligation: 54k → 39k → 24k → 9k → 0 (Q4 clipped to 9k payment)
    self.assertEqual(rows[3]["closing_balance"], 0)
    # ROU: 54k → 51.3k → 48.6k → 45.9k → 43.2k (continues depreciating)
    expected_rou_q4 = round(54000 * (20 - 4) / 20)
    self.assertEqual(rows[3]["rou_asset_closing"], expected_rou_q4)
    # ROU reaches 0 at Q20
    self.assertEqual(rows[19]["rou_asset_closing"], 0)


class CapitalLeaseValidatorTests(unittest.TestCase):
  def _ok_payload(self) -> dict:
    from client_intake_and_finmo.post_intake_capital_lease import build_capital_lease_schedule

    return build_capital_lease_schedule(
      opening_balance=20000.0,
      principal_payments_per_quarter=[1000.0 for _ in range(20)],
      interest_rate=0.025,
    )

  def _ok_model_input(self) -> dict:
    return {
      "sections": {
        "schedules": {
          "lease_opening_balance_seed": 20000.0,
          "rows": [],
        },
      },
    }

  def test_validator_passes_on_clean_payload(self) -> None:
    from client_intake_and_finmo.post_intake_capital_lease import validate_capital_lease_schedule_payload

    violations = validate_capital_lease_schedule_payload(
      capital_lease_schedule=self._ok_payload(),
      model_input_json=self._ok_model_input(),
    )
    self.assertEqual(violations, [])

  def test_validator_detects_obligation_at_q0_mismatch(self) -> None:
    from client_intake_and_finmo.post_intake_capital_lease import validate_capital_lease_schedule_payload

    payload = self._ok_payload()
    payload["rows"][0]["opening_balance"] = 99999  # synthetic violation
    violations = validate_capital_lease_schedule_payload(
      capital_lease_schedule=payload,
      model_input_json=self._ok_model_input(),
    )
    reasons = {v.get("reason") for v in violations}
    self.assertIn("capital_lease_obligation_at_q0", reasons)

  def test_validator_detects_asset_at_q0_mismatch(self) -> None:
    from client_intake_and_finmo.post_intake_capital_lease import validate_capital_lease_schedule_payload

    payload = self._ok_payload()
    payload["rows"][0]["rou_asset_opening"] = 99999
    violations = validate_capital_lease_schedule_payload(
      capital_lease_schedule=payload,
      model_input_json=self._ok_model_input(),
    )
    reasons = {v.get("reason") for v in violations}
    self.assertIn("capital_lease_asset_at_q0", reasons)

  def test_validator_detects_amortization_mismatch(self) -> None:
    from client_intake_and_finmo.post_intake_capital_lease import validate_capital_lease_schedule_payload

    payload = self._ok_payload()
    payload["rows"][5]["closing_balance"] = payload["rows"][5]["opening_balance"]  # didn't apply principal
    violations = validate_capital_lease_schedule_payload(
      capital_lease_schedule=payload,
      model_input_json=self._ok_model_input(),
    )
    reasons = {v.get("reason") for v in violations}
    self.assertIn("capital_lease_obligation_amortizes_correctly", reasons)

  def test_validator_detects_interest_rate_mismatch(self) -> None:
    from client_intake_and_finmo.post_intake_capital_lease import validate_capital_lease_schedule_payload

    payload = self._ok_payload()
    payload["rows"][3]["interest_payment"] = 99999
    violations = validate_capital_lease_schedule_payload(
      capital_lease_schedule=payload,
      model_input_json=self._ok_model_input(),
    )
    reasons = {v.get("reason") for v in violations}
    self.assertIn("capital_lease_interest_at_sba_rate", reasons)

  def test_validator_detects_asset_depreciation_drift(self) -> None:
    from client_intake_and_finmo.post_intake_capital_lease import validate_capital_lease_schedule_payload

    payload = self._ok_payload()
    payload["rows"][2]["rou_asset_closing"] = 99999
    violations = validate_capital_lease_schedule_payload(
      capital_lease_schedule=payload,
      model_input_json=self._ok_model_input(),
    )
    reasons = {v.get("reason") for v in violations}
    self.assertIn("capital_lease_asset_depreciates_linearly", reasons)


class FinmoCapitalLeaseIntegrationTests(unittest.TestCase):
  def test_no_lease_business_unchanged_behavior(self) -> None:
    """Businesses without a capital lease produce identical FINMO
    output to pre-iter (modulo the new fields, all zero)."""
    from financial_model_engine.finmo_model import calculate_finmo_model
    from financial_model_engine.model_inputs import FinancialModelInputs

    book = FinancialModelInputs.empty(
      start_date="2026-09-03",
      business_name="NoLeaseBiz",
    )
    book.set_schedule_seed(debt_opening_balance_seed=10000.0)
    result = calculate_finmo_model(book)
    rows = result.quarter_rows(include_stub=True)
    # Q0 ROU = 0, capital_lease_obligation = 0
    self.assertEqual(rows[0]["right_of_use_asset"], 0.0)
    self.assertEqual(rows[0]["capital_lease_obligation"], 0.0)
    self.assertEqual(rows[0]["lease_interest_expense"], 0.0)
    self.assertEqual(rows[0]["lease_asset_depreciation_expense"], 0.0)
    # All quarters: no lease components
    for row in rows[1:]:
      self.assertEqual(row["right_of_use_asset"], 0.0)
      self.assertEqual(row["capital_lease_obligation"], 0.0)
      self.assertEqual(row["lease_interest_expense"], 0.0)
      self.assertEqual(row["lease_asset_depreciation_expense"], 0.0)
    # interest field equals debt-only interest (since lease = 0)
    for row in rows[1:]:
      self.assertAlmostEqual(row["interest"], row["debt_interest_expense"], places=4)

  def test_lease_bearing_business_produces_rou_and_interest(self) -> None:
    """Business with a capital lease has ROU asset = seed at Q0
    that depreciates over 20 quarters, plus lease interest expense
    that adds to the combined P&L interest line."""
    from financial_model_engine.finmo_model import calculate_finmo_model
    from financial_model_engine.model_inputs import FinancialModelInputs

    book = FinancialModelInputs.empty(
      start_date="2026-09-03",
      business_name="LeaseBiz",
    )
    book.set_schedule_seed(lease_opening_balance_seed=54000.0)
    book.set_expense_drivers(quarter_index=1, interest_rate=0.025)
    for q in range(2, 21):
      book.set_expense_drivers(quarter_index=q, interest_rate=0.025)
    result = calculate_finmo_model(book)
    rows = result.quarter_rows(include_stub=True)
    # Q0 stub: ROU = seed, capital_lease_obligation = seed
    self.assertAlmostEqual(rows[0]["right_of_use_asset"], 54000.0, places=4)
    self.assertAlmostEqual(rows[0]["capital_lease_obligation"], 54000.0, places=4)
    # Q1 ROU = 54000 - 54000/20 = 51300
    self.assertAlmostEqual(rows[1]["right_of_use_asset"], 51300.0, places=4)
    self.assertAlmostEqual(rows[1]["lease_asset_depreciation_expense"], 2700.0, places=4)
    # Q1 lease interest = 54000 * 0.025 = 1350
    self.assertAlmostEqual(rows[1]["lease_interest_expense"], 1350.0, places=4)
    # Combined depreciation includes lease portion
    self.assertAlmostEqual(
      rows[1]["depreciation"],
      rows[1]["ppe_depreciation_expense"] + rows[1]["lease_asset_depreciation_expense"],
      places=4,
    )
    # Combined interest includes lease portion
    self.assertAlmostEqual(
      rows[1]["interest"],
      rows[1]["debt_interest_expense"] + rows[1]["lease_interest_expense"],
      places=4,
    )

  def test_balance_sheet_reconciles_with_lease(self) -> None:
    """BS invariant: Assets == Liab + Equity at every quarter."""
    from financial_model_engine.finmo_model import calculate_finmo_model
    from financial_model_engine.model_inputs import FinancialModelInputs

    book = FinancialModelInputs.empty(
      start_date="2026-09-03",
      business_name="LeaseBSCheck",
    )
    book.set_schedule_seed(
      lease_opening_balance_seed=12000.0,
      debt_opening_balance_seed=5000.0,
    )
    book.set_expense_drivers(quarter_index=1, interest_rate=0.025, depreciation_percent=0.05)
    for q in range(2, 21):
      book.set_expense_drivers(quarter_index=q, interest_rate=0.025, depreciation_percent=0.05)
    result = calculate_finmo_model(book)
    rows = result.quarter_rows(include_stub=True)
    for row in rows:
      diff = abs(row["total_assets"] - row["total_liabilities_and_equity"])
      self.assertLess(
        diff,
        1.0,
        f"BS reconcile failed at q={row['quarter_index']}: assets={row['total_assets']} liab+eq={row['total_liabilities_and_equity']}",
      )

  def test_snapshot_agrees_with_finmo(self) -> None:
    """Mirror flavor 2 — snapshot reads FINMO and produces a
    parallel structure that should agree by construction."""
    from client_intake_and_finmo.post_intake_capital_lease import (
      build_capital_lease_schedule_snapshot,
      assert_finmo_matches_capital_lease_schedule,
    )
    from financial_model_engine.finmo_model import calculate_finmo_model
    from financial_model_engine.model_inputs import FinancialModelInputs

    book = FinancialModelInputs.empty(
      start_date="2026-09-03",
      business_name="SnapshotBiz",
    )
    book.set_schedule_seed(lease_opening_balance_seed=20000.0)
    book.set_expense_drivers(quarter_index=1, interest_rate=0.025)
    for q in range(2, 21):
      book.set_expense_drivers(quarter_index=q, interest_rate=0.025)
    finmo_result = calculate_finmo_model(book)
    finmo_payload = {"quarter_rows": finmo_result.quarter_rows(include_stub=True)}
    model_input_json = book.to_model_input_json()
    snapshot = build_capital_lease_schedule_snapshot(
      finmo_payload=finmo_payload,
      model_input_json=model_input_json,
    )
    # Should not raise
    assert_finmo_matches_capital_lease_schedule(
      capital_lease_schedule=snapshot,
      finmo_json=finmo_payload,
      stage="test_snapshot_finmo_reconcile",
    )


class CapitalLeaseMachineryFailFastTests(unittest.TestCase):
  def test_interest_components_fail_fast_fires_on_drift(self) -> None:
    from client_intake_and_finmo.fail_fast.common import FailFastError
    from client_intake_and_finmo.post_intake_capital_lease import (
      fail_fast_lease_interest_components_misaligned,
    )
    import os

    os.environ["CONVERGENCE_TEST_MODE"] = "true"
    try:
      finmo_payload = {
        "quarter_rows": [
          {
            "quarter_index": 1,
            "interest": 1000,  # broken: should be debt + lease
            "debt_interest_expense": 100,
            "lease_interest_expense": 100,
          },
        ],
      }
      with self.assertRaises((FailFastError, RuntimeError)):
        fail_fast_lease_interest_components_misaligned(
          finmo_payload=finmo_payload,
          stage="synth_check",
        )
    finally:
      os.environ.pop("CONVERGENCE_TEST_MODE", None)

  def test_depreciation_components_fail_fast_fires_on_drift(self) -> None:
    from client_intake_and_finmo.fail_fast.common import FailFastError
    from client_intake_and_finmo.post_intake_capital_lease import (
      fail_fast_lease_depreciation_components_misaligned,
    )
    import os

    os.environ["CONVERGENCE_TEST_MODE"] = "true"
    try:
      finmo_payload = {
        "quarter_rows": [
          {
            "quarter_index": 1,
            "depreciation": 9999,  # broken
            "ppe_depreciation_expense": 100,
            "lease_asset_depreciation_expense": 100,
          },
        ],
      }
      with self.assertRaises((FailFastError, RuntimeError)):
        fail_fast_lease_depreciation_components_misaligned(
          finmo_payload=finmo_payload,
          stage="synth_check",
        )
    finally:
      os.environ.pop("CONVERGENCE_TEST_MODE", None)

  def test_orphan_detector_flags_lease_section_with_no_lease(self) -> None:
    from client_intake_and_finmo.post_intake_capital_lease import (
      detect_orphaned_capital_lease_schedule,
    )

    # No-lease business but schedule shows non-zero values → orphan
    orphan_payload = {
      "rows": [
        {"quarter_index": 1, "opening_balance": 5000, "principal_payment": 0, "interest_payment": 125, "rou_asset_closing": 4750},
      ],
    }
    model_input_no_lease = {"sections": {"schedules": {"lease_opening_balance_seed": 0.0, "rows": []}}}
    orphaned = detect_orphaned_capital_lease_schedule(
      capital_lease_schedule=orphan_payload,
      model_input_json=model_input_no_lease,
    )
    self.assertEqual(len(orphaned), 1)


if __name__ == "__main__":
  unittest.main()
