"""P3.41 NexGen E2E iter 8 — regression tests for the maintenance-
capex envelope unit-mismatch fix + sibling-check sweep.

Bug: _check_envelope_violations in
``post_intake_amalgamated/tools/set_capex_rd_balance_seed.py:42-91``
read ``mc_payload["maintenance_capex_percent"]`` (percent form,
0..100) against a [0, 1] bound (ratio form). Dead-on-arrival on any
valid maintenance-capex band emission (NexGen surfaced 2.14 > 1.0).

Fix: read ``mc_payload["maintenance_rate"]`` (the canonical ratio
form every downstream consumer reads at
``finmo_bridge.py:1266/:1331/:1695``); keep the [0, 1] sanity floor.

Sweep (per directive): the function has only two checks (mc + bs).
The ``rd_payload`` parameter is by-design unread (the R&D producer
returns ``{r_and_d_enabled: bool, ...}`` -- zero numeric fields).
The bs check reads ``seed_value`` against ``>= 0`` -- field/bound
match the producer's convention (days / ratio / currency all share
the non-negative-magnitude floor). No sibling bugs to fix.
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


from client_intake_and_finmo.post_intake_amalgamated.tools.set_capex_rd_balance_seed import (  # noqa: E402
  _check_envelope_violations,
)


def _violation_codes(violations):
  return {v.get("code") for v in violations}


class MaintenanceCapexEnvelopeReadsRatioFieldTest(unittest.TestCase):

  def test_valid_ratio_021_passes_envelope(self) -> None:
    """maintenance_rate = 0.0214 (the canonical ratio form NexGen
    actually emits) is in [0, 1]. Must pass with no violations.
    Before the fix, the corresponding maintenance_capex_percent
    value of 2.14 incorrectly tripped the [0, 1] check."""
    mc_payload = {"maintenance_capex_percent": 2.14, "maintenance_rate": 0.0214}
    violations = _check_envelope_violations(mc_payload, None, None)
    self.assertNotIn(
      "envelope_violation_maintenance_capex_out_of_unit_interval",
      _violation_codes(violations),
    )

  def test_old_percent_value_no_longer_trips(self) -> None:
    """Even if the producer still emits maintenance_capex_percent=2.14,
    the envelope check ignores it (now reading maintenance_rate
    instead). Pre-fix this exact payload tripped the unit-interval
    violation on every clean E2E."""
    mc_payload = {
      "maintenance_capex_percent": 2.14,  # was the bug-trigger
      "maintenance_rate": 0.0214,         # is the canonical field
    }
    violations = _check_envelope_violations(mc_payload, None, None)
    self.assertEqual(violations, [])

  def test_ratio_above_one_still_flagged(self) -> None:
    """A genuinely out-of-[0,1] maintenance_rate (e.g. 1.5 -> 150%)
    is still caught. Confirms the fix didn't drop the floor; just
    pointed it at the right field."""
    mc_payload = {"maintenance_rate": 1.5}
    violations = _check_envelope_violations(mc_payload, None, None)
    self.assertIn(
      "envelope_violation_maintenance_capex_out_of_unit_interval",
      _violation_codes(violations),
    )

  def test_negative_ratio_flagged(self) -> None:
    """[0, 1] floor still rejects negative ratios."""
    mc_payload = {"maintenance_rate": -0.01}
    violations = _check_envelope_violations(mc_payload, None, None)
    self.assertIn(
      "envelope_violation_maintenance_capex_out_of_unit_interval",
      _violation_codes(violations),
    )

  def test_non_finite_ratio_flagged(self) -> None:
    """Finite check survives the field rename."""
    mc_payload = {"maintenance_rate": float("inf")}
    violations = _check_envelope_violations(mc_payload, None, None)
    self.assertIn(
      "envelope_violation_maintenance_capex_not_finite",
      _violation_codes(violations),
    )

  def test_missing_maintenance_rate_is_no_violation(self) -> None:
    """When the field is absent the check is a no-op (matches the
    pre-fix `if pct is not None:` semantic, just on the right key)."""
    violations = _check_envelope_violations({}, None, None)
    self.assertEqual(violations, [])


class SiblingEnvelopeChecksSweepTest(unittest.TestCase):
  """Sweep confirmation that the two other arms of _check_envelope_
  violations are correct. rd_payload has no numeric fields to check
  (verified against the R&D producer at runner.py:1416-1426); bs
  check reads the right field for the right floor."""

  def test_rd_payload_unread_by_design(self) -> None:
    """R&D producer returns {r_and_d_enabled: bool, ...} with zero
    numeric fields. Passing any rd_payload shape must produce no
    rd-related violations (the function never inspects it)."""
    violations = _check_envelope_violations(
      None,
      {"r_and_d_enabled": True, "contract_version": "x", "rationale": "y"},
      None,
    )
    self.assertEqual(violations, [])
    # And with a deliberately-wrong rd payload -- still no violations,
    # confirming the parameter is intentionally pass-through.
    violations = _check_envelope_violations(
      None, {"r_and_d_enabled": "nonsense"}, None,
    )
    self.assertEqual(violations, [])

  def test_bs_seed_value_negative_flagged(self) -> None:
    """bs check reads seed_value against >= 0. A negative seed_value
    on an applicable row must trip the existing violation code."""
    bs_payload = {
      "balance_sheet_seed_grid": [
        {"lever_id": "balance_sheet::Owner's Capital", "applicable": True, "seed_value": -1.0},
      ],
    }
    violations = _check_envelope_violations(None, None, bs_payload)
    self.assertIn(
      "envelope_violation_balance_sheet_seed_negative",
      _violation_codes(violations),
    )

  def test_bs_seed_value_non_applicable_row_skipped(self) -> None:
    """Non-applicable rows are skipped per existing logic (the
    proposer sets seed_value=0 on these; we don't second-guess)."""
    bs_payload = {
      "balance_sheet_seed_grid": [
        {"lever_id": "balance_sheet::Inventory Days", "applicable": False, "seed_value": -1.0},
      ],
    }
    violations = _check_envelope_violations(None, None, bs_payload)
    self.assertEqual(violations, [])

  def test_bs_seed_value_zero_or_positive_passes(self) -> None:
    """Days / ratios / currency seed_values >= 0 must all pass the
    floor. Producer emits all three unit-types under this same
    field key; floor is unit-agnostic."""
    bs_payload = {
      "balance_sheet_seed_grid": [
        {"lever_id": "balance_sheet::Accounts Receivable Days",
         "applicable": True, "seed_value": 45.0},     # days
        {"lever_id": "balance_sheet::Prepaid Expenses (% of Revenue)",
         "applicable": True, "seed_value": 0.02},     # ratio
        {"lever_id": "balance_sheet::Owner's Capital",
         "applicable": True, "seed_value": 1200000.0},  # currency
        {"lever_id": "balance_sheet::Other Equity",
         "applicable": True, "seed_value": 0.0},      # zero is OK
      ],
    }
    violations = _check_envelope_violations(None, None, bs_payload)
    self.assertEqual(violations, [])


if __name__ == "__main__":
  unittest.main()
