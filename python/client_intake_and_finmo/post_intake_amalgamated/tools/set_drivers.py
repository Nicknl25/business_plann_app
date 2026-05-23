"""set_drivers — author the P&L + working-capital driver anchors.

Wraps the existing H2 anchor writer + anchor interpolation. On
acceptance the tool writes per-quarter values via
``_write_gpt_authored_per_quarter_values`` and returns the committed
anchors + the lever-margin echo against cohort bands. On rejection
it returns structured violations (per-anchor distance to the band
edge) so GPT (step 5) or the deterministic floor will repair and retry.

The H2 GPT iteration loop is gone (deleted in this same commit). The
amalgamated session (step 5) calls this tool directly with GPT-
supplied anchors. During the transition window between this commit
and step 5 the orchestrator's pre-amalgamation entry point
(``run_gpt_exhaustion_handler``) is a thin shim that returns
EXHAUSTED with a transitional diagnostic — driver authoring becomes a
real GPT activity only once the amalgamated session lands.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Optional, Tuple


# The 7 P&L + WC driver lever_ids the cohort bands populator covers
# (mirror of cohort_bands_table._SECTION_LEVERS["drivers"]).
_DRIVER_LEVER_IDS: Tuple[str, ...] = (
  "expenses::Cost of Goods Sold",
  "expenses::Research & Development",
  "expenses::General & Administrative",
  "expenses::Marketing",
  "balance_sheet::Accounts Receivable Days",
  "balance_sheet::Accounts Payable Days",
  "balance_sheet::Inventory Days",
)

_ANCHOR_QUARTERS: Tuple[str, ...] = ("q1", "q11", "q20")


def _string(value: Any) -> str:
  return str(value if value is not None else "").strip()


def _echo_bands_for_section(conn, *, draft_id: str, planning_run_id: str) -> Dict[str, Any]:
  if conn is None or not draft_id or not planning_run_id:
    return {}
  try:
    from client_intake_and_finmo.post_intake_solver.cohort_bands_table import (  # type: ignore
      get_bands,
    )
    payload = get_bands(conn, draft_id=draft_id, planning_run_id=planning_run_id, section="drivers")
    return payload.get("bands") or {}
  except Exception:
    return {}


def _check_anchor_band_violations(
  anchors: Dict[str, Any],
  bands: Dict[str, Any],
) -> List[Dict[str, Any]]:
  """For each (lever_id, anchor_quarter) in anchors, check the supplied
  value lies inside the lever's robust band. Returns one entry per
  out-of-band anchor with delta + units.
  """
  violations: List[Dict[str, Any]] = []
  if not isinstance(anchors, dict) or not isinstance(bands, dict):
    return violations
  for lever_id, levered in anchors.items():
    if lever_id not in _DRIVER_LEVER_IDS:
      continue
    band = bands.get(lever_id) if isinstance(bands, dict) else None
    bmin = bmax = None
    if isinstance(band, dict):
      bmin = band.get("robust_min") if band.get("robust_min") is not None else band.get("benchmark_min")
      bmax = band.get("robust_max") if band.get("robust_max") is not None else band.get("benchmark_max")
    # Two anchor shapes accepted:
    #   {"q1": <v>, "q11": <v>, "q20": <v>}  for P&L levers
    #   <scalar number>                        for balance-sheet WC levers
    if isinstance(levered, (int, float)):
      candidates = [("scalar", float(levered))]
    elif isinstance(levered, dict):
      candidates = [
        (q, float(levered[q])) for q in _ANCHOR_QUARTERS
        if q in levered and isinstance(levered.get(q), (int, float))
      ]
    else:
      continue
    for anchor_label, value in candidates:
      if isinstance(bmin, (int, float)) and value < float(bmin):
        violations.append({
          "code": "driver_anchor_below_band_min",
          "lever_id": lever_id, "anchor": anchor_label,
          "actual": value, "band_min": float(bmin),
          "delta": float(bmin) - value, "units": "fraction",
        })
      if isinstance(bmax, (int, float)) and value > float(bmax):
        violations.append({
          "code": "driver_anchor_above_band_max",
          "lever_id": lever_id, "anchor": anchor_label,
          "actual": value, "band_max": float(bmax),
          "delta": value - float(bmax), "units": "fraction",
        })
  return violations


def set_drivers(
  *,
  conn=None,
  draft_id: Optional[str] = None,
  planning_run_id: Optional[str] = None,
  anchors: Optional[Dict[str, Any]] = None,
  # Inputs required to actually commit anchors to model_input (the
  # writer needs the live operating_context):
  operating_context: Optional[Dict[str, Any]] = None,
  # Test seams.
  _writer: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
  """Author / validate / commit per-quarter driver anchors.

  Returns the standard authoring-tool envelope::

    {
      "accepted": bool,
      "section": "drivers",
      "anchors": <validated anchors>|None,
      "commit_summary": <writer result>|None,
      "violations": [ {...}, ... ],
      "bands_echoed": { lever_id: band_dict, ... },
      "decision_source": "amalgamated_gpt_supplied" | "amalgamated_session_pending",
    }

  Rejection does NOT mutate state. On acceptance the writer applies
  the anchors to operating_context['model_input_template']; the
  caller persists model_input and refreshes the mirror.
  """
  bands_echoed = _echo_bands_for_section(
    conn, draft_id=_string(draft_id), planning_run_id=_string(planning_run_id)
  )

  if not isinstance(anchors, dict) or not anchors:
    # Deterministic-floor / pre-amalgamated-session path. The K13 Fix 3
    # (apply_viability_floor) and Fix 4 (reconcile_revenue_to_stage_ramp)
    # functions in post_intake_gpt_exhaustion_handler.handler remain
    # the deterministic-floor authors during the transition; the
    # orchestrator's run_gpt_exhaustion_handler shim still routes
    # exhaustion through them. The amalgamated session (step 5) is the
    # only caller that supplies real anchors via this tool.
    return {
      "accepted": False,
      "section": "drivers",
      "anchors": None,
      "commit_summary": None,
      "violations": [{
        "code": "driver_anchors_required",
        "message": (
          "set_drivers requires GPT-supplied anchors. During the "
          "step 3c -> step 5 transition the orchestrator's H2 entry "
          "point returns EXHAUSTED and the K13 floor (Fix 3 / Fix 4 "
          "in post_intake_gpt_exhaustion_handler.handler) handles "
          "deterministic floor commits. Step 5 wires GPT-supplied "
          "anchors into this tool."
        ),
      }],
      "bands_echoed": bands_echoed,
      "decision_source": "amalgamated_session_pending",
    }

  # Band check first — cheap, no mutation.
  band_violations = _check_anchor_band_violations(anchors, bands_echoed)
  if band_violations:
    return {
      "accepted": False,
      "section": "drivers",
      "anchors": None,
      "commit_summary": None,
      "violations": band_violations,
      "bands_echoed": bands_echoed,
      "decision_source": "amalgamated_gpt_supplied",
    }

  # Operating context required to actually commit anchors to model_input.
  if not isinstance(operating_context, dict) or not operating_context:
    return {
      "accepted": False,
      "section": "drivers",
      "anchors": None,
      "commit_summary": None,
      "violations": [{
        "code": "operating_context_required",
        "message": (
          "set_drivers needs operating_context (model_input_template, "
          "build_finmo callable, stage_ramp_contract) to commit anchors "
          "to model_input via _write_gpt_authored_per_quarter_values."
        ),
      }],
      "bands_echoed": bands_echoed,
      "decision_source": "amalgamated_gpt_supplied",
    }

  writer = _writer
  if writer is None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (  # type: ignore
      _write_gpt_authored_per_quarter_values,
    )
    writer = _write_gpt_authored_per_quarter_values

  try:
    commit_summary = writer(copy.deepcopy(anchors), operating_context)
  except Exception as exc:
    return {
      "accepted": False,
      "section": "drivers",
      "anchors": None,
      "commit_summary": None,
      "violations": [{
        "code": "driver_anchor_commit_failed",
        "message": _string(exc)[:1200],
      }],
      "bands_echoed": bands_echoed,
      "decision_source": "amalgamated_gpt_supplied",
    }

  return {
    "accepted": True,
    "section": "drivers",
    "anchors": copy.deepcopy(anchors),
    "commit_summary": commit_summary if commit_summary is not None else {},
    "violations": [],
    "bands_echoed": bands_echoed,
    "decision_source": "amalgamated_gpt_supplied",
  }
