"""FAST P&L EVALUATOR — the restructure search's inner loop.

Evaluates a candidate business configuration (a full model_input) in
milliseconds instead of a full ~25-minute pipeline run, so the
restructure solver can search the ENTIRE P&L configuration space.

FIDELITY BY CONSTRUCTION — this module reimplements NOTHING:
  - The quarterly P&L is computed by the pipeline's OWN deterministic
    builder (``build_python_finmo_json`` → ``calculate_finmo_model``),
    the same code that produces finmo_json in a real run.
  - The viability scoring calls the acceptance gate's OWN check
    functions (net-income trajectory, cash-never-negative) and the
    realism validator's OWN universal viability-timeline rows.

THE EVALUATOR ONLY SEARCHES; IT NEVER DECIDES. The winning candidate
always runs through the REAL pipeline and the REAL acceptance gate for
the actual verdict. A fidelity gap here can waste a search round; it
cannot produce a fake-viable plan.

Cash semantics: the fast build is PRE-FUNDING (the real cash pass
funds loss windows from owner capital / retained earnings / debt).
Cash-dependent checks are therefore scored as ADVISORY here — the
search optimizes P&L substance, the real pipeline settles funding.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple


VIABILITY_TIMELINE_METRICS: Tuple[str, ...] = (
  "ebitda_positive_by_q11",
  "ebitda_recovery_trend_q5_q11",
  "loss_window_funded_through_q5",
  "ebitda_margin_q20_holds_or_improves_vs_q11",
  "gross_margin_supports_ebitda_recovery",
  "fixed_cost_burden_reduced_or_scaled_by_q11",
)

# Cash-position checks are pre-funding in the fast build (see module
# docstring) — advisory in the search score, settled by the real run.
_ADVISORY_METRICS: Tuple[str, ...] = (
  "loss_window_funded_through_q5",
)


def build_fast_finmo(model_input_json: Dict[str, Any]) -> Dict[str, Any]:
  """The pipeline's own deterministic model_input -> finmo build.

  Wrapped in a synthetic sequence-controller scope (the sanctioned
  pattern for orchestration-level callers — see
  post_intake_sequence_step_scope): the payroll-capacity policy apply
  inside the build gates itself against ad-hoc callers, and the
  restructure search is a legitimate orchestration-level caller."""
  from client_intake_and_finmo.finmo_bridge import (  # type: ignore
    build_python_finmo_json,
  )
  from client_intake_and_finmo.post_intake_sequence import (  # type: ignore
    post_intake_sequence_step_scope,
  )
  with post_intake_sequence_step_scope(
    step_key="restructure_fast_evaluation",
    phase="post_intake_target_seeking",
    executor_function="restructure_fast_evaluation",
  ):
    return build_python_finmo_json(
      model_input_json=copy.deepcopy(model_input_json),
    )


def _quarter_rows_by_index(finmo_json: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
  rows: Dict[int, Dict[str, Any]] = {}
  for row in (finmo_json or {}).get("quarter_rows") or []:
    if not isinstance(row, dict):
      continue
    try:
      rows[int(float(row.get("quarter_index")))] = row
    except (TypeError, ValueError):
      continue
  return rows


def _timeline_check_rows() -> List[Any]:
  from client_intake_and_finmo.post_intake_realism.lookup import (  # type: ignore
    post_intake_finalize_realism_check_rows,
  )
  return [
    row for row in post_intake_finalize_realism_check_rows()
    if str(getattr(row, "metric_key", None) or (row.get("metric_key") if isinstance(row, dict) else "")) in VIABILITY_TIMELINE_METRICS
  ]


def score_viability(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  business_naics_6: Optional[str] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  planning_mode: Optional[str] = None,
  solver_input_targets_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Score the P&L-substance viability checks on a finmo, using the
  gate's and validator's own logic. Returns::

    {
      "viable_pnl": bool,          # all binding checks pass
      "checks": {name: {"passed": bool, "advisory": bool, "detail": {}}},
      "failed_binding": [names],
      "landed": {q1/q5/q11/q20 margins},
    }
  """
  from client_intake_and_finmo.post_intake_acceptance.gate import (  # type: ignore
    _check_cash_never_negative,
    _check_net_income_trajectory_viable,
  )
  from client_intake_and_finmo.post_intake_realism.validator import (  # type: ignore
    RealismBandViolation,
    validate_industry_realism_bands,
  )

  checks: Dict[str, Any] = {}

  ni_passed, ni_detail = _check_net_income_trajectory_viable(finmo_json)
  checks["net_income_trajectory_viable"] = {
    "passed": bool(ni_passed), "advisory": False, "detail": ni_detail,
  }

  cash_passed, cash_detail = _check_cash_never_negative(finmo_json)
  checks["cash_never_negative_prefunding"] = {
    "passed": bool(cash_passed), "advisory": True, "detail": cash_detail,
  }

  # The 6 universal viability-timeline metrics, one validator call per
  # row (the validator raises on the FIRST hard fail, so a single call
  # would hide the rest of the picture).
  for row in _timeline_check_rows():
    metric_key = str(getattr(row, "metric_key", None) or (row.get("metric_key") if isinstance(row, dict) else ""))
    advisory = metric_key in _ADVISORY_METRICS
    try:
      payload = validate_industry_realism_bands(
        model_input_json=model_input_json,
        finmo_json=finmo_json,
        business_naics_6=business_naics_6,
        ops_json=ops_json,
        financials_json=financials_json,
        rows_override=[row],
        solver_input_targets_payload=solver_input_targets_payload,
        planning_mode=planning_mode,
      )
      statuses = [
        str(r.get("status") or "")
        for r in (payload.get("results") or [])
        if isinstance(r, dict)
      ]
      failed = any("fail" in s.lower() for s in statuses)
      checks[metric_key] = {
        "passed": not failed, "advisory": advisory,
        "detail": {"statuses": statuses},
      }
    except RealismBandViolation as exc:  # hard fail — the honest signal
      checks[metric_key] = {
        "passed": False, "advisory": advisory,
        "detail": {"violation": str(exc)[:300]},
      }
    except Exception as exc:  # noqa: BLE001 — score must not crash the search
      checks[metric_key] = {
        "passed": False, "advisory": advisory,
        "detail": {"error": f"{type(exc).__name__}: {str(exc)[:200]}"},
      }

  failed_binding = [
    name for name, c in checks.items()
    if not c["passed"] and not c["advisory"]
  ]

  rows = _quarter_rows_by_index(finmo_json)

  def _landed(qi: int) -> Dict[str, Any]:
    r = rows.get(qi) or {}
    try:
      rev = float(r.get("revenue") or 0.0)
    except (TypeError, ValueError):
      rev = 0.0
    if rev <= 0:
      return {"revenue": 0}
    def _m(key: str) -> float:
      try:
        return round(float(r.get(key) or 0.0) / rev, 4)
      except (TypeError, ValueError):
        return 0.0
    return {
      "revenue": round(rev),
      "ebitda_margin": _m("ebitda"),
      "net_income_margin": _m("net_income"),
      "payroll_pct": _m("payroll"),
      "rent_pct": _m("lease_rent"),
      "cogs_pct": _m("cogs"),
    }

  return {
    "viable_pnl": not failed_binding,
    "checks": checks,
    "failed_binding": failed_binding,
    "landed": {"q1": _landed(1), "q5": _landed(5), "q11": _landed(11), "q20": _landed(20)},
  }


def evaluate_candidate(
  *,
  model_input_json: Dict[str, Any],
  business_naics_6: Optional[str] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  planning_mode: Optional[str] = None,
  solver_input_targets_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Full fast evaluation: build the P&L with the pipeline's own
  builder, score it with the gate's own checks. Returns the score dict
  plus ``finmo_json`` (for callers that inspect the trajectory)."""
  finmo_json = build_fast_finmo(model_input_json)
  score = score_viability(
    model_input_json=model_input_json,
    finmo_json=finmo_json,
    business_naics_6=business_naics_6,
    ops_json=ops_json,
    financials_json=financials_json,
    planning_mode=planning_mode,
    solver_input_targets_payload=solver_input_targets_payload,
  )
  score["finmo_json"] = finmo_json
  return score


def compare_finmo_rows(
  fast_finmo: Dict[str, Any],
  real_finmo: Dict[str, Any],
  *,
  fields: Tuple[str, ...] = ("revenue", "ebitda", "net_income"),
) -> Dict[str, Any]:
  """Fidelity comparison: per-field max abs and max relative diff of the
  fast build vs the real pipeline's stored finmo across live quarters."""
  fast_rows = _quarter_rows_by_index(fast_finmo)
  real_rows = _quarter_rows_by_index(real_finmo)
  out: Dict[str, Any] = {}
  for field in fields:
    max_abs = 0.0
    max_rel = 0.0
    worst_q = None
    for q in range(1, 21):
      try:
        fv = float((fast_rows.get(q) or {}).get(field) or 0.0)
        rv = float((real_rows.get(q) or {}).get(field) or 0.0)
      except (TypeError, ValueError):
        continue
      diff = abs(fv - rv)
      rel = diff / max(1.0, abs(rv))
      if diff > max_abs:
        max_abs = diff
        worst_q = q
      max_rel = max(max_rel, rel)
    out[field] = {
      "max_abs_diff": round(max_abs, 2),
      "max_rel_diff": round(max_rel, 6),
      "worst_quarter": worst_q,
    }
  return out


__all__ = [
  "build_fast_finmo",
  "score_viability",
  "evaluate_candidate",
  "compare_finmo_rows",
  "VIABILITY_TIMELINE_METRICS",
]
