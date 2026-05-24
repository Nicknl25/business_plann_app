"""P3.33 Phase 3 step 4 — restructure protocol subpackage.

Foundation for the restructure cascade specified in
``docs/architecture/p3_33_restructure_protocol_spec.md``.

Step 4 ships:

  - reason_codes.py            : ReasonCode + AppliedBy + StepType enums
                                 (closed sets; spec §10.2 / §10.3 / §6).
  - restructuring_log_table.py : ``post_intake_restructuring_log`` DDL,
                                 ensure-table helper, ``log_restructure``
                                 row writer (spec §10.1 / §10.4).

Step 5 will add ``cascades.py`` (the §5 cascade tables as data),
``restructure_proposer.py`` (Python proposal builders), ``floor.py``
(the unattended cascade walker + §9.2 floor primitives), and
``session_driver.py`` (the §12 state machine).
"""

from __future__ import annotations

from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (  # noqa: F401
  ReasonCode,
  AppliedBy,
  StepType,
  REASON_CODES_BY_MODE,
  reason_code_belongs_to_mode,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.restructuring_log_table import (  # noqa: F401
  RESTRUCTURING_LOG_TABLE_NAME,
  RestructureLogEntry,
  ensure_restructuring_log_table,
  log_restructure,
  fetch_restructuring_log,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: F401  # noqa: E501
  ProposalResponse,
  confirm_proposal,
  veto_proposal,
  choose_option,
  other_proposal,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (  # noqa: F401
  CascadeLever,
  CascadeTier,
  CASCADES,
  MODE_PRIORITY,
  BOUND_RELAXATION_STEP_FRACTION,
  BOUND_RELAXATION_MAX_ATTEMPTS,
  BOUND_RELAXATION_CUMULATIVE_CAP,
  PROGRESS_THRESHOLD_FRACTION,
  MAX_CONSECUTIVE_NO_PROGRESS,
  DEFAULT_TOOL_CALL_BUDGET,
  BUDGET_AWARE_THRESHOLD,
  BUDGET_FLOOR_THRESHOLD,
  get_cascade,
  get_tier,
  next_tier,
  coherence_anchor_order,
)
