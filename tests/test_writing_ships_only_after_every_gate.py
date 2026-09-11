"""A plan enters Client Written Plans only after every gate passes (Nick
2026-09-11: "Just fix the folder breach").

The runner used to RENDER a plan that passed the writing check straight into
Client Written Plans and run the completeness, reason and artifact gates
afterwards - a plan that then failed a gate stayed in the ship folder. These
tests drive the real run_model with the writer, renderer and gates stubbed,
and look at the folder.

WP_RUNNER_PATH points the tests at another copy of the runner (the red-proof
runs them against the pre-fix version).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

RUNNER = os.environ.get("WP_RUNNER_PATH") or os.path.join(ROOT, "scripts", "writing_phase_v2_run.py")
_spec = importlib.util.spec_from_file_location("wp_v2_run_under_test", RUNNER)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

from writing_phase_v2 import docx_audit as DA  # noqa: E402

REGISTRY = json.load(open(os.path.join(ROOT, "python", "writing_phase_v2", "assets",
                                       "figure_registry.json"), encoding="utf-8"))["items"]


def _fake_run(cmd, *a, **k):
  """render_charts: nothing. render_plan_v2.js: write the docx and a render
  report placing every registry item."""
  if any("render_plan_v2.js" in str(c) for c in cmd):
    target = cmd[5]
    with open(target, "wb") as fh:
      fh.write(b"docx")
    with open(target + ".render_report.json", "w", encoding="utf-8") as fh:
      json.dump([{"id": it["id"], "placed": True} for it in REGISTRY], fh)

  class _Done:
    returncode = 0
  return _Done()


class ShipOnlyAfterEveryGateTests(unittest.TestCase):
  def _run(self, *, check_findings=(), artifact_findings=()):
    plans = tempfile.mkdtemp(prefix="plans_")
    out = tempfile.mkdtemp(prefix="run_")
    plan = {"sections": []}
    with mock.patch.object(M, "PLANS_DIR", plans), \
         mock.patch.dict(M.W.WRITERS, {"claude": lambda v2: (plan, {}, "stats")}), \
         mock.patch.object(M.CK, "check", lambda v2, p: (list(check_findings), ["checked"])), \
         mock.patch.object(M.CP, "audit_absences", lambda *a, **k: []), \
         mock.patch.object(DA, "audit_docx", lambda *a, **k: list(artifact_findings)), \
         mock.patch.object(M.subprocess, "run", _fake_run), \
         mock.patch.object(M.ED, "edit_plan", lambda v2, p, f, model_family=None: (None, {}, "stats")):
      outcome = M.run_model("claude", {"meta": {}}, out, "biz", False, "Biz Co")
    return outcome, os.listdir(plans), out

  def test_a_plan_that_passes_every_gate_ships(self):
    outcome, shipped, _out = self._run()
    self.assertEqual(outcome["state"], "shipped")
    self.assertEqual(len(shipped), 1)
    self.assertTrue(outcome["docx"].endswith(shipped[0]))

  def test_a_plan_that_fails_the_artifact_gate_never_enters_the_ship_folder(self):
    outcome, shipped, out = self._run(artifact_findings=["caption numbering broken"])
    self.assertEqual(outcome["state"], "failed")
    self.assertEqual(shipped, [], "a plan that failed a gate is sitting in Client Written Plans")
    self.assertTrue(outcome["docx"].startswith(out))

  def test_a_plan_that_fails_the_writing_check_never_enters_the_ship_folder(self):
    outcome, shipped, _out = self._run(check_findings=["an undeclared figure"])
    self.assertEqual(outcome["state"], "failed")
    self.assertEqual(shipped, [])


class ShipCopyTests(unittest.TestCase):
  def test_an_open_deliverable_gets_a_stamped_sibling(self):
    if not hasattr(M, "_ship_to_plans"):
      self.fail("no _ship_to_plans - the runner renders straight into the ship folder")
    plans = tempfile.mkdtemp(prefix="plans_")
    staged = os.path.join(tempfile.mkdtemp(prefix="run_"), "Biz Co -- Business Plan (CLAUDE v2, unedited).docx")
    with open(staged, "wb") as fh:
      fh.write(b"docx")
    real_copy = M.shutil.copy2
    calls = []

    def copy(src, dst):
      calls.append(dst)
      if len(calls) == 1:
        raise PermissionError("open in Word")
      return real_copy(src, dst)

    with mock.patch.object(M, "PLANS_DIR", plans), mock.patch.object(M.shutil, "copy2", copy):
      target = M._ship_to_plans(staged)
    self.assertNotEqual(target, calls[0])
    self.assertTrue(os.path.exists(target))


if __name__ == "__main__":
  unittest.main()
