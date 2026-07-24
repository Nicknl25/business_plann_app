"""Shared fail-fast primitives."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


_FALSE_VALUES = {"0", "false", "no", "off", "disabled"}


class PostIntakePreconditionFailed(RuntimeError):
  """Phase 9 P3.10 — hard-fail raised when a critical post-intake
  operation's precondition fails or an unrecoverable error is hit.

  Carries structured diagnostic context so the operator can identify
  the exact fix in one log line: the operation that failed, the
  expected state, the actual state, and where in the pipeline the
  failure occurred. Only raised when ``CONVERGENCE_TEST_MODE`` is
  enabled — production-mode callers continue to receive the legacy
  status-dict pattern (separate decision).

  Distinguished from ``FailFastError`` (state-checking asserts in
  ``post_intake_fail_fast``) — ``PostIntakePreconditionFailed`` is for
  operation-level preconditions (build_finmo, GPT session, post-commit
  rebuild, writer contract violations) where the operation cannot
  produce a usable result. ``FailFastError`` is for state invariants
  (model_input rows, FINMO statement math, contract conformance) that
  must hold across operation boundaries.
  """

  def __init__(
    self,
    *,
    operation: str,
    pipeline_stage: str,
    expected: str = "",
    actual: str = "",
    details: Optional[Dict[str, Any]] = None,
    cause: Optional[BaseException] = None,
  ) -> None:
    self.operation = str(operation or "").strip()
    self.pipeline_stage = str(pipeline_stage or "").strip()
    self.expected = str(expected or "").strip()
    self.actual = str(actual or "").strip()
    self.details = details if isinstance(details, dict) else {}
    self.cause = cause
    header = (
      f"post_intake_precondition_failed: operation={self.operation} "
      f"pipeline_stage={self.pipeline_stage}"
    )
    if self.expected or self.actual:
      header += f" expected={self.expected!r} actual={self.actual!r}"
    if cause is not None:
      header += f" cause={type(cause).__name__}: {str(cause)[:200]}"
    super().__init__(header)

  def to_dict(self) -> Dict[str, Any]:
    return {
      "operation": self.operation,
      "pipeline_stage": self.pipeline_stage,
      "expected": self.expected,
      "actual": self.actual,
      "details": dict(self.details),
      "cause_class": type(self.cause).__name__ if self.cause else None,
      "cause_detail": str(self.cause)[:500] if self.cause else None,
    }


class FailFastError(RuntimeError):
  """Runtime error raised when an enabled fail-fast guard trips."""

  def __init__(
    self,
    code: str,
    message: str = "",
    *,
    phase: str = "",
    stage: str = "",
    details: Optional[Dict[str, Any]] = None,
  ) -> None:
    self.code = str(code or "fail_fast_violation").strip()
    self.phase = str(phase or "").strip()
    self.stage = str(stage or "").strip()
    self.details = details if isinstance(details, dict) else {}
    prefix = self.code
    if self.phase:
      prefix = f"{self.phase}:{prefix}"
    if self.stage:
      prefix = f"{prefix}@{self.stage}"
    body = str(message or self.code).strip()
    super().__init__(f"{prefix}: {body}")


class FailFastDisabled(RuntimeError):
  """Raised only by callers that explicitly require fail-fast to be enabled."""


def _env_bool(name: str, *, default: bool = True) -> bool:
  raw = os.getenv(name)
  if raw is None:
    return bool(default)
  return str(raw).strip().lower() not in _FALSE_VALUES


def convergence_test_mode_enabled() -> bool:
  """Fail-loud mode. Despite the historical name, this is NOT test-only:
  as of the fallback-class fix it defaults ON — every gated fail-loud
  conversion (realism formula exceptions, cash-strategy/funding GPT
  failures, mini-finmo preconditions, ...) raises in production too.
  Doctrine: no plan ships on substituted judgment; a failed run stops
  and is retried by the supervisor, it does not degrade silently.

  CONVERGENCE_TEST_MODE=0 remains as an explicit, deliberate emergency
  kill switch only."""
  return _env_bool("CONVERGENCE_TEST_MODE", default=True)


def fail_fast_enabled(phase: str) -> bool:
  normalized = str(phase or "").strip().upper()
  if not convergence_test_mode_enabled():
    return False
  if not _env_bool("FAIL_FAST_ENABLED", default=True):
    return False
  if not normalized:
    return True
  return _env_bool(f"{normalized}_FAIL_FAST_ENABLED", default=True)


def fail_fast_result(
  code: str,
  message: str = "",
  *,
  phase: str,
  stage: str = "",
  details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  return {
    "fail_fast_enabled": fail_fast_enabled(phase),
    "phase": str(phase or "").strip(),
    "stage": str(stage or "").strip(),
    "code": str(code or "fail_fast_violation").strip(),
    "message": str(message or code or "fail_fast_violation").strip(),
    "details": details if isinstance(details, dict) else {},
  }


def fail_fast_raise(
  code: str,
  message: str = "",
  *,
  phase: str,
  stage: str = "",
  details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  result = fail_fast_result(
    code,
    message,
    phase=phase,
    stage=stage,
    details=details,
  )
  if result["fail_fast_enabled"]:
    raise FailFastError(
      result["code"],
      result["message"],
      phase=result["phase"],
      stage=result["stage"],
      details=result["details"],
    )
  return result
