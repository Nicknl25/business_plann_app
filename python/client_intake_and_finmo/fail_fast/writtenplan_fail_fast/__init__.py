"""Written-plan fail-fast authority."""

from __future__ import annotations

from .fail_fast import (
  WRITTENPLAN_FAIL_FAST_ENV,
  writtenplan_fail_fast_enabled,
  writtenplan_fail_fast_raise,
  writtenplan_fail_fast_result,
)

__all__ = [
  "WRITTENPLAN_FAIL_FAST_ENV",
  "writtenplan_fail_fast_enabled",
  "writtenplan_fail_fast_raise",
  "writtenplan_fail_fast_result",
]
