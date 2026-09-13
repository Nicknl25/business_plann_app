"""A LONG STAGE IS NOT A DEAD RUN (Wren & Calloway 07a5b10f, 2026-09-12):
the grid-application stage ran ten minutes of real work with the heartbeat
frozen at the stage transition; the watcher called it a stall and Cowork
filed a blocker. Now every model rebuild touches the run's heartbeat,
throttled, keyed by the run in the trace context, never raising - and the
run timestamps leave the API in the app's zone, not labelled GMT.
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo import planning_run_heartbeat as HB  # noqa: E402
from client_intake_and_finmo import post_intake_handler_traces as TR  # noqa: E402
from client_intake_and_finmo import finmo_bridge as FB  # noqa: E402
from api_handlers import intake_consult as H  # noqa: E402


class TheHeartbeatMovesWhileTheRunWorks(unittest.TestCase):
  def setUp(self):
    HB._reset_for_tests()

  def test_no_run_in_context_means_no_write(self):
    TR.end_trace_run()
    writes = []
    self.assertFalse(HB.touch_planning_run_heartbeat(_writer=lambda pid: writes.append(pid) or True))
    self.assertEqual(writes, [])

  def test_the_run_id_comes_from_the_trace_context_and_the_touch_is_throttled(self):
    TR.begin_trace_run("draft-x", "")
    TR.set_planning_run_id("run-abc")
    try:
      self.assertEqual(TR.current_planning_run_id(), "run-abc")
      writes = []
      w = lambda pid: writes.append(pid) or True  # noqa: E731
      self.assertTrue(HB.touch_planning_run_heartbeat(_writer=w, min_interval_s=60.0))
      self.assertFalse(HB.touch_planning_run_heartbeat(_writer=w, min_interval_s=60.0), "inside the interval: no second write")
      self.assertTrue(HB.touch_planning_run_heartbeat(_writer=w, min_interval_s=0.0), "interval elapsed: writes again")
      self.assertEqual(writes, ["run-abc", "run-abc"])
      self.assertTrue(HB.touch_planning_run_heartbeat("run-other", _writer=w, min_interval_s=60.0), "an explicit id wins")
    finally:
      TR.end_trace_run()

  def test_a_failing_writer_never_raises(self):
    def boom(pid):
      raise RuntimeError("db down")
    self.assertFalse(HB.touch_planning_run_heartbeat("run-z", _writer=boom, min_interval_s=0.0))

  def test_every_model_rebuild_touches_it(self):
    src = inspect.getsource(FB.build_python_finmo_json)
    self.assertIn("touch_planning_run_heartbeat()", src)


class TheRunTimestampsLeaveInTheAppZone(unittest.TestCase):
  def test_a_naive_app_zone_datetime_is_stamped_with_its_offset_not_gmt(self):
    out = H._app_dt_iso(datetime(2026, 9, 12, 23, 34, 16))
    self.assertTrue(out.startswith("2026-09-12T23:34:16"), out)
    self.assertTrue(out.endswith("-04:00"), "September in America/New_York is -04:00: " + out)
    self.assertNotIn("GMT", out)

  def test_an_aware_datetime_and_a_non_datetime_pass_through(self):
    aware = datetime(2026, 9, 12, 23, 34, 16, tzinfo=timezone.utc)
    self.assertEqual(H._app_dt_iso(aware), aware.isoformat())
    self.assertIsNone(H._app_dt_iso(None)); self.assertEqual(H._app_dt_iso("x"), "x")

  def test_the_draft_response_uses_it_for_every_run_timestamp(self):
    src = inspect.getsource(H)
    for k in ("planning_run_started_at", "planning_last_heartbeat_at", "planning_paused_at", "planning_stopped_at", "planning_run_completed_at"):
      self.assertIn(f'"{k}": _app_dt_iso(draft.get("{k}"))', src, k)


if __name__ == "__main__":
  unittest.main()
