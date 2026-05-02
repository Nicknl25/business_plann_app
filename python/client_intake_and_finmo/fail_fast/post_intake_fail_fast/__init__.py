"""Post-intake fail-fast authority."""

from __future__ import annotations

from .fail_fast import (
  CASH_STRATEGY_TEST_MODE_FAIL_FLAGS,
  CONVERGENCE_TEST_MODE_FAIL_FLAGS,
  PAYROLL_HEADCOUNT_TEST_MODE_FAIL_FLAGS,
  POST_INTAKE_FAIL_FAST_ENV,
  TRANSLATION_TEST_MODE_FAIL_FLAGS,
  post_intake_convergence_test_mode_enabled,
  post_intake_fail_fast_enabled,
  post_intake_fail_fast_raise,
  post_intake_fail_fast_result,
)

__all__ = [
  "CASH_STRATEGY_TEST_MODE_FAIL_FLAGS",
  "CONVERGENCE_TEST_MODE_FAIL_FLAGS",
  "PAYROLL_HEADCOUNT_TEST_MODE_FAIL_FLAGS",
  "POST_INTAKE_FAIL_FAST_ENV",
  "TRANSLATION_TEST_MODE_FAIL_FLAGS",
  "post_intake_convergence_test_mode_enabled",
  "post_intake_fail_fast_enabled",
  "post_intake_fail_fast_raise",
  "post_intake_fail_fast_result",
]
