"""Phase 9 P3.10 Commit 1 — smoke test for the network retry primitive.

Exercises every retry path of ``call_with_retries`` without making real
network calls. Fakes ``requests.Response`` and ``requests.exceptions.*``
to verify:

  - Success on first attempt returns the response.
  - DNS / connection / timeout errors retry up to ``max_retries`` then
    raise ``NetworkRetryExhausted``.
  - HTTP 429 retries; Retry-After header overrides exponential backoff.
  - HTTP 500/502/503/504 retry then raise on exhaustion.
  - HTTP 400/401/403/404 raise NonRetriableHTTPError immediately (no retry).
  - Exponential backoff: 1s, 2s with default ``backoff_base_seconds=1.0``.
  - Successful response after one retry returns the success response
    (not the earlier failure response).

The test injects a stub ``sleep`` so the test runs in milliseconds.
"""

from __future__ import annotations

import os
import sys
import types
import unittest
from typing import Any, Dict, List, Optional
from unittest import mock

import requests


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


from client_intake_and_finmo.post_intake_solver._network_retry import (  # noqa: E402
  NetworkRetryExhausted,
  NonRetriableHTTPError,
  call_with_retries,
  _parse_retry_after,
  _exponential_backoff_seconds,
)


def _fake_response(status: int, body: str = "", headers: Optional[Dict[str, str]] = None) -> requests.Response:
  resp = requests.Response()
  resp.status_code = int(status)
  resp._content = body.encode("utf-8") if body else b""
  resp.headers = headers or {}
  return resp


class CapturingSleep:
  def __init__(self) -> None:
    self.sleeps: List[float] = []

  def __call__(self, seconds: float) -> None:
    self.sleeps.append(float(seconds))


class NetworkRetryPrimitiveSmokeTest(unittest.TestCase):
  def test_success_on_first_attempt(self) -> None:
    sleep = CapturingSleep()
    calls: List[int] = []

    def request():
      calls.append(1)
      return _fake_response(200, "ok")

    resp = call_with_retries(request, endpoint="https://test/", sleep=sleep)
    self.assertEqual(resp.status_code, 200)
    self.assertEqual(len(calls), 1)
    self.assertEqual(sleep.sleeps, [])

  def test_dns_exhaustion_raises_with_diagnostic(self) -> None:
    sleep = CapturingSleep()
    calls: List[int] = []

    def request():
      calls.append(1)
      raise requests.exceptions.ConnectionError(
        "HTTPSConnection(host='api.openai.com', port=443): Failed to "
        "resolve 'api.openai.com' (getaddrinfo failed)"
      )

    with self.assertRaises(NetworkRetryExhausted) as ctx:
      call_with_retries(request, endpoint="https://api.openai.com/v1/responses", sleep=sleep)

    exc = ctx.exception
    self.assertEqual(exc.attempts_made, 3)
    self.assertEqual(exc.final_failure_kind, "dns_error")
    self.assertEqual(exc.final_exception_class, "ConnectionError")
    self.assertEqual(len(calls), 3)
    self.assertEqual(sleep.sleeps, [1.0, 2.0])

    diag = exc.to_dict()
    self.assertEqual(diag["attempts_made"], 3)
    self.assertEqual(diag["final_failure_kind"], "dns_error")
    self.assertEqual(len(diag["attempt_log"]), 3)
    self.assertEqual(diag["attempt_log"][0]["failure_kind"], "dns_error")

  def test_connect_timeout_retried_then_succeeds(self) -> None:
    sleep = CapturingSleep()
    call_count = [0]

    def request():
      call_count[0] += 1
      if call_count[0] < 2:
        raise requests.exceptions.ConnectTimeout("connect timed out")
      return _fake_response(200, "ok")

    resp = call_with_retries(request, endpoint="https://test/", sleep=sleep)
    self.assertEqual(resp.status_code, 200)
    self.assertEqual(call_count[0], 2)
    self.assertEqual(sleep.sleeps, [1.0])

  def test_http_500_retry_then_raise(self) -> None:
    sleep = CapturingSleep()
    calls: List[int] = []

    def request():
      calls.append(1)
      return _fake_response(503, "service unavailable")

    with self.assertRaises(NetworkRetryExhausted) as ctx:
      call_with_retries(request, endpoint="https://test/", sleep=sleep)

    self.assertEqual(ctx.exception.attempts_made, 3)
    self.assertEqual(ctx.exception.final_status_code, 503)
    self.assertEqual(ctx.exception.final_failure_kind, "retriable_http_503")
    self.assertEqual(len(calls), 3)
    self.assertEqual(sleep.sleeps, [1.0, 2.0])

  def test_http_429_retry_with_retry_after_header(self) -> None:
    sleep = CapturingSleep()
    call_count = [0]

    def request():
      call_count[0] += 1
      if call_count[0] < 2:
        return _fake_response(429, "too many requests", headers={"Retry-After": "5"})
      return _fake_response(200, "ok")

    resp = call_with_retries(request, endpoint="https://test/", sleep=sleep)
    self.assertEqual(resp.status_code, 200)
    self.assertEqual(sleep.sleeps, [5.0])

  def test_http_429_caps_retry_after_at_60s(self) -> None:
    sleep = CapturingSleep()
    call_count = [0]

    def request():
      call_count[0] += 1
      if call_count[0] < 2:
        return _fake_response(429, "rl", headers={"Retry-After": "300"})
      return _fake_response(200, "ok")

    call_with_retries(request, endpoint="https://test/", sleep=sleep)
    self.assertEqual(sleep.sleeps, [60.0])

  def test_http_400_raises_non_retriable_immediately(self) -> None:
    sleep = CapturingSleep()
    calls: List[int] = []

    def request():
      calls.append(1)
      return _fake_response(400, "bad request")

    with self.assertRaises(NonRetriableHTTPError) as ctx:
      call_with_retries(request, endpoint="https://test/", sleep=sleep)

    self.assertEqual(ctx.exception.status_code, 400)
    self.assertEqual(len(calls), 1)
    self.assertEqual(sleep.sleeps, [])

  def test_http_401_403_404_all_non_retriable(self) -> None:
    for status in (401, 403, 404):
      sleep = CapturingSleep()
      calls: List[int] = []

      def request(s=status):
        calls.append(1)
        return _fake_response(s, "")

      with self.assertRaises(NonRetriableHTTPError):
        call_with_retries(request, endpoint="https://test/", sleep=sleep)
      self.assertEqual(len(calls), 1, f"status {status} should not retry")

  def test_unexpected_exception_raises_immediately(self) -> None:
    sleep = CapturingSleep()
    calls: List[int] = []

    def request():
      calls.append(1)
      raise ValueError("schema build failed")

    with self.assertRaises(NetworkRetryExhausted) as ctx:
      call_with_retries(request, endpoint="https://test/", sleep=sleep)

    self.assertEqual(ctx.exception.attempts_made, 1)
    self.assertEqual(ctx.exception.final_failure_kind, "unexpected_exception")
    self.assertEqual(len(calls), 1)

  def test_exponential_backoff_schedule_default(self) -> None:
    # attempt 1 -> 1s; attempt 2 -> 2s
    self.assertEqual(_exponential_backoff_seconds(attempt_index=1, backoff_base_seconds=1.0), 1.0)
    self.assertEqual(_exponential_backoff_seconds(attempt_index=2, backoff_base_seconds=1.0), 2.0)

  def test_parse_retry_after_seconds_only(self) -> None:
    self.assertEqual(_parse_retry_after("5"), 5.0)
    self.assertEqual(_parse_retry_after("0"), 0.0)
    self.assertEqual(_parse_retry_after("not-a-number"), None)
    self.assertEqual(_parse_retry_after(""), None)
    self.assertEqual(_parse_retry_after(None), None)
    self.assertEqual(_parse_retry_after("-1"), None)


if __name__ == "__main__":
  unittest.main()
