"""Phase 9 P3.5 — GPT exhaustion handler (tool-calling pattern).

When the deterministic restoration loop returns RestorationStatus.EXHAUSTED
at conservative bounds, this handler is the authoritative path that lands
Q11 EBITDA viability without delivering a broken plan.

Pipeline (post-restoration):
  1. Build operating context (Q1 actual state, capacity-driver detection,
     FINMO callable closure).
  2. Run GPT tool-calling session: GPT proposes driver anchors and calls
     compute_full_trajectory(anchors) to verify the EBITDA path the
     system would compute. GPT iterates against the tool result up to
     MAX_TOOL_CALLS times, then commits a final answer.
  3. Path engine interpolates anchors -> 20 quarters per driver.
  4. System writes per-quarter values to model_input, tags
     gpt_authored=True (FINMO contracts: skip Capacity for labor-driven,
     integer-round capacity, clip utilization).
  5. FINMO rebuild so the rest of the post-cascade tail sees the
     GPT-authored operating model.
  6. Mute realism flags whose primary_levers include GPT-authored
     drivers (per-draft, per-metric — universal viability trajectory
     checks stay active).

The Call 1 / Call 2 / iteration / snap-into-place pattern is retired.
GPT verifies the math himself before committing — the structural gap
between his anchored target and FINMO's computed result no longer
exists because the tool runs full FINMO under the hood.

Universal-app principle: same handler runs for every NAICS, every stage,
every business archetype. Differences in output come from the
operating_model_json data passed in, NOT from business-classification
branches in code.

Cash strategy is NOT touched. Cash strategy continues to run AFTER this
handler completes, unchanged.
"""

from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (
  HandlerResult,
  HandlerStatus,
  run_gpt_exhaustion_handler,
)

__all__ = [
  "HandlerResult",
  "HandlerStatus",
  "run_gpt_exhaustion_handler",
]
