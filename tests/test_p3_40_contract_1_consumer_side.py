"""Consumer-side enforcement tests for P3.40 Contract 1 Commit 4.

Validates that ``build_python_finmo_json`` runs the FinmoModelInputContract
gate at its entry point, raises ContractViolation with side=
"consumer" on shape failure, and accepts an optional
emit_diagnostic_fn for observability.

Spec: ``docs/architecture/p3_40_contract_1_finmo_model_input_spec.md`` §6.

The producer-side gate's tests (test_p3_40_contract_1_enforcement.py)
already cover the helper's behavior in isolation. These tests confirm
the helper is correctly wired at the build_python_finmo_json entry
point with the right side label, and that the gate fires BEFORE any
heavyweight processing happens.
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


from client_intake_and_finmo.finmo_bridge import build_python_finmo_json  # noqa: E402
from client_intake_and_finmo.post_intake_contracts.enforcement import (  # noqa: E402
  MODEL_INPUT_STAGE_LABEL,
  SIDE_CONSUMER,
)
from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (  # noqa: E402
  ContractViolation,
)
from client_intake_and_finmo.post_intake_diagnostics.phase_codes import (  # noqa: E402
  EventCode,
  PhaseCode,
  Status,
)
from _p3_40_contract_1_fixtures import valid_top_level  # noqa: E402


class _Recorder:
  """Fake emit_diagnostic_fn that records each call."""

  def __init__(self) -> None:
    self.calls = []

  def __call__(self, **kwargs):
    self.calls.append(kwargs)


# ---------------------------------------------------------------------------
# Consumer-side gate fires
# ---------------------------------------------------------------------------

class ConsumerGateFiresTest(unittest.TestCase):

  def test_missing_required_field_raises_contract_violation(self) -> None:
    bad = valid_top_level()
    del bad["business_name"]
    with self.assertRaises(ContractViolation) as ctx:
      build_python_finmo_json(model_input_json=bad)
    self.assertEqual(ctx.exception.stage, MODEL_INPUT_STAGE_LABEL)
    self.assertIn("business_name", ctx.exception.field)

  def test_nested_violation_raises_with_dotted_field_path(self) -> None:
    bad = valid_top_level()
    bad["sections"]["revenue"][0]["values"][3] = float("nan")
    with self.assertRaises(ContractViolation) as ctx:
      build_python_finmo_json(model_input_json=bad)
    self.assertIn("revenue", ctx.exception.field)

  def test_cross_section_violation_routed_through_gate(self) -> None:
    bad = valid_top_level()
    # Capex without Depreciation — cross-section invariant violation
    bad["sections"]["schedules"]["rows"] = [{
      "named_range": "model_input_schedules",
      "controller_write": True,
      "lever_id": "schedules::Capital Expenditures",
      "label": "Capital Expenditures",
      "value_kind": "direct_number",
      "input_semantics": "capital_expenditures_cash",
      "values": [0.0] * 21,
    }]
    with self.assertRaises(ContractViolation) as ctx:
      build_python_finmo_json(model_input_json=bad)
    self.assertIn("Capital Expenditures", ctx.exception.expected)

  def test_non_dict_input_raises_contract_violation(self) -> None:
    # Per the wiring, non-dict input is normalized to {} which then
    # fails the contract (sections min_length=1, etc.). The gate
    # surfaces this loudly instead of silently no-op'ing further down
    # build_python_finmo_json.
    with self.assertRaises(ContractViolation):
      build_python_finmo_json(model_input_json=None)
    with self.assertRaises(ContractViolation):
      build_python_finmo_json(model_input_json="not a dict")


# ---------------------------------------------------------------------------
# Side label is "consumer"
# ---------------------------------------------------------------------------

class ConsumerSideLabelTest(unittest.TestCase):

  def test_emits_with_consumer_side_label_on_failure(self) -> None:
    rec = _Recorder()
    bad = valid_top_level()
    del bad["business_name"]
    with self.assertRaises(ContractViolation):
      build_python_finmo_json(model_input_json=bad, emit_diagnostic_fn=rec)
    self.assertEqual(len(rec.calls), 1)
    call = rec.calls[0]
    self.assertEqual(call["phase"], PhaseCode.MODEL_INPUT_CONTRACT)
    self.assertEqual(call["event_code"], EventCode.MODEL_INPUT_CONTRACT_VIOLATION)
    self.assertEqual(call["status"], Status.FAILED)
    self.assertEqual(call["diagnostic_data"]["side"], SIDE_CONSUMER)

  def test_no_emitter_means_no_emit_on_failure(self) -> None:
    bad = valid_top_level()
    del bad["business_name"]
    # Should still raise even without an emitter.
    with self.assertRaises(ContractViolation):
      build_python_finmo_json(model_input_json=bad)


# ---------------------------------------------------------------------------
# Gate fires BEFORE heavyweight processing
# ---------------------------------------------------------------------------

class GateFiresBeforeProcessingTest(unittest.TestCase):

  def test_invalid_payload_does_not_reach_apply_derived_driver_policies(self) -> None:
    """If the consumer-side gate fires before
    apply_derived_driver_policies_to_model_input, an invalid payload
    that would have caused a downstream crash (e.g. missing
    required nested fields) raises ContractViolation cleanly
    instead of the downstream's harder-to-diagnose error."""
    bad = {
      # missing contract_version, sections, etc. - barely a payload
      "business_name": "Halt Co",
    }
    with self.assertRaises(ContractViolation) as ctx:
      build_python_finmo_json(model_input_json=bad)
    # ContractViolation, NOT some downstream AttributeError /
    # KeyError that the empty-payload would trigger in
    # apply_derived_driver_policies_to_model_input or
    # FinancialModelInputs.from_model_input_json.
    self.assertEqual(ctx.exception.stage, MODEL_INPUT_STAGE_LABEL)


if __name__ == "__main__":
  unittest.main(verbosity=2)
