"""Phase 9 P3.10 iter 10 fix — buffer math units correction +
single-source-of-truth collapse.

Iter 10's diagnostic showed `cash_buffer_invalid` despite NexGen Q1
ending_cash ($993K) being well above the floor a `cash_floor_months=1.5`
SQL policy implies (~$750K).

Root cause: TWO parallel `buffer_components` implementations existed:
  - `post_intake_cash/runner.py:_cash_strategy_buffer_components`
    correctly divided opex_quarter by months_per_quarter to get
    monthly_opex before multiplying by floor_months.
  - `post_intake_cash/common.py:buffer_components` SKIPPED that
    division, multiplying QUARTERLY opex by floor_months — producing
    buffer thresholds 3x too large.

The validation envelope, planning envelope, and finalize cash-buffer
validator all called common.py's buggy version. The runner.py version
was used in different code paths.

Fix:
  - common.py:buffer_components now correctly divides by
    months_per_quarter (uses the parameter that was already declared
    but ignored).
  - runner.py:_cash_strategy_buffer_components is now a thin wrapper
    that delegates to common.py's canonical implementation. There is
    exactly ONE buffer-math implementation in the codebase.
"""

from __future__ import annotations

import os
import re
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


from client_intake_and_finmo.post_intake_cash import common as _common  # noqa: E402
from client_intake_and_finmo.post_intake_cash import runner as _runner  # noqa: E402


SYNTHETIC_ROW = {
  # opex_quarter = 1.5M total
  "cost_of_goods_sold": 600_000,
  "payroll": 400_000,
  "marketing": 100_000,
  "research_and_development": 0,
  "lease_rent": 24_000,
  "general_and_administrative": 376_000,
}


class BufferMathUnitsCorrectionTest(unittest.TestCase):
  def test_quarterly_opex_divided_by_months_per_quarter(self) -> None:
    """opex_quarter = $1.5M, months_per_quarter = 3 -> monthly_opex = $500K."""
    out = _common.buffer_components(
      SYNTHETIC_ROW,
      cash_floor_months=1.5,
      cash_ceiling_months=2.0,
      default_buffer_months=1.0,
      months_per_quarter=3.0,
    )
    self.assertEqual(out["operating_expense_quarter"], 1_500_000)
    self.assertEqual(out["monthly_opex"], 500_000)
    # cash_buffer_base_opex must be the monthly value, not the quarterly value
    # (pre-fix it was opex_quarter, despite being named "base_opex" alongside
    # a buffer multiplier in months).
    self.assertEqual(out["cash_buffer_base_opex"], 500_000)

  def test_buffer_required_is_monthly_opex_times_floor_months(self) -> None:
    """1.5 months of $500K monthly opex = $750K floor (NOT $2.25M)."""
    out = _common.buffer_components(
      SYNTHETIC_ROW,
      cash_floor_months=1.5,
      cash_ceiling_months=2.0,
      default_buffer_months=1.0,
      months_per_quarter=3.0,
    )
    self.assertEqual(out["cash_buffer_required"], 750_000)
    # Pre-fix value (3x) - guard against regression
    self.assertNotEqual(out["cash_buffer_required"], 2_250_000)

  def test_cash_ceiling_is_monthly_opex_times_ceiling_months(self) -> None:
    """2.0 months of $500K monthly opex = $1M ceiling (NOT $3M)."""
    out = _common.buffer_components(
      SYNTHETIC_ROW,
      cash_floor_months=1.5,
      cash_ceiling_months=2.0,
      default_buffer_months=1.0,
      months_per_quarter=3.0,
    )
    self.assertEqual(out["cash_ceiling"], 1_000_000)
    self.assertNotEqual(out["cash_ceiling"], 3_000_000)

  def test_zero_opex_yields_zero_buffer(self) -> None:
    out = _common.buffer_components(
      {},
      cash_floor_months=1.5,
      cash_ceiling_months=2.0,
      default_buffer_months=1.0,
      months_per_quarter=3.0,
    )
    self.assertEqual(out["monthly_opex"], 0)
    self.assertEqual(out["cash_buffer_required"], 0)
    self.assertEqual(out["cash_ceiling"], 0)

  def test_default_buffer_months_when_floor_is_none(self) -> None:
    """When cash_floor_months is None, default_buffer_months kicks in."""
    out = _common.buffer_components(
      SYNTHETIC_ROW,
      cash_floor_months=None,
      cash_ceiling_months=None,
      default_buffer_months=1.0,
      months_per_quarter=3.0,
    )
    # 1.0 months * $500K monthly = $500K floor
    self.assertEqual(out["cash_buffer_required"], 500_000)
    # ceiling defaults to max(floor, default_buffer_months) = 1.0 months
    self.assertEqual(out["cash_ceiling"], 500_000)


class SingleSourceOfTruthCollapseTest(unittest.TestCase):
  def test_runner_wrapper_delegates_to_common(self) -> None:
    """runner._cash_strategy_buffer_components and common.buffer_components
    must return identical values for the same inputs (single source of
    truth)."""
    common_out = _common.buffer_components(
      SYNTHETIC_ROW,
      cash_floor_months=1.5,
      cash_ceiling_months=2.0,
      default_buffer_months=1.0,
      months_per_quarter=3.0,
    )
    runner_out = _runner._cash_strategy_buffer_components(
      SYNTHETIC_ROW,
      cash_floor_months=1.5,
      cash_ceiling_months=2.0,
    )
    self.assertEqual(common_out, runner_out)

  def test_runner_uses_runner_local_defaults_when_overrides_omitted(self) -> None:
    """The wrapper applies the runner-local default constants
    (_CASH_STRATEGY_BUFFER_MONTHS, _CASH_STRATEGY_MONTHS_PER_QUARTER)
    when the caller doesn't pass explicit floor/ceiling overrides.
    Behavior preservation for any caller that depended on the prior
    runner-local defaults."""
    runner_out = _runner._cash_strategy_buffer_components(SYNTHETIC_ROW)
    # _CASH_STRATEGY_BUFFER_MONTHS = 1.0, months_per_quarter = 3.0
    # opex_quarter = $1.5M -> monthly = $500K -> floor (1mo) = $500K
    self.assertEqual(runner_out["monthly_opex"], 500_000)
    self.assertEqual(runner_out["cash_buffer_required"], 500_000)

  def test_only_one_buffer_math_implementation_exists(self) -> None:
    """Searches the codebase for any function that multiplies an opex
    base by floor_months (the buffer-math signature). Asserts only ONE
    such site exists: common.py:buffer_components.

    If a future developer reintroduces a parallel implementation
    (copying the formula into another module), this test fails and
    points at the offending file. The runner.py wrapper does NOT
    perform the math itself — it delegates — so it doesn't match.
    """
    import pathlib
    pat = re.compile(r"\*\s*floor_months")  # ← formula signature
    matches: list[tuple[str, int, str]] = []
    for path in pathlib.Path(PYTHON_ROOT).rglob("*.py"):
      if "__pycache__" in str(path):
        continue
      try:
        text = path.read_text(encoding="utf-8")
      except OSError:
        continue
      for lineno, line in enumerate(text.splitlines(), start=1):
        if pat.search(line):
          matches.append((str(path), lineno, line.strip()))
    self.assertEqual(
      len(matches), 2,
      "Expected exactly 2 references to the `* floor_months` formula "
      "(once in common.py:buffer_components for cash_buffer_required, "
      "once in the same function for cash_ceiling). Found:\n"
      + "\n".join(f"  {p}:{ln}  {snip}" for p, ln, snip in matches),
    )
    for path, _, _ in matches:
      self.assertTrue(
        path.endswith("post_intake_cash" + os.sep + "common.py"),
        f"Buffer math must live exclusively in post_intake_cash/common.py; found in {path}",
      )


class NexGenIter10ScenarioTest(unittest.TestCase):
  def test_nexgen_q1_post_fix_buffer_thresholds(self) -> None:
    """NexGen Q1 (per iter 10 persisted state):
      opex_quarter = ~$1.498M, ending_cash = $993K, cash_floor_months = 1.5.
    Pre-fix buffer = $1.5M*1.5 = $2.25M -> Q1 cash $993K APPEARED below
    floor -> false buffer violation -> proposer overshoot -> revert ->
    finalize cash_buffer_invalid.
    Post-fix buffer = ($1.5M/3)*1.5 = $750K -> Q1 cash $993K is comfortably
    above the floor -> no violation -> proposer adds nothing -> finalize
    passes (modulo other constraints)."""
    nexgen_q1 = {
      "cost_of_goods_sold": 641_211,
      "payroll": 391_223,
      "marketing": 441_000,
      "research_and_development": 0,
      "lease_rent": 24_000,
      "general_and_administrative": 968,
    }
    out = _common.buffer_components(
      nexgen_q1,
      cash_floor_months=1.5,
      cash_ceiling_months=2.0,
      default_buffer_months=1.0,
      months_per_quarter=3.0,
    )
    self.assertEqual(out["monthly_opex"], 499_467)  # opex_quarter / 3
    self.assertEqual(out["cash_buffer_required"], 749_200)  # 1.5 months
    self.assertEqual(out["cash_ceiling"], 998_934)  # 2.0 months
    # The corrected floor is well below the $993K ending_cash NexGen has at Q1
    nexgen_q1_ending_cash = 993_201
    self.assertGreater(nexgen_q1_ending_cash, out["cash_buffer_required"],
                       "NexGen Q1 should pass the corrected floor")


if __name__ == "__main__":
  unittest.main()
