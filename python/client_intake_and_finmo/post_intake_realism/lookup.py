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

_QUARTER_AGGREGATIONS = {"per_quarter", "year_one_aggregate", "horizon_average"}
_GATE_KINDS = {"hard_fail", "warn", "skip_if_no_coverage"}

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
          notes LONGTEXT NULL,
          active TINYINT(1) NOT NULL DEFAULT 1,
          created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
          UNIQUE KEY uniq_realism_check_metric_aggregation (metric_key, quarter_aggregation),
          KEY idx_realism_check_active (active),
          KEY idx_realism_check_gate_kind (gate_kind)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
      )
      for row in _DEFAULT_REALISM_CHECK_ROWS:
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
            notes,
            active
          ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
    "notes": notes,
    "active": active,
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
    gate_kind="warn",
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
    gate_kind="warn",
    governs_model_input_lever_id="expenses::Marketing",
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
    gate_kind="warn",
    governs_model_input_lever_id="expenses::Research & Development",
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
    gate_kind="warn",
    governs_model_input_lever_id="expenses::Lease",
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
    gate_kind="warn",
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
    gate_kind="warn",
    governs_model_input_lever_id="expenses::Payroll",
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
    gate_kind="warn",
    notes="Depreciation / revenue. Cross-check on capex schedule and PPE.",
  ),
  _row(
    metric_key="effective_tax_rate",
    finmo_line_label="Taxes",
    derivation_formula_key="taxes_div_pretax_income_year_one",
    quarter_aggregation="year_one_aggregate",
    applicability_rule_key="skip_when_pretax_income_nonpositive",
    tolerance_bps_high_confidence=500,
    tolerance_bps_medium_confidence=1000,
    tolerance_bps_low_confidence=2000,
    tolerance_bps_generic_default=3000,
    gate_kind="hard_fail",
    governs_model_input_lever_id="expenses::Taxes",
    notes="Year-one aggregate (per-quarter tax rates noisy). Promoted to hard_fail — n=1,519 IRS_SOI rows; tax rate that's far off industry typical is a signal of either tax-loss-carry-forward or a model error.",
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
    gate_kind="warn",
    notes=(
      "EBITDA / revenue. Demoted to warn — Q1 of a forecast routinely shows "
      "launch-quarter volatility (low fixed costs not yet absorbed, revenue "
      "ramping unevenly) that lands outside steady-state NAICS bands without "
      "indicating an implausible cost stack. Cost realism is enforced upstream "
      "by `cogs_to_revenue_ratio` and the line-level expense ratio bands, "
      "which are still hard_fail. Promote back to hard_fail once the gate "
      "applies a steady-state-quarter rule (e.g., Q5+) or a per-stage band."
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
    gate_kind="warn",
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
    gate_kind="warn",
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
    gate_kind="warn",
    governs_model_input_lever_id="balance_sheet::Inventory Days",
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
    gate_kind="warn",
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
    gate_kind="warn",
    notes="Deferred revenue / revenue. SEC EDGAR-backed (n=745). Applicability gate skips for retail / accommodation / personal-services NAICS-2 sectors.",
  ),
  _row(
    metric_key="ppe_percent_of_revenue",
    finmo_line_label="Property, Plant, and Equipment",
    derivation_formula_key="ppe_dollars_div_revenue_dollars",
    quarter_aggregation="year_one_aggregate",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="warn",
    notes="Year-one PPE / revenue (sum-vs-sum approximation). Cross-check on capex schedule.",
  ),
  _row(
    metric_key="total_assets_to_revenue",
    finmo_line_label="Total Assets",
    derivation_formula_key="total_assets_div_revenue",
    quarter_aggregation="year_one_aggregate",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="warn",
    notes="Year-one total assets / revenue. Cross-check on BS-vs-P&L scale (master-diagnostic Part 9.2).",
  ),
  _row(
    metric_key="owners_capital_percent_of_assets",
    finmo_line_label="Owner's Capital",
    derivation_formula_key="owners_capital_div_total_assets",
    quarter_aggregation="year_one_aggregate",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="warn",
    notes="Equity / assets. Cross-check on capital structure.",
  ),
  _row(
    metric_key="current_ratio",
    finmo_line_label="Current Ratio",
    derivation_formula_key="current_ratio",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=None,
    gate_kind="warn",
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
    gate_kind="warn",
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
    gate_kind="warn",
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
    gate_kind="warn",
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
    gate_kind="warn",
    notes="Operating CF / revenue. SEC EDGAR-backed (n=555).",
  ),
  _row(
    metric_key="capex_percent_of_revenue",
    finmo_line_label="Capital Expenditures",
    derivation_formula_key="capex_div_revenue_year_one",
    quarter_aggregation="year_one_aggregate",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="warn",
    notes="Year-one capex / revenue. Cross-check on PPE buildup.",
  ),
  _row(
    metric_key="distributions_percent_of_net_income",
    finmo_line_label="Distributions",
    derivation_formula_key="distributions_div_net_income_year_one",
    quarter_aggregation="year_one_aggregate",
    applicability_rule_key="skip_when_distributions_zero",
    tolerance_bps_high_confidence=_RATIO_TOL_HIGH,
    tolerance_bps_medium_confidence=_RATIO_TOL_MEDIUM,
    tolerance_bps_low_confidence=_RATIO_TOL_LOW,
    tolerance_bps_generic_default=_RATIO_TOL_GENERIC,
    gate_kind="warn",
    notes="Distributions / net income. Skip when distributions is zero (legitimate for early-stage / pre-profit).",
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
