"""Industry baseline resolver — Module 1, Task 1.1 + 1.7.

Implements the NAICS coverage cascade (6 -> 5 -> 4 -> 3 -> 2 -> 0 ->
no_coverage) over `post_intake_industry_baseline_lookup` per the contract
documented in `context/system_overview_update_4.25.26.md` §"Coverage cascade
contract" and `context/post_intake_master_diagnostic_2026-05-05.md` Part 5
Phase 0.

Cascade contract:
- L6: only return if `data_source = registry.primary_source` AND
  `confidence_tier IN ('high','medium')`. Else fall through.
- L5: any row at L5; cap confidence at medium (high -> medium).
- L4: any row at L4; cap confidence at medium.
- L3: any row at L3; cap confidence at low.
- L2: any row at L2; cap confidence at low.
- L0: generic_default row at naics_code='*'; confidence = generic_default.
- None of the above: trust_flag='no_coverage'. If
  `metric_registry.fail_if_no_coverage = 1`, raise.

The substitution sites that consume the resolver write to forecast Q1-Q20
ONLY — never stub 0 (Part 9.1 invariant).
"""

from __future__ import annotations

import os
import threading
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from client_intake_and_finmo.intake_submission import get_mysql_connection


BASELINE_LOOKUP_TABLE = "post_intake_industry_baseline_lookup"
METRIC_REGISTRY_TABLE = "post_intake_industry_metric_registry"

# Trust-flag enum returned by the resolver.
TRUST_NAICS_6_DIRECT = "naics_6_direct"
TRUST_NAICS_5_FALLBACK = "naics_5_fallback"
TRUST_NAICS_4_FALLBACK = "naics_4_fallback"
TRUST_NAICS_3_FALLBACK = "naics_3_fallback"
TRUST_NAICS_2_FALLBACK = "naics_2_fallback"
TRUST_GENERIC_DEFAULT = "generic_default"
TRUST_NO_COVERAGE = "no_coverage"

_TRUST_BY_LEVEL = {
  6: TRUST_NAICS_6_DIRECT,
  5: TRUST_NAICS_5_FALLBACK,
  4: TRUST_NAICS_4_FALLBACK,
  3: TRUST_NAICS_3_FALLBACK,
  2: TRUST_NAICS_2_FALLBACK,
  0: TRUST_GENERIC_DEFAULT,
}

_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1, "generic_default": 0}


class PostIntakeIndustryBaselineNoCoverage(RuntimeError):
  """Raised when the metric registry says fail_if_no_coverage and the cascade
  exhausts every NAICS level without finding a row.
  """


# ----------------------------------------------------------------------------
# Env loader (mirrors the headcount-lookup pattern; no extra deps).
# ----------------------------------------------------------------------------

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


# ----------------------------------------------------------------------------
# Metric registry (49 rows; cache on first call).
# ----------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_metric_registry() -> Dict[str, Dict[str, Any]]:
  _ensure_env_loaded()
  conn = get_mysql_connection()
  try:
    cur = conn.cursor(dictionary=True)
    try:
      cur.execute(
        f"""
        SELECT metric_key,
               metric_domain,
               metric_label,
               unit,
               primary_source,
               secondary_source,
               applies_to_statement,
               governs_model_input_lever,
               fail_if_no_coverage
        FROM `{METRIC_REGISTRY_TABLE}`
        WHERE active = 1
        """
      )
      rows = cur.fetchall() or []
    finally:
      cur.close()
  finally:
    conn.close()
  by_key: Dict[str, Dict[str, Any]] = {}
  for row in rows:
    metric_key = (row.get("metric_key") or "").strip()
    if not metric_key:
      continue
    by_key[metric_key] = {
      "metric_key": metric_key,
      "metric_domain": (row.get("metric_domain") or "").strip(),
      "metric_label": (row.get("metric_label") or "").strip(),
      "unit": (row.get("unit") or "").strip(),
      "primary_source": (row.get("primary_source") or "").strip() or None,
      "secondary_source": (row.get("secondary_source") or "").strip() or None,
      "applies_to_statement": (row.get("applies_to_statement") or "").strip() or None,
      "governs_model_input_lever": (
        (row.get("governs_model_input_lever") or "").strip() or None
      ),
      "fail_if_no_coverage": bool(row.get("fail_if_no_coverage") or 0),
    }
  return by_key


def post_intake_industry_metric_registry_row(metric_key: str) -> Dict[str, Any]:
  registry = _load_metric_registry()
  row = registry.get(str(metric_key or "").strip())
  if not row:
    raise KeyError(f"post_intake_industry_metric_registry_unknown_metric_key: {metric_key}")
  return dict(row)


def post_intake_industry_metric_governs_lever(metric_key: str) -> Optional[str]:
  try:
    return post_intake_industry_metric_registry_row(metric_key).get("governs_model_input_lever")
  except KeyError:
    return None


# ----------------------------------------------------------------------------
# Cascade resolver.
# ----------------------------------------------------------------------------


def _normalize_naics(naics: Any) -> str:
  text = "".join(ch for ch in str(naics or "") if ch.isdigit())
  return text


def _truncate_to_level(naics_6_digits: str, level: int) -> str:
  if level <= 0:
    return "*"
  return naics_6_digits[:level]


def _query_baseline_row(
  conn,
  *,
  metric_key: str,
  naics_code: str,
  naics_level: int,
  data_source: Optional[str] = None,
  confidence_tiers: Optional[Tuple[str, ...]] = None,
) -> Optional[Dict[str, Any]]:
  cur = conn.cursor(dictionary=True)
  try:
    sql = (
      f"SELECT naics_code, naics_level, naics_title, "
      f"benchmark_min, benchmark_target, benchmark_max, "
      f"data_source, source_year, sample_size, confidence_tier "
      f"FROM `{BASELINE_LOOKUP_TABLE}` "
      f"WHERE metric_key = %s AND naics_code = %s AND naics_level = %s AND active = 1"
    )
    params: List[Any] = [metric_key, naics_code, naics_level]
    if data_source:
      sql += " AND data_source = %s"
      params.append(data_source)
    if confidence_tiers:
      placeholders = ",".join(["%s"] * len(confidence_tiers))
      sql += f" AND confidence_tier IN ({placeholders})"
      params.extend(confidence_tiers)
    sql += (
      # Order: best confidence first (high < medium < low < generic_default per
      # FIELD ordering); within tier, largest sample size first.
      " ORDER BY FIELD(confidence_tier,'high','medium','low','generic_default') ASC, "
      "sample_size DESC LIMIT 1"
    )
    cur.execute(sql, tuple(params))
    return cur.fetchone()
  finally:
    cur.close()


def _downgrade_confidence(raw_confidence: str, *, level_used: int) -> str:
  raw = (raw_confidence or "").strip().lower() or "generic_default"
  if level_used == 6:
    return raw
  if level_used in (5, 4):
    # Cap at medium.
    return "medium" if _CONFIDENCE_RANK.get(raw, 0) >= 3 else raw
  if level_used in (3, 2):
    # Cap at low.
    return "low" if _CONFIDENCE_RANK.get(raw, 0) >= 2 else raw
  if level_used == 0:
    return "generic_default"
  return raw


def _payload_from_row(
  row: Dict[str, Any],
  *,
  level_used: int,
  fallback_chain: List[str],
  trust_flag: str,
  metric_key: str,
) -> Dict[str, Any]:
  raw_confidence = (row.get("confidence_tier") or "").strip().lower() or "generic_default"
  return {
    "metric_key": metric_key,
    "benchmark_min": _decimal_to_float(row.get("benchmark_min")),
    "benchmark_target": _decimal_to_float(row.get("benchmark_target")),
    "benchmark_max": _decimal_to_float(row.get("benchmark_max")),
    "naics_code_used": str(row.get("naics_code") or "").strip(),
    "naics_level_used": int(level_used),
    "data_source": str(row.get("data_source") or "").strip(),
    "source_year": int(row["source_year"]) if row.get("source_year") is not None else None,
    "sample_size": int(row["sample_size"]) if row.get("sample_size") is not None else None,
    "confidence_tier": _downgrade_confidence(raw_confidence, level_used=level_used),
    "raw_confidence_tier": raw_confidence,
    "trust_flag": trust_flag,
    "fallback_chain_attempted": list(fallback_chain),
  }


# Phase 9 P3 — generic-default bands for the two new working-capital
# structure metrics (Targets 3 & 4 in the target-driven restoration
# loop). The cohort tables (industry_metrics_alpha / industry_metrics_edgar)
# only store derived ratios, not raw balance sheet items; until those
# tables are extended with the components needed to compute these
# metrics empirically per NAICS, fall back to cross-industry defaults
# when both the alternating-walk and the baseline lookup come up empty.
#
# Bands sourced from typical small-business working-capital structure:
#   current_assets_minus_cash / revenue ≈ 15-30% of quarterly revenue
#     (AR + inventory + prepaid combined)
#   current_liabilities / revenue       ≈  8-20% of quarterly revenue
#     (AP + short-term debt + accrued + deferred)
#
# Phase 9 P3 callers: realism gate Targets 3 & 4 in
# python/client_intake_and_finmo/post_intake_realism/lookup.py
_PHASE_9_P3_GENERIC_BANDS: Dict[str, Tuple[float, float, float]] = {
  # (min, target, max) — ratios against quarterly revenue.
  "current_assets_minus_cash": (0.15, 0.225, 0.30),
  "current_liabilities_to_revenue": (0.08, 0.14, 0.20),
}


def _phase_9_p3_generic_default_payload(
  *, metric_key: str, fallback_chain: List[str]
) -> Optional[Dict[str, Any]]:
  band = _PHASE_9_P3_GENERIC_BANDS.get(metric_key)
  if band is None:
    return None
  band_min, band_target, band_max = band
  fallback_chain.append("phase_9_p3_generic_default")
  return {
    "metric_key": metric_key,
    "benchmark_min": float(band_min),
    "benchmark_target": float(band_target),
    "benchmark_max": float(band_max),
    "naics_code_used": "*",
    "naics_level_used": 0,
    "data_source": "phase_9_p3_generic_default",
    "source_year": None,
    "sample_size": None,
    "confidence_tier": "generic_default",
    "raw_confidence_tier": None,
    "trust_flag": TRUST_GENERIC_DEFAULT,
    "fallback_chain_attempted": list(fallback_chain),
  }


def _no_coverage_payload(
  *, metric_key: str, fallback_chain: List[str]
) -> Dict[str, Any]:
  return {
    "metric_key": metric_key,
    "benchmark_min": None,
    "benchmark_target": None,
    "benchmark_max": None,
    "naics_code_used": None,
    "naics_level_used": None,
    "data_source": None,
    "source_year": None,
    "sample_size": None,
    "confidence_tier": "generic_default",
    "raw_confidence_tier": None,
    "trust_flag": TRUST_NO_COVERAGE,
    "fallback_chain_attempted": list(fallback_chain),
  }


def _decimal_to_float(value: Any) -> Optional[float]:
  if value is None:
    return None
  try:
    return float(value)
  except Exception:
    return None


# ----------------------------------------------------------------------------
# Alternating cohort walk (EDGAR L6 -> Alpha L6 -> EDGAR L5 -> Alpha L5 -> ...)
# ----------------------------------------------------------------------------
#
# When a metric has a corresponding column in the cohort tables
# (industry_metrics_alpha / industry_metrics_edgar), this walk runs BEFORE
# the post_intake_industry_baseline_lookup cascade. The first level/source
# pair that yields >= 2 distinct firms wins; otherwise we fall through to
# the cascade. Threshold and pair-order match the directive.

_COHORT_ALT_TABLES: Tuple[Tuple[str, str], ...] = (
  ("edgar", "industry_metrics_edgar"),
  ("alpha", "industry_metrics_alpha"),
)
_COHORT_ALT_FIRM_MIN = 2


def _cohort_alt_metric_column(metric_key: str) -> Optional[str]:
  """Return the cohort-table column for this metric_key, or None if the
  metric isn't covered by the cohort tables. Mirrors the map used by
  cohort_band_resolver.METRIC_KEY_TO_COLUMN."""
  m = (metric_key or "").strip()
  return {
    "cogs_to_revenue_ratio": "cogs_percent",
    "cogs_percent_of_revenue": "cogs_percent",
    "gross_margin_percent": "gross_margin_q",
    "marketing_percent_of_revenue": "sga_percent",   # SGA proxy
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
  }.get(m)


def _cohort_alt_query_band(
  *, conn, table_name: str, naics_prefix: str, naics_level: int,
  metric_column: str,
) -> Tuple[Optional[Tuple[float, float, float]], int, int]:
  """Run a single cohort query against (table, NAICS prefix). Returns
  (band_or_None, distinct_firm_count, row_count). band is None when
  fewer than 2 distinct firms have a non-null value for this metric."""
  if table_name not in {t for _src, t in _COHORT_ALT_TABLES}:
    raise ValueError(f"unknown cohort table: {table_name}")
  if naics_level == 6:
    like_clause = "naics_code = %s"
    pattern: Any = naics_prefix
  else:
    like_clause = "naics_code LIKE %s"
    pattern = naics_prefix + "%"
  cur = conn.cursor()
  try:
    cur.execute(
      f"SELECT symbol, `{metric_column}` FROM `{table_name}` "
      f"WHERE {like_clause} AND naics_code IS NOT NULL AND `{metric_column}` IS NOT NULL",
      (pattern,),
    )
    rows = cur.fetchall() or []
  finally:
    cur.close()
  values: List[float] = []
  firms: set = set()
  for sym, val in rows:
    if val is None:
      continue
    try:
      v = float(val)
    except Exception:
      continue
    if v != v:  # NaN
      continue
    values.append(v)
    if sym:
      firms.add(sym)
  firm_count = len(firms)
  row_count = len(values)
  if firm_count < _COHORT_ALT_FIRM_MIN or row_count == 0:
    return None, firm_count, row_count
  values.sort()
  def pct(p: float) -> float:
    if len(values) == 1:
      return values[0]
    rank = (len(values) - 1) * (p / 100.0)
    lo = int(rank)
    hi = min(lo + 1, len(values) - 1)
    w = rank - lo
    return values[lo] * (1.0 - w) + values[hi] * w
  return (pct(25.0), pct(50.0), pct(75.0)), firm_count, row_count


def _cohort_alt_walk(
  *, conn, metric_key: str, naics_6_clean: str,
) -> Optional[Dict[str, Any]]:
  """Alternating EDGAR/Alpha walk. Returns a payload dict matching the
  shape of `_payload_from_row` if any (level, source) pair yields >= 2
  firms, else None."""
  metric_column = _cohort_alt_metric_column(metric_key)
  if not metric_column:
    return None
  if not naics_6_clean or len(naics_6_clean) < 2:
    return None
  attempts: List[str] = []
  for level in (6, 5, 4, 3, 2):
    if level > len(naics_6_clean):
      continue
    prefix = naics_6_clean[:level]
    for source_tag, table_name in _COHORT_ALT_TABLES:
      band, firm_count, row_count = _cohort_alt_query_band(
        conn=conn, table_name=table_name,
        naics_prefix=prefix, naics_level=level,
        metric_column=metric_column,
      )
      attempts.append(f"naics_{level}:{prefix}:{source_tag}:firms={firm_count}")
      if band is None:
        continue
      p25, p50, p75 = band
      return {
        "metric_key": metric_key,
        "benchmark_min": float(p25) if p25 is not None else None,
        "benchmark_target": float(p50) if p50 is not None else None,
        "benchmark_max": float(p75) if p75 is not None else None,
        "naics_code_used": prefix,
        "naics_level_used": level,
        "data_source": f"cohort_alternating_{source_tag}",
        "source_year": None,
        "sample_size": row_count,
        "confidence_tier": (
          "high" if row_count >= 50 else
          "medium" if row_count >= 20 else
          "low"
        ),
        "raw_confidence_tier": None,
        "trust_flag": _TRUST_BY_LEVEL.get(level, TRUST_NAICS_2_FALLBACK),
        "fallback_chain_attempted": attempts,
        "cohort_table": source_tag,
        "firm_count": firm_count,
      }
  return None


def post_intake_industry_baseline_for_naics(
  *,
  metric_key: str,
  naics_6: str,
) -> Dict[str, Any]:
  """Resolve a NAICS baseline benchmark for one metric_key.

  Resolution order:
    1. Alternating cohort walk over industry_metrics_edgar /
       industry_metrics_alpha — EDGAR-first at each NAICS level, then
       Alpha. First level/source pair with >= 2 distinct firms wins.
       (Only tried for metrics with a cohort-table column.)
    2. Existing post_intake_industry_baseline_lookup cascade for metrics
       not covered by cohort tables, OR when the alternating walk turns
       up nothing across all levels.

  Stamps `trust_flag`, `naics_level_used`, downgraded `confidence_tier`,
  and the full `fallback_chain_attempted` so callers can carry
  provenance into model_input.

  Raises `PostIntakeIndustryBaselineNoCoverage` only when both
  resolutions fail AND the metric registry says `fail_if_no_coverage = 1`.
  """
  metric_key_clean = str(metric_key or "").strip()
  if not metric_key_clean:
    raise ValueError("post_intake_industry_baseline_metric_key_required")
  try:
    registry_row = post_intake_industry_metric_registry_row(metric_key_clean)
    primary_source = registry_row.get("primary_source")
    fail_if_no_coverage = bool(registry_row.get("fail_if_no_coverage"))
  except KeyError:
    # Phase 9 P3 — metric not yet in post_intake_industry_metric_registry
    # (e.g. the new current_assets_minus_cash / current_liabilities_to_revenue
    # targets). Treat as no-registry-row: skip primary-source-only L6 path,
    # try generic-default-aware cascade, then fall through to inline
    # generic-default payload for known-band metrics.
    primary_source = None
    fail_if_no_coverage = False

  digits = _normalize_naics(naics_6)
  if len(digits) < 2:
    # Without at least two digits we cannot descend; treat as no_coverage at
    # generic_default level rather than guessing.
    digits = ""

  fallback_chain: List[str] = []
  _ensure_env_loaded()
  conn = get_mysql_connection()
  try:
    # Step 1: alternating cohort walk over the split tables.
    if digits and _cohort_alt_metric_column(metric_key_clean):
      cohort_payload = _cohort_alt_walk(
        conn=conn, metric_key=metric_key_clean, naics_6_clean=digits,
      )
      if cohort_payload is not None:
        return cohort_payload
      fallback_chain.append("cohort_alternating:no_match")
    # L6: primary-source-only, high/medium confidence.
    if digits and len(digits) >= 6 and primary_source:
      l6_code = _truncate_to_level(digits, 6)
      fallback_chain.append(f"naics_6:{l6_code}:primary_source={primary_source}")
      row = _query_baseline_row(
        conn,
        metric_key=metric_key_clean,
        naics_code=l6_code,
        naics_level=6,
        data_source=primary_source,
        confidence_tiers=("high", "medium"),
      )
      if row:
        return _payload_from_row(
          row,
          level_used=6,
          fallback_chain=fallback_chain,
          trust_flag=TRUST_NAICS_6_DIRECT,
          metric_key=metric_key_clean,
        )
    # L5/L4/L3/L2: any row, cascading.
    for level in (5, 4, 3, 2):
      if not digits or len(digits) < level:
        continue
      code = _truncate_to_level(digits, level)
      fallback_chain.append(f"naics_{level}:{code}")
      row = _query_baseline_row(
        conn,
        metric_key=metric_key_clean,
        naics_code=code,
        naics_level=level,
      )
      if row:
        return _payload_from_row(
          row,
          level_used=level,
          fallback_chain=fallback_chain,
          trust_flag=_TRUST_BY_LEVEL[level],
          metric_key=metric_key_clean,
        )
    # L0: generic_default.
    fallback_chain.append("naics_0:*")
    row = _query_baseline_row(
      conn,
      metric_key=metric_key_clean,
      naics_code="*",
      naics_level=0,
    )
    if row:
      return _payload_from_row(
        row,
        level_used=0,
        fallback_chain=fallback_chain,
        trust_flag=TRUST_GENERIC_DEFAULT,
        metric_key=metric_key_clean,
      )
  finally:
    conn.close()

  # Phase 9 P3 — inline generic-default for the new working-capital
  # structure metrics (Targets 3 & 4 in the target-driven restoration
  # loop). When cohort + table cascade both come up empty, return a
  # cross-industry default rather than no_coverage; the restoration
  # loop needs a band to solve against.
  generic_default = _phase_9_p3_generic_default_payload(
    metric_key=metric_key_clean, fallback_chain=fallback_chain
  )
  if generic_default is not None:
    return generic_default

  payload = _no_coverage_payload(
    metric_key=metric_key_clean, fallback_chain=fallback_chain
  )
  if fail_if_no_coverage:
    raise PostIntakeIndustryBaselineNoCoverage(
      "post_intake_industry_baseline_no_coverage: "
      f"metric_key={metric_key_clean} naics_6={naics_6} "
      f"fallback_chain_attempted={fallback_chain}"
    )
  return payload


# ----------------------------------------------------------------------------
# Provenance helper for substitution callers (Task 1.3-1.6).
# ----------------------------------------------------------------------------


def baseline_seed_provenance(payload: Dict[str, Any]) -> Dict[str, Any]:
  """Build the metadata dict to attach to a substituted model_input value."""
  return {
    "seed_source": "naics_cascade",
    "metric_key": payload.get("metric_key"),
    "naics_code_used": payload.get("naics_code_used"),
    "naics_level_used": payload.get("naics_level_used"),
    "confidence_tier": payload.get("confidence_tier"),
    "data_source": payload.get("data_source"),
    "sample_size": payload.get("sample_size"),
    "trust_flag": payload.get("trust_flag"),
  }


# ----------------------------------------------------------------------------
# NAICS-2 applicability lookup (Task 1.7).
# ----------------------------------------------------------------------------
#
# Distinguishes "stub 0 = 0 because legitimate (driver does not apply)" from
# "stub 0 = 0 because intake omitted." When applicable=False, callers must
# leave the value at zero (legitimate zero); the cascade is only consulted
# when applicable=True.
#
# Defaults follow Module 1 Task 1.7 — code constants for now, table later.
# Sectors are NAICS-2 strings.

_INVENTORY_APPLICABLE_NAICS2 = {
  # Manufacturing.
  "31", "32", "33",
  # Wholesale.
  "42",
  # Retail.
  "44", "45",
  # Accommodation/Food.
  "72",
}

_DEFERRED_REVENUE_APPLICABLE_NAICS2 = {
  # Information (publishers, software, telecom, data).
  "51",
  # Finance/Insurance (premiums, retainers, fee-based).
  "52",
  # Real Estate (lease prepayments, deposits).
  "53",
  # Professional/Scientific/Technical (retainers, contracts).
  "54",
}
_DEFERRED_REVENUE_NOT_APPLICABLE_NAICS2 = {
  # Retail / accommodation-food / personal services — point-of-sale, not
  # subscription/contract-based.
  "44", "45",
  "72",
  "81",
}

_R_AND_D_APPLICABLE_NAICS2 = {
  # Pharma / industrial / computer / transportation manufacturing.
  "32", "33",
  # Information / Professional/Scientific/Technical.
  "51", "54",
}
_R_AND_D_NOT_APPLICABLE_NAICS2 = {
  # Consumer-facing.
  "44", "45", "72", "81",
}


def post_intake_baseline_applicability_for_naics2(
  *,
  metric_key: str,
  naics_2: str,
) -> Dict[str, Any]:
  """Return whether a baseline metric applies for the given NAICS-2 sector.

  When `applicable` is False, the substitution caller MUST keep the value at
  zero (legitimate zero per Part 9.1) rather than substituting a NAICS band.
  When `applicable` is True, the resolver should be consulted normally.

  Conservative default: when sector is not explicitly classified for a metric
  that has applicability gating (e.g., deferred_revenue), return
  `applicable=False`. It is safer to leave a zero than to invent a non-zero
  for a business where the metric does not apply.
  """
  metric_key_clean = str(metric_key or "").strip()
  digits = _normalize_naics(naics_2)[:2]
  reason = ""

  if metric_key_clean == "inventory_days":
    if digits in _INVENTORY_APPLICABLE_NAICS2:
      return {
        "applicable": True,
        "reason": f"naics2_{digits}_inventory_sector",
        "confidence": "high",
      }
    return {
      "applicable": False,
      "reason": f"naics2_{digits}_no_inventory_default",
      "confidence": "medium",
    }

  if metric_key_clean == "deferred_revenue_percent_of_revenue":
    if digits in _DEFERRED_REVENUE_APPLICABLE_NAICS2:
      return {
        "applicable": True,
        "reason": f"naics2_{digits}_deferred_revenue_business_model",
        "confidence": "high",
      }
    if digits in _DEFERRED_REVENUE_NOT_APPLICABLE_NAICS2:
      return {
        "applicable": False,
        "reason": f"naics2_{digits}_point_of_sale_no_deferred_revenue",
        "confidence": "high",
      }
    # Conservative default for ambiguous sectors.
    return {
      "applicable": False,
      "reason": f"naics2_{digits}_deferred_revenue_default_off",
      "confidence": "low",
    }

  if metric_key_clean == "r_and_d_percent_of_revenue":
    if digits in _R_AND_D_APPLICABLE_NAICS2:
      return {
        "applicable": True,
        "reason": f"naics2_{digits}_r_and_d_sector",
        "confidence": "high",
      }
    if digits in _R_AND_D_NOT_APPLICABLE_NAICS2:
      return {
        "applicable": False,
        "reason": f"naics2_{digits}_consumer_facing_no_r_and_d",
        "confidence": "high",
      }
    return {
      "applicable": False,
      "reason": f"naics2_{digits}_r_and_d_default_off",
      "confidence": "low",
    }

  # Metrics without applicability gating apply universally.
  reason = "metric_has_no_applicability_gate"
  return {"applicable": True, "reason": reason, "confidence": "high"}
