"""GPT_RESPONSE_LOCK_STRICT: a replay answers from the response store or names
the miss - it never makes a live call (2026-09-11, the post-intake replay gate).

Default off, so production behaviour is unchanged: a miss still goes live and
is saved.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo import openai_http as H  # noqa: E402

PAYLOAD = {"model": "gpt-x", "messages": [
  {"role": "system", "content": "You estimate CUSTOMER RETENTION for small businesses"}]}


def _call():
  return H.post_openai_with_retries(
    url="https://api.openai.com/v1/chat/completions", headers={}, payload=PAYLOAD,
    timeout_seconds=5, retryable_status=(429,), max_attempts=1)


class _NoNetwork:
  def __enter__(self):
    raise AssertionError("a strict replay reached the network")

  def __exit__(self, *a):
    return False


class _FakeResp:
  status_code = 200
  text = '{"live": 1}'
  headers = {"content-type": "application/json"}

  def json(self):
    return {"live": 1}


class _LiveSession:
  def __enter__(self):
    return self

  def __exit__(self, *a):
    return False

  def post(self, *a, **k):
    return _FakeResp()


class _Base(unittest.TestCase):
  env = {}

  def setUp(self):
    p = mock.patch.dict(os.environ, self.env)
    p.start()
    self.addCleanup(p.stop)
    v = mock.patch.object(H, "_record_call_vitals", lambda **k: None)
    v.start()
    self.addCleanup(v.stop)
    del H._STRICT_MISSES[:]


class StrictTests(_Base):
  env = {"GPT_RESPONSE_LOCK": "1", "GPT_RESPONSE_LOCK_STRICT": "1"}

  def test_a_miss_raises_names_the_prompt_and_never_calls_live(self):
    with mock.patch.object(H, "_lock_lookup", return_value=None), \
         mock.patch.object(H, "_openai_session", _NoNetwork):
      with self.assertRaises(H.GptLockMiss) as cm:
        _call()
    self.assertIn("CUSTOMER RETENTION", str(cm.exception))

  def test_a_miss_is_recorded_even_if_a_caller_swallows_it(self):
    with mock.patch.object(H, "_lock_lookup", return_value=None), \
         mock.patch.object(H, "_openai_session", _NoNetwork):
      try:
        _call()
      except H.GptLockMiss:
        pass
    self.assertEqual(len(H._STRICT_MISSES), 1)

  def test_a_hit_replays_the_stored_answer(self):
    with mock.patch.object(H, "_lock_lookup", return_value='{"ok": 1}'), \
         mock.patch.object(H, "_openai_session", _NoNetwork):
      self.assertEqual(_call().json(), {"ok": 1})

  def test_strict_with_the_lock_switched_off_still_refuses_live(self):
    with mock.patch.dict(os.environ, {"GPT_RESPONSE_LOCK": "0"}), \
         mock.patch.object(H, "_openai_session", _NoNetwork):
      with self.assertRaises(H.GptLockMiss):
        _call()


class DefaultTests(_Base):
  env = {"GPT_RESPONSE_LOCK": "1", "GPT_RESPONSE_LOCK_STRICT": ""}

  def test_default_off_a_miss_still_goes_live_and_is_saved(self):
    with mock.patch.object(H, "_lock_lookup", return_value=None), \
         mock.patch.object(H, "_lock_save") as save, \
         mock.patch.object(H, "_openai_session", _LiveSession):
      self.assertEqual(_call().json(), {"live": 1})
    save.assert_called_once()
    self.assertEqual(H._STRICT_MISSES, [])


if __name__ == "__main__":
  unittest.main()
