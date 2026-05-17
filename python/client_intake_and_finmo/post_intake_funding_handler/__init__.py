"""Iter 19 Stage 4 — Cash-funding handler.

Engaged when ``cash_buffer_violations`` is non-empty after the Python
cash-strategy proposer's post-pass validation. Per docs/architecture/
doctrine.md §6 (Handler Inventory): authority over

  - ``schedules::Debt Issuance (New Borrowing)``
  - ``schedules::Debt Repayment (Scheduled)``
  - ``balance_sheet::Owner's Capital``
  - ``balance_sheet::Other Equity``
  - ``balance_sheet::Distributions``
  - ``planning_run_json.cash_strategy_mode`` override

Engagement trigger: ``cash_buffer_violations`` non-empty after the cash
strategy post-pass.

10-tool-call budget. Bypasses run-wide GPT budget (handler-budget
decoupling per iter 17, doctrine.md §5).

This iter (19) ships the deterministic correction engine — Python
walks each violating quarter and tries to fill the buffer gap by
incrementing funding levers in priority order within their per-quarter
``lever_bounds``. The full GPT tool-calling variant (using
``compute_full_trajectory`` mirror like the exhaustion handler) is
scaffolded but flag-gated; ``run_funding_handler`` calls only the
deterministic core today.

Production wiring of ``run_funding_handler`` into the cash runner's
post-pass branch is documented in docs/architecture/doctrine.md §6 as
the next-iter follow-up; see Stage 8 documentation.
"""

from client_intake_and_finmo.post_intake_funding_handler.handler import (
  FundingHandlerResult,
  FundingHandlerStatus,
  apply_authored_lever_changes_to_model_input,
  engage_funding_handler_on_violations,
  run_funding_handler,
)

__all__ = [
  "FundingHandlerResult",
  "FundingHandlerStatus",
  "apply_authored_lever_changes_to_model_input",
  "engage_funding_handler_on_violations",
  "run_funding_handler",
]
