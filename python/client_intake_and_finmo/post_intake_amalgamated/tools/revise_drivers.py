"""revise_drivers — partial-patch variant of ``set_drivers``.

Used by VIABILITY V1 (cost-ratio tuning) — the most common cascade step.
The patch shape mirrors the ``anchors`` argument of ``set_drivers``: keys
are lever_id strings (e.g. ``"expenses::Cost of Goods Sold"``), values are
either a per-anchor dict (``{"q1": v, "q11": v, "q20": v}``) for P&L
levers or a scalar for working-capital levers. The patch overlays whatever
subset of these the proposer wants to change; unspecified anchors are
preserved from the current commitment.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, Optional

from client_intake_and_finmo.post_intake_amalgamated.tools._patch import (
  deep_merge_patch,
)


def revise_drivers(
  *,
  conn=None,
  draft_id: Optional[str] = None,
  planning_run_id: Optional[str] = None,
  current_anchors: Optional[Dict[str, Any]] = None,
  patch: Optional[Dict[str, Any]] = None,
  operating_context: Optional[Dict[str, Any]] = None,
  # Test seams.
  _set_drivers: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
  if not isinstance(current_anchors, dict) or not current_anchors:
    return {
      "accepted": False,
      "section": "drivers",
      "anchors": None,
      "commit_summary": None,
      "violations": [{
        "code": "no_current_driver_anchors",
        "message": (
          "revise_drivers requires currently-committed anchors to patch. "
          "Call set_drivers first."
        ),
      }],
      "bands_echoed": {},
      "decision_source": "amalgamated_session_pending",
      "patch_applied": [],
    }
  if not isinstance(patch, dict) or not patch:
    return {
      "accepted": False,
      "section": "drivers",
      "anchors": None,
      "commit_summary": None,
      "violations": [{
        "code": "drivers_patch_required",
        "message": "patch dict missing or empty",
      }],
      "bands_echoed": {},
      "decision_source": "amalgamated_gpt_supplied",
      "patch_applied": [],
    }

  merged, applied = deep_merge_patch(current_anchors, patch)

  setter = _set_drivers
  if setter is None:
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_drivers import (  # type: ignore
      set_drivers,
    )
    setter = set_drivers

  envelope = setter(
    conn=conn,
    draft_id=draft_id,
    planning_run_id=planning_run_id,
    anchors=copy.deepcopy(merged),
    operating_context=operating_context,
  )
  envelope = dict(envelope) if isinstance(envelope, dict) else {}
  envelope["patch_applied"] = applied
  envelope.setdefault("section", "drivers")
  return envelope


__all__ = ["revise_drivers"]
