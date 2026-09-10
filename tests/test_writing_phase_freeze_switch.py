"""Item 4 FREEZE REAL (Nick 2026-09-09): the writing-phase trigger switch.

Pins both states of the ONE trigger site, _auto_trigger_writing_phase in
api_handlers/intake_consult.py, offline (the runner subprocess is mocked,
the auto_run.log root is a temp dir, the flag file is a temp file):

  ON  (absent flag)  + acceptance passed -> the runner is launched with the
                       draft id and planning_run_id, the auto-trigger line is
                       appended, auto-triggered is logged.
  OFF (flag file)    + acceptance passed -> Writing phase FROZEN is logged
                       with draft, run, business; the runner is NOT launched;
                       no log dir is created; the function returns normally so
                       the tail's own delivery continues.
  OFF + acceptance FAILED -> still FROZEN (the switch precedes acceptance -
                       the freeze line fires on Sunny too).
  ON  + acceptance FAILED -> NOT triggered ... acceptance did not pass,
                       unchanged from before the switch existed.
  Corrupt flag file  -> FROZEN (fail-closed).
  Flip at call time  -> flipping the file between two calls changes the
                       outcome with no re-import (no import-time cache).
  scripts/writing_phase_freeze.py on|off|status -> one line each, readback.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO, os.path.join(REPO, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from api_handlers import intake_consult as IC  # noqa: E402
from writing_phase_v2 import trigger_switch as TS  # noqa: E402

DRAFT = "d3adbeefcafe4f00b1e5c0ffee000001"
RUN = "0123456789ab4cdef0123456789abcde"
BIZ = "Sunny Glaze Donuts"


class _App:
  def __init__(self):
    self.logger = logging.getLogger(f"freeze-pin-{id(self)}")
    self.logger.setLevel(logging.DEBUG)
    self.logger.propagate = False
    self.records = []
    h = logging.Handler()
    h.emit = lambda rec: self.records.append(rec)  # type: ignore[assignment]
    self.logger.addHandler(h)

  def lines(self):
    return [r.getMessage() for r in self.records]


def _payload(accepted: bool):
  return {"acceptance_passed": accepted, "planning_run_id": RUN, "business_name": BIZ}


class FreezeSwitchPins(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.flag = os.path.join(self.tmp.name, "flags", "writing_phase_trigger.json")
    self.log_root = os.path.join(self.tmp.name, "_v2_runs")
    self._p_flag = mock.patch.object(TS, "FLAG_PATH", self.flag)
    self._p_root = mock.patch.object(IC, "_WP_LOG_ROOT", self.log_root)
    self._p_flag.start()
    self._p_root.start()
    self.app = _App()

  def tearDown(self):
    self._p_root.stop()
    self._p_flag.stop()
    self.tmp.cleanup()

  def _call(self, accepted: bool):
    with mock.patch("subprocess.Popen") as popen:
      outcome = IC._auto_trigger_writing_phase(self.app, _payload(accepted), DRAFT)
    return outcome, popen

  # ---- ON --------------------------------------------------------------
  def test_on_default_absent_flag_fires_runner_with_draft_and_run(self):
    self.assertFalse(os.path.exists(self.flag))
    outcome, popen = self._call(accepted=True)
    self.assertEqual(outcome, "fired")
    self.assertEqual(popen.call_count, 1)
    argv = popen.call_args.args[0]
    self.assertTrue(argv[-5].endswith(os.path.join("scripts", "writing_phase_v2_run.py")), argv)
    self.assertEqual(argv[-4:], ["--business", DRAFT, "--planning-run-id", RUN])
    self.assertEqual(popen.call_args.kwargs["cwd"], REPO)
    log = os.path.join(self.log_root, "sunny_glaze_donuts", "auto_run.log")
    self.assertTrue(os.path.exists(log))
    with open(log, encoding="utf-8") as fh:
      self.assertIn(f"=== auto-trigger {DRAFT} run={RUN} ===", fh.read())
    self.assertTrue(any("Writing phase auto-triggered for draft " + DRAFT in ln
                        for ln in self.app.lines()), self.app.lines())
    self.assertFalse(any("FROZEN" in ln for ln in self.app.lines()))

  def test_on_acceptance_failed_logs_not_triggered_unchanged(self):
    outcome, popen = self._call(accepted=False)
    self.assertEqual(outcome, "acceptance_failed")
    self.assertEqual(popen.call_count, 0)
    self.assertIn(f"Writing phase NOT triggered for draft {DRAFT}: acceptance did not pass",
                  self.app.lines())
    self.assertFalse(os.path.exists(self.log_root))

  # ---- OFF (FROZEN) -----------------------------------------------------
  def test_off_logs_frozen_and_never_launches_runner(self):
    TS.set_state(False, by="pin", note="directive freeze", path=self.flag)
    outcome, popen = self._call(accepted=True)
    self.assertEqual(outcome, "frozen")
    self.assertEqual(popen.call_count, 0, "runner must not be launched while frozen")
    frozen = [ln for ln in self.app.lines() if "Writing phase FROZEN" in ln]
    self.assertEqual(len(frozen), 1, self.app.lines())
    self.assertIn(DRAFT, frozen[0])
    self.assertIn(RUN, frozen[0])
    self.assertIn(BIZ, frozen[0])
    self.assertIn("acceptance_passed=True", frozen[0])
    self.assertIn("note: directive freeze", frozen[0])
    self.assertEqual(self.app.records[0].levelno, logging.WARNING)
    self.assertFalse(os.path.exists(self.log_root),
                     "frozen trigger must not touch Client Written Plans")
    self.assertFalse(any("auto-triggered" in ln or "NOT triggered" in ln
                         for ln in self.app.lines()))

  def test_off_precedes_acceptance_so_sunny_shape_still_logs_frozen(self):
    TS.set_state(False, by="pin", path=self.flag)
    outcome, popen = self._call(accepted=False)
    self.assertEqual(outcome, "frozen")
    self.assertEqual(popen.call_count, 0)
    frozen = [ln for ln in self.app.lines() if "Writing phase FROZEN" in ln]
    self.assertEqual(len(frozen), 1)
    self.assertIn("acceptance_passed=False", frozen[0])
    self.assertFalse(any("NOT triggered" in ln for ln in self.app.lines()),
                     "the freeze line, not the acceptance line, is what fires")

  def test_corrupt_flag_file_is_fail_closed(self):
    os.makedirs(os.path.dirname(self.flag), exist_ok=True)
    with open(self.flag, "w", encoding="utf-8") as fh:
      fh.write("{not json")
    state = TS.read_state(self.flag)
    self.assertTrue(state["frozen"])
    self.assertEqual(state["source"], "corrupt")
    outcome, popen = self._call(accepted=True)
    self.assertEqual(outcome, "frozen")
    self.assertEqual(popen.call_count, 0)
    self.assertTrue(any("Writing phase FROZEN" in ln and "corrupt" in ln
                        for ln in self.app.lines()), self.app.lines())

  def test_unknown_value_is_fail_closed(self):
    os.makedirs(os.path.dirname(self.flag), exist_ok=True)
    with open(self.flag, "w", encoding="utf-8") as fh:
      json.dump({"trigger": "maybe"}, fh)
    self.assertTrue(TS.read_state(self.flag)["frozen"])

  def test_flip_takes_effect_at_call_time_without_reimport(self):
    TS.set_state(False, by="pin", path=self.flag)
    outcome1, popen1 = self._call(accepted=True)
    TS.set_state(True, by="pin", path=self.flag)
    outcome2, popen2 = self._call(accepted=True)
    os.remove(self.flag)  # back to default
    outcome3, popen3 = self._call(accepted=True)
    self.assertEqual((outcome1, outcome2, outcome3), ("frozen", "fired", "fired"))
    self.assertEqual((popen1.call_count, popen2.call_count, popen3.call_count), (0, 1, 1))

  # ---- the flag script ---------------------------------------------------
  def _script(self, *args):
    cp = subprocess.run(
      [sys.executable, "-X", "utf8", os.path.join(REPO, "scripts", "writing_phase_freeze.py"),
       *args, "--path", self.flag],
      capture_output=True, text=True, cwd=REPO, timeout=60,
    )
    out = cp.stdout.strip().splitlines()
    self.assertEqual(len(out), 1, cp.stdout + cp.stderr)
    return cp.returncode, out[0]

  def test_flag_script_status_off_on_readback_one_line_each(self):
    rc, line = self._script("status")
    self.assertEqual(rc, 0)
    self.assertTrue(line.startswith("writing-phase trigger: ON (default"), line)

    rc, line = self._script("off", "--note", "pin freeze", "--by", "pin")
    self.assertEqual(rc, 3)
    self.assertTrue(line.startswith("writing-phase trigger: FROZEN (off since "), line)
    self.assertIn("by pin", line)
    self.assertIn("pin freeze", line)
    with open(self.flag, encoding="utf-8") as fh:
      self.assertEqual(json.load(fh)["trigger"], "off")

    rc, line = self._script("status")
    self.assertEqual(rc, 3)
    self.assertTrue(line.startswith("writing-phase trigger: FROZEN"), line)
    self.assertTrue(TS.is_frozen(self.flag))

    rc, line = self._script("on", "--by", "pin")
    self.assertEqual(rc, 0)
    self.assertTrue(line.startswith("writing-phase trigger: ON (set "), line)
    self.assertFalse(TS.is_frozen(self.flag))

    rc, line = self._script("status")
    self.assertEqual(rc, 0)
    self.assertTrue(line.startswith("writing-phase trigger: ON (set "), line)

  def test_default_flag_path_is_gitignored_runtime_dir(self):
    # setUp patches FLAG_PATH; the production default is the unpatched value.
    self._p_flag.stop()
    try:
      default_path = TS.FLAG_PATH
    finally:
      self._p_flag.start()
    self.assertEqual(os.path.relpath(default_path, REPO),
                     os.path.join("_runtime", "writing_phase_trigger.json"))
    self.assertEqual(TS.REPO_ROOT, REPO)
    with open(os.path.join(REPO, ".gitignore"), encoding="utf-8") as fh:
      self.assertIn("/_runtime/", fh.read().splitlines())

  def test_only_one_launcher_of_the_runner_exists(self):
    """Coverage rider: no second trigger site. Every code file under
    python/, scripts/, Test Files/, tests/ that names the runner script."""
    hits = []
    for root_dir in ("python", "scripts", "Test Files", "tests"):
      for dp, dn, fn in os.walk(os.path.join(REPO, root_dir)):
        dn[:] = [d for d in dn if d not in ("__pycache__", "node_modules")]
        for f in fn:
          if not f.endswith((".py", ".ps1", ".bat", ".cmd", ".xml")):
            continue
          fp = os.path.join(dp, f)
          try:
            txt = open(fp, encoding="utf-8", errors="replace").read()
          except OSError:
            continue
          if "writing_phase_v2_run" in txt:
            hits.append(os.path.relpath(fp, REPO))
    launchers = [h for h in hits
                 if h not in (os.path.join("scripts", "writing_phase_v2_run.py"),
                              os.path.join("tests", "test_writing_phase_freeze_switch.py"))]
    self.assertEqual(launchers, [os.path.join("python", "api_handlers", "intake_consult.py")],
                     hits)
    src = open(os.path.join(REPO, "python", "api_handlers", "intake_consult.py"),
               encoding="utf-8").read()
    self.assertEqual(src.count("writing_phase_v2_run.py"), 2,
                     "one docstring mention + one launcher path")
    self.assertEqual(src.count("_auto_trigger_writing_phase("), 2,
                     "one def + one call site")


if __name__ == "__main__":
  unittest.main()
