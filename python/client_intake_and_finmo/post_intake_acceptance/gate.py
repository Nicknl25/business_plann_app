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
        # Phase 9 audit fix #1 — the realism validator emits status
        # "out_of_band_hard_fail" (see validator.py line 829), not the
        # legacy "hard_fail". The pre-fix consumer only matched legacy
        # values, so every realism hard_fail was invisible to the gate.
        if status in ("hard_fail", "violation_hard_fail", "out_of_band_hard_fail") or (
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

_NI_TRAJECTORY_MIN_DELTA_Q5_TO_Q11 = 0.02  # 2pp minimum recovery (ramping shape)
# Minimum Q11 net-income margin for the FLAT-margin shape to count as healthy.
# Matches the strictest non-zero Q11 profitability floors in the planning-mode
# policy table (rebalance startup / turnaround mature = 0.02) — a level the
# doctrine already treats as the minimum sellable mature margin. Flat-near-zero
# stays non-viable.
_NI_Q11_HEALTHY_FLAT_MARGIN_FLOOR = 0.02
_INTEREST_REVENUE_RATIO_THRESHOLD_DEFAULT = 0.05  # 5% of revenue (NAICS-tunable later)
_BALANCE_SHEET_GROWTH_RATIO_THRESHOLD = 5.0  # cash/AR/inv may grow up to 5x opex


def _check_net_income_trajectory_viable(
  finmo_json: Dict[str, Any],
  model_input_json: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Dict[str, Any]]:
  """Phase 9 G1 recalibrated — the Q11 net-income position must be genuinely
  viable in EITHER of the two real shapes:

    (a) RAMPING: Q11 margin >= 0 and improving >= 2pp over Q5 (the original
        rule — an early-stage plan still climbing toward maturity), OR
    (b) FLAT-HEALTHY: Q11 margin >= the healthy floor (2%), no ramp required.

  The original rule demanded shape (a) only. That "margin must RAMP" pattern
  was an artifact of the fixed-payroll operating-leverage bug: margins ramped
  because payroll stayed flat while revenue grew. With payroll correctly
  scaling for labor-bound businesses, a mature plan holds a FLAT margin — the
  business gets BIGGER at the same margin, not more profitable — and shape (b)
  is the honest viable outcome. The guard still rejects what it must: a
  flat-NEGATIVE margin fails both shapes, and flat-near-zero (below the
  healthy floor, not ramping) fails both shapes."""
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
  # JUDGED NI FLOOR (fragility-class Wave 2): the flat-and-healthy bar
  # is the executive's ni_margin_floor_q11 when authored — a healthy
  # grocer's flat 1.2% NI could never satisfy a 2pp absolute constant,
  # while a consultancy limping at 3% flat should not be blessed by it.
  # Railed at authoring to [0, judged EBITDA band low]. Judgment absent
  # -> the 2pp constant governs (today's exact behavior).
  flat_floor = _NI_Q11_HEALTHY_FLAT_MARGIN_FLOOR
  flat_floor_source = "doctrine_default_2pp"
  try:
    from client_intake_and_finmo.post_intake_headcount.gpt_margin_band_judgment import (  # type: ignore  # noqa: E501
      margin_band_from_model_input,
    )
    _judgment = margin_band_from_model_input(model_input_json)
    _judged_ni = (_judgment or {}).get("ni_margin_floor_q11")
    if _judged_ni is not None:
      flat_floor = float(_judged_ni)
      flat_floor_source = "executive_margin_band_judgment"
  except Exception:
    flat_floor = _NI_Q11_HEALTHY_FLAT_MARGIN_FLOOR
    flat_floor_source = "doctrine_default_2pp"
  ramping_viable = (q11_margin >= 0.0) and (delta >= _NI_TRAJECTORY_MIN_DELTA_Q5_TO_Q11)
  flat_healthy_viable = q11_margin >= flat_floor
  passed = ramping_viable or flat_healthy_viable
  return passed, {
    "q5_ni_margin": round(q5_margin, 4),
    "q11_ni_margin": round(q11_margin, 4),
    "q5_to_q11_delta": round(delta, 4),
    "ramping_viable": ramping_viable,
    "flat_healthy_viable": flat_healthy_viable,
    "min_required_delta_ramping": _NI_TRAJECTORY_MIN_DELTA_Q5_TO_Q11,
    "min_required_q11_margin_flat": round(float(flat_floor), 4),
    "flat_floor_source": flat_floor_source,
  }


def _check_cash_never_negative(
  finmo_json: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any]]:
  """A plan whose ending cash goes NEGATIVE in any live quarter is not a
  fundable plan — no lender reads a negative cash balance as anything but
  insolvency. This is the verdict-side replacement for the finalize cash-
  buffer CRASH (demoted to advisory): a business that honestly cannot keep
  cash positive under its JUDGED funding access renders an honest
  NON-VIABLE with the record intact, instead of a dead run (Cedar: debt-
  only access, every funding leg exhausted, cash -$2.9M by Q20 — the
  machinery tried proposer + handler + minimum-debt floors and the drag
  arithmetic genuinely does not close)."""
  rows = _quarter_rows_by_index(finmo_json or {})
  negative_quarters = []
  for q in range(1, 21):
    row = rows.get(q) or {}
    ending = _safe_float(row.get("ending_cash"))
    if ending is None:
      continue
    if float(ending) < 0.0:
      negative_quarters.append({"q": q, "ending_cash": round(float(ending), 2)})
  return (not negative_quarters), {
    "negative_cash_quarters": negative_quarters[:10],
    "negative_quarter_count": len(negative_quarters),
  }


def _check_cash_health_operational_not_debt_funded(
  finmo_json: Dict[str, Any],
  model_input_json: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Dict[str, Any]]:
  """Phase 9 G2 — the plan must not fund growth with debt it cannot carry.

  DEFAULT RAIL (no cash judgment): interest / revenue at Q11 <= 5% — the
  small-business lender's rule of thumb.

  JUDGMENT-AWARE RAIL: when the executive cash judgment authored this
  business's capital structure (viability-blind, fundability-not-need),
  a flat percent-of-revenue rail misjudges honestly debt-financed
  models — a project-financed plant with contracted PPA revenue runs
  15%+ interest/revenue and real lenders underwrite it on COVERAGE.
  The test becomes Q11 EBITDA / Q11 interest >= 2.0x (the standard
  lender coverage floor). This CANNOT rescue a doomed business: negative
  or thin EBITDA fails coverage automatically, and the judgment that
  unlocks this rail is the same one that refuses funding to unfundable
  businesses. No debt (zero interest) passes trivially under either rail.
  """
  rows = _quarter_rows_by_index(finmo_json or {})
  q11 = rows.get(11) or {}
  interest = _safe_float(q11.get("debt_interest_expense"))
  if interest is None:
    interest = _safe_float(q11.get("interest_expense")) or 0.0
  revenue = _safe_float(q11.get("revenue"))
  if revenue is None or revenue <= 0:
    return False, {"reason": "missing_q11_revenue", "interest_q11": interest}
  ratio = float(interest or 0.0) / float(revenue)

  _judgment = None
  try:
    from client_intake_and_finmo.post_intake_cash.gpt_cash_judgment import (  # type: ignore
      cash_judgment_from_model_input,
    )
    _judgment = cash_judgment_from_model_input(model_input_json)
  except Exception:
    _judgment = None
  if isinstance(_judgment, dict):
    # 1.5x interest coverage — conservative against real lender norms
    # (SBA's own DSCR minimum is 1.15x; 1.25-1.5x is the conventional
    # small-business floor). A 2.0x floor failed an otherwise-viable
    # shop carrying a small buffer revolver at 1.9x — a loan any
    # community lender writes. Negative/thin EBITDA still fails
    # automatically, so a doomed business cannot pass this rail.
    _COVERAGE_FLOOR = 1.5
    ebitda = _safe_float(q11.get("ebitda")) or 0.0
    if float(interest or 0.0) <= 0.0:
      coverage = float("inf")
      passed = True
    else:
      coverage = float(ebitda) / float(interest)
      passed = coverage >= _COVERAGE_FLOOR
    return passed, {
      "rail": "judged_capital_structure_interest_coverage",
      "q11_interest": round(float(interest or 0.0), 2),
      "q11_ebitda": round(float(ebitda), 2),
      "interest_coverage": (round(coverage, 2) if coverage != float("inf") else "no_debt"),
      "coverage_floor": _COVERAGE_FLOOR,
      "interest_revenue_ratio_informational": round(ratio, 4),
    }

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
  'phase_3_calibrated' so we know cohort calibration flowed through the
  realism gate.

  Phase 9 P3.5 — the GPT amendment layer (target_shaping consultant)
  has been retired; the "phase_3_calibrated" band_source label now
  signifies the deterministic Phase 3 Python proposer's calibrated
  per-business targets band (no GPT). The gate check still passes
  whenever the per-business band cascade fired — which it does
  unconditionally now that ``assemble_finmo_output_targets`` is the
  sole producer."""
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
    "ebitda_margin_q20_holds_or_improves_vs_q11",
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


JUDGMENT_LEDGER_EXPECTED_SITES = (
  "wc_judgment",
  "cash_judgment",
  "margin_band_judgment",
  "headcount_coherence",
  "growth_judgment",
  "revenue_authoring",
  "band_fitting",
)

# Ledger sources that are legitimate DECLARED absences (nothing to judge)
# rather than authored judgments. Anything else with authored=False is a
# substituted judgment reaching the gate — hard fail.
JUDGMENT_LEDGER_TOLERATED_ABSENCES = (
  "no_industry_envelope",
  "grid_default_drivers",
  "naics_flat_seed",
  "mechanical_constants",
  "derived_cost_band_only",
  "stated_team_stands",
  "mechanical_defaults",
)


def _check_judgment_ledger(model_input_json: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
  """Doctrine invariant, one testable check: no plan ships on a
  substituted judgment. Every judgment seat must have DECLARED itself in
  solver_input.judgment_ledger (author failures raise upstream and never
  reach this gate; a missing declaration means a seat was silently
  bypassed — the S16 class)."""
  ledger = ((model_input_json or {}).get("solver_input") or {}).get("judgment_ledger")
  if not isinstance(ledger, dict) or not ledger:
    return False, {"reason": "judgment_ledger_missing"}
  missing = [s for s in JUDGMENT_LEDGER_EXPECTED_SITES if s not in ledger]
  undeclared = [
    site
    for site, entry in ledger.items()
    if not isinstance(entry, dict)
    or (
      not entry.get("authored")
      and str(entry.get("source") or "") not in JUDGMENT_LEDGER_TOLERATED_ABSENCES
    )
  ]
  detail = {
    "sites": {
      site: {
        "authored": bool((entry or {}).get("authored")),
        "source": str((entry or {}).get("source") or ""),
      }
      for site, entry in ledger.items()
      if isinstance(entry, dict)
    },
    "missing_declarations": missing,
    "undeclared_or_invalid": undeclared,
  }
  return (not missing and not undeclared), detail


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
    # Step 9d item 25 — FAIL_WORKBOOK_ACCEPT_NO_DRAFT_ID.
    from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
      FailFastCode, PhaseCode, raise_fail_fast,
    )
    raise_fail_fast(
      conn, draft_id="", planning_run_id=str(planning_run_id or ""),
      phase=PhaseCode.WORKBOOK_ACCEPT,
      code=FailFastCode.FAIL_WORKBOOK_ACCEPT_NO_DRAFT_ID,
      detail="acceptance_gate_draft_id_required",
      where="post_intake_acceptance.gate.verify_run_acceptance",
    )

  planning_run = _planning_run_row(conn, planning_run_id=planning_run_id or "", draft_id=d_id)
  resolved_run_id = str(planning_run.get("planning_run_id") or planning_run_id or "").strip()
  if not resolved_run_id:
    # Step 9d item 24 — FAIL_WORKBOOK_ACCEPT_NO_RUN_ID. Neither the
    # caller-supplied planning_run_id nor the row lookup yielded one.
    from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
      FailFastCode, PhaseCode, raise_fail_fast,
    )
    raise_fail_fast(
      conn, draft_id=d_id, planning_run_id="",
      phase=PhaseCode.WORKBOOK_ACCEPT,
      code=FailFastCode.FAIL_WORKBOOK_ACCEPT_NO_RUN_ID,
      detail=f"no planning_run_id resolvable for draft_id={d_id!r}",
      where="post_intake_acceptance.gate.verify_run_acceptance",
    )
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
  passed, detail = _check_net_income_trajectory_viable(
    finmo_json, _parse_json(draft.get("model_input_json")),
  )
  _record("net_income_trajectory_viable", passed, detail)

  passed, detail = _check_cash_health_operational_not_debt_funded(
    finmo_json, _parse_json(draft.get("model_input_json")),
  )
  _record("cash_health_operational_not_debt_funded", passed, detail)

  passed, detail = _check_cash_never_negative(finmo_json)
  _record("cash_never_negative", passed, detail)

  passed, detail = _check_cascade_exercised_or_documented(planning_run, planning_run_json, realism_memo)
  _record("cascade_exercised_or_documented", passed, detail)

  passed, detail = _check_phase_3_calibrated_bands_consulted(realism_memo)
  _record("phase_3_calibrated_bands_consulted", passed, detail)

  passed, detail = _check_balance_sheet_growth_plausible(finmo_json)
  _record("balance_sheet_growth_plausible", passed, detail)

  passed, detail = _check_viability_timeline_landed(realism_memo)
  _record("viability_timeline_landed", passed, detail)

  passed, detail = _check_judgment_ledger(_parse_json(draft.get("model_input_json")))
  _record("judgment_ledger_complete", passed, detail)

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

  # Fix #1 — viability standard (operating-engine-only economic-soundness
  # verdict). ADVISORY here: attached for surfacing, does NOT gate `passed`
  # (the standard supersedes planning_mode's profitability-FLOOR judgement
  # role, but that floor still shapes the out-of-scope solver — see
  # post_intake_viability/adapter.py SURFACED notes). Wrapped so it can never
  # break the acceptance gate.
  try:
    from client_intake_and_finmo.post_intake_viability.adapter import (  # type: ignore
      evaluate_run_viability,
    )
    model_input_json = _parse_json(draft.get("model_input_json"))
    verdict["viability_standard"] = evaluate_run_viability(
      finmo_json=finmo_json,
      draft=draft,
      model_input_json=model_input_json,
      planning_run_json=planning_run_json,
    )
  except Exception as exc:  # advisory — never break acceptance
    verdict["viability_standard"] = {"verdict": "error", "error": str(exc)}

  # Fix #1 — payroll/revenue feasibility ADVISORY (non-gating). The assert is
  # demoted to advisory upstream (premature viability/affordability judgment —
  # docs/architecture/payroll_revenue_assert_purpose_trace.md). Surface the
  # violation signal here durably for transparency / a possible future
  # malformed-driver envelope; it does NOT gate `passed`.
  try:
    from client_intake_and_finmo.post_intake_headcount import (  # type: ignore
      payroll_revenue_feasibility_violations,
    )
    _pr_payroll = _parse_json(draft.get("payroll_headcount"))
    _pr_violations = payroll_revenue_feasibility_violations(
      payroll_headcount=_pr_payroll, finmo_json=finmo_json,
    )
    verdict["payroll_revenue_feasibility_advisory"] = {
      "gating": False,
      "violation_count": len(_pr_violations),
      "violations": _pr_violations[:20],
    }
  except Exception as exc:  # advisory — never break acceptance
    verdict["payroll_revenue_feasibility_advisory"] = {"gating": False, "error": str(exc)}

  if resolved_run_id:
    try:
      _persist_verdict(conn, planning_run_id=resolved_run_id, verdict=copy.deepcopy(verdict))
    except Exception as exc:
      verdict.setdefault("persistence_error", str(exc))

  # Step 9c — workbook_accept emit. The acceptance gate's verdict is the
  # workbook_accept phase outcome. ACCEPTED on passed=True; REJECTED
  # otherwise, with diagnostic_data carrying failed_check names.
  if resolved_run_id and d_id:
    try:
      from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
        EventCode as _DiagEventCode,
        PhaseCode as _DiagPhaseCode,
        Status as _DiagStatus,
        safe_emit as _diag_safe_emit,
      )
      _diag_safe_emit(
        conn,
        draft_id=d_id,
        planning_run_id=resolved_run_id,
        phase=_DiagPhaseCode.WORKBOOK_ACCEPT,
        event_code=(
          _DiagEventCode.WORKBOOK_ACCEPT_ACCEPTED if verdict["passed"]
          else _DiagEventCode.WORKBOOK_ACCEPT_REJECTED
        ),
        status=(_DiagStatus.COMPLETED if verdict["passed"] else _DiagStatus.FAILED),
        diagnostic_data={
          "failed_check_count": len(failed_checks),
          "failed_check_names": list(failed_checks)[:10],
          "gate_version": "phase_9_g_v1",
        },
      )
    except Exception:
      pass

  return verdict
