"""Phase 9 P3.5 — GPT exhaustion handler.

When the deterministic restoration loop returns RestorationStatus.EXHAUSTED
at conservative bounds, this handler is the authoritative path that lands
Q11 EBITDA viability without delivering a broken plan.

Pipeline (post-restoration):
  1. Call 1 — GPT returns EBITDA anchors {Q1, Q11, Q20}.
  2. Call 2 — GPT returns driver anchors that produce those EBITDA values.
  3. Path engine interpolates anchors -> 20 quarters per driver.
  4. System writes per-quarter values to model_input, tags
     gpt_authored=True.
  5. FINMO recalculates.
  6. Compare FINMO Q11 EBITDA vs GPT's Q11 EBITDA anchor (tolerance ±50bps).
  7. If gap, iterate up to 3 times. Each iteration is a fresh GPT call
     with cumulative diagnostic. GPT keeps Call 1 EBITDA anchor stable
     and updates drivers only.
  8. If 3 iterations don't converge, deterministic solver snaps drivers
     to GPT's EBITDA anchor as target ramp.
  9. Mute realism flags that triggered exhaustion (per-draft, per-metric).

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
