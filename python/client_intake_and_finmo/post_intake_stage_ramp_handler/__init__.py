"""P3.33 Phase 3 step 3a — stage_ramp handler package.

Reduced from the pre-amalgamation set of exports
(``StageRampHandlerResult``, ``StageRampHandlerStatus``,
``run_stage_ramp_handler``) to just the orchestrator-wiring entry
point. The GPT session loop, the verified-commit-candidate model, the
machinery contextvars, prompts, and the standalone mini_finmo are all
gone; authoring authority for the stage_ramp_contract now belongs to
``post_intake_amalgamated.tools.set_stage_ramp_contract``.

``engage_stage_ramp_handler_on_validator_failure`` remains as a thin
shim because ``api_handlers/intake_consult.py`` still wires it as the
orchestrator's stage_ramp authoring callable. Step 5 (amalgamated
session) will remove this shim and call ``set_stage_ramp_contract``
directly.
"""

from client_intake_and_finmo.post_intake_stage_ramp_handler.handler import (
  engage_stage_ramp_handler_on_validator_failure,
)

__all__ = [
  "engage_stage_ramp_handler_on_validator_failure",
]
