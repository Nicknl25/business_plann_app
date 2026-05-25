"""Acceptance tests for the DraftWorkbookData <-> WorkbookPayloadContract
adapter added in Contract 2 Commit 2.

Spec: ``docs/architecture/p3_40_contract_2_workbook_payload_spec.md`` §6.
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


from pydantic import ValidationError  # noqa: E402

from client_intake_and_finmo.post_intake_contracts.workbook_payload_contract import (  # noqa: E402
  WorkbookPayloadContract,
)
from client_statements_output_excel.data import (  # noqa: E402
  DraftWorkbookData,
  draft_data_from_row,
)
from _p3_40_contract_2_fixtures import (  # noqa: E402
  valid_workbook_payload_dict,
)


def _draft_data_from_fixture(
  *,
  include_planning_run: bool = True,
  include_run_diagnostics: bool = True,
  draft_row: dict | None = None,
) -> DraftWorkbookData:
  """Build a DraftWorkbookData via the round-trip path:
  fixture dict -> contract -> from_contract. Mirrors how Contract 1
  adapter tests are organized."""
  payload = valid_workbook_payload_dict(
    include_planning_run=include_planning_run,
    include_run_diagnostics=include_run_diagnostics,
  )
  contract = WorkbookPayloadContract.model_validate(payload)
  return DraftWorkbookData.from_contract(contract, draft_row=draft_row)


# ---------------------------------------------------------------------------
# from_contract -- contract -> dataclass
# ---------------------------------------------------------------------------

class FromContractTest(unittest.TestCase):

  def test_from_contract_returns_draft_workbook_data(self) -> None:
    data = _draft_data_from_fixture()
    self.assertIsInstance(data, DraftWorkbookData)

  def test_from_contract_default_draft_row_is_empty_dict(self) -> None:
    data = _draft_data_from_fixture()
    self.assertEqual(data.draft_row, {})

  def test_from_contract_preserves_supplied_draft_row(self) -> None:
    row = {"draft_id": "draft_xyz", "client_id": "client_abc"}
    data = _draft_data_from_fixture(draft_row=row)
    self.assertEqual(data.draft_row, row)
    # The derived property reads from draft_row first.
    self.assertEqual(data.draft_id, "draft_xyz")
    self.assertEqual(data.client_id, "client_abc")

  def test_from_contract_loads_model_input_json_dict(self) -> None:
    data = _draft_data_from_fixture()
    self.assertIsInstance(data.model_input_json, dict)
    self.assertEqual(data.model_input_json.get("business_name"), "Test Co")

  def test_from_contract_loads_finmo_json_dict(self) -> None:
    data = _draft_data_from_fixture()
    self.assertIsInstance(data.finmo_json, dict)
    self.assertEqual(data.finmo_json.get("contract_version"), "finmo_output_v1")

  def test_from_contract_loads_payroll_headcount_dict(self) -> None:
    data = _draft_data_from_fixture()
    self.assertIsInstance(data.payroll_headcount, dict)
    self.assertEqual(
      data.payroll_headcount.get("capacity_labor_model"),
      "capacity_units_per_supporting_fte",
    )

  def test_from_contract_loads_debt_schedule_dict(self) -> None:
    data = _draft_data_from_fixture()
    self.assertIsInstance(data.debt_schedule, dict)
    self.assertEqual(
      data.debt_schedule.get("contract_version"),
      "post_intake_debt_amortization_schedule_v1",
    )
    self.assertEqual(len(data.debt_schedule.get("rows", [])), 20)

  def test_from_contract_loads_planning_run_json_dict(self) -> None:
    data = _draft_data_from_fixture(include_planning_run=True)
    # planning_run_json fixture has the full canonical chain populated.
    ucc = data.planning_run_json.get("unified_convergence_context")
    self.assertIsInstance(ucc, dict)
    self.assertIn("business_world_contract", ucc)

  def test_from_contract_planning_run_json_absent_becomes_empty_dict(self) -> None:
    data = _draft_data_from_fixture(include_planning_run=False)
    self.assertEqual(data.planning_run_json, {})

  def test_from_contract_run_diagnostics_passed_through_when_present(self) -> None:
    data = _draft_data_from_fixture(include_run_diagnostics=True)
    self.assertIsNotNone(data.run_diagnostics)
    self.assertEqual(data.run_diagnostics.get("draft_id"), "draft_test_001")

  def test_from_contract_run_diagnostics_None_when_absent(self) -> None:
    data = _draft_data_from_fixture(include_run_diagnostics=False)
    self.assertIsNone(data.run_diagnostics)


# ---------------------------------------------------------------------------
# to_contract -- dataclass -> contract
# ---------------------------------------------------------------------------

class ToContractTest(unittest.TestCase):

  def test_to_contract_returns_workbook_payload_contract(self) -> None:
    data = _draft_data_from_fixture()
    contract = data.to_contract()
    self.assertIsInstance(contract, WorkbookPayloadContract)

  def test_to_contract_drops_draft_row(self) -> None:
    # draft_row carries arbitrary DB columns the contract doesn't model;
    # it must NOT leak into the typed payload.
    row = {"draft_id": "X", "internal_only_db_column": "leak_me"}
    data = _draft_data_from_fixture(draft_row=row)
    contract = data.to_contract()
    dumped = contract.model_dump(mode="json")
    self.assertNotIn("draft_row", dumped)
    self.assertNotIn("internal_only_db_column", str(dumped))

  def test_to_contract_preserves_business_name_in_model_input(self) -> None:
    data = _draft_data_from_fixture()
    contract = data.to_contract()
    self.assertEqual(contract.model_input_json.business_name, "Test Co")

  def test_to_contract_validates_required_fields(self) -> None:
    # Construct a dataclass directly with empty payload dicts and
    # confirm to_contract raises ValidationError -- the adapter does
    # not silently swallow shape errors.
    bad = DraftWorkbookData(
      draft_row={},
      model_input_json={},  # empty -- Contract 1 requires many fields
      finmo_json={},
      payroll_headcount={},
      debt_schedule={},
      planning_run_json={},
    )
    with self.assertRaises(ValidationError):
      bad.to_contract()

  def test_to_contract_empty_planning_run_dict_omitted_on_contract(self) -> None:
    # data.py line 175-176: empty planning_run_json on the dataclass
    # is the legitimate "convergence did not run" state. The adapter
    # OMITS the field rather than sending {} (which would trip
    # invariant 4.1's chain-raise on present-but-empty
    # planning_run_json). The contract sees the Optional field as
    # absent -> None, and the chain-raise short-circuits at the
    # outer ``is None`` guard.
    data = _draft_data_from_fixture(include_planning_run=False)
    self.assertEqual(data.planning_run_json, {})
    contract = data.to_contract()
    self.assertIsNone(contract.planning_run_json)

  def test_to_contract_omits_run_diagnostics_when_None(self) -> None:
    data = _draft_data_from_fixture(include_run_diagnostics=False)
    contract = data.to_contract()
    self.assertIsNone(contract.run_diagnostics)


# ---------------------------------------------------------------------------
# Round-trip -- contract -> from_contract -> to_contract
# ---------------------------------------------------------------------------

class RoundTripTest(unittest.TestCase):

  def test_round_trip_contract_dataclass_contract_preserves_shape(self) -> None:
    """contract -> from_contract -> to_contract should produce a
    contract that re-validates and carries the same top-level
    business data. The draft_row is dropped at to_contract (per
    design) and reconstructed as {} at from_contract; both sides
    of the round-trip otherwise pass through the 6 JSON dicts
    unchanged."""
    original = WorkbookPayloadContract.model_validate(valid_workbook_payload_dict())
    data = DraftWorkbookData.from_contract(original)
    round_tripped = data.to_contract()

    self.assertEqual(
      original.model_input_json.business_name,
      round_tripped.model_input_json.business_name,
    )
    self.assertEqual(
      len(original.finmo_json.quarter_rows or []),
      len(round_tripped.finmo_json.quarter_rows or []),
    )
    self.assertEqual(
      len(original.payroll_headcount.rows),
      len(round_tripped.payroll_headcount.rows),
    )
    self.assertEqual(
      len(original.debt_schedule.rows),
      len(round_tripped.debt_schedule.rows),
    )

  def test_round_trip_with_db_row_inputs(self) -> None:
    """The production path draft_data_from_row -> DraftWorkbookData
    -> to_contract should produce a valid contract. Verifies the
    adapter interoperates with the existing row-from-DB parser."""
    row = {
      "draft_id": "draft_xyz",
      "client_id": "client_xyz",
      "business_name": "From DB Row",
      "model_input_json": valid_workbook_payload_dict()["model_input_json"],
      "finmo_json": valid_workbook_payload_dict()["finmo_json"],
      "payroll_headcount": valid_workbook_payload_dict()["payroll_headcount"],
      "debt_schedule": valid_workbook_payload_dict()["debt_schedule"],
      "planning_run_json": valid_workbook_payload_dict()["planning_run_json"],
    }
    data = draft_data_from_row(row)
    contract = data.to_contract()
    self.assertIsInstance(contract, WorkbookPayloadContract)
    self.assertEqual(contract.model_input_json.business_name, "Test Co")
    # draft_row's business_name takes precedence in the dataclass
    # property but isn't part of the typed contract -- only the
    # nested model_input_json.business_name is.
    self.assertEqual(data.business_name, "From DB Row")


if __name__ == "__main__":
  unittest.main()
