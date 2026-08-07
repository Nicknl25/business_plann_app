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
import math
from typing import Any, Callable, Dict, List, Optional, Tuple


def _is_finite_number(v: Any) -> bool:
  return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


# The 4 P&L driver lever_ids the cohort bands populator covers
# (mirror of cohort_bands_table._SECTION_LEVERS["drivers"]).
#
# P3.33 Phase 3 pre-step-8 — WC scalar levers (AR/AP/Inventory days)
# moved out of this tool. FINMO reads from the balance-sheet rows in
# model_input; both this tool and set_capex_rd_balance_seed used to
# write those rows for WC days, creating two sources of truth.
# balance_sheet section now owns WC days exclusively, authored via
# set_capex_rd_balance_seed and revised via revise_capex_rd_balance_seed.
_DRIVER_LEVER_IDS: Tuple[str, ...] = (
  "expenses::Cost of Goods Sold",
  "expenses::Research & Development",
  "expenses::General & Administrative",
  "expenses::Marketing",
)

_ANCHOR_QUARTERS: Tuple[str, ...] = ("q1", "q11", "q20")


def _check_envelope_violations(anchors: Dict[str, Any]) -> List[Dict[str, Any]]:
  """B6 — economic envelope check for driver anchors. Each P&L lever
  ratio must be in [0, 1] (a 100% ratio is at the edge but allowed;
  negative or > 1 ratios are structurally impossible)."""
  violations: List[Dict[str, Any]] = []
  if not isinstance(anchors, dict):
    return violations
  for lever_id, levered in anchors.items():
    if lever_id not in _DRIVER_LEVER_IDS:
      continue
    if not isinstance(levered, dict):
      continue
    for anchor in _ANCHOR_QUARTERS:
      v = levered.get(anchor)
      if v is None:
        continue
      if not _is_finite_number(v):
        violations.append({
          "code": "envelope_violation_driver_anchor_not_finite",
          "lever_id": lever_id, "anchor": anchor, "actual": v,
        })
        continue
      vf = float(v)
      if vf < 0.0 or vf > 1.0:
        violations.append({
          "code": "envelope_violation_driver_anchor_out_of_unit_interval",
          "lever_id": lever_id, "anchor": anchor, "actual": vf,
        })
  return violations


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


# lever_id -> fitted-envelope metric key (the manager's wall vocabulary).
_LEVER_ID_TO_METRIC: Dict[str, str] = {
  "expenses::Cost of Goods Sold": "cogs_percent_of_revenue",
  "expenses::Research & Development": "r_and_d_percent_of_revenue",
  "expenses::General & Administrative": "sga_percent_of_revenue",
  "expenses::Marketing": "marketing_percent_of_revenue",
}

_ANCHOR_LABEL_TO_QUARTER: Dict[str, int] = {"q1": 1, "q11": 11, "q20": 20}


def _manager_anchor_walls(operating_context: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
  """The manager's fitted per-quarter [min, max] walls keyed by lever_id
  — the OWNER's envelope for the demotion test below. Empty when no
  managerial forecast exists (raw-cohort fallback keeps the veto)."""
  walls: Dict[str, Dict[str, Dict[str, Any]]] = {}
  try:
    mi = (operating_context or {}).get("model_input_template") if isinstance(operating_context, dict) else None
    few = ((mi or {}).get("solver_input") or {}).get("fitted_envelope_per_q") if isinstance(mi, dict) else None
    if not isinstance(few, dict):
      return walls
    for lever_id, metric in _LEVER_ID_TO_METRIC.items():
      band = few.get(metric)
      if isinstance(band, dict) and (band.get("min") or band.get("max")):
        walls[lever_id] = band
  except Exception:
    return {}
  return walls


def _check_anchor_band_violations(
  anchors: Dict[str, Any],
  bands: Dict[str, Any],
  manager_walls: Optional[Dict[str, Dict[str, Dict[str, Any]]]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
  """For each (lever_id, anchor_quarter) in anchors, check the supplied
  value against the lever's robust band. Returns (violations,
  advisories).

  OWNERSHIP (CW-017 informant-authority ledger, ruled 2026-08-07): the
  cohort band is an informant. When the MANAGER'S fitted per-quarter
  envelope covers the lever and the anchor sits inside the manager's
  own [min, max] wall at that quarter, a cohort-band breach DEMOTES to
  an ADVISORY — the informant cannot veto the owner (the same
  demotion floors got in Wave 2 and ceilings got for the stage ramp).
  The veto is RETAINED when no managerial wall covers the lever
  (raw-cohort fallback) and when the anchor exceeds the manager's own
  wall."""
  violations: List[Dict[str, Any]] = []
  advisories: List[Dict[str, Any]] = []
  if not isinstance(anchors, dict) or not isinstance(bands, dict):
    return violations, advisories
  walls = manager_walls or {}
  for lever_id, levered in anchors.items():
    if lever_id not in _DRIVER_LEVER_IDS:
      continue
    band = bands.get(lever_id) if isinstance(bands, dict) else None
    bmin = bmax = None
    if isinstance(band, dict):
      bmin = band.get("robust_min") if band.get("robust_min") is not None else band.get("benchmark_min")
      bmax = band.get("robust_max") if band.get("robust_max") is not None else band.get("benchmark_max")
    # P&L lever anchor shape: {"q1": <v>, "q11": <v>, "q20": <v>}.
    # Scalar shape used to be accepted for balance-sheet WC levers
    # (AR/AP/Inventory days), but those moved to set_capex_rd_balance_seed
    # in P3.33 Phase 3 pre-step-8.
    if isinstance(levered, dict):
      candidates = [
        (q, float(levered[q])) for q in _ANCHOR_QUARTERS
        if q in levered and isinstance(levered.get(q), (int, float))
      ]
    else:
      continue

    def _wall_covers(anchor_label: str, value: float) -> Optional[Dict[str, float]]:
      wall = walls.get(lever_id)
      if not isinstance(wall, dict):
        return None
      q = _ANCHOR_LABEL_TO_QUARTER.get(anchor_label)
      if q is None:
        return None
      lo = ((wall.get("min") or {}) if isinstance(wall.get("min"), dict) else {}).get(str(q))
      hi = ((wall.get("max") or {}) if isinstance(wall.get("max"), dict) else {}).get(str(q))
      try:
        lo_f = float(lo) if lo is not None else None
        hi_f = float(hi) if hi is not None else None
      except (TypeError, ValueError):
        return None
      if lo_f is None and hi_f is None:
        return None
      if (lo_f is None or value >= lo_f - 1e-9) and (hi_f is None or value <= hi_f + 1e-9):
        return {"manager_wall_min": lo_f, "manager_wall_max": hi_f}
      return None

    for anchor_label, value in candidates:
      if isinstance(bmin, (int, float)) and value < float(bmin):
        entry = {
          "code": "driver_anchor_below_band_min",
          "lever_id": lever_id, "anchor": anchor_label,
          "actual": value, "band_min": float(bmin),
          "delta": float(bmin) - value, "units": "fraction",
        }
        covered = _wall_covers(anchor_label, value)
        if covered is not None:
          entry["code"] = "driver_anchor_below_band_min_advisory"
          entry.update({k: v for k, v in covered.items() if v is not None})
          advisories.append(entry)
        else:
          violations.append(entry)
      if isinstance(bmax, (int, float)) and value > float(bmax):
        entry = {
          "code": "driver_anchor_above_band_max",
          "lever_id": lever_id, "anchor": anchor_label,
          "actual": value, "band_max": float(bmax),
          "delta": value - float(bmax), "units": "fraction",
        }
        covered = _wall_covers(anchor_label, value)
        if covered is not None:
          entry["code"] = "driver_anchor_above_band_max_advisory"
          entry.update({k: v for k, v in covered.items() if v is not None})
          advisories.append(entry)
        else:
          violations.append(entry)
  return violations, advisories


def set_drivers(
  *,
  conn=None,
  draft_id: Optional[str] = None,
  planning_run_id: Optional[str] = None,
  anchors: Optional[Dict[str, Any]] = None,
  # Inputs required to actually commit anchors to model_input (the
  # writer needs the live operating_context):
  operating_context: Optional[Dict[str, Any]] = None,
  # When False, validate + accept the anchors but DO NOT invoke the all-P&L
  # writer. Used by the amalgamated cascade (revise_drivers), which commits
  # ONE driver lever per tier — the writer (_write_gpt_authored_per_quarter_
  # values) expects a full P&L driver set at once and hard-fails on partial
  # commits under CONVERGENCE_TEST_MODE. The live model_input write for the
  # cascade is handled per-lever by session_factory._propagate_committed_
  # section_to_model_input instead.
  commit_to_model_input: bool = True,
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

  # 0) Economic envelope (B6) — structural sanity check.
  envelope_violations = _check_envelope_violations(anchors)
  # Band check — cheap, no mutation. Manager-wall-covered breaches come
  # back as advisories (recorded, never rejecting).
  band_violations, band_advisories = _check_anchor_band_violations(
    anchors, bands_echoed,
    manager_walls=_manager_anchor_walls(operating_context),
  )
  if band_advisories:
    try:
      from client_intake_and_finmo.post_intake_handler_traces import (  # type: ignore
        record_runtime_status,
      )
      record_runtime_status(
        handler="driver_anchor_band_advisory",
        status={"draft_id": _string(draft_id), "advisories": band_advisories},
      )
    except Exception:
      pass
  # REVENUE AUTHORITY check: when the revenue trajectory is
  # deterministically authored (market-grounded growth judgment), the
  # executive may not re-author revenue driver anchors here -- growth
  # belongs to the judgment and to the ceilinged viability search, not to
  # unbounded anchor authoring (Anderson: judged 8->4%/yr rewritten to
  # ~34%/yr through revenue::Utilization anchors). Cost and working-
  # capital anchors remain fully authorable.
  revenue_authority_violations: List[Dict[str, Any]] = []
  _oc_mi = (operating_context or {}).get("model_input_template") if isinstance(operating_context, dict) else None
  if bool(((_oc_mi or {}).get("solver_input") or {}).get("revenue_authored")):
    for _lever_id in (anchors or {}):
      if str(_lever_id or "").strip().startswith("revenue::"):
        revenue_authority_violations.append({
          "code": "revenue_authored_lever_not_authorable",
          "lever_id": str(_lever_id),
          "message": (
            "revenue is deterministically authored from the market-grounded "
            "growth judgment; its adaptation happens in the ceilinged "
            "viability search. Author cost / working-capital anchors instead."
          ),
        })
  combined = envelope_violations + band_violations + revenue_authority_violations
  if combined:
    return {
      "accepted": False,
      "section": "drivers",
      "anchors": None,
      "commit_summary": None,
      "violations": combined,
      "bands_echoed": bands_echoed,
      "decision_source": "amalgamated_gpt_supplied",
    }

  # Cascade incremental path: envelope + band validation passed; accept the
  # anchors WITHOUT the all-P&L writer (which hard-fails on a single-lever
  # commit). The session propagates this lever into the live model_input.
  if not commit_to_model_input:
    return {
      "accepted": True,
      "section": "drivers",
      "anchors": copy.deepcopy(anchors),
      "commit_summary": {
        "committed_to_model_input": False,
        "note": "validated; live model_input write handled by session propagation",
      },
      "violations": [],
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
