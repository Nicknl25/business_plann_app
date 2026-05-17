"""Iter 19 Stage 4 — Funding handler prompts (scaffold).

System prompt and tool-definition scaffolds for the GPT-driven variant
of the funding handler (see :mod:`tool_calling_session`). The
deterministic correction path in
:func:`post_intake_funding_handler.handler.run_funding_handler` does
not consume these prompts; they are kept here for the follow-up iter
that wires real GPT tool-calling.

Per docs/architecture/doctrine.md §5 the prompt MUST narrow GPT to
the handler's defined lever authority. The funding handler's
authority is:

  - ``schedules::Debt Issuance (New Borrowing)``
  - ``schedules::Debt Repayment (Scheduled)``
  - ``balance_sheet::Owner's Capital``
  - ``balance_sheet::Other Equity``
  - ``balance_sheet::Distributions``

Any tool-call that proposes editing a lever NOT in this list is a
mis-shaped handler (doctrine.md §7 anti-pattern, F6-Pinnacle
authority/check mismatch).
"""

from __future__ import annotations

from typing import Any, Dict


FUNDING_HANDLER_SYSTEM_PROMPT: str = (
  "You are the funding handler for a post-intake business plan. The "
  "Python cash-strategy proposer has produced a funding plan that "
  "trips one or more cash_buffer_violations: the plan's ending cash "
  "is below the buffer requirement in those quarters. Your job is to "
  "AUTHOR funding-lever changes that close the residual gap without "
  "violating the per-quarter lever_bounds.\n"
  "\n"
  "Your lever authority is strictly limited to:\n"
  "  - schedules::Debt Issuance (New Borrowing)\n"
  "  - schedules::Debt Repayment (Scheduled)\n"
  "  - balance_sheet::Owner's Capital\n"
  "  - balance_sheet::Other Equity\n"
  "  - balance_sheet::Distributions\n"
  "\n"
  "You may also override planning_run_json.cash_strategy_mode when "
  "the operator's chronic posture conflicts with the buffer mechanics "
  "(e.g., a preserve_cash mode rejecting debt issuance when chronic "
  "gaps require it). Document the override rationale.\n"
  "\n"
  "You have a 10 tool-call budget. Each tool call invokes "
  "compute_full_trajectory with proposed lever adjustments and "
  "returns the resulting cash trajectory. When all "
  "cash_buffer_violations are filled, commit your final answer. If "
  "the gap cannot be closed within the per-quarter lever_bounds, "
  "return a residual report naming the unfillable quarters — the "
  "system will hard-fail with a specific diagnostic rather than "
  "ship a broken plan."
)


COMPUTE_FULL_TRAJECTORY_TOOL_DEFINITION: Dict[str, Any] = {
  "type": "function",
  "function": {
    "name": "compute_full_trajectory",
    "description": (
      "Run the mini_finmo cash-trajectory mirror with proposed funding-lever "
      "adjustments. Returns per-quarter ending_cash and per-quarter "
      "buffer-violation residuals. Use this to verify your proposed "
      "adjustments close the violations before committing."
    ),
    "parameters": {
      "type": "object",
      "properties": {
        "lever_adjustments": {
          "type": "object",
          "description": (
            "Map of lever_id -> { quarter_index: signed_amount }. "
            "Positive amounts increase the lever; negative amounts "
            "decrease it. Levers outside the handler's authority are "
            "rejected with a specific diagnostic."
          ),
        },
        "cash_strategy_mode_override": {
          "type": ["string", "null"],
          "enum": ["preserve_cash", "balanced", "shareholder_return", None],
          "description": (
            "Optional override for planning_run_json.cash_strategy_mode. "
            "Use only when the operator's chronic posture conflicts with "
            "the buffer mechanics. Document rationale in the commit payload."
          ),
        },
      },
      "required": ["lever_adjustments"],
      "additionalProperties": False,
    },
  },
}


def build_funding_handler_user_payload(
  *,
  cash_buffer_violations: Any,
  lever_bounds: Any,
) -> Dict[str, Any]:
  """Construct the user-side payload for the GPT-driven variant.

  Not consumed by the deterministic path. Kept here so the follow-up
  iter that wires real GPT tool-calling has the input shape already
  defined.
  """
  return {
    "cash_buffer_violations": cash_buffer_violations,
    "lever_bounds": lever_bounds,
    "instructions": (
      "Author funding-lever adjustments that resolve every violation. "
      "Verify each proposal with compute_full_trajectory before "
      "committing. Hard-fail with a residual report if any quarter "
      "cannot be filled within lever_bounds."
    ),
  }
