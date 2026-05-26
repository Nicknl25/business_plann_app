"""Per-sub-contract acceptance tests for Contract 7
(AmalgamatedSessionContract). FINAL contract in P3.40 sequence.

Spec: ``docs/architecture/p3_40_contract_7_amalgamated_session_spec.md``
§6 Commit 1b. Top-level + cross-field tests land in
``test_p3_40_contract_7_amalgamated_session.py`` (Commit 1c).

7 test classes covering all sub-contracts + the 5 cross-field
invariants + the vocabulary constants + extra-policy.
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

from client_intake_and_finmo.post_intake_contracts.amalgamated_session_contract import (  # noqa: E402
  AMALGAMATED_SESSION_STAGE_LABEL,
  PLAN_STATE_ALIAS_TRIPLET,
  SUPPORTED_SECTIONS,
  SUPPORTED_STRICTNESS_VALUES,
  VALIDATION_STATE_RENDER_CAP,
  LeverMarginEntryContract,
  MirrorContract,
  ValidationStateProjectionContract,
)
from _p3_40_contract_7_fixtures import (  # noqa: E402
  valid_lever_margin_entry_dict,
  valid_mirror_dict,
  valid_plan_state_dict,
  valid_validation_state_projection_dict,
)


# ---------------------------------------------------------------------------
# RecentDecisionContractTest REMOVED per P3.40 Cleanup 3/6 R10
# (RecentDecisionContract + RecentDecision + record_decision all
# dropped upstream). Phantom-write status confirmed via reader/
# writer audit -- zero production callers of record_decision.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# LeverMarginEntryContract (F6 (iv) + F8)
# ---------------------------------------------------------------------------

class LeverMarginEntryContractTest(unittest.TestCase):

  def test_valid_8_field_entry_accepted(self) -> None:
    entry = LeverMarginEntryContract.model_validate(
      valid_lever_margin_entry_dict()
    )
    self.assertEqual(entry.lever_id, "gross_margin_percent_lever")
    self.assertTrue(entry.outside_band)
    self.assertEqual(len(LeverMarginEntryContract.model_fields), 8)

  def test_outside_band_required(self) -> None:
    """outside_band is a required bool (not Optional)."""
    payload = valid_lever_margin_entry_dict()
    del payload["outside_band"]
    with self.assertRaises(ValidationError):
      LeverMarginEntryContract.model_validate(payload)

  def test_outside_band_false_accepted_at_entry_level(self) -> None:
    """Per the contract module's docstring: this entry-level
    contract permits outside_band=False so tests can construct
    rejection cases for the parent ValidationStateProjection
    contract's F6 (iv) lever_margins_all_outside_band
    validator. The filter invariant fires at the parent level."""
    payload = valid_lever_margin_entry_dict(outside_band=False)
    entry = LeverMarginEntryContract.model_validate(payload)
    self.assertFalse(entry.outside_band)

  def test_section_literal_typo_rejected(self) -> None:
    """F8: section Literal of 5 SECTIONS."""
    payload = valid_lever_margin_entry_dict()
    payload["section"] = "drvers"  # typo
    with self.assertRaises(ValidationError):
      LeverMarginEntryContract.model_validate(payload)

  def test_pinned_min_max_default_false(self) -> None:
    payload = valid_lever_margin_entry_dict()
    del payload["pinned_min"]
    del payload["pinned_max"]
    entry = LeverMarginEntryContract.model_validate(payload)
    self.assertFalse(entry.pinned_min)
    self.assertFalse(entry.pinned_max)


# ---------------------------------------------------------------------------
# ValidationStateProjectionContract (F6 i-iv + F7)
# ---------------------------------------------------------------------------

class ValidationStateProjectionContractTest(unittest.TestCase):

  def test_valid_11_field_payload_accepted(self) -> None:
    contract = ValidationStateProjectionContract.model_validate(
      valid_validation_state_projection_dict()
    )
    self.assertEqual(contract.round_number, 3)
    self.assertEqual(len(ValidationStateProjectionContract.model_fields), 11)

  def test_strictness_mini_finmo_accepted(self) -> None:
    """F7: 'mini_finmo' accepted."""
    payload = valid_validation_state_projection_dict(strictness="mini_finmo")
    ValidationStateProjectionContract.model_validate(payload)

  def test_strictness_full_acceptance_gate_accepted(self) -> None:
    payload = valid_validation_state_projection_dict(
      strictness="full_acceptance_gate",
    )
    ValidationStateProjectionContract.model_validate(payload)

  def test_strictness_typo_rejected(self) -> None:
    """F7 typo-lock pair (Contract 1 pattern)."""
    payload = valid_validation_state_projection_dict(strictness="mini_finmoo")
    with self.assertRaises(ValidationError):
      ValidationStateProjectionContract.model_validate(payload)

  # --- F6 (i) failing_check_names cap ---

  def test_failing_check_names_at_cap_accepted_if_truncated(self) -> None:
    """F6 (i) + (iii): exactly cap (12) entries is accepted IF
    truncated flag is True (one-half check)."""
    payload = valid_validation_state_projection_dict(
      failing_check_count=15,
      failing_check_names=[f"check_{i}" for i in range(VALIDATION_STATE_RENDER_CAP)],
      failing_check_names_truncated=True,
    )
    ValidationStateProjectionContract.model_validate(payload)

  def test_failing_check_names_above_cap_rejected(self) -> None:
    """F6 (i): > 12 entries rejected at field-level."""
    payload = valid_validation_state_projection_dict(
      failing_check_count=15,
      failing_check_names=[f"check_{i}" for i in range(VALIDATION_STATE_RENDER_CAP + 1)],
      failing_check_names_truncated=True,
    )
    with self.assertRaises(ValidationError):
      ValidationStateProjectionContract.model_validate(payload)

  # --- F6 (ii) failing_lever_margins cap ---

  def test_failing_lever_margins_above_cap_rejected(self) -> None:
    """F6 (ii): > 12 entries rejected."""
    payload = valid_validation_state_projection_dict(
      failing_lever_margins_count=VALIDATION_STATE_RENDER_CAP + 1,
      failing_lever_margins_truncated=True,
    )
    with self.assertRaises(ValidationError):
      ValidationStateProjectionContract.model_validate(payload)

  # --- F6 (iii) truncation flag consistency ---

  def test_truncation_flag_required_when_at_cap_failing_checks(self) -> None:
    """F6 (iii): when failing_check_names is at-or-above cap
    AND truncated flag is False, reject."""
    payload = valid_validation_state_projection_dict(
      failing_check_count=15,
      failing_check_names=[f"check_{i}" for i in range(VALIDATION_STATE_RENDER_CAP)],
      failing_check_names_truncated=False,  # bug: should be True
    )
    with self.assertRaises(ValidationError) as ctx:
      ValidationStateProjectionContract.model_validate(payload)
    self.assertIn("truncated", str(ctx.exception))

  def test_truncation_flag_required_when_at_cap_lever_margins(self) -> None:
    """F6 (iii): mirror check for lever margins."""
    payload = valid_validation_state_projection_dict(
      failing_lever_margins_count=VALIDATION_STATE_RENDER_CAP,
      failing_lever_margins_truncated=False,  # bug
    )
    with self.assertRaises(ValidationError) as ctx:
      ValidationStateProjectionContract.model_validate(payload)
    self.assertIn("truncated", str(ctx.exception))

  # --- F6 (iv) outside_band filter ---

  def test_lever_margins_with_outside_band_false_rejected(self) -> None:
    """F6 (iv): every failing_lever_margins entry must have
    outside_band=True (Bug 3 producer filter encoded). An entry
    with outside_band=False represents a producer-side regression
    (filter was bypassed)."""
    payload = valid_validation_state_projection_dict()
    # Inject one bad entry with outside_band=False
    payload["failing_lever_margins"][0]["outside_band"] = False
    with self.assertRaises(ValidationError) as ctx:
      ValidationStateProjectionContract.model_validate(payload)
    self.assertIn("outside_band", str(ctx.exception))


# ---------------------------------------------------------------------------
# MirrorContract (F1 composition + F2 DEFER + F5 alias-sync + F13)
# ---------------------------------------------------------------------------

class MirrorContractTest(unittest.TestCase):

  def test_valid_full_payload_accepted(self) -> None:
    mirror = MirrorContract.model_validate(valid_mirror_dict())
    # 9 -> 6 post-Cleanup-3/6: recent_decisions +
    # sequence_position + budget dropped per R10 + R11.
    self.assertEqual(len(MirrorContract.model_fields), 6)
    self.assertIsNotNone(mirror.validation_state)

  def test_minimal_payload_accepted_without_optionals(self) -> None:
    """validation_state Optional per F4. recent_decisions /
    sequence_position / budget DROPPED per Cleanup 3/6 R10 +
    R11; no longer on MirrorContract."""
    mirror = MirrorContract.model_validate(valid_mirror_dict(
      include_validation_state=False,
    ))
    self.assertIsNone(mirror.validation_state)
    # R10/R11 closure: these attributes are gone from MirrorContract
    self.assertFalse(hasattr(mirror, "recent_decisions"))
    self.assertFalse(hasattr(mirror, "sequence_position"))
    self.assertFalse(hasattr(mirror, "budget"))

  # --- F5 plan_state_alias_sync invariant ---

  def test_alias_sync_matching_payloads_accepted(self) -> None:
    """F5: when balance_sheet + capex_rd both hold SAME payload,
    validator passes."""
    payload = valid_mirror_dict(alias_payload={"key": "shared"})
    mirror = MirrorContract.model_validate(payload)
    self.assertEqual(
      mirror.plan_state["balance_sheet"], mirror.plan_state["capex_rd"],
    )

  def test_alias_sync_mismatched_payloads_rejected(self) -> None:
    """F5: when balance_sheet + capex_rd hold DIFFERENT payloads,
    validator fires."""
    payload = valid_mirror_dict()
    payload["plan_state"]["balance_sheet"] = {"key": "A"}
    payload["plan_state"]["capex_rd"] = {"key": "B"}
    with self.assertRaises(ValidationError) as ctx:
      MirrorContract.model_validate(payload)
    self.assertIn("alias-sync", str(ctx.exception))

  def test_alias_sync_only_one_alias_present_accepted(self) -> None:
    """F5: when only balance_sheet is present (capex_rd absent),
    no constraint -- sub-condition documented in §4.1."""
    payload = valid_mirror_dict()
    del payload["plan_state"]["capex_rd"]
    mirror = MirrorContract.model_validate(payload)
    self.assertIn("balance_sheet", mirror.plan_state)
    self.assertNotIn("capex_rd", mirror.plan_state)

  def test_alias_sync_no_aliases_present_accepted(self) -> None:
    """F5: when NEITHER alias key is present (pre-commit Mirror
    state), no constraint."""
    payload = valid_mirror_dict()
    del payload["plan_state"]["balance_sheet"]
    del payload["plan_state"]["capex_rd"]
    mirror = MirrorContract.model_validate(payload)
    self.assertNotIn("balance_sheet", mirror.plan_state)

  # --- F13 extra='forbid' on top-level Mirror ---

  def test_extra_field_on_mirror_rejected(self) -> None:
    payload = valid_mirror_dict()
    payload["future_mirror_field"] = "anything"
    with self.assertRaises(ValidationError):
      MirrorContract.model_validate(payload)

  # --- F1 composition with Contract 6 ---

  def test_bands_typed_as_get_bands_view_contract(self) -> None:
    """F1: mirror.bands typed as
    Dict[Literal[5 SECTIONS], GetBandsViewContract]."""
    mirror = MirrorContract.model_validate(valid_mirror_dict())
    from client_intake_and_finmo.post_intake_contracts.industry_baseline_resolved_contract import (
      GetBandsViewContract,
    )
    for section in SUPPORTED_SECTIONS:
      self.assertIsInstance(mirror.bands[section], GetBandsViewContract)


# ---------------------------------------------------------------------------
# Vocabulary constants alignment (Contract 1 typo-lock pattern)
# ---------------------------------------------------------------------------

class VocabularyConstantsTest(unittest.TestCase):

  def test_supported_sections_matches_5_tuple(self) -> None:
    self.assertEqual(
      SUPPORTED_SECTIONS,
      ("stage_ramp", "drivers", "payroll", "capex_rd", "balance_sheet"),
    )

  def test_supported_strictness_matches_2_tuple(self) -> None:
    self.assertEqual(
      SUPPORTED_STRICTNESS_VALUES, ("mini_finmo", "full_acceptance_gate"),
    )

  def test_validation_state_render_cap_is_12(self) -> None:
    self.assertEqual(VALIDATION_STATE_RENDER_CAP, 12)

  def test_plan_state_alias_triplet_matches_3_tuple(self) -> None:
    self.assertEqual(
      PLAN_STATE_ALIAS_TRIPLET,
      ("balance_sheet", "capex_rd_balance_seed", "capex_rd"),
    )

  def test_stage_label_matches(self) -> None:
    self.assertEqual(
      AMALGAMATED_SESSION_STAGE_LABEL,
      "INDUSTRY_BASELINE->AMALGAMATED_SESSION",
    )


# ---------------------------------------------------------------------------
# extra policy (F13)
# ---------------------------------------------------------------------------

class ExtraPolicyTest(unittest.TestCase):
  """F13: extra='ignore' on sub-contracts
  (ValidationStateProjection, LeverMarginEntry). MirrorContract
  uses extra='forbid' top-level. Top-level
  AmalgamatedSessionContract also extra='forbid'.

  Cleanup 3/6 R10: RecentDecision extra-ignore test removed
  (RecentDecisionContract dropped)."""

  def test_validation_state_extra_ignored(self) -> None:
    payload = valid_validation_state_projection_dict()
    payload["future_diagnostic"] = 42
    vsp = ValidationStateProjectionContract.model_validate(payload)
    self.assertFalse(hasattr(vsp, "future_diagnostic"))

  def test_lever_margin_extra_ignored(self) -> None:
    payload = valid_lever_margin_entry_dict()
    payload["future_diagnostic"] = "anything"
    lme = LeverMarginEntryContract.model_validate(payload)
    self.assertFalse(hasattr(lme, "future_diagnostic"))


if __name__ == "__main__":
  unittest.main()
