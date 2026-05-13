"""Phase 9 P3.10 STD canonical-source layer 3 HOTFIX — orphaned-caller
removal.

Layer 3 deleted `_apply_cash_pass_short_term_debt_current_portion` from
`post_intake_cash/runner.py` but missed two callers in
`post_intake_cash_strategy/orchestrator_invocation.py`:
  - Step 2 (pre-review STD seed) at line ~214
  - Step 8 (re-apply post-review STD) at line ~398

When `run_mode_based_cash_strategy` hit those calls the `AttributeError`
was silently swallowed by the orchestrator's cash-pass try/except. The
pipeline ran all the way to finalize with stale pre-cash FINMO state
(opening=closing=$300K every quarter, payroll never updated, cash never
adjusted), producing four cascading downstream errors instead of the
actual underlying AttributeError.

This test enforces the no-orphaned-references invariant going forward
and confirms the live cash-pass entry point loads cleanly.
"""

from __future__ import annotations

import os
import pathlib
import re
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, os.pardir))
PYTHON_ROOT = os.path.join(REPO_ROOT, "python")
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


# Symbols deleted in Layer 3 + this hotfix; live code must not call them
# or reference them. NameErrors at runtime would otherwise surface as
# misleading downstream errors (e.g. cascading finalize failures or
# wrapped PostIntakePreconditionFailed). See iter 4 + iter 6.
_DELETED_SYMBOLS = (
  # Layer 3 deleted functions
  "_apply_cash_pass_short_term_debt_current_portion",
  "apply_short_term_debt_current_portion",
  "build_short_term_debt_current_portion_plan",
  # Layer 3 deleted constants
  "SHORT_TERM_DEBT_RATIO_LEVER_ID",
  "_CASH_STRATEGY_SHORT_TERM_DEBT_RATIO_LEVER_ID",
)


def _python_source_files():
  """Yield every .py file under python/ that is not the test file
  itself or a __pycache__ artifact."""
  this_file = os.path.abspath(__file__)
  for root, dirs, files in os.walk(PYTHON_ROOT):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for name in files:
      if not name.endswith(".py"):
        continue
      path = os.path.join(root, name)
      if os.path.abspath(path) == this_file:
        continue
      yield path


def _strip_python_comments(text: str) -> str:
  """Remove line-comment content (everything after `#` on a line) and
  triple-quoted strings so a name appearing only in a docstring or
  comment is not flagged as a live reference."""
  no_strings = re.sub(r'"""[\s\S]*?"""', "", text)
  no_strings = re.sub(r"'''[\s\S]*?'''", "", no_strings)
  out_lines = []
  for line in no_strings.splitlines():
    if "#" in line:
      i = 0
      in_single = False
      in_double = False
      cut = -1
      while i < len(line):
        ch = line[i]
        if ch == "'" and not in_double:
          in_single = not in_single
        elif ch == '"' and not in_single:
          in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
          cut = i
          break
        i += 1
      if cut >= 0:
        line = line[:cut]
    out_lines.append(line)
  return "\n".join(out_lines)


class STDLayer3HotfixOrphanedCallersTest(unittest.TestCase):
  def test_no_orphaned_calls_to_deleted_std_writers(self) -> None:
    """Grep python/ for any live (non-comment, non-string) references
    to the deleted STD-writer symbols. The test file itself is excluded
    via _python_source_files()."""
    offenders = []
    for path in _python_source_files():
      try:
        text = open(path, encoding="utf-8").read()
      except OSError:
        continue
      stripped = _strip_python_comments(text)
      for symbol in _DELETED_SYMBOLS:
        if symbol in stripped:
          offenders.append((path, symbol))
    self.assertEqual(
      offenders, [],
      "Orphaned live references to Layer 3 deleted STD writers found:\n"
      + "\n".join(f"  {p} -> {s}" for p, s in offenders),
    )

  def test_run_mode_based_cash_strategy_imports_clean(self) -> None:
    """The live cash-pass entry point must import without
    AttributeError after Layer 3 + this hotfix."""
    from client_intake_and_finmo.post_intake_cash_strategy.orchestrator_invocation import (  # noqa: WPS433
      run_mode_based_cash_strategy,
    )
    self.assertTrue(callable(run_mode_based_cash_strategy))

  def test_orchestrator_cash_pass_try_except_hard_fails_under_test_mode(self) -> None:
    """Source-level: the orchestrator's cash-pass try/except now
    re-raises under CONVERGENCE_TEST_MODE."""
    p = (
      pathlib.Path(PYTHON_ROOT)
      / "client_intake_and_finmo"
      / "post_intake_solver"
      / "orchestrator.py"
    )
    text = p.read_text(encoding="utf-8")
    # Find the cash-pass try/except region. Anchor on the
    # completion_trace["cash_pass"] = cash_result.to_dict() line that
    # precedes the except.
    anchor = 'completion_trace["cash_pass"] = cash_result.to_dict()'
    idx = text.index(anchor)
    block = text[idx: idx + 1500]
    self.assertIn(
      "convergence_test_mode_enabled",
      block,
      "cash-pass except block must consult convergence_test_mode_enabled",
    )
    self.assertIn(
      "raise",
      block,
      "cash-pass except block must re-raise under test mode",
    )

  def test_orchestrator_invocation_step_2_orphaned_call_removed(self) -> None:
    p = (
      pathlib.Path(PYTHON_ROOT)
      / "client_intake_and_finmo"
      / "post_intake_cash_strategy"
      / "orchestrator_invocation.py"
    )
    text = p.read_text(encoding="utf-8")
    self.assertNotIn(
      "seed_after_short_term = _cash_runner._apply_cash_pass_short_term_debt_current_portion",
      text,
      "Step 2 orphaned call must be removed",
    )

  def test_orchestrator_invocation_step_8_orphaned_call_removed(self) -> None:
    p = (
      pathlib.Path(PYTHON_ROOT)
      / "client_intake_and_finmo"
      / "post_intake_cash_strategy"
      / "orchestrator_invocation.py"
    )
    text = p.read_text(encoding="utf-8")
    self.assertNotIn(
      "cash_strategy_second_pass_result = _cash_runner._apply_cash_pass_short_term_debt_current_portion",
      text,
      "Step 8 orphaned call must be removed",
    )


if __name__ == "__main__":
  unittest.main()
