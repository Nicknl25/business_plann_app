from __future__ import annotations

import copy
from typing import Any, Dict

from .version import APP_AGENTS_CONTRACT_VERSION


def build_app_agents_run_payload(
  *,
  shared_context: Dict[str, Any],
  realism_agent: Dict[str, Any],
  operations_agent: Dict[str, Any],
  capital_agent: Dict[str, Any],
  grid_agent: Dict[str, Any],
  execution_trace: Any = None,
) -> Dict[str, Any]:
  planner_status = str((grid_agent or {}).get("planner_status") or "blocked").strip() or "blocked"
  return {
    "contract_version": APP_AGENTS_CONTRACT_VERSION,
    "planner_status": planner_status,
    "execution_trace": [dict(item) for item in (execution_trace or []) if isinstance(item, dict)],
    "shared_context": copy.deepcopy(shared_context or {}),
    "realism_agent": copy.deepcopy(realism_agent or {}),
    "operations_agent": copy.deepcopy(operations_agent or {}),
    "capital_agent": copy.deepcopy(capital_agent or {}),
    "grid_agent": copy.deepcopy(grid_agent or {}),
  }
