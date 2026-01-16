from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests


_STATE_ABBREV = {
  "alabama": "AL",
  "alaska": "AK",
  "arizona": "AZ",
  "arkansas": "AR",
  "california": "CA",
  "colorado": "CO",
  "connecticut": "CT",
  "delaware": "DE",
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
  "district of columbia": "DC",
}

ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def _load_root_env() -> None:
  try:
    from dotenv import load_dotenv  # type: ignore
  except Exception:
    return
  try:
    load_dotenv(str(ROOT_ENV_PATH))
  except Exception:
    pass


def _require_openai_key() -> str:
  _load_root_env()
  key = (os.getenv("OPENAI_API_KEY") or "").strip()
  if not key:
    raise RuntimeError("OPENAI_API_KEY is not configured.")
  return key


def _openai_model() -> str:
  _load_root_env()
  return (os.getenv("OPENAI_MODEL") or "gpt-5.1").strip() or "gpt-5.1"


def _openai_timeout_seconds() -> int:
  _load_root_env()
  raw = (os.getenv("OPENAI_HTTP_TIMEOUT_SECONDS") or "").strip()
  if raw:
    try:
      return max(30, int(raw))
    except Exception:
      return 180
  return 180


def _post_openai(*, url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> requests.Response:
  timeout = _openai_timeout_seconds()
  last_exc: Optional[Exception] = None
  for attempt in range(3):
    try:
      return requests.post(url, headers=headers, json=payload, timeout=timeout)
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as exc:
      last_exc = exc
      if attempt >= 2:
        raise
      time.sleep(0.75 * (2**attempt))
    except requests.exceptions.ConnectionError as exc:
      last_exc = exc
      if attempt >= 2:
        raise
      time.sleep(0.75 * (2**attempt))
  if last_exc:
    raise last_exc
  raise RuntimeError("OpenAI request failed unexpectedly.")


def _parse_responses_text(data: Dict[str, Any]) -> str:
  output = data.get("output") or []
  chunks: list[str] = []
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_text" and part.get("text"):
        chunks.append(str(part["text"]))
  if not chunks:
    raise RuntimeError("OpenAI response contained no output_text.")
  return "\n".join(chunks).strip()


def _normalize_state_abbrev(state_raw: Any, address_raw: Any) -> Optional[str]:
  if state_raw:
    state_text = str(state_raw).strip()
    if len(state_text) == 2 and state_text.isalpha():
      return state_text.upper()
    lowered = state_text.lower()
    if lowered in _STATE_ABBREV:
      return _STATE_ABBREV[lowered]

  if address_raw:
    addr = str(address_raw).strip()
    parts = [p.strip() for p in addr.replace(",", " ").split()]
    for token in parts:
      if len(token) == 2 and token.isalpha():
        return token.upper()
      lowered = token.lower()
      if lowered in _STATE_ABBREV:
        return _STATE_ABBREV[lowered]
  return None


def _normalize_title(text: str) -> str:
  cleaned = "".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in text)
  return " ".join(cleaned.split())


def _match_occ_title_with_gpt(
  *,
  role_title: str,
  notes: str,
  business_type: str,
  candidate_titles: List[str],
) -> Optional[str]:
  if not role_title or not candidate_titles:
    return None

  api_key = _require_openai_key()
  model = _openai_model()

  system = (
    "You map a role title to the single best-matching occupation title from a provided list.\n"
    "Return one exact string from the list or an empty string if none fit.\n"
    "Do not invent new titles."
  )

  titles_blob = "\n".join(f"- {t}" for t in candidate_titles)
  user = (
    "Role title:\n"
    f"{role_title}\n\n"
    "Business type:\n"
    f"{business_type}\n\n"
    "Role notes (why it was proposed):\n"
    f"{notes}\n\n"
    "Candidate OEWS occupation titles:\n"
    f"{titles_blob}\n"
  )

  payload = {
    "model": model,
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": user},
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": "oews_occ_title_match",
        "schema": {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "occ_title": {"type": "string"},
          },
          "required": ["occ_title"],
        },
        "strict": True,
      }
    },
  }

  resp = _post_openai(
    url="https://api.openai.com/v1/responses",
    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    payload=payload,
  )
  if resp.status_code >= 400:
    raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text[:300]}")

  data = resp.json()
  output = data.get("output") or []
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_json" and isinstance(part.get("json"), dict):
        occ = str(part["json"].get("occ_title") or "").strip()
        return occ or None

  raw = _parse_responses_text(data)
  try:
    parsed = json.loads(raw)
  except Exception:
    return None
  occ = str(parsed.get("occ_title") or "").strip()
  return occ or None


def _select_wage(row: Dict[str, Any], prefer_pct10: bool) -> Tuple[Optional[float], Optional[str]]:
  pct10 = row.get("a_pct10")
  median = row.get("a_median")

  def clean(value: Any) -> Optional[float]:
    try:
      num = float(value)
    except Exception:
      return None
    if num <= 0:
      return None
    return num

  pct10_val = clean(pct10)
  median_val = clean(median)

  if prefer_pct10:
    if pct10_val is not None:
      return pct10_val, "oews_pct10"
    if median_val is not None:
      return median_val, "oews_median"
  else:
    if median_val is not None:
      return median_val, "oews_median"
    if pct10_val is not None:
      return pct10_val, "oews_pct10"
  return None, None


def _fetch_oews_rows_exact(conn, *, state_abbrev: str, naics_6: str) -> List[Dict[str, Any]]:
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      """
      SELECT occ_title, a_pct10, a_median
      FROM oews_state_wages
      WHERE prim_state = %s
        AND naics = %s
        AND occ_title IS NOT NULL
      """,
      (state_abbrev, naics_6),
    )
    rows = cur.fetchall() or []
  finally:
    try:
      cur.close()
    except Exception:
      pass
  return rows


def _fetch_oews_rows_prefix(conn, *, state_abbrev: str, naics_prefix: str) -> List[Dict[str, Any]]:
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      """
      SELECT occ_title, a_pct10, a_median
      FROM oews_state_wages
      WHERE prim_state = %s
        AND naics LIKE %s
        AND occ_title IS NOT NULL
      """,
      (state_abbrev, f"{naics_prefix}%"),
    )
    rows = cur.fetchall() or []
  finally:
    try:
      cur.close()
    except Exception:
      pass
  return rows


def _get_naics_from_business_type(conn, business_type: Any) -> Optional[str]:
  if not business_type:
    return None
  naics = None
  try:
    from intake_business_types import get_naics_from_business_type  # type: ignore

    naics = get_naics_from_business_type(conn, str(business_type).strip())
  except Exception:
    try:
      from client_intake_and_finmo.intake_business_types import get_naics_from_business_type  # type: ignore

      naics = get_naics_from_business_type(conn, str(business_type).strip())
    except Exception:
      return None
  if naics:
    return str(naics).strip()
  return None


def apply_oews_wages(
  conn,
  *,
  roles: List[Dict[str, Any]],
  business_type: Any,
  business_stage: Any,
  address_state: Any = None,
  address: Any = None,
) -> List[Dict[str, Any]]:
  prefer_pct10 = False

  naics_6 = _get_naics_from_business_type(conn, business_type)
  state_abbrev = _normalize_state_abbrev(address_state, address)

  naics_prefix = str(naics_6 or "")[:4] if naics_6 else ""

  us_rows: List[Dict[str, Any]] = []
  if naics_prefix:
    us_rows = _fetch_oews_rows_prefix(conn, state_abbrev="US", naics_prefix=naics_prefix)

  updated: List[Dict[str, Any]] = []
  for role in roles or []:
    role_title = str(role.get("role_title") or "").strip()
    notes = str(role.get("notes") or "").strip()
    gpt_wage = role.get("annual_wage")
    try:
      gpt_wage_val = float(gpt_wage) if gpt_wage is not None else None
    except Exception:
      gpt_wage_val = None
    wage_source = str(role.get("wage_source") or "").strip() or "gpt_estimate"

    wage_val = None
    rows_to_use = us_rows
    if role_title and rows_to_use:
      candidate_titles: List[str] = []
      seen: set[str] = set()
      for row in rows_to_use:
        occ_title = str(row.get("occ_title") or "").strip()
        if not occ_title:
          continue
        if occ_title.lower().strip() == "all occupations":
          continue
        if occ_title in seen:
          continue
        seen.add(occ_title)
        candidate_titles.append(occ_title)

      try:
        matched_title = _match_occ_title_with_gpt(
          role_title=role_title,
          notes=notes,
          business_type=str(business_type or ""),
          candidate_titles=candidate_titles,
        )
      except Exception:
        matched_title = None

      if matched_title:
        matched_row = None
        for row in rows_to_use:
          if str(row.get("occ_title") or "").strip() == matched_title:
            matched_row = row
            break
        if matched_row:
          picked, source = _select_wage(matched_row, prefer_pct10)
          if picked is not None:
            wage_val = picked
            wage_source = source or wage_source

    if wage_val is None and gpt_wage_val is not None:
      wage_val = gpt_wage_val

    updated.append(
      {
        "role_title": role_title,
        "annual_wage": wage_val,
        "wage_source": wage_source or "gpt_estimate",
        "notes": notes,
      }
    )

  return updated


def apply_oews_wages_to_people(
  conn,
  *,
  people: List[Dict[str, Any]],
  business_type: Any,
  business_stage: Any,
  address_state: Any = None,
  address: Any = None,
) -> List[Dict[str, Any]]:
  if not people:
    return []

  roles: List[Dict[str, Any]] = []
  for person in people:
    if not isinstance(person, dict):
      continue
    role_title = str(person.get("role_title") or "").strip()
    notes = str(
      person.get("primary_responsibilities")
      or person.get("paragraph")
      or person.get("relevant_background")
      or ""
    ).strip()
    roles.append(
      {
        "role_title": role_title,
        "notes": notes,
        "annual_wage": person.get("annual_wage"),
        "wage_source": person.get("wage_source"),
      }
    )

  enriched_roles = apply_oews_wages(
    conn,
    roles=roles,
    business_type=business_type,
    business_stage=business_stage,
    address_state=address_state,
    address=address,
  )

  updated: List[Dict[str, Any]] = []
  for idx, person in enumerate(people):
    if not isinstance(person, dict):
      continue
    enriched = enriched_roles[idx] if idx < len(enriched_roles) else {}
    wage = enriched.get("annual_wage")
    wage_source = str(enriched.get("wage_source") or "").strip() or "gpt_estimate"
    updated_person = dict(person)
    updated_person["annual_wage"] = wage
    updated_person["wage_source"] = wage_source
    updated.append(updated_person)

  return updated


def format_people_wage_summary(people: List[Dict[str, Any]]) -> str:
  if not people:
    return ""
  lines = ["Estimated year-1 wages for key people:"]
  for person in people:
    if not isinstance(person, dict):
      continue
    name = str(person.get("full_name") or "").strip()
    title = str(person.get("role_title") or "").strip()
    if not name and not title:
      continue
    label = name or title
    if name and title:
      label = f"{name} ({title})"
    wage = person.get("annual_wage")
    wage_str = "TBD"
    try:
      if wage is not None:
        wage_str = f"${float(wage):,.0f}/year"
    except Exception:
      wage_str = "TBD"
    lines.append(f"- {label}: {wage_str}")
  return "\n".join(lines).strip()


def format_roles_summary(roles: List[Dict[str, Any]]) -> str:
  if not roles:
    return ""
  lines = ["Suggested year-1 roles and estimated annual wages:"]
  for role in roles:
    title = str(role.get("role_title") or "").strip()
    if not title:
      continue
    wage = role.get("annual_wage")
    wage_str = "TBD"
    try:
      if wage is not None:
        wage_str = f"${float(wage):,.0f}/year"
    except Exception:
      wage_str = "TBD"
    notes = str(role.get("notes") or "").strip()
    line = f"- {title}: {wage_str}"
    if notes:
      line = f"{line} — {notes}"
    lines.append(line)
  return "\n".join(lines).strip()
