"""P3.41 round-1 set-tool audit batch — regression tests for F-J1 +
F-C1 + F-C2 fixes.

Audit catalog: docs/architecture/round1_set_tool_boundary_audit.md
(commit 79ac6ef).

F-J1: post_intake_contracts/runner.py operational branch of
_stage_family_ni_floors was hardcoded as
[0.0]*4 + [0.02]*16, ignoring the planning-mode-policy floor values
resolved into validator_rules. Surfaced by NexGen iter 9 on
normalize-mode (q11_q20_operational=0.05 -> 10 violations Q11..Q20).
Fix derives the 20-quarter array entirely from validator_rules.

F-C1: set_stage_ramp_contract envelope _RATIO_FIELDS_STAGE_RAMP listed
util_max + util_floor (dead -- producer emits max_util, no util_floor
anywhere). Rename + delete dead consistency check.

F-C2: set_payroll_schedule envelope had 2 dead subblocks (roles/wages
+ schedule) reading fields no producer emits. Deleted; only the live
target_payroll_percent_of_revenue arm remains.
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


# ---------------------------------------------------------------------------
# F-J1 -- operational ni_floor derivation is policy-driven, not hardcoded
# ---------------------------------------------------------------------------

class OperationalNiFloorPolicyDrivenTest(unittest.TestCase):
  """The operational branch of _stage_family_ni_floors must derive
  every quarter's floor from validator_rules; no literal floor value
  remains in the operational branch source."""

  def _floors(self, validator_rules):
    from client_intake_and_finmo.post_intake_contracts.runner import (
      _stage_family_ni_floors,
    )
    return _stage_family_ni_floors(
      stage_family="operational",
      validator_rules=validator_rules,
    )

  def test_normalize_operational_q11_q20_satisfies_validator_floor(self) -> None:
    """NexGen's iter-9 trip case: planning_mode=normalize,
    stage=operational sets q11_to_q20_min=0.05. Producer must emit
    Q11..Q20 >= 0.05 (the iter 9 STOP condition is fully resolved
    by this assertion)."""
    floors = self._floors({
      "q1_to_q20_min_net_income_margin_floor": 0.0,
      "q5_to_q20_min_net_income_margin_floor": 0.02,
      "q11_to_q20_min_net_income_margin_floor": 0.05,
      "operational_requires_nonnegative_from_q1": True,
    })
    self.assertEqual(len(floors), 20)
    for q in range(11, 21):
      self.assertGreaterEqual(
        floors[q - 1], 0.05,
        f"Q{q} floor {floors[q-1]} must be >= 0.05 (q11_to_q20 policy)",
      )

  def test_rebalance_operational_q11_q20_satisfies_validator_floor(self) -> None:
    """rebalance mode operational: q11_to_q20=0.07."""
    floors = self._floors({
      "q1_to_q20_min_net_income_margin_floor": 0.02,
      "q5_to_q20_min_net_income_margin_floor": 0.05,
      "q11_to_q20_min_net_income_margin_floor": 0.07,
      "operational_requires_nonnegative_from_q1": True,
    })
    for q in range(11, 21):
      self.assertGreaterEqual(floors[q - 1], 0.07)
    for q in range(5, 11):
      self.assertGreaterEqual(floors[q - 1], 0.05)
    for q in range(1, 5):
      self.assertGreaterEqual(floors[q - 1], 0.02)

  def test_preservation_operational_q11_q20_picks_higher_of_q5_or_q11(self) -> None:
    """preservation mode operational has q5_q10=0.05 and q11_q20=0.10;
    Q11+ floor must be max(both) = 0.10."""
    floors = self._floors({
      "q1_to_q20_min_net_income_margin_floor": 0.05,
      "q5_to_q20_min_net_income_margin_floor": 0.05,
      "q11_to_q20_min_net_income_margin_floor": 0.10,
      "operational_requires_nonnegative_from_q1": True,
    })
    for q in range(11, 21):
      self.assertGreaterEqual(floors[q - 1], 0.10)

  def test_floor_array_changes_with_policy(self) -> None:
    """Drive-by parity: changing the policy q11_q20 value changes
    the output -- proving derivation is from policy, not hardcoded."""
    floors_05 = self._floors({
      "q11_to_q20_min_net_income_margin_floor": 0.05,
      "operational_requires_nonnegative_from_q1": True,
    })
    floors_10 = self._floors({
      "q11_to_q20_min_net_income_margin_floor": 0.10,
      "operational_requires_nonnegative_from_q1": True,
    })
    self.assertNotEqual(floors_05[10:], floors_10[10:],
                        "Q11..Q20 must shift when q11_q20 policy changes")
    self.assertGreaterEqual(min(floors_10[10:]), 0.10)

  def test_no_policy_uses_universal_viability_zero(self) -> None:
    """When no policy floor is supplied (empty validator_rules), every
    quarter falls back to the universal viability floor (0.0 per
    post_intake_mapping.py:2956 doctrine). Note: validator-rules
    fallback at post_intake_mapping.py:2972-2977 always sets
    q11_to_q20=0.0 in real pipeline; this test exercises the
    defensive code path for a manually-built empty dict."""
    floors = self._floors({})
    self.assertEqual(len(floors), 20)
    for q in range(1, 21):
      self.assertEqual(floors[q - 1], 0.0)

  def test_no_literal_floor_numbers_in_operational_branch_source(self) -> None:
    """Audit-grade structural check: the operational branch source
    must contain no literal floor numbers in EXECUTABLE code
    (0.0 and 0.02 in particular). Historical references in COMMENTS
    are OK -- this test strips comments before the literal scan."""
    import inspect
    from client_intake_and_finmo.post_intake_contracts import runner as runner_mod
    src = inspect.getsource(runner_mod._stage_family_ni_floors)
    operational_marker = 'if str(stage_family).lower() == "operational":'
    op_start = src.find(operational_marker)
    self.assertGreater(op_start, 0, "operational branch marker not found")
    op_end = src.find("# Glide", op_start)
    if op_end < 0:
      op_end = len(src)
    operational_src = src[op_start:op_end]
    # Strip comment-only content for the literal scan -- references to
    # the historical 0.02 hardcode are permitted in the explanatory
    # comment block above the implementation.
    executable_lines = []
    for line in operational_src.splitlines():
      stripped = line.split("#", 1)[0]
      executable_lines.append(stripped)
    executable_src = "\n".join(executable_lines)
    self.assertNotIn(
      "0.02", executable_src,
      "operational branch executable code contains literal 0.02 -- hardcode regressed",
    )
    # The only 0.0 literal permitted in executable code is the
    # universal_viability_floor constant declaration.
    self.assertEqual(
      executable_src.count("0.0"),
      executable_src.count("universal_viability_floor = 0.0"),
      "executable code contains 0.0 literals beyond the universal_viability_floor declaration",
    )

  def test_operational_requires_nonnegative_clamp_applies(self) -> None:
    """When the flag is True, ALL quarters clamp to >= 0 even if a
    policy floor (or fallback) would otherwise be negative."""
    floors = self._floors({
      # Policy q1_q4 set negative (e.g., turnaround-style):
      "q1_to_q20_min_net_income_margin_floor": -0.10,
      "q5_to_q20_min_net_income_margin_floor": -0.05,
      "q11_to_q20_min_net_income_margin_floor": 0.0,
      "operational_requires_nonnegative_from_q1": True,
    })
    for q in range(1, 21):
      self.assertGreaterEqual(floors[q - 1], 0.0)

  def test_operational_requires_nonnegative_clamp_off_passes_negatives(self) -> None:
    """When the flag is False, negative policy floors flow through
    (e.g., turnaround mode operational q1_q4=-0.10, q5_q10=-0.05)."""
    floors = self._floors({
      "q1_to_q20_min_net_income_margin_floor": -0.10,
      "q5_to_q20_min_net_income_margin_floor": -0.05,
      "q11_to_q20_min_net_income_margin_floor": 0.0,
      "operational_requires_nonnegative_from_q1": False,
    })
    self.assertEqual(floors[0], -0.10)  # Q1
    self.assertEqual(floors[3], -0.10)  # Q4
    self.assertEqual(floors[4], -0.05)  # Q5
    self.assertEqual(floors[9], 0.0)    # Q10 (max(0.0, -0.05, q10_min_default))
    self.assertEqual(floors[10], 0.0)   # Q11 (max(0.0, -0.05, 0.0))


# ---------------------------------------------------------------------------
# F-C1 -- stage_ramp envelope max_util ratio bound is now live
# ---------------------------------------------------------------------------

class StageRampEnvelopeMaxUtilTest(unittest.TestCase):

  def test_max_util_above_one_now_flagged(self) -> None:
    """Pre-fix this trip-case fell through (envelope read 'util_max'
    which the producer never emits). Post-fix the envelope reads
    'max_util' -- matching the producer at runner.py:2017."""
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_stage_ramp_contract import (
      _check_envelope_violations,
    )
    contract = {
      "quarter_ramp_grid": [{"q": 1, "max_util": 1.5}],
    }
    violations = _check_envelope_violations(contract)
    codes = {v.get("code") for v in violations}
    self.assertIn("envelope_violation_ratio_out_of_unit_interval", codes)
    fields = {v.get("field") for v in violations if v.get("code") == "envelope_violation_ratio_out_of_unit_interval"}
    self.assertIn("max_util", fields)

  def test_max_util_valid_passes(self) -> None:
    """A valid max_util in [0, 1] produces no violation."""
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_stage_ramp_contract import (
      _check_envelope_violations,
    )
    contract = {"quarter_ramp_grid": [{"q": 1, "max_util": 0.75}]}
    violations = _check_envelope_violations(contract)
    codes = {v.get("code") for v in violations}
    self.assertNotIn("envelope_violation_ratio_out_of_unit_interval", codes)

  def test_old_util_max_no_longer_referenced(self) -> None:
    """The previous dead field name 'util_max' should not appear in
    the source (no false-coverage references). 'util_floor' must
    also be gone."""
    import inspect
    from client_intake_and_finmo.post_intake_amalgamated.tools import set_stage_ramp_contract as st
    src = inspect.getsource(st)
    self.assertNotIn('"util_max"', src,
                     "stale 'util_max' reference still present")
    self.assertNotIn('"util_floor"', src,
                     "stale 'util_floor' reference still present")
    self.assertNotIn("envelope_violation_util_max_below_floor", src,
                     "dead util_max >= util_floor consistency check not removed")


# ---------------------------------------------------------------------------
# F-C2 -- payroll envelope dead arms removed; surviving arm intact
# ---------------------------------------------------------------------------

class PayrollEnvelopeDeadArmsRemovedTest(unittest.TestCase):

  def test_target_payroll_arm_still_catches_out_of_unit_interval(self) -> None:
    """The LIVE arm (target_payroll_percent_of_revenue in [0,1])
    must still fire on bad values after the dead-arm cleanup."""
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_payroll_schedule import (
      _check_envelope_violations,
    )
    violations = _check_envelope_violations({"target_payroll_percent_of_revenue": 1.5})
    self.assertIn(
      "envelope_violation_payroll_target_out_of_unit_interval",
      {v.get("code") for v in violations},
    )

  def test_target_payroll_arm_still_catches_non_finite(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_payroll_schedule import (
      _check_envelope_violations,
    )
    violations = _check_envelope_violations({
      "target_payroll_percent_of_revenue": float("nan"),
    })
    self.assertIn(
      "envelope_violation_payroll_target_not_finite",
      {v.get("code") for v in violations},
    )

  def test_valid_target_payroll_passes(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_payroll_schedule import (
      _check_envelope_violations,
    )
    violations = _check_envelope_violations({
      "target_payroll_percent_of_revenue": 0.25,
    })
    self.assertEqual(violations, [])

  def test_dead_field_references_removed_from_source(self) -> None:
    """The dead-arm field names must not appear in the envelope source
    anymore. Prevents accidental resurrection of the dead checks.
    Note: the ``tools/__init__.py`` re-exports ``set_payroll_schedule``
    as the FUNCTION, so importing the submodule must use the full
    dotted path via importlib rather than the package re-export."""
    import importlib
    import inspect
    ps = importlib.import_module(
      "client_intake_and_finmo.post_intake_amalgamated.tools.set_payroll_schedule"
    )
    fn_src = inspect.getsource(ps._check_envelope_violations)
    for stale in ('"roles"', '"role_specs"', '"headcount"', '"fte_count"',
                  '"wage_per_employee"', '"wage"', '"schedule"',
                  '"quarter_schedule"', '"total_headcount"',
                  '"total_payroll_dollars"',
                  "envelope_violation_headcount_invalid",
                  "envelope_violation_wage_invalid",
                  "envelope_violation_schedule_quarter_negative"):
      self.assertNotIn(stale, fn_src,
                       f"dead reference {stale} still in envelope source")


if __name__ == "__main__":
  unittest.main()
