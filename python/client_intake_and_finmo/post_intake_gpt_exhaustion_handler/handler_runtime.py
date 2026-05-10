"""Phase 9 P3.5 — Handler runtime.

Phase 1 scaffolding: this module exposes ``execute_handler`` with the
correct signature and provenance plumbing. Phase 2 fills in the GPT
Call 1 / Call 2 path; Phase 3 fills in the iteration loop and
deterministic snap-in; Phase 4 wires the realism mute mechanism.

Keeping the runtime separate from ``handler.py`` lets Phase 1's commit
land cleanly without forward-referencing later phases.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (
  HandlerResult,
  HandlerStatus,
)


logger = logging.getLogger(__name__)


def execute_handler(
  *,
  restoration_result: Any,
  model_input: Dict[str, Any],
  operating_model: Dict[str, Any],
  build_finmo: Callable[[Dict[str, Any]], Dict[str, Any]],
  intake_context: Dict[str, Any],
  finmo_json: Optional[Dict[str, Any]] = None,
) -> HandlerResult:
  """Phase 1 scaffolding stub. Returns FAILED with a provenance trail
  showing the wiring is intact. Phase 2 replaces the body with the real
  Call 1 / Call 2 / iterate / snap-in pipeline.
  """
  exhaustion_diagnostic: Dict[str, Any] = {}
  try:
    if hasattr(restoration_result, "to_dict"):
      exhaustion_diagnostic = restoration_result.to_dict()
    elif isinstance(restoration_result, dict):
      exhaustion_diagnostic = dict(restoration_result)
  except Exception:
    exhaustion_diagnostic = {"note": "restoration_result_not_serializable"}

  provenance: Dict[str, Any] = {
    "phase": "phase_1_scaffolding_only",
    "wired_at_call_site": True,
    "exhaustion_diagnostic_received": bool(exhaustion_diagnostic),
    "restoration_status": exhaustion_diagnostic.get("status"),
    "restoration_q11_ebitda_margin": exhaustion_diagnostic.get("q11_ebitda_margin"),
    "operating_model_present": isinstance(operating_model, dict) and bool(operating_model),
    "model_input_present": isinstance(model_input, dict) and bool(model_input),
    "intake_context_keys": sorted(list((intake_context or {}).keys())),
  }

  return HandlerResult(
    status=HandlerStatus.FAILED,
    gpt_calls_made=0,
    iterations_used=0,
    q11_ebitda_target=None,
    q11_ebitda_actual=exhaustion_diagnostic.get("q11_ebitda_margin"),
    provenance=provenance,
    realism_flags_to_mute=[],
    reason="phase_1_scaffolding_only_handler_not_yet_implemented",
  )
