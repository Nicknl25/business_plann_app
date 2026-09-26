"""A GATE THAT CANNOT REPORT ITS OWN ABORT REFUSES A PUSH AND CANNOT SAY WHY.

2026-09-26. A pre-push hook refused a push with exit 1 and no verdict at all -
no FAIL line, no ABORTED line, no reason, nothing naming what had written to
the database. The gate had died inside its own reporter:

    File "replay_gate/verdict.py", line 155, in emit
        print(f"[{flag}] {leg.id} {leg.kind:<10} {leg.bug}{ref}")
    AttributeError: '_AbortLeg' object has no attribute 'bug'

`Report.abort` exists so a half-finished run can never come back green - its own
comment says "a half-run suite that prints GREEN is the worst possible outcome" -
and it records a failure row through `_AbortLeg` to make that true. But `emit`
reads seven attributes off a leg and `_AbortLeg` carried three of them, so the
abort path had NEVER rendered: the first time it fired, in a pre-push hook, the
suite printed a traceback instead of its verdict.

That is the same class of instrument failure the abort was built to prevent,
one step further along. A suite that prints GREEN after half a run lies about
the build; a suite that prints a traceback instead of a verdict says nothing
about the build at all, and the operator cannot tell a red leg from a crashed
reporter from a database that would not stay still.

The attributes are found by reading the emitter, not by fixing one
AttributeError at a time - that is how a half-fixed reporter dies on the row
after next.
"""
from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
  sys.path.insert(0, ROOT)

from replay_gate.verdict import Report, _AbortLeg  # noqa: E402


class AnAbortRendersThroughTheNormalPath(unittest.TestCase):

  def _emit(self, why):
    report = Report("testbuild")
    report.abort(why)
    buf = io.StringIO()
    with redirect_stdout(buf):
      code = report.emit()
    return code, buf.getvalue()

  def test_it_does_not_crash(self):
    """The live failure: AttributeError inside emit, mid-report."""
    code, out = self._emit("the intake guard recorded a turn at 17:05:12")
    self.assertTrue(out.strip(), "the gate printed nothing at all")

  def test_it_says_the_run_aborted(self):
    _code, out = self._emit("the intake guard recorded a turn at 17:05:12")
    self.assertIn("ABORTED", out)
    self.assertIn("ABORT", out)

  def test_it_names_the_reason_the_operator_needs(self):
    """The reason is the only actionable thing in an abort - what was writing."""
    why = "an issue was filed or re-seen at 2026-09-26 16:46:25"
    _code, out = self._emit(why)
    self.assertIn(why, out)

  def test_it_is_a_failure_so_a_half_run_can_never_print_green(self):
    code, out = self._emit("something wrote to the tables mid-run")
    self.assertNotEqual(0, code, "an aborted run must refuse the push")
    self.assertIn("FAIL", out)
    self.assertNotIn("GREEN", out)
    self.assertIn("0/1 legs clear", out)

  def test_every_attribute_the_emitter_reads_is_present(self):
    """Read off the emitter rather than discovered one crash at a time."""
    import re
    src = io.open(os.path.join(ROOT, "replay_gate", "verdict.py"),
                  encoding="utf-8").read()
    needed = sorted(set(re.findall(r"\bleg\.([a-z_]+)", src)))
    self.assertTrue(needed, "the emitter reads no leg attributes at all?")
    for attr in needed:
      self.assertTrue(hasattr(_AbortLeg, attr),
                      "_AbortLeg has no %r, so emit() will die on it" % attr)

  def test_a_real_leg_and_the_abort_leg_agree_on_their_shape(self):
    """The abort stands in for a leg, so it has to BE one as far as the
    reporter is concerned."""
    from replay_gate.legs import Leg
    import inspect
    real = set(inspect.signature(Leg.__init__).parameters) - {"self"}
    for attr in ("id", "kind", "bug", "title", "issue"):
      self.assertTrue(hasattr(_AbortLeg, attr), attr)
      if attr in real:
        self.assertIsInstance(getattr(_AbortLeg, attr), str, attr)


if __name__ == "__main__":
  unittest.main()
