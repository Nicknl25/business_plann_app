"""Iter 19 Stage 5 — Stage ramp handler prompts.

The system prompt and tool definition are co-located with the
tool-calling session loop (see :mod:`tool_calling_session`). This
module re-exports them as ``STAGE_RAMP_HANDLER_SYSTEM_PROMPT`` and
``PROBE_STAGE_RAMP_CONTRACT_TOOL_DEFINITION`` for use by external
consumers (tests, docs).
"""

from __future__ import annotations

from typing import Any, Dict

from client_intake_and_finmo.post_intake_stage_ramp_handler.tool_calling_session import (
  EXTENSION_PROMPT_TEXT,
  SYSTEM_PROMPT,
  _build_tool_definition,
)


STAGE_RAMP_HANDLER_SYSTEM_PROMPT: str = SYSTEM_PROMPT
STAGE_RAMP_HANDLER_EXTENSION_PROMPT: str = EXTENSION_PROMPT_TEXT


def probe_stage_ramp_contract_tool_definition() -> Dict[str, Any]:
  """Return the Responses-API tool definition for the stage ramp
  probe tool. Built fresh each call so callers can mutate the dict
  without affecting the canonical schema."""
  return _build_tool_definition()


PROBE_STAGE_RAMP_CONTRACT_TOOL_DEFINITION: Dict[str, Any] = probe_stage_ramp_contract_tool_definition()
