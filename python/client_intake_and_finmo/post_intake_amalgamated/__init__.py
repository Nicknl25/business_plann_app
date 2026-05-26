"""P3.33 Phase 3 — Amalgamated post-intake session machinery.

Phase 3 step 2 deliverables exported here:
  - evaluation_types : FailureMode + structured result dataclasses
  - evaluate_plan    : the deterministic plan evaluator (mini_finmo +
                       full 16-check acceptance gate paths)
  - mirror           : the per-decision context object handed to GPT

Per the manager/executive framing: this package is the manager's
toolkit. evaluate_plan is the standards check; the Mirror is the
manager's view of the situation. GPT (in later commits) reads the
mirror and proposes one move at a time within tools; Python keeps
the protocol, the sequence, and the floor.
"""

from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (  # noqa: F401
  FailureMode,
  CheckResult,
  LeverMargin,
  QuarterTrajectory,
  EvaluatePlanResult,
)
from client_intake_and_finmo.post_intake_amalgamated.evaluate_plan import (  # noqa: F401
  evaluate_plan,
  classify_failure,
  attribute_to_sections,
)
from client_intake_and_finmo.post_intake_amalgamated.mirror import (  # noqa: F401
  Mirror,
  build_mirror,
  estimate_token_count,
)
# RecentDecision DROPPED per P3.40 Cleanup 3/6 Contract 7 R10.
