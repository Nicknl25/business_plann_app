"""Phase 9 P3.10 iter 13 — remove cash-ceiling-based "surplus violation" concept.

Iter 13's failure analysis on NexGen revealed:
  - The cash all-or-nothing post-pass gate trips on surplus *ceiling*
    violations even when the buffer (floor) is satisfied.
  - For profitable mature businesses (NexGen) cash legitimately
    accumulates above the ceiling; the gate then reverts the entire
    cash strategy, so finalize observes the *pre-cash* state with its
    buffer violation Q1-Q9 still in place.

Fix scope:
  CHANGE 1 — distributions cap is floor-based:
              max(0, ending_cash - buffer_required)
              (was ceiling-based: max(0, ending_cash - cash_ceiling))
  CHANGE 2 — drop `cash_surplus_ceiling_violations` clause from
              `keep_changes` formula in runner.py
  CHANGE 3 — don't add quarters to violation_quarters when only
              `deployable_surplus > 0` (no buffer/distribution issue)
  CHANGE 4 — finalize already buffer-only (verified, no change)

Buffer (floor) check stays. Buffer math fix (3339fd8) stays.
All-or-nothing gate stays — only the surplus clause is dropped.
Proposer logic untouched. Surplus-cleanup pass can stay (will no-op
on the gate side; surplus tracking still informational).
"""

from __future__ import annotations

import os
import pathlib
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


CASH_PKG = pathlib.Path(PYTHON_ROOT) / "client_intake_and_finmo" / "post_intake_cash"
RUNNER_PATH = CASH_PKG / "runner.py"
VALIDATION_ENVELOPE_PATH = CASH_PKG / "validation_envelope.py"
PLANNING_ENVELOPE_PATH = CASH_PKG / "planning_envelope.py"
FINALIZE_PATH = (
  pathlib.Path(PYTHON_ROOT)
  / "client_intake_and_finmo"
  / "post_intake_runtime_validation"
  / "finalize_post_intake.py"
)


class Change2DropSurplusCeilingClauseFromKeepChangesTest(unittest.TestCase):
  """The all-or-nothing keep_changes gate must NOT include surplus-ceiling."""

  @staticmethod
  def _keep_changes_block(text: str) -> str:
    keep_idx = text.find("keep_changes = bool(")
    assert keep_idx > 0, "keep_changes formula must exist in runner.py"
    # Match the closing ')' of bool(...): it sits on its own line at 2-space indent
    end_idx = text.find("\n  )", keep_idx)
    assert end_idx > keep_idx, "keep_changes bool(...) close not found"
    return text[keep_idx:end_idx]

  def test_keep_changes_does_not_reference_cash_surplus_ceiling_violations(self) -> None:
    text = RUNNER_PATH.read_text(encoding="utf-8")
    block = self._keep_changes_block(text)
    self.assertNotIn(
      "cash_surplus_ceiling_violations",
      block,
      "CHANGE 2: keep_changes must NOT reference cash_surplus_ceiling_violations — "
      "ceiling-based surplus is no longer a hard violation.",
    )

  def test_keep_changes_still_references_buffer_and_distribution(self) -> None:
    text = RUNNER_PATH.read_text(encoding="utf-8")
    block = self._keep_changes_block(text)
    self.assertIn(
      "cash_buffer_violations", block,
      "Buffer (floor) check must remain in keep_changes",
    )
    self.assertIn(
      "cash_distribution_violations", block,
      "Distribution-while-below-buffer check must remain in keep_changes",
    )
    self.assertIn(
      "cash_contract_failures", block,
      "Cash-contract failures must remain in keep_changes",
    )

  def test_cash_failed_rule_codes_does_not_use_surplus_ceiling(self) -> None:
    text = RUNNER_PATH.read_text(encoding="utf-8")
    self.assertNotIn(
      "if cash_surplus_ceiling_violations:\n    cash_failed_rule_codes.append",
      text,
      "CHANGE 2: cash_failed_rule_codes must NOT be populated by surplus-ceiling violations",
    )


class Change1DistributionsCapIsFloorBasedTest(unittest.TestCase):
  """`max_additional_distribution` must use buffer (floor), not ceiling."""

  def test_validation_envelope_distributions_cap_uses_buffer_required(self) -> None:
    text = VALIDATION_ENVELOPE_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "max_additional_distribution = int(",
      text,
      "CHANGE 1: validation_envelope.py must define max_additional_distribution explicitly",
    )
    self.assertIn(
      "max(0, effective_ending_cash - buffer_required)",
      text,
      "CHANGE 1: distributions cap must be floor-based (ending_cash - buffer_required)",
    )

  def test_planning_envelope_distributions_cap_uses_buffer_required(self) -> None:
    text = PLANNING_ENVELOPE_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "max_additional_distribution = int(",
      text,
      "CHANGE 1: planning_envelope.py must define max_additional_distribution explicitly",
    )
    self.assertIn(
      "max(0, effective_ending_cash - buffer_required)",
      text,
      "CHANGE 1: planning_envelope.py distributions cap must be floor-based",
    )

  def test_distributions_cap_payload_field_uses_floor_value_in_validation_envelope(self) -> None:
    text = VALIDATION_ENVELOPE_PATH.read_text(encoding="utf-8")
    self.assertNotIn(
      '"max_additional_distribution": deployable_surplus',
      text,
      "CHANGE 1: validation_envelope payload must NOT set "
      "max_additional_distribution = deployable_surplus (the ceiling-based value)",
    )

  def test_distributions_cap_payload_field_uses_floor_value_in_planning_envelope(self) -> None:
    text = PLANNING_ENVELOPE_PATH.read_text(encoding="utf-8")
    self.assertNotIn(
      '"max_additional_distribution": deployable_surplus',
      text,
      "CHANGE 1: planning_envelope payload must NOT set "
      "max_additional_distribution = deployable_surplus",
    )


class Change3SurplusQuartersDoNotEnterViolationQuartersTest(unittest.TestCase):
  """Quarters with only `deployable_surplus > 0` must NOT enter
  `violation_quarters` — they are NOT violations under the new policy."""

  def test_validation_envelope_does_not_classify_surplus_as_violation_quarter(self) -> None:
    text = VALIDATION_ENVELOPE_PATH.read_text(encoding="utf-8")
    # The pattern we removed: surplus_deployment append immediately
    # followed by an unconditional violation_quarters append.
    self.assertNotIn(
      "surplus_deployment_quarters.append(quarter_index)\n      violation_quarters.append(quarter_index)",
      text,
      "CHANGE 3: validation_envelope must NOT add surplus quarters to violation_quarters",
    )

  def test_planning_envelope_does_not_classify_surplus_as_violation_quarter(self) -> None:
    text = PLANNING_ENVELOPE_PATH.read_text(encoding="utf-8")
    # Pattern from first pass:
    self.assertNotIn(
      "surplus_deployment_quarters.append(quarter_index)\n      violation_quarters.append(quarter_index)",
      text,
      "CHANGE 3: planning_envelope first pass must NOT add surplus quarters to violation_quarters",
    )
    # Pattern from second pass (uses quarter_payload.get):
    second_pass_anti = (
      "if deployable_surplus > 0:\n"
      "      violation_quarters.append(int(quarter_payload.get(\"quarter_index\") or 0))"
    )
    self.assertNotIn(
      second_pass_anti, text,
      "CHANGE 3: planning_envelope second pass must NOT add surplus quarters to violation_quarters",
    )

  def test_validation_envelope_still_tracks_surplus_quarters_for_diagnostics(self) -> None:
    """Surplus tracking must remain — only the violation classification is removed."""
    text = VALIDATION_ENVELOPE_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "surplus_deployment_quarters",
      text,
      "Surplus tracking must remain (informational, not a violation)",
    )

  def test_planning_envelope_still_tracks_surplus_quarters_for_diagnostics(self) -> None:
    text = PLANNING_ENVELOPE_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "surplus_deployment_quarters",
      text,
      "Surplus tracking must remain (informational, not a violation)",
    )


class Change4FinalizeHasNoSeparateCeilingCheckTest(unittest.TestCase):
  """Finalize's hard gate must be buffer-only — no ceiling enforcement."""

  def test_finalize_imports_buffer_only_assertion(self) -> None:
    text = FINALIZE_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "assert_post_intake_cash_buffer_integrity",
      text,
      "Finalize must invoke the buffer-only integrity assertion",
    )

  def test_finalize_does_not_raise_on_ceiling_excess(self) -> None:
    text = FINALIZE_PATH.read_text(encoding="utf-8")
    # The diagnostic logs `surplus_violation=` for visibility, but no
    # `raise` may be conditioned on a ceiling excess in finalize.
    # Detect the anti-pattern: a raise statement in the same line as
    # an ending_cash-vs-ceiling comparison.
    forbidden_substrings = (
      "raise RuntimeError(f\"surplus_violation",
      "raise PostIntakePreconditionFailed(\"surplus_violation",
      "post_intake_fail_fast_raise(\n    \"post_intake_cash_surplus",
    )
    for forbidden in forbidden_substrings:
      self.assertNotIn(forbidden, text, f"Finalize must not raise on ceiling excess: {forbidden!r}")


class ModulesStillImportCleanlyTest(unittest.TestCase):
  def test_runner_imports_clean(self) -> None:
    from client_intake_and_finmo.post_intake_cash import runner  # noqa: WPS433
    self.assertTrue(callable(runner._validate_cash_strategy_post_pass))

  def test_validation_envelope_imports_clean(self) -> None:
    from client_intake_and_finmo.post_intake_cash import validation_envelope  # noqa: WPS433
    self.assertTrue(callable(validation_envelope.build_cash_validation_envelope))

  def test_planning_envelope_imports_clean(self) -> None:
    from client_intake_and_finmo.post_intake_cash import planning_envelope  # noqa: WPS433
    self.assertTrue(callable(planning_envelope.build_cash_planning_envelope))

  def test_finalize_imports_clean(self) -> None:
    from client_intake_and_finmo.post_intake_runtime_validation import finalize_post_intake  # noqa: WPS433
    self.assertTrue(callable(finalize_post_intake.run_finalize_post_intake_validation))


if __name__ == "__main__":
  unittest.main()
