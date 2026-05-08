"""Phase 8 — replacement for the deleted post_intake_issues machinery.

This module provides the small, well-defined replacement surface that
the convergence runner, cash runner, contracts runner, state runner,
and convergence runtime now consume. The legacy issue ledger / issue
status records / controller_resolution_state are gone — the realism
gate (post_intake_realism), cascade diagnostics
(post_intake_solver.adaptation_cascade), and planning_mode_policy
(post_intake_realism.lookup) are the new authority.

Function names mirror the legacy bound names so the call-site changes
are minimal: callers replace
``from <bind injection> _build_realism_memo_from_issue_ledger``
with
``from client_intake_and_finmo.post_intake_resolution_state import
  build_realism_memo``.
The dict shapes the functions return remain compatible with what the
existing planning_run_json / realism_memo_json schemas expect, so
downstream readers (workbook export, planning_runtime_json) still work.
"""

from __future__ import annotations

from client_intake_and_finmo.post_intake_resolution_state.state import (  # type: ignore
  build_controller_resolution_state,
  build_persisted_realism_memo_payload,
  build_realism_memo,
  build_resolution_summary,
  empty_controller_resolution_state,
  empty_realism_memo,
  empty_resolution_summary,
  filter_cash_pass_owned_issue_records,
  financial_story_issue_codes,
  issue_status_records_from_state,
  realism_gate_hard_fail_count,
  realism_gate_hard_fail_metric_keys,
)

__all__ = [
  "build_controller_resolution_state",
  "build_persisted_realism_memo_payload",
  "build_realism_memo",
  "build_resolution_summary",
  "empty_controller_resolution_state",
  "empty_realism_memo",
  "empty_resolution_summary",
  "filter_cash_pass_owned_issue_records",
  "financial_story_issue_codes",
  "issue_status_records_from_state",
  "realism_gate_hard_fail_count",
  "realism_gate_hard_fail_metric_keys",
]
