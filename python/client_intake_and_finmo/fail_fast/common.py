"""Shared fail-fast primitives."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


_FALSE_VALUES = {"0", "false", "no", "off", "disabled"}


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
  return _env_bool("CONVERGENCE_TEST_MODE", default=False)


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
