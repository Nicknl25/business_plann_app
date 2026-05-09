"""Module 3 Task 3.6 — `validate_industry_realism_bands`.

The finalize-stage realism gate. Walks `post_intake_finalize_realism_check_lookup`,
computes each metric's actual ratio via the formula registry, resolves the
NAICS band via Module 1's resolver, applies the confidence-tier-keyed
tolerance, and either:

  - raises `RealismBandViolation` (gate_kind = "hard_fail")
  - appends to a warnings list (gate_kind = "warn")
  - skips the check (gate_kind = "skip_if_no_coverage" + no coverage)

Invariants enforced (from master-diagnostic Part 9):
  - Stub 0 (period[0]) is intake fact and is NEVER validated.
  - The gate fails-fast or warns; it does NOT rewrite drivers or statements.
  - Every check carries provenance — metric, naics_level_used,
    confidence_tier, source band, produced value, residual.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .formulas import evaluate_realism_formula
from .lookup import post_intake_finalize_realism_check_rows


HORIZON_QUARTERS = 20


# ----------------------------------------------------------------------------
# Result + violation types.
# ----------------------------------------------------------------------------


@dataclass
class RealismCheckResult:
  metric_key: str
  finmo_line_label: str
  derivation_formula_key: str
  quarter_aggregation: str
  quarter_index: Optional[int]
  actual_value: Optional[float]
  band_min: Optional[float]
  band_max: Optional[float]
  band_target: Optional[float]
  band_naics_code: Optional[str]
  band_naics_level: Optional[int]
  band_confidence_tier: Optional[str]
  band_data_source: Optional[str]
  band_trust_flag: Optional[str]
  tolerance_applied_bps: Optional[int]
  effective_min: Optional[float]
  effective_max: Optional[float]
  status: str  # 'in_band' | 'out_of_band_warn' | 'out_of_band_hard_fail' | 'skipped' | 'no_coverage'
  reason: str
  governs_lever_id: Optional[str] = None
  # Phase 6 Step 5 — band-source provenance. Records WHICH path resolved
  # the band edges so the run report can audit why each metric was
  # checked against what.
  band_source: str = "naics_baseline"
  planning_mode_floor_applied: Optional[float] = None
  planning_mode_active: Optional[str] = None
  tolerated_issue_code: Optional[str] = None

  def to_dict(self) -> Dict[str, Any]:
    return {
      "metric_key": self.metric_key,
      "finmo_line_label": self.finmo_line_label,
      "derivation_formula_key": self.derivation_formula_key,
      "quarter_aggregation": self.quarter_aggregation,
      "quarter_index": self.quarter_index,
      "actual_value": self.actual_value,
      "band_min": self.band_min,
      "band_max": self.band_max,
      "band_target": self.band_target,
      "band_naics_code": self.band_naics_code,
      "band_naics_level": self.band_naics_level,
      "band_confidence_tier": self.band_confidence_tier,
      "band_data_source": self.band_data_source,
      "band_trust_flag": self.band_trust_flag,
      "tolerance_applied_bps": self.tolerance_applied_bps,
      "effective_min": self.effective_min,
      "effective_max": self.effective_max,
      "status": self.status,
      "reason": self.reason,
      "governs_lever_id": self.governs_lever_id,
      "band_source": self.band_source,
      "planning_mode_floor_applied": self.planning_mode_floor_applied,
      "planning_mode_active": self.planning_mode_active,
      "tolerated_issue_code": self.tolerated_issue_code,
    }


class RealismBandViolation(RuntimeError):
  """Raised on the first hard_fail violation encountered."""

  def __init__(self, message: str, *, results: Iterable[RealismCheckResult]):
    super().__init__(message)
    self.results = [r.to_dict() for r in results]


# ----------------------------------------------------------------------------
# Applicability rules.
# ----------------------------------------------------------------------------


def _naics_2(naics_6: Optional[str]) -> str:
  if not naics_6:
    return ""
  digits = "".join(ch for ch in str(naics_6) if ch.isdigit())
  return digits[:2]


def _applicability_skip(
  *,
  rule_key: Optional[str],
  business_naics_6: Optional[str],
  ops_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int],
) -> Optional[str]:
  """Return a non-empty reason string when the check should be skipped, else None."""
  if not rule_key:
    return None
  rule = str(rule_key).strip().lower()
  if rule == "skip_when_revenue_zero":
    revenue = _safe_float(_quarter_field(finmo_json, quarter_index, "revenue")) if quarter_index else None
    if revenue is None or revenue <= 0.0:
      return "skip_revenue_zero"
    return None
  if rule == "skip_when_operating_expense_zero":
    if quarter_index is None:
      return None
    base = _safe_float(_quarter_field(finmo_json, quarter_index, "operating_expense_total"))
    if base is None or base <= 0.0:
      cogs = _safe_float(_quarter_field(finmo_json, quarter_index, "cogs")) or 0.0
      marketing = _safe_float(_quarter_field(finmo_json, quarter_index, "marketing")) or 0.0
      g_and_a = _safe_float(_quarter_field(finmo_json, quarter_index, "g_and_a")) or 0.0
      base = float(cogs) + float(marketing) + float(g_and_a)
    if base is None or base <= 0.0:
      return "skip_operating_expense_zero"
    return None
  if rule == "skip_when_pretax_income_nonpositive":
    pretax = 0.0
    found = False
    for q in (1, 2, 3, 4):
      v = _safe_float(_quarter_field(finmo_json, q, "pretax_income"))
      if v is None:
        v = _safe_float(_quarter_field(finmo_json, q, "ebt"))
      if v is not None:
        pretax += float(v)
        found = True
    if not found or pretax <= 0.0:
      return "skip_pretax_income_nonpositive"
    return None
  if rule == "inventory_when_business_has_inventory":
    naics_2 = _naics_2(business_naics_6)
    inventory_naics_2 = {"31", "32", "33", "42", "44", "45", "72"}
    if naics_2 not in inventory_naics_2:
      return f"skip_inventory_not_applicable_naics2_{naics_2 or 'unknown'}"
    return None
  if rule == "r_and_d_when_applicable":
    # Skip when r_and_d is zero across the entire forecast horizon — that
    # is the deterministic signal that the r_and_d_applicability decision
    # disabled the lever upstream. Any nonzero R&D anywhere triggers the
    # band check.
    nonzero = False
    for row in (finmo_json or {}).get("quarter_rows") or []:
      if not isinstance(row, dict):
        continue
      qi = int(_safe_float(row.get("quarter_index")) or 0)
      if qi < 1:
        continue
      v = _safe_float(row.get("research_and_development"))
      if v is not None and abs(float(v)) > 1e-6:
        nonzero = True
        break
    if not nonzero:
      return "skip_r_and_d_not_applicable_to_business"
    return None
  if rule == "deferred_revenue_when_business_has_recurring":
    naics_2 = _naics_2(business_naics_6)
    # Recurring/contract-based business models: Information, Finance, Real
    # Estate, Professional Services, plus Healthcare (62) where capitation
    # / membership revenue is deferred-revenue-shaped.
    deferred_naics_2 = {"51", "52", "53", "54", "62"}
    if naics_2 not in deferred_naics_2:
      return f"skip_deferred_revenue_not_applicable_naics2_{naics_2 or 'unknown'}"
    return None
  if rule == "skip_when_debt_zero":
    if quarter_index is None:
      return None
    short_term = _safe_float(_quarter_field(finmo_json, quarter_index, "short_term_debt")) or 0.0
    long_term = _safe_float(_quarter_field(finmo_json, quarter_index, "long_term_debt")) or 0.0
    if abs(short_term) <= 1e-6 and abs(long_term) <= 1e-6:
      return "skip_debt_zero"
    return None
  if rule == "skip_when_distributions_zero":
    distributions_total = 0.0
    nonzero = False
    for row in (finmo_json or {}).get("quarter_rows") or []:
      if not isinstance(row, dict):
        continue
      qi = int(_safe_float(row.get("quarter_index")) or 0)
      if qi < 1:
        continue
      v = _safe_float(row.get("distributions"))
      if v is None:
        v = _safe_float(row.get("owner_distributions"))
      if v is None:
        continue
      distributions_total += float(v)
      if abs(float(v)) > 1e-6:
        nonzero = True
    if not nonzero:
      return "skip_distributions_zero"
    return None
  # Unknown rule — fail open (do not skip), but tag it for diagnostics.
  return None


def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  try:
    out = float(value)
  except Exception:
    return None
  if out != out:
    return None
  return out


def _quarter_field(finmo_json: Dict[str, Any], quarter_index: Optional[int], field_name: str) -> Optional[float]:
  if quarter_index is None:
    return None
  for row in (finmo_json or {}).get("quarter_rows") or []:
    if not isinstance(row, dict):
      continue
    if int(_safe_float(row.get("quarter_index")) or 0) == int(quarter_index):
      return _safe_float(row.get(field_name))
  return None


# ----------------------------------------------------------------------------
# Tolerance picker.
# ----------------------------------------------------------------------------


def _tolerance_bps_for_confidence(
  row: Dict[str, Any], confidence_tier: str
) -> Optional[int]:
  tier = str(confidence_tier or "").strip().lower()
  if tier == "high":
    return int(row.get("tolerance_bps_high_confidence") or 0)
  if tier == "medium":
    return int(row.get("tolerance_bps_medium_confidence") or 0)
  if tier == "low":
    return int(row.get("tolerance_bps_low_confidence") or 0)
  if tier == "generic_default":
    raw = row.get("tolerance_bps_generic_default")
    return None if raw is None else int(raw)
  return None


# ----------------------------------------------------------------------------
# Phase 6 Step 5 — band-resolution helpers.
# ----------------------------------------------------------------------------


# Profitability metrics whose effective_min is floored by the active
# planning_mode_policy.profitability_floor_q* values. Other metrics
# ignore the floor.
_PROFITABILITY_FLOOR_METRICS = frozenset({
  "ebitda_margin",
  "net_income_margin",
  "operating_margin_percent",
})


# Mapping from realism metric_key (when violated below band) to the
# planning_mode_policy.tolerated_issue_codes entry that, when listed for
# the active mode, downgrades hard_fail to warn. Only configured for
# metrics where the violation maps cleanly onto an issue code already
# used by the convergence issue detector / planning_mode policy.
_REALISM_METRIC_BELOW_BAND_TO_ISSUE_CODE: Dict[str, str] = {
  "ebitda_margin": "mature_loss_state",
  "net_income_margin": "mature_loss_state",
  "operating_margin_percent": "mature_loss_state",
  "gross_margin_percent": "early_revenue_under_run_rate",
}


def _profitability_floor_for_quarter(
  policy: Optional[Dict[str, Any]], quarter_index: Optional[int],
) -> Optional[float]:
  """Return the planning_mode_policy.profitability_floor_q* value that
  applies for the given quarter index, or None when no floor applies for
  the active mode (e.g., turnaround Q1-Q10 where all floors are NULL).
  """
  if not isinstance(policy, dict) or quarter_index is None:
    return None
  q = int(quarter_index)
  if q <= 0:
    return None
  if q <= 4:
    raw = policy.get("profitability_floor_q1_q4")
  elif q <= 10:
    raw = policy.get("profitability_floor_q5_q10")
  else:
    raw = policy.get("profitability_floor_q11_q20")
  if raw is None:
    return None
  try:
    return float(raw)
  except Exception:
    return None


def _phase_3_calibrated_band(
  *,
  solver_input_targets_payload: Optional[Dict[str, Any]],
  metric_key: str,
) -> Optional[Dict[str, Any]]:
  """Return Phase 3 calibrated band for the metric, or None if absent.

  The Phase 3 target-shaping consultant calibrates per-metric bands and
  stamps them on solver_input.finmo_output_targets.metrics. When present
  for the metric being validated, the realism gate prefers this
  business-specific band over the static NAICS baseline.
  """
  if not isinstance(solver_input_targets_payload, dict):
    return None
  metrics = solver_input_targets_payload.get("metrics")
  if not isinstance(metrics, dict):
    return None
  entry = metrics.get(metric_key)
  if not isinstance(entry, dict):
    return None
  target_min = _safe_float(entry.get("target_min"))
  target_max = _safe_float(entry.get("target_max"))
  if target_min is None or target_max is None:
    return None
  return {
    "target_min": target_min,
    "target_max": target_max,
    "target_target": _safe_float(entry.get("target_target")),
    "calibration_source": (
      ((entry.get("provenance") or {}).get("calibration_source"))
      if isinstance(entry.get("provenance"), dict) else None
    ),
    "confidence_tier": (
      ((entry.get("provenance") or {}).get("confidence_tier"))
      if isinstance(entry.get("provenance"), dict) else None
    ),
  }


def _planning_mode_policy(planning_mode: Optional[str]) -> Optional[Dict[str, Any]]:
  if not planning_mode:
    return None
  try:
    from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
      post_intake_planning_mode_policy_for,
    )
    return post_intake_planning_mode_policy_for(planning_mode)
  except Exception:
    return None


# ----------------------------------------------------------------------------
# The validator.
# ----------------------------------------------------------------------------


def validate_industry_realism_bands(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  business_naics_6: Optional[str],
  ops_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  rows_override: Optional[List[Dict[str, Any]]] = None,
  solver_input_targets_payload: Optional[Dict[str, Any]] = None,
  planning_mode: Optional[str] = None,
) -> Dict[str, Any]:
  """Run the realism gate over the configured check rows.

  Returns a payload with the full result set. Hard-fail violations raise
  `RealismBandViolation` immediately on the first hit (the diagnostic
  payload includes all results computed so far).

  `rows_override` is for tests — production callers should let the
  validator load from `post_intake_finalize_realism_check_lookup`.

  Phase 6 Step 5 — band-resolution cascade and planning-mode wiring:
    1. Phase 3 calibrated band from
       ``solver_input_targets_payload.metrics[metric_key]`` is preferred
       when present. The Phase 3 target-shaping consultant calibrates
       these per-metric bands per business; using them instead of the
       static NAICS baseline closes the disconnect between "what the
       solver targeted" and "what the gate accepts."
    2. NAICS baseline is the fallback when Phase 3 didn't calibrate the
       metric.
    3. For profitability metrics (ebitda_margin / net_income_margin /
       operating_margin_percent), the active planning_mode policy's
       per-quarter ``profitability_floor_q*`` is enforced as a floor on
       the effective minimum. None floor (e.g., turnaround Q1-Q10) leaves
       the band unchanged. A non-None floor that's higher than the
       resolved band's lower edge raises the effective_min to the floor.
    4. Hard-fail violations are downgraded to warnings when the
       metric's derived issue code (per
       ``_REALISM_METRIC_BELOW_BAND_TO_ISSUE_CODE``) appears in the
       planning_mode policy's tolerated_issue_codes list.

  Every result records its band_source provenance so the run report
  can audit which path resolved each metric's band.
  """
  rows = rows_override if rows_override is not None else post_intake_finalize_realism_check_rows()
  results: List[RealismCheckResult] = []
  warnings_list: List[Dict[str, Any]] = []
  ops = ops_json if isinstance(ops_json, dict) else {}
  financials = financials_json if isinstance(financials_json, dict) else {}
  active_mode = str(planning_mode or "").strip().lower() or None
  active_policy = _planning_mode_policy(active_mode)
  tolerated_codes: set = set(
    str(code or "").strip().lower()
    for code in ((active_policy or {}).get("tolerated_issue_codes") or [])
    if str(code or "").strip()
  )

  # Lazy import the resolver so the validator module can be imported even
  # when the resolver package is not yet on sys.path (tests / migrations).
  from client_intake_and_finmo.post_intake_industry_baseline import (  # type: ignore
    post_intake_industry_baseline_for_naics,
  )

  for row in rows:
    metric_key = str(row.get("metric_key") or "").strip()
    if not metric_key or not bool(row.get("active", True)):
      continue
    aggregation = str(row.get("quarter_aggregation") or "per_quarter").strip().lower()
    formula_key = str(row.get("derivation_formula_key") or "").strip()
    finmo_label = str(row.get("finmo_line_label") or "").strip()
    governs_lever = row.get("governs_model_input_lever_id")
    gate_kind = str(row.get("gate_kind") or "warn").strip().lower()

    # Phase 9 Phase D — trajectory_check rows (universal viability
    # timeline) are evaluated separately from the band-comparison loop.
    # The formula returns a value where >= 0.0 = pass, < 0.0 = fail.
    # No NAICS band needed — the doctrine itself is the threshold.
    if aggregation == "trajectory_check":
      try:
        trajectory_value = evaluate_realism_formula(
          formula_key,
          model_input_json=model_input_json,
          finmo_json=finmo_json,
          quarter_index=None,
        )
      except Exception as exc:
        results.append(RealismCheckResult(
          metric_key=metric_key, finmo_line_label=finmo_label,
          derivation_formula_key=formula_key, quarter_aggregation=aggregation,
          quarter_index=None, actual_value=None,
          band_min=0.0, band_max=None, band_target=0.0,
          band_naics_code=None, band_naics_level=None, band_confidence_tier=None,
          band_data_source="universal_viability_doctrine",
          band_trust_flag="phase_9_doctrine",
          tolerance_applied_bps=None, effective_min=0.0, effective_max=None,
          status="skipped",
          reason=f"trajectory_formula_exception: {type(exc).__name__}: {str(exc)[:200]}",
          governs_lever_id=governs_lever, band_source="universal_viability_doctrine",
          planning_mode_active=active_mode,
        ))
        continue
      if trajectory_value is None:
        results.append(RealismCheckResult(
          metric_key=metric_key, finmo_line_label=finmo_label,
          derivation_formula_key=formula_key, quarter_aggregation=aggregation,
          quarter_index=None, actual_value=None,
          band_min=0.0, band_max=None, band_target=0.0,
          band_naics_code=None, band_naics_level=None, band_confidence_tier=None,
          band_data_source="universal_viability_doctrine",
          band_trust_flag="phase_9_doctrine",
          tolerance_applied_bps=None, effective_min=0.0, effective_max=None,
          status="skipped", reason="trajectory_formula_returned_none",
          governs_lever_id=governs_lever, band_source="universal_viability_doctrine",
          planning_mode_active=active_mode,
        ))
        continue
      passed = float(trajectory_value) >= 0.0
      status = "in_band" if passed else "out_of_band_hard_fail"
      results.append(RealismCheckResult(
        metric_key=metric_key, finmo_line_label=finmo_label,
        derivation_formula_key=formula_key, quarter_aggregation=aggregation,
        quarter_index=None, actual_value=float(trajectory_value),
        band_min=0.0, band_max=None, band_target=0.0,
        band_naics_code=None, band_naics_level=None, band_confidence_tier="universal",
        band_data_source="universal_viability_doctrine",
        band_trust_flag="phase_9_doctrine",
        tolerance_applied_bps=None, effective_min=0.0, effective_max=None,
        status=status, reason=None if passed else f"viability_check_failed: value={trajectory_value:.4f} below universal floor 0.0",
        governs_lever_id=governs_lever, band_source="universal_viability_doctrine",
        planning_mode_active=active_mode,
      ))
      # trajectory_check rows DO NOT raise RealismBandViolation; they
      # surface as hard_fail status and the cascade reads them via the
      # issue router. This avoids halting the run on Q11 EBITDA<0 when
      # the cascade is actively trying to repair it.
      continue

    quarter_indices: List[Optional[int]]
    if aggregation == "per_quarter":
      quarter_indices = list(range(1, HORIZON_QUARTERS + 1))
    elif aggregation in ("year_one_aggregate", "horizon_average"):
      quarter_indices = [None]
    else:
      quarter_indices = [None]

    # Phase 6 Step 5 — band resolution cascade. Phase 3 calibrated band
    # is preferred when present; NAICS baseline is the fallback. The
    # band_source provenance travels onto every RealismCheckResult so
    # the run report can audit per-metric why each check used what.
    phase_3_band = _phase_3_calibrated_band(
      solver_input_targets_payload=solver_input_targets_payload,
      metric_key=metric_key,
    )
    naics_band: Optional[Dict[str, Any]] = None
    if business_naics_6:
      try:
        naics_band = post_intake_industry_baseline_for_naics(
          metric_key=metric_key, naics_6=business_naics_6
        )
      except Exception:
        naics_band = None

    if phase_3_band is not None:
      row_band_source = "phase_3_calibrated"
      band_target = phase_3_band["target_target"]
      band_min = phase_3_band["target_min"]
      band_max = phase_3_band["target_max"]
      band_confidence = phase_3_band.get("confidence_tier") or "high"
      band_naics_code = (naics_band or {}).get("naics_code_used")
      band_naics_level = (naics_band or {}).get("naics_level_used")
      band_data_source = "phase_3_target_shaping_consultant"
      band_trust_flag = phase_3_band.get("calibration_source") or "gpt_calibrated"
    else:
      row_band_source = "naics_baseline"
      band_naics_code = (naics_band or {}).get("naics_code_used")
      band_naics_level = (naics_band or {}).get("naics_level_used")
      band_confidence = (naics_band or {}).get("confidence_tier")
      band_data_source = (naics_band or {}).get("data_source")
      band_trust_flag = (naics_band or {}).get("trust_flag")
      band_target = (naics_band or {}).get("benchmark_target")
      band_min = (naics_band or {}).get("benchmark_min")
      band_max = (naics_band or {}).get("benchmark_max")

    # No coverage — handle per gate_kind.
    no_coverage = (
      naics_band is None
      or band_trust_flag == "no_coverage"
      or (band_target is None and band_min is None and band_max is None)
    )
    if no_coverage and gate_kind == "skip_if_no_coverage":
      results.append(
        RealismCheckResult(
          metric_key=metric_key,
          finmo_line_label=finmo_label,
          derivation_formula_key=formula_key,
          quarter_aggregation=aggregation,
          quarter_index=None,
          actual_value=None,
          band_min=None,
          band_max=None,
          band_target=None,
          band_naics_code=None,
          band_naics_level=None,
          band_confidence_tier=None,
          band_data_source=None,
          band_trust_flag="no_coverage",
          tolerance_applied_bps=None,
          effective_min=None,
          effective_max=None,
          status="skipped",
          reason="no_naics_coverage_skip_per_row_policy",
          governs_lever_id=governs_lever,
          band_source=row_band_source,
          planning_mode_active=active_mode,
        )
      )
      continue

    tolerance_bps = _tolerance_bps_for_confidence(row, str(band_confidence or "")) if not no_coverage else None
    if tolerance_bps is None and not no_coverage:
      # The row's tolerance for this confidence tier is unset — skip rather
      # than fail noisily on a misconfigured row.
      results.append(
        RealismCheckResult(
          metric_key=metric_key,
          finmo_line_label=finmo_label,
          derivation_formula_key=formula_key,
          quarter_aggregation=aggregation,
          quarter_index=None,
          actual_value=None,
          band_min=_safe_float(band_min),
          band_max=_safe_float(band_max),
          band_target=_safe_float(band_target),
          band_naics_code=band_naics_code,
          band_naics_level=band_naics_level,
          band_confidence_tier=band_confidence,
          band_data_source=band_data_source,
          band_trust_flag=band_trust_flag,
          tolerance_applied_bps=None,
          effective_min=None,
          effective_max=None,
          status="skipped",
          reason=f"no_tolerance_bps_for_confidence_tier_{band_confidence}",
          governs_lever_id=governs_lever,
          band_source=row_band_source,
          planning_mode_active=active_mode,
        )
      )
      continue

    for q in quarter_indices:
      skip_reason = _applicability_skip(
        rule_key=row.get("applicability_rule_key"),
        business_naics_6=business_naics_6,
        ops_json=ops,
        financials_json=financials,
        finmo_json=finmo_json,
        quarter_index=q,
      )
      if skip_reason is not None:
        results.append(
          RealismCheckResult(
            metric_key=metric_key,
            finmo_line_label=finmo_label,
            derivation_formula_key=formula_key,
            quarter_aggregation=aggregation,
            quarter_index=q,
            actual_value=None,
            band_min=_safe_float(band_min),
            band_max=_safe_float(band_max),
            band_target=_safe_float(band_target),
            band_naics_code=band_naics_code,
            band_naics_level=band_naics_level,
            band_confidence_tier=band_confidence,
            band_data_source=band_data_source,
            band_trust_flag=band_trust_flag,
            tolerance_applied_bps=tolerance_bps,
            effective_min=None,
            effective_max=None,
            status="skipped",
            reason=skip_reason,
            governs_lever_id=governs_lever,
            band_source=row_band_source,
            planning_mode_active=active_mode,
          )
        )
        continue

      try:
        actual = evaluate_realism_formula(
          formula_key,
          model_input_json=model_input_json,
          finmo_json=finmo_json,
          quarter_index=q,
        )
      except Exception as exc:
        results.append(
          RealismCheckResult(
            metric_key=metric_key,
            finmo_line_label=finmo_label,
            derivation_formula_key=formula_key,
            quarter_aggregation=aggregation,
            quarter_index=q,
            actual_value=None,
            band_min=_safe_float(band_min),
            band_max=_safe_float(band_max),
            band_target=_safe_float(band_target),
            band_naics_code=band_naics_code,
            band_naics_level=band_naics_level,
            band_confidence_tier=band_confidence,
            band_data_source=band_data_source,
            band_trust_flag=band_trust_flag,
            tolerance_applied_bps=tolerance_bps,
            effective_min=None,
            effective_max=None,
            status="skipped",
            reason=f"formula_error:{type(exc).__name__}:{exc}",
            governs_lever_id=governs_lever,
            band_source=row_band_source,
            planning_mode_active=active_mode,
          )
        )
        continue
      if actual is None:
        results.append(
          RealismCheckResult(
            metric_key=metric_key,
            finmo_line_label=finmo_label,
            derivation_formula_key=formula_key,
            quarter_aggregation=aggregation,
            quarter_index=q,
            actual_value=None,
            band_min=_safe_float(band_min),
            band_max=_safe_float(band_max),
            band_target=_safe_float(band_target),
            band_naics_code=band_naics_code,
            band_naics_level=band_naics_level,
            band_confidence_tier=band_confidence,
            band_data_source=band_data_source,
            band_trust_flag=band_trust_flag,
            tolerance_applied_bps=tolerance_bps,
            effective_min=None,
            effective_max=None,
            status="skipped",
            reason="formula_returned_none",
            governs_lever_id=governs_lever,
            band_source=row_band_source,
            planning_mode_active=active_mode,
          )
        )
        continue

      # Pick band edges. Prefer (min, max); fall back to target +/- tolerance
      # alone when min/max are missing.
      effective_min = _safe_float(band_min)
      effective_max = _safe_float(band_max)
      if effective_min is None and band_target is not None:
        effective_min = float(band_target)
      if effective_max is None and band_target is not None:
        effective_max = float(band_target)
      if effective_min is None or effective_max is None:
        results.append(
          RealismCheckResult(
            metric_key=metric_key,
            finmo_line_label=finmo_label,
            derivation_formula_key=formula_key,
            quarter_aggregation=aggregation,
            quarter_index=q,
            actual_value=float(actual),
            band_min=_safe_float(band_min),
            band_max=_safe_float(band_max),
            band_target=_safe_float(band_target),
            band_naics_code=band_naics_code,
            band_naics_level=band_naics_level,
            band_confidence_tier=band_confidence,
            band_data_source=band_data_source,
            band_trust_flag=band_trust_flag,
            tolerance_applied_bps=tolerance_bps,
            effective_min=effective_min,
            effective_max=effective_max,
            status="skipped",
            reason="band_min_max_missing",
            governs_lever_id=governs_lever,
            band_source=row_band_source,
            planning_mode_active=active_mode,
          )
        )
        continue

      # Apply tolerance: convert bps to absolute. tolerance_bps is "around
      # the band edges" — i.e., 1500 bps = 0.15 absolute units (since these
      # metrics are already ratios). For days metrics (ar_days_dso, etc.),
      # tolerance_bps stays as bps but the metric's units are days, so a
      # 1500-bps tolerance on a 60-day target = 60 +/- 15 days. We use bps
      # as the absolute additive tolerance for ratio metrics, and as a
      # fraction-of-target tolerance otherwise.
      tolerance_units: float
      is_ratio_metric = bool(_metric_is_ratio(metric_key))
      if is_ratio_metric:
        tolerance_units = float(tolerance_bps or 0) / 10000.0
      else:
        # Days / count metrics — tolerance_bps interpreted as % of target.
        ref = float(band_target) if band_target is not None else (
          (float(effective_min) + float(effective_max)) / 2.0
        )
        tolerance_units = abs(ref) * (float(tolerance_bps or 0) / 10000.0)

      lower = float(effective_min) - tolerance_units
      upper = float(effective_max) + tolerance_units

      # Phase 6 Step 5 — apply planning_mode profitability floor for the
      # configured profitability metrics. The floor enforces a minimum
      # for the active mode/quarter; when the floor exceeds the band's
      # post-tolerance lower edge, it raises lower to the floor and the
      # band_source becomes "{prior_band_source}_with_planning_mode_floor".
      # When the floor is None for the active mode/quarter (e.g.,
      # turnaround Q1-Q10), the band is unchanged.
      effective_band_source = row_band_source
      planning_mode_floor: Optional[float] = None
      if metric_key in _PROFITABILITY_FLOOR_METRICS and active_policy is not None:
        floor = _profitability_floor_for_quarter(active_policy, q)
        if floor is not None and float(floor) > lower:
          lower = float(floor)
          planning_mode_floor = float(floor)
          effective_band_source = f"{row_band_source}_with_planning_mode_floor"

      in_band = lower <= float(actual) <= upper

      if in_band:
        status = "in_band"
        reason = ""
        derived_issue_code: Optional[str] = None
      else:
        below_band = float(actual) < lower
        # Phase 6 Step 5 — derive an issue code for below-band hits;
        # downgrade hard_fail to warn when the active planning_mode
        # tolerates that issue code.
        derived_issue_code = (
          _REALISM_METRIC_BELOW_BAND_TO_ISSUE_CODE.get(metric_key)
          if below_band else None
        )
        if (
          gate_kind == "hard_fail"
          and derived_issue_code is not None
          and derived_issue_code in tolerated_codes
        ):
          status = "out_of_band_warn"
          effective_band_source = (
            f"{effective_band_source}_tolerated_per_planning_mode"
          )
        else:
          status = "out_of_band_warn" if gate_kind == "warn" else "out_of_band_hard_fail"
        reason = (
          f"actual={float(actual):.6f} band=[{lower:.6f},{upper:.6f}] "
          f"target={(_safe_float(band_target) or 0.0):.6f} "
          f"tolerance_bps={tolerance_bps} confidence_tier={band_confidence} "
          f"naics_level_used={band_naics_level} band_source={effective_band_source}"
        )
        if planning_mode_floor is not None:
          reason += f" planning_mode_floor={planning_mode_floor:.6f}"
        if derived_issue_code is not None:
          reason += f" derived_issue_code={derived_issue_code}"

      result = RealismCheckResult(
        metric_key=metric_key,
        finmo_line_label=finmo_label,
        derivation_formula_key=formula_key,
        quarter_aggregation=aggregation,
        quarter_index=q,
        actual_value=float(actual),
        band_min=_safe_float(band_min),
        band_max=_safe_float(band_max),
        band_target=_safe_float(band_target),
        band_naics_code=band_naics_code,
        band_naics_level=band_naics_level,
        band_confidence_tier=band_confidence,
        band_data_source=band_data_source,
        band_trust_flag=band_trust_flag,
        tolerance_applied_bps=tolerance_bps,
        effective_min=lower,
        effective_max=upper,
        status=status,
        reason=reason,
        governs_lever_id=governs_lever,
        band_source=effective_band_source,
        planning_mode_floor_applied=planning_mode_floor,
        planning_mode_active=active_mode,
        tolerated_issue_code=(
          derived_issue_code
          if (status == "out_of_band_warn" and derived_issue_code in tolerated_codes)
          else None
        ),
      )
      results.append(result)

      if status == "out_of_band_hard_fail":
        message = (
          "post_intake_finalize_realism_band_violation: "
          f"metric={metric_key} {reason}"
        )
        if governs_lever:
          message += f" governs_lever={governs_lever}"
        if q is not None:
          message += f" quarter={q}"
        raise RealismBandViolation(message, results=results)

      if status == "out_of_band_warn":
        warnings_list.append(result.to_dict())

  return {
    "results": [r.to_dict() for r in results],
    "warnings": warnings_list,
    "warning_count": len(warnings_list),
    "checked_metric_count": len({r.metric_key for r in results}),
    "result_count": len(results),
  }


# ----------------------------------------------------------------------------
# Metric classification — ratio vs. days / count.
# ----------------------------------------------------------------------------


_RATIO_METRICS = {
  "cogs_percent_of_revenue",
  "gross_margin_percent",
  "marketing_percent_of_revenue",
  "advertising_percent_of_revenue",
  "payroll_percent_of_revenue",
  "effective_tax_rate",
  "ebitda_margin",
  "operating_margin_percent",
  "net_income_margin",
  "sga_percent_of_revenue",
  "rent_percent_of_revenue",
  "lease_percent_of_revenue",
  "occupancy_total_percent_of_revenue",
  "depreciation_percent_of_revenue",
  "stock_based_compensation_percent_of_revenue",
  "r_and_d_percent_of_revenue",
  "operating_cash_flow_margin",
  "capex_percent_of_revenue",
  "maintenance_capex_percent_of_revenue",
  "distributions_percent_of_net_income",
  "prepaid_expenses_percent_of_revenue",
  "deferred_revenue_percent_of_revenue",
  "ppe_percent_of_revenue",
  "owners_capital_percent_of_assets",
  "current_ratio",
  "quick_ratio",
  "debt_to_equity",
  "debt_to_assets",
  "total_assets_to_revenue",
}


def _metric_is_ratio(metric_key: str) -> bool:
  return str(metric_key or "").strip().lower() in _RATIO_METRICS
