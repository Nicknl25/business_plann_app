from __future__ import annotations

from typing import Any, Dict

from .agent_base import BaseAppAgent


_CAPITAL_EXPERTISE = """
You are the capital_agent. You reason like a top-tier CFO, capital allocator, and growth strategist with deep knowledge of liquidity, operating buffers, excess cash, redeployment, shareholder return, and capital discipline.
Your job is to translate the selected cash strategy into binding liquidity and capital-allocation constraints that are visibly meaningful and realistic for this business type.
You do not author the final grid. You produce binding capital constraints, vetoes, strategy-visibility requirements, and row/quarter implications that the grid_agent must obey.
"""


class CapitalAgent(BaseAppAgent):
  def __init__(self) -> None:
    super().__init__(
      agent_name="capital_agent",
      schema_file="capital_agent_output.schema.json",
      expertise_brief=_CAPITAL_EXPERTISE,
      prompt_file="capital_agent.md",
    )

  def _extra_request_fields(self, **kwargs: Any) -> Dict[str, Any]:
    return {
      "focus": "liquidity posture, cash buffers, excess cash, growth redeployment, shareholder return, visible strategy expression across all four strategies, and a machine-usable capital operating system for grid execution",
      **dict(kwargs or {}),
    }
