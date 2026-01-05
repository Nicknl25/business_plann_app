from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Tuple


_MIN_TITLE_MATCH_SCORE = 0.55

_STATE_TO_CODE: Dict[str, str] = {
  "alabama": "AL",
  "alaska": "AK",
  "arizona": "AZ",
  "arkansas": "AR",
  "california": "CA",
  "colorado": "CO",
  "connecticut": "CT",
  "delaware": "DE",
  "district of columbia": "DC",
  "florida": "FL",
  "georgia": "GA",
  "hawaii": "HI",
  "idaho": "ID",
  "illinois": "IL",
  "indiana": "IN",
  "iowa": "IA",
  "kansas": "KS",
  "kentucky": "KY",
  "louisiana": "LA",
  "maine": "ME",
  "maryland": "MD",
  "massachusetts": "MA",
  "michigan": "MI",
  "minnesota": "MN",
  "mississippi": "MS",
  "missouri": "MO",
  "montana": "MT",
  "nebraska": "NE",
  "nevada": "NV",
  "new hampshire": "NH",
  "new jersey": "NJ",
  "new mexico": "NM",
  "new york": "NY",
  "north carolina": "NC",
  "north dakota": "ND",
  "ohio": "OH",
  "oklahoma": "OK",
  "oregon": "OR",
  "pennsylvania": "PA",
  "rhode island": "RI",
  "south carolina": "SC",
  "south dakota": "SD",
  "tennessee": "TN",
  "texas": "TX",
  "utah": "UT",
  "vermont": "VT",
  "virginia": "VA",
  "washington": "WA",
  "west virginia": "WV",
  "wisconsin": "WI",
  "wyoming": "WY",
}


def normalize_state_code(value: Any) -> Optional[str]:
  raw = str(value or "").strip()
  if not raw:
    return None
  if len(raw) == 2 and raw.isalpha():
    return raw.upper()
  lowered = " ".join(raw.lower().split())
  return _STATE_TO_CODE.get(lowered)


def _as_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  if isinstance(value, (int, float)):
    return float(value)
  raw = str(value).strip().replace(",", "")
  if not raw:
    return None
  try:
    return float(raw)
  except Exception:
    return None


def _title_similarity(a: str, b: str) -> float:
  a_norm = " ".join(str(a or "").lower().replace("/", " ").replace("-", " ").split())
  b_norm = " ".join(str(b or "").lower().replace("/", " ").replace("-", " ").split())
  if not a_norm or not b_norm:
    return 0.0
  tokens_a = {t for t in a_norm.split() if len(t) >= 3}
  tokens_b = {t for t in b_norm.split() if len(t) >= 3}
  jacc = (len(tokens_a & tokens_b) / max(1, len(tokens_a | tokens_b))) if (tokens_a or tokens_b) else 0.0
  seq = SequenceMatcher(None, a_norm, b_norm).ratio()
  return (0.55 * seq) + (0.45 * jacc)


@dataclass(frozen=True)
class WageMatch:
  occ_title: str
  area_title: str
  naics: Optional[str]
  h_mean: Optional[float]
  match_score: float


def _fetch_wage_rows(
  *,
  conn,
  state_code: str,
  state_name: Optional[str],
  naics_6: Optional[str],
) -> List[Dict[str, Any]]:
  """
  Best-effort fetch for a state + NAICS subset. Falls back to broader queries if needed.
  """
  state_code = str(state_code or "").strip().upper()
  naics_norm = str(naics_6 or "").strip()
  cur = conn.cursor(dictionary=True)
  try:
    # Prefer state-filtered + NAICS-filtered rows when possible.
    params: List[Any] = []
    where_parts: List[str] = ["h_mean IS NOT NULL"]

    # Area filter: many datasets store "City, ST" or similar.
    if state_code:
      where_parts.append("area_title LIKE %s")
      params.append(f"%{state_code}%")
    elif state_name:
      where_parts.append("area_title LIKE %s")
      params.append(f"%{state_name}%")

    # NAICS filter: tolerate prefix matching across data variants.
    if naics_norm:
      where_parts.append(
        "(naics = %s OR LEFT(naics, 4) = LEFT(%s, 4) OR LEFT(naics, 3) = LEFT(%s, 3) OR LEFT(naics, 2) = LEFT(%s, 2))"
      )
      params.extend([naics_norm, naics_norm, naics_norm, naics_norm])

    sql = (
      "SELECT occ_title, area_title, naics, h_mean "
      "FROM oews_state_wages "
      f"WHERE {' AND '.join(where_parts)}"
    )
    cur.execute(sql, tuple(params))
    rows = cur.fetchall() or []
  except Exception:
    rows = []
  finally:
    try:
      cur.close()
    except Exception:
      pass

  # Fallbacks: broaden if nothing came back.
  if rows:
    return rows

  cur2 = conn.cursor(dictionary=True)
  try:
    params2: List[Any] = []
    where2 = ["h_mean IS NOT NULL"]
    if state_code:
      where2.append("area_title LIKE %s")
      params2.append(f"%{state_code}%")
    elif state_name:
      where2.append("area_title LIKE %s")
      params2.append(f"%{state_name}%")
    sql2 = (
      "SELECT occ_title, area_title, naics, h_mean "
      "FROM oews_state_wages "
      f"WHERE {' AND '.join(where2)}"
    )
    cur2.execute(sql2, tuple(params2))
    rows2 = cur2.fetchall() or []
  except Exception:
    rows2 = []
  finally:
    try:
      cur2.close()
    except Exception:
      pass
  if rows2:
    return rows2

  cur3 = conn.cursor(dictionary=True)
  try:
    cur3.execute(
      "SELECT occ_title, area_title, naics, h_mean FROM oews_state_wages WHERE h_mean IS NOT NULL"
    )
    rows3 = cur3.fetchall() or []
  except Exception:
    rows3 = []
  finally:
    try:
      cur3.close()
    except Exception:
      pass
  return rows3


def match_wage_for_title(
  *,
  conn,
  role_title: str,
  state_code: Optional[str],
  state_name: Optional[str],
  naics_6: Optional[str],
) -> Optional[WageMatch]:
  role = str(role_title or "").strip()
  if not role:
    return None

  sc = str(state_code or "").strip().upper()
  rows = _fetch_wage_rows(conn=conn, state_code=sc, state_name=state_name, naics_6=naics_6)
  best: Optional[Tuple[float, Dict[str, Any]]] = None
  for r in rows:
    if not isinstance(r, dict):
      continue
    occ = str(r.get("occ_title") or "").strip()
    if not occ:
      continue
    score = _title_similarity(role, occ)
    if best is None or score > best[0]:
      best = (score, r)
  if not best:
    return None
  score, r = best
  if float(score) < _MIN_TITLE_MATCH_SCORE:
    return None
  return WageMatch(
    occ_title=str(r.get("occ_title") or "").strip(),
    area_title=str(r.get("area_title") or "").strip(),
    naics=str(r.get("naics") or "").strip() or None,
    h_mean=_as_float(r.get("h_mean")),
    match_score=float(score),
  )


def _avg_hourly_wage(
  *,
  conn,
  state_code: Optional[str],
  state_name: Optional[str],
  naics_6: Optional[str],
) -> Optional[float]:
  sc = str(state_code or "").strip().upper()
  naics_norm = str(naics_6 or "").strip()
  cur = conn.cursor()
  try:
    params: List[Any] = []
    where_parts: List[str] = ["h_mean IS NOT NULL"]
    if sc:
      where_parts.append("area_title LIKE %s")
      params.append(f"%{sc}%")
    elif state_name:
      where_parts.append("area_title LIKE %s")
      params.append(f"%{state_name}%")
    if naics_norm:
      where_parts.append(
        "(naics = %s OR LEFT(naics, 4) = LEFT(%s, 4) OR LEFT(naics, 3) = LEFT(%s, 3) OR LEFT(naics, 2) = LEFT(%s, 2))"
      )
      params.extend([naics_norm, naics_norm, naics_norm, naics_norm])
    cur.execute(
      f"SELECT AVG(h_mean) AS avg_h_mean FROM oews_state_wages WHERE {' AND '.join(where_parts)}",
      tuple(params),
    )
    row = cur.fetchone()
    if not row:
      return None
    try:
      # mysql connector may return dict or tuple depending on cursor settings
      if isinstance(row, dict):
        return _as_float(row.get("avg_h_mean"))
      return _as_float(row[0] if isinstance(row, (list, tuple)) and row else None)
    except Exception:
      return None
  except Exception:
    return None
  finally:
    try:
      cur.close()
    except Exception:
      pass


def enrich_headcount_roles(
  *,
  conn,
  roles: Iterable[Dict[str, Any]],
  state_code: Optional[str],
  state_name: Optional[str],
  naics_6: Optional[str],
) -> Tuple[List[Dict[str, Any]], float]:
  """
  Attach dataset-derived hourly rates and compute annual payroll math per role.

  Role input supports:
    - role_title (required)
    - employee_count (default 1)
    - hours_per_week (default 40)
    - weeks_per_year (default 52)
    - hourly_rate_override (optional)
  """
  out: List[Dict[str, Any]] = []
  total = 0.0
  for raw in list(roles or []):
    if not isinstance(raw, dict):
      continue
    role_title = str(raw.get("role_title") or raw.get("title") or "").strip()
    if not role_title:
      continue

    try:
      employee_count = int(raw.get("employee_count") or raw.get("count") or 1)
    except Exception:
      employee_count = 1
    employee_count = max(0, employee_count)

    hpw = _as_float(raw.get("hours_per_week"))
    wpy = _as_float(raw.get("weeks_per_year"))
    hours_per_week = float(hpw) if hpw is not None else 40.0
    weeks_per_year = float(wpy) if wpy is not None else 52.0
    hours_per_week = max(0.0, hours_per_week)
    weeks_per_year = max(0.0, weeks_per_year)

    override = _as_float(raw.get("hourly_rate_override"))
    fallback_rate = _as_float(raw.get("fallback_hourly_rate"))
    fallback_basis = str(raw.get("fallback_hourly_rate_basis") or "").strip() or None
    if override is not None and override <= 0 and employee_count > 0:
      override = None
    if fallback_rate is not None and fallback_rate <= 0:
      fallback_rate = None
    hourly_rate: Optional[float] = override
    source: str = "override" if override is not None else "dataset"
    hourly_rate_basis: Optional[str] = None

    match: Optional[WageMatch] = None
    if override is None:
      match = match_wage_for_title(
        conn=conn,
        role_title=role_title,
        state_code=state_code,
        state_name=state_name,
        naics_6=naics_6,
      )
      hourly_rate = match.h_mean if match and match.h_mean is not None else None
      if hourly_rate is not None and match:
        hourly_rate_basis = f"Matched wage dataset: {match.occ_title} ({match.area_title})"
      if hourly_rate is None and fallback_rate is not None:
        hourly_rate = fallback_rate
        source = "gpt_fallback"
        hourly_rate_basis = fallback_basis or "Assumption (edit if needed)."

      if hourly_rate is None:
        # Deterministic dataset fallback: use average wage as a conservative placeholder.
        avg_naics = _avg_hourly_wage(
          conn=conn,
          state_code=state_code,
          state_name=state_name,
          naics_6=naics_6,
        )
        if avg_naics is not None:
          hourly_rate = avg_naics
          source = "dataset_average_naics"
          hourly_rate_basis = "No strong occupation match; using state/NAICS average hourly wage (edit if needed)."
        else:
          avg_state = _avg_hourly_wage(
            conn=conn,
            state_code=state_code,
            state_name=state_name,
            naics_6=None,
          )
          if avg_state is not None:
            hourly_rate = avg_state
            source = "dataset_average_state"
            hourly_rate_basis = "No strong occupation match; using state average hourly wage (edit if needed)."

      if hourly_rate is None and employee_count > 0:
        # Last-resort to preserve invariant: never leave missing pay.
        hourly_rate = 25.0
        source = "default_assumption"
        hourly_rate_basis = "No wage data match available; using a conservative placeholder (edit if needed)."

    annual_hours = float(hours_per_week) * float(weeks_per_year)
    annual_per_employee = (float(hourly_rate) * annual_hours) if hourly_rate is not None else None
    annual_total = (annual_per_employee * float(employee_count)) if annual_per_employee is not None else None
    if annual_total is not None:
      total += float(annual_total)

    enriched = dict(raw)
    enriched.update(
      {
        "role_title": role_title,
        "employee_count": employee_count,
        "hours_per_week": hours_per_week,
        "weeks_per_year": weeks_per_year,
        "hourly_rate": hourly_rate,
        "hourly_rate_source": source,
        "hourly_rate_basis": hourly_rate_basis,
        "fallback_hourly_rate": fallback_rate,
        "fallback_hourly_rate_basis": fallback_basis,
        "annual_hours": annual_hours,
        "annual_wage_per_employee": annual_per_employee,
        "annual_total_wage": annual_total,
        "naics_context": naics_6,
        "state_context": state_code or state_name,
      }
    )
    if match:
      enriched.update(
        {
          "matched_occ_title": match.occ_title,
          "area_title": match.area_title,
          "naics_matched": match.naics,
          "h_mean": match.h_mean,
          "match_score": match.match_score,
        }
      )
    out.append(enriched)
  return out, float(total)
