"""Intake fail-fast authority."""

from __future__ import annotations

from .fail_fast import (
  INTAKE_FAIL_FAST_ENV,
  intake_fail_fast_enabled,
  intake_fail_fast_raise,
  intake_fail_fast_result,
)

__all__ = [
  "INTAKE_FAIL_FAST_ENV",
  "intake_fail_fast_enabled",
  "intake_fail_fast_raise",
  "intake_fail_fast_result",
]
