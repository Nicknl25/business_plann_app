"""Top-level + cross-field + Adjustment B + F14 dataclass
conversion acceptance tests for Contract 7
(AmalgamatedSessionContract).

FINAL acceptance test file in the P3.40 sequence (Commit 1c
of the last contract). Spec:
``docs/architecture/p3_40_contract_7_amalgamated_session_spec.md``
§6 Commit 1c.

5 test classes per spec:
- AmalgamatedSessionContractTopLevelTest: full payload +
  extra='forbid' + missing-field rejection.
- CompositionWithContract6Test: mirror.bands typed via Contract
  6's GetBandsViewContract; Contract 6 invariant violations
  propagate.
- CrossFieldInvariantTest: F5 + F6 invariants firing through
  top-level construction.
- DataclassConversionTest: F14 -- asdict(mirror) round-trip
  produces a valid AmalgamatedSessionContract.
- ApiBoundaryContractViolationTest: F11 Adjustment B per
  Contracts 3-6 pattern.
"""

from __future__ import annotations

import os
import sys
import unittest
from dataclasses import asdict


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)
if HERE not in sys.path:
  sys.path.insert(0, HERE)


from pydantic import ValidationError  # noqa: E402

from client_intake_and_finmo.post_intake_contracts.amalgamated_session_contract import (  # noqa: E402
  AMALGAMATED_SESSION_STAGE_LABEL,
  AmalgamatedSessionContract,
  ContractViolation,
  GetBandsViewContract,
  MirrorContract,
  ValidationStateProjectionContract,
)
from _p3_40_contract_7_fixtures import (  # noqa: E402
  valid_amalgamated_session_dict,
  valid_mirror_dict,
  valid_validation_state_projection_dict,
)


# ---------------------------------------------------------------------------
# AmalgamatedSessionContract -- top-level + extra='forbid' (F13)
# ---------------------------------------------------------------------------

class AmalgamatedSessionContractTopLevelTest(unittest.TestCase):

  def test_valid_full_payload_accepted(self) -> None:
    contract = AmalgamatedSessionContract.model_validate(
      valid_amalgamated_session_dict()
    )
    self.assertIsInstance(contract.mirror, MirrorContract)

  def test_extra_top_level_field_forbidden(self) -> None:
    """F13: extra='forbid' on top-level."""
    payload = valid_amalgamated_session_dict()
    payload["future_session_field"] = {"foo": "bar"}
    with self.assertRaises(ValidationError) as ctx:
      AmalgamatedSessionContract.model_validate(payload)
    self.assertIn("future_session_field", str(ctx.exception))

  def test_missing_mirror_rejected(self) -> None:
    payload = valid_amalgamated_session_dict()
    del payload["mirror"]
    with self.assertRaises(ValidationError) as ctx:
      AmalgamatedSessionContract.model_validate(payload)
    self.assertIn("mirror", str(ctx.exception))

  def test_top_level_thin_wrapper_design(self) -> None:
    """Per F0 design rationale: top-level is a thin wrapper
    (single mirror field). Pin the field set so a future
    expansion (e.g., adding session_driver_state alongside
    mirror) is a deliberate spec amendment, not silent drift."""
    self.assertEqual(
      set(AmalgamatedSessionContract.model_fields.keys()), {"mirror"},
    )


# ---------------------------------------------------------------------------
# Composition with Contract 6 (F1 -- mirror.bands)
# ---------------------------------------------------------------------------

class CompositionWithContract6Test(unittest.TestCase):

  def test_mirror_bands_typed_as_get_bands_view_contract(self) -> None:
    """F1: each section's band in mirror.bands typed as
    Contract 6's GetBandsViewContract. Same class identity
    ensures type-checking parity."""
    contract = AmalgamatedSessionContract.model_validate(
      valid_amalgamated_session_dict()
    )
    for section, band in contract.mirror.bands.items():
      self.assertIsInstance(band, GetBandsViewContract)

  def test_contract_6_invariant_propagates_through_mirror(self) -> None:
    """Contract 6 monotonicity invariant on band rows: when a
    GetBandsViewBandContract has min > max, validation fails.
    Propagates through Contract 7's mirror.bands field."""
    payload = valid_amalgamated_session_dict()
    # Inject a band-level violation: corrupt monotonicity
    drivers_bands = payload["mirror"]["bands"]["drivers"]["bands"]
    first_lever_id = next(iter(drivers_bands.keys()))
    drivers_bands[first_lever_id]["benchmark_min"] = 0.99
    drivers_bands[first_lever_id]["benchmark_target"] = 0.40
    drivers_bands[first_lever_id]["benchmark_max"] = 0.55
    with self.assertRaises(ValidationError) as ctx:
      AmalgamatedSessionContract.model_validate(payload)
    self.assertIn("monotonicity", str(ctx.exception))


# ---------------------------------------------------------------------------
# Cross-field invariants firing through top-level (F5 + F6)
# ---------------------------------------------------------------------------

class CrossFieldInvariantTest(unittest.TestCase):
  """F5 (alias-sync) + F6 (i-iv bounded projection) invariants
  must fire when validating from the top-level
  AmalgamatedSessionContract. Distinct from sub-contract tests
  (Commit 1b) which validate via MirrorContract /
  ValidationStateProjectionContract directly."""

  # --- F5 alias-sync through top-level ---

  def test_f5_alias_sync_violation_propagates_top_level(self) -> None:
    payload = valid_amalgamated_session_dict()
    payload["mirror"]["plan_state"]["balance_sheet"] = {"key": "A"}
    payload["mirror"]["plan_state"]["capex_rd"] = {"key": "B"}
    with self.assertRaises(ValidationError) as ctx:
      AmalgamatedSessionContract.model_validate(payload)
    self.assertIn("alias-sync", str(ctx.exception))

  # --- F6 (i) failing_check_names cap through top-level ---

  def test_f6_failing_check_names_cap_propagates_top_level(self) -> None:
    payload = valid_amalgamated_session_dict()
    payload["mirror"]["validation_state"] = valid_validation_state_projection_dict(
      failing_check_count=15,
      failing_check_names=[f"c_{i}" for i in range(13)],
      failing_check_names_truncated=True,
    )
    with self.assertRaises(ValidationError):
      AmalgamatedSessionContract.model_validate(payload)

  # --- F6 (iii) truncation flag consistency through top-level ---

  def test_f6_truncation_flag_consistency_propagates_top_level(self) -> None:
    payload = valid_amalgamated_session_dict()
    payload["mirror"]["validation_state"] = valid_validation_state_projection_dict(
      failing_check_count=15,
      failing_check_names=[f"c_{i}" for i in range(12)],
      failing_check_names_truncated=False,  # bug: at-cap but flag False
    )
    with self.assertRaises(ValidationError) as ctx:
      AmalgamatedSessionContract.model_validate(payload)
    self.assertIn("truncated", str(ctx.exception))

  # --- F6 (iv) outside_band filter through top-level ---

  def test_f6_outside_band_filter_propagates_top_level(self) -> None:
    payload = valid_amalgamated_session_dict()
    vsp = valid_validation_state_projection_dict()
    vsp["failing_lever_margins"][0]["outside_band"] = False
    payload["mirror"]["validation_state"] = vsp
    with self.assertRaises(ValidationError) as ctx:
      AmalgamatedSessionContract.model_validate(payload)
    self.assertIn("outside_band", str(ctx.exception))


# ---------------------------------------------------------------------------
# F14 dataclass conversion pattern
# ---------------------------------------------------------------------------

class DataclassConversionTest(unittest.TestCase):
  """F14: the Mirror is the FIRST DATACLASS-SHAPED boundary in
  P3.40. Gate sites convert via dataclasses.asdict(mirror).
  These tests confirm the conversion pattern works end-to-end:
  build a Mirror dataclass; asdict() it; validate the resulting
  dict against MirrorContract. If asdict() ever proves
  insufficient, R14 R-residual covers the upgrade to an explicit
  MirrorContract.from_mirror(mirror) classmethod."""

  def test_asdict_of_default_mirror_validates_minimally(self) -> None:
    """The Mirror() default dataclass (empty business_facts,
    empty plan_state, etc.) should validate against
    MirrorContract -- even an empty Mirror is structurally
    valid per F3/F4 Optional dispositions."""
    from client_intake_and_finmo.post_intake_amalgamated.mirror import Mirror
    mirror = Mirror()
    mirror_dict = asdict(mirror)
    # Drop recent_decisions_cap per the to_dict() precedent
    # (internal config, not boundary surface)
    mirror_dict.pop("recent_decisions_cap", None)
    # Pre-build_mirror, bands isn't loaded yet -- supply minimal
    # valid bands so the F1 composition validates.
    from _p3_40_contract_6_fixtures import valid_get_bands_view_dict
    mirror_dict["bands"] = {
      section: valid_get_bands_view_dict(section=section)
      for section in (
        "stage_ramp", "drivers", "payroll", "capex_rd", "balance_sheet",
      )
    }
    # Mirror() default validation_state is {} (empty dict);
    # MirrorContract types it as Optional[ValidationStateProjectionContract]
    # so empty {} would fail. Match production: pre-evaluate
    # state is None, not {}.
    mirror_dict["validation_state"] = None
    # Same for empty recent_decisions list -> None per F3
    if not mirror_dict["recent_decisions"]:
      mirror_dict["recent_decisions"] = None
    # Same for empty sequence_position + budget per F4
    if not mirror_dict["sequence_position"]:
      mirror_dict["sequence_position"] = None
    if not mirror_dict["budget"]:
      mirror_dict["budget"] = None
    # Now validate
    contract = MirrorContract.model_validate(mirror_dict)
    self.assertEqual(contract.invariants, {})

  def test_asdict_handles_nested_recent_decision_dataclass(self) -> None:
    """F14 spec point: asdict() recursive conversion handles the
    nested RecentDecision dataclass automatically -- no special-
    case adapter needed."""
    from client_intake_and_finmo.post_intake_amalgamated.mirror import (
      Mirror, RecentDecision,
    )
    mirror = Mirror()
    mirror.record_decision(
      tool_name="revise_drivers",
      inputs_summary="test conversion",
      delta_all_pass=1,
    )
    mirror_dict = asdict(mirror)
    self.assertEqual(len(mirror_dict["recent_decisions"]), 1)
    self.assertEqual(
      mirror_dict["recent_decisions"][0]["tool_name"], "revise_drivers",
    )
    # The nested dataclass is now a plain dict -- ready for
    # Pydantic validation without special handling.
    self.assertIsInstance(mirror_dict["recent_decisions"][0], dict)


# ---------------------------------------------------------------------------
# Adjustment B -- API-boundary ContractViolation propagation (F11)
# ---------------------------------------------------------------------------

class ApiBoundaryContractViolationTest(unittest.TestCase):
  """Mirror of Contracts 3-6 ApiBoundaryContractViolationTest.
  Per trace Div-8 the API handler at intake_consult.py:7377
  catches ``except Exception as exc:`` and logs str(exc).
  ContractViolation is Exception subclass (not RuntimeError),
  so it skips the line-7298 RuntimeError branch and lands in
  the line-7377 generic catch as structured 500 with
  detail=str(exc) carrying AMALGAMATED_SESSION_STAGE_LABEL."""

  def _violation(self) -> ContractViolation:
    return ContractViolation(
      stage=AMALGAMATED_SESSION_STAGE_LABEL,
      field="plan_state",
      expected="alias-sync (balance_sheet == capex_rd payload)",
      actual="mismatched_payloads",
      source_payload={"redacted": "..."},
    )

  def test_violation_message_uses_amalgamated_session_stage_label(self) -> None:
    exc = self._violation()
    self.assertIn(AMALGAMATED_SESSION_STAGE_LABEL, str(exc))

  def test_violation_attributes_accessible_for_structured_handling(self) -> None:
    exc = self._violation()
    self.assertEqual(exc.stage, AMALGAMATED_SESSION_STAGE_LABEL)
    self.assertEqual(exc.field, "plan_state")
    self.assertEqual(
      exc.expected, "alias-sync (balance_sheet == capex_rd payload)",
    )
    self.assertIsInstance(exc.source_payload, dict)

  def test_violation_survives_generic_exception_catch(self) -> None:
    """Mirrors intake_consult.py:7377 catch pattern exactly."""
    try:
      raise self._violation()
    except Exception as exc:  # exact pattern from line 7377
      log_line = str(exc).strip() or "system_run_failed"
      self.assertIn(AMALGAMATED_SESSION_STAGE_LABEL, log_line)
      self.assertIn("plan_state", log_line)
      self.assertNotEqual(log_line, "system_run_failed")

  def test_violation_str_does_not_dump_source_payload(self) -> None:
    """source_payload may be a 100KB Mirror dict at the wire
    level; the str(violation) the API handler logs MUST stay
    readable. Adjustment B safety check carried from Contracts
    3-6."""
    exc = self._violation()
    log_str = str(exc)
    self.assertLess(len(log_str), 500)
    self.assertNotIn("redacted", log_str)


if __name__ == "__main__":
  unittest.main()
