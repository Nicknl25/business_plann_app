"""Phase 9 P3.32 K1 F7 — pre-cash gate routes RICH payroll
violations to Handler C.

The K1 F5 implementation (orchestrator.py pre-cash gate Handler C
route) constructed failure_details from the orchestrator's
TRANSLATED failing_metrics, which carry actual_value=0.0 and
bounds=None for payroll violations (the translator at
_evaluate_gpt_authorable_pre_cash_checks reads "actual_ratio" /
"stage_ramp_max_ratio" keys that only exist on stage_ramp_expense
violations, NOT on payroll_revenue_feasibility_violations).

Handler C's _compact_payroll_failure_for_gpt at schedule.py:514
extracts violation context for the GPT prompt's previous_contract_
failure. It reads "violations" or "payroll_revenue_feasibility_
violations" keys with rich fields like payroll_percent_of_revenue,
effective_min_pct_with_tolerance, effective_max_pct_with_tolerance,
and deterministic_driver_math (precise quantitative repair
direction).

If F5 doesn't populate the compactor-expected keys with rich
violations, Handler C's GPT iterates blind. Skyward Express
timed out at 180s on this issue.

K1 F7 fix:
  - F5 calls payroll_revenue_feasibility_violations directly to
    compute fresh rich violations from current state.
  - Puts them under failure_details["violations"] (the canonical
    compactor-read key).
  - Compactor finds them, extracts payroll_percent_of_revenue +
    bounds + deterministic_driver_math, feeds them to GPT.
  - GPT receives precise repair direction, converges faster.

DOCTRINE THREE-SURFACE CHECK:
  Q1. Surfaces: payroll feasibility violations are computed by
      payroll_revenue_feasibility_violations() from
      payroll_headcount + finmo_json. Consumed by Handler C via
      _compact_payroll_failure_for_gpt.
  Q2. Alignment: same source data (payroll_headcount, finmo_json
      after F6 re-sync). Same helper called.
  Q3. This fix preserves alignment: YES — F7 calls the canonical
      helper directly; no parallel implementation.

This file pins:
  - F5 (now extended by F7) computes rich violations via the
    canonical helper.
  - Failure details include the "violations" key (compactor's
    canonical lookup).
  - Compactor extracts the rich fields and Handler C receives
    them.
  - The fix preserves K1 F1-F6 structural closures.
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


class TestF7CallsCanonicalViolationsHelper(unittest.TestCase):
  """F7 must compute rich violations via the canonical helper,
  not by relying on the orchestrator's lossy translation."""

  @staticmethod
  def _orchestrator_source() -> str:
    path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo", "post_intake_solver",
      "orchestrator.py",
    )
    with open(path, "r", encoding="utf-8") as fh:
      return fh.read()

  def test_orchestrator_imports_payroll_revenue_feasibility_violations(self) -> None:
    src = self._orchestrator_source()
    self.assertIn(
      "payroll_revenue_feasibility_violations",
      src,
      msg="F5 (extended by F7) must call payroll_revenue_feasibility_violations",
    )

  def test_orchestrator_contains_f7_marker(self) -> None:
    src = self._orchestrator_source()
    self.assertIn("Phase 9 P3.32 K1 F7", src)


class TestF7FailureDetailsHasCanonicalViolationsKey(unittest.TestCase):
  """The compactor at schedule.py:560-564 looks for keys named
  'violations' or 'payroll_revenue_feasibility_violations'.
  Failure details must include 'violations' so the compactor
  finds rich data and feeds it to GPT."""

  @staticmethod
  def _orchestrator_source() -> str:
    path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo", "post_intake_solver",
      "orchestrator.py",
    )
    with open(path, "r", encoding="utf-8") as fh:
      return fh.read()

  def test_failure_details_contains_violations_key(self) -> None:
    src = self._orchestrator_source()
    # Look for "violations": _rich_payroll_violations (or similar)
    # somewhere in the F7 block.
    f7_start = src.find("Phase 9 P3.32 K1 F7")
    self.assertGreater(f7_start, 0, "F7 block marker not found")
    f7_section = src[f7_start: f7_start + 5000]
    self.assertIn(
      "\"violations\": _rich_payroll_violations",
      f7_section,
      msg=(
        "F7 must put rich violations under the canonical "
        "'violations' key so Handler C compactor finds them"
      ),
    )


class TestCompactorReadsViolationsKey(unittest.TestCase):
  """Pin the compactor's interface contract. F7 relies on this
  contract; if the compactor changes its lookup keys, F7 breaks
  silently."""

  def test_compactor_reads_violations_or_payroll_revenue_feasibility_violations(self) -> None:
    path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo", "post_intake_headcount",
      "schedule.py",
    )
    with open(path, "r", encoding="utf-8") as fh:
      src = fh.read()
    # The compactor function name
    self.assertIn("def _compact_payroll_failure_for_gpt(", src)
    # The lookup pattern
    self.assertIn("\"payroll_revenue_feasibility_violations\"", src)
    self.assertIn("\"violations\"", src)


class TestPayrollFeasibilityViolationsCarryRichFields(unittest.TestCase):
  """The payroll_revenue_feasibility_violations helper produces
  dicts with specific rich fields the compactor extracts and
  feeds to GPT. If the helper's output schema changes, F7's
  call to it loses signal silently."""

  @staticmethod
  def _schedule_source() -> str:
    path = os.path.join(
      PYTHON_ROOT, "client_intake_and_finmo", "post_intake_headcount",
      "schedule.py",
    )
    with open(path, "r", encoding="utf-8") as fh:
      return fh.read()

  def test_violations_carry_payroll_percent_of_revenue(self) -> None:
    self.assertIn("\"payroll_percent_of_revenue\": round(", self._schedule_source())

  def test_violations_carry_effective_bounds(self) -> None:
    src = self._schedule_source()
    self.assertIn("\"effective_min_pct_with_tolerance\":", src)
    self.assertIn("\"effective_max_pct_with_tolerance\":", src)

  def test_violations_carry_deterministic_driver_math(self) -> None:
    src = self._schedule_source()
    self.assertIn("\"deterministic_driver_math\":", src)


class TestF7PreservesK1F1ThroughF6Invariants(unittest.TestCase):
  """F7 must operate within K1 F1-F6's structural closures."""

  def test_exhaustion_handler_still_excludes_payroll(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (  # noqa: WPS433
      GPT_AUTHORED_LEVER_IDS,
    )
    self.assertNotIn("expenses::Payroll", GPT_AUTHORED_LEVER_IDS)

  def test_target_solver_still_excludes_payroll(self) -> None:
    from client_intake_and_finmo.post_intake_target_solver.target_solver import (  # noqa: WPS433
      _HANDLER_C_OWNED_LEVER_IDS,
    )
    self.assertIn("expenses::Payroll", _HANDLER_C_OWNED_LEVER_IDS)

  def test_route_payroll_feasibility_primitive_still_callable(self) -> None:
    from client_intake_and_finmo.post_intake_headcount.feasibility_repair import (  # noqa: WPS433
      route_payroll_feasibility_to_handler_c,
    )
    self.assertTrue(callable(route_payroll_feasibility_to_handler_c))


if __name__ == "__main__":
  unittest.main()
