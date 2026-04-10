from __future__ import annotations

from typing import Any, Dict

from .agent_base import BaseAppAgent


_REALISM_EXPERTISE = """
You are the realism_agent. You reason like a top-tier business strategist and operator with deep knowledge of business models, business types, growth patterns, and commercial realism.
Your job is to define what is believable, what is not believable, and what row patterns would violate the real-world operating logic of this business.
You do not author the final grid. You produce binding realism constraints, vetoes, and row/quarter implications that the grid_agent must obey.
"""


class RealismAgent(BaseAppAgent):
  def __init__(self) -> None:
    super().__init__(
      agent_name="realism_agent",
      schema_file="realism_agent_output.schema.json",
      expertise_brief=_REALISM_EXPERTISE,
      prompt_file="realism_agent.md",
    )

  def _extra_request_fields(self, **kwargs: Any) -> Dict[str, Any]:
    return {
      "focus": "business-model realism, business-type realism, forbidden patterns, row realism, and quarter pacing realism",
      **dict(kwargs or {}),
    }
