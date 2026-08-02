"""Cohort-Matched Band Resolver — Phase 3.5.

Queries `industry_metrics_raw` directly at runtime to compute per-business
percentile bands (p25 / median / p75) for the cohort that matches the
business profile (NAICS prefix + revenue window + cap_category set + recent
date window). This is a higher-priority source for the Driver Movement
Assembler and FINMO Output Target Assembler than the existing pre-aggregated
`post_intake_industry_baseline_lookup` cascade resolver — which now becomes
the fallback when a business's cohort is too small.

Why a runtime query instead of a new ETL table:
  - The user directive specifies a process-memory cache scoped to one
    planning run, not a materialized cohort-bands table. That keeps Phase
    3.5 small and avoids a schema migration.
  - `industry_metrics_raw` is small (~10-20k rows). A cohort filter
    typically returns 50-500 rows. Percentile computation in Python is
    sub-millisecond. Even with 16 metric columns × 5 cascading attempts
    per planning run, the total query volume is bounded.

Cohort filter, in priority order:
  1. NAICS-6 prefix match. Fall back to NAICS-5 / 4 / 3 / 2 only when the
     more-specific level returns < 8 rows.
  2. total_revenue between [target * 0.3, target * 3.0]. Widen to
     [target * 0.1, target * 10.0] on small cohorts. Drop the revenue
     filter entirely as a last cohort-widening step.
  3. cap_category in the SBA-vs-growth set derived from target_revenue +
     stage. SBA-scale: {small, mid}. Growth-scale: {mid, large}.
  4. fiscalDateEnding within the last 5 years. Widen to 8 / 10 years if
     small.

Confidence tiering matches the existing cascade resolver's vocabulary so
provenance reads consistently:
  - n >= 50 -> high
  - 20 <= n < 50 -> medium
  - 8 <= n < 20 -> low
  - n < 8 -> fallback (resolver returns None; caller uses cascade)

The lever-to-column map below covers every lever and metric the directive
specified for cohort sourcing. Levers without a direct industry_metrics_raw
column (Lease, Payroll, Interest Rate, Tax Rate) are not in the map; the
existing cascade / SBA / IRS sources keep their authority.
"""

from __future__ import annotations

import copy
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lever-to-column map and metric-key-to-column map.
# ---------------------------------------------------------------------------

# Maps a Driver Movement Assembler lever_id to the industry_metrics_raw
# column whose percentile band represents that lever's plausible range.
LEVER_TO_METRIC_COLUMN: Dict[str, str] = {
  "expenses::Cost of Goods Sold": "cogs_percent",
  "expenses::Research & Development": "rnd_percent",
  "expenses::General & Administrative": "sga_percent",
  # Marketing has no dedicated column in industry_metrics_raw; the SGA
  # convention bundles marketing into sga_percent. Using sga_percent as
  # the cohort proxy is the same compromise the cascade resolver makes.
  "expenses::Marketing": "sga_percent",
  "balance_sheet::Accounts Receivable Days": "dso",
  "balance_sheet::Accounts Payable Days": "dpo",
  "balance_sheet::Inventory Days": "inventory_days",
}

# Maps a FINMO Output Target Assembler metric_key to the
# industry_metrics_raw column that supplies its target band.
METRIC_KEY_TO_COLUMN: Dict[str, str] = {
  "cogs_to_revenue_ratio": "cogs_percent",
  "cogs_percent_of_revenue": "cogs_percent",
  "gross_margin_percent": "gross_margin_q",
  # Fix #1 viability standard (§5.1): the Rule-of-40 growth term. The
  # column exists in industry_metrics_{edgar,alpha} but was previously
  # unregistered, so resolve_cohort_band returned None for it.
  "revenue_growth": "revenue_growth_q",
  "revenue_growth_q": "revenue_growth_q",
  "marketing_percent_of_revenue": "sga_percent",
  "advertising_percent_of_revenue": "sga_percent",
  "r_and_d_percent_of_revenue": "rnd_percent",
  "sga_percent_of_revenue": "sga_percent",
  "ebitda_margin": "ebitda_margin_q",
  "operating_margin_percent": "operating_margin_q",
  "net_income_margin": "net_margin_q",
  "ar_days_dso": "dso",
  "ap_days_dpo": "dpo",
  "inventory_days": "inventory_days",
  "current_ratio": "current_ratio",
  "quick_ratio": "quick_ratio",
  "debt_to_equity": "debt_to_equity",
  "debt_to_assets": "debt_to_assets",
  "interest_coverage": "interest_coverage",
  "capex_percent_of_revenue": "capex_percent_revenue",
  "depreciation_percent_of_revenue": "depreciation_percent_revenue",
  # Phase 9 P3 — derived working-capital metrics. Populated from existing
  # dso / dpo / inventory_days / cogs_percent components by
  # python/scripts/phase_9_p3_derive_working_capital_columns.py.
  "current_assets_minus_cash": "current_assets_minus_cash_to_revenue",
  "current_liabilities_to_revenue": "current_liabilities_to_revenue",
}

# Columns we know about in industry_metrics_raw — used to validate that a
# requested column exists before we build a SELECT.
_KNOWN_METRIC_COLUMNS = frozenset({
  "revenue_growth_q",  # Fix #1 viability standard (§5.1) — Rule-of-40 growth term.
  "cogs_percent", "gross_margin_q", "operating_margin_q", "ebit_margin_q",
  "ebitda_margin_q", "net_margin_q", "sga_percent", "rnd_percent",
  "dso", "dpo", "inventory_days", "ccc",
  "current_ratio", "quick_ratio", "debt_to_equity", "debt_to_assets",
  "debt_to_ebitda", "interest_coverage",
  "capex_percent_revenue", "depreciation_percent_revenue",
  "roa", "roe",
  # Phase 9 P3 derived working-capital columns.
  "current_assets_minus_cash_to_revenue", "current_liabilities_to_revenue",
})


# Two cohort source tables, queried in alternating order at each NAICS
# level: EDGAR first (broader SIC-classified universe; ~3K extra firms
# beyond the Alpha SEC-listed set), then Alpha (richer per-firm history).
# The runtime resolver tries (level=6, edgar) -> (level=6, alpha) ->
# (level=5, edgar) -> (level=5, alpha) -> ... -> (level=2, alpha) and
# accepts the FIRST level/source pair whose distinct-firm count >= 2.
_COHORT_TABLES: Tuple[Tuple[str, str], ...] = (
  ("edgar", "industry_metrics_edgar"),
  ("alpha", "industry_metrics_alpha"),
)
_COHORT_FIRM_MIN = 2  # ≥ 2 distinct firms qualifies a bucket as a real industry

# Cohort widening ladder. Each tier widens one filter dimension.
_REVENUE_WINDOW_LADDER: Tuple[Tuple[float, float], ...] = (
  (0.30, 3.0),    # primary: 0.3x .. 3x target
  (0.10, 10.0),   # widen: 0.1x .. 10x target
)
_DATE_WINDOW_YEARS_LADDER: Tuple[int, ...] = (5, 8, 10)
_NAICS_LEVEL_LADDER: Tuple[int, ...] = (6, 5, 4, 3, 2)

# Confidence-tier thresholds (kept for provenance/reporting; do NOT gate
# acceptance — the firm-count threshold above is what gates).
_TIER_HIGH_MIN_N = 50
_TIER_MEDIUM_MIN_N = 20
_TIER_LOW_MIN_N = 8


# ---------------------------------------------------------------------------
# Result type.
# ---------------------------------------------------------------------------


@dataclass
class CohortBandResult:
  metric_key: str
  metric_column: str
  benchmark_min: Optional[float]    # 25th percentile
  benchmark_target: Optional[float]  # median (50th)
  benchmark_max: Optional[float]    # 75th percentile
  cohort_size: int                  # row count used for percentile compute
  firm_count: int                   # distinct firms (the gating metric)
  confidence_tier: str              # high / medium / low / fallback (informational)
  cohort_table: str                 # 'edgar' or 'alpha' — which table answered
  naics_level_used: int             # 6/5/4/3/2 — where in the alternating walk we stopped
  naics_prefix_used: str
  cohort_query: Dict[str, Any] = field(default_factory=dict)
  data_source: str = "cohort_alternating"  # was: industry_metrics_raw_cohort

  def to_dict(self) -> Dict[str, Any]:
    return {
      "metric_key": self.metric_key,
      "metric_column": self.metric_column,
      "benchmark_min": self.benchmark_min,
      "benchmark_target": self.benchmark_target,
      "benchmark_max": self.benchmark_max,
      "cohort_size": int(self.cohort_size),
      "firm_count": int(self.firm_count),
      "confidence_tier": self.confidence_tier,
      "cohort_table": self.cohort_table,
      "naics_level_used": int(self.naics_level_used),
      "naics_prefix_used": self.naics_prefix_used,
      "cohort_query": copy.deepcopy(self.cohort_query),
      "data_source": self.data_source,
    }


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  try:
    number = float(value)
  except Exception:
    return None
  if number != number:
    return None
  return number


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


def _normalized_naics_6(naics_6: Optional[str]) -> str:
  return "".join(ch for ch in str(naics_6 or "") if ch.isdigit())


def map_revenue_to_cap_categories(
  *,
  target_annual_revenue: Optional[float],
  stage: Optional[str],
) -> Tuple[str, ...]:
  """Map a (target_revenue, stage) pair to the cap_category SET allowed
  in the cohort. Returning a set lets the SQL filter be permissive — for
  a $4M SBA-scale business, both `small` and `mid` public-comp cohorts
  are reasonable references; we don't restrict to `small` alone because
  small-cap public companies are usually still much larger than SBA-scale
  privates.
  """
  rev = _safe_float(target_annual_revenue)
  stage_clean = _clean_text(stage).lower()
  growth_stage_tokens = {"growth", "scaling", "growth-stage", "expansion"}
  mature_stage_tokens = {"mature", "operational", "established", "steady-state"}
  early_stage_tokens = {
    "early", "early-stage", "pre-revenue", "pre_revenue", "startup",
    "seed", "founding",
  }

  if stage_clean in growth_stage_tokens:
    return ("mid", "large")
  if stage_clean in mature_stage_tokens:
    if rev is None or rev >= 50_000_000:
      return ("mid", "large")
    return ("small", "mid")
  if stage_clean in early_stage_tokens:
    return ("small", "mid")
  # Stage not identified or supplied — fall back to revenue heuristic.
  if rev is None:
    return ("small", "mid", "large")
  if rev < 5_000_000:
    return ("small", "mid")
  if rev < 50_000_000:
    return ("small", "mid", "large")
  return ("mid", "large")


def _revenue_bucket_label(target_annual_revenue: Optional[float]) -> str:
  rev = _safe_float(target_annual_revenue) or 0.0
  if rev <= 0:
    return "unknown_revenue"
  buckets = (
    (250_000, "lt_250k"),
    (1_000_000, "250k_1M"),
    (5_000_000, "1M_5M"),
    (25_000_000, "5M_25M"),
    (100_000_000, "25M_100M"),
    (1_000_000_000, "100M_1B"),
  )
  for ceiling, label in buckets:
    if rev < ceiling:
      return label
  return "gte_1B"


def _percentile(sorted_values: List[float], pct: float) -> Optional[float]:
  """Return the linearly-interpolated percentile of a sorted list.

  Equivalent to NumPy's default percentile method (linear). Implemented
  in pure Python so this module has no NumPy dependency at import time.
  """
  if not sorted_values:
    return None
  if len(sorted_values) == 1:
    return float(sorted_values[0])
  rank = (len(sorted_values) - 1) * (float(pct) / 100.0)
  lo = int(rank)
  hi = min(lo + 1, len(sorted_values) - 1)
  weight = rank - lo
  return float(sorted_values[lo]) * (1.0 - weight) + float(sorted_values[hi]) * weight


def _confidence_tier_for_cohort_size(n: int) -> str:
  if n >= _TIER_HIGH_MIN_N:
    return "high"
  if n >= _TIER_MEDIUM_MIN_N:
    return "medium"
  # Below the low threshold the band is still COHORT-DERIVED (the true
  # cohort_size rides the row for consumers to weigh) - it is a
  # low-confidence band, in the contract's shared 4-value vocabulary
  # (high/medium/low/generic_default). The old "fallback" tier predated
  # that vocabulary and was never in it: the first tiny-cohort business
  # (Ironwood HVAC, R&D n=5) had its rows REJECTED by the read contract,
  # which erased all five sections in the mirror and failed the run.
  # Writer and reader must share one vocabulary - fail at write time or
  # emit a legal value, never a word the reader is contracted to refuse.
  return "low"


def compute_band_from_rows(
  *,
  rows: List[Dict[str, Any]],
  metric_column: str,
) -> Tuple[Optional[float], Optional[float], Optional[float], int]:
  """Pure-Python percentile band computation from a list of dict rows.

  Public so unit tests can pass synthetic rows without hitting MySQL.
  Returns (p25, p50, p75, n_used) where n_used counts rows whose
  metric_column value parsed as a finite number.
  """
  values: List[float] = []
  for row in rows:
    if not isinstance(row, dict):
      continue
    raw = row.get(metric_column)
    parsed = _safe_float(raw)
    if parsed is None:
      continue
    values.append(parsed)
  values.sort()
  n_used = len(values)
  if n_used == 0:
    return (None, None, None, 0)
  return (
    _percentile(values, 25.0),
    _percentile(values, 50.0),
    _percentile(values, 75.0),
    n_used,
  )


# ---------------------------------------------------------------------------
# Process-memory cohort-rows cache.
#
# Key shape: (naics_prefix, naics_level, revenue_window_min, revenue_window_max,
#             cap_categories_tuple, fiscal_year_min, fiscal_year_max).
# Value: list of dict rows (already filtered).
#
# Caching is at the row-set level (not at the metric_column level) so all
# metric bands for the same cohort share one query. Caching is process-
# wide and persists for the process lifetime; for a planning run that's
# a fresh process most of the time, but if the process is reused across
# runs, NAICS / revenue / stage variation produces different keys so the
# cache stays correct.
# ---------------------------------------------------------------------------

_COHORT_ROWS_CACHE: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
_COHORT_ROWS_LOCK = threading.Lock()
# When the DB is unreachable or the connection module is missing, set a
# process-level flag so subsequent cohort attempts short-circuit to []
# instead of triggering another connection error per (NAICS-level x
# revenue-window x date-window) combination. The flag is cleared when
# clear_cohort_cache() is called.
_DB_UNREACHABLE_FLAG = {"value": False}


def _cohort_cache_key(
  *,
  table_name: str,
  naics_prefix: str,
  naics_level: int,
  revenue_window: Optional[Tuple[float, float]],
  cap_categories: Tuple[str, ...],
  fiscal_year_min: int,
) -> Tuple[Any, ...]:
  rev = revenue_window if revenue_window is not None else (None, None)
  return (
    table_name,
    naics_prefix,
    int(naics_level),
    rev[0],
    rev[1],
    tuple(sorted(cap_categories)),
    int(fiscal_year_min),
  )


def _query_cohort_rows(
  *,
  table_name: str,
  naics_prefix: str,
  naics_level: int,
  revenue_window: Optional[Tuple[float, float]],
  cap_categories: Tuple[str, ...],
  fiscal_year_min: int,
) -> List[Dict[str, Any]]:
  """Run the cohort SELECT against the specified industry_metrics_* table.
  Caches by (table, filter shape) for the process lifetime. Returns [] on
  any DB error so the resolver can transparently fall back.

  Only `industry_metrics_alpha` and `industry_metrics_edgar` are valid;
  other names are rejected to prevent SQL injection via the table param.
  """
  if table_name not in {t for _src, t in _COHORT_TABLES}:
    raise ValueError(f"unknown cohort table: {table_name}")
  cache_key = _cohort_cache_key(
    table_name=table_name,
    naics_prefix=naics_prefix,
    naics_level=naics_level,
    revenue_window=revenue_window,
    cap_categories=cap_categories,
    fiscal_year_min=fiscal_year_min,
  )
  with _COHORT_ROWS_LOCK:
    cached = _COHORT_ROWS_CACHE.get(cache_key)
    if cached is not None:
      return cached
    if _DB_UNREACHABLE_FLAG["value"]:
      _COHORT_ROWS_CACHE[cache_key] = []
      return []

  try:
    from client_intake_and_finmo.intake_submission import get_mysql_connection  # type: ignore
  except Exception as exc:
    logger.warning("cohort_resolver_db_module_import_failed: %s", exc)
    with _COHORT_ROWS_LOCK:
      _DB_UNREACHABLE_FLAG["value"] = True
      _COHORT_ROWS_CACHE[cache_key] = []
    return []

  metric_columns = sorted(_KNOWN_METRIC_COLUMNS)
  # `symbol` is selected so we can count distinct firms (the gating
  # threshold is now firm count, not row count).
  select_columns = (
    ["symbol", "naics_code", "cap_category", "fiscalDateEnding", "total_revenue"]
    + metric_columns
  )
  select_sql = ", ".join(f"`{col}`" for col in select_columns)
  filters = [
    "`naics_code` LIKE %s",
    "`naics_code` IS NOT NULL",
    "`naics_code` <> ''",
    "YEAR(`fiscalDateEnding`) >= %s",
  ]
  like_pattern = naics_prefix + ("%" if naics_level < 6 else "")
  params: List[Any] = [like_pattern, int(fiscal_year_min)]
  if revenue_window is not None:
    rev_lo, rev_hi = revenue_window
    filters.append("`total_revenue` BETWEEN %s AND %s")
    params.extend([float(rev_lo), float(rev_hi)])
  else:
    filters.append("`total_revenue` > 0")
  if cap_categories:
    placeholders = ",".join(["%s"] * len(cap_categories))
    filters.append(f"`cap_category` IN ({placeholders})")
    params.extend(cap_categories)
  sql = (
    f"SELECT {select_sql} FROM `{table_name}` "
    f"WHERE {' AND '.join(filters)}"
  )

  try:
    conn = get_mysql_connection()
  except Exception as exc:
    logger.warning("cohort_resolver_db_connect_failed: %s", exc)
    with _COHORT_ROWS_LOCK:
      _DB_UNREACHABLE_FLAG["value"] = True
      _COHORT_ROWS_CACHE[cache_key] = []
    return []
  rows: List[Dict[str, Any]] = []
  try:
    cur = conn.cursor(dictionary=True)
    try:
      cur.execute(sql, tuple(params))
      raw_rows = cur.fetchall() or []
      for raw in raw_rows:
        if isinstance(raw, dict):
          rows.append(dict(raw))
    finally:
      try:
        cur.close()
      except Exception:
        pass
  except Exception as exc:
    logger.warning("cohort_resolver_db_query_failed: %s", exc)
    rows = []
  finally:
    try:
      conn.close()
    except Exception:
      pass

  with _COHORT_ROWS_LOCK:
    _COHORT_ROWS_CACHE[cache_key] = rows
  return rows


def clear_cohort_cache() -> None:
  """Drop the process-memory cohort cache. Called at the start of a
  planning run so a fresh /post-grid invocation gets fresh queries."""
  with _COHORT_ROWS_LOCK:
    _COHORT_ROWS_CACHE.clear()
    _DB_UNREACHABLE_FLAG["value"] = False


# ---------------------------------------------------------------------------
# Public resolver entry point.
# ---------------------------------------------------------------------------


def _try_cohort_at_filter(
  *,
  table_name: str,
  naics_prefix: str,
  naics_level: int,
  revenue_window: Optional[Tuple[float, float]],
  cap_categories: Tuple[str, ...],
  fiscal_year_min: int,
  metric_column: str,
) -> Tuple[Optional[Tuple[float, float, float]], int, int]:
  """Query one (table, NAICS prefix, revenue window, date window) combo.

  Returns (band_or_None, n_rows_used, distinct_firm_count). The firm
  count is what gates acceptance (≥ 2 firms = qualifies); the row count
  is informational and used for confidence-tier tagging.
  """
  rows = _query_cohort_rows(
    table_name=table_name,
    naics_prefix=naics_prefix,
    naics_level=naics_level,
    revenue_window=revenue_window,
    cap_categories=cap_categories,
    fiscal_year_min=fiscal_year_min,
  )
  # Count distinct firms with a non-null value for THIS metric column.
  firm_set: set = set()
  for r in rows:
    if not isinstance(r, dict):
      continue
    if r.get(metric_column) is None:
      continue
    sym = r.get("symbol")
    if sym:
      firm_set.add(sym)
  firm_count = len(firm_set)
  p25, p50, p75, n_used = compute_band_from_rows(
    rows=rows, metric_column=metric_column,
  )
  if firm_count < _COHORT_FIRM_MIN or p50 is None:
    return None, n_used, firm_count
  return (p25, p50, p75), n_used, firm_count


def _current_year() -> int:
  from datetime import datetime
  return datetime.utcnow().year


def resolve_cohort_band(
  *,
  metric_key: str,
  business_profile: Dict[str, Any],
  metric_column_override: Optional[str] = None,
) -> Optional[CohortBandResult]:
  """Resolve a cohort-matched percentile band for a single metric using
  the alternating EDGAR/Alpha walk.

  Walk order:
    (level=6, edgar) -> (level=6, alpha) ->
    (level=5, edgar) -> (level=5, alpha) ->
    (level=4, edgar) -> (level=4, alpha) ->
    (level=3, edgar) -> (level=3, alpha) ->
    (level=2, edgar) -> (level=2, alpha)

  At each (level, source) pair we still apply the existing cohort
  widening (revenue window, date window) but accept the FIRST combo that
  yields >= 2 distinct firms. EDGAR-first reflects the directive that an
  EDGAR NAICS-5 cohort is more relevant than an Alpha NAICS-2 cohort.

  Args:
    metric_key: a key from METRIC_KEY_TO_COLUMN, OR a lever_id from
      LEVER_TO_METRIC_COLUMN. The function looks up the column itself.
    business_profile: dict with keys naics_6, target_annual_revenue,
      stage (optional), business_model (optional, used only for cache
      partitioning and provenance).
    metric_column_override: bypass the maps and target a specific
      industry_metrics_* column.

  Returns:
    CohortBandResult on success (table, level, firm_count tagged on
    provenance); None when no level/source pair yields >= 2 firms.
  """
  metric_column = (
    _clean_text(metric_column_override)
    or LEVER_TO_METRIC_COLUMN.get(_clean_text(metric_key))
    or METRIC_KEY_TO_COLUMN.get(_clean_text(metric_key))
  )
  if not metric_column or metric_column not in _KNOWN_METRIC_COLUMNS:
    return None

  naics_6 = _normalized_naics_6(business_profile.get("naics_6") or business_profile.get("business_naics_6"))
  if not naics_6 or len(naics_6) < 2:
    return None
  target_revenue = _safe_float(business_profile.get("target_annual_revenue"))
  stage = business_profile.get("stage") or business_profile.get("business_stage")
  cap_categories = map_revenue_to_cap_categories(
    target_annual_revenue=target_revenue,
    stage=stage,
  )

  current_year = _current_year()
  attempts: List[Dict[str, Any]] = []
  # Revenue/date widening — same as before; tried within each
  # (level, source) before moving on.
  revenue_ladder: List[Optional[Tuple[float, float]]] = []
  if target_revenue and target_revenue > 0:
    for lo, hi in _REVENUE_WINDOW_LADDER:
      revenue_ladder.append((float(target_revenue) * lo, float(target_revenue) * hi))
  revenue_ladder.append(None)
  date_ladder = list(_DATE_WINDOW_YEARS_LADDER)

  # Outer alternating walk: at each NAICS level, try EDGAR then Alpha.
  for naics_level in _NAICS_LEVEL_LADDER:
    if naics_level > len(naics_6):
      continue
    naics_prefix = naics_6[:naics_level]
    for source_tag, table_name in _COHORT_TABLES:
      best_at_this_pair: Optional[Tuple[Tuple[float, float, float], int, int, Dict[str, Any]]] = None
      for revenue_window in revenue_ladder:
        for window_years in date_ladder:
          fiscal_year_min = max(1990, current_year - int(window_years))
          attempt_descr = {
            "naics_level": naics_level,
            "naics_prefix": naics_prefix,
            "source": source_tag,
            "table": table_name,
            "revenue_window": revenue_window,
            "cap_categories": list(cap_categories),
            "fiscal_year_min": fiscal_year_min,
          }
          band, n_rows, n_firms = _try_cohort_at_filter(
            table_name=table_name,
            naics_prefix=naics_prefix,
            naics_level=naics_level,
            revenue_window=revenue_window,
            cap_categories=cap_categories,
            fiscal_year_min=fiscal_year_min,
            metric_column=metric_column,
          )
          attempts.append({**attempt_descr, "n_rows": n_rows, "n_firms": n_firms})
          if band is not None:
            if best_at_this_pair is None or n_firms > best_at_this_pair[2]:
              best_at_this_pair = (band, n_rows, n_firms, attempt_descr)
      if best_at_this_pair is not None:
        # Found a (level, source) that satisfies >= 2 firms — pick it
        # and stop. This is the "first level/source wins" semantic.
        (p25, p50, p75), n_rows, n_firms, picked = best_at_this_pair
        confidence = _confidence_tier_for_cohort_size(n_rows)
        return CohortBandResult(
          metric_key=_clean_text(metric_key),
          metric_column=metric_column,
          benchmark_min=round(float(p25), 6) if p25 is not None else None,
          benchmark_target=round(float(p50), 6) if p50 is not None else None,
          benchmark_max=round(float(p75), 6) if p75 is not None else None,
          cohort_size=n_rows,
          firm_count=n_firms,
          confidence_tier=confidence,
          cohort_table=picked["source"],
          naics_level_used=picked["naics_level"],
          naics_prefix_used=picked["naics_prefix"],
          cohort_query={
            "naics_6": naics_6,
            "naics_level_used": picked["naics_level"],
            "naics_prefix": picked["naics_prefix"],
            "cohort_table": picked["source"],
            "revenue_window": picked["revenue_window"],
            "cap_categories": picked["cap_categories"],
            "fiscal_year_min": picked["fiscal_year_min"],
            "revenue_bucket": _revenue_bucket_label(target_revenue),
            "stage": _clean_text(stage) or None,
            "business_model": _clean_text(business_profile.get("business_model")) or None,
            "attempts": attempts,
          },
          data_source=f"cohort_alternating_{picked['source']}",
        )
  # No (level, source) pair yielded >= 2 firms.
  return None


def cohort_calibration_source_for_confidence(confidence_tier: str) -> str:
  tier = _clean_text(confidence_tier).lower()
  if tier == "high":
    return "cohort_matched_high_confidence"
  if tier == "medium":
    return "cohort_matched_medium_confidence"
  if tier == "low":
    return "cohort_matched_low_confidence"
  return "cohort_matched_unknown"
