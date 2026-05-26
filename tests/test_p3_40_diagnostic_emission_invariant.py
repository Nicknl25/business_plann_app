"""Observability-actually-emits invariant tests for P3.40
contracts 1, 2, and 3.

Establishes the invariant that every contract's gate observably
emits its OWN phase code (not silently dropped, not mis-routed to
a different contract's phase code).

This guard catches a class of regression: if a future refactor
re-introduces the ``_safe_emit`` hardcode-to-MODEL_INPUT_CONTRACT
bug, or if a new contract's PhaseCode is forgotten in the
diagnostics module (which is exactly what happened to
Contract 2's WORKBOOK_PAYLOAD_CONTRACT from its Commit 3 landing
through to the Contract 3 Commit 3 _safe_emit parameterization),
these tests fail loudly rather than silently no-op'ing the
diagnostic stream.

Pattern: each test feeds a deliberate contract violation through
the boundary gate with a capturing ``emit_diagnostic_fn`` callback.
Assert the captured event carries the right PhaseCode value.
"""

from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Dict, List


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
ROOT = os.path.abspath(os.path.join(HERE, os.pardir))
for path in (PYTHON_ROOT, ROOT, HERE):
  if path not in sys.path:
    sys.path.insert(0, path)


from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (  # noqa: E402
  ContractViolation,
)
from client_intake_and_finmo.post_intake_contracts.enforcement import (  # noqa: E402
  SIDE_CONSUMER,
  SIDE_PRODUCER,
  validate_amalgamated_session_at_boundary,
  validate_industry_baseline_population_summary_at_boundary,
  validate_intake_draft_at_boundary,
  validate_model_input_at_boundary,
  validate_solver_input_at_boundary,
  validate_solver_output_at_boundary,
  validate_workbook_payload_at_boundary,
)
from client_intake_and_finmo.post_intake_diagnostics.phase_codes import (  # noqa: E402
  PhaseCode,
)
from _p3_40_contract_1_fixtures import valid_top_level  # noqa: E402
from _p3_40_contract_2_fixtures import valid_workbook_payload_dict  # noqa: E402
from _p3_40_contract_3_fixtures import valid_solver_input_dict  # noqa: E402
from _p3_40_contract_4_fixtures import valid_solver_output_dict  # noqa: E402
from _p3_40_contract_5_fixtures import valid_intake_draft_dict  # noqa: E402
from _p3_40_contract_6_fixtures import (  # noqa: E402
  valid_population_summary_section_dict,
)
from _p3_40_contract_7_fixtures import (  # noqa: E402
  valid_mirror_dict,
)


class _CapturingEmitter:
  """Records every (phase, event_code, status, diagnostic_data)
  tuple ``_safe_emit`` forwards through it. Used by all three
  observability tests below to confirm the gate's emit lands."""

  def __init__(self) -> None:
    self.calls: List[Dict[str, Any]] = []

  def __call__(self, **kwargs: Any) -> None:
    self.calls.append(kwargs)


class ContractOneEmitsModelInputPhaseCodeTest(unittest.TestCase):

  def test_violation_emit_carries_model_input_contract_phase(self) -> None:
    """Contract 1 gate must emit under PhaseCode.MODEL_INPUT_CONTRACT
    -- the gate's diagnostic event tags the right contract so
    queries / dashboards can filter by phase. Catches the
    _safe_emit hardcode-regression class."""
    emitter = _CapturingEmitter()
    bad_payload = valid_top_level()
    bad_payload["sections"]["revenue"] = []  # min_length=1 violation
    with self.assertRaises(ContractViolation):
      validate_model_input_at_boundary(
        bad_payload, side=SIDE_PRODUCER, emit_diagnostic_fn=emitter,
      )
    self.assertEqual(len(emitter.calls), 1)
    self.assertEqual(emitter.calls[0]["phase"], PhaseCode.MODEL_INPUT_CONTRACT)


class ContractTwoEmitsWorkbookPhaseCodeTest(unittest.TestCase):

  def test_violation_emit_carries_workbook_payload_contract_phase(self) -> None:
    """Contract 2 gate must emit under
    PhaseCode.WORKBOOK_PAYLOAD_CONTRACT. This is the regression
    test for the silent-no-op bug that lived between Contract 2's
    Commit 3 landing and the Contract 2 diagnostic-stack
    restoration commit (this commit). Before this commit:
    Contract 2's _safe_emit calls passed
    phase_code_name='WORKBOOK_PAYLOAD_CONTRACT', but
    PhaseCode.WORKBOOK_PAYLOAD_CONTRACT didn't exist, so
    getattr(PhaseCode, 'WORKBOOK_PAYLOAD_CONTRACT') raised
    AttributeError which the outer try/except in _safe_emit
    swallowed. Contract still raised ContractViolation, but the
    diagnostic event never landed. This test pins the fix."""
    emitter = _CapturingEmitter()
    bad_payload = valid_workbook_payload_dict()
    del bad_payload["debt_schedule"]  # required-field violation
    with self.assertRaises(ContractViolation):
      validate_workbook_payload_at_boundary(
        bad_payload, side=SIDE_CONSUMER, emit_diagnostic_fn=emitter,
      )
    self.assertEqual(len(emitter.calls), 1)
    self.assertEqual(emitter.calls[0]["phase"], PhaseCode.WORKBOOK_PAYLOAD_CONTRACT)


class ContractThreeEmitsSolverPhaseCodeTest(unittest.TestCase):

  def test_violation_emit_carries_solver_input_contract_phase(self) -> None:
    """Contract 3 gate must emit under
    PhaseCode.SOLVER_INPUT_CONTRACT. Symmetric with Contract 1 +
    Contract 2 tests above -- establishes the invariant that
    every contract's gate observably emits its own phase code."""
    emitter = _CapturingEmitter()
    bad_payload = valid_solver_input_dict()
    del bad_payload["business_facts"]  # required-field violation
    with self.assertRaises(ContractViolation):
      validate_solver_input_at_boundary(
        bad_payload, side=SIDE_CONSUMER, emit_diagnostic_fn=emitter,
      )
    self.assertEqual(len(emitter.calls), 1)
    self.assertEqual(emitter.calls[0]["phase"], PhaseCode.SOLVER_INPUT_CONTRACT)


class ContractFourEmitsSolverOutputPhaseCodeTest(unittest.TestCase):

  def test_violation_emit_carries_solver_output_contract_phase(self) -> None:
    """Contract 4 gate must emit under
    PhaseCode.SOLVER_OUTPUT_CONTRACT. Extends the established
    every-contract-emits-its-own-phase invariant to Contract 4.
    The Commit 3 lockstep that added the PhaseCode enum entry
    + the validate_solver_output_at_boundary helper must keep
    them paired -- this test catches a future regression where
    the helper's phase_code_name string drifts from the enum
    attribute name."""
    emitter = _CapturingEmitter()
    bad_payload = valid_solver_output_dict()
    del bad_payload["plan_confidence"]  # required-field violation
    with self.assertRaises(ContractViolation):
      validate_solver_output_at_boundary(
        bad_payload, side=SIDE_CONSUMER, emit_diagnostic_fn=emitter,
      )
    self.assertEqual(len(emitter.calls), 1)
    self.assertEqual(emitter.calls[0]["phase"], PhaseCode.SOLVER_OUTPUT_CONTRACT)


class ContractFiveEmitsIntakeDraftPhaseCodeTest(unittest.TestCase):

  def test_violation_emit_carries_intake_draft_contract_phase(self) -> None:
    """Contract 5 gate must emit under
    PhaseCode.INTAKE_DRAFT_CONTRACT. Extends the established
    every-contract-emits-its-own-phase invariant to Contract 5
    (the most-upstream contract in the P3.40 series). Same
    regression guard pattern as Contracts 1-4."""
    emitter = _CapturingEmitter()
    bad_payload = valid_intake_draft_dict()
    del bad_payload["financials_json"]  # required-field violation
    with self.assertRaises(ContractViolation):
      validate_intake_draft_at_boundary(
        bad_payload, side=SIDE_CONSUMER, emit_diagnostic_fn=emitter,
      )
    self.assertEqual(len(emitter.calls), 1)
    self.assertEqual(emitter.calls[0]["phase"], PhaseCode.INTAKE_DRAFT_CONTRACT)


class ContractSixEmitsIndustryBaselinePhaseCodeTest(unittest.TestCase):

  def test_violation_emit_carries_industry_baseline_contract_phase(self) -> None:
    """Contract 6 gate must emit under
    PhaseCode.INDUSTRY_BASELINE_CONTRACT. Per F16: SINGLE
    PhaseCode covers all 4 shapes (A/B/C/D);
    diagnostic_data['shape'] field distinguishes them.

    This test exercises Shape D (PopulationSummary) via the
    F10 zero-resolved-total violation; the same PhaseCode
    routing applies to the other 3 enforcement helpers
    (validated separately in the cross-contamination test
    class below)."""
    emitter = _CapturingEmitter()
    # F10 violation: zero resolved bands triggers ContractViolation
    bad_payload = {
      "drivers": valid_population_summary_section_dict(resolved=0, skipped=5),
    }
    with self.assertRaises(ContractViolation):
      validate_industry_baseline_population_summary_at_boundary(
        bad_payload, side=SIDE_PRODUCER, emit_diagnostic_fn=emitter,
      )
    self.assertEqual(len(emitter.calls), 1)
    self.assertEqual(
      emitter.calls[0]["phase"], PhaseCode.INDUSTRY_BASELINE_CONTRACT,
    )
    # Per F16: diagnostic_data['shape'] distinguishes A/B/C/D
    self.assertEqual(emitter.calls[0]["diagnostic_data"]["shape"], "D")


class ContractSevenEmitsAmalgamatedSessionPhaseCodeTest(unittest.TestCase):

  def test_violation_emit_carries_amalgamated_session_contract_phase(self) -> None:
    """Contract 7 gate must emit under
    PhaseCode.AMALGAMATED_SESSION_CONTRACT. Per F12: SINGLE
    PhaseCode covers all sub-contract shapes
    (mirror / validation_state); diagnostic_data['shape'] field
    distinguishes them. Closes the every-contract-emits-its-own
    invariant for the FINAL P3.40 contract."""
    emitter = _CapturingEmitter()
    bad_payload = valid_mirror_dict()
    # F5 alias-sync violation: balance_sheet + capex_rd hold
    # differing payloads.
    bad_payload["plan_state"]["balance_sheet"] = {"key": "A"}
    bad_payload["plan_state"]["capex_rd"] = {"key": "B"}
    with self.assertRaises(ContractViolation):
      validate_amalgamated_session_at_boundary(
        bad_payload, side=SIDE_CONSUMER, emit_diagnostic_fn=emitter,
      )
    self.assertEqual(len(emitter.calls), 1)
    self.assertEqual(
      emitter.calls[0]["phase"], PhaseCode.AMALGAMATED_SESSION_CONTRACT,
    )
    # Per F12: diagnostic_data['shape'] distinguishes mirror /
    # validation_state sub-contracts under the single PhaseCode.
    self.assertEqual(emitter.calls[0]["diagnostic_data"]["shape"], "mirror")


# ---------------------------------------------------------------------------
# Cross-contract negative check: phase codes are NOT mis-routed
# ---------------------------------------------------------------------------

class PhaseCodesDoNotCrossContaminateTest(unittest.TestCase):
  """Belt-and-suspenders: confirm Contract 2's gate does NOT emit
  under MODEL_INPUT_CONTRACT (the old hardcoded value) even now
  that the PhaseCode is parameterized. If a future refactor
  re-hardcodes a phase code, this test fails before the silent
  cross-contamination ships."""

  def test_contract_2_violation_does_not_emit_under_model_input_contract(self) -> None:
    emitter = _CapturingEmitter()
    bad_payload = valid_workbook_payload_dict()
    del bad_payload["debt_schedule"]
    with self.assertRaises(ContractViolation):
      validate_workbook_payload_at_boundary(
        bad_payload, side=SIDE_CONSUMER, emit_diagnostic_fn=emitter,
      )
    self.assertEqual(len(emitter.calls), 1)
    self.assertNotEqual(emitter.calls[0]["phase"], PhaseCode.MODEL_INPUT_CONTRACT)

  def test_contract_3_violation_does_not_emit_under_model_input_contract(self) -> None:
    emitter = _CapturingEmitter()
    bad_payload = valid_solver_input_dict()
    del bad_payload["business_facts"]
    with self.assertRaises(ContractViolation):
      validate_solver_input_at_boundary(
        bad_payload, side=SIDE_CONSUMER, emit_diagnostic_fn=emitter,
      )
    self.assertEqual(len(emitter.calls), 1)
    self.assertNotEqual(emitter.calls[0]["phase"], PhaseCode.MODEL_INPUT_CONTRACT)

  def test_contract_4_violation_routes_only_to_solver_output_contract_phase(self) -> None:
    """Belt-and-suspenders for Contract 4: confirm a violation
    emits ONLY under SOLVER_OUTPUT_CONTRACT, not under any of the
    other 3 contract phase codes. Symmetric with the Contract 2
    + Contract 3 cross-contamination tests above."""
    emitter = _CapturingEmitter()
    bad_payload = valid_solver_output_dict()
    del bad_payload["plan_confidence"]
    with self.assertRaises(ContractViolation):
      validate_solver_output_at_boundary(
        bad_payload, side=SIDE_CONSUMER, emit_diagnostic_fn=emitter,
      )
    self.assertEqual(len(emitter.calls), 1)
    emitted_phase = emitter.calls[0]["phase"]
    self.assertEqual(emitted_phase, PhaseCode.SOLVER_OUTPUT_CONTRACT)
    # And NOT any of the other three contract phase codes:
    self.assertNotEqual(emitted_phase, PhaseCode.MODEL_INPUT_CONTRACT)
    self.assertNotEqual(emitted_phase, PhaseCode.WORKBOOK_PAYLOAD_CONTRACT)
    self.assertNotEqual(emitted_phase, PhaseCode.SOLVER_INPUT_CONTRACT)

  def test_contract_5_violation_routes_only_to_intake_draft_contract_phase(self) -> None:
    """Belt-and-suspenders for Contract 5: confirm a violation
    emits ONLY under INTAKE_DRAFT_CONTRACT, NOT under any of the
    other 4 contract phase codes. Symmetric with the Contract 2-4
    cross-contamination tests above."""
    emitter = _CapturingEmitter()
    bad_payload = valid_intake_draft_dict()
    del bad_payload["financials_json"]
    with self.assertRaises(ContractViolation):
      validate_intake_draft_at_boundary(
        bad_payload, side=SIDE_CONSUMER, emit_diagnostic_fn=emitter,
      )
    self.assertEqual(len(emitter.calls), 1)
    emitted_phase = emitter.calls[0]["phase"]
    self.assertEqual(emitted_phase, PhaseCode.INTAKE_DRAFT_CONTRACT)
    # And NOT any of the other four contract phase codes:
    self.assertNotEqual(emitted_phase, PhaseCode.MODEL_INPUT_CONTRACT)
    self.assertNotEqual(emitted_phase, PhaseCode.WORKBOOK_PAYLOAD_CONTRACT)
    self.assertNotEqual(emitted_phase, PhaseCode.SOLVER_INPUT_CONTRACT)
    self.assertNotEqual(emitted_phase, PhaseCode.SOLVER_OUTPUT_CONTRACT)

  def test_contract_6_violation_routes_only_to_industry_baseline_contract_phase(self) -> None:
    """Belt-and-suspenders for Contract 6: confirm a violation
    emits ONLY under INDUSTRY_BASELINE_CONTRACT, NOT under any of
    the other 5 contract phase codes. Symmetric with the
    Contract 2-5 cross-contamination tests above."""
    emitter = _CapturingEmitter()
    bad_payload = {
      "drivers": valid_population_summary_section_dict(resolved=0, skipped=5),
    }
    with self.assertRaises(ContractViolation):
      validate_industry_baseline_population_summary_at_boundary(
        bad_payload, side=SIDE_PRODUCER, emit_diagnostic_fn=emitter,
      )
    self.assertEqual(len(emitter.calls), 1)
    emitted_phase = emitter.calls[0]["phase"]
    self.assertEqual(emitted_phase, PhaseCode.INDUSTRY_BASELINE_CONTRACT)
    # And NOT any of the other five contract phase codes:
    self.assertNotEqual(emitted_phase, PhaseCode.MODEL_INPUT_CONTRACT)
    self.assertNotEqual(emitted_phase, PhaseCode.WORKBOOK_PAYLOAD_CONTRACT)
    self.assertNotEqual(emitted_phase, PhaseCode.SOLVER_INPUT_CONTRACT)
    self.assertNotEqual(emitted_phase, PhaseCode.SOLVER_OUTPUT_CONTRACT)
    self.assertNotEqual(emitted_phase, PhaseCode.INTAKE_DRAFT_CONTRACT)

  def test_contract_7_violation_routes_only_to_amalgamated_session_contract_phase(self) -> None:
    """Belt-and-suspenders for Contract 7: confirm a violation
    emits ONLY under AMALGAMATED_SESSION_CONTRACT, NOT under any
    of the other 6 contract phase codes. Closes the cross-
    contamination invariant for the FINAL P3.40 contract."""
    emitter = _CapturingEmitter()
    bad_payload = valid_mirror_dict()
    bad_payload["plan_state"]["balance_sheet"] = {"key": "A"}
    bad_payload["plan_state"]["capex_rd"] = {"key": "B"}
    with self.assertRaises(ContractViolation):
      validate_amalgamated_session_at_boundary(
        bad_payload, side=SIDE_CONSUMER, emit_diagnostic_fn=emitter,
      )
    self.assertEqual(len(emitter.calls), 1)
    emitted_phase = emitter.calls[0]["phase"]
    self.assertEqual(emitted_phase, PhaseCode.AMALGAMATED_SESSION_CONTRACT)
    # And NOT any of the other six contract phase codes:
    self.assertNotEqual(emitted_phase, PhaseCode.MODEL_INPUT_CONTRACT)
    self.assertNotEqual(emitted_phase, PhaseCode.WORKBOOK_PAYLOAD_CONTRACT)
    self.assertNotEqual(emitted_phase, PhaseCode.SOLVER_INPUT_CONTRACT)
    self.assertNotEqual(emitted_phase, PhaseCode.SOLVER_OUTPUT_CONTRACT)
    self.assertNotEqual(emitted_phase, PhaseCode.INTAKE_DRAFT_CONTRACT)
    self.assertNotEqual(emitted_phase, PhaseCode.INDUSTRY_BASELINE_CONTRACT)


if __name__ == "__main__":
  unittest.main()
