"""Load post_intake_industry_baseline_lookup from existing public-data tables.

Aggregates NAICS-keyed industry baseline ratios from:
  - SOI_corporate_tax_returns (IRS Statistics of Income; corporate effective rates)
  - oews_state_wages (BLS Occupational Employment and Wage Statistics)
  - cbp_2022_raw (Census County Business Patterns 2022; payroll + employment by NAICS)
  - bds_firm_age (Census Business Dynamics Statistics; firm-age survival/growth)
  - bds_firm_size (Census BDS firm-size distribution)
  - sba_loan_7a_raw (SBA 7(a) loan approvals; debt structure benchmarks)
  - industry_metrics_raw (public-company quarterly financial ratios; Alpha Vantage source)

Coverage cascade is per-metric: each (NAICS, metric) pair gets its own row at the
level where it was resolved. The lookup function (separate work) walks 6 -> 5 -> 4
-> 3 -> 2 -> generic_default.

This loader is idempotent: it deletes rows for the data sources it owns before
re-inserting, so it can be re-run after an upstream refresh.
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple

from dotenv import load_dotenv
import mysql.connector


load_dotenv()


def _conn():
  return mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
    autocommit=False,
  )


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS post_intake_industry_baseline_lookup (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,

  naics_code              VARCHAR(6)  NOT NULL,
  naics_level             TINYINT     NOT NULL,
  naics_title             VARCHAR(255) NULL,

  metric_domain           VARCHAR(40) NOT NULL,
  metric_key              VARCHAR(80) NOT NULL,
  metric_label            VARCHAR(160) NULL,
  unit                    VARCHAR(20) NOT NULL,

  benchmark_min           DECIMAL(20,6) NULL,
  benchmark_target        DECIMAL(20,6) NULL,
  benchmark_max           DECIMAL(20,6) NULL,

  data_source             VARCHAR(40) NOT NULL,
  source_year             SMALLINT NULL,
  sample_size             INT NULL,
  confidence_tier         ENUM('high','medium','low','generic_default') NOT NULL,
  derivation_formula      TEXT NULL,

  active                  TINYINT(1) DEFAULT 1,
  notes                   TEXT NULL,
  created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at              DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  UNIQUE KEY uniq_baseline (naics_code, naics_level, metric_key, data_source, source_year),
  INDEX idx_lookup_path    (metric_key, naics_level, naics_code, active),
  INDEX idx_metric_active  (metric_key, active),
  INDEX idx_naics_active   (naics_code, naics_level, active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

CREATE_REGISTRY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS post_intake_industry_metric_registry (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  metric_key              VARCHAR(80) NOT NULL,
  metric_domain           VARCHAR(40) NOT NULL,
  metric_label            VARCHAR(160),
  unit                    VARCHAR(20) NOT NULL,
  description             TEXT,
  primary_source          VARCHAR(40),
  secondary_source        VARCHAR(40),
  applies_to_statement    VARCHAR(40),
  governs_model_input_lever VARCHAR(120),
  fail_if_no_coverage     TINYINT(1) NOT NULL DEFAULT 0,
  active                  TINYINT(1) NOT NULL DEFAULT 1,
  notes                   TEXT,
  created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at              DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_metric (metric_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

CREATE_COVERAGE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS post_intake_industry_baseline_coverage_audit (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  metric_key              VARCHAR(80) NOT NULL,
  metric_domain           VARCHAR(40) NOT NULL,
  total_rows              INT NOT NULL,
  level_6_rows            INT NOT NULL,
  level_5_rows            INT NOT NULL,
  level_4_rows            INT NOT NULL,
  level_3_rows            INT NOT NULL,
  level_2_rows            INT NOT NULL,
  generic_default_rows    INT NOT NULL,
  highest_level_with_coverage TINYINT,
  has_generic_default     TINYINT(1) NOT NULL,
  primary_data_source     VARCHAR(40),
  audit_run_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_metric_audit (metric_key, audit_run_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _to_float(value: Any) -> Optional[float]:
  if value is None:
    return None
  try:
    if isinstance(value, Decimal):
      return float(value)
    return float(value)
  except Exception:
    return None


def _confidence_for_sample(
  *,
  sample_size: Optional[int],
  high_floor: int,
  medium_floor: int,
) -> str:
  n = int(sample_size or 0)
  if n >= high_floor:
    return "high"
  if n >= medium_floor:
    return "medium"
  return "low"


def _normalize_naics(value: Any, expected_level: int) -> Optional[str]:
  if value is None:
    return None
  raw = str(value).strip()
  digits = "".join(ch for ch in raw if ch.isdigit())
  if not digits:
    return None
  digits = digits[:expected_level].zfill(expected_level) if len(digits) < expected_level else digits[:expected_level]
  return digits


def _insert_baseline_rows(cur, rows: Iterable[Dict[str, Any]], *, source_label: str) -> int:
  """Insert (or replace) baseline rows for a single data_source. Idempotent per source."""
  count = 0
  buffer: List[Tuple] = []
  for r in rows:
    buffer.append(
      (
        str(r["naics_code"]),
        int(r["naics_level"]),
        r.get("naics_title"),
        r["metric_domain"],
        r["metric_key"],
        r.get("metric_label"),
        r["unit"],
        r.get("benchmark_min"),
        r.get("benchmark_target"),
        r.get("benchmark_max"),
        r["data_source"],
        r.get("source_year"),
        r.get("sample_size"),
        r["confidence_tier"],
        r.get("derivation_formula"),
        1,
        r.get("notes"),
      )
    )
    if len(buffer) >= 500:
      cur.executemany(
        """
        REPLACE INTO post_intake_industry_baseline_lookup
          (naics_code, naics_level, naics_title,
           metric_domain, metric_key, metric_label, unit,
           benchmark_min, benchmark_target, benchmark_max,
           data_source, source_year, sample_size,
           confidence_tier, derivation_formula, active, notes)
        VALUES (%s,%s,%s, %s,%s,%s,%s, %s,%s,%s, %s,%s,%s, %s,%s,%s,%s)
        """,
        buffer,
      )
      count += len(buffer)
      buffer.clear()
  if buffer:
    cur.executemany(
      """
      REPLACE INTO post_intake_industry_baseline_lookup
        (naics_code, naics_level, naics_title,
         metric_domain, metric_key, metric_label, unit,
         benchmark_min, benchmark_target, benchmark_max,
         data_source, source_year, sample_size,
         confidence_tier, derivation_formula, active, notes)
      VALUES (%s,%s,%s, %s,%s,%s,%s, %s,%s,%s, %s,%s,%s, %s,%s,%s,%s)
      """,
      buffer,
    )
    count += len(buffer)
  print(f"  [{source_label}] inserted/replaced {count} rows")
  return count


# ---------------------------------------------------------------------------
# Source 1: SOI corporate tax returns
# ---------------------------------------------------------------------------


def load_from_soi(cur) -> int:
  """Derive P&L + balance sheet ratios from IRS SOI; aggregate (mean) across
  sub-industries when rolling up to higher NAICS levels."""
  cur.execute(
    "SELECT naics_title, with_net_income, business_receipts, cost_of_goods_sold, "
    "       net_income, deficit, depreciation_deduction, depreciable_assets, "
    "       total_assets, net_worth, income_subject_to_tax, "
    "       total_income_tax_after_credits, naics_2_digit, naics_3_digit, "
    "       naics_4_digit, naics_5_digit, naics_6_digit "
    "FROM SOI_corporate_tax_returns"
  )
  rows = cur.fetchall()

  # IRS SOI corporate tax returns dataset typically lags by 2-3 years; the
  # currently loaded slice corresponds to TY2020 release.
  source_year = 2020

  # Pre-collect all per-row metric observations, then aggregate.
  # Bucket per (naics_code_at_level, level, metric_key) -> list of (value, sample_size)
  buckets: Dict[Tuple[str, int, str], List[Tuple[float, int]]] = {}
  metric_definitions: Dict[str, Dict[str, Any]] = {}
  title_by_naics: Dict[Tuple[str, int], str] = {}

  def _record(metric_key, value, naics_levels_, sample_size_, *, definition):
    if value is None:
      return
    metric_definitions.setdefault(metric_key, definition)
    for level, naics_code in naics_levels_:
      buckets.setdefault((naics_code, level, metric_key), []).append((float(value), int(sample_size_ or 0)))

  for r in rows:
    naics_levels: List[Tuple[int, str]] = []
    for lvl_col, lvl in (
      ("naics_6_digit", 6), ("naics_5_digit", 5), ("naics_4_digit", 4),
      ("naics_3_digit", 3), ("naics_2_digit", 2),
    ):
      v = _normalize_naics(r.get(lvl_col), lvl)
      if v:
        naics_levels.append((lvl, v))

    title = str(r.get("naics_title") or "").strip()[:255] or None
    if title:
      for lvl, code in naics_levels:
        title_by_naics.setdefault((code, lvl), title)

    receipts = _to_float(r.get("business_receipts"))
    cogs = _to_float(r.get("cost_of_goods_sold"))
    net_income = _to_float(r.get("net_income"))
    depr = _to_float(r.get("depreciation_deduction"))
    depr_assets = _to_float(r.get("depreciable_assets"))
    total_assets = _to_float(r.get("total_assets"))
    net_worth = _to_float(r.get("net_worth"))
    income_subj_to_tax = _to_float(r.get("income_subject_to_tax"))
    tax_after = _to_float(r.get("total_income_tax_after_credits"))
    sample_size = int(_to_float(r.get("with_net_income")) or 0)

    if income_subj_to_tax and income_subj_to_tax > 0 and tax_after is not None:
      _record(
        "effective_tax_rate", tax_after / income_subj_to_tax, naics_levels, sample_size,
        definition={"metric_domain":"p_and_l","metric_label":"Effective corporate income tax rate","unit":"ratio",
                    "derivation_formula":"total_income_tax_after_credits / income_subject_to_tax (mean across sub-industries)"},
      )
    if receipts and receipts > 0 and cogs is not None:
      cogs_pct = cogs / receipts
      _record(
        "cogs_percent_of_revenue", cogs_pct, naics_levels, sample_size,
        definition={"metric_domain":"p_and_l","metric_label":"Cost of Goods Sold as % of revenue","unit":"ratio",
                    "derivation_formula":"cost_of_goods_sold / business_receipts (mean across sub-industries)"},
      )
      _record(
        "gross_margin_percent", max(0.0, 1.0 - cogs_pct), naics_levels, sample_size,
        definition={"metric_domain":"p_and_l","metric_label":"Gross margin","unit":"ratio",
                    "derivation_formula":"1 - cogs_percent (mean across sub-industries)"},
      )
    if receipts and receipts > 0 and net_income is not None:
      _record(
        "net_income_margin", net_income / receipts, naics_levels, sample_size,
        definition={"metric_domain":"p_and_l","metric_label":"Net income margin","unit":"ratio",
                    "derivation_formula":"net_income / business_receipts (mean across sub-industries)"},
      )
    if receipts and receipts > 0 and depr is not None:
      _record(
        "depreciation_percent_of_revenue", depr / receipts, naics_levels, sample_size,
        definition={"metric_domain":"p_and_l","metric_label":"Depreciation as % of revenue","unit":"ratio",
                    "derivation_formula":"depreciation_deduction / business_receipts (mean across sub-industries)"},
      )
    if receipts and receipts > 0 and depr_assets is not None:
      _record(
        "ppe_percent_of_revenue", depr_assets / receipts, naics_levels, sample_size,
        definition={"metric_domain":"balance_sheet","metric_label":"Depreciable assets as % of revenue","unit":"ratio",
                    "derivation_formula":"depreciable_assets / business_receipts (mean across sub-industries)"},
      )
    if receipts and receipts > 0 and total_assets is not None:
      _record(
        "total_assets_to_revenue", total_assets / receipts, naics_levels, sample_size,
        definition={"metric_domain":"balance_sheet","metric_label":"Total assets / revenue","unit":"ratio",
                    "derivation_formula":"total_assets / business_receipts (mean across sub-industries)"},
      )
    if total_assets and total_assets > 0 and net_worth is not None:
      _record(
        "owners_capital_percent_of_assets", net_worth / total_assets, naics_levels, sample_size,
        definition={"metric_domain":"balance_sheet","metric_label":"Equity / total assets","unit":"ratio",
                    "derivation_formula":"net_worth / total_assets (mean across sub-industries)"},
      )
      if net_worth > 0 and total_assets > net_worth:
        _record(
          "debt_to_equity", (total_assets - net_worth) / net_worth, naics_levels, sample_size,
          definition={"metric_domain":"balance_sheet","metric_label":"Total liabilities / equity","unit":"ratio",
                      "derivation_formula":"(total_assets - net_worth) / net_worth (mean across sub-industries)"},
        )

  # Aggregate: weighted mean by sample_size when multiple rows share the bucket.
  rows_to_insert: List[Dict[str, Any]] = []
  for (naics_code, level, metric_key), observations in buckets.items():
    if not observations:
      continue
    values = [v for v, _ in observations]
    total_sample = sum(s for _, s in observations) or len(values)
    if total_sample > 0 and any(s for _, s in observations):
      mean_value = sum(v * max(s, 0) for v, s in observations) / max(
        sum(max(s, 0) for _, s in observations), 1
      )
    else:
      mean_value = sum(values) / max(len(values), 1)
    confidence = _confidence_for_sample(
      sample_size=total_sample, high_floor=10000, medium_floor=1000,
    )
    if level <= 3 and confidence == "high":
      confidence = "medium"
    definition = metric_definitions.get(metric_key) or {}
    rows_to_insert.append(
      {
        "naics_code": naics_code,
        "naics_level": level,
        "naics_title": title_by_naics.get((naics_code, level)),
        "metric_domain": definition.get("metric_domain", "p_and_l"),
        "metric_key": metric_key,
        "metric_label": definition.get("metric_label"),
        "unit": definition.get("unit", "ratio"),
        "benchmark_target": float(mean_value),
        "data_source": "IRS_SOI",
        "source_year": source_year,
        "sample_size": int(total_sample),
        "confidence_tier": confidence,
        "derivation_formula": definition.get("derivation_formula"),
        "notes": f"IRS Statistics of Income, weighted mean across {len(observations)} sub-industry rows.",
      }
    )

  return _insert_baseline_rows(cur, rows_to_insert, source_label="IRS_SOI")


# ---------------------------------------------------------------------------
# Source 2: BLS OEWS state wages -> avg wage by NAICS
# ---------------------------------------------------------------------------


def load_from_oews(cur) -> int:
  """Aggregate national-level wages by NAICS from BLS OEWS."""
  rows_to_insert: List[Dict[str, Any]] = []

  # Use national rows (area_title='U.S.' / area_type='1') across all occupations,
  # weighted by tot_emp. NAICS codes in OEWS are 6-digit when specific, but some
  # are aggregated NAICS-3/4/5 (e.g., '230000' for Construction = NAICS 23).
  cur.execute(
    """
    SELECT naics, naics_title,
           SUM(tot_emp) AS total_emp,
           SUM(tot_emp * a_mean) AS weighted_pay,
           COUNT(*) AS occ_count
    FROM oews_state_wages
    WHERE area_type = '1'
      AND naics IS NOT NULL AND naics <> ''
      AND tot_emp > 0
      AND a_mean IS NOT NULL AND a_mean > 0
    GROUP BY naics, naics_title
    """
  )
  for r in cur.fetchall():
    naics_raw = str(r["naics"] or "").strip()
    digits = "".join(ch for ch in naics_raw if ch.isdigit())
    if not digits:
      continue
    if len(digits) < 6:
      digits = digits.ljust(6, "0")
    # OEWS encodes hierarchy by zero-padding (e.g., '230000' = NAICS 23)
    # Strip trailing zeros from a 6-digit code to detect actual depth.
    actual_level = 6
    while actual_level > 2 and len(digits) >= actual_level and digits[actual_level - 1] == "0":
      actual_level -= 1
    if actual_level < 2:
      continue
    naics_code = digits[:actual_level]
    # Skip the cross-industry pseudo-NAICS '000000' entirely
    if not any(ch != "0" for ch in naics_code):
      continue

    total_emp = int(_to_float(r.get("total_emp")) or 0)
    weighted_pay = _to_float(r.get("weighted_pay")) or 0.0
    occ_count = int(_to_float(r.get("occ_count")) or 0)
    if total_emp <= 0 or weighted_pay <= 0:
      continue
    avg_wage = weighted_pay / total_emp
    title = str(r.get("naics_title") or "").strip()[:255] or None

    rows_to_insert.append(
      {
        "naics_code": naics_code,
        "naics_level": actual_level,
        "naics_title": title,
        "metric_domain": "workforce",
        "metric_key": "avg_wage_per_fte",
        "metric_label": "Employment-weighted mean annual wage across all occupations",
        "unit": "usd",
        "benchmark_target": avg_wage,
        "data_source": "BLS_OEWS",
        "source_year": 2023,
        "sample_size": total_emp,
        "confidence_tier": _confidence_for_sample(
          sample_size=total_emp, high_floor=10000, medium_floor=500,
        ),
        "derivation_formula": "SUM(tot_emp * a_mean) / SUM(tot_emp) over national rows",
        "notes": f"Aggregated across {occ_count} occupations at U.S. national level.",
      }
    )

  return _insert_baseline_rows(cur, rows_to_insert, source_label="BLS_OEWS")


# ---------------------------------------------------------------------------
# Source 3: Census CBP 2022 -> employment density + wages by NAICS
# ---------------------------------------------------------------------------


def load_from_cbp(cur) -> int:
  """Derive payroll-per-FTE and establishment density from Census CBP 2022."""
  rows_to_insert: List[Dict[str, Any]] = []

  cur.execute(
    """
    SELECT naics, naics_label,
           SUM(estab) AS total_estab,
           SUM(emp) AS total_emp,
           SUM(pay_ann) AS total_pay_ann
    FROM cbp_2022_raw
    WHERE naics IS NOT NULL AND naics <> ''
      AND naics <> '------'
    GROUP BY naics, naics_label
    """
  )
  for r in cur.fetchall():
    naics_raw = str(r["naics"] or "").strip()
    digits = "".join(ch for ch in naics_raw if ch.isdigit())
    if not digits:
      continue
    actual_level = len(digits)  # CBP gives variable-length NAICS codes
    if actual_level < 2:
      continue
    naics_code = digits

    total_estab = int(_to_float(r.get("total_estab")) or 0)
    total_emp = int(_to_float(r.get("total_emp")) or 0)
    total_pay_thousands = int(_to_float(r.get("total_pay_ann")) or 0)
    if total_emp <= 0 or total_pay_thousands <= 0:
      continue

    # CBP pay_ann is in $1,000s
    avg_wage_per_fte = (total_pay_thousands * 1000.0) / total_emp
    emp_per_estab = total_emp / max(1, total_estab)

    title = str(r.get("naics_label") or "").strip()[:255] or None
    confidence = _confidence_for_sample(
      sample_size=total_estab, high_floor=500, medium_floor=50,
    )

    rows_to_insert.append(
      {
        "naics_code": naics_code,
        "naics_level": actual_level,
        "naics_title": title,
        "metric_domain": "workforce",
        "metric_key": "avg_wage_per_fte",
        "metric_label": "CBP-derived average annual wage per employee (national)",
        "unit": "usd",
        "benchmark_target": avg_wage_per_fte,
        "data_source": "Census_CBP",
        "source_year": 2022,
        "sample_size": total_estab,
        "confidence_tier": confidence,
        "derivation_formula": "SUM(pay_ann) * 1000 / SUM(emp) across all states",
        "notes": "From Census County Business Patterns 2022.",
      }
    )
    rows_to_insert.append(
      {
        "naics_code": naics_code,
        "naics_level": actual_level,
        "naics_title": title,
        "metric_domain": "workforce",
        "metric_key": "employees_per_establishment",
        "metric_label": "Average employees per establishment",
        "unit": "count",
        "benchmark_target": emp_per_estab,
        "data_source": "Census_CBP",
        "source_year": 2022,
        "sample_size": total_estab,
        "confidence_tier": confidence,
        "derivation_formula": "SUM(emp) / SUM(estab) across all states",
        "notes": "From Census County Business Patterns 2022.",
      }
    )

  return _insert_baseline_rows(cur, rows_to_insert, source_label="Census_CBP")


# ---------------------------------------------------------------------------
# Source 4: industry_metrics_raw -> P&L + BS ratios from public companies
# ---------------------------------------------------------------------------


def load_from_industry_metrics(cur) -> int:
  """Aggregate public-company quarterly ratios into NAICS baselines (median + p25/p75)."""
  rows_to_insert: List[Dict[str, Any]] = []

  # We only trust observations with reasonable revenue magnitudes; filter by
  # total_revenue > 0. We'll use the most recent 4 years to favor current trends.
  cur.execute("SELECT MAX(YEAR(fiscalDateEnding)) FROM industry_metrics_raw")
  max_year = (cur.fetchone() or {}).get("MAX(YEAR(fiscalDateEnding))")
  cutoff_year = int(max_year) - 3 if max_year else 2020

  metric_columns = [
    ("p_and_l", "cogs_percent",                      "cogs_percent_of_revenue", "ratio", "median(cogs_percent) within NAICS"),
    ("p_and_l", "gross_margin_q",                    "gross_margin_percent",    "ratio", "median(gross_margin_q) within NAICS"),
    ("p_and_l", "operating_margin_q",                "operating_margin_percent","ratio", "median(operating_margin_q) within NAICS"),
    ("p_and_l", "ebitda_margin_q",                   "ebitda_margin",           "ratio", "median(ebitda_margin_q) within NAICS"),
    ("p_and_l", "net_margin_q",                      "net_income_margin",       "ratio", "median(net_margin_q) within NAICS"),
    ("p_and_l", "sga_percent",                       "sga_percent_of_revenue",  "ratio", "median(sga_percent) within NAICS"),
    ("p_and_l", "rnd_percent",                       "r_and_d_percent_of_revenue", "ratio", "median(rnd_percent) within NAICS"),
    ("balance_sheet", "dso",                         "ar_days_dso",             "days",  "median(dso) within NAICS"),
    ("balance_sheet", "dpo",                         "ap_days_dpo",             "days",  "median(dpo) within NAICS"),
    ("balance_sheet", "inventory_days",              "inventory_days",          "days",  "median(inventory_days) within NAICS"),
    ("balance_sheet", "current_ratio",               "current_ratio",           "ratio", "median(current_ratio) within NAICS"),
    ("balance_sheet", "quick_ratio",                 "quick_ratio",             "ratio", "median(quick_ratio) within NAICS"),
    ("balance_sheet", "debt_to_equity",              "debt_to_equity",          "ratio", "median(debt_to_equity) within NAICS"),
    ("balance_sheet", "debt_to_assets",              "debt_to_assets",          "ratio", "median(debt_to_assets) within NAICS"),
    ("balance_sheet", "interest_coverage",           "interest_coverage",       "ratio", "median(interest_coverage) within NAICS"),
    ("cash_flow",     "capex_percent_revenue",       "capex_percent_of_revenue","ratio", "median(capex_percent_revenue) within NAICS"),
    ("cash_flow",     "depreciation_percent_revenue","depreciation_percent_of_revenue","ratio","median(depreciation_percent_revenue) within NAICS"),
  ]

  # MySQL does not have a direct PERCENTILE_DISC; we approximate median by sorting
  # and computing in Python per-NAICS group. We pull all obs and aggregate locally.
  # Filter to the cutoff year window and non-null on at least one metric.
  cur.execute(
    f"""
    SELECT naics_code,
           cogs_percent, gross_margin_q, operating_margin_q, ebitda_margin_q,
           net_margin_q, sga_percent, rnd_percent,
           dso, dpo, inventory_days,
           current_ratio, quick_ratio, debt_to_equity, debt_to_assets,
           interest_coverage,
           capex_percent_revenue, depreciation_percent_revenue
    FROM industry_metrics_raw
    WHERE total_revenue > 0
      AND YEAR(fiscalDateEnding) >= {cutoff_year}
      AND naics_code IS NOT NULL AND naics_code <> ''
    """
  )
  raw_obs = cur.fetchall()
  if not raw_obs:
    print("  [industry_metrics_raw] no rows in cutoff window; skipping")
    return 0

  # Build naics_master lookup for titles
  cur.execute("SELECT naics_code, naics_title FROM naics_master WHERE naics_code IS NOT NULL")
  title_by_naics: Dict[str, str] = {}
  for r in cur.fetchall():
    code = "".join(ch for ch in str(r["naics_code"] or "") if ch.isdigit())
    title = str(r.get("naics_title") or "").strip()[:255]
    if code and title and code not in title_by_naics:
      title_by_naics[code] = title

  # Collect observations at each rollup level
  # naics_6 -> raw; for level 5/4/3/2 we aggregate by truncating naics_6
  per_level_obs: Dict[int, Dict[str, Dict[str, List[float]]]] = {
    lvl: {} for lvl in (6, 5, 4, 3, 2)
  }

  for r in raw_obs:
    n6_raw = str(r["naics_code"] or "").strip()
    digits = "".join(ch for ch in n6_raw if ch.isdigit())
    if len(digits) < 2:
      continue
    n6 = digits.ljust(6, "0")[:6] if len(digits) >= 2 else None
    if not n6:
      continue
    for level in (6, 5, 4, 3, 2):
      key = n6[:level]
      group = per_level_obs[level].setdefault(key, {})
      for _domain, src_col, _dest, _unit, _formula in metric_columns:
        v = _to_float(r.get(src_col))
        if v is None:
          continue
        # Reject extreme outliers from quarterly snapshots
        if abs(v) > 50:  # ratios above 5000% are noise
          continue
        group.setdefault(src_col, []).append(v)

  def _percentile(values: List[float], pct: float) -> float:
    s = sorted(values)
    if not s:
      return 0.0
    if len(s) == 1:
      return s[0]
    k = (len(s) - 1) * pct
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
      return s[int(k)]
    return s[f] + (s[c] - s[f]) * (k - f)

  for level, groups in per_level_obs.items():
    for naics_code, metric_obs in groups.items():
      title = title_by_naics.get(naics_code)
      for _domain, src_col, dest_key, unit, formula in metric_columns:
        domain = _domain
        observations = metric_obs.get(src_col) or []
        n = len(observations)
        if n < 3:
          continue  # not enough signal
        target = _percentile(observations, 0.50)
        p25 = _percentile(observations, 0.25)
        p75 = _percentile(observations, 0.75)
        confidence = _confidence_for_sample(
          sample_size=n, high_floor=40, medium_floor=10,
        )
        if level <= 3 and confidence == "high":
          confidence = "medium"
        rows_to_insert.append(
          {
            "naics_code": naics_code,
            "naics_level": level,
            "naics_title": title,
            "metric_domain": domain,
            "metric_key": dest_key,
            "metric_label": dest_key.replace("_", " "),
            "unit": unit,
            "benchmark_min": p25,
            "benchmark_target": target,
            "benchmark_max": p75,
            "data_source": "industry_metrics_raw",
            "source_year": cutoff_year,
            "sample_size": n,
            "confidence_tier": confidence,
            "derivation_formula": formula + f"; window >= {cutoff_year}; outlier filter |x|<=50",
            "notes": "Public-company quarterly ratios aggregated to NAICS via median (P50) with P25/P75 band.",
          }
        )

  return _insert_baseline_rows(cur, rows_to_insert, source_label="industry_metrics_raw")


# ---------------------------------------------------------------------------
# Source 5: SBA 7(a) loans -> debt structure benchmarks
# ---------------------------------------------------------------------------


def load_from_sba(cur) -> int:
  """Aggregate SBA 7(a) loan benchmarks (typical loan size, interest rate, term)."""
  rows_to_insert: List[Dict[str, Any]] = []

  cur.execute(
    """
    SELECT NAICSCode AS naics_code,
           NAICSDescription AS naics_title,
           InitialInterestRate AS rate,
           GrossApproval AS amount,
           TermInMonths AS term_months,
           JobsSupported AS jobs
    FROM sba_loan_7a_raw
    WHERE NAICSCode IS NOT NULL AND NAICSCode <> ''
      AND LoanStatus IN ('PIF','EXEMPT','COMMIT','ACTIVE')
      AND ApprovalFY >= 2018
      AND InitialInterestRate IS NOT NULL AND InitialInterestRate > 0
      AND GrossApproval IS NOT NULL AND GrossApproval > 0
    """
  )
  obs = cur.fetchall()
  if not obs:
    print("  [SBA_7A] no usable loan rows; skipping")
    return 0

  # Aggregate by NAICS at each rollup level
  per_level: Dict[int, Dict[str, Dict[str, List[float]]]] = {
    lvl: {} for lvl in (6, 5, 4, 3, 2)
  }
  title_by_naics: Dict[str, str] = {}
  for r in obs:
    n_raw = str(r["naics_code"] or "").strip()
    digits = "".join(ch for ch in n_raw if ch.isdigit())
    if len(digits) < 2:
      continue
    n6 = digits.ljust(6, "0")[:6]
    title = str(r.get("naics_title") or "").strip()[:255]
    if n6 and title:
      title_by_naics.setdefault(n6, title)
    rate = _to_float(r.get("rate"))
    amount = _to_float(r.get("amount"))
    term = _to_float(r.get("term_months"))
    jobs = _to_float(r.get("jobs"))
    for level in (6, 5, 4, 3, 2):
      key = n6[:level]
      g = per_level[level].setdefault(key, {})
      if rate is not None and 0.0 < rate < 0.5:
        g.setdefault("rate", []).append(rate)
      if amount is not None and amount > 0:
        g.setdefault("amount", []).append(amount)
      if term is not None and term > 0:
        g.setdefault("term", []).append(term)
      if jobs is not None and jobs > 0:
        g.setdefault("jobs", []).append(jobs)

  def _median(vals: List[float]) -> float:
    s = sorted(vals)
    n = len(s)
    if n == 0:
      return 0.0
    if n % 2 == 1:
      return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0

  for level, groups in per_level.items():
    for naics_code, m in groups.items():
      title = title_by_naics.get(naics_code.ljust(6, "0")[:6]) or title_by_naics.get(naics_code)
      sample = max(len(m.get("rate", [])), len(m.get("amount", [])), len(m.get("term", [])))
      if sample < 5:
        continue
      conf = _confidence_for_sample(sample_size=sample, high_floor=200, medium_floor=30)
      if level <= 3 and conf == "high":
        conf = "medium"
      if m.get("rate"):
        rates = m["rate"]
        rows_to_insert.append(
          {
            "naics_code": naics_code,
            "naics_level": level,
            "naics_title": title,
            "metric_domain": "capital_structure",
            "metric_key": "sba_initial_interest_rate",
            "metric_label": "Median initial interest rate on SBA 7(a) loans",
            "unit": "ratio",
            "benchmark_min": _median(sorted(rates)[: max(1, len(rates) // 4)]),
            "benchmark_target": _median(rates),
            "benchmark_max": _median(sorted(rates)[-max(1, len(rates) // 4):]),
            "data_source": "SBA_7A",
            "source_year": 2024,
            "sample_size": len(rates),
            "confidence_tier": conf,
            "derivation_formula": "median(InitialInterestRate) on SBA 7(a) loans, FY>=2018, status in (PIF/EXEMPT/COMMIT/ACTIVE)",
            "notes": "From sba_loan_7a_raw.",
          }
        )
      if m.get("amount"):
        amts = m["amount"]
        rows_to_insert.append(
          {
            "naics_code": naics_code,
            "naics_level": level,
            "naics_title": title,
            "metric_domain": "capital_structure",
            "metric_key": "sba_typical_loan_size",
            "metric_label": "Median SBA 7(a) gross approval amount",
            "unit": "usd",
            "benchmark_target": _median(amts),
            "data_source": "SBA_7A",
            "source_year": 2024,
            "sample_size": len(amts),
            "confidence_tier": conf,
            "derivation_formula": "median(GrossApproval) on SBA 7(a) loans, FY>=2018",
            "notes": "From sba_loan_7a_raw.",
          }
        )
      if m.get("term"):
        terms = m["term"]
        rows_to_insert.append(
          {
            "naics_code": naics_code,
            "naics_level": level,
            "naics_title": title,
            "metric_domain": "capital_structure",
            "metric_key": "sba_typical_loan_term_months",
            "metric_label": "Median SBA 7(a) loan term in months",
            "unit": "count",
            "benchmark_target": _median(terms),
            "data_source": "SBA_7A",
            "source_year": 2024,
            "sample_size": len(terms),
            "confidence_tier": conf,
            "derivation_formula": "median(TermInMonths) on SBA 7(a) loans, FY>=2018",
            "notes": "From sba_loan_7a_raw.",
          }
        )

  return _insert_baseline_rows(cur, rows_to_insert, source_label="SBA_7A")


# ---------------------------------------------------------------------------
# Source 6: BDS firm-age -> stage ramp benchmarks
# ---------------------------------------------------------------------------


def load_from_bds(cur) -> int:
  """Derive stage-ramp typical employment trajectory by NAICS-4 from BDS firm-age."""
  rows_to_insert: List[Dict[str, Any]] = []

  # Use most recent year in the table
  cur.execute("SELECT MAX(year) AS y FROM bds_firm_age")
  max_year = int((cur.fetchone() or {}).get("y") or 0)
  if max_year <= 0:
    print("  [Census_BDS] no year data; skipping")
    return 0

  cur.execute(
    f"""
    SELECT vcnaics4 AS naics4,
           firm_age_bucket,
           SUM(firms) AS firms,
           SUM(emp) AS emp,
           AVG(net_job_creation_rate) AS net_job_growth,
           AVG(estabs_exit_rate) AS exit_rate
    FROM bds_firm_age
    WHERE year = {max_year}
      AND vcnaics4 IS NOT NULL
    GROUP BY vcnaics4, firm_age_bucket
    """
  )
  by_naics: Dict[str, Dict[str, Dict[str, float]]] = {}
  for r in cur.fetchall():
    n4_raw = str(r.get("naics4") or "").strip()
    digits = "".join(ch for ch in n4_raw if ch.isdigit())
    if len(digits) < 2:
      continue
    naics4 = digits[:4]
    bucket = str(r.get("firm_age_bucket") or "").strip()
    by_naics.setdefault(naics4, {})[bucket] = {
      "firms": _to_float(r.get("firms")) or 0.0,
      "emp": _to_float(r.get("emp")) or 0.0,
      "net_job_growth": _to_float(r.get("net_job_growth")) or 0.0,
      "exit_rate": _to_float(r.get("exit_rate")) or 0.0,
    }

  def _emp_per_firm(d: Dict[str, float]) -> float:
    firms = d.get("firms") or 0.0
    if firms <= 0:
      return 0.0
    return (d.get("emp") or 0.0) / firms

  for naics4, buckets in by_naics.items():
    if not buckets:
      continue
    age_age0 = buckets.get("a) 0") or {}
    age_age1 = buckets.get("b) 1") or {}
    age_age2 = buckets.get("c) 2") or {}
    # 11+ years is split across "h) 11 to 15", "i) 16 to 20", "j) 21 to 25", "k) 26+"
    # in current BDS releases. Combine them by summing firms+emp and averaging rates.
    mature_buckets = [
      buckets.get(label) or {}
      for label in ("h) 11 to 15", "i) 16 to 20", "j) 21 to 25", "k) 26+")
      if buckets.get(label)
    ]
    if mature_buckets:
      total_firms_mature = sum(b.get("firms") or 0.0 for b in mature_buckets)
      total_emp_mature = sum(b.get("emp") or 0.0 for b in mature_buckets)
      avg_njg = (
        sum(b.get("net_job_growth") or 0.0 for b in mature_buckets) / max(len(mature_buckets), 1)
      )
      avg_exit = (
        sum(b.get("exit_rate") or 0.0 for b in mature_buckets) / max(len(mature_buckets), 1)
      )
      age_age5plus = {
        "firms": total_firms_mature,
        "emp": total_emp_mature,
        "net_job_growth": avg_njg,
        "exit_rate": avg_exit,
      }
    else:
      age_age5plus = (
        buckets.get("g) 6 to 10")
        or buckets.get("f) 5")
        or {}
      )
    sample = int(sum(b.get("firms") or 0.0 for b in buckets.values()))
    if sample < 50:
      continue
    confidence = _confidence_for_sample(sample_size=sample, high_floor=2000, medium_floor=200)
    title = None  # BDS uses vcnaics4 numeric; map via naics_master if needed

    # Year-1 to Year-5 employment ratio
    e0 = _emp_per_firm(age_age0)
    e1 = _emp_per_firm(age_age1)
    e5 = _emp_per_firm(age_age5plus)
    if e0 > 0 and e5 > 0:
      rows_to_insert.append(
        {
          "naics_code": naics4,
          "naics_level": 4,
          "naics_title": title,
          "metric_domain": "stage_ramp",
          "metric_key": "year1_to_year5_employment_ratio",
          "metric_label": "Typical employment Y5+ / Y0 per firm",
          "unit": "ratio",
          "benchmark_target": e5 / max(e0, 0.1),
          "data_source": "Census_BDS",
          "source_year": max_year,
          "sample_size": sample,
          "confidence_tier": confidence,
          "derivation_formula": "AVG(emp/firms at age 11+) / AVG(emp/firms at age 0)",
          "notes": "Census Business Dynamics Statistics firm-age cohorts.",
        }
      )
    # Typical exit rate by stage. Age-0 firms cannot have exited yet by BDS
    # methodology (they were just established this year). Use age-1 as the
    # earliest measurable exit cohort: firms born last year, exited this year.
    exit_age1 = age_age1.get("exit_rate") or 0.0
    exit_age5 = age_age5plus.get("exit_rate") or 0.0
    if exit_age1 > 0:
      rows_to_insert.append(
        {
          "naics_code": naics4,
          "naics_level": 4,
          "naics_title": title,
          "metric_domain": "stage_ramp",
          "metric_key": "startup_year1_exit_rate",
          "metric_label": "Year-1 establishment exit rate (%)",
          "unit": "percent",
          "benchmark_target": exit_age1,
          "data_source": "Census_BDS",
          "source_year": max_year,
          "sample_size": sample,
          "confidence_tier": confidence,
          "derivation_formula": "AVG(estabs_exit_rate where firm_age='b) 1')  -- age-0 exits are structurally zero in BDS",
          "notes": "Year-1 exit rate measured from age-1 cohort (firms born last year, exited this year).",
        }
      )
    # QoQ revenue growth proxies, derived from BDS net_job_creation_rate by stage.
    # Employment growth is the closest publicly-available proxy for revenue growth
    # by firm age. We divide annual rate by 4 to approximate quarterly. This is
    # marked low-confidence because it's an employment-derived proxy, not a direct
    # revenue measurement.
    for source_bucket, qoq_metric_key, qoq_label in (
      (age_age0, "startup_qoq_growth_typical", "Startup typical QoQ revenue growth (employment-proxy)"),
      (age_age1, "early_qoq_growth_typical", "Early-stage typical QoQ revenue growth (employment-proxy)"),
    ):
      annual_njg_pct = source_bucket.get("net_job_growth")
      if annual_njg_pct is None:
        continue
      # BDS rates are in percent (e.g., 25.0 = 25%). Convert to ratio and quarterly.
      qoq_ratio = float(annual_njg_pct) / 100.0 / 4.0
      if qoq_ratio == 0.0:
        continue
      qoq_conf = "low" if confidence == "high" else confidence
      rows_to_insert.append(
        {
          "naics_code": naics4,
          "naics_level": 4,
          "naics_title": title,
          "metric_domain": "stage_ramp",
          "metric_key": qoq_metric_key,
          "metric_label": qoq_label,
          "unit": "ratio",
          "benchmark_target": qoq_ratio,
          "data_source": "Census_BDS",
          "source_year": max_year,
          "sample_size": sample,
          "confidence_tier": qoq_conf,
          "derivation_formula": "BDS net_job_creation_rate by firm-age cohort / 100 / 4 -- employment-proxy for revenue growth",
          "notes": "Employment-derived QoQ growth proxy. Use revenue-direct industry_growth_table for mature stage.",
        }
      )
    if exit_age5 > 0:
      rows_to_insert.append(
        {
          "naics_code": naics4,
          "naics_level": 4,
          "naics_title": title,
          "metric_domain": "stage_ramp",
          "metric_key": "mature_exit_rate",
          "metric_label": "Mature firms (11+) establishment exit rate (%)",
          "unit": "percent",
          "benchmark_target": exit_age5,
          "data_source": "Census_BDS",
          "source_year": max_year,
          "sample_size": sample,
          "confidence_tier": confidence,
          "derivation_formula": "AVG(estabs_exit_rate where firm_age='g) 11+')",
          "notes": "Steady-state churn for established firms.",
        }
      )
    # Typical job growth at age-1 (early stage)
    net_growth_age0 = age_age0.get("net_job_growth")
    net_growth_age1 = age_age1.get("net_job_growth")
    net_growth_age5 = age_age5plus.get("net_job_growth")
    for label, age_bucket_value, key in (
      ("startup_net_job_growth_rate", net_growth_age0, "startup_net_job_growth_rate"),
      ("early_net_job_growth_rate", net_growth_age1, "early_net_job_growth_rate"),
      ("mature_net_job_growth_rate", net_growth_age5, "mature_net_job_growth_rate"),
    ):
      if age_bucket_value is None:
        continue
      rows_to_insert.append(
        {
          "naics_code": naics4,
          "naics_level": 4,
          "naics_title": title,
          "metric_domain": "stage_ramp",
          "metric_key": key,
          "metric_label": label.replace("_", " "),
          "unit": "percent",
          "benchmark_target": age_bucket_value,
          "data_source": "Census_BDS",
          "source_year": max_year,
          "sample_size": sample,
          "confidence_tier": confidence,
          "derivation_formula": f"AVG(net_job_creation_rate) at firm_age corresponding to {label}",
          "notes": "BDS net job growth rate by firm-age cohort.",
        }
      )

  return _insert_baseline_rows(cur, rows_to_insert, source_label="Census_BDS")


# ---------------------------------------------------------------------------
# Generic defaults (level 0, naics_code='*')
# ---------------------------------------------------------------------------


GENERIC_DEFAULTS: List[Dict[str, Any]] = [
  # P&L
  {"metric_domain":"p_and_l","metric_key":"effective_tax_rate","metric_label":"Effective tax rate","unit":"ratio",
   "benchmark_min":0.10,"benchmark_target":0.21,"benchmark_max":0.28,
   "notes":"U.S. federal corporate statutory rate is 21%; effective rates net of credits typically 10-25%."},
  {"metric_domain":"p_and_l","metric_key":"cogs_percent_of_revenue","metric_label":"COGS / revenue","unit":"ratio",
   "benchmark_min":0.20,"benchmark_target":0.55,"benchmark_max":0.80,
   "notes":"Wide cross-industry band; service businesses ~20%, retail ~70-80%."},
  {"metric_domain":"p_and_l","metric_key":"gross_margin_percent","metric_label":"Gross margin","unit":"ratio",
   "benchmark_min":0.20,"benchmark_target":0.45,"benchmark_max":0.80},
  {"metric_domain":"p_and_l","metric_key":"net_income_margin","metric_label":"Net income margin","unit":"ratio",
   "benchmark_min":0.02,"benchmark_target":0.07,"benchmark_max":0.15},
  {"metric_domain":"p_and_l","metric_key":"sga_percent_of_revenue","metric_label":"SG&A / revenue","unit":"ratio",
   "benchmark_min":0.05,"benchmark_target":0.15,"benchmark_max":0.30},
  {"metric_domain":"p_and_l","metric_key":"r_and_d_percent_of_revenue","metric_label":"R&D / revenue","unit":"ratio",
   "benchmark_min":0.0,"benchmark_target":0.0,"benchmark_max":0.20,
   "notes":"Most industries 0; tech can hit 15-20%."},
  {"metric_domain":"p_and_l","metric_key":"depreciation_percent_of_revenue","metric_label":"Depreciation / revenue","unit":"ratio",
   "benchmark_min":0.005,"benchmark_target":0.03,"benchmark_max":0.12},
  {"metric_domain":"p_and_l","metric_key":"interest_coverage","metric_label":"EBIT / interest expense","unit":"ratio",
   "benchmark_min":2.0,"benchmark_target":6.0,"benchmark_max":20.0},
  {"metric_domain":"p_and_l","metric_key":"rent_percent_of_revenue","metric_label":"Operating rent / revenue","unit":"ratio",
   "benchmark_min":0.010,"benchmark_target":0.040,"benchmark_max":0.120,
   "notes":"Cross-industry typical; retail/restaurants 5-12%, manufacturing 1-3%, services 3-7%. Replaced by NAICS-2 expert default for any sector with that data."},
  {"metric_domain":"p_and_l","metric_key":"lease_percent_of_revenue","metric_label":"Operating lease / revenue","unit":"ratio",
   "benchmark_min":0.005,"benchmark_target":0.020,"benchmark_max":0.060,
   "notes":"Cross-industry typical for equipment/vehicle operating leases. Transportation higher (3-10%)."},
  {"metric_domain":"p_and_l","metric_key":"occupancy_total_percent_of_revenue","metric_label":"Rent + lease combined / revenue","unit":"ratio",
   "benchmark_min":0.020,"benchmark_target":0.060,"benchmark_max":0.150,
   "notes":"Combined rent + operating lease as % of revenue."},
  {"metric_domain":"p_and_l","metric_key":"ebitda_margin","metric_label":"EBITDA margin","unit":"ratio",
   "benchmark_min":0.05,"benchmark_target":0.15,"benchmark_max":0.30},
  {"metric_domain":"p_and_l","metric_key":"operating_margin_percent","metric_label":"Operating margin","unit":"ratio",
   "benchmark_min":0.03,"benchmark_target":0.10,"benchmark_max":0.20},
  # Balance sheet
  {"metric_domain":"balance_sheet","metric_key":"ar_days_dso","metric_label":"DSO","unit":"days",
   "benchmark_min":15.0,"benchmark_target":40.0,"benchmark_max":75.0},
  {"metric_domain":"balance_sheet","metric_key":"ap_days_dpo","metric_label":"DPO","unit":"days",
   "benchmark_min":15.0,"benchmark_target":35.0,"benchmark_max":60.0},
  {"metric_domain":"balance_sheet","metric_key":"inventory_days","metric_label":"Inventory days","unit":"days",
   "benchmark_min":10.0,"benchmark_target":45.0,"benchmark_max":120.0,
   "notes":"Service businesses near 0; retail/manufacturing 30-120."},
  {"metric_domain":"balance_sheet","metric_key":"current_ratio","metric_label":"Current ratio","unit":"ratio",
   "benchmark_min":1.0,"benchmark_target":1.8,"benchmark_max":3.0},
  {"metric_domain":"balance_sheet","metric_key":"quick_ratio","metric_label":"Quick ratio","unit":"ratio",
   "benchmark_min":0.5,"benchmark_target":1.0,"benchmark_max":2.0},
  {"metric_domain":"balance_sheet","metric_key":"debt_to_equity","metric_label":"Debt / equity","unit":"ratio",
   "benchmark_min":0.2,"benchmark_target":1.0,"benchmark_max":2.5},
  {"metric_domain":"balance_sheet","metric_key":"debt_to_assets","metric_label":"Debt / assets","unit":"ratio",
   "benchmark_min":0.1,"benchmark_target":0.4,"benchmark_max":0.7},
  {"metric_domain":"balance_sheet","metric_key":"ppe_percent_of_revenue","metric_label":"PP&E / revenue","unit":"ratio",
   "benchmark_min":0.05,"benchmark_target":0.30,"benchmark_max":1.50},
  {"metric_domain":"balance_sheet","metric_key":"total_assets_to_revenue","metric_label":"Total assets / revenue","unit":"ratio",
   "benchmark_min":0.40,"benchmark_target":1.20,"benchmark_max":3.00},
  {"metric_domain":"balance_sheet","metric_key":"owners_capital_percent_of_assets","metric_label":"Equity / assets","unit":"ratio",
   "benchmark_min":0.20,"benchmark_target":0.45,"benchmark_max":0.70},
  {"metric_domain":"balance_sheet","metric_key":"prepaid_expenses_percent_of_revenue","metric_label":"Prepaids / revenue","unit":"ratio",
   "benchmark_min":0.005,"benchmark_target":0.02,"benchmark_max":0.05},
  {"metric_domain":"balance_sheet","metric_key":"deferred_revenue_percent_of_revenue","metric_label":"Deferred revenue / revenue","unit":"ratio",
   "benchmark_min":0.0,"benchmark_target":0.0,"benchmark_max":0.15,
   "notes":"Subscription/SaaS/membership only; otherwise 0."},
  # Cash flow
  {"metric_domain":"cash_flow","metric_key":"capex_percent_of_revenue","metric_label":"CapEx / revenue","unit":"ratio",
   "benchmark_min":0.005,"benchmark_target":0.04,"benchmark_max":0.12},
  {"metric_domain":"cash_flow","metric_key":"maintenance_capex_percent_of_revenue","metric_label":"Maintenance CapEx / revenue","unit":"ratio",
   "benchmark_min":0.003,"benchmark_target":0.02,"benchmark_max":0.06},
  {"metric_domain":"cash_flow","metric_key":"distributions_percent_of_net_income","metric_label":"Owner distributions / net income","unit":"ratio",
   "benchmark_min":0.0,"benchmark_target":0.30,"benchmark_max":0.80,
   "notes":"Pass-through entities distribute heavily; C-corps less so."},
  # Workforce
  {"metric_domain":"workforce","metric_key":"avg_wage_per_fte","metric_label":"Avg wage per FTE","unit":"usd",
   "benchmark_min":35000.0,"benchmark_target":58000.0,"benchmark_max":90000.0,
   "notes":"BLS national avg ~$59K (2022). Tech ~$110K, retail ~$32K."},
  {"metric_domain":"workforce","metric_key":"revenue_per_fte","metric_label":"Revenue per FTE","unit":"usd",
   "benchmark_min":80000.0,"benchmark_target":250000.0,"benchmark_max":600000.0,
   "notes":"Highly variable; SaaS often $400K+, retail $150-250K, restaurants $80-120K."},
  {"metric_domain":"workforce","metric_key":"payroll_percent_of_revenue","metric_label":"Payroll / revenue","unit":"ratio",
   "benchmark_min":0.08,"benchmark_target":0.20,"benchmark_max":0.40},
  {"metric_domain":"workforce","metric_key":"employees_per_establishment","metric_label":"Employees per establishment","unit":"count",
   "benchmark_min":3.0,"benchmark_target":15.0,"benchmark_max":50.0},
  # Capital structure
  {"metric_domain":"capital_structure","metric_key":"sba_initial_interest_rate","metric_label":"Typical small-business loan rate","unit":"ratio",
   "benchmark_min":0.06,"benchmark_target":0.085,"benchmark_max":0.12},
  {"metric_domain":"capital_structure","metric_key":"sba_typical_loan_size","metric_label":"Typical small-business loan size","unit":"usd",
   "benchmark_min":50000.0,"benchmark_target":250000.0,"benchmark_max":1000000.0},
  {"metric_domain":"capital_structure","metric_key":"sba_typical_loan_term_months","metric_label":"Typical loan term (months)","unit":"count",
   "benchmark_min":60.0,"benchmark_target":120.0,"benchmark_max":300.0},
  # Stage ramp
  {"metric_domain":"stage_ramp","metric_key":"year1_to_year5_employment_ratio","metric_label":"Y5/Y0 employment growth","unit":"ratio",
   "benchmark_min":1.0,"benchmark_target":3.0,"benchmark_max":10.0},
  {"metric_domain":"stage_ramp","metric_key":"startup_year1_exit_rate","metric_label":"Year-1 startup exit rate","unit":"percent",
   "benchmark_min":15.0,"benchmark_target":25.0,"benchmark_max":40.0,
   "notes":"BDS national avg ~20-30% Y1 exit."},
  {"metric_domain":"stage_ramp","metric_key":"mature_exit_rate","metric_label":"Mature firm exit rate","unit":"percent",
   "benchmark_min":3.0,"benchmark_target":7.0,"benchmark_max":12.0},
  {"metric_domain":"stage_ramp","metric_key":"startup_qoq_growth_typical","metric_label":"Startup QoQ revenue growth","unit":"ratio",
   "benchmark_min":0.05,"benchmark_target":0.20,"benchmark_max":0.50,
   "notes":"5-50% QoQ in startup phase typical."},
  {"metric_domain":"stage_ramp","metric_key":"early_qoq_growth_typical","metric_label":"Early-stage QoQ growth","unit":"ratio",
   "benchmark_min":0.03,"benchmark_target":0.08,"benchmark_max":0.20},
  {"metric_domain":"stage_ramp","metric_key":"mature_qoq_growth_typical","metric_label":"Mature QoQ growth","unit":"ratio",
   "benchmark_min":0.005,"benchmark_target":0.015,"benchmark_max":0.05},
]


def load_derived_workforce_metrics(cur) -> int:
  """Cross-source derivations: payroll_percent_of_revenue and revenue_per_fte.

  These are the metrics most directly tied to the realism gap (FTE-too-low
  for revenue level). We join CBP (payroll + employment) with SOI (revenue) at
  every NAICS level both cover, then derive:
    payroll_percent_of_revenue = CBP.pay_ann*1000 / SOI.business_receipts
    revenue_per_fte             = SOI.business_receipts / CBP.emp
  """
  rows_to_insert: List[Dict[str, Any]] = []

  # Pull CBP aggregated by NAICS at native level (variable-length)
  cur.execute(
    """
    SELECT naics, naics_label,
           SUM(estab) AS estab,
           SUM(emp) AS emp,
           SUM(pay_ann) AS pay_ann_thousands
    FROM cbp_2022_raw
    WHERE naics IS NOT NULL AND naics <> '' AND naics <> '------'
    GROUP BY naics, naics_label
    """
  )
  cbp_by_naics: Dict[str, Dict[str, Any]] = {}
  for r in cur.fetchall():
    raw = str(r["naics"] or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits or len(digits) < 2:
      continue
    cbp_by_naics[digits] = {
      "title": str(r.get("naics_label") or "").strip()[:255] or None,
      "level": len(digits),
      "estab": int(_to_float(r.get("estab")) or 0),
      "emp": int(_to_float(r.get("emp")) or 0),
      "pay_thousands": int(_to_float(r.get("pay_ann_thousands")) or 0),
    }

  # Pull SOI revenue (business_receipts) keyed by every NAICS level present
  cur.execute(
    "SELECT business_receipts, naics_2_digit, naics_3_digit, naics_4_digit, "
    "       naics_5_digit, naics_6_digit, with_net_income, naics_title "
    "FROM SOI_corporate_tax_returns "
    "WHERE business_receipts IS NOT NULL AND business_receipts > 0"
  )
  # SOI revenue stored at the level where the row's NAICS column was non-padded.
  # Aggregate revenue per NAICS code at each level (sum across sub-rows).
  soi_revenue_by_level_code: Dict[Tuple[int, str], Dict[str, Any]] = {}
  for r in cur.fetchall():
    receipts = _to_float(r.get("business_receipts")) or 0.0
    sample = int(_to_float(r.get("with_net_income")) or 0)
    title = str(r.get("naics_title") or "").strip()[:255] or None
    for col, lvl in (
      ("naics_6_digit", 6), ("naics_5_digit", 5), ("naics_4_digit", 4),
      ("naics_3_digit", 3), ("naics_2_digit", 2),
    ):
      code = _normalize_naics(r.get(col), lvl)
      if not code:
        continue
      bucket = soi_revenue_by_level_code.setdefault(
        (lvl, code), {"revenue": 0.0, "sample": 0, "title": title}
      )
      bucket["revenue"] += receipts
      bucket["sample"] += sample
      if not bucket["title"] and title:
        bucket["title"] = title

  # CBP at NAICS level X joins SOI revenue at the same NAICS level X.
  # We try CBP's native level first; if no SOI match, we don't downgrade
  # (caller's resolver handles fallback).
  for cbp_code, cbp_data in cbp_by_naics.items():
    level = cbp_data["level"]
    soi_match = soi_revenue_by_level_code.get((level, cbp_code))
    if not soi_match or soi_match["revenue"] <= 0:
      continue
    soi_revenue_thousands = soi_match["revenue"]  # SOI receipts in $1000s
    cbp_pay_thousands = cbp_data["pay_thousands"]
    cbp_emp = cbp_data["emp"]
    if cbp_emp <= 0 or cbp_pay_thousands <= 0:
      continue

    # Both SOI and CBP report dollar amounts in thousands.
    payroll_dollars = cbp_pay_thousands * 1000.0
    revenue_dollars = soi_revenue_thousands * 1000.0

    payroll_pct = payroll_dollars / revenue_dollars
    revenue_per_fte = revenue_dollars / cbp_emp

    sample = min(cbp_data["estab"], soi_match["sample"]) or cbp_data["estab"] or soi_match["sample"]
    confidence = _confidence_for_sample(sample_size=sample, high_floor=200, medium_floor=30)
    if level <= 3 and confidence == "high":
      confidence = "medium"
    title = cbp_data["title"] or soi_match["title"]

    if 0.0 < payroll_pct < 1.5:
      rows_to_insert.append(
        {
          "naics_code": cbp_code,
          "naics_level": level,
          "naics_title": title,
          "metric_domain": "workforce",
          "metric_key": "payroll_percent_of_revenue",
          "metric_label": "Payroll / revenue (CBP payroll, SOI revenue)",
          "unit": "ratio",
          "benchmark_target": float(payroll_pct),
          "data_source": "derived_CBP_SOI",
          "source_year": 2022,
          "sample_size": sample,
          "confidence_tier": confidence,
          "derivation_formula": "CBP.pay_ann*1000 / SOI.business_receipts (both reported in thousands)",
          "notes": "Cross-source derivation: CBP 2022 payroll over SOI receipts at same NAICS level.",
        }
      )
    if revenue_per_fte > 1000.0:
      rows_to_insert.append(
        {
          "naics_code": cbp_code,
          "naics_level": level,
          "naics_title": title,
          "metric_domain": "workforce",
          "metric_key": "revenue_per_fte",
          "metric_label": "Revenue per FTE (SOI revenue / CBP employment)",
          "unit": "usd",
          "benchmark_target": float(revenue_per_fte),
          "data_source": "derived_CBP_SOI",
          "source_year": 2022,
          "sample_size": sample,
          "confidence_tier": confidence,
          "derivation_formula": "SOI.business_receipts*1000 / CBP.emp",
          "notes": "Cross-source derivation: SOI receipts over CBP employment at same NAICS level.",
        }
      )
      rows_to_insert.append(
        {
          "naics_code": cbp_code,
          "naics_level": level,
          "naics_title": title,
          "metric_domain": "workforce",
          "metric_key": "fte_per_million_revenue",
          "metric_label": "FTEs needed per $1M revenue",
          "unit": "fte_per_million_rev",
          "benchmark_target": 1_000_000.0 / float(revenue_per_fte),
          "data_source": "derived_CBP_SOI",
          "source_year": 2022,
          "sample_size": sample,
          "confidence_tier": confidence,
          "derivation_formula": "1,000,000 / revenue_per_fte",
          "notes": "Inverse of revenue_per_fte; the realism floor for FTE sizing.",
        }
      )

  return _insert_baseline_rows(cur, rows_to_insert, source_label="derived_CBP_SOI")


def load_from_sec_edgar(cur) -> int:
  """Aggregate `sec_edgar_facts` (raw XBRL pull) into NAICS-keyed baseline rows.

  For each (CIK, fiscal_period) we have a snapshot of multiple GAAP concepts.
  We form ratios by pairing a numerator concept with same-period revenue, then
  aggregate ratios to NAICS-6/5/4/3/2 via P25/P50/P75 bands.

  All joins/aggregation happen here in the loader. Production runtime never
  touches sec_edgar_facts.
  """
  rows_to_insert: List[Dict[str, Any]] = []

  # 1) Build (cik, fiscal_period) -> revenue map, preferring the most-specific
  #    revenue concept when both are reported.
  cur.execute(
    """
    SELECT cik, fiscal_period, naics_code, concept_name, value
    FROM sec_edgar_facts
    WHERE concept_name IN ('RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues')
      AND value IS NOT NULL AND value > 0
      AND naics_code IS NOT NULL AND naics_code <> ''
      AND is_instant = 0
    """
  )
  revenue_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
  for r in cur.fetchall():
    cik = str(r["cik"] or "").strip()
    fp = str(r["fiscal_period"] or "").strip()
    if not cik or not fp:
      continue
    naics = "".join(ch for ch in str(r["naics_code"] or "") if ch.isdigit())
    if len(naics) < 6:
      continue
    val = _to_float(r["value"])
    if val is None or val <= 0:
      continue
    key = (cik, fp)
    existing = revenue_by_key.get(key)
    # Prefer RevenueFromContractWithCustomer over Revenues (more specific post-ASC 606)
    if existing is None or (
      r["concept_name"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
      and existing.get("concept") != "RevenueFromContractWithCustomerExcludingAssessedTax"
    ):
      revenue_by_key[key] = {"value": val, "naics": naics[:6], "concept": r["concept_name"]}

  if not revenue_by_key:
    print("  [SEC_EDGAR] no revenue rows found; skipping aggregation")
    return 0
  print(f"  [SEC_EDGAR] revenue index built: {len(revenue_by_key)} (cik, period) pairs")

  # 2) Helper to pair numerator concept with revenue and emit one ratio per
  #    (cik, fiscal_period) pair. Returns list of (naics_6, ratio).
  def _ratios_for(
    *,
    numerator_concepts: List[str],
    instant: bool,
    annualize_quarterly_revenue: bool,
    sum_within_cik_period: bool = False,
    upper_bound: float = 5.0,
    lower_bound: float = -1.0,
  ) -> List[Tuple[str, float]]:
    placeholders = ",".join(["%s"] * len(numerator_concepts))
    cur.execute(
      f"""
      SELECT cik, fiscal_period, naics_code, concept_name, value
      FROM sec_edgar_facts
      WHERE concept_name IN ({placeholders})
        AND value IS NOT NULL
        AND naics_code IS NOT NULL AND naics_code <> ''
        AND is_instant = %s
      """,
      tuple(numerator_concepts) + (1 if instant else 0,),
    )
    by_key_concepts: Dict[Tuple[str, str], Dict[str, float]] = {}
    naics_by_key: Dict[Tuple[str, str], str] = {}
    for r in cur.fetchall():
      cik = str(r["cik"] or "").strip()
      fp = str(r["fiscal_period"] or "").strip()
      naics = "".join(ch for ch in str(r["naics_code"] or "") if ch.isdigit())
      if not cik or not fp or len(naics) < 6:
        continue
      val = _to_float(r["value"])
      if val is None:
        continue
      # If instant, fiscal_period ends in 'I'; pair with the duration period that
      # has the same Q (e.g., CY2024Q1I -> CY2024Q1).
      pair_fp = fp.rstrip("I")
      key = (cik, pair_fp)
      bucket = by_key_concepts.setdefault(key, {})
      bucket[r["concept_name"]] = val
      naics_by_key.setdefault(key, naics[:6])
    out: List[Tuple[str, float]] = []
    for key, concept_values in by_key_concepts.items():
      revenue_entry = revenue_by_key.get(key)
      if not revenue_entry:
        continue
      revenue_val = float(revenue_entry["value"])
      if revenue_val <= 0:
        continue
      naics = naics_by_key.get(key) or revenue_entry.get("naics")
      if not naics:
        continue
      if sum_within_cik_period:
        numerator_value = sum(float(v) for v in concept_values.values() if v is not None)
      else:
        numerator_value = max(
          (float(v) for v in concept_values.values() if v is not None),
          default=0.0,
        )
      denom = revenue_val * 4.0 if annualize_quarterly_revenue else revenue_val
      if denom <= 0:
        continue
      ratio = numerator_value / denom
      if ratio < lower_bound or ratio > upper_bound:
        continue
      out.append((naics, ratio))
    return out

  def _percentile(values: List[float], pct: float) -> float:
    s = sorted(values)
    if not s:
      return 0.0
    if len(s) == 1:
      return s[0]
    k = (len(s) - 1) * pct
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
      return s[int(k)]
    return s[f] + (s[c] - s[f]) * (k - f)

  def _emit_naics_aggregates(
    *,
    raw_obs: List[Tuple[str, float]],
    metric_domain: str,
    metric_key: str,
    metric_label: str,
    unit: str,
    derivation_formula: str,
    notes: str,
    high_floor: int = 30,
    medium_floor: int = 8,
  ) -> None:
    if not raw_obs:
      return
    by_level: Dict[int, Dict[str, List[float]]] = {lvl: {} for lvl in (6, 5, 4, 3, 2)}
    for naics_6, ratio in raw_obs:
      for level in (6, 5, 4, 3, 2):
        key = naics_6[:level]
        by_level[level].setdefault(key, []).append(float(ratio))
    for level, groups in by_level.items():
      for naics_code, observations in groups.items():
        if len(observations) < 4:
          continue
        confidence = _confidence_for_sample(
          sample_size=len(observations), high_floor=high_floor, medium_floor=medium_floor,
        )
        if level <= 3 and confidence == "high":
          confidence = "medium"
        rows_to_insert.append(
          {
            "naics_code": naics_code,
            "naics_level": level,
            "naics_title": None,
            "metric_domain": metric_domain,
            "metric_key": metric_key,
            "metric_label": metric_label,
            "unit": unit,
            "benchmark_min": _percentile(observations, 0.25),
            "benchmark_target": _percentile(observations, 0.50),
            "benchmark_max": _percentile(observations, 0.75),
            "data_source": "SEC_EDGAR",
            "source_year": 2024,
            "sample_size": len(observations),
            "confidence_tier": confidence,
            "derivation_formula": derivation_formula,
            "notes": notes,
          }
        )

  # 3) Define metric mappings and aggregate

  # Deferred revenue (annualized quarterly revenue as denominator for instant balance)
  _emit_naics_aggregates(
    raw_obs=_ratios_for(
      numerator_concepts=[
        "DeferredRevenueCurrent",
        "DeferredRevenueNoncurrent",
        "DeferredRevenue",
        "ContractWithCustomerLiabilityCurrent",
        "ContractWithCustomerLiabilityNoncurrent",
        "ContractWithCustomerLiability",
      ],
      instant=True,
      annualize_quarterly_revenue=True,
      sum_within_cik_period=False,  # MAX across the alternative tags (DeferredRevenue OR ContractWithCustomerLiability, not both)
      upper_bound=2.0, lower_bound=0.0,
    ),
    metric_domain="balance_sheet",
    metric_key="deferred_revenue_percent_of_revenue",
    metric_label="Deferred revenue / annualized revenue",
    unit="ratio",
    derivation_formula="MAX(DeferredRevenue* OR ContractWithCustomerLiability*) / (Revenues * 4)",
    notes="From SEC EDGAR XBRL Frames; pairs balance-sheet snapshot with annualized same-quarter revenue.",
  )

  # Prepaid expenses
  _emit_naics_aggregates(
    raw_obs=_ratios_for(
      numerator_concepts=[
        "PrepaidExpenseCurrent",
        "PrepaidExpenseAndOtherAssetsCurrent",
        "PrepaidExpenseAndOtherAssets",
      ],
      instant=True,
      annualize_quarterly_revenue=True,
      sum_within_cik_period=False,
      upper_bound=1.0, lower_bound=0.0,
    ),
    metric_domain="balance_sheet",
    metric_key="prepaid_expenses_percent_of_revenue",
    metric_label="Prepaid expenses / annualized revenue",
    unit="ratio",
    derivation_formula="MAX(PrepaidExpenseCurrent OR PrepaidExpenseAndOther*) / (Revenues * 4)",
    notes="From SEC EDGAR XBRL Frames.",
  )

  # Marketing / advertising (separate metric_keys for each disclosure flavor)
  _emit_naics_aggregates(
    raw_obs=_ratios_for(
      numerator_concepts=["AdvertisingExpense"],
      instant=False, annualize_quarterly_revenue=False, upper_bound=1.0, lower_bound=0.0,
    ),
    metric_domain="p_and_l", metric_key="advertising_percent_of_revenue",
    metric_label="Advertising expense / revenue", unit="ratio",
    derivation_formula="AdvertisingExpense / Revenues (per quarter)",
    notes="From SEC EDGAR XBRL Frames; advertising is a subset of marketing for most filers.",
  )
  _emit_naics_aggregates(
    raw_obs=_ratios_for(
      numerator_concepts=["MarketingExpense", "MarketingAndAdvertisingExpense", "SellingAndMarketingExpense"],
      instant=False, annualize_quarterly_revenue=False, upper_bound=1.0, lower_bound=0.0,
    ),
    metric_domain="p_and_l", metric_key="marketing_percent_of_revenue",
    metric_label="Marketing expense / revenue", unit="ratio",
    derivation_formula="MAX(MarketingExpense | MarketingAndAdvertisingExpense | SellingAndMarketingExpense) / Revenues",
    notes="From SEC EDGAR XBRL Frames; takes the largest reported marketing variant (some firms split selling and marketing, some combine).",
  )

  # Operating lease / rent expense (the actual NAICS-direct rent we wanted)
  _emit_naics_aggregates(
    raw_obs=_ratios_for(
      numerator_concepts=["OperatingLeaseExpense", "OperatingLeasesRentExpenseNet", "LeaseAndRentalExpense"],
      instant=False, annualize_quarterly_revenue=False, upper_bound=1.0, lower_bound=0.0,
    ),
    metric_domain="p_and_l", metric_key="rent_percent_of_revenue",
    metric_label="Operating lease/rent expense / revenue (SEC EDGAR data-backed)", unit="ratio",
    derivation_formula="MAX(OperatingLeaseExpense | OperatingLeasesRentExpenseNet | LeaseAndRentalExpense) / Revenues",
    notes="From SEC EDGAR XBRL Frames; data-backed alternative to the expert NAICS-2 default. Cascade prefers high-confidence rows.",
  )

  # R&D from EDGAR (augments industry_metrics_raw at NAICS-6)
  _emit_naics_aggregates(
    raw_obs=_ratios_for(
      numerator_concepts=["ResearchAndDevelopmentExpense"],
      instant=False, annualize_quarterly_revenue=False, upper_bound=2.0, lower_bound=0.0,
    ),
    metric_domain="p_and_l", metric_key="r_and_d_percent_of_revenue",
    metric_label="R&D expense / revenue", unit="ratio",
    derivation_formula="ResearchAndDevelopmentExpense / Revenues",
    notes="From SEC EDGAR XBRL Frames.",
  )

  # SG&A
  _emit_naics_aggregates(
    raw_obs=_ratios_for(
      numerator_concepts=["SellingGeneralAndAdministrativeExpense", "GeneralAndAdministrativeExpense"],
      instant=False, annualize_quarterly_revenue=False, upper_bound=2.0, lower_bound=0.0,
    ),
    metric_domain="p_and_l", metric_key="sga_percent_of_revenue",
    metric_label="SG&A expense / revenue", unit="ratio",
    derivation_formula="MAX(SG&A | G&A) / Revenues",
    notes="From SEC EDGAR XBRL Frames.",
  )

  # COGS
  _emit_naics_aggregates(
    raw_obs=_ratios_for(
      numerator_concepts=["CostOfRevenue", "CostOfGoodsAndServicesSold"],
      instant=False, annualize_quarterly_revenue=False, upper_bound=2.0, lower_bound=0.0,
    ),
    metric_domain="p_and_l", metric_key="cogs_percent_of_revenue",
    metric_label="COGS / revenue", unit="ratio",
    derivation_formula="MAX(CostOfRevenue | CostOfGoodsAndServicesSold) / Revenues",
    notes="From SEC EDGAR XBRL Frames.",
  )

  # Effective tax rate (income tax / pretax income)
  cur.execute(
    """
    SELECT cik, fiscal_period, naics_code, concept_name, value
    FROM sec_edgar_facts
    WHERE concept_name IN (
      'IncomeTaxExpenseBenefit',
      'IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest'
    )
    AND value IS NOT NULL
    AND naics_code IS NOT NULL AND naics_code <> ''
    AND is_instant = 0
    """
  )
  by_key_etr: Dict[Tuple[str, str], Dict[str, float]] = {}
  naics_by_key_etr: Dict[Tuple[str, str], str] = {}
  for r in cur.fetchall():
    cik = str(r["cik"] or "").strip()
    fp = str(r["fiscal_period"] or "").strip()
    naics = "".join(ch for ch in str(r["naics_code"] or "") if ch.isdigit())
    if not cik or not fp or len(naics) < 6:
      continue
    val = _to_float(r["value"])
    if val is None:
      continue
    key = (cik, fp)
    by_key_etr.setdefault(key, {})[r["concept_name"]] = val
    naics_by_key_etr.setdefault(key, naics[:6])
  etr_obs: List[Tuple[str, float]] = []
  for key, concepts in by_key_etr.items():
    pretax = concepts.get(
      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"
    )
    tax = concepts.get("IncomeTaxExpenseBenefit")
    if pretax is None or tax is None or pretax <= 0:
      continue
    etr = tax / pretax
    if etr < 0 or etr > 0.6:
      continue
    naics = naics_by_key_etr.get(key)
    if naics:
      etr_obs.append((naics, etr))
  _emit_naics_aggregates(
    raw_obs=etr_obs,
    metric_domain="p_and_l", metric_key="effective_tax_rate",
    metric_label="Effective tax rate (SEC EDGAR data-backed)",
    unit="ratio",
    derivation_formula="IncomeTaxExpenseBenefit / IncomeLossFromContinuingOperationsBeforeIncomeTax... per quarter, filtered pretax>0 and 0<=etr<=60%",
    notes="From SEC EDGAR XBRL Frames; complements IRS_SOI and alpha_data effective tax rates.",
  )

  # Distributions / net income
  cur.execute(
    """
    SELECT cik, fiscal_period, naics_code, concept_name, value
    FROM sec_edgar_facts
    WHERE concept_name IN ('PaymentsOfDividends', 'PaymentsOfDividendsCommonStock', 'NetIncomeLoss')
      AND value IS NOT NULL
      AND naics_code IS NOT NULL AND naics_code <> ''
      AND is_instant = 0
    """
  )
  by_key_dist: Dict[Tuple[str, str], Dict[str, float]] = {}
  naics_by_key_dist: Dict[Tuple[str, str], str] = {}
  for r in cur.fetchall():
    cik = str(r["cik"] or "").strip()
    fp = str(r["fiscal_period"] or "").strip()
    naics = "".join(ch for ch in str(r["naics_code"] or "") if ch.isdigit())
    if not cik or not fp or len(naics) < 6:
      continue
    val = _to_float(r["value"])
    if val is None:
      continue
    key = (cik, fp)
    by_key_dist.setdefault(key, {})[r["concept_name"]] = val
    naics_by_key_dist.setdefault(key, naics[:6])
  dist_obs: List[Tuple[str, float]] = []
  for key, concepts in by_key_dist.items():
    dividends = max(
      float(concepts.get("PaymentsOfDividends") or 0.0),
      float(concepts.get("PaymentsOfDividendsCommonStock") or 0.0),
    )
    ni = concepts.get("NetIncomeLoss")
    if ni is None or ni <= 0 or dividends < 0:
      continue
    ratio = dividends / ni
    if ratio < 0 or ratio > 3.0:
      continue
    naics = naics_by_key_dist.get(key)
    if naics:
      dist_obs.append((naics, ratio))
  _emit_naics_aggregates(
    raw_obs=dist_obs,
    metric_domain="cash_flow", metric_key="distributions_percent_of_net_income",
    metric_label="Dividends / net income", unit="ratio",
    derivation_formula="MAX(PaymentsOfDividends, PaymentsOfDividendsCommonStock) / NetIncomeLoss; filter ni>0 and 0<=ratio<=300%",
    notes="From SEC EDGAR XBRL Frames; complements alpha_data distributions.",
  )

  # Capital expenditures
  _emit_naics_aggregates(
    raw_obs=_ratios_for(
      numerator_concepts=["PaymentsToAcquirePropertyPlantAndEquipment"],
      instant=False, annualize_quarterly_revenue=False, upper_bound=2.0, lower_bound=0.0,
    ),
    metric_domain="cash_flow", metric_key="capex_percent_of_revenue",
    metric_label="CapEx / revenue (SEC EDGAR data-backed)", unit="ratio",
    derivation_formula="PaymentsToAcquirePropertyPlantAndEquipment / Revenues",
    notes="From SEC EDGAR XBRL Frames.",
  )

  # Operating cash flow margin
  _emit_naics_aggregates(
    raw_obs=_ratios_for(
      numerator_concepts=["NetCashProvidedByUsedInOperatingActivities"],
      instant=False, annualize_quarterly_revenue=False, upper_bound=2.0, lower_bound=-2.0,
    ),
    metric_domain="cash_flow", metric_key="operating_cash_flow_margin",
    metric_label="Operating cash flow / revenue", unit="ratio",
    derivation_formula="NetCashProvidedByUsedInOperatingActivities / Revenues",
    notes="From SEC EDGAR XBRL Frames; new metric not previously covered.",
  )

  # PP&E / revenue (annualized)
  _emit_naics_aggregates(
    raw_obs=_ratios_for(
      numerator_concepts=["PropertyPlantAndEquipmentNet"],
      instant=True, annualize_quarterly_revenue=True, upper_bound=20.0, lower_bound=0.0,
    ),
    metric_domain="balance_sheet", metric_key="ppe_percent_of_revenue",
    metric_label="PP&E / annualized revenue", unit="ratio",
    derivation_formula="PropertyPlantAndEquipmentNet / (Revenues * 4)",
    notes="From SEC EDGAR XBRL Frames.",
  )

  # Stock-based compensation as % of revenue
  _emit_naics_aggregates(
    raw_obs=_ratios_for(
      numerator_concepts=["ShareBasedCompensation"],
      instant=False, annualize_quarterly_revenue=False, upper_bound=1.0, lower_bound=0.0,
    ),
    metric_domain="p_and_l", metric_key="stock_based_compensation_percent_of_revenue",
    metric_label="Stock-based compensation / revenue", unit="ratio",
    derivation_formula="ShareBasedCompensation / Revenues",
    notes="From SEC EDGAR XBRL Frames; new metric not previously covered.",
  )

  return _insert_baseline_rows(cur, rows_to_insert, source_label="SEC_EDGAR")


# ---------------------------------------------------------------------------
# Expert NAICS-2 defaults for rent and lease (no public NAICS-keyed source
# available in the loaded data; values sourced from commonly-cited industry
# operating expense studies, IBISWorld profiles, and industry trade group
# reports). Confidence = 'low' because these are research-derived rather than
# data-aggregated. The cascade resolver picks these up at NAICS-2 fallback when
# a more-specific NAICS-3/4/5/6 row is unavailable.
# ---------------------------------------------------------------------------

EXPERT_NAICS2_RENT_LEASE_DEFAULTS: List[Tuple[str, str, float, float, float, float, float, float]] = [
  # (naics_2, title, rent_min, rent_target, rent_max, lease_min, lease_target, lease_max)
  ("11", "Agriculture, Forestry, Fishing and Hunting",         0.005, 0.015, 0.030,   0.005, 0.015, 0.030),
  ("21", "Mining, Quarrying, and Oil and Gas Extraction",      0.005, 0.012, 0.025,   0.010, 0.025, 0.050),
  ("22", "Utilities",                                          0.003, 0.008, 0.015,   0.010, 0.020, 0.040),
  ("23", "Construction",                                       0.005, 0.020, 0.040,   0.020, 0.040, 0.080),
  ("31", "Manufacturing",                                      0.010, 0.020, 0.040,   0.005, 0.015, 0.030),
  ("32", "Manufacturing",                                      0.010, 0.020, 0.040,   0.005, 0.015, 0.030),
  ("33", "Manufacturing",                                      0.010, 0.020, 0.040,   0.005, 0.015, 0.030),
  ("42", "Wholesale Trade",                                    0.020, 0.030, 0.050,   0.010, 0.020, 0.040),
  ("44", "Retail Trade",                                       0.040, 0.075, 0.120,   0.005, 0.015, 0.030),
  ("45", "Retail Trade",                                       0.040, 0.075, 0.120,   0.005, 0.015, 0.030),
  ("48", "Transportation and Warehousing",                     0.020, 0.040, 0.080,   0.030, 0.060, 0.100),
  ("49", "Transportation and Warehousing",                     0.020, 0.040, 0.080,   0.030, 0.060, 0.100),
  ("51", "Information",                                        0.020, 0.040, 0.070,   0.005, 0.015, 0.030),
  ("52", "Finance and Insurance",                              0.030, 0.060, 0.090,   0.005, 0.015, 0.030),
  ("53", "Real Estate and Rental and Leasing",                 0.040, 0.080, 0.150,   0.020, 0.040, 0.080),
  ("54", "Professional, Scientific, and Technical Services",   0.030, 0.055, 0.090,   0.005, 0.015, 0.030),
  ("55", "Management of Companies and Enterprises",            0.020, 0.040, 0.070,   0.005, 0.015, 0.030),
  ("56", "Administrative and Support and Waste Management",    0.020, 0.040, 0.070,   0.010, 0.025, 0.050),
  ("61", "Educational Services",                               0.030, 0.060, 0.100,   0.010, 0.025, 0.050),
  ("62", "Health Care and Social Assistance",                  0.040, 0.075, 0.120,   0.010, 0.025, 0.050),
  ("71", "Arts, Entertainment, and Recreation",                0.040, 0.080, 0.150,   0.010, 0.025, 0.050),
  ("72", "Accommodation and Food Services",                    0.050, 0.090, 0.140,   0.010, 0.025, 0.050),
  ("81", "Other Services (except Public Administration)",      0.030, 0.060, 0.100,   0.010, 0.025, 0.050),
  ("92", "Public Administration",                              0.020, 0.040, 0.070,   0.005, 0.015, 0.030),
]


def load_expert_rent_lease_defaults(cur) -> int:
  """Insert NAICS-2 expert defaults for rent and lease coverage.

  No public NAICS-keyed source for operating rent or lease expense was loaded
  in the database (IRS SOI bundles them into deductions; industry_metrics_raw
  has no rent column; alpha_data only has capitalized lease obligations on the
  balance sheet, not P&L operating rent). Until a BLS PPI for Commercial Rents
  pull or Census ACES rental-cost extract lands, these expert defaults at
  NAICS-2 give universal coverage via the cascade resolver.
  """
  rows_to_insert: List[Dict[str, Any]] = []
  for (naics_2, title, rent_min, rent_tgt, rent_max,
       lease_min, lease_tgt, lease_max) in EXPERT_NAICS2_RENT_LEASE_DEFAULTS:
    rows_to_insert.append(
      {
        "naics_code": naics_2,
        "naics_level": 2,
        "naics_title": title,
        "metric_domain": "p_and_l",
        "metric_key": "rent_percent_of_revenue",
        "metric_label": "Operating real-estate rent as % of revenue",
        "unit": "ratio",
        "benchmark_min": float(rent_min),
        "benchmark_target": float(rent_tgt),
        "benchmark_max": float(rent_max),
        "data_source": "expert_naics2_default",
        "source_year": 2024,
        "sample_size": None,
        "confidence_tier": "low",
        "derivation_formula": "Industry-typical rent intensity at NAICS-2; expert estimate from IBISWorld / industry trade studies.",
        "notes": "Research-derived NAICS-2 default; replace with BLS PPI for Commercial Rents or Census ACES rental costs when sourced.",
      }
    )
    rows_to_insert.append(
      {
        "naics_code": naics_2,
        "naics_level": 2,
        "naics_title": title,
        "metric_domain": "p_and_l",
        "metric_key": "lease_percent_of_revenue",
        "metric_label": "Operating equipment/vehicle lease as % of revenue",
        "unit": "ratio",
        "benchmark_min": float(lease_min),
        "benchmark_target": float(lease_tgt),
        "benchmark_max": float(lease_max),
        "data_source": "expert_naics2_default",
        "source_year": 2024,
        "sample_size": None,
        "confidence_tier": "low",
        "derivation_formula": "Industry-typical operating lease intensity at NAICS-2; expert estimate.",
        "notes": "Research-derived NAICS-2 default; replace with Census ACES equipment-leasing extract when sourced. Excludes balance-sheet capitalized leases (ASC 842 finance leases).",
      }
    )
    rows_to_insert.append(
      {
        "naics_code": naics_2,
        "naics_level": 2,
        "naics_title": title,
        "metric_domain": "p_and_l",
        "metric_key": "occupancy_total_percent_of_revenue",
        "metric_label": "Total occupancy and lease (rent + operating lease) as % of revenue",
        "unit": "ratio",
        "benchmark_min": float(rent_min) + float(lease_min),
        "benchmark_target": float(rent_tgt) + float(lease_tgt),
        "benchmark_max": float(rent_max) + float(lease_max),
        "data_source": "expert_naics2_default",
        "source_year": 2024,
        "sample_size": None,
        "confidence_tier": "low",
        "derivation_formula": "rent_percent + lease_percent at NAICS-2 expert default.",
        "notes": "Combined occupancy+lease intensity; matches the model_input lever 'expenses::Lease' which captures rent + operating lease together.",
      }
    )
  return _insert_baseline_rows(cur, rows_to_insert, source_label="expert_naics2_default")


def load_maintenance_capex_from_depreciation(cur) -> int:
  """maintenance_capex_percent_of_revenue is approximated from depreciation
  intensity. The accounting-economic identity is: when depreciation expense
  approximates capital reinvestment needed to keep PPE constant, depreciation
  serves as a maintenance-capex proxy. We take min(depreciation%, capex%) as
  the maintenance-capex floor per NAICS, then read depreciation% directly when
  capex% is missing.
  """
  rows_to_insert: List[Dict[str, Any]] = []

  cur.execute(
    """
    SELECT naics_code, naics_level, metric_key, benchmark_target, sample_size,
           confidence_tier, naics_title
    FROM post_intake_industry_baseline_lookup
    WHERE metric_key IN ('depreciation_percent_of_revenue','capex_percent_of_revenue')
      AND active = 1 AND naics_level >= 2
    """
  )
  by_key: Dict[Tuple[str, int], Dict[str, Any]] = {}
  for r in cur.fetchall():
    code = str(r["naics_code"] or "").strip()
    level = int(r["naics_level"] or 0)
    if not code or level < 2:
      continue
    key = (code, level)
    bucket = by_key.setdefault(key, {})
    metric = str(r["metric_key"] or "")
    if metric not in bucket:
      bucket[metric] = {
        "value": _to_float(r["benchmark_target"]),
        "sample": int(_to_float(r["sample_size"]) or 0),
        "confidence": str(r["confidence_tier"] or "low"),
        "title": r.get("naics_title"),
      }

  for (code, level), metrics in by_key.items():
    depr = metrics.get("depreciation_percent_of_revenue")
    capex = metrics.get("capex_percent_of_revenue")
    if not depr:
      continue
    depr_val = float(depr["value"] or 0.0)
    if depr_val <= 0.0:
      continue
    capex_val = float(capex["value"] or 0.0) if capex else 0.0
    maintenance_val = min(depr_val, capex_val) if capex_val > 0 else depr_val
    if maintenance_val <= 0.0:
      continue
    sample_used = depr["sample"]
    confidence_used = depr["confidence"]
    rows_to_insert.append(
      {
        "naics_code": code,
        "naics_level": level,
        "naics_title": depr.get("title"),
        "metric_domain": "cash_flow",
        "metric_key": "maintenance_capex_percent_of_revenue",
        "metric_label": "Maintenance CapEx / revenue (depreciation-as-proxy)",
        "unit": "ratio",
        "benchmark_target": float(maintenance_val),
        "data_source": "derived_depreciation_proxy",
        "source_year": 2024,
        "sample_size": sample_used,
        "confidence_tier": confidence_used,
        "derivation_formula": "min(depreciation_percent_of_revenue, capex_percent_of_revenue) per NAICS -- accounting-economic maintenance-capex proxy",
        "notes": "Maintenance capex is not directly disclosed in public filings; depreciation is the standard accounting proxy.",
      }
    )

  return _insert_baseline_rows(cur, rows_to_insert, source_label="derived_depreciation_proxy")


def load_qoq_growth_from_industry_growth_table(cur) -> int:
  """Derive typical QoQ revenue growth per NAICS from industry_growth_table.

  industry_growth_table contains pre-aggregated NAICS-quarter median ratios for
  public companies. We collect each NAICS's revenue_growth_q distribution and
  insert P25/P50/P75 as the mature QoQ growth band, then aggregate upward to
  higher NAICS levels.
  """
  rows_to_insert: List[Dict[str, Any]] = []

  cur.execute(
    """
    SELECT naics_code, industry_revenue_growth_q AS growth
    FROM industry_growth_table
    WHERE industry_revenue_growth_q IS NOT NULL
      AND YEAR(fiscalDateEnding) >= 2018
    """
  )
  per_level_obs: Dict[int, Dict[str, List[float]]] = {lvl: {} for lvl in (6, 5, 4, 3, 2)}
  for r in cur.fetchall():
    n_raw = str(r["naics_code"] or "").strip()
    digits = "".join(ch for ch in n_raw if ch.isdigit())
    if len(digits) < 2:
      continue
    n6 = digits.ljust(6, "0")[:6]
    growth = _to_float(r.get("growth"))
    if growth is None or abs(growth) > 5:
      continue
    for level in (6, 5, 4, 3, 2):
      key = n6[:level]
      per_level_obs[level].setdefault(key, []).append(float(growth))

  cur.execute("SELECT naics_code, naics_title FROM naics_master WHERE naics_code IS NOT NULL")
  title_by_naics: Dict[str, str] = {}
  for r in cur.fetchall():
    code = "".join(ch for ch in str(r["naics_code"] or "") if ch.isdigit())
    if code and code not in title_by_naics:
      title_by_naics[code] = str(r.get("naics_title") or "").strip()[:255]

  def _percentile(values: List[float], pct: float) -> float:
    s = sorted(values)
    if not s:
      return 0.0
    if len(s) == 1:
      return s[0]
    k = (len(s) - 1) * pct
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
      return s[int(k)]
    return s[f] + (s[c] - s[f]) * (k - f)

  for level, groups in per_level_obs.items():
    for naics_code, observations in groups.items():
      if len(observations) < 4:
        continue
      n = len(observations)
      conf = _confidence_for_sample(sample_size=n, high_floor=40, medium_floor=10)
      if level <= 3 and conf == "high":
        conf = "medium"
      title = title_by_naics.get(naics_code)
      rows_to_insert.append(
        {
          "naics_code": naics_code,
          "naics_level": level,
          "naics_title": title,
          "metric_domain": "stage_ramp",
          "metric_key": "mature_qoq_growth_typical",
          "metric_label": "Industry-typical QoQ revenue growth (mature firms)",
          "unit": "ratio",
          "benchmark_min": _percentile(observations, 0.25),
          "benchmark_target": _percentile(observations, 0.50),
          "benchmark_max": _percentile(observations, 0.75),
          "data_source": "industry_growth_table",
          "source_year": 2024,
          "sample_size": n,
          "confidence_tier": conf,
          "derivation_formula": "P25/P50/P75 of industry_revenue_growth_q within NAICS, year>=2018",
          "notes": "Public-company quarterly revenue growth distribution.",
        }
      )

  return _insert_baseline_rows(cur, rows_to_insert, source_label="industry_growth_table")


def load_alpha_data_distributions(cur) -> int:
  """Derive distributions_percent_of_net_income and a NAICS-6 effective_tax_rate
  from alpha_data joined with alpha_match_naics_industry."""
  rows_to_insert: List[Dict[str, Any]] = []

  cur.execute(
    """
    SELECT m.naics_code AS naics, a.dividendPayout AS dividends,
           a.netIncome_x AS net_income,
           a.incomeBeforeTax AS pretax,
           a.incomeTaxExpense AS tax_exp,
           m.naics_industry_name AS title
    FROM alpha_data a
    JOIN alpha_match_naics_industry m
      ON UPPER(m.symbol) COLLATE utf8mb4_unicode_ci = UPPER(a.symbol) COLLATE utf8mb4_unicode_ci
    WHERE a.fiscalDateEnding IS NOT NULL
      AND YEAR(a.fiscalDateEnding) >= 2018
      AND m.naics_code IS NOT NULL AND m.naics_code <> ''
      AND m.confidence >= 0.7
    """
  )
  per_naics: Dict[str, Dict[str, List[float]]] = {}
  title_by: Dict[str, str] = {}
  for r in cur.fetchall():
    naics_raw = str(r["naics"] or "").strip()
    digits = "".join(ch for ch in naics_raw if ch.isdigit())
    if len(digits) < 6:
      continue
    n6 = digits[:6]
    title = str(r.get("title") or "").strip()[:255]
    if title:
      title_by.setdefault(n6, title)
    div = _to_float(r.get("dividends"))
    ni = _to_float(r.get("net_income"))
    pretax = _to_float(r.get("pretax"))
    tax = _to_float(r.get("tax_exp"))
    g = per_naics.setdefault(n6, {})
    if div is not None and ni is not None and ni > 0 and div >= 0:
      ratio = float(div) / float(ni)
      if 0 <= ratio <= 2.0:
        g.setdefault("dist_ratio", []).append(ratio)
    if pretax is not None and tax is not None and pretax > 0:
      etr = float(tax) / float(pretax)
      if 0 <= etr <= 0.6:
        g.setdefault("etr", []).append(etr)

  def _percentile(values: List[float], pct: float) -> float:
    s = sorted(values)
    if not s:
      return 0.0
    if len(s) == 1:
      return s[0]
    k = (len(s) - 1) * pct
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
      return s[int(k)]
    return s[f] + (s[c] - s[f]) * (k - f)

  for level in (6, 5, 4, 3, 2):
    rolled: Dict[str, Dict[str, List[float]]] = {}
    for n6, metrics in per_naics.items():
      key = n6[:level]
      g = rolled.setdefault(key, {})
      for k, v in metrics.items():
        g.setdefault(k, []).extend(v)
    for naics_code, metric_obs in rolled.items():
      title = title_by.get(naics_code) if level == 6 else None
      dist = metric_obs.get("dist_ratio") or []
      if len(dist) >= 8:
        conf = _confidence_for_sample(sample_size=len(dist), high_floor=80, medium_floor=20)
        if level <= 3 and conf == "high":
          conf = "medium"
        rows_to_insert.append(
          {
            "naics_code": naics_code,
            "naics_level": level,
            "naics_title": title,
            "metric_domain": "cash_flow",
            "metric_key": "distributions_percent_of_net_income",
            "metric_label": "Dividends + distributions / net income",
            "unit": "ratio",
            "benchmark_min": _percentile(dist, 0.25),
            "benchmark_target": _percentile(dist, 0.50),
            "benchmark_max": _percentile(dist, 0.75),
            "data_source": "alpha_data",
            "source_year": 2024,
            "sample_size": len(dist),
            "confidence_tier": conf,
            "derivation_formula": "P25/P50/P75 of dividendPayout/netIncome across public-co quarterly filings, year>=2018",
            "notes": "Public-company filings; SMBs likely distribute more (use as a floor).",
          }
        )
      etr = metric_obs.get("etr") or []
      if len(etr) >= 8:
        conf = _confidence_for_sample(sample_size=len(etr), high_floor=80, medium_floor=20)
        if level <= 3 and conf == "high":
          conf = "medium"
        rows_to_insert.append(
          {
            "naics_code": naics_code,
            "naics_level": level,
            "naics_title": title,
            "metric_domain": "p_and_l",
            "metric_key": "effective_tax_rate",
            "metric_label": "Effective tax rate (incomeTaxExpense / pretax income)",
            "unit": "ratio",
            "benchmark_min": _percentile(etr, 0.25),
            "benchmark_target": _percentile(etr, 0.50),
            "benchmark_max": _percentile(etr, 0.75),
            "data_source": "alpha_data",
            "source_year": 2024,
            "sample_size": len(etr),
            "confidence_tier": conf,
            "derivation_formula": "P25/P50/P75 of incomeTaxExpense/incomeBeforeTax across public-co quarterly filings, year>=2018, pretax>0, etr<=60%",
            "notes": "Public-company effective rates; complements IRS_SOI data and provides NAICS-6 coverage.",
          }
        )

  return _insert_baseline_rows(cur, rows_to_insert, source_label="alpha_data")


def load_cross_aggregated_workforce_metrics(cur) -> int:
  """Broaden payroll_pct/revenue_per_fte coverage by aggregating CBP and SOI
  separately to each NAICS level (2,3,4,5) by truncation, then joining.

  This complements load_derived_workforce_metrics() (which only joins where CBP
  and SOI share the exact same NAICS code at the same level) by deliberately
  rolling up to broader NAICS levels where exact match isn't available.
  """
  rows_to_insert: List[Dict[str, Any]] = []

  # CBP raw aggregated by NAICS native level
  cur.execute(
    """
    SELECT naics, naics_label,
           SUM(estab) AS estab, SUM(emp) AS emp, SUM(pay_ann) AS pay_thousands
    FROM cbp_2022_raw
    WHERE naics IS NOT NULL AND naics <> '' AND naics <> '------'
    GROUP BY naics, naics_label
    """
  )
  cbp_native: Dict[str, Dict[str, Any]] = {}
  for r in cur.fetchall():
    digits = "".join(ch for ch in str(r["naics"] or "") if ch.isdigit())
    if not digits or len(digits) < 2:
      continue
    cbp_native[digits] = {
      "title": str(r.get("naics_label") or "").strip()[:255] or None,
      "estab": int(_to_float(r.get("estab")) or 0),
      "emp": int(_to_float(r.get("emp")) or 0),
      "pay_thousands": int(_to_float(r.get("pay_thousands")) or 0),
    }

  # SOI revenue aggregated to each NAICS level
  cur.execute(
    "SELECT business_receipts, naics_2_digit, naics_3_digit, naics_4_digit, "
    "       naics_5_digit, naics_6_digit, naics_title "
    "FROM SOI_corporate_tax_returns "
    "WHERE business_receipts IS NOT NULL AND business_receipts > 0"
  )
  soi_revenue_by_level_code: Dict[Tuple[int, str], Dict[str, Any]] = {}
  for r in cur.fetchall():
    receipts = _to_float(r.get("business_receipts")) or 0.0
    title = str(r.get("naics_title") or "").strip()[:255] or None
    for col, lvl in (
      ("naics_6_digit", 6), ("naics_5_digit", 5), ("naics_4_digit", 4),
      ("naics_3_digit", 3), ("naics_2_digit", 2),
    ):
      code = _normalize_naics(r.get(col), lvl)
      if not code:
        continue
      bucket = soi_revenue_by_level_code.setdefault(
        (lvl, code), {"revenue": 0.0, "title": title}
      )
      bucket["revenue"] += receipts
      if not bucket["title"] and title:
        bucket["title"] = title

  # CBP totals aggregated to each NAICS level by truncating native NAICS
  cbp_by_level: Dict[Tuple[int, str], Dict[str, Any]] = {}
  for native_code, data in cbp_native.items():
    for level in (2, 3, 4, 5, 6):
      if len(native_code) < level:
        continue
      key = (level, native_code[:level])
      bucket = cbp_by_level.setdefault(
        key, {"estab": 0, "emp": 0, "pay_thousands": 0, "title": data["title"]}
      )
      bucket["estab"] += data["estab"]
      bucket["emp"] += data["emp"]
      bucket["pay_thousands"] += data["pay_thousands"]
      if not bucket["title"] and data["title"]:
        bucket["title"] = data["title"]

  # Join at each level
  for (level, naics_code), cbp_data in cbp_by_level.items():
    soi_match = soi_revenue_by_level_code.get((level, naics_code))
    if not soi_match or soi_match["revenue"] <= 0:
      continue
    cbp_pay_thousands = cbp_data["pay_thousands"]
    cbp_emp = cbp_data["emp"]
    if cbp_emp <= 0 or cbp_pay_thousands <= 0:
      continue
    payroll_dollars = cbp_pay_thousands * 1000.0
    revenue_dollars = soi_match["revenue"] * 1000.0
    payroll_pct = payroll_dollars / revenue_dollars
    revenue_per_fte = revenue_dollars / cbp_emp

    sample = cbp_data["estab"]
    confidence = _confidence_for_sample(sample_size=sample, high_floor=2000, medium_floor=200)
    if level <= 3 and confidence == "high":
      confidence = "medium"
    title = cbp_data["title"] or soi_match["title"]

    if 0.0 < payroll_pct < 1.5:
      rows_to_insert.append(
        {
          "naics_code": naics_code,
          "naics_level": level,
          "naics_title": title,
          "metric_domain": "workforce",
          "metric_key": "payroll_percent_of_revenue",
          "metric_label": "Payroll / revenue (CBP rolled-up payroll, SOI rolled-up revenue)",
          "unit": "ratio",
          "benchmark_target": float(payroll_pct),
          "data_source": "derived_CBP_SOI_rollup",
          "source_year": 2022,
          "sample_size": sample,
          "confidence_tier": confidence,
          "derivation_formula": "(CBP.pay_ann*1000 summed across native-level rows truncated to this level) / (SOI.business_receipts summed at this level)",
          "notes": "Rolled-up cross-source derivation; broader coverage than exact-NAICS-match join.",
        }
      )
    if revenue_per_fte > 1000.0:
      rows_to_insert.append(
        {
          "naics_code": naics_code,
          "naics_level": level,
          "naics_title": title,
          "metric_domain": "workforce",
          "metric_key": "revenue_per_fte",
          "metric_label": "Revenue per FTE (SOI rolled-up revenue / CBP rolled-up emp)",
          "unit": "usd",
          "benchmark_target": float(revenue_per_fte),
          "data_source": "derived_CBP_SOI_rollup",
          "source_year": 2022,
          "sample_size": sample,
          "confidence_tier": confidence,
          "derivation_formula": "(SOI.business_receipts summed) * 1000 / (CBP.emp summed)",
          "notes": "Rolled-up cross-source derivation.",
        }
      )
      rows_to_insert.append(
        {
          "naics_code": naics_code,
          "naics_level": level,
          "naics_title": title,
          "metric_domain": "workforce",
          "metric_key": "fte_per_million_revenue",
          "metric_label": "FTEs per $1M revenue (rolled up)",
          "unit": "fte_per_million_rev",
          "benchmark_target": 1_000_000.0 / float(revenue_per_fte),
          "data_source": "derived_CBP_SOI_rollup",
          "source_year": 2022,
          "sample_size": sample,
          "confidence_tier": confidence,
          "derivation_formula": "1,000,000 / revenue_per_fte (rolled up)",
          "notes": "Inverse of revenue_per_fte; broader coverage rollup.",
        }
      )

  return _insert_baseline_rows(cur, rows_to_insert, source_label="derived_CBP_SOI_rollup")


METRIC_REGISTRY: List[Dict[str, Any]] = [
  # P&L
  {"metric_key":"effective_tax_rate","metric_domain":"p_and_l","metric_label":"Effective corporate tax rate","unit":"ratio","applies_to_statement":"income_statement","primary_source":"IRS_SOI","secondary_source":"expert_default","governs_model_input_lever":"expenses::Taxes","fail_if_no_coverage":0,"description":"Effective tax rate net of credits as reported on corporate returns."},
  {"metric_key":"cogs_percent_of_revenue","metric_domain":"p_and_l","metric_label":"COGS / revenue","unit":"ratio","applies_to_statement":"income_statement","primary_source":"industry_metrics_raw","secondary_source":"IRS_SOI","governs_model_input_lever":"expenses::Cost of Goods Sold","fail_if_no_coverage":0,"description":"Direct cost of producing/delivering revenue."},
  {"metric_key":"gross_margin_percent","metric_domain":"p_and_l","metric_label":"Gross margin","unit":"ratio","applies_to_statement":"income_statement","primary_source":"industry_metrics_raw","secondary_source":"IRS_SOI","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"1 - cogs_percent_of_revenue."},
  {"metric_key":"net_income_margin","metric_domain":"p_and_l","metric_label":"Net income margin","unit":"ratio","applies_to_statement":"income_statement","primary_source":"industry_metrics_raw","secondary_source":"IRS_SOI","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Net income as % of revenue."},
  {"metric_key":"operating_margin_percent","metric_domain":"p_and_l","metric_label":"Operating margin","unit":"ratio","applies_to_statement":"income_statement","primary_source":"industry_metrics_raw","secondary_source":"expert_default","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"EBIT / revenue."},
  {"metric_key":"ebitda_margin","metric_domain":"p_and_l","metric_label":"EBITDA margin","unit":"ratio","applies_to_statement":"income_statement","primary_source":"industry_metrics_raw","secondary_source":"expert_default","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"EBITDA / revenue."},
  {"metric_key":"sga_percent_of_revenue","metric_domain":"p_and_l","metric_label":"SG&A / revenue","unit":"ratio","applies_to_statement":"income_statement","primary_source":"industry_metrics_raw","secondary_source":"expert_default","governs_model_input_lever":"expenses::General & Administrative","fail_if_no_coverage":0,"description":"Combined selling, general & administrative."},
  {"metric_key":"r_and_d_percent_of_revenue","metric_domain":"p_and_l","metric_label":"R&D / revenue","unit":"ratio","applies_to_statement":"income_statement","primary_source":"industry_metrics_raw","secondary_source":"expert_default","governs_model_input_lever":"expenses::Research & Development","fail_if_no_coverage":0,"description":"R&D spending as % of revenue."},
  {"metric_key":"depreciation_percent_of_revenue","metric_domain":"p_and_l","metric_label":"Depreciation / revenue","unit":"ratio","applies_to_statement":"income_statement","primary_source":"IRS_SOI","secondary_source":"industry_metrics_raw","governs_model_input_lever":"expenses::Depreciation","fail_if_no_coverage":0,"description":"Depreciation expense as % of revenue."},
  {"metric_key":"interest_coverage","metric_domain":"p_and_l","metric_label":"Interest coverage ratio","unit":"ratio","applies_to_statement":"income_statement","primary_source":"industry_metrics_raw","secondary_source":"expert_default","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"EBIT / interest expense."},
  {"metric_key":"rent_percent_of_revenue","metric_domain":"p_and_l","metric_label":"Operating rent / revenue","unit":"ratio","applies_to_statement":"income_statement","primary_source":"expert_naics2_default","secondary_source":"expert_default","governs_model_input_lever":"expenses::Lease","fail_if_no_coverage":0,"description":"Operating real-estate rent as % of revenue. Until BLS PPI for Commercial Rents is sourced, expert NAICS-2 defaults provide universal coverage."},
  {"metric_key":"lease_percent_of_revenue","metric_domain":"p_and_l","metric_label":"Operating lease / revenue","unit":"ratio","applies_to_statement":"income_statement","primary_source":"expert_naics2_default","secondary_source":"expert_default","governs_model_input_lever":"expenses::Lease","fail_if_no_coverage":0,"description":"Operating equipment/vehicle lease as % of revenue. Excludes balance-sheet capital lease obligations (ASC 842 finance leases)."},
  {"metric_key":"occupancy_total_percent_of_revenue","metric_domain":"p_and_l","metric_label":"Rent + lease combined / revenue","unit":"ratio","applies_to_statement":"income_statement","primary_source":"expert_naics2_default","secondary_source":"expert_default","governs_model_input_lever":"expenses::Lease","fail_if_no_coverage":0,"description":"Combined rent + operating lease intensity. Matches the model_input 'expenses::Lease' lever which captures both."},
  {"metric_key":"marketing_percent_of_revenue","metric_domain":"p_and_l","metric_label":"Marketing expense / revenue","unit":"ratio","applies_to_statement":"income_statement","primary_source":"SEC_EDGAR","secondary_source":"expert_default","governs_model_input_lever":"expenses::Marketing","fail_if_no_coverage":0,"description":"Marketing expense as % of revenue. SEC EDGAR XBRL data-backed at NAICS-6."},
  {"metric_key":"advertising_percent_of_revenue","metric_domain":"p_and_l","metric_label":"Advertising expense / revenue","unit":"ratio","applies_to_statement":"income_statement","primary_source":"SEC_EDGAR","secondary_source":"expert_default","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Advertising expense as % of revenue (subset of marketing for many filers)."},
  {"metric_key":"operating_cash_flow_margin","metric_domain":"cash_flow","metric_label":"Operating cash flow / revenue","unit":"ratio","applies_to_statement":"cash_flow","primary_source":"SEC_EDGAR","secondary_source":"expert_default","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Operating cash flow margin from SEC EDGAR."},
  {"metric_key":"stock_based_compensation_percent_of_revenue","metric_domain":"p_and_l","metric_label":"Stock-based comp / revenue","unit":"ratio","applies_to_statement":"income_statement","primary_source":"SEC_EDGAR","secondary_source":"expert_default","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Stock-based compensation as % of revenue from SEC EDGAR."},
  # Balance sheet
  {"metric_key":"ar_days_dso","metric_domain":"balance_sheet","metric_label":"DSO","unit":"days","applies_to_statement":"balance_sheet","primary_source":"industry_metrics_raw","secondary_source":"expert_default","governs_model_input_lever":"balance_sheet::Accounts Receivable Days","fail_if_no_coverage":0,"description":"Days sales outstanding (AR cash collection cycle)."},
  {"metric_key":"ap_days_dpo","metric_domain":"balance_sheet","metric_label":"DPO","unit":"days","applies_to_statement":"balance_sheet","primary_source":"industry_metrics_raw","secondary_source":"expert_default","governs_model_input_lever":"balance_sheet::Accounts Payable Days","fail_if_no_coverage":0,"description":"Days payable outstanding (vendor payment cycle)."},
  {"metric_key":"inventory_days","metric_domain":"balance_sheet","metric_label":"Inventory days","unit":"days","applies_to_statement":"balance_sheet","primary_source":"industry_metrics_raw","secondary_source":"expert_default","governs_model_input_lever":"balance_sheet::Inventory Days","fail_if_no_coverage":0,"description":"Days of inventory on hand."},
  {"metric_key":"current_ratio","metric_domain":"balance_sheet","metric_label":"Current ratio","unit":"ratio","applies_to_statement":"balance_sheet","primary_source":"industry_metrics_raw","secondary_source":"expert_default","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Current assets / current liabilities."},
  {"metric_key":"quick_ratio","metric_domain":"balance_sheet","metric_label":"Quick ratio","unit":"ratio","applies_to_statement":"balance_sheet","primary_source":"industry_metrics_raw","secondary_source":"expert_default","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"(Current assets - inventory) / current liabilities."},
  {"metric_key":"debt_to_equity","metric_domain":"balance_sheet","metric_label":"Debt / equity","unit":"ratio","applies_to_statement":"balance_sheet","primary_source":"industry_metrics_raw","secondary_source":"IRS_SOI","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Total liabilities / equity."},
  {"metric_key":"debt_to_assets","metric_domain":"balance_sheet","metric_label":"Debt / assets","unit":"ratio","applies_to_statement":"balance_sheet","primary_source":"industry_metrics_raw","secondary_source":"expert_default","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Total liabilities / total assets."},
  {"metric_key":"ppe_percent_of_revenue","metric_domain":"balance_sheet","metric_label":"PP&E / revenue","unit":"ratio","applies_to_statement":"balance_sheet","primary_source":"IRS_SOI","secondary_source":"expert_default","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Asset intensity proxy."},
  {"metric_key":"total_assets_to_revenue","metric_domain":"balance_sheet","metric_label":"Assets / revenue","unit":"ratio","applies_to_statement":"balance_sheet","primary_source":"IRS_SOI","secondary_source":"expert_default","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Capital intensity."},
  {"metric_key":"owners_capital_percent_of_assets","metric_domain":"balance_sheet","metric_label":"Equity / assets","unit":"ratio","applies_to_statement":"balance_sheet","primary_source":"IRS_SOI","secondary_source":"expert_default","governs_model_input_lever":"balance_sheet::Owner's Capital","fail_if_no_coverage":0,"description":"Equity share of capital structure."},
  {"metric_key":"prepaid_expenses_percent_of_revenue","metric_domain":"balance_sheet","metric_label":"Prepaids / revenue","unit":"ratio","applies_to_statement":"balance_sheet","primary_source":"expert_default","secondary_source":None,"governs_model_input_lever":"balance_sheet::Prepaid Expenses (% of Revenue)","fail_if_no_coverage":0,"description":"Prepaid expense intensity."},
  {"metric_key":"deferred_revenue_percent_of_revenue","metric_domain":"balance_sheet","metric_label":"Deferred revenue / revenue","unit":"ratio","applies_to_statement":"balance_sheet","primary_source":"expert_default","secondary_source":None,"governs_model_input_lever":"balance_sheet::Deferred Revenue (% of Revenue)","fail_if_no_coverage":0,"description":"For subscription/membership/upfront-payment business models."},
  # Cash flow
  {"metric_key":"capex_percent_of_revenue","metric_domain":"cash_flow","metric_label":"CapEx / revenue","unit":"ratio","applies_to_statement":"cash_flow","primary_source":"industry_metrics_raw","secondary_source":"expert_default","governs_model_input_lever":"schedules::Capital Expenditures","fail_if_no_coverage":0,"description":"Capital expenditures as % of revenue."},
  {"metric_key":"maintenance_capex_percent_of_revenue","metric_domain":"cash_flow","metric_label":"Maintenance CapEx / revenue","unit":"ratio","applies_to_statement":"cash_flow","primary_source":"expert_default","secondary_source":None,"governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Sustaining capex (excludes growth investment)."},
  {"metric_key":"distributions_percent_of_net_income","metric_domain":"cash_flow","metric_label":"Distributions / net income","unit":"ratio","applies_to_statement":"cash_flow","primary_source":"expert_default","secondary_source":None,"governs_model_input_lever":"balance_sheet::Distributions","fail_if_no_coverage":0,"description":"Owner draws / dividends as % of profits."},
  # Workforce
  {"metric_key":"avg_wage_per_fte","metric_domain":"workforce","metric_label":"Average wage per FTE","unit":"usd","applies_to_statement":"income_statement","primary_source":"BLS_OEWS","secondary_source":"Census_CBP","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Industry-typical wage per employee."},
  {"metric_key":"revenue_per_fte","metric_domain":"workforce","metric_label":"Revenue per FTE","unit":"usd","applies_to_statement":"workforce_realism","primary_source":"derived_CBP_SOI","secondary_source":"expert_default","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Realism floor for FTE sizing relative to revenue."},
  {"metric_key":"payroll_percent_of_revenue","metric_domain":"workforce","metric_label":"Payroll / revenue","unit":"ratio","applies_to_statement":"income_statement","primary_source":"derived_CBP_SOI","secondary_source":"expert_default","governs_model_input_lever":"expenses::Payroll","fail_if_no_coverage":0,"description":"Industry-typical payroll intensity."},
  {"metric_key":"fte_per_million_revenue","metric_domain":"workforce","metric_label":"FTEs per $1M revenue","unit":"fte_per_million_rev","applies_to_statement":"workforce_realism","primary_source":"derived_CBP_SOI","secondary_source":"expert_default","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Inverse of revenue_per_fte; sets the FTE realism band."},
  {"metric_key":"employees_per_establishment","metric_domain":"workforce","metric_label":"Employees per establishment","unit":"count","applies_to_statement":"workforce_realism","primary_source":"Census_CBP","secondary_source":"expert_default","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Average headcount per location."},
  # Capital structure
  {"metric_key":"sba_initial_interest_rate","metric_domain":"capital_structure","metric_label":"SBA loan initial rate","unit":"ratio","applies_to_statement":"income_statement","primary_source":"SBA_7A","secondary_source":"expert_default","governs_model_input_lever":"expenses::Interest Rate","fail_if_no_coverage":0,"description":"Typical small-business loan interest rate."},
  {"metric_key":"sba_typical_loan_size","metric_domain":"capital_structure","metric_label":"SBA typical loan size","unit":"usd","applies_to_statement":"balance_sheet","primary_source":"SBA_7A","secondary_source":"expert_default","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Typical 7(a) gross approval amount."},
  {"metric_key":"sba_typical_loan_term_months","metric_domain":"capital_structure","metric_label":"SBA typical term","unit":"count","applies_to_statement":"balance_sheet","primary_source":"SBA_7A","secondary_source":"expert_default","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Typical loan term in months."},
  # Stage ramp
  {"metric_key":"year1_to_year5_employment_ratio","metric_domain":"stage_ramp","metric_label":"Y5/Y0 employment ratio","unit":"ratio","applies_to_statement":"workforce_realism","primary_source":"Census_BDS","secondary_source":"expert_default","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Typical headcount growth from year-zero to year-five."},
  {"metric_key":"startup_year1_exit_rate","metric_domain":"stage_ramp","metric_label":"Year-1 startup exit rate","unit":"percent","applies_to_statement":"stage_ramp","primary_source":"Census_BDS","secondary_source":"expert_default","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"% of new establishments closing in year 1."},
  {"metric_key":"mature_exit_rate","metric_domain":"stage_ramp","metric_label":"Mature exit rate","unit":"percent","applies_to_statement":"stage_ramp","primary_source":"Census_BDS","secondary_source":"expert_default","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Steady-state churn for established firms."},
  {"metric_key":"startup_net_job_growth_rate","metric_domain":"stage_ramp","metric_label":"Startup net job growth","unit":"percent","applies_to_statement":"stage_ramp","primary_source":"Census_BDS","secondary_source":"expert_default","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Net job creation rate for age-0 firms."},
  {"metric_key":"early_net_job_growth_rate","metric_domain":"stage_ramp","metric_label":"Early-stage net job growth","unit":"percent","applies_to_statement":"stage_ramp","primary_source":"Census_BDS","secondary_source":"expert_default","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Net job creation rate for age-1 firms."},
  {"metric_key":"mature_net_job_growth_rate","metric_domain":"stage_ramp","metric_label":"Mature net job growth","unit":"percent","applies_to_statement":"stage_ramp","primary_source":"Census_BDS","secondary_source":"expert_default","governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Net job creation rate for mature firms."},
  {"metric_key":"startup_qoq_growth_typical","metric_domain":"stage_ramp","metric_label":"Startup QoQ revenue growth","unit":"ratio","applies_to_statement":"stage_ramp","primary_source":"expert_default","secondary_source":None,"governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Typical revenue growth quarter-over-quarter for startups."},
  {"metric_key":"early_qoq_growth_typical","metric_domain":"stage_ramp","metric_label":"Early-stage QoQ growth","unit":"ratio","applies_to_statement":"stage_ramp","primary_source":"expert_default","secondary_source":None,"governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Typical revenue growth for early-stage firms."},
  {"metric_key":"mature_qoq_growth_typical","metric_domain":"stage_ramp","metric_label":"Mature QoQ growth","unit":"ratio","applies_to_statement":"stage_ramp","primary_source":"expert_default","secondary_source":None,"governs_model_input_lever":None,"fail_if_no_coverage":0,"description":"Typical revenue growth for mature firms."},
]


def load_metric_registry(cur) -> int:
  rows: List[Tuple[Any, ...]] = []
  for r in METRIC_REGISTRY:
    rows.append((
      r["metric_key"], r["metric_domain"], r.get("metric_label"), r["unit"],
      r.get("description"), r.get("primary_source"), r.get("secondary_source"),
      r.get("applies_to_statement"), r.get("governs_model_input_lever"),
      int(r.get("fail_if_no_coverage", 0)), 1, None,
    ))
  if not rows:
    return 0
  cur.executemany(
    """
    REPLACE INTO post_intake_industry_metric_registry
      (metric_key, metric_domain, metric_label, unit, description,
       primary_source, secondary_source, applies_to_statement,
       governs_model_input_lever, fail_if_no_coverage, active, notes)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """,
    rows,
  )
  print(f"  [metric_registry] inserted/replaced {len(rows)} rows")
  return len(rows)


def populate_coverage_audit(cur) -> int:
  cur.execute("DELETE FROM post_intake_industry_baseline_coverage_audit")
  cur.execute(
    """
    INSERT INTO post_intake_industry_baseline_coverage_audit
      (metric_key, metric_domain, total_rows,
       level_6_rows, level_5_rows, level_4_rows, level_3_rows, level_2_rows,
       generic_default_rows, highest_level_with_coverage, has_generic_default,
       primary_data_source)
    SELECT
      l.metric_key,
      MAX(l.metric_domain),
      COUNT(*),
      SUM(CASE WHEN naics_level=6 THEN 1 ELSE 0 END),
      SUM(CASE WHEN naics_level=5 THEN 1 ELSE 0 END),
      SUM(CASE WHEN naics_level=4 THEN 1 ELSE 0 END),
      SUM(CASE WHEN naics_level=3 THEN 1 ELSE 0 END),
      SUM(CASE WHEN naics_level=2 THEN 1 ELSE 0 END),
      SUM(CASE WHEN naics_level=0 THEN 1 ELSE 0 END),
      MAX(naics_level),
      MAX(CASE WHEN naics_level=0 THEN 1 ELSE 0 END),
      (
        SELECT data_source FROM post_intake_industry_baseline_lookup l2
        WHERE l2.metric_key = l.metric_key AND l2.naics_level > 0
        GROUP BY data_source
        ORDER BY COUNT(*) DESC
        LIMIT 1
      )
    FROM post_intake_industry_baseline_lookup l
    GROUP BY l.metric_key
    """
  )
  print(f"  [coverage_audit] populated {cur.rowcount} rows")
  return cur.rowcount


def load_generic_defaults(cur) -> int:
  rows_to_insert: List[Dict[str, Any]] = []
  for d in GENERIC_DEFAULTS:
    row = {
      "naics_code": "*",
      "naics_level": 0,
      "naics_title": "Cross-industry generic default",
      "data_source": "expert_default",
      "source_year": None,
      "sample_size": None,
      "confidence_tier": "generic_default",
      "derivation_formula": "Cross-industry typical band; not NAICS-specific.",
    }
    row.update(d)
    rows_to_insert.append(row)
  return _insert_baseline_rows(cur, rows_to_insert, source_label="expert_default")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
  print("Connecting to MySQL...")
  conn = _conn()
  try:
    cur = conn.cursor(dictionary=True)
    print("\nCreating post_intake_industry_baseline_lookup if not exists...")
    cur.execute(CREATE_TABLE_SQL)
    print("Creating post_intake_industry_metric_registry if not exists...")
    cur.execute(CREATE_REGISTRY_TABLE_SQL)
    print("Creating post_intake_industry_baseline_coverage_audit if not exists...")
    cur.execute(CREATE_COVERAGE_TABLE_SQL)
    conn.commit()

    cur2 = conn.cursor()
    # Clear rows by source to keep this idempotent
    print("\nClearing prior rows by source (idempotent re-run)...")
    for src in (
      "IRS_SOI", "BLS_OEWS", "Census_CBP",
      "industry_metrics_raw", "SBA_7A", "Census_BDS", "expert_default",
      "derived_CBP_SOI", "industry_growth_table", "alpha_data",
      "derived_CBP_SOI_rollup", "derived_depreciation_proxy",
      "expert_naics2_default", "SEC_EDGAR",
    ):
      cur2.execute(
        "DELETE FROM post_intake_industry_baseline_lookup WHERE data_source = %s",
        (src,),
      )
      print(f"  cleared {cur2.rowcount} rows from data_source={src}")
    conn.commit()
    cur2.close()

    print("\nLoading from each source...")
    cur_load = conn.cursor()
    total = 0
    total += load_generic_defaults(cur_load)
    conn.commit()
    total += load_from_soi(cur)
    conn.commit()
    total += load_from_oews(cur)
    conn.commit()
    total += load_from_cbp(cur)
    conn.commit()
    total += load_derived_workforce_metrics(cur)
    conn.commit()
    total += load_cross_aggregated_workforce_metrics(cur)
    conn.commit()
    total += load_from_industry_metrics(cur)
    conn.commit()
    total += load_qoq_growth_from_industry_growth_table(cur)
    conn.commit()
    total += load_alpha_data_distributions(cur)
    conn.commit()
    total += load_from_sba(cur)
    conn.commit()
    total += load_from_bds(cur)
    conn.commit()
    total += load_expert_rent_lease_defaults(cur)
    conn.commit()
    total += load_from_sec_edgar(cur)
    conn.commit()
    # Derived metrics that depend on already-inserted rows must run last.
    total += load_maintenance_capex_from_depreciation(cur)
    conn.commit()

    print("\nLoading metric registry...")
    cur_reg = conn.cursor()
    load_metric_registry(cur_reg)
    conn.commit()
    cur_reg.close()

    print("\nPopulating coverage audit...")
    cur_aud = conn.cursor()
    populate_coverage_audit(cur_aud)
    conn.commit()
    cur_aud.close()

    print(f"\nTotal rows inserted/replaced: {total}")

    # Coverage audit
    print("\n--- Coverage audit ---")
    cur2 = conn.cursor(dictionary=True)
    cur2.execute(
      """
      SELECT data_source, naics_level, COUNT(*) AS n
      FROM post_intake_industry_baseline_lookup
      GROUP BY data_source, naics_level
      ORDER BY data_source, naics_level
      """
    )
    for r in cur2.fetchall():
      print(f"  source={r['data_source']:24} level={r['naics_level']}  rows={r['n']}")

    print("\n--- Per-metric distinct NAICS coverage ---")
    cur2.execute(
      """
      SELECT metric_key,
             COUNT(*) AS total_rows,
             SUM(CASE WHEN naics_level=6 THEN 1 ELSE 0 END) AS l6,
             SUM(CASE WHEN naics_level=5 THEN 1 ELSE 0 END) AS l5,
             SUM(CASE WHEN naics_level=4 THEN 1 ELSE 0 END) AS l4,
             SUM(CASE WHEN naics_level=3 THEN 1 ELSE 0 END) AS l3,
             SUM(CASE WHEN naics_level=2 THEN 1 ELSE 0 END) AS l2,
             SUM(CASE WHEN naics_level=0 THEN 1 ELSE 0 END) AS gen
      FROM post_intake_industry_baseline_lookup
      GROUP BY metric_key
      ORDER BY metric_key
      """
    )
    print(f"  {'metric_key':45} {'total':>6} {'L6':>5} {'L5':>5} {'L4':>5} {'L3':>5} {'L2':>5} {'gen':>5}")
    for r in cur2.fetchall():
      print(
        f"  {r['metric_key']:45} {r['total_rows']:>6} {r['l6']:>5} {r['l5']:>5} "
        f"{r['l4']:>5} {r['l3']:>5} {r['l2']:>5} {r['gen']:>5}"
      )
    cur2.close()
  finally:
    conn.close()
  return 0


if __name__ == "__main__":
  sys.exit(main())
