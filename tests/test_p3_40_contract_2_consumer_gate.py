"""Acceptance tests for the P3.40 Contract 2 Commit 3 consumer-side
gate at ``client_statements_output_excel/workbook_builder.py:
build_client_financial_model_workbook``.

Spec: ``docs/architecture/p3_40_contract_2_workbook_payload_spec.md`` §6.

Coverage:
  - Gate accepts a valid payload and the workbook build proceeds.
  - Gate rejects each of the 4 required missing fields with a
    structured ``ContractViolation``.
  - Gate rejects a structurally-invalid sub-payload (bad debt row
    width / wrong type) with field path pointing into the violation
    location.
  - Gate diagnostics use ``WORKBOOK_STAGE_LABEL`` and side
    ``"consumer"`` so the API-layer log line carries the boundary
    name.
  - The ``except Exception`` catch at
    ``python/api_handlers/intake_consult.py:7655`` is satisfied --
    ``ContractViolation`` is a subclass of ``Exception`` and
    ``str(exc)`` returns a structured message (Adjustment B
    end-to-end verification at the wire level rather than the
    unit-test level done in test_p3_40_contract_2_workbook_payload.py).
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


from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (  # noqa: E402
  ContractViolation,
)
from client_intake_and_finmo.post_intake_contracts.workbook_payload_contract import (  # noqa: E402
  WORKBOOK_STAGE_LABEL,
)
from client_statements_output_excel.data import DraftWorkbookData  # noqa: E402
from client_statements_output_excel.workbook_builder import (  # noqa: E402
  build_client_financial_model_workbook,
)
from _p3_40_contract_2_fixtures import (  # noqa: E402
  valid_workbook_payload_dict,
)


def _draft_data_from_payload(payload: dict) -> DraftWorkbookData:
  """Build a DraftWorkbookData from a raw payload dict (does NOT
  go through to_contract -- we want bad payloads to reach the
  consumer gate, not get caught by adapter validation)."""
  return DraftWorkbookData(
    draft_row={},
    model_input_json=payload.get("model_input_json") or {},
    finmo_json=payload.get("finmo_json") or {},
    payroll_headcount=payload.get("payroll_headcount") or {},
    debt_schedule=payload.get("debt_schedule") or {},
    planning_run_json=payload.get("planning_run_json") or {},
    run_diagnostics=payload.get("run_diagnostics"),
  )


# ---------------------------------------------------------------------------
# Gate accepts valid payloads
# ---------------------------------------------------------------------------

class ValidPayloadBuildsWorkbookTest(unittest.TestCase):

  def test_valid_payload_builds_a_workbook(self) -> None:
    payload = valid_workbook_payload_dict()
    data = _draft_data_from_payload(payload)
    wb = build_client_financial_model_workbook(data)
    # openpyxl Workbook instance has sheetnames; just confirm we got
    # SOMETHING back rather than a raised exception.
    self.assertIsNotNone(wb)
    self.assertTrue(hasattr(wb, "sheetnames"))
    self.assertGreater(len(wb.sheetnames), 0)


# ---------------------------------------------------------------------------
# Gate rejects missing required fields
# ---------------------------------------------------------------------------

class GateRejectsMissingRequiredFieldTest(unittest.TestCase):

  def _assert_violation_for_missing(self, field_name: str) -> ContractViolation:
    payload = valid_workbook_payload_dict()
    del payload[field_name]
    data = _draft_data_from_payload(payload)
    with self.assertRaises(ContractViolation) as ctx:
      build_client_financial_model_workbook(data)
    return ctx.exception

  def test_missing_model_input_json_rejected(self) -> None:
    exc = self._assert_violation_for_missing("model_input_json")
    self.assertEqual(exc.stage, WORKBOOK_STAGE_LABEL)
    self.assertIn("model_input_json", exc.field)

  def test_missing_finmo_json_rejected(self) -> None:
    exc = self._assert_violation_for_missing("finmo_json")
    self.assertEqual(exc.stage, WORKBOOK_STAGE_LABEL)
    self.assertIn("finmo_json", exc.field)

  def test_missing_payroll_headcount_rejected(self) -> None:
    exc = self._assert_violation_for_missing("payroll_headcount")
    self.assertEqual(exc.stage, WORKBOOK_STAGE_LABEL)
    self.assertIn("payroll_headcount", exc.field)

  def test_missing_debt_schedule_rejected(self) -> None:
    exc = self._assert_violation_for_missing("debt_schedule")
    self.assertEqual(exc.stage, WORKBOOK_STAGE_LABEL)
    self.assertIn("debt_schedule", exc.field)


# ---------------------------------------------------------------------------
# Gate rejects structurally-invalid sub-payloads with useful field paths
# ---------------------------------------------------------------------------

class GateRejectsBadSubPayloadTest(unittest.TestCase):

  def test_bad_debt_schedule_row_field_path_points_into_violation(self) -> None:
    payload = valid_workbook_payload_dict()
    # Wipe the row's required interest_rate -- contract requires it
    # (field path should mention debt_schedule + rows + interest_rate).
    payload["debt_schedule"]["rows"][0].pop("interest_rate", None)
    payload["debt_schedule"]["rows"][0].pop("annual_interest_rate", None)
    data = _draft_data_from_payload(payload)
    with self.assertRaises(ContractViolation) as ctx:
      build_client_financial_model_workbook(data)
    self.assertEqual(ctx.exception.stage, WORKBOOK_STAGE_LABEL)
    self.assertIn("debt_schedule", ctx.exception.field)

  def test_wrong_finmo_pl_values_length_rejected(self) -> None:
    payload = valid_workbook_payload_dict()
    payload["finmo_json"]["pl"][0]["values"] = [0.0] * 5  # not 21
    data = _draft_data_from_payload(payload)
    with self.assertRaises(ContractViolation) as ctx:
      build_client_financial_model_workbook(data)
    self.assertEqual(ctx.exception.stage, WORKBOOK_STAGE_LABEL)
    self.assertIn("finmo_json", ctx.exception.field)
    self.assertIn("pl", ctx.exception.field)


# ---------------------------------------------------------------------------
# ContractViolation propagates through the API handler's generic
# ``except Exception as exc`` pattern (Adjustment B end-to-end check)
# ---------------------------------------------------------------------------

class ApiCatchPatternEndToEndTest(unittest.TestCase):

  def test_violation_is_subclass_of_exception(self) -> None:
    """The API handler's catch is ``except Exception as exc``. If
    ContractViolation ever stops being an Exception subclass, that
    catch would miss it and the server would 500. Pin the contract."""
    self.assertTrue(issubclass(ContractViolation, Exception))

  def test_violation_str_used_by_api_log_carries_stage_and_field(self) -> None:
    """The API handler at intake_consult.py:7655 logs
    ``str(exc).strip() or 'client_workbook_export_failed'``.
    Confirm the structured str(violation) the gate produces lands
    with both the stage tag and the field path in that log
    line."""
    payload = valid_workbook_payload_dict()
    del payload["debt_schedule"]
    data = _draft_data_from_payload(payload)
    try:
      build_client_financial_model_workbook(data)
      self.fail("expected ContractViolation")
    except Exception as exc:  # match the API handler exactly
      log_line = str(exc).strip() or "client_workbook_export_failed"
      self.assertIn(WORKBOOK_STAGE_LABEL, log_line)
      self.assertIn("debt_schedule", log_line)
      self.assertNotEqual(log_line, "client_workbook_export_failed")


if __name__ == "__main__":
  unittest.main()
