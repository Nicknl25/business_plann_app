from __future__ import annotations

from typing import Any, Dict

from .agent_base import BaseAppAgent


_OPERATIONS_EXPERTISE = """
You are the operations_agent. You reason like a top-tier operator with deep knowledge of staffing, throughput, service delivery, facilities, growth pacing, and support-row dependencies.
Your job is to define what this business can realistically absorb operationally across 20 quarters.
You do not author the final grid. You produce binding operating constraints, vetoes, sequencing rules, and row/quarter implications that the grid_agent must obey.
"""


class OperationsAgent(BaseAppAgent):
  def __init__(self) -> None:
    super().__init__(
      agent_name="operations_agent",
      schema_file="operations_agent_output.schema.json",
      expertise_brief=_OPERATIONS_EXPERTISE,
      prompt_file="operations_agent.md",
    )

  def _extra_request_fields(self, **kwargs: Any) -> Dict[str, Any]:
    return {
      "focus": "throughput, staffing, facilities, sequencing, operating dependencies, and growth absorption",
      **dict(kwargs or {}),
    }
