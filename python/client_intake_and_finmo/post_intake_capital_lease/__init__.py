"""Capital lease integration subsystem (Phase 9 P3.16).

Pure deterministic Python schedule builder + validators + machinery
fail-fasts. Mirrors the post_intake_debt_schedule shape but with no
dedicated handler — capital lease is mechanical math given intake
inputs (cf. iter spec P3.16 §"NO HANDLER").
"""

from .schedule import (
  CAPITAL_LEASE_CONTRACT_VERSION,
  CAPITAL_LEASE_DEPRECIATION_QUARTERS,
  assert_capital_lease_schedule_payload_ready,
  assert_finmo_matches_capital_lease_schedule,
  assert_no_orphaned_capital_lease_schedule,
  build_capital_lease_schedule,
  build_capital_lease_schedule_snapshot,
  capital_lease_opening_seed,
  detect_orphaned_capital_lease_schedule,
  fail_fast_capital_lease_routing_double_count,
  fail_fast_lease_depreciation_components_misaligned,
  fail_fast_lease_interest_components_misaligned,
  validate_capital_lease_schedule_payload,
)

__all__ = [
  "CAPITAL_LEASE_CONTRACT_VERSION",
  "CAPITAL_LEASE_DEPRECIATION_QUARTERS",
  "assert_capital_lease_schedule_payload_ready",
  "assert_finmo_matches_capital_lease_schedule",
  "assert_no_orphaned_capital_lease_schedule",
  "build_capital_lease_schedule",
  "build_capital_lease_schedule_snapshot",
  "capital_lease_opening_seed",
  "detect_orphaned_capital_lease_schedule",
  "fail_fast_capital_lease_routing_double_count",
  "fail_fast_lease_depreciation_components_misaligned",
  "fail_fast_lease_interest_components_misaligned",
  "validate_capital_lease_schedule_payload",
]
