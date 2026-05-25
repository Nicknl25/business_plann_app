"""Acceptance tests for the FinancialModelInputs <-> FinmoModelInputContract
adapter added in Contract 1 Commit 2.

Spec: ``docs/architecture/p3_40_contract_1_finmo_model_input_spec.md`` §6.
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)
if HERE not in sys.path:
  sys.path.insert(0, HERE)


from pydantic import ValidationError  # noqa: E402

from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (  # noqa: E402
  FinmoModelInputContract,
  PERIOD_COUNT,
)
from financial_model_engine.model_inputs import (  # noqa: E402
  FinancialModelInputs,
  QUARTER_COUNT,
  _adapter_pad_values_to_21,
  _adapter_periods_21,
)
from _p3_40_contract_1_fixtures import valid_top_level  # noqa: E402


def _fmi_from_valid_contract() -> FinancialModelInputs:
  """Build a FinancialModelInputs from a fixture-valid v3 contract.
  The shared fixture builds a minimal-valid payload (one product
  slot, one expense, WC days triple, no schedules.rows)."""
  contract = FinmoModelInputContract.model_validate(valid_top_level())
  return FinancialModelInputs.from_contract(contract)


# ---------------------------------------------------------------------------
# from_contract — contract -> dataclass parsing
# ---------------------------------------------------------------------------

class FromContractTest(unittest.TestCase):

  def test_from_contract_preserves_business_name(self) -> None:
    book = _fmi_from_valid_contract()
    self.assertEqual(book.business_name, "Test Co")

  def test_from_contract_preserves_start_date(self) -> None:
    book = _fmi_from_valid_contract()
    self.assertEqual(book.start_date, "2026-01-01")

  def test_from_contract_loads_revenue_per_slot(self) -> None:
    book = _fmi_from_valid_contract()
    # Fixture has exactly one product slot (LOB 1 / Product 1).
    self.assertEqual(len(book.quarters), QUARTER_COUNT)
    q1 = book.quarter(1)
    self.assertGreaterEqual(len(q1.revenue_groups), 1)

  def test_from_contract_loads_expense_rows(self) -> None:
    book = _fmi_from_valid_contract()
    self.assertIn("Cost of Goods Sold", book.expense_rows)

  def test_from_contract_loads_balance_sheet_wc_days(self) -> None:
    book = _fmi_from_valid_contract()
    for label in ("Accounts Receivable Days", "Inventory Days", "Accounts Payable Days"):
      self.assertIn(label, book.balance_sheet_rows)

  def test_from_contract_zero_seeds_loaded(self) -> None:
    book = _fmi_from_valid_contract()
    self.assertEqual(book.debt_opening_balance_seed, 0.0)
    self.assertEqual(book.lease_opening_balance_seed, 0.0)
    self.assertEqual(book.accumulated_depreciation_opening_seed, 0.0)


# ---------------------------------------------------------------------------
# to_contract — dataclass -> contract emission
# ---------------------------------------------------------------------------

class ToContractTest(unittest.TestCase):

  def test_empty_book_fails_contract_validation(self) -> None:
    # min_length=1 on revenue/expenses/balance_sheet means an empty
    # book cannot produce a valid contract. This is intentional —
    # the contract describes a converged model_input, not a stub.
    book = FinancialModelInputs.empty(start_date="2026-01-01", business_name="X")
    with self.assertRaises(ValidationError):
      book.to_contract()

  def test_round_trip_from_then_to_contract(self) -> None:
    """contract -> from_contract -> to_contract should produce a
    contract with equivalent business-data fields. The opaque-blob
    top-level fields (lever_catalog, etc.) and the periods array
    are NOT preserved across the round-trip because the dataclass
    doesn't model them.

    The dataclass also runs ``_normalize_debt_schedule_rows`` on
    ``from_model_input_json`` ingestion (model_inputs.py:360), which
    auto-creates Debt Issuance + Debt Repayment schedule rows when
    they are absent. So an empty-schedules-rows fixture round-trips
    to >=2 schedule rows. This is intentional dataclass behavior,
    not an adapter bug; the test asserts it explicitly.
    """
    src = FinmoModelInputContract.model_validate(valid_top_level())
    book = FinancialModelInputs.from_contract(src)
    rebuilt = book.to_contract()
    # Core identity fields preserved
    self.assertEqual(rebuilt.contract_version, src.contract_version)
    self.assertEqual(rebuilt.business_name, src.business_name)
    self.assertEqual(rebuilt.start_date, src.start_date)
    # Section row counts preserved for revenue/expenses/balance_sheet
    self.assertEqual(len(rebuilt.sections.revenue), len(src.sections.revenue))
    self.assertEqual(len(rebuilt.sections.expenses), len(src.sections.expenses))
    self.assertEqual(len(rebuilt.sections.balance_sheet), len(src.sections.balance_sheet))
    # Schedule rows: at least the src count plus the dataclass's
    # auto-normalized Debt Issuance + Debt Repayment rows. When src
    # already contains those rows, no growth happens.
    rebuilt_labels = {r.label for r in rebuilt.sections.schedules.rows}
    src_labels = {r.label for r in src.sections.schedules.rows}
    self.assertTrue(
      src_labels.issubset(rebuilt_labels),
      f"src schedule labels {src_labels} not preserved in rebuilt {rebuilt_labels}",
    )
    # _normalize_debt_schedule_rows guarantees these:
    self.assertIn("Debt Issuance (New Borrowing)", rebuilt_labels)
    self.assertIn("Debt Repayment (Scheduled)", rebuilt_labels)

  def test_round_trip_preserves_revenue_slot_keys(self) -> None:
    src = FinmoModelInputContract.model_validate(valid_top_level())
    book = FinancialModelInputs.from_contract(src)
    rebuilt = book.to_contract()
    src_slot_keys = sorted({r.revenue_slot_key for r in src.sections.revenue})
    rebuilt_slot_keys = sorted({r.revenue_slot_key for r in rebuilt.sections.revenue})
    self.assertEqual(src_slot_keys, rebuilt_slot_keys)

  def test_round_trip_preserves_per_driver_values(self) -> None:
    """Capacity / Unit Price / Utilization values should round-trip
    through the dataclass faithfully."""
    src = FinmoModelInputContract.model_validate(valid_top_level())
    book = FinancialModelInputs.from_contract(src)
    rebuilt = book.to_contract()
    # Get the Capacity row from src and from rebuilt for the same slot.
    src_capacity = next(
      r for r in src.sections.revenue
      if r.driver == "Capacity" and r.revenue_slot_key == "lob_1_product_1"
    )
    rebuilt_capacity = next(
      r for r in rebuilt.sections.revenue
      if r.driver == "Capacity" and r.revenue_slot_key == "lob_1_product_1"
    )
    # The dataclass round-trip preserves the LIVE 20 values exactly;
    # the stub at index 0 is reset to 0.0 because the dataclass
    # stores only per-quarter live values.
    self.assertEqual(rebuilt_capacity.values[1:], src_capacity.values[1:])

  def test_to_contract_normalizes_accumulated_depreciation_sign(self) -> None:
    """The contract requires accumulated_depreciation_opening_seed
    <= 0; the dataclass stores a raw float. Adapter must normalize
    via -abs(...) so a positive value in the dataclass doesn't fail
    contract validation."""
    book = FinancialModelInputs.from_contract(
      FinmoModelInputContract.model_validate(valid_top_level())
    )
    book.accumulated_depreciation_opening_seed = 50000.0  # positive
    contract = book.to_contract()
    self.assertEqual(
      contract.sections.schedules.accumulated_depreciation_opening_seed,
      -50000.0,
    )

  def test_to_contract_emits_canonical_named_ranges(self) -> None:
    book = FinancialModelInputs.from_contract(
      FinmoModelInputContract.model_validate(valid_top_level())
    )
    contract = book.to_contract()
    self.assertTrue(all(r.named_range == "model_input_revenue" for r in contract.sections.revenue))
    self.assertTrue(all(r.named_range == "model_input_expenses" for r in contract.sections.expenses))
    # Production typo retained per R2
    self.assertTrue(all(
      r.named_range == "model_input_balancehseet" for r in contract.sections.balance_sheet
    ))

  def test_to_contract_emits_21_period_array(self) -> None:
    book = FinancialModelInputs.from_contract(
      FinmoModelInputContract.model_validate(valid_top_level())
    )
    contract = book.to_contract()
    self.assertEqual(len(contract.periods), PERIOD_COUNT)
    self.assertTrue(contract.periods[0].is_stub)
    for i in range(1, PERIOD_COUNT):
      self.assertFalse(contract.periods[i].is_stub)
      self.assertEqual(contract.periods[i].quarter, float(i))

  def test_to_contract_opaque_blobs_emitted_empty(self) -> None:
    book = FinancialModelInputs.from_contract(
      FinmoModelInputContract.model_validate(valid_top_level())
    )
    contract = book.to_contract()
    self.assertEqual(contract.lever_catalog, {})
    self.assertEqual(contract.controller_write_levers, [])
    # Optional fields absent (None) — producer-side validation case.
    self.assertIsNone(contract.derived_driver_policies)
    self.assertIsNone(contract.derived_driver_runtime)


# ---------------------------------------------------------------------------
# Adapter helper unit tests
# ---------------------------------------------------------------------------

class AdapterHelpersTest(unittest.TestCase):

  def test_pad_20_to_21_prepends_stub(self) -> None:
    padded = _adapter_pad_values_to_21([float(i) for i in range(1, 21)])
    self.assertEqual(len(padded), PERIOD_COUNT)
    self.assertEqual(padded[0], 0.0)  # stub
    self.assertEqual(padded[1], 1.0)
    self.assertEqual(padded[20], 20.0)

  def test_pad_21_preserved(self) -> None:
    src = [float(i) for i in range(21)]
    self.assertEqual(_adapter_pad_values_to_21(src), src)

  def test_pad_more_than_21_truncated(self) -> None:
    src = [float(i) for i in range(30)]
    padded = _adapter_pad_values_to_21(src)
    self.assertEqual(len(padded), PERIOD_COUNT)
    self.assertEqual(padded, src[:PERIOD_COUNT])

  def test_pad_short_right_pads_with_zero(self) -> None:
    padded = _adapter_pad_values_to_21([1.0, 2.0, 3.0])
    self.assertEqual(len(padded), PERIOD_COUNT)
    self.assertEqual(padded[:3], [1.0, 2.0, 3.0])
    self.assertTrue(all(x == 0.0 for x in padded[3:]))

  def test_periods_21_stub_first_then_quarters_1_to_20(self) -> None:
    periods = _adapter_periods_21("2026-01-01")
    self.assertEqual(len(periods), PERIOD_COUNT)
    self.assertTrue(periods[0]["is_stub"])
    self.assertEqual(periods[0]["quarter"], 0.0)
    for i in range(1, PERIOD_COUNT):
      self.assertFalse(periods[i]["is_stub"])
      self.assertEqual(periods[i]["quarter"], float(i))

  def test_periods_21_invalid_date_falls_back_to_today(self) -> None:
    # Bad ISO string -> falls back to utcnow().date(); the structure
    # is still valid (21 entries, stub-first, integer-sequential).
    periods = _adapter_periods_21("not-a-real-date")
    self.assertEqual(len(periods), PERIOD_COUNT)
    self.assertTrue(periods[0]["is_stub"])


if __name__ == "__main__":
  unittest.main(verbosity=2)
