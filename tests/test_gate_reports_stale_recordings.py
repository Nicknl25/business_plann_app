"""A leg that cannot find its GPT recording says so, instead of going red.

Nick 2026-09-13: "I'd rather have fewer legs that mean something than
sixty-five that can go red because a prompt got a comma."

A gate leg drives a real turn. The turn calls the intake guard. The guard calls
GPT under the strict lock, which keys on the exact prompt bytes. Edit a prompt -
add a comma - and the key changes, the recording is not found, and the leg fails
for a reason that has nothing to do with the code it claims to test. That is
what turned the gate red on an unchanged commit on 2026-09-13.

STALE RECORDING is a verdict, not a failure: it says the leg cannot speak until
it is re-recorded.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "python"))


class _Leg:
  id = "TEST"
  kind = "REGRESSION"
  name = "a-leg"
  claim = "something"
  issue = ""
  proof = None

  def __init__(self, run):
    self.run = run


class _Ctx:
  last_turn = None
  last_wall = ""

  def reset(self):
    pass


class StaleRecordingIsAVerdictNotAFailure(unittest.TestCase):
  def setUp(self):
    from client_intake_and_finmo import openai_http as o  # type: ignore

    self.o = o
    o.reset_lock_misses()

  def tearDown(self):
    self.o.reset_lock_misses()

  def _miss(self, n=2):
    for i in range(n):
      self.o._LOCK_MISSES["n"] += 1
      self.o._LOCK_MISSES["keys"].append("key%d" % i)

  def test_a_leg_that_raises_on_a_missing_recording_is_not_a_failure(self):
    from replay_gate import runner  # type: ignore

    def run(ctx):
      self._miss()
      raise RuntimeError("gpt_lock_miss_strict_replay: no recorded response")

    ok, verdict, detail, _ev = runner.run_leg(_Ctx(), _Leg(run))
    self.assertTrue(ok, "a missing recording must not fail the gate")
    self.assertEqual(verdict, "STALE RECORDING")
    self.assertIn("re-record", detail)
    self.assertIn("key0", detail, "it must name the keys that need re-recording")

  def test_a_leg_that_returns_false_after_a_miss_is_stale_not_failed(self):
    from replay_gate import runner  # type: ignore

    def run(ctx):
      self._miss(1)
      return False, "the pinned value did not land"

    ok, verdict, detail, _ev = runner.run_leg(_Ctx(), _Leg(run))
    self.assertTrue(ok)
    self.assertEqual(verdict, "STALE RECORDING")
    self.assertIn("did not land", detail,
                  "the underlying verdict is kept - it is context, not a pass")

  def test_a_genuine_failure_with_no_miss_still_fails(self):
    """The whole point is that this still goes red."""
    from replay_gate import runner  # type: ignore

    def run(ctx):
      return False, "the pinned value did not land"

    ok, verdict, _detail, _ev = runner.run_leg(_Ctx(), _Leg(run))
    self.assertFalse(ok, "a real regression must still fail")
    self.assertNotEqual(verdict, "STALE RECORDING")

  def test_a_genuine_error_with_no_miss_still_errors(self):
    from replay_gate import runner  # type: ignore

    def run(ctx):
      raise ValueError("a real bug in the leg")

    ok, verdict, detail, _ev = runner.run_leg(_Ctx(), _Leg(run))
    self.assertFalse(ok)
    self.assertEqual(verdict, "ERROR")
    self.assertIn("ValueError", detail)

  def test_the_counter_is_reset_per_leg(self):
    """One leg's stale recording must not excuse the next leg's failure."""
    from replay_gate import runner  # type: ignore

    self._miss(3)

    def run(ctx):
      return False, "the pinned value did not land"

    ok, verdict, _d, _e = runner.run_leg(_Ctx(), _Leg(run))
    self.assertFalse(ok, "a miss from an EARLIER leg leaked into this one")
    self.assertNotEqual(verdict, "STALE RECORDING")


class TheCounterLivesWhereTheMissHappens(unittest.TestCase):
  def test_the_lock_miss_is_counted_at_its_one_site(self):
    src = (ROOT / "python" / "client_intake_and_finmo" / "openai_http.py").read_text(encoding="utf-8")
    self.assertEqual(src.count("raise GptLockMiss("), 1,
                     "more than one raise site means the count can be wrong")
    i = src.index("raise GptLockMiss(")
    self.assertIn('_LOCK_MISSES["n"] += 1', src[max(0, i - 400):i],
                  "the count must be taken at the raise, not inferred elsewhere")


if __name__ == "__main__":
  unittest.main(verbosity=2)
