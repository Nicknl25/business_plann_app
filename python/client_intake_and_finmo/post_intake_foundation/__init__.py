"""Shared post-intake foundation checks."""

from .golden_rule import (
  post_intake_golden_rule_errors,
  post_intake_assert_golden_rule_integrity,
  post_intake_runtime_table_integrity_errors,
  post_intake_assert_runtime_table_integrity,
)
from .runtime_binding import (
  bind_table_safe_runtime_dependencies,
  table_safe_runtime_bindings,
)
__all__ = [
  "post_intake_golden_rule_errors",
  "post_intake_assert_golden_rule_integrity",
  "post_intake_runtime_table_integrity_errors",
  "post_intake_assert_runtime_table_integrity",
  "bind_table_safe_runtime_dependencies",
  "table_safe_runtime_bindings",
]
