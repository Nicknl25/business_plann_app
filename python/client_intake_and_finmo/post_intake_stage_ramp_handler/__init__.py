"""Iter 19 Stage 5 — Stage ramp handler.

Engaged when the Python deterministic stage ramp builder
(``build_python_stage_ramp_contract`` in
post_intake_contracts/runner.py) produces a contract that fails the
stage ramp realism validator
(``_validate_stage_ramp_contract_payload``).

Per docs/architecture/doctrine.md §6 (Handler Inventory): authority
over the stage_ramp_contract grid fields:

  - quarter_ramp_grid[].rev_target / rev_max / rev_spike_max / rev_spike
  - quarter_ramp_grid[].max_util (utilization_cap)
  - quarter_ramp_grid[].cogs_target / cogs_max
  - quarter_ramp_grid[].marketing_max / rd_max / ga_max / lease_max
  - quarter_ramp_grid[].ni_floor / posture
  - utilization_high_watermark
  - rationale

The handler's role: refine the deterministic ramp when validator
constraints conflict with cohort-default values (e.g., the cohort
suggests an aggressive growth rate that conflicts with the
operator's stated stage, or cost ratio defaults trip a policy floor).

10-tool-call budget. Bypasses run-wide GPT budget per iter 17.

Live API integration is unverified pending end-of-iter E2E sweep.
"""

from client_intake_and_finmo.post_intake_stage_ramp_handler.handler import (
  StageRampHandlerResult,
  StageRampHandlerStatus,
  engage_stage_ramp_handler_on_validator_failure,
  run_stage_ramp_handler,
)

__all__ = [
  "StageRampHandlerResult",
  "StageRampHandlerStatus",
  "engage_stage_ramp_handler_on_validator_failure",
  "run_stage_ramp_handler",
]
