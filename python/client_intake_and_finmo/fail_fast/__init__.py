"""Central fail-fast ownership.

Fail-fast behavior is structural infrastructure, not business judgment. Keep the
phase toggles and fail helpers here so phase code can call one authority instead
of scattering environment checks and raw RuntimeError construction.
"""

from __future__ import annotations

from .common import (
  FailFastDisabled,
  FailFastError,
  convergence_test_mode_enabled,
  fail_fast_enabled,
  fail_fast_raise,
  fail_fast_result,
)

__all__ = [
  "FailFastDisabled",
  "FailFastError",
  "convergence_test_mode_enabled",
  "fail_fast_enabled",
  "fail_fast_raise",
  "fail_fast_result",
]
