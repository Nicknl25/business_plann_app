from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
  from intake_submission import get_mysql_connection  # type: ignore
except Exception:
  from client_intake_and_finmo.intake_submission import get_mysql_connection  # type: ignore

try:
  from planning_contract import FALLBACK_LEVELS, PLANNING_CONTRACT_VERSION  # type: ignore
except Exception:
  from client_intake_and_finmo.planning_contract import FALLBACK_LEVELS, PLANNING_CONTRACT_VERSION  # type: ignore


BENCHMARK_RESOLVER_VERSION = "benchmark-resolver/v1"


def _empty_band() -> Dict[str, Optional[float]]:
  return {"min": None, "max": None}


def _to_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  if isinstance(value, bool):
    return None
  if isinstance(value, (int, float)):
    return float(value)
  try:
    return float(str(value).strip().replace(",", ""))
  except Exception:
    return None


def _serialize_date(value: Any) -> Optional[str]:
  if isinstance(value, datetime):
    return value.date().isoformat()
  if isinstance(value, date):
    return value.isoformat()
  text = str(value or "").strip()
  return text or None


def _percentile(values: Sequence[float], pct: float) -> Optional[float]:
  clean = sorted(float(v) for v in values if v is not None)
  if not clean:
    return None
  if len(clean) == 1:
    return clean[0]
  rank = max(0.0, min(1.0, pct)) * (len(clean) - 1)
  low = int(rank)
  high = min(low + 1, len(clean) - 1)
  if low == high:
    return clean[low]
  weight = rank - low
  return (clean[low] * (1.0 - weight)) + (clean[high] * weight)


def _band_from_values(values: Sequence[float], fallback_value: Optional[float] = None) -> Dict[str, Optional[float]]:
  clean = [float(v) for v in values if v is not None]
  if clean:
    low = _percentile(clean, 0.25)
    high = _percentile(clean, 0.75)
    if low is not None and high is not None:
      return {"min": round(low, 6), "max": round(high, 6)}
  if fallback_value is not None:
    point = round(float(fallback_value), 6)
    return {"min": point, "max": point}
  return _empty_band()


def _extract_metric_values(rows: Sequence[Dict[str, Any]], key: str) -> List[float]:
  out: List[float] = []
  for row in rows:
    if not isinstance(row, dict):
      continue
    value = _to_float(row.get(key))
    if value is not None:
      out.append(value)
  return out


def _extract_opex_values(rows: Sequence[Dict[str, Any]]) -> List[float]:
  out: List[float] = []
  for row in rows:
    if not isinstance(row, dict):
      continue
    sga = _to_float(row.get("sga_percent")) or 0.0
    rnd = _to_float(row.get("rnd_percent")) or 0.0
    total = sga + rnd
    if total > 0:
      out.append(total)
  return out


def _build_growth_path(rows: Sequence[Dict[str, Any]]) -> List[float]:
  values: List[float] = []
  for row in reversed(list(rows or [])):
    if not isinstance(row, dict):
      continue
    value = _to_float(row.get("industry_revenue_growth_q") or row.get("median_revenue_growth_q"))
    if value is not None:
      values.append(round(value, 6))
  return values


def _confidence_score(*, fallback_level: str, sample_size: int, matched_level: Optional[int]) -> float:
  level_value = 0.0
  if fallback_level.startswith("naics_") and matched_level:
    level_value = max(0.0, min(1.0, float(matched_level) / 6.0))
  elif fallback_level == "trait_based":
    level_value = 0.45
  else:
    level_value = 0.25
  sample_value = max(0.0, min(1.0, float(sample_size) / 20.0))
  confidence = 0.2 + (0.5 * level_value) + (0.3 * sample_value)
  return round(max(0.05, min(0.95, confidence)), 3)


def _base_payload() -> Dict[str, Any]:
  return {
    "contract_version": PLANNING_CONTRACT_VERSION,
    "benchmark_resolver_version": BENCHMARK_RESOLVER_VERSION,
    "matched_naics_code": None,
    "matched_naics_level": None,
    "fallback_source": None,
    "fallback_level": "generic",
    "confidence_score": 0.05,
    "benchmark_recency": None,
    "revenue_growth_path": [],
    "gross_margin_band": _empty_band(),
    "ebitda_margin_band": _empty_band(),
    "opex_intensity": _empty_band(),
    "payroll_intensity": _empty_band(),
    "capex_percent_revenue": _empty_band(),
    "depreciation_percent_revenue": _empty_band(),
    "working_capital": {
      "dso": _empty_band(),
      "dpo": _empty_band(),
      "inventory_days": _empty_band(),
    },
  }


def _fetch_growth_rows(conn, *, naics_code: str, limit: int = 8) -> List[Dict[str, Any]]:
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      """
      SELECT *
      FROM industry_growth_table
      WHERE naics_code = %s
      ORDER BY fiscalDateEnding DESC, quarter DESC
      LIMIT %s
      """,
      (naics_code, int(limit)),
    )
    return list(cur.fetchall() or [])
  finally:
    try:
      cur.close()
    except Exception:
      pass


def _fetch_latest_raw_rows_for_naics(conn, *, naics_code: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      """
      SELECT MAX(fiscalDateEnding) AS latest_period
      FROM industry_metrics_raw
      WHERE naics_code = %s
      """,
      (naics_code,),
    )
    latest = cur.fetchone() or {}
    period = latest.get("latest_period")
    if not period:
      return [], None
    cur.execute(
      """
      SELECT *
      FROM industry_metrics_raw
      WHERE naics_code = %s
        AND fiscalDateEnding = %s
      """,
      (naics_code, period),
    )
    return list(cur.fetchall() or []), _serialize_date(period)
  finally:
    try:
      cur.close()
    except Exception:
      pass


def _fetch_sector_rows(conn, *, sector: str, limit_periods: int = 8) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      """
      SELECT MAX(imr.fiscalDateEnding) AS latest_period
      FROM industry_metrics_raw imr
      INNER JOIN alpha_match_naics_industry ami
        ON BINARY imr.symbol = BINARY ami.symbol
      WHERE LOWER(TRIM(ami.sector)) = LOWER(TRIM(%s))
      """,
      (sector,),
    )
    latest = cur.fetchone() or {}
    period = latest.get("latest_period")
    latest_rows: List[Dict[str, Any]] = []
    if period:
      cur.execute(
        """
        SELECT imr.*
        FROM industry_metrics_raw imr
        INNER JOIN alpha_match_naics_industry ami
          ON BINARY imr.symbol = BINARY ami.symbol
        WHERE LOWER(TRIM(ami.sector)) = LOWER(TRIM(%s))
          AND imr.fiscalDateEnding = %s
        """,
        (sector, period),
      )
      latest_rows = list(cur.fetchall() or [])

    cur.execute(
      """
      SELECT
        imr.fiscalDateEnding,
        imr.revenue_growth_q
      FROM industry_metrics_raw imr
      INNER JOIN alpha_match_naics_industry ami
        ON BINARY imr.symbol = BINARY ami.symbol
      WHERE LOWER(TRIM(ami.sector)) = LOWER(TRIM(%s))
        AND imr.revenue_growth_q IS NOT NULL
      ORDER BY imr.fiscalDateEnding DESC
      LIMIT %s
      """,
      (sector, int(limit_periods * 50)),
    )
    growth_rows = list(cur.fetchall() or [])
    return latest_rows, growth_rows, _serialize_date(period)
  finally:
    try:
      cur.close()
    except Exception:
      pass


def _fetch_prefix_rows(conn, *, naics_code: str, limit_periods: int = 8) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      """
      SELECT MAX(imr.fiscalDateEnding) AS latest_period
      FROM industry_metrics_raw imr
      INNER JOIN alpha_match_naics_industry ami
        ON BINARY imr.symbol = BINARY ami.symbol
      WHERE ami.naics_code IS NOT NULL
        AND TRIM(ami.naics_code) <> ''
        AND ami.naics_code LIKE CONCAT(%s, '%%')
      """,
      (naics_code,),
    )
    latest = cur.fetchone() or {}
    period = latest.get("latest_period")
    latest_rows: List[Dict[str, Any]] = []
    if period:
      cur.execute(
        """
        SELECT imr.*
        FROM industry_metrics_raw imr
        INNER JOIN alpha_match_naics_industry ami
          ON BINARY imr.symbol = BINARY ami.symbol
        WHERE ami.naics_code IS NOT NULL
          AND TRIM(ami.naics_code) <> ''
          AND ami.naics_code LIKE CONCAT(%s, '%%')
          AND imr.fiscalDateEnding = %s
        """,
        (naics_code, period),
      )
      latest_rows = list(cur.fetchall() or [])

    cur.execute(
      """
      SELECT
        imr.fiscalDateEnding,
        imr.revenue_growth_q
      FROM industry_metrics_raw imr
      INNER JOIN alpha_match_naics_industry ami
        ON BINARY imr.symbol = BINARY ami.symbol
      WHERE ami.naics_code IS NOT NULL
        AND TRIM(ami.naics_code) <> ''
        AND ami.naics_code LIKE CONCAT(%s, '%%')
        AND imr.revenue_growth_q IS NOT NULL
      ORDER BY imr.fiscalDateEnding DESC
      LIMIT %s
      """,
      (naics_code, int(limit_periods * 50)),
    )
    growth_rows = list(cur.fetchall() or [])
    return latest_rows, growth_rows, _serialize_date(period)
  finally:
    try:
      cur.close()
    except Exception:
      pass


def _fetch_generic_rows(conn, *, limit_periods: int = 8) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute("SELECT MAX(fiscalDateEnding) AS latest_period FROM industry_metrics_raw")
    latest = cur.fetchone() or {}
    period = latest.get("latest_period")
    latest_rows: List[Dict[str, Any]] = []
    if period:
      cur.execute(
        """
        SELECT *
        FROM industry_metrics_raw
        WHERE fiscalDateEnding = %s
        """,
        (period,),
      )
      latest_rows = list(cur.fetchall() or [])
    cur.execute(
      """
      SELECT fiscalDateEnding, revenue_growth_q
      FROM industry_metrics_raw
      WHERE revenue_growth_q IS NOT NULL
      ORDER BY fiscalDateEnding DESC
      LIMIT %s
      """,
      (int(limit_periods * 50),),
    )
    growth_rows = list(cur.fetchall() or [])
    return latest_rows, growth_rows, _serialize_date(period)
  finally:
    try:
      cur.close()
    except Exception:
      pass


def _build_grouped_growth_path(rows: Sequence[Dict[str, Any]], *, limit_periods: int = 8) -> List[float]:
  grouped: Dict[str, List[float]] = {}
  for row in rows:
    if not isinstance(row, dict):
      continue
    period = _serialize_date(row.get("fiscalDateEnding"))
    value = _to_float(row.get("revenue_growth_q"))
    if not period or value is None:
      continue
    grouped.setdefault(period, []).append(value)
  ordered = sorted(grouped.keys(), reverse=True)[:limit_periods]
  ordered = list(reversed(ordered))
  out: List[float] = []
  for period in ordered:
    values = grouped.get(period) or []
    if not values:
      continue
    median = _percentile(values, 0.5)
    if median is not None:
      out.append(round(median, 6))
  return out


def _payload_from_dataset(
  *,
  fallback_level: str,
  fallback_source: str,
  matched_naics_code: Optional[str],
  matched_naics_level: Optional[int],
  recency: Optional[str],
  growth_path: Sequence[float],
  raw_rows: Sequence[Dict[str, Any]],
  growth_row: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  fallback_value_gross = _to_float((growth_row or {}).get("industry_gross_margin_q"))
  fallback_value_ebitda = _to_float((growth_row or {}).get("industry_ebitda_margin_q"))
  fallback_value_opex = None
  if growth_row:
    sga = _to_float(growth_row.get("industry_sga_percent")) or 0.0
    rnd = _to_float(growth_row.get("industry_rnd_percent")) or 0.0
    if sga or rnd:
      fallback_value_opex = sga + rnd
  fallback_value_capex = _to_float((growth_row or {}).get("industry_capex_percent_revenue"))
  fallback_value_dep = _to_float((growth_row or {}).get("industry_depreciation_percent_revenue"))
  payload = _base_payload()
  payload["matched_naics_code"] = matched_naics_code
  payload["matched_naics_level"] = matched_naics_level
  payload["fallback_source"] = fallback_source
  payload["fallback_level"] = fallback_level if fallback_level in FALLBACK_LEVELS else "generic"
  payload["benchmark_recency"] = recency
  payload["revenue_growth_path"] = list(growth_path or [])
  payload["gross_margin_band"] = _band_from_values(
    _extract_metric_values(raw_rows, "gross_margin_q"),
    fallback_value_gross,
  )
  payload["ebitda_margin_band"] = _band_from_values(
    _extract_metric_values(raw_rows, "ebitda_margin_q"),
    fallback_value_ebitda,
  )
  payload["opex_intensity"] = _band_from_values(
    _extract_opex_values(raw_rows),
    fallback_value_opex,
  )
  payload["payroll_intensity"] = _empty_band()
  payload["capex_percent_revenue"] = _band_from_values(
    _extract_metric_values(raw_rows, "capex_percent_revenue"),
    fallback_value_capex,
  )
  payload["depreciation_percent_revenue"] = _band_from_values(
    _extract_metric_values(raw_rows, "depreciation_percent_revenue"),
    fallback_value_dep,
  )
  payload["working_capital"] = {
    "dso": _band_from_values(
      _extract_metric_values(raw_rows, "dso"),
      _to_float((growth_row or {}).get("industry_dso")),
    ),
    "dpo": _band_from_values(
      _extract_metric_values(raw_rows, "dpo"),
      _to_float((growth_row or {}).get("industry_dpo")),
    ),
    "inventory_days": _band_from_values(
      _extract_metric_values(raw_rows, "inventory_days"),
      _to_float((growth_row or {}).get("industry_inventory_days")),
    ),
  }
  payload["confidence_score"] = _confidence_score(
    fallback_level=payload["fallback_level"],
    sample_size=len(list(raw_rows or [])),
    matched_level=matched_naics_level,
  )
  return payload


def resolve_alpha_benchmark_payload(
  *,
  normalized_traits: Dict[str, Any],
  conn=None,
) -> Dict[str, Any]:
  close_conn = False
  if conn is None:
    conn = get_mysql_connection()
    close_conn = True

  try:
    traits = normalized_traits if isinstance(normalized_traits, dict) else {}
    naics_6 = "".join(ch for ch in str(traits.get("naics_6") or "") if ch.isdigit())[:6]
    sector = " ".join(str(traits.get("sector") or "").strip().split())

    if naics_6:
      for level in range(min(6, len(naics_6)), 1, -1):
        code = naics_6[:level]
        growth_rows = _fetch_growth_rows(conn, naics_code=code, limit=8)
        if growth_rows:
          raw_rows, recency = _fetch_latest_raw_rows_for_naics(conn, naics_code=code)
          payload = _payload_from_dataset(
            fallback_level=f"naics_{level}",
            fallback_source="industry_growth_table",
            matched_naics_code=code,
            matched_naics_level=level,
            recency=recency or _serialize_date((growth_rows[0] or {}).get("fiscalDateEnding")),
            growth_path=_build_growth_path(growth_rows),
            raw_rows=raw_rows,
            growth_row=(growth_rows[0] if growth_rows else None),
          )
          if payload.get("confidence_score", 0) > 0:
            return payload

        raw_rows, grouped_growth_rows, recency = _fetch_prefix_rows(conn, naics_code=code, limit_periods=8)
        if raw_rows:
          payload = _payload_from_dataset(
            fallback_level=f"naics_{level}",
            fallback_source="alpha_match_naics_prefix",
            matched_naics_code=code,
            matched_naics_level=level,
            recency=recency,
            growth_path=_build_grouped_growth_path(grouped_growth_rows, limit_periods=8),
            raw_rows=raw_rows,
            growth_row=(growth_rows[0] if growth_rows else None),
          )
          if payload.get("confidence_score", 0) > 0:
            return payload

    if sector:
      raw_rows, growth_rows, recency = _fetch_sector_rows(conn, sector=sector, limit_periods=8)
      if raw_rows:
        payload = _payload_from_dataset(
          fallback_level="trait_based",
          fallback_source=f"sector:{sector}",
          matched_naics_code=None,
          matched_naics_level=None,
          recency=recency,
          growth_path=_build_grouped_growth_path(growth_rows, limit_periods=8),
          raw_rows=raw_rows,
          growth_row=None,
        )
        return payload

    raw_rows, growth_rows, recency = _fetch_generic_rows(conn, limit_periods=8)
    payload = _payload_from_dataset(
      fallback_level="generic",
      fallback_source="all_industries_latest",
      matched_naics_code=None,
      matched_naics_level=None,
      recency=recency,
      growth_path=_build_grouped_growth_path(growth_rows, limit_periods=8),
      raw_rows=raw_rows,
      growth_row=None,
    )
    return payload
  finally:
    if close_conn and conn is not None:
      try:
        conn.close()
      except Exception:
        pass
