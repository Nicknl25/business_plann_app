"""Module 3 Task 3.4 — `post_intake_finalize_realism_check_lookup` table.

DDL + idempotent migration + cached load + per-metric finder. The table
drives the finalize-stage realism gate (Task 3.6); each row says which
metric to check, which derivation formula computes the produced ratio,
which applicability rule gates it, and which tolerance + gate_kind apply.
"""

from __future__ import annotations

import json
import os
import threading
from functools import lru_cache
from typing import Any, Dict, List, Optional

from client_intake_and_finmo.intake_submission import get_mysql_connection


REALISM_CHECK_TABLE_NAME = "post_intake_finalize_realism_check_lookup"

# Phase 9 Phase D adds "trajectory_check" for viability timeline checks
# (Q5-Q11 recovery trend, Q11+ no-relapse, etc.) where the validator
# evaluates a per-quarter sequence rather than a single ratio.
#
# Phase 9 audit Bucket B adds "per_year_aggregate" — a row with this
# aggregation runs 5 times (Y1..Y5), each spanning 4 quarters, so
# Y2..Y5 drift on tax rate / capex / distributions / capital structure
# is no longer invisible. year_one_aggregate is preserved for back-compat.
_QUARTER_AGGREGATIONS = {
  "per_quarter",
  "year_one_aggregate",
  "per_year_aggregate",
  "horizon_average",
  "trajectory_check",
}
_GATE_KINDS = {"hard_fail", "warn", "skip_if_no_coverage"}

# Phase 9 Phase D — adaptation family vocabulary. Mirrors
# post_intake_adaptive_planning.policy.ADAPTATION_FAMILIES so the
# issue router can resolve metric → family lookups deterministically.
_ADAPTATION_FAMILIES = {
  "ramp_adaptation",
  "turnaround_recovery_q5_q11",
  "industry_normalization",
  "operating_scale_adaptation",
  "funding_adaptation",
  "balance_sheet_adaptation",
  "schedule_adaptation",
  "revenue_achievability",
  "payroll_ratio_excess",
  "leverage_excess",
  "capital_intensity_adaptation",
  "margin_compression",
}

_ENSURE_TABLE_READY = False
_ENSURE_TABLE_LOCK = threading.Lock()
_ENV_LOADED_LOCK = threading.Lock()


def _ensure_env_loaded() -> None:
  if os.getenv("MYSQL_HOST") and os.getenv("MYSQL_USER") and (
    os.getenv("MYSQL_DB") or os.getenv("MYSQL_DATABASE")
  ):
    return
  env_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env")
  )
  if not os.path.exists(env_path):
    return
  with _ENV_LOADED_LOCK:
    try:
      with open(env_path, "r", encoding="utf-8") as handle:
        for line in handle:
          stripped = line.strip()
          if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
          key, value = stripped.split("=", 1)
          os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except Exception:
      return


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


def _ensure_realism_check_lookup_table(conn) -> None:
  global _ENSURE_TABLE_READY
  if _ENSURE_TABLE_READY:
    return
  with _ENSURE_TABLE_LOCK:
    if _ENSURE_TABLE_READY:
      return
    cur = conn.cursor()
    try:
      # Phase 6 Step 11: drop the orphaned ppe_percent_of_revenue row
      # from existing deployments. PPE has no editable remediation
      # lever (Capex schedule is python_derived), so the metric isn't
      # cascade-recoverable; removed from the realism table. Idempotent.
      try:
        cur.execute(
          f"DELETE FROM {REALISM_CHECK_TABLE_NAME} WHERE metric_key = 'ppe_percent_of_revenue'"
        )
      except Exception:
        pass
      cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {REALISM_CHECK_TABLE_NAME} (
          id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
          metric_key VARCHAR(128) NOT NULL,
          finmo_line_label VARCHAR(128) NOT NULL,
          derivation_formula_key VARCHAR(128) NOT NULL,
          quarter_aggregation VARCHAR(32) NOT NULL,
          applicability_rule_key VARCHAR(64) NULL,
          tolerance_bps_high_confidence INT NOT NULL,
          tolerance_bps_medium_confidence INT NOT NULL,
          tolerance_bps_low_confidence INT NOT NULL,
          tolerance_bps_generic_default INT NULL,
          gate_kind VARCHAR(32) NOT NULL,
          governs_model_input_lever_id VARCHAR(128) NULL,
          issue_family VARCHAR(64) NULL,
          remediation_family VARCHAR(64) NULL,
          primary_levers TEXT NULL,
          secondary_levers TEXT NULL,
          stage_sensitivity TEXT NULL,
          deadline_quarter TINYINT UNSIGNED NULL,
          notes LONGTEXT NULL,
          active TINYINT(1) NOT NULL DEFAULT 1,
          created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
          UNIQUE KEY uniq_realism_check_metric_aggregation (metric_key, quarter_aggregation),
          KEY idx_realism_check_active (active),
          KEY idx_realism_check_gate_kind (gate_kind),
          KEY idx_realism_check_issue_family (issue_family),
          KEY idx_realism_check_remediation_family (remediation_family)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
      )
      # Phase 9 Phase D — idempotent ALTER TABLE for already-deployed
      # databases. Add the doctrine metadata columns if they are not
      # already present. Each ADD COLUMN runs in its own try/except so
      # MySQL's "Duplicate column name" error doesn't abort the others.
      _phase9_d_columns = (
        ("issue_family", "VARCHAR(64) NULL"),
        ("remediation_family", "VARCHAR(64) NULL"),
        ("primary_levers", "TEXT NULL"),
        ("secondary_levers", "TEXT NULL"),
        ("stage_sensitivity", "TEXT NULL"),
        ("deadline_quarter", "TINYINT UNSIGNED NULL"),
      )
      for column_name, column_decl in _phase9_d_columns:
        try:
          cur.execute(
            f"ALTER TABLE {REALISM_CHECK_TABLE_NAME} ADD COLUMN {column_name} {column_decl}"
          )
        except Exception:
          # Column already exists or other ALTER failure — ignore.
          pass
      for index_name, index_column in (
        ("idx_realism_check_issue_family", "issue_family"),
        ("idx_realism_check_remediation_family", "remediation_family"),
      ):
        try:
          cur.execute(
            f"ALTER TABLE {REALISM_CHECK_TABLE_NAME} ADD KEY {index_name} ({index_column})"
          )
        except Exception:
          pass
      for row in _DEFAULT_REALISM_CHECK_ROWS:
        primary_levers = row.get("primary_levers") or []
        secondary_levers = row.get("secondary_levers") or []
        stage_sensitivity = row.get("stage_sensitivity") or {}
        cur.execute(
          f"""
          INSERT INTO {REALISM_CHECK_TABLE_NAME} (
            metric_key,
            finmo_line_label,
            derivation_formula_key,
            quarter_aggregation,
            applicability_rule_key,
            tolerance_bps_high_confidence,
            tolerance_bps_medium_confidence,
            tolerance_bps_low_confidence,
            tolerance_bps_generic_default,
            gate_kind,
            governs_model_input_lever_id,
            issue_family,
            remediation_family,
            primary_levers,
            secondary_levers,
            stage_sensitivity,
            deadline_quarter,
            notes,
            active
          ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
          ON DUPLICATE KEY UPDATE
            finmo_line_label = VALUES(finmo_line_label),
            derivation_formula_key = VALUES(derivation_formula_key),
            applicability_rule_key = VALUES(applicability_rule_key),
            tolerance_bps_high_confidence = VALUES(tolerance_bps_high_confidence),
            tolerance_bps_medium_confidence = VALUES(tolerance_bps_medium_confidence),
            tolerance_bps_low_confidence = VALUES(tolerance_bps_low_confidence),
            tolerance_bps_generic_default = VALUES(tolerance_bps_generic_default),
            gate_kind = VALUES(gate_kind),
            governs_model_input_lever_id = VALUES(governs_model_input_lever_id),
            issue_family = VALUES(issue_family),
            remediation_family = VALUES(remediation_family),
            primary_levers = VALUES(primary_levers),
            secondary_levers = VALUES(secondary_levers),
            stage_sensitivity = VALUES(stage_sensitivity),
            deadline_quarter = VALUES(deadline_quarter),
            notes = VALUES(notes),
            active = VALUES(active)
          """,
          (
            _clean_text(row.get("metric_key")),
            _clean_text(row.get("finmo_line_label")),
            _clean_text(row.get("derivation_formula_key")),
            _clean_text(row.get("quarter_aggregation")),
            _clean_text(row.get("applicability_rule_key")) or None,
            int(row.get("tolerance_bps_high_confidence") or 0),
            int(row.get("tolerance_bps_medium_confidence") or 0),
            int(row.get("tolerance_bps_low_confidence") or 0),
            int(row["tolerance_bps_generic_default"]) if row.get("tolerance_bps_generic_default") is not None else None,
            _clean_text(row.get("gate_kind")) or "warn",
            _clean_text(row.get("governs_model_input_lever_id")) or None,
            _clean_text(row.get("issue_family")) or None,
            _clean_text(row.get("remediation_family")) or None,
            json.dumps(primary_levers) if primary_levers else None,
            json.dumps(secondary_levers) if secondary_levers else None,
            json.dumps(stage_sensitivity) if stage_sensitivity else None,
            int(row["deadline_quarter"]) if row.get("deadline_quarter") is not None else None,
            _clean_text(row.get("notes")) or None,
            1 if row.get("active", True) else 0,
          ),
        )
      conn.commit()
      _ENSURE_TABLE_READY = True
    finally:
      try:
        cur.close()
      except Exception:
        pass


# ----------------------------------------------------------------------------
# Default rows — initial set populated on first ensure. Module 3 v2 starts
# with 10 high-impact metrics in warn-mode. Module 3 v3 expands to the full
# ~30-row sweep from master-diagnostic Part 6.1 and considers promotion to
# hard_fail per Task 3.9.
#
# Tolerance choices follow the master-diagnostic Phase 4 recommendation:
#   high   : +/- 1500 bps (15pp around target)
#   medium : +/- 2500 bps
#   low    : +/- 4000 bps
#   generic_default : NULL (skip the check) for ratio metrics where the
#                     universal default is too coarse to be useful;
#                     looser tolerance (5000 bps) when the universal
#                     default is still informative.
# ----------------------------------------------------------------------------

def _row(
  *,
  metric_key: str,
  finmo_line_label: str,
  derivation_formula_key: str,
  quarter_aggregation: str = "per_quarter",
  applicability_rule_key: Optional[str] = None,
  tolerance_bps_high_confidence: int,
  tolerance_bps_medium_confidence: int,
  tolerance_bps_low_confidence: int,
  tolerance_bps_generic_default: Optional[int] = None,
  gate_kind: str = "warn",
  governs_model_input_lever_id: Optional[str] = None,
  issue_family: Optional[str] = None,
  remediation_family: Optional[str] = None,
  primary_levers: Optional[List[str]] = None,
  secondary_levers: Optional[List[str]] = None,
  stage_sensitivity: Optional[Dict[str, float]] = None,
  deadline_quarter: Optional[int] = None,
  notes: str = "",
  active: bool = True,
) -> Dict[str, Any]:
  return {
    "metric_key": metric_key,
    "finmo_line_label": finmo_line_label,
    "derivation_formula_key": derivation_formula_key,
    "quarter_aggregation": quarter_aggregation,
    "applicability_rule_key": applicability_rule_key,
    "tolerance_bps_high_confidence": tolerance_bps_high_confidence,
    "tolerance_bps_medium_confidence": tolerance_bps_medium_confidence,
    "tolerance_bps_low_confidence": tolerance_bps_low_confidence,
    "tolerance_bps_generic_default": tolerance_bps_generic_default,
    "gate_kind": gate_kind,
    "governs_model_input_lever_id": governs_model_input_lever_id,
    "issue_family": issue_family,
    "remediation_family": remediation_family,
    "primary_levers": list(primary_levers) if primary_levers else None,
    "secondary_levers": list(secondary_levers) if secondary_levers else None,
    "stage_sensitivity": dict(stage_sensitivity) if stage_sensitivity else None,
    "deadline_quarter": deadline_quarter,
    "notes": notes,
    "active": active,
  }


# Phase 9 Phase D — stage tolerance multipliers.
#
# When a metric is out-of-band, the multiplier widens the tolerance for
# stage-appropriate cases (startups can absorb more deviation; mature
# businesses get tighter expectations). Used by the issue router to
# decide severity (adaptation_required vs stage_tolerable).
_STAGE_SENSITIVITY_PROFITABILITY = {
  # Startups can be deeply unprofitable through the loss window;
  # mature businesses must be near-industry steady state.
  "startup": 3.0,
  "early": 2.0,
  "operational": 1.2,
  "mature": 0.8,
}
_STAGE_SENSITIVITY_RAMP_LIGHT = {
  # Marketing %, R&D %, G&A % — startups invest more, mature less.
  "startup": 1.5,
  "early": 1.3,
  "operational": 1.0,
  "mature": 0.9,
}
_STAGE_SENSITIVITY_RAMP_HEAVY = {
  # Payroll, capacity-driven costs — startups ramp slowly.
  "startup": 1.6,
  "early": 1.3,
  "operational": 1.0,
  "mature": 0.9,
}
_STAGE_SENSITIVITY_LEVERAGE = {
  # Startups carry higher D/E, mature must steady.
  "startup": 2.0,
  "early": 1.5,
  "operational": 1.0,
  "mature": 0.8,
}
_STAGE_SENSITIVITY_FLAT = {
  "startup": 1.0,
  "early": 1.0,
  "operational": 1.0,
  "mature": 1.0,
}


# Module 3 v3 default tolerances. Two profiles, by metric kind:
#   ratio metrics — tighter band (real industry data is already a tight band;
#                   tolerance is the noise envelope around it)
#   days metrics — looser (days metric tolerance is interpreted as % of
#                  target days inside the validator)
#
# Promotion to hard_fail: high-confidence ratio metrics with NAICS-6/5/4
# coverage AND `confidence_tier IN (high, medium)` go to hard_fail. Universal
# liquidity ratios (current_ratio, quick_ratio) and workforce metrics with
# known coverage gaps stay at warn. Generic-default-only rows skip when no
# meaningful tolerance is configured.
#
# Tier-based promotion follows master-diagnostic Phase 4 guidance.

_RATIO_TOL_HIGH = 700      # 7pp tolerance on real NAICS ratio bands
_RATIO_TOL_MEDIUM = 1200   # 12pp
_RATIO_TOL_LOW = 2000      # 20pp
_RATIO_TOL_GENERIC = 3000  # 30pp; conservative skip-or-warn at L0

_DAYS_TOL_HIGH = 2000      # 20% of target (e.g. 12 days on a 60-day band)
_DAYS_TOL_MEDIUM = 3500    # 35%
_DAYS_TOL_LOW = 5000       # 50%
_DAYS_TOL_GENERIC = None   # skip generic-default for days metrics

_DEFAULT_REALISM_CHECK_ROWS: List[Dict[str, Any]] = [
  # ============================================================
  # P&L (per_quarter, ratio metrics)
  # ============================================================
  _row(
    metric_key="cogs_percent_of_revenue",
    finmo_line_label="Cost of Goods Sold",
    derivation_formula_key="cogs_dollars_div_revenue_dollars",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="hard_fail",
    governs_model_input_lever_id="expenses::Cost of Goods Sold",
    issue_family="margin_compression",
    remediation_family="margin_compression",
    primary_levers=["expenses::Cost of Goods Sold"],
    secondary_levers=["revenue::Unit Price"],
    stage_sensitivity=_STAGE_SENSITIVITY_FLAT,
    deadline_quarter=11,
    notes="Per-quarter COGS / revenue. Strong NAICS coverage (n=1,686). Promoted to hard_fail in v3 — high-confidence metric with broad NAICS-6/5/4 coverage.",
  ),
  _row(
    metric_key="gross_margin_percent",
    finmo_line_label="Gross Profit",
    derivation_formula_key="gross_margin_div_revenue",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="hard_fail",
    governs_model_input_lever_id="expenses::Cost of Goods Sold",
    issue_family="margin_compression",
    remediation_family="margin_compression",
    primary_levers=["expenses::Cost of Goods Sold", "revenue::Unit Price"],
    secondary_levers=[],
    stage_sensitivity=_STAGE_SENSITIVITY_FLAT,
    deadline_quarter=11,
    notes="(Revenue - COGS) / revenue. Cross-check on COGS; warn-mode because hard_fail on COGS already catches the same condition.",
  ),
  _row(
    metric_key="marketing_percent_of_revenue",
    finmo_line_label="Marketing",
    derivation_formula_key="marketing_dollars_div_revenue_dollars",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="hard_fail",
    governs_model_input_lever_id="expenses::Marketing",
    issue_family="industry_normalization",
    remediation_family="industry_normalization",
    primary_levers=["expenses::Marketing"],
    secondary_levers=["expenses::General & Administrative"],
    stage_sensitivity=_STAGE_SENSITIVITY_RAMP_LIGHT,
    deadline_quarter=11,
    notes="SEC EDGAR-backed for many NAICS (n=421). Stays at warn until Module 6 marketing schedule replaces this metric's authority entirely.",
  ),
  _row(
    metric_key="advertising_percent_of_revenue",
    finmo_line_label="Marketing",
    derivation_formula_key="advertising_dollars_div_revenue_dollars",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="skip_if_no_coverage",
    issue_family="industry_normalization",
    remediation_family="industry_normalization",
    primary_levers=["expenses::Marketing"],
    secondary_levers=[],
    stage_sensitivity=_STAGE_SENSITIVITY_RAMP_LIGHT,
    deadline_quarter=11,
    notes="FINMO does not split advertising from marketing today; the formula returns None to skip cleanly. Active row reserved for the future split.",
  ),
  _row(
    metric_key="r_and_d_percent_of_revenue",
    finmo_line_label="Research and Development",
    derivation_formula_key="r_and_d_dollars_div_revenue_dollars",
    applicability_rule_key="r_and_d_when_applicable",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="hard_fail",
    governs_model_input_lever_id="expenses::Research & Development",
    issue_family="industry_normalization",
    remediation_family="industry_normalization",
    primary_levers=["expenses::Research & Development"],
    secondary_levers=["expenses::General & Administrative"],
    stage_sensitivity=_STAGE_SENSITIVITY_RAMP_LIGHT,
    deadline_quarter=11,
    notes="Skip when r_and_d_applicability disabled the lever; otherwise compare R&D / revenue against NAICS band.",
  ),
  _row(
    metric_key="rent_percent_of_revenue",
    finmo_line_label="Lease",
    derivation_formula_key="lease_rent_dollars_div_revenue_dollars",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="hard_fail",
    governs_model_input_lever_id="expenses::Lease",
    issue_family="operating_scale_adaptation",
    remediation_family="operating_scale_adaptation",
    primary_levers=["revenue::Unit Price", "revenue::Capacity", "revenue::Utilization"],
    secondary_levers=["expenses::Lease"],
    stage_sensitivity=_STAGE_SENSITIVITY_RAMP_HEAVY,
    deadline_quarter=11,
    notes="FINMO emits a single `lease_rent` line; the realism check uses rent_percent_of_revenue band as the comparison.",
  ),
  _row(
    metric_key="sga_percent_of_revenue",
    finmo_line_label="General and Administrative",
    derivation_formula_key="sga_dollars_div_revenue_dollars",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="hard_fail",
    governs_model_input_lever_id="expenses::General & Administrative",
    issue_family="industry_normalization",
    remediation_family="industry_normalization",
    primary_levers=["expenses::General & Administrative"],
    secondary_levers=["expenses::Marketing"],
    stage_sensitivity=_STAGE_SENSITIVITY_RAMP_LIGHT,
    deadline_quarter=11,
    notes="Marketing + G&A combined per industry_metrics_raw SGA convention.",
  ),
  _row(
    metric_key="payroll_percent_of_revenue",
    finmo_line_label="Payroll",
    derivation_formula_key="payroll_dollars_div_revenue_dollars",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="hard_fail",
    governs_model_input_lever_id="expenses::Payroll",
    issue_family="payroll_ratio_excess",
    remediation_family="payroll_ratio_excess",
    primary_levers=["expenses::Payroll"],
    secondary_levers=["revenue::Capacity", "revenue::Utilization"],
    stage_sensitivity=_STAGE_SENSITIVITY_RAMP_HEAVY,
    deadline_quarter=11,
    notes="Reasonableness signal only — payroll is NOT clipped to fit revenue (Golden Rule preservation). Stays at warn because payroll/revenue NAICS coverage is uneven; out-of-band surfaces likely wage_positioning / labor_intensity_class mismatch.",
  ),
  _row(
    metric_key="depreciation_percent_of_revenue",
    finmo_line_label="Depreciation",
    derivation_formula_key="depreciation_dollars_div_revenue_dollars",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="hard_fail",
    governs_model_input_lever_id="expenses::Depreciation",
    issue_family="capital_intensity_adaptation",
    remediation_family="capital_intensity_adaptation",
    primary_levers=["schedules::Capital Expenditures"],
    secondary_levers=[],
    stage_sensitivity=_STAGE_SENSITIVITY_FLAT,
    deadline_quarter=20,
    notes="Depreciation / revenue. Cross-check on capex schedule and PPE.",
  ),
  _row(
    metric_key="effective_tax_rate",
    finmo_line_label="Taxes",
    derivation_formula_key="taxes_div_pretax_income_per_year",
    quarter_aggregation="per_year_aggregate",
    applicability_rule_key="skip_when_pretax_income_nonpositive",
    tolerance_bps_high_confidence=500,
    tolerance_bps_medium_confidence=1000,
    tolerance_bps_low_confidence=2000,
    tolerance_bps_generic_default=3000,
    gate_kind="hard_fail",
    governs_model_input_lever_id="expenses::Taxes",
    issue_family="industry_normalization",
    remediation_family="industry_normalization",
    primary_levers=["expenses::Taxes"],
    secondary_levers=[],
    stage_sensitivity=_STAGE_SENSITIVITY_FLAT,
    deadline_quarter=20,
    notes="Per-year aggregate (Y1..Y5). Each year's tax rate is taxes/pretax_income summed over that year's 4 quarters; a year with non-positive pretax_income is skipped per applicability rule. Phase 9 audit Bucket B promoted from year_one_aggregate so Y2..Y5 tax drift is visible. n=1,519 IRS_SOI rows; out-of-band tax rate signals tax-loss-carry-forward or model error.",
  ),
  _row(
    metric_key="ebitda_margin",
    finmo_line_label="EBITDA",
    derivation_formula_key="ebitda_div_revenue",
    applicability_rule_key="skip_when_revenue_zero",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="hard_fail",
    governs_model_input_lever_id="expenses::Cost of Goods Sold",
    issue_family="turnaround_recovery_q5_q11",
    remediation_family="turnaround_recovery_q5_q11",
    primary_levers=[
      "expenses::Cost of Goods Sold",
      "expenses::Marketing",
      "expenses::General & Administrative",
      "expenses::Payroll",
      "revenue::Unit Price",
      "revenue::Utilization",
    ],
    secondary_levers=["revenue::Capacity"],
    stage_sensitivity=_STAGE_SENSITIVITY_PROFITABILITY,
    deadline_quarter=11,
    notes=(
      "EBITDA / revenue. Promoted back to hard_fail in Phase 4 — the "
      "target-seeking solver now lands EBITDA in band by construction: "
      "the Phase 3 target-shaping consultant calibrates EBITDA target "
      "ranges to the business stage (early-stage / runway-focused / "
      "bootstrapped-profitable), the outer loop tweaks drivers to land "
      "EBITDA within those calibrated ranges, and the Phase 3.7 "
      "adaptation cascade widens tolerances when the original calibration "
      "is too tight. A residual hard_fail at finalize is a real solver "
      "bug, not launch-quarter volatility."
    ),
  ),
  _row(
    metric_key="operating_margin_percent",
    finmo_line_label="Operating Income",
    derivation_formula_key="operating_margin_div_revenue",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="hard_fail",
    issue_family="turnaround_recovery_q5_q11",
    remediation_family="turnaround_recovery_q5_q11",
    primary_levers=[
      "expenses::Cost of Goods Sold",
      "expenses::Marketing",
      "expenses::General & Administrative",
      "revenue::Unit Price",
    ],
    secondary_levers=["expenses::Depreciation"],
    stage_sensitivity=_STAGE_SENSITIVITY_PROFITABILITY,
    deadline_quarter=11,
    notes="(EBITDA - depreciation) / revenue. Warn-mode because EBITDA hard_fail already catches the upstream condition.",
  ),
  _row(
    metric_key="net_income_margin",
    finmo_line_label="Net Income",
    derivation_formula_key="net_income_div_revenue",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="hard_fail",
    issue_family="turnaround_recovery_q5_q11",
    remediation_family="turnaround_recovery_q5_q11",
    primary_levers=[
      "expenses::Cost of Goods Sold",
      "expenses::Marketing",
      "expenses::General & Administrative",
      "revenue::Unit Price",
    ],
    secondary_levers=["schedules::Debt Issuance (New Borrowing)"],
    stage_sensitivity=_STAGE_SENSITIVITY_PROFITABILITY,
    deadline_quarter=11,
    notes="Net income / revenue. Warn-mode — downstream of EBITDA / interest / taxes which are individually gated.",
  ),

  # ============================================================
  # Balance sheet (per_quarter mostly, days metrics + ratios)
  # ============================================================
  _row(
    metric_key="ar_days_dso",
    finmo_line_label="Accounts Receivable Days",
    derivation_formula_key="ar_days_from_balance_and_revenue",
    applicability_rule_key="skip_when_revenue_zero",
    tolerance_bps_high_confidence=_DAYS_TOL_HIGH,
    tolerance_bps_medium_confidence=_DAYS_TOL_MEDIUM,
    tolerance_bps_low_confidence=_DAYS_TOL_LOW,
    tolerance_bps_generic_default=_DAYS_TOL_GENERIC,
    gate_kind="hard_fail",
    governs_model_input_lever_id="balance_sheet::Accounts Receivable Days",
    issue_family="balance_sheet_adaptation",
    remediation_family="balance_sheet_adaptation",
    primary_levers=["balance_sheet::Accounts Receivable Days"],
    secondary_levers=[],
    stage_sensitivity=_STAGE_SENSITIVITY_RAMP_HEAVY,
    deadline_quarter=20,
    notes="AR / revenue * 90. Strong NAICS coverage. Promoted to hard_fail.",
  ),
  _row(
    metric_key="ap_days_dpo",
    finmo_line_label="Accounts Payable Days",
    derivation_formula_key="ap_days_from_balance_and_expenses",
    applicability_rule_key="skip_when_operating_expense_zero",
    tolerance_bps_high_confidence=_DAYS_TOL_HIGH,
    tolerance_bps_medium_confidence=_DAYS_TOL_MEDIUM,
    tolerance_bps_low_confidence=_DAYS_TOL_LOW,
    tolerance_bps_generic_default=_DAYS_TOL_GENERIC,
    gate_kind="hard_fail",
    governs_model_input_lever_id="balance_sheet::Accounts Payable Days",
    issue_family="balance_sheet_adaptation",
    remediation_family="balance_sheet_adaptation",
    primary_levers=["balance_sheet::Accounts Payable Days"],
    secondary_levers=[],
    stage_sensitivity=_STAGE_SENSITIVITY_RAMP_HEAVY,
    deadline_quarter=20,
    notes="AP / operating_expense_base * 90. Promoted to hard_fail.",
  ),
  _row(
    metric_key="inventory_days",
    finmo_line_label="Inventory Days",
    derivation_formula_key="inventory_days_from_balance_and_cogs",
    applicability_rule_key="inventory_when_business_has_inventory",
    tolerance_bps_high_confidence=_DAYS_TOL_HIGH,
    tolerance_bps_medium_confidence=_DAYS_TOL_MEDIUM,
    tolerance_bps_low_confidence=_DAYS_TOL_LOW,
    tolerance_bps_generic_default=_DAYS_TOL_GENERIC,
    gate_kind="hard_fail",
    governs_model_input_lever_id="balance_sheet::Inventory Days",
    issue_family="balance_sheet_adaptation",
    remediation_family="balance_sheet_adaptation",
    primary_levers=["balance_sheet::Inventory Days"],
    secondary_levers=[],
    stage_sensitivity=_STAGE_SENSITIVITY_RAMP_HEAVY,
    deadline_quarter=20,
    notes="Inventory / COGS * 90. Applicability gate skips for software / professional services NAICS-2. Stays at warn pending empirical sweep on inventory-heavy businesses.",
  ),
  _row(
    metric_key="prepaid_expenses_percent_of_revenue",
    finmo_line_label="Prepaid Expenses",
    derivation_formula_key="prepaid_expenses_dollars_div_revenue_dollars",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="hard_fail",
    governs_model_input_lever_id="balance_sheet::Prepaid Expenses (% of Revenue)",
    issue_family="balance_sheet_adaptation",
    remediation_family="balance_sheet_adaptation",
    primary_levers=["balance_sheet::Prepaid Expenses (% of Revenue)"],
    secondary_levers=[],
    stage_sensitivity=_STAGE_SENSITIVITY_FLAT,
    deadline_quarter=20,
    notes="Prepaid / revenue. SEC EDGAR-backed (n=827).",
  ),
  _row(
    metric_key="deferred_revenue_percent_of_revenue",
    finmo_line_label="Deferred Revenue",
    derivation_formula_key="deferred_revenue_dollars_div_revenue_dollars",
    applicability_rule_key="deferred_revenue_when_business_has_recurring",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="hard_fail",
    governs_model_input_lever_id="balance_sheet::Deferred Revenue (% of Revenue)",
    issue_family="balance_sheet_adaptation",
    remediation_family="balance_sheet_adaptation",
    primary_levers=["balance_sheet::Deferred Revenue (% of Revenue)"],
    secondary_levers=[],
    stage_sensitivity=_STAGE_SENSITIVITY_FLAT,
    deadline_quarter=20,
    notes="Deferred revenue / revenue. SEC EDGAR-backed (n=745). Applicability gate skips for retail / accommodation / personal-services NAICS-2 sectors.",
  ),
  _row(
    metric_key="total_assets_to_revenue",
    finmo_line_label="Total Assets",
    derivation_formula_key="total_assets_div_revenue_per_year",
    quarter_aggregation="per_year_aggregate",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="hard_fail",
    issue_family="capital_intensity_adaptation",
    remediation_family="capital_intensity_adaptation",
    primary_levers=["revenue::Capacity", "schedules::Capital Expenditures"],
    secondary_levers=["balance_sheet::Owner's Capital"],
    stage_sensitivity=_STAGE_SENSITIVITY_FLAT,
    deadline_quarter=20,
    notes="Per-year (Y1..Y5) end-of-year total assets / sum-of-year revenue. Cross-check on BS-vs-P&L scale (master-diagnostic Part 9.2). Phase 9 audit Bucket B promoted from year_one_aggregate; pre-fix the formula returned None for year_one_aggregate (it required a quarter_index) so the metric was silently skipped every run.",
  ),
  _row(
    metric_key="owners_capital_percent_of_assets",
    finmo_line_label="Owner's Capital",
    derivation_formula_key="owners_capital_div_total_assets_per_year",
    quarter_aggregation="per_year_aggregate",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="hard_fail",
    governs_model_input_lever_id="balance_sheet::Owner's Capital",
    issue_family="leverage_excess",
    remediation_family="leverage_excess",
    primary_levers=["balance_sheet::Owner's Capital", "schedules::Debt Issuance (New Borrowing)"],
    secondary_levers=["balance_sheet::Other Equity"],
    stage_sensitivity=_STAGE_SENSITIVITY_FLAT,
    deadline_quarter=20,
    notes="Per-year (Y1..Y5) end-of-year equity / total assets. Capital-structure cross-check. Phase 9 audit Bucket B promoted from year_one_aggregate; pre-fix the formula was silently skipped (see total_assets_to_revenue note).",
  ),
  _row(
    metric_key="current_ratio",
    finmo_line_label="Current Ratio",
    derivation_formula_key="current_ratio",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=None,
    gate_kind="hard_fail",
    issue_family="balance_sheet_adaptation",
    remediation_family="balance_sheet_adaptation",
    primary_levers=[
      "balance_sheet::Accounts Receivable Days",
      "balance_sheet::Accounts Payable Days",
      "balance_sheet::Inventory Days",
    ],
    secondary_levers=["schedules::Debt Issuance (New Borrowing)"],
    stage_sensitivity=_STAGE_SENSITIVITY_FLAT,
    deadline_quarter=20,
    notes="Current assets / current liabilities. Universal liquidity sanity — stays warn-only because NAICS variation is weak.",
  ),
  _row(
    metric_key="quick_ratio",
    finmo_line_label="Quick Ratio",
    derivation_formula_key="quick_ratio",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=None,
    gate_kind="hard_fail",
    issue_family="balance_sheet_adaptation",
    remediation_family="balance_sheet_adaptation",
    primary_levers=[
      "balance_sheet::Accounts Receivable Days",
      "balance_sheet::Accounts Payable Days",
    ],
    secondary_levers=["schedules::Debt Issuance (New Borrowing)"],
    stage_sensitivity=_STAGE_SENSITIVITY_FLAT,
    deadline_quarter=20,
    notes="(Current assets - inventory) / current liabilities. Same as current_ratio but more conservative.",
  ),
  _row(
    metric_key="debt_to_equity",
    finmo_line_label="Debt to Equity",
    derivation_formula_key="total_debt_div_total_equity",
    applicability_rule_key="skip_when_debt_zero",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="hard_fail",
    issue_family="leverage_excess",
    remediation_family="leverage_excess",
    primary_levers=["schedules::Debt Issuance (New Borrowing)", "balance_sheet::Owner's Capital"],
    secondary_levers=["balance_sheet::Distributions"],
    stage_sensitivity=_STAGE_SENSITIVITY_LEVERAGE,
    deadline_quarter=20,
    notes="(Short + long term debt) / total equity. Skip when total debt is zero.",
  ),
  _row(
    metric_key="debt_to_assets",
    finmo_line_label="Debt to Assets",
    derivation_formula_key="total_debt_div_total_assets",
    applicability_rule_key="skip_when_debt_zero",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="hard_fail",
    issue_family="leverage_excess",
    remediation_family="leverage_excess",
    primary_levers=["schedules::Debt Issuance (New Borrowing)", "balance_sheet::Owner's Capital"],
    secondary_levers=["balance_sheet::Distributions"],
    stage_sensitivity=_STAGE_SENSITIVITY_LEVERAGE,
    deadline_quarter=20,
    notes="Total debt / total assets.",
  ),

  # ============================================================
  # Cash flow (mostly year_one_aggregate where signed-quarter noise hurts)
  # ============================================================
  _row(
    metric_key="operating_cash_flow_margin",
    finmo_line_label="Operating Cash Flow",
    derivation_formula_key="operating_cash_flow_div_revenue",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="hard_fail",
    issue_family="turnaround_recovery_q5_q11",
    remediation_family="turnaround_recovery_q5_q11",
    primary_levers=[
      "expenses::Cost of Goods Sold",
      "expenses::Marketing",
      "expenses::General & Administrative",
      "balance_sheet::Accounts Receivable Days",
    ],
    secondary_levers=["revenue::Unit Price"],
    stage_sensitivity=_STAGE_SENSITIVITY_PROFITABILITY,
    deadline_quarter=11,
    notes="Operating CF / revenue. SEC EDGAR-backed (n=555).",
  ),
  _row(
    metric_key="capex_percent_of_revenue",
    finmo_line_label="Capital Expenditures",
    derivation_formula_key="capex_div_revenue_per_year",
    quarter_aggregation="per_year_aggregate",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="hard_fail",
    governs_model_input_lever_id="schedules::Capital Expenditures",
    issue_family="capital_intensity_adaptation",
    remediation_family="capital_intensity_adaptation",
    primary_levers=["schedules::Capital Expenditures"],
    secondary_levers=["revenue::Capacity"],
    stage_sensitivity=_STAGE_SENSITIVITY_FLAT,
    deadline_quarter=20,
    notes="Per-year (Y1..Y5) capex / revenue. Cross-check on PPE buildup. Phase 9 audit Bucket B promoted from year_one_aggregate so Y2..Y5 capex bursts are visible.",
  ),
  _row(
    metric_key="distributions_percent_of_net_income",
    finmo_line_label="Distributions",
    derivation_formula_key="distributions_div_net_income_per_year",
    quarter_aggregation="per_year_aggregate",
    applicability_rule_key="skip_when_distributions_zero",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="hard_fail",
    governs_model_input_lever_id="balance_sheet::Distributions",
    issue_family="funding_adaptation",
    remediation_family="funding_adaptation",
    primary_levers=["balance_sheet::Distributions"],
    secondary_levers=["schedules::Debt Issuance (New Borrowing)"],
    stage_sensitivity=_STAGE_SENSITIVITY_FLAT,
    deadline_quarter=20,
    notes="Per-year (Y1..Y5) distributions / net income. Skip per-year when distributions is zero for that year (legitimate for early-stage / pre-profit). Phase 9 audit Bucket B promoted from year_one_aggregate; the per-year skip replaces the prior horizon-wide silent skip.",
  ),

  # ============================================================
  # Phase 9 Phase D — Universal viability timeline checks.
  #
  # Every plan must satisfy the universal viability rule:
  #   Q1-Q5    losses tolerated when funded and stage-appropriate
  #   Q6-Q10   recovery trajectory required
  #   Q11      EBITDA positive (NI margin >= 0)
  #   Q12-Q20  no relapse unless deliberate funded expansion
  #
  # These six checks are trajectory_check rows — the validator
  # evaluates the entire Q1..Q20 sequence rather than a single
  # ratio. Issue routing maps each violation to its remediation
  # family so the cascade picks the right adaptation.
  # ============================================================
  _row(
    metric_key="ebitda_positive_by_q11",
    finmo_line_label="EBITDA",
    derivation_formula_key="trajectory_ebitda_positive_at_quarter",
    quarter_aggregation="trajectory_check",
    tolerance_bps_high_confidence=0,
    tolerance_bps_medium_confidence=0,
    tolerance_bps_low_confidence=0,
    tolerance_bps_generic_default=None,
    gate_kind="hard_fail",
    issue_family="turnaround_recovery_q5_q11",
    remediation_family="turnaround_recovery_q5_q11",
    primary_levers=[
      "expenses::Cost of Goods Sold",
      "expenses::Marketing",
      "expenses::General & Administrative",
      "expenses::Payroll",
      "revenue::Unit Price",
      "revenue::Utilization",
    ],
    secondary_levers=["revenue::Capacity"],
    stage_sensitivity=_STAGE_SENSITIVITY_FLAT,
    deadline_quarter=11,
    notes="Universal viability rule: by Q11, EBITDA margin must be >= 0 regardless of stage. Stage shifts WHEN inside Q1-Q11 the floor binds (loss tolerance window per stage), not WHETHER it binds.",
  ),
  _row(
    metric_key="ebitda_recovery_trend_q5_q11",
    finmo_line_label="EBITDA",
    derivation_formula_key="trajectory_ebitda_recovery_trend",
    quarter_aggregation="trajectory_check",
    tolerance_bps_high_confidence=0,
    tolerance_bps_medium_confidence=0,
    tolerance_bps_low_confidence=0,
    tolerance_bps_generic_default=None,
    gate_kind="hard_fail",
    issue_family="turnaround_recovery_q5_q11",
    remediation_family="turnaround_recovery_q5_q11",
    primary_levers=[
      "expenses::Cost of Goods Sold",
      "expenses::Marketing",
      "expenses::General & Administrative",
      "revenue::Unit Price",
      "revenue::Utilization",
    ],
    secondary_levers=["expenses::Payroll"],
    stage_sensitivity=_STAGE_SENSITIVITY_FLAT,
    deadline_quarter=11,
    notes="Universal viability rule: Q5-Q11 must show EBITDA recovery (improvement quarter-over-quarter or material upward trend). Pure flat or declining trajectory in this window fails.",
  ),
  _row(
    metric_key="loss_window_funded_through_q5",
    finmo_line_label="Cash",
    derivation_formula_key="trajectory_loss_window_funded",
    quarter_aggregation="trajectory_check",
    tolerance_bps_high_confidence=0,
    tolerance_bps_medium_confidence=0,
    tolerance_bps_low_confidence=0,
    tolerance_bps_generic_default=None,
    gate_kind="hard_fail",
    issue_family="funding_adaptation",
    remediation_family="funding_adaptation",
    primary_levers=[
      "schedules::Debt Issuance (New Borrowing)",
      "balance_sheet::Owner's Capital",
      "balance_sheet::Other Equity",
    ],
    secondary_levers=["balance_sheet::Distributions"],
    stage_sensitivity=_STAGE_SENSITIVITY_FLAT,
    deadline_quarter=5,
    notes="Universal viability rule: losses through Q5 must be FUNDED (cash never goes below zero, debt covers the gap, equity covers the gap). Unfunded losses fail.",
  ),
  _row(
    metric_key="no_post_recovery_relapse_q11_q20",
    finmo_line_label="EBITDA",
    derivation_formula_key="trajectory_no_post_recovery_relapse",
    quarter_aggregation="trajectory_check",
    tolerance_bps_high_confidence=0,
    tolerance_bps_medium_confidence=0,
    tolerance_bps_low_confidence=0,
    tolerance_bps_generic_default=None,
    gate_kind="hard_fail",
    issue_family="industry_normalization",
    remediation_family="industry_normalization",
    primary_levers=[
      "expenses::Cost of Goods Sold",
      "expenses::Marketing",
      "expenses::General & Administrative",
    ],
    secondary_levers=["revenue::Unit Price", "expenses::Payroll"],
    stage_sensitivity=_STAGE_SENSITIVITY_FLAT,
    deadline_quarter=20,
    notes="Universal viability rule: once EBITDA goes positive at Q11, it stays positive through Q20 unless a deliberate funded expansion event causes a temporary dip. Drift back into losses fails.",
  ),
  _row(
    metric_key="gross_margin_supports_ebitda_recovery",
    finmo_line_label="Gross Profit",
    derivation_formula_key="trajectory_gross_margin_supports_recovery",
    quarter_aggregation="trajectory_check",
    tolerance_bps_high_confidence=0,
    tolerance_bps_medium_confidence=0,
    tolerance_bps_low_confidence=0,
    tolerance_bps_generic_default=None,
    gate_kind="hard_fail",
    issue_family="margin_compression",
    remediation_family="margin_compression",
    primary_levers=["expenses::Cost of Goods Sold", "revenue::Unit Price"],
    secondary_levers=[],
    stage_sensitivity=_STAGE_SENSITIVITY_FLAT,
    deadline_quarter=11,
    notes="Gross margin at Q11 must be high enough that EBITDA can land >= 0 given typical operating expense ratios. If gross margin is structurally too thin, no amount of OpEx tightening can restore EBITDA.",
  ),
  _row(
    metric_key="fixed_cost_burden_reduced_or_scaled_by_q11",
    finmo_line_label="Operating Income",
    derivation_formula_key="trajectory_fixed_cost_burden_at_industry_floor",
    quarter_aggregation="trajectory_check",
    tolerance_bps_high_confidence=0,
    tolerance_bps_medium_confidence=0,
    tolerance_bps_low_confidence=0,
    tolerance_bps_generic_default=None,
    gate_kind="hard_fail",
    issue_family="operating_scale_adaptation",
    remediation_family="operating_scale_adaptation",
    primary_levers=[
      "revenue::Capacity",
      "revenue::Unit Price",
      "revenue::Utilization",
      "expenses::Payroll",
    ],
    secondary_levers=["expenses::Lease", "expenses::General & Administrative"],
    stage_sensitivity=_STAGE_SENSITIVITY_FLAT,
    deadline_quarter=11,
    notes="(Payroll + Rent + G&A) / Revenue at Q11 must be at industry-floor or below so the operating margin can land positive. Either revenue scaled into the cost base or the cost base trimmed to fit revenue.",
  ),
]


# ----------------------------------------------------------------------------
# Load + lookup.
# ----------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_realism_check_rows() -> List[Dict[str, Any]]:
  _ensure_env_loaded()
  conn = get_mysql_connection()
  try:
    _ensure_realism_check_lookup_table(conn)
    cur = conn.cursor(dictionary=True)
    try:
      cur.execute(
        f"""
        SELECT
          metric_key,
          finmo_line_label,
          derivation_formula_key,
          quarter_aggregation,
          applicability_rule_key,
          tolerance_bps_high_confidence,
          tolerance_bps_medium_confidence,
          tolerance_bps_low_confidence,
          tolerance_bps_generic_default,
          gate_kind,
          governs_model_input_lever_id,
          issue_family,
          remediation_family,
          primary_levers,
          secondary_levers,
          stage_sensitivity,
          deadline_quarter,
          notes,
          active
        FROM {REALISM_CHECK_TABLE_NAME}
        WHERE active = 1
        ORDER BY metric_key ASC, quarter_aggregation ASC
        """
      )
      raw_rows = cur.fetchall() or []
    finally:
      cur.close()
  finally:
    conn.close()
  rows: List[Dict[str, Any]] = []
  for raw in raw_rows:
    if not isinstance(raw, dict):
      continue
    metric_key = _clean_text(raw.get("metric_key"))
    if not metric_key:
      continue
    def _decode_json(value: Any) -> Any:
      if value is None or value == "":
        return None
      if isinstance(value, (list, dict)):
        return value
      try:
        return json.loads(value)
      except Exception:
        return None

    rows.append(
      {
        "metric_key": metric_key,
        "finmo_line_label": _clean_text(raw.get("finmo_line_label")),
        "derivation_formula_key": _clean_text(raw.get("derivation_formula_key")),
        "quarter_aggregation": _clean_text(raw.get("quarter_aggregation")) or "per_quarter",
        "applicability_rule_key": _clean_text(raw.get("applicability_rule_key")) or None,
        "tolerance_bps_high_confidence": int(raw.get("tolerance_bps_high_confidence") or 0),
        "tolerance_bps_medium_confidence": int(raw.get("tolerance_bps_medium_confidence") or 0),
        "tolerance_bps_low_confidence": int(raw.get("tolerance_bps_low_confidence") or 0),
        "tolerance_bps_generic_default": (
          int(raw["tolerance_bps_generic_default"])
          if raw.get("tolerance_bps_generic_default") is not None
          else None
        ),
        "gate_kind": _clean_text(raw.get("gate_kind")) or "warn",
        "governs_model_input_lever_id": _clean_text(raw.get("governs_model_input_lever_id")) or None,
        "issue_family": _clean_text(raw.get("issue_family")) or None,
        "remediation_family": _clean_text(raw.get("remediation_family")) or None,
        "primary_levers": _decode_json(raw.get("primary_levers")) or None,
        "secondary_levers": _decode_json(raw.get("secondary_levers")) or None,
        "stage_sensitivity": _decode_json(raw.get("stage_sensitivity")) or None,
        "deadline_quarter": (
          int(raw["deadline_quarter"]) if raw.get("deadline_quarter") is not None else None
        ),
        "notes": _clean_text(raw.get("notes")) or None,
        "active": bool(raw.get("active") or 0),
      }
    )
  return rows


def post_intake_finalize_realism_check_rows() -> List[Dict[str, Any]]:
  return [dict(row) for row in _load_realism_check_rows()]


def post_intake_finalize_realism_check_for_metric(
  metric_key: str,
  *,
  quarter_aggregation: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
  metric = _clean_text(metric_key)
  agg = _clean_text(quarter_aggregation) if quarter_aggregation else None
  for row in _load_realism_check_rows():
    if row.get("metric_key") != metric:
      continue
    if agg is not None and row.get("quarter_aggregation") != agg:
      continue
    return dict(row)
  return None
