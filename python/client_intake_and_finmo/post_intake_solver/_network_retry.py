"""Phase 9 P3.10 — Network retry primitive for the GPT chokepoint.

Foundation for the fail-fast architectural overhaul. Distinguishes
transient network failures (which we retry up to 2 times) from
non-retriable failures (which raise immediately). On retry exhaustion,
raises a structured ``NetworkRetryExhausted`` carrying enough diagnostic
context for an operator to identify the precise cause in one log line.

Retriable categories (3 total attempts: first + 2 retries):
  - DNS / name-resolution failures (gaierror, NameResolutionError)
  - TCP connection refused / reset / SSL handshake failures
  - Read and connect timeouts
  - HTTP 429 (rate limit) — honors ``Retry-After`` header if present
  - HTTP 500 / 502 / 503 / 504 (transient server errors)

Non-retriable (fail-fast on first occurrence):
  - HTTP 400 / 401 / 403 / 404 (caller bug or config issue)
  - Malformed JSON response body
  - Any other exception that is neither connection-level nor a known
    retriable HTTP status

Backoff: exponential, base 1.0s (1s, 2s). HTTP 429 with a parseable
``Retry-After`` header overrides the exponential schedule for that
attempt.

Q2 (P3.10 directive): network-failed calls do not count against the
caller's tool-call budget. The chokepoint passes ``successful_response``
to its budget accounting; only successful HTTP responses (including
HTTP-error responses with usable body text) count.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests


logger = logging.getLogger(__name__)


# Status codes treated as transient. 429 is explicitly retriable
# despite being 4xx — it signals rate limit, which by definition is
# transient.
RETRIABLE_HTTP_STATUS = frozenset({429, 500, 502, 503, 504})

# Non-retriable 4xx codes — caller bug or config issue, no retry will
# help.
NON_RETRIABLE_HTTP_STATUS = frozenset({400, 401, 403, 404, 405, 410, 422})

DEFAULT_MAX_RETRIES = 2  # first attempt + 2 retries = 3 total
DEFAULT_BACKOFF_BASE_SECONDS = 1.0


class NetworkRetryExhausted(RuntimeError):
  """Raised when the retry primitive exhausts all attempts on a network
  call. Carries structured diagnostic context so callers and operators
  can identify the failure without parsing exception messages.
  """

  def __init__(
    self,
    *,
    endpoint: str,
    attempts_made: int,
    elapsed_seconds: float,
    final_failure_kind: str,
    final_status_code: Optional[int],
    final_exception_class: Optional[str],
    final_detail: str,
    attempt_log: List[Dict[str, Any]],
  ) -> None:
    self.endpoint = str(endpoint or "")
    self.attempts_made = int(attempts_made)
    self.elapsed_seconds = float(elapsed_seconds)
    self.final_failure_kind = str(final_failure_kind or "")
    self.final_status_code = (
      int(final_status_code) if final_status_code is not None else None
    )
    self.final_exception_class = (
      str(final_exception_class) if final_exception_class else None
    )
    self.final_detail = str(final_detail or "")
    self.attempt_log = list(attempt_log or [])
    header = (
      f"network_retry_exhausted: endpoint={self.endpoint} "
      f"attempts={self.attempts_made} elapsed={self.elapsed_seconds:.2f}s "
      f"final={self.final_failure_kind}"
    )
    if self.final_status_code is not None:
      header += f" status={self.final_status_code}"
    if self.final_exception_class:
      header += f" exception={self.final_exception_class}"
    if self.final_detail:
      header += f" detail={self.final_detail[:200]}"
    super().__init__(header)

  def to_dict(self) -> Dict[str, Any]:
    return {
      "endpoint": self.endpoint,
      "attempts_made": self.attempts_made,
      "elapsed_seconds": round(self.elapsed_seconds, 3),
      "final_failure_kind": self.final_failure_kind,
      "final_status_code": self.final_status_code,
      "final_exception_class": self.final_exception_class,
      "final_detail": self.final_detail[:500],
      "attempt_log": list(self.attempt_log),
    }


class NonRetriableHTTPError(RuntimeError):
  """Raised when the remote returns an HTTP status that is not
  retriable (400/401/403/404/etc). The caller can choose to convert
  this into its own status-dict pattern; the primitive does not retry.
  """

  def __init__(
    self,
    *,
    endpoint: str,
    status_code: int,
    body_text: str,
  ) -> None:
    self.endpoint = str(endpoint or "")
    self.status_code = int(status_code)
    self.body_text = str(body_text or "")[:4000]
    super().__init__(
      f"non_retriable_http_status: endpoint={self.endpoint} "
      f"status={self.status_code} body={self.body_text[:200]}"
    )


@dataclass
class AttemptOutcome:
  attempt_index: int
  failure_kind: str = ""
  status_code: Optional[int] = None
  exception_class: Optional[str] = None
  detail: str = ""
  duration_seconds: float = 0.0
  backoff_seconds_after: float = 0.0

  def to_dict(self) -> Dict[str, Any]:
    return {
      "attempt": int(self.attempt_index),
      "failure_kind": self.failure_kind,
      "status_code": self.status_code,
      "exception_class": self.exception_class,
      "detail": self.detail[:300],
      "duration_seconds": round(self.duration_seconds, 3),
      "backoff_seconds_after": round(self.backoff_seconds_after, 3),
    }


def _classify_connection_exception(exc: BaseException) -> Tuple[str, bool]:
  """Return (failure_kind, retriable). ``failure_kind`` is a short stable
  identifier for logging and diagnostics."""
  if isinstance(exc, requests.exceptions.ConnectTimeout):
    return ("connect_timeout", True)
  if isinstance(exc, requests.exceptions.ReadTimeout):
    return ("read_timeout", True)
  if isinstance(exc, requests.exceptions.SSLError):
    return ("ssl_error", True)
  if isinstance(exc, requests.exceptions.ConnectionError):
    msg = str(exc).lower()
    if "name resolution" in msg or "nodename nor servname" in msg or "getaddrinfo" in msg:
      return ("dns_error", True)
    return ("connection_error", True)
  if isinstance(exc, TimeoutError):
    return ("timeout", True)
  return ("unexpected_exception", False)


def _parse_retry_after(value: Any) -> Optional[float]:
  """Parse a ``Retry-After`` header. Accepts integer seconds or HTTP
  date strings. Returns seconds-to-wait or None if unparseable.

  Per RFC 7231 the value may also be an HTTP-date; we honor the
  integer-seconds form (the common OpenAI shape) and return None
  otherwise — callers fall back to exponential backoff.
  """
  if value is None:
    return None
  raw = str(value).strip()
  if not raw:
    return None
  try:
    seconds = float(raw)
  except Exception:
    return None
  if seconds < 0.0:
    return None
  # Cap at 60s — anything longer suggests a misconfigured server and
  # we'd rather raise than block the run for minutes.
  return min(60.0, seconds)


def call_with_retries(
  request_callable: Callable[[], requests.Response],
  *,
  endpoint: str,
  max_retries: int = DEFAULT_MAX_RETRIES,
  backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
  sleep: Callable[[float], None] = time.sleep,
  retriable_status: frozenset = RETRIABLE_HTTP_STATUS,
  non_retriable_status: frozenset = NON_RETRIABLE_HTTP_STATUS,
) -> requests.Response:
  """Invoke ``request_callable`` with exponential-backoff retries on
  transient failures.

  Parameters
  ----------
  request_callable
    Zero-argument callable that performs the HTTP request and returns a
    ``requests.Response``. The caller is responsible for building the
    request; this primitive only retries it.
  endpoint
    URL or short identifier used in diagnostic output. Not validated.
  max_retries
    Number of retries after the first attempt. Default 2 → 3 total
    attempts.
  backoff_base_seconds
    Base for exponential backoff. Default 1.0 → 1s, 2s.
  sleep
    Override sleep function (used for tests).
  retriable_status / non_retriable_status
    Status sets. 429 is in retriable; 400/401/403/404 are not.

  Returns
  -------
  ``requests.Response`` from a successful attempt. "Successful" means
  the request did not raise AND the status is NOT in
  ``retriable_status`` AND not in ``non_retriable_status`` (i.e., a 2xx
  or 3xx response). A response with a non-retriable error status
  causes ``NonRetriableHTTPError`` to raise rather than retry-and-fail.

  Raises
  ------
  NetworkRetryExhausted
    When all attempts produced retriable failures and the budget is
    exhausted. Carries structured diagnostic context.
  NonRetriableHTTPError
    When a single attempt returned an HTTP status that should not be
    retried (caller bug or config issue).
  """
  attempts_to_try = max(1, int(max_retries) + 1)
  attempt_log: List[AttemptOutcome] = []
  started_at = time.monotonic()
  last_failure_kind = ""
  last_status_code: Optional[int] = None
  last_exception_class: Optional[str] = None
  last_detail = ""

  for attempt_index in range(1, attempts_to_try + 1):
    attempt_started = time.monotonic()
    outcome = AttemptOutcome(attempt_index=attempt_index)
    response: Optional[requests.Response] = None
    exc_for_attempt: Optional[BaseException] = None
    try:
      response = request_callable()
    except BaseException as exc:
      exc_for_attempt = exc

    outcome.duration_seconds = time.monotonic() - attempt_started

    if exc_for_attempt is not None:
      failure_kind, retriable = _classify_connection_exception(exc_for_attempt)
      outcome.failure_kind = failure_kind
      outcome.exception_class = type(exc_for_attempt).__name__
      outcome.detail = str(exc_for_attempt)[:300]
      last_failure_kind = failure_kind
      last_status_code = None
      last_exception_class = outcome.exception_class
      last_detail = outcome.detail
      if not retriable:
        attempt_log.append(outcome)
        raise NetworkRetryExhausted(
          endpoint=endpoint,
          attempts_made=attempt_index,
          elapsed_seconds=time.monotonic() - started_at,
          final_failure_kind=failure_kind,
          final_status_code=None,
          final_exception_class=outcome.exception_class,
          final_detail=outcome.detail,
          attempt_log=[a.to_dict() for a in attempt_log],
        ) from exc_for_attempt
      if attempt_index >= attempts_to_try:
        attempt_log.append(outcome)
        break
      backoff = _exponential_backoff_seconds(
        attempt_index=attempt_index,
        backoff_base_seconds=backoff_base_seconds,
      )
      outcome.backoff_seconds_after = backoff
      attempt_log.append(outcome)
      logger.warning(
        "network_retry: %s attempt=%s/%s kind=%s detail=%s backoff=%.2fs",
        endpoint, attempt_index, attempts_to_try, failure_kind,
        outcome.detail[:120], backoff,
      )
      sleep(backoff)
      continue

    assert response is not None
    status = int(getattr(response, "status_code", 0) or 0)

    if status in non_retriable_status:
      outcome.status_code = status
      outcome.failure_kind = "non_retriable_http_status"
      outcome.detail = str(getattr(response, "text", "") or "")[:300]
      attempt_log.append(outcome)
      raise NonRetriableHTTPError(
        endpoint=endpoint,
        status_code=status,
        body_text=str(getattr(response, "text", "") or ""),
      )

    if status in retriable_status:
      outcome.status_code = status
      outcome.failure_kind = f"retriable_http_{status}"
      outcome.detail = str(getattr(response, "text", "") or "")[:300]
      last_failure_kind = outcome.failure_kind
      last_status_code = status
      last_exception_class = None
      last_detail = outcome.detail
      if attempt_index >= attempts_to_try:
        attempt_log.append(outcome)
        break
      retry_after = _parse_retry_after(
        (getattr(response, "headers", {}) or {}).get("Retry-After")
      ) if status == 429 else None
      backoff = (
        float(retry_after)
        if retry_after is not None
        else _exponential_backoff_seconds(
          attempt_index=attempt_index,
          backoff_base_seconds=backoff_base_seconds,
        )
      )
      outcome.backoff_seconds_after = backoff
      attempt_log.append(outcome)
      logger.warning(
        "network_retry: %s attempt=%s/%s status=%s backoff=%.2fs%s",
        endpoint, attempt_index, attempts_to_try, status, backoff,
        " (Retry-After)" if retry_after is not None else "",
      )
      sleep(backoff)
      continue

    # Success — return the response. Status may still be >= 400 if
    # it's not in either set (e.g., 451). Caller decides whether to
    # treat as failure; the retry primitive's job is done.
    return response

  raise NetworkRetryExhausted(
    endpoint=endpoint,
    attempts_made=attempts_to_try,
    elapsed_seconds=time.monotonic() - started_at,
    final_failure_kind=last_failure_kind,
    final_status_code=last_status_code,
    final_exception_class=last_exception_class,
    final_detail=last_detail,
    attempt_log=[a.to_dict() for a in attempt_log],
  )


def _exponential_backoff_seconds(
  *,
  attempt_index: int,
  backoff_base_seconds: float,
) -> float:
  """Exponential backoff. attempt_index=1 -> base, 2 -> 2*base, ..."""
  base = max(0.0, float(backoff_base_seconds))
  exponent = max(0, int(attempt_index) - 1)
  return float(base * (2**exponent))
