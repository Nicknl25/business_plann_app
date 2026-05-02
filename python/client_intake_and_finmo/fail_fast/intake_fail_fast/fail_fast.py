"""Intake fail-fast switches."""

from __future__ import annotations

from typing import Any, Dict, Optional

from client_intake_and_finmo.fail_fast.common import (  # type: ignore
  fail_fast_enabled,
  fail_fast_raise,
  fail_fast_result,
)


INTAKE_FAIL_FAST_ENV = "INTAKE_FAIL_FAST_ENABLED"


def intake_fail_fast_enabled() -> bool:
  return fail_fast_enabled("INTAKE")


def intake_fail_fast_result(
  code: str,
  message: str = "",
  *,
  stage: str = "",
  details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  return fail_fast_result(code, message, phase="INTAKE", stage=stage, details=details)


def intake_fail_fast_raise(
  code: str,
  message: str = "",
  *,
  stage: str = "",
  details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  return fail_fast_raise(code, message, phase="INTAKE", stage=stage, details=details)
