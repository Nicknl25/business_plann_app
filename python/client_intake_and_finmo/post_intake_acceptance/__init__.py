"""Phase 8 acceptance gate.

Single source of truth for whether a planning run "passed." The gate
queries only new-architecture fields (cascade_landed_tier, realism gate
provenance, solver_target_assertion, finmo workbook integrity) and has
zero dependency on the legacy post_intake_issues machinery. Exit code 0
from the orchestrator is not "passed" — only the verdict from this gate
is.

Public surface:

  verify_run_acceptance(conn, draft_id, planning_run_id) -> verdict dict
"""

from __future__ import annotations

from client_intake_and_finmo.post_intake_acceptance.gate import (  # type: ignore
  verify_run_acceptance,
)

__all__ = ["verify_run_acceptance"]
