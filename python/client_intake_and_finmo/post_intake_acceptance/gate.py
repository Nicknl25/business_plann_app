"""Phase 8 — acceptance gate (`verify_run_acceptance`).

Runs after the orchestrator returns and before the API responds. Decides
whether a planning run actually passed using ONLY new-architecture fields:

  1. planning_runs.current_stage == "post_intake_finalize_validation_completed"
  2. planning_runs.cascade_landed_tier IS NOT NULL
  3. planning_runs.plan_confidence IS NOT NULL
  4. realism_memo_json carries per-metric provenance from the realism gate
  5. realism gate produced no hard_fail violations
  6. solver_target_assertion.checked == True
  7. solver_target_assertion has no hard_fail violations
  8. revenue is not flat across Q1-Q10 (stdev/mean >= 0.02 OR (Q10-Q1)/Q1 >= 0.05)
  9. for every quarter Q1-Q10, cash >= 0 OR interest > 0
 10. for every quarter Q1-Q10, current_assets > 0

The verdict is persisted to planning_runs.acceptance_verdict_json. The
API handler turns a failed verdict into an HTTP 500 with the verdict in
the response body so the caller can see exactly what failed.

This module has zero imports from post_intake_issues — by design.
"""

from __future__ import annotations

import copy
import datetime
import json
import math
import statistics
from typing import Any, Dict, List, Optional, Tuple


HORIZON_QUARTERS = 10
REVENUE_FLAT_STDEV_OVER_MEAN_THRESHOLD = 0.02
REVENUE_FLAT_Q10_OVER_Q1_DELTA_THRESHOLD = 0.05

FINALIZE_STAGE = "post_intake_finalize_validation_completed"


def _now_iso() -> str:
  return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  try:
    out = float(value)
  except Exception:
    return None
  if math.isnan(out) or math.isinf(out):
    return None
  return out


def _parse_json(value: Any) -> Dict[str, Any]:
  if isinstance(value, dict):
    return value
  if isinstance(value, (bytes, bytearray)):
    try:
      value = value.decode("utf-8")
    except Exception:
      return {}
  if isinstance(value, str):
    text = value.strip()
    if not text:
      return {}
    try:
      parsed = json.loads(text)
    except Exception:
      return {}
    return parsed if isinstance(parsed, dict) else {}
  return {}


def _planning_run_row(conn, *, planning_run_id: str, draft_id: str) -> Dict[str, Any]:
  """Read the planning_runs row by id (preferred) or latest by draft.

  Reads only — never writes. Returns {} if neither lookup finds a row.
  """
  cur = conn.cursor(dictionary=True)
  try:
    pr_id = str(planning_run_id or "").strip()
    if pr_id:
      cur.execute(
        "SELECT * FROM planning_runs WHERE planning_run_id = %s LIMIT 1",
        (pr_id,),
      )
      row = cur.fetchone()
      if isinstance(row, dict):
        return row
    d_id = str(draft_id or "").strip()
    if d_id:
      cur.execute(
        """
        SELECT * FROM planning_runs
        WHERE draft_id = %s
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (d_id,),
      )
      row = cur.fetchone()
      if isinstance(row, dict):
        return row
  finally:
    try:
      cur.close()
    except Exception:
      pass
  return {}


def _draft_row(conn, *, draft_id: str) -> Dict[str, Any]:
  cur = conn.cursor(dictionary=True)
  try:
    d_id = str(draft_id or "").strip()
    if not d_id:
      return {}
    cur.execute(
      "SELECT * FROM intake_consult_drafts WHERE draft_id = %s LIMIT 1",
      (d_id,),
    )
    row = cur.fetchone()
    return row if isinstance(row, dict) else {}
  finally:
    try:
      cur.close()
    except Exception:
      pass


def _quarter_rows_by_index(finmo_json: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
  rows = (finmo_json or {}).get("quarter_rows") or []
  out: Dict[int, Dict[str, Any]] = {}
  for row in rows:
    if not isinstance(row, dict):
      continue
    q = _safe_float(row.get("quarter_index"))
    if q is None:
      continue
    iq = int(round(q))
    if iq >= 1:
      out[iq] = row
  return out


def _quarter_field(
  quarter_rows: Dict[int, Dict[str, Any]], quarter_index: int, *names: str
) -> Optional[float]:
  row = quarter_rows.get(int(quarter_index)) or {}
  for name in names:
    val = _safe_float(row.get(name))
    if val is not None:
      return val
  return None


def _check_stage_reached_finalize(planning_run: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
  current_stage = str(planning_run.get("current_stage") or "").strip()
  passed = current_stage == FINALIZE_STAGE
  return passed, {
    "current_stage": current_stage or None,
    "expected_stage": FINALIZE_STAGE,
  }


def _check_cascade_tier_set(planning_run: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
  tier = planning_run.get("cascade_landed_tier")
  passed = tier is not None
  return passed, {"cascade_landed_tier": tier}


def _check_plan_confidence_set(planning_run: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
  conf = str(planning_run.get("plan_confidence") or "").strip() or None
  return (conf is not None), {"plan_confidence": conf}


def _check_realism_provenance(realism_memo: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
  """Realism gate is the new-architecture verdict source for ratios.
  Provenance means: at least one result row was produced and each row
  carries a band_source field naming where its band came from
  (phase_3_calibrated or naics_baseline). When the realism gate never
  ran, this list is empty or missing — the legacy machinery's None
  default would have papered over that; the gate refuses to.
  """
  if not isinstance(realism_memo, dict) or not realism_memo:
    return False, {"reason": "realism_memo_json_missing_or_empty"}
  candidate_lists: List[List[Any]] = []
  for path in (
    ("realism_gate", "line_level", "results"),
    ("realism_gate", "results"),
    ("line_level", "results"),
    ("results",),
  ):
    cursor: Any = realism_memo
    ok = True
    for key in path:
      if isinstance(cursor, dict) and key in cursor:
        cursor = cursor[key]
      else:
        ok = False
        break
    if ok and isinstance(cursor, list) and cursor:
      candidate_lists.append(cursor)
  if not candidate_lists:
    return False, {"reason": "no_realism_gate_results_found_in_memo"}
  results = candidate_lists[0]
  rows_with_provenance = 0
  band_sources_seen: List[str] = []
  for row in results:
    if not isinstance(row, dict):
      continue
    src = str(row.get("band_source") or "").strip()
    if src:
      rows_with_provenance += 1
      if src not in band_sources_seen:
        band_sources_seen.append(src)
  passed = rows_with_provenance > 0
  return passed, {
    "result_count": len(results),
    "rows_with_band_source_provenance": rows_with_provenance,
    "band_sources_seen": band_sources_seen,
  }


def _check_realism_no_hard_fail(realism_memo: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
  """A run should not pass acceptance with realism hard_fail violations
  outstanding. The cascade exists to resolve them; if any survive, the
  run did not actually adapt to a feasible plan.
  """
  hard_violations: List[Dict[str, Any]] = []
  for path in (
    ("realism_gate", "line_level", "results"),
    ("realism_gate", "results"),
    ("line_level", "results"),
    ("results",),
  ):
    cursor: Any = realism_memo
    ok = True
    for key in path:
      if isinstance(cursor, dict) and key in cursor:
        cursor = cursor[key]
      else:
        ok = False
        break
    if ok and isinstance(cursor, list) and cursor:
      for row in cursor:
        if not isinstance(row, dict):
          continue
        status = str(row.get("status") or "").strip().lower()
        gate_kind = str(row.get("gate_kind") or row.get("severity") or "").strip().lower()
        if status in ("hard_fail", "violation_hard_fail") or (
          status == "fail" and gate_kind == "hard_fail"
        ):
          hard_violations.append(
            {
              "metric_key": row.get("metric_key"),
              "quarter_index": row.get("quarter_index"),
              "actual_value": row.get("actual_value"),
              "effective_min": row.get("effective_min"),
              "effective_max": row.get("effective_max"),
              "band_source": row.get("band_source"),
            }
          )
      break
  passed = len(hard_violations) == 0
  return passed, {"hard_fail_violations": hard_violations[:10]}


def _solver_target_assertion(planning_run_json: Dict[str, Any]) -> Dict[str, Any]:
  """Locate solver_target_assertion in the persisted planning_run_json.

  finalize_post_intake.py returns the assertion under
  cash_strategy_second_pass_result.post_intake_finalize_validation; the
  convergence runner snapshots cash_strategy_second_pass_result onto the
  planning_run_json at run completion. We also accept a top-level key in
  case a future writer puts it there.
  """
  candidates = [
    planning_run_json.get("solver_target_assertion"),
    (planning_run_json.get("cash_strategy_second_pass_result") or {})
    .get("post_intake_finalize_validation", {})
    .get("solver_target_assertion")
    if isinstance(planning_run_json.get("cash_strategy_second_pass_result"), dict)
    else None,
    (planning_run_json.get("post_intake_finalize_validation") or {}).get(
      "solver_target_assertion"
    )
    if isinstance(planning_run_json.get("post_intake_finalize_validation"), dict)
    else None,
  ]
  for c in candidates:
    if isinstance(c, dict) and c:
      return c
  return {}


def _check_solver_target_checked(planning_run_json: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
  assertion = _solver_target_assertion(planning_run_json)
  checked = bool(assertion.get("checked"))
  return checked, {
    "solver_target_assertion_checked": checked,
    "solver_target_assertion_status": assertion.get("status"),
    "solver_target_assertion_reason": assertion.get("reason"),
    "solver_target_checked_metric_count": assertion.get("checked_metric_count"),
  }


def _check_solver_target_no_hard_violations(
  planning_run_json: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any]]:
  assertion = _solver_target_assertion(planning_run_json)
  raw_violations = assertion.get("violations") or []
  hard = [
    v
    for v in raw_violations
    if isinstance(v, dict)
    and str((v.get("gate_kind") or "")).strip().lower() == "hard_fail"
  ]
  return (len(hard) == 0), {
    "solver_target_hard_violations": hard[:10],
    "solver_target_total_violations": len(raw_violations) if isinstance(raw_violations, list) else None,
  }


def _check_revenue_not_flat(finmo_json: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
  rows = _quarter_rows_by_index(finmo_json)
  series: List[float] = []
  missing: List[int] = []
  for q in range(1, HORIZON_QUARTERS + 1):
    val = _quarter_field(rows, q, "revenue")
    if val is None:
      missing.append(q)
    else:
      series.append(float(val))
  if missing or len(series) < HORIZON_QUARTERS:
    return False, {
      "reason": "revenue_quarter_values_missing",
      "missing_quarters": missing,
      "values_seen": series,
    }
  mean = sum(series) / len(series)
  if mean <= 0:
    return False, {
      "reason": "revenue_mean_non_positive",
      "mean": mean,
      "values": series,
    }
  stdev = statistics.pstdev(series)
  cv = stdev / mean
  q1 = series[0]
  q10 = series[-1]
  q10_over_q1_delta = ((q10 - q1) / q1) if q1 > 0 else 0.0
  passed = (
    cv >= REVENUE_FLAT_STDEV_OVER_MEAN_THRESHOLD
    or q10_over_q1_delta >= REVENUE_FLAT_Q10_OVER_Q1_DELTA_THRESHOLD
  )
  return passed, {
    "values_q1_q10": series,
    "mean": round(mean, 2),
    "stdev": round(stdev, 2),
    "stdev_over_mean": round(cv, 6),
    "q10_over_q1_delta": round(q10_over_q1_delta, 6),
    "stdev_over_mean_threshold": REVENUE_FLAT_STDEV_OVER_MEAN_THRESHOLD,
    "q10_over_q1_delta_threshold": REVENUE_FLAT_Q10_OVER_Q1_DELTA_THRESHOLD,
  }


def _check_cash_legitimate(finmo_json: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
  """Cash may go negative ONLY if interest > 0 in that quarter — debt
  was raised by the cash strategy. A negative cash quarter with no
  interest means the cash strategy never ran (Sunny pattern).
  """
  rows = _quarter_rows_by_index(finmo_json)
  offending: List[Dict[str, Any]] = []
  missing_quarters: List[int] = []
  per_quarter: List[Dict[str, Any]] = []
  for q in range(1, HORIZON_QUARTERS + 1):
    cash = _quarter_field(rows, q, "cash", "cash_balance")
    interest = _quarter_field(rows, q, "interest", "debt_interest_expense")
    if cash is None:
      missing_quarters.append(q)
      continue
    per_quarter.append({"q": q, "cash": cash, "interest": interest})
    if cash < 0 and (interest is None or interest <= 0):
      offending.append({"quarter_index": q, "cash": cash, "interest": interest})
  if missing_quarters:
    return False, {
      "reason": "cash_quarter_values_missing",
      "missing_quarters": missing_quarters,
    }
  passed = len(offending) == 0
  return passed, {
    "negative_cash_with_no_interest_quarters": offending,
    "per_quarter_summary": per_quarter,
  }


# ----------------------------------------------------------------------------
# Phase 9 Phase G — six new acceptance criteria measuring business viability,
# not just pipeline integrity. Phase 8 verified that the orchestrator wrote
# fields correctly; Phase G verifies that the assembled plan is sellable.
# ----------------------------------------------------------------------------

_NI_TRAJECTORY_MIN_DELTA_Q5_TO_Q11 = 0.02  # 2pp minimum recovery
_INTEREST_REVENUE_RATIO_THRESHOLD_DEFAULT = 0.05  # 5% of revenue (NAICS-tunable later)
_BALANCE_SHEET_GROWTH_RATIO_THRESHOLD = 5.0  # cash/AR/inv may grow up to 5x opex


def _check_net_income_trajectory_viable(finmo_json: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
  """Phase 9 G1 — Q11 NI margin >= 0 AND Q11 > Q5 by the doctrine floor."""
  rows = _quarter_rows_by_index(finmo_json or {})
  q5 = rows.get(5) or {}
  q11 = rows.get(11) or {}
  q5_ni = _safe_float(q5.get("net_income"))
  q5_rev = _safe_float(q5.get("revenue"))
  q11_ni = _safe_float(q11.get("net_income"))
  q11_rev = _safe_float(q11.get("revenue"))
  if q5_rev is None or q11_rev is None or q5_rev <= 0 or q11_rev <= 0:
    return False, {
      "reason": "missing_q5_or_q11_revenue",
      "q5_revenue": q5_rev,
      "q11_revenue": q11_rev,
    }
  q5_margin = (q5_ni or 0.0) / float(q5_rev)
  q11_margin = (q11_ni or 0.0) / float(q11_rev)
  delta = q11_margin - q5_margin
  passed = (q11_margin >= 0.0) and (delta >= _NI_TRAJECTORY_MIN_DELTA_Q5_TO_Q11)
  return passed, {
    "q5_ni_margin": round(q5_margin, 4),
    "q11_ni_margin": round(q11_margin, 4),
    "q5_to_q11_delta": round(delta, 4),
    "min_required_delta": _NI_TRAJECTORY_MIN_DELTA_Q5_TO_Q11,
    "min_required_q11_margin": 0.0,
  }


def _check_cash_health_operational_not_debt_funded(
  finmo_json: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any]]:
  """Phase 9 G2 — interest expense / revenue at Q11 must be under industry-typical
  threshold (default 5%). Catches plans that fund growth purely with debt at
  ratios that would consume operating profit."""
  rows = _quarter_rows_by_index(finmo_json or {})
  q11 = rows.get(11) or {}
  interest = _safe_float(q11.get("debt_interest_expense"))
  if interest is None:
    interest = _safe_float(q11.get("interest_expense")) or 0.0
  revenue = _safe_float(q11.get("revenue"))
  if revenue is None or revenue <= 0:
    return False, {"reason": "missing_q11_revenue", "interest_q11": interest}
  ratio = float(interest or 0.0) / float(revenue)
  passed = ratio <= _INTEREST_REVENUE_RATIO_THRESHOLD_DEFAULT
  return passed, {
    "q11_interest": round(float(interest or 0.0), 2),
    "q11_revenue": round(float(revenue), 2),
    "interest_revenue_ratio": round(ratio, 4),
    "threshold": _INTEREST_REVENUE_RATIO_THRESHOLD_DEFAULT,
  }


def _check_cascade_exercised_or_documented(
  planning_run: Dict[str, Any],
  planning_run_json: Dict[str, Any],
  realism_memo: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Dict[str, Any]]:
  """Phase 9 G3 — tier > 0 lands fine on their own (cascade exercised); tier-0
  lands require non-vacuous justification that real bands were consulted, not
  papered with NAICS defaults."""
  cascade_tier = planning_run.get("cascade_landed_tier")
  try:
    tier_int = int(cascade_tier) if cascade_tier is not None else None
  except Exception:
    tier_int = None
  cascade_diag = planning_run_json.get("adaptation_cascade") or planning_run_json.get(
    "target_seeking_diagnostics", {}
  ).get("adaptation_cascade") or {}
  if tier_int is not None and tier_int > 0:
    return True, {
      "cascade_landed_tier": tier_int,
      "tier_exercised": True,
    }
  # Tier 0 land — require evidence Phase 3 calibration was real.
  # Phase 9 Step 2 fix: read realism_memo from the separate column (passed
  # in by the caller). Pre-fix code looked for realism_memo_json INSIDE
  # planning_run_json which never matches because they're parallel
  # columns in intake_consult_drafts. The bug made every tier-0 land
  # fail this check despite phase_3_calibrated bands being present.
  attempts = (cascade_diag or {}).get("tier_attempts") or []
  if not isinstance(realism_memo, dict) or not realism_memo:
    realism_memo = planning_run_json.get("realism_memo_json") or {}
  band_sources = []
  for entry in (realism_memo.get("results") or []):
    if isinstance(entry, dict):
      bs = entry.get("band_source")
      if bs:
        band_sources.append(str(bs))
  has_calibrated = any("phase_3_calibrated" in bs for bs in band_sources)
  passed = bool(has_calibrated) and bool(planning_run.get("plan_confidence"))
  return passed, {
    "cascade_landed_tier": tier_int,
    "phase_3_calibrated_bands_present": has_calibrated,
    "band_source_distinct_count": len(set(band_sources)),
    "tier_attempts_recorded": len(attempts),
  }


def _check_phase_3_calibrated_bands_consulted(
  realism_memo: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any]]:
  """Phase 9 G4 — at least one metric must have band_source containing
  'phase_3_calibrated' so we know cohort/GPT calibration actually flowed
  through the realism gate."""
  results = (realism_memo or {}).get("results") or []
  calibrated_metrics: List[str] = []
  naics_baseline_metrics: List[str] = []
  for r in results:
    if not isinstance(r, dict):
      continue
    bs = str(r.get("band_source") or "").lower()
    metric = str(r.get("metric_key") or "")
    if "phase_3_calibrated" in bs or "cohort" in bs:
      calibrated_metrics.append(metric)
    elif "naics" in bs:
      naics_baseline_metrics.append(metric)
  passed = len(calibrated_metrics) > 0
  return passed, {
    "calibrated_band_metric_count": len(calibrated_metrics),
    "naics_baseline_only_metric_count": len(naics_baseline_metrics),
    "examples_calibrated": calibrated_metrics[:5],
  }


def _check_balance_sheet_growth_plausible(
  finmo_json: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any]]:
  """Phase 9 G5 — cash / AR / inventory at Q20 must not be more than 5x
  the Q20 quarterly operating expense. Catches plans where cash accumulates
  absurdly because surplus distribution / capex absorption isn't working."""
  rows = _quarter_rows_by_index(finmo_json or {})
  q20 = rows.get(20) or {}
  if not q20:
    return False, {"reason": "missing_q20_row"}
  cash = _safe_float(q20.get("cash")) or 0.0
  ar = _safe_float(q20.get("accounts_receivable")) or 0.0
  inv = _safe_float(q20.get("inventory")) or 0.0
  payroll = _safe_float(q20.get("payroll")) or 0.0
  rent = _safe_float(q20.get("lease_rent")) or 0.0
  cogs = _safe_float(q20.get("cost_of_goods_sold")) or 0.0
  ga = _safe_float(q20.get("general_and_administrative")) or 0.0
  quarter_opex = max(payroll + rent + cogs + ga, 1.0)
  cash_ratio = cash / quarter_opex
  ar_ratio = ar / quarter_opex
  inv_ratio = inv / quarter_opex
  passed = (
    cash_ratio <= _BALANCE_SHEET_GROWTH_RATIO_THRESHOLD
    and ar_ratio <= _BALANCE_SHEET_GROWTH_RATIO_THRESHOLD
    and inv_ratio <= _BALANCE_SHEET_GROWTH_RATIO_THRESHOLD
  )
  return passed, {
    "q20_cash_to_quarter_opex": round(cash_ratio, 2),
    "q20_ar_to_quarter_opex": round(ar_ratio, 2),
    "q20_inventory_to_quarter_opex": round(inv_ratio, 2),
    "threshold": _BALANCE_SHEET_GROWTH_RATIO_THRESHOLD,
  }


def _check_viability_timeline_landed(
  realism_memo: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any]]:
  """Phase 9 G6 — all 6 universal viability timeline checks must pass.
  This is the doctrine's universal viability rule encoded as gate criteria."""
  expected_metrics = {
    "ebitda_positive_by_q11",
    "ebitda_recovery_trend_q5_q11",
    "loss_window_funded_through_q5",
    "no_post_recovery_relapse_q11_q20",
    "gross_margin_supports_ebitda_recovery",
    "fixed_cost_burden_reduced_or_scaled_by_q11",
  }
  results = (realism_memo or {}).get("results") or []
  found: Dict[str, str] = {}
  for r in results:
    if not isinstance(r, dict):
      continue
    metric = str(r.get("metric_key") or "")
    if metric in expected_metrics:
      found[metric] = str(r.get("status") or "")
  missing = sorted(expected_metrics - set(found.keys()))
  failed = [m for m, s in found.items() if s and "fail" in s.lower()]
  passed = (len(missing) == 0) and (len(failed) == 0)
  return passed, {
    "viability_timeline_metrics_found": sorted(found.keys()),
    "viability_timeline_metrics_missing": missing,
    "viability_timeline_metrics_failed": failed,
    "expected_metric_count": len(expected_metrics),
  }


def _check_current_assets_positive(finmo_json: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
  rows = _quarter_rows_by_index(finmo_json)
  offending: List[Dict[str, Any]] = []
  missing_quarters: List[int] = []
  for q in range(1, HORIZON_QUARTERS + 1):
    ca = _quarter_field(rows, q, "current_assets", "total_current_assets")
    if ca is None:
      missing_quarters.append(q)
      continue
    if ca <= 0:
      offending.append({"quarter_index": q, "current_assets": ca})
  if missing_quarters:
    return False, {
      "reason": "current_assets_quarter_values_missing",
      "missing_quarters": missing_quarters,
    }
  passed = len(offending) == 0
  return passed, {"non_positive_current_assets_quarters": offending}


def _persist_verdict(conn, *, planning_run_id: str, verdict: Dict[str, Any]) -> None:
  pr_id = str(planning_run_id or "").strip()
  if not pr_id:
    return
  payload = json.dumps(verdict, ensure_ascii=False, default=str)
  cur = conn.cursor()
  try:
    cur.execute(
      "UPDATE planning_runs SET acceptance_verdict_json = %s, updated_at = %s "
      "WHERE planning_run_id = %s",
      (payload, datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"), pr_id),
    )
    conn.commit()
  except Exception:
    try:
      conn.rollback()
    except Exception:
      pass
    raise
  finally:
    try:
      cur.close()
    except Exception:
      pass


def verify_run_acceptance(
  conn,
  *,
  draft_id: str,
  planning_run_id: Optional[str] = None,
) -> Dict[str, Any]:
  """Run the acceptance gate. Reads only; writes the verdict to
  planning_runs.acceptance_verdict_json. Returns the verdict dict.

  The caller (API handler) decides what to do with a failed verdict —
  this function never raises on a failed check, only on a malformed call
  (no draft_id, no DB).
  """
  d_id = str(draft_id or "").strip()
  if not d_id:
    raise RuntimeError("acceptance_gate_draft_id_required")

  planning_run = _planning_run_row(conn, planning_run_id=planning_run_id or "", draft_id=d_id)
  resolved_run_id = str(planning_run.get("planning_run_id") or planning_run_id or "").strip()
  draft = _draft_row(conn, draft_id=d_id)

  finmo_json = _parse_json(draft.get("finmo_json"))
  realism_memo = _parse_json(draft.get("realism_memo_json"))
  planning_run_json = _parse_json(draft.get("planning_run_json"))

  checks: List[Dict[str, Any]] = []

  def _record(name: str, passed: bool, detail: Dict[str, Any]) -> None:
    checks.append({"name": name, "passed": bool(passed), "detail": detail})

  passed, detail = _check_stage_reached_finalize(planning_run)
  _record("stage_reached_finalize", passed, detail)

  passed, detail = _check_cascade_tier_set(planning_run)
  _record("cascade_landed_tier_set", passed, detail)

  passed, detail = _check_plan_confidence_set(planning_run)
  _record("plan_confidence_recorded", passed, detail)

  passed, detail = _check_realism_provenance(realism_memo)
  _record("realism_gate_provenance_recorded", passed, detail)

  passed, detail = _check_realism_no_hard_fail(realism_memo)
  _record("realism_gate_no_hard_fail_violations", passed, detail)

  passed, detail = _check_solver_target_checked(planning_run_json)
  _record("solver_target_assertion_checked", passed, detail)

  passed, detail = _check_solver_target_no_hard_violations(planning_run_json)
  _record("solver_target_assertion_no_hard_violations", passed, detail)

  passed, detail = _check_revenue_not_flat(finmo_json)
  _record("revenue_not_flat_q1_q10", passed, detail)

  passed, detail = _check_cash_legitimate(finmo_json)
  _record("cash_legitimate_q1_q10", passed, detail)

  passed, detail = _check_current_assets_positive(finmo_json)
  _record("current_assets_positive_q1_q10", passed, detail)

  # Phase 9 Phase G — six new viability criteria.
  passed, detail = _check_net_income_trajectory_viable(finmo_json)
  _record("net_income_trajectory_viable", passed, detail)

  passed, detail = _check_cash_health_operational_not_debt_funded(finmo_json)
  _record("cash_health_operational_not_debt_funded", passed, detail)

  passed, detail = _check_cascade_exercised_or_documented(planning_run, planning_run_json, realism_memo)
  _record("cascade_exercised_or_documented", passed, detail)

  passed, detail = _check_phase_3_calibrated_bands_consulted(realism_memo)
  _record("phase_3_calibrated_bands_consulted", passed, detail)

  passed, detail = _check_balance_sheet_growth_plausible(finmo_json)
  _record("balance_sheet_growth_plausible", passed, detail)

  passed, detail = _check_viability_timeline_landed(realism_memo)
  _record("viability_timeline_landed", passed, detail)

  failed_checks = [c["name"] for c in checks if not c["passed"]]
  verdict: Dict[str, Any] = {
    "passed": len(failed_checks) == 0,
    "failed_checks": failed_checks,
    "checks": checks,
    "field_snapshot": {
      "planning_run_id": resolved_run_id or None,
      "current_stage": planning_run.get("current_stage"),
      "run_status": planning_run.get("run_status"),
      "cascade_landed_tier": planning_run.get("cascade_landed_tier"),
      "plan_confidence": planning_run.get("plan_confidence"),
      "draft_id": d_id,
      "finmo_quarter_row_count": len((finmo_json or {}).get("quarter_rows") or []),
      "realism_memo_present": bool(realism_memo),
      "planning_run_json_present": bool(planning_run_json),
    },
    "draft_id": d_id,
    "planning_run_id": resolved_run_id or None,
    "checked_at": _now_iso(),
    "gate_version": "phase_9_g_v1",
  }

  if resolved_run_id:
    try:
      _persist_verdict(conn, planning_run_id=resolved_run_id, verdict=copy.deepcopy(verdict))
    except Exception as exc:
      verdict.setdefault("persistence_error", str(exc))

  return verdict
