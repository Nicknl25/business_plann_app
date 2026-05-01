"""Shared post-intake foundation checks."""

from .golden_rule import (
  post_intake_golden_rule_errors,
  post_intake_assert_golden_rule_integrity,
)
from .runtime_binding import (
  bind_table_safe_runtime_dependencies,
  table_safe_runtime_bindings,
)
from .fail_flags import (
  CASH_STRATEGY_TEST_MODE_FAIL_FLAGS,
  CONVERGENCE_TEST_MODE_FAIL_FLAGS,
  PAYROLL_HEADCOUNT_TEST_MODE_FAIL_FLAGS,
  TRANSLATION_TEST_MODE_FAIL_FLAGS,
)

__all__ = [
  "post_intake_golden_rule_errors",
  "post_intake_assert_golden_rule_integrity",
  "bind_table_safe_runtime_dependencies",
  "table_safe_runtime_bindings",
  "CASH_STRATEGY_TEST_MODE_FAIL_FLAGS",
  "CONVERGENCE_TEST_MODE_FAIL_FLAGS",
  "PAYROLL_HEADCOUNT_TEST_MODE_FAIL_FLAGS",
  "TRANSLATION_TEST_MODE_FAIL_FLAGS",
]
