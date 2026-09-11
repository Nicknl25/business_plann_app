"""The pre-push hook runs the known-issue gate on intake and payroll pushes
(Nick 2026-09-11: "the hook as it stands would have let last night through").

Measured: on e4a13f26 every unit pin the preflight runs passed while seven
known-issue legs were red. The gate is what catches that class.
"""
from __future__ import annotations

import importlib.util
import inspect
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_spec = importlib.util.spec_from_file_location(
  "prepush_preflight", os.path.join(ROOT, "scripts", "prepush_preflight.py"))
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)


class WhatTriggersTheGateTests(unittest.TestCase):
  def test_intake_payroll_model_workbook_and_gate_code_do(self):
    for path in ("python/api_handlers/intake_consult.py",
                 "python/client_intake_and_finmo/post_intake_headcount/schedule.py",
                 "python/client_intake_and_finmo/intake_coherence/section.py",
                 "python/financial_model_engine/finmo_model.py",
                 "client_statements_output_excel/workbook_builder.py",
                 "replay_gate/legs.py"):
      self.assertTrue(P._gate_relevant(path), path)

  def test_the_writing_phase_and_gate_notes_do_not(self):
    for path in ("python/writing_phase_v2/writer.py", "replay_gate/HANDOFF.md",
                 "cowork_tester/agenda.json", "scripts/preflight.py"):
      self.assertFalse(P._gate_relevant(path), path)


class TheGateRunTests(unittest.TestCase):
  def test_it_runs_strict_saves_everything_and_refuses_on_red(self):
    run_src = inspect.getsource(P.run_known_issue_gate)
    self.assertIn('GPT_RESPONSE_LOCK_STRICT"] = "1"', run_src)
    self.assertIn("replay_gate.run_gate", run_src)
    self.assertIn("GATE_REPORT", run_src)
    self.assertIn('startswith("[ FAIL ]")', run_src)
    main_src = inspect.getsource(P.main)
    self.assertIn("run_known_issue_gate()", main_src)
    self.assertIn("PUSH REFUSED: the known-issue gate is not green", main_src)


if __name__ == "__main__":
  unittest.main()
