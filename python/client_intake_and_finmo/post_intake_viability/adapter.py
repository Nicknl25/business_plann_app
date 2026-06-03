"""Pipeline adapter for the viability standard (Fix #1 spec §9 wiring).

Bridges persisted run state (draft row + finmo_json + planning_run_json) to
evaluate_viability(). Extracts the inputs the standard needs:
  - business_start_date  -> business age -> stage (§4.1)
  - business_naics_6 + target_annual_revenue -> cohort bands (§5)
  - planning_mode posture -> explicit_distress_context (§4.3/§8): the RETAINED
    posture role of planning_mode (its profitability-FLOOR role is superseded
    by this standard — see SURFACED decisions in the module docstring below).

Best-effort + total: never raises (acceptance must not break). Missing naics
only drops the cohort bands; the gates (which own viability) still produce a
verdict. Missing age defaults to startup with a note (handled in standard.py).

SURFACED (not guessed — Fix #1 build §9):
  1. FLOW-THROUGH BLOCKER. The live system-run currently hard-fails Sunny at
     the payroll/revenue feasibility ASSERT (post_intake_headcount/schedule.py
     assert_payroll_revenue_feasibility, fired at
     quarter_grid_applied_after_feasibility_repair) BEFORE acceptance, so this
     advisory verdict is not reached on that path. Relaxing that assert for a
     ramping startup is the fix_1_early_quarter_viability_scope.md decision
     (grace window / convergence / founder-draw carve-out) — a separate,
     payroll-path change, deliberately NOT made here.
  2. PROFITABILITY-FLOOR SUPERSEDE. This standard supersedes planning_mode's
     profitability-FLOOR VIABILITY-JUDGMENT role. The same floor
     (post_intake_mapping.py:4805-4863, applied validator.py:323-345,988-994)
     also SHAPES the target-seeking solver, which is the executor/cascade
     machinery explicitly out of scope for this build. Removing it there would
     change solver behavior, so it is retained for solver-shaping until the
     executor build retires it. Wiring here is therefore ADVISORY (non-gating):
     it attaches the verdict, it does not yet replace the floor's gate role.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional

from .standard import evaluate_viability

_DISTRESS_MODES = {"turnaround"}
_DISTRESS_REASON_TOKENS = ("distress", "rescue", "insolven", "survival", "turnaround")


def _parse_start_date(value: Any) -> Optional[date]:
  raw = str(value or "").strip()
  if not raw:
    return None
  for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
    try:
      return datetime.strptime(raw, fmt).date()
    except Exception:
      continue
  return None


def _dig(d: Any, *keys: str) -> Any:
  """Return the first present, non-empty value among keys in dict d."""
  if not isinstance(d, dict):
    return None
  for k in keys:
    v = d.get(k)
    if v not in (None, ""):
      return v
  return None


def _extract_naics(draft: Dict[str, Any], model_input: Dict[str, Any], planning_run: Dict[str, Any]) -> Optional[str]:
  for src in (planning_run, model_input, draft):
    v = _dig(src, "business_naics_6", "business_naics", "naics_6", "naics_code")
    if v:
      s = "".join(ch for ch in str(v) if ch.isdigit())
      if s:
        return s[:6]
  # operating_model_json nested under model_input or draft
  for src in (model_input, draft):
    om = src.get("operating_model_json") if isinstance(src, dict) else None
    v = _dig(om, "business_naics_6", "business_naics")
    if v:
      s = "".join(ch for ch in str(v) if ch.isdigit())
      if s:
        return s[:6]
  return None


def _extract_target_revenue(finmo_json: Dict[str, Any], model_input: Dict[str, Any]) -> Optional[float]:
  # Year-1 revenue (sum of live quarters 1-4) is a reasonable annual-scale proxy
  # for cohort cap-category selection. Best-effort.
  rows = (finmo_json or {}).get("quarter_rows") or []
  y1 = 0.0
  found = False
  for r in rows:
    if not isinstance(r, dict):
      continue
    try:
      qi = int(r.get("quarter_index") or 0)
    except Exception:
      continue
    if 1 <= qi <= 4 and r.get("revenue") is not None:
      try:
        y1 += float(r.get("revenue"))
        found = True
      except Exception:
        pass
  return y1 if found else None


def _is_distress(planning_run: Dict[str, Any]) -> bool:
  if not isinstance(planning_run, dict):
    return False
  if bool(planning_run.get("explicit_distress_context")):
    return True
  mode = str(planning_run.get("planning_mode") or "").strip().lower()
  if mode in _DISTRESS_MODES:
    return True
  reason = str(planning_run.get("planning_mode_reason") or "").strip().lower()
  return any(tok in reason for tok in _DISTRESS_REASON_TOKENS)


def evaluate_run_viability(
  *,
  finmo_json: Optional[Dict[str, Any]],
  draft: Optional[Dict[str, Any]] = None,
  model_input_json: Optional[Dict[str, Any]] = None,
  planning_run_json: Optional[Dict[str, Any]] = None,
  as_of: Optional[date] = None,
) -> Dict[str, Any]:
  """Compute the viability verdict from persisted run state. Never raises."""
  try:
    draft = draft or {}
    model_input = model_input_json or {}
    planning_run = planning_run_json or {}
    start_date = _parse_start_date(_dig(draft, "business_start_date", "start_date"))
    naics = _extract_naics(draft, model_input, planning_run)
    target_rev = _extract_target_revenue(finmo_json or {}, model_input)
    distress = _is_distress(planning_run)
    return evaluate_viability(
      finmo_json,
      business_start_date=start_date,
      as_of=as_of,
      business_profile={"naics_6": naics, "target_annual_revenue": target_rev},
      explicit_distress_context=distress,
    )
  except Exception as exc:  # advisory — must never break the caller
    return {
      "verdict": "error",
      "viable": None,
      "error": f"{type(exc).__name__}: {exc}",
    }
