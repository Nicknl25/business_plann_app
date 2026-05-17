"""Iter 19 Stage 4 — Funding handler tool-calling session (scaffold).

This module is the scaffold for the GPT-driven variant of the funding
handler. It mirrors the structure of
``post_intake_gpt_exhaustion_handler.tool_calling_session`` so the
two handlers share the same authoritative shape:

  - ``HARD_CAP_TOOL_CALLS = 10`` (docs/architecture/doctrine.md §5).
  - ``counts_against_run_budget=False`` for any OpenAI invocation
    inside the session (iter 17 decoupling).

The deterministic per-quarter allocator at
:func:`post_intake_funding_handler.handler.run_funding_handler` is the
authoritative correction path today; this scaffold documents the
intended shape of the GPT-driven variant for the follow-up iter that
wires real tool-calling.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


# Mirror the exhaustion handler's authoritative budget constant. See
# post_intake_gpt_exhaustion_handler/tool_calling_session.py:22.
INITIAL_TOOL_CALL_BUDGET: int = 8
EXTENSION_TOOL_CALLS: int = 2
HARD_CAP_TOOL_CALLS: int = INITIAL_TOOL_CALL_BUDGET + EXTENSION_TOOL_CALLS  # 10
MAX_TOOL_CALLS: int = HARD_CAP_TOOL_CALLS


# Run-budget decoupling flag. Per iter 17 (commit 8dfd23a) every
# handler-internal OpenAI invocation must pass this flag so the
# handler does not consume the run-wide GPT budget. Production wiring
# of the GPT-driven variant must thread this through every
# ``_post_openai`` call inside this module.
COUNTS_AGAINST_RUN_BUDGET: bool = False


def run_funding_tool_calling_session(
  *,
  cash_buffer_violations: List[Dict[str, Any]],
  lever_bounds: Optional[Dict[str, List[Dict[str, Any]]]] = None,
  context_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Scaffold entry point for the GPT-driven funding session.

  Today this function is intentionally NOT wired. The deterministic
  allocator in :func:`post_intake_funding_handler.handler.run_funding_handler`
  is the correction path; production callers should use that.

  When the GPT-driven variant is implemented in a follow-up iter, the
  shape of this function will be:

    1. Build a system prompt from :mod:`prompts` describing the
       handler's funding-lever authority and the current violations.
    2. Loop up to ``HARD_CAP_TOOL_CALLS`` times. Each iteration GPT
       proposes a funding adjustment via the
       ``compute_full_trajectory`` tool (the mini_finmo mirror runs
       the proposed changes through a simplified cash projection so
       GPT can preview the result before committing).
    3. Commit the final answer; return authored lever changes.
    4. Every OpenAI call passes ``counts_against_run_budget=False``
       (iter 17 fix).

  Raising :class:`NotImplementedError` rather than silently returning
  a no-op is the doctrine-aligned hard-fail diagnostic — callers that
  reach this path indicate a wiring error.
  """
  raise NotImplementedError(
    "iter 19 Stage 4 ships the deterministic funding handler only. "
    "GPT-driven funding tool-calling is scaffolded but not yet wired. "
    "Use post_intake_funding_handler.run_funding_handler for "
    "deterministic correction; the GPT-driven variant is the "
    "follow-up iter's work."
  )
