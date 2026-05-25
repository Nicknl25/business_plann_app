"""P3.33 Phase 3 step 9 — post-intake run diagnostics.

The ``post_intake_run_diagnostics`` table stores a structured event
stream for every post-intake run, covering every phase from cohort-
bands population through workbook acceptance. The Phase 4 verification
scenarios will read these rows to know exactly what happened at each
juncture.

Module layout:

  phase_codes.py            — PhaseCode + EventCode + Status enums.
  run_diagnostics_table.py  — ``post_intake_run_diagnostics`` DDL,
                              ``ensure_run_diagnostics_table`` helper,
                              ``emit_diagnostic`` writer, fetch helpers.

Step 9a ships the table + writer + enums. Steps 9b and 9c instrument
the actual pipeline phases to call ``emit_diagnostic`` at every state
transition.
"""

from __future__ import annotations

from client_intake_and_finmo.post_intake_diagnostics.phase_codes import (  # noqa: F401
  EVENT_CODES_BY_PHASE,
  EventCode,
  PhaseCode,
  Status,
  event_code_belongs_to_phase,
)
from client_intake_and_finmo.post_intake_diagnostics.run_diagnostics_table import (  # noqa: F401  # noqa: E501
  RUN_DIAGNOSTICS_TABLE_NAME,
  emit_diagnostic,
  ensure_run_diagnostics_table,
  fetch_diagnostics,
)
