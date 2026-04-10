from __future__ import annotations

import copy
from typing import Any, Dict

from .agent_base import BaseAppAgent


_GRID_EXPERTISE = """
You are the grid_agent. You are the constrained final integrator for the app-agent planner.
You must produce the exact same solver-compatible quarter-grid shape the current solver already expects.
You are the final author of the grid, but you are not allowed to ignore the binding outputs of realism_agent, operations_agent, or capital_agent.
If their constraints cannot be satisfied together, you must surface a blocked status rather than silently weakening them.
"""


class GridAgent(BaseAppAgent):
  def __init__(self) -> None:
    super().__init__(
      agent_name="grid_agent",
      schema_file="grid_agent_output.schema.json",
      expertise_brief=_GRID_EXPERTISE,
      prompt_file="grid_agent.md",
    )

  def build_request(
    self,
    *,
    shared_context: Dict[str, Any],
    realism_agent_output: Dict[str, Any],
    operations_agent_output: Dict[str, Any],
    capital_agent_output: Dict[str, Any],
    previous_grid_output: Dict[str, Any] | None = None,
    revision_directive: str = "",
    **kwargs: Any,
  ) -> Dict[str, Any]:
    payload = super().build_request(shared_context=shared_context, **kwargs)
    payload["realism_agent_output"] = copy.deepcopy(realism_agent_output or {})
    payload["operations_agent_output"] = copy.deepcopy(operations_agent_output or {})
    payload["capital_agent_output"] = copy.deepcopy(capital_agent_output or {})
    if isinstance(previous_grid_output, dict) and previous_grid_output:
      payload["previous_grid_output"] = copy.deepcopy(previous_grid_output)
    if str(revision_directive or "").strip():
      payload["revision_directive"] = str(revision_directive).strip()
    payload["focus"] = (
      "final grid integration, conflict resolution, solver-contract preservation, row coherence, and explicit blocked status when constraints cannot be satisfied together"
    )
    return payload
