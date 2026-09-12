"""THE CLIENT'S TODAY, ONE DEFINITION (Nick 2026-09-12).

"A client finishing an intake after 8pm should not get tomorrow's date on
their plan."

The handler computed the intake's "today" as ``datetime.utcnow().date()``
and every post-intake stage check did the same, while MySQL stamps the
draft's created_at in the DB server's local zone and the writing phase
dated the plan with the app server's local ``date.today()``. Three clocks,
none of them the client's. For a Portland business at 21:00 the intake was
already dated tomorrow, the stage inference ("early-stage" is <= 365 days
from the start date) could flip a day early, milestone months could round
differently, and - the one that costs a real month - the plan's projection
window is the first of the month AFTER the intake date, so a UTC flip on
the last evening of a month moved the client's Q1 by a whole quarter of a
year's planning.

RESOLUTION ORDER, strongest first:
  1. ``client_today`` in the request - the browser's own local date, sent
     with every intake message (YYYY-MM-DD). The client's clock is the
     client's clock.
  2. The business address state -> its IANA zone -> today there. Persisted
     with the draft, so post-intake and the writing phase can recover the
     same day without a new column.
  3. The app server's LOCAL date. Never UTC: a server in London is wrong for
     every US client after 19:00, a server on PythonAnywhere (UTC) is wrong
     for every US client after 20:00 Eastern.

Post-intake code has only the flat draft columns (address_state among
them), which is why (2) is what ``today_for`` reads: the run happens on the
same client-day as the intake it follows.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any, Dict, Optional

try:
  from zoneinfo import ZoneInfo  # type: ignore
except Exception:  # pragma: no cover - python < 3.9
  ZoneInfo = None  # type: ignore

CLIENT_TODAY_KEYS = ("client_today", "clientToday", "client_local_date")

#: US states and DC to the IANA zone that covers the bulk of their
#: population. A handful of states straddle two zones (TX, FL, KY, TN, ID,
#: OR, NE, KS, ND, SD, MI, IN); the majority zone is used. This only matters
#: within an hour of midnight, and the browser-sent date wins over it.
US_STATE_TZ: Dict[str, str] = {
  "AL": "America/Chicago", "AK": "America/Anchorage", "AZ": "America/Phoenix",
  "AR": "America/Chicago", "CA": "America/Los_Angeles", "CO": "America/Denver",
  "CT": "America/New_York", "DE": "America/New_York", "DC": "America/New_York",
  "FL": "America/New_York", "GA": "America/New_York", "HI": "Pacific/Honolulu",
  "ID": "America/Boise", "IL": "America/Chicago", "IN": "America/Indiana/Indianapolis",
  "IA": "America/Chicago", "KS": "America/Chicago", "KY": "America/New_York",
  "LA": "America/Chicago", "ME": "America/New_York", "MD": "America/New_York",
  "MA": "America/New_York", "MI": "America/Detroit", "MN": "America/Chicago",
  "MS": "America/Chicago", "MO": "America/Chicago", "MT": "America/Denver",
  "NE": "America/Chicago", "NV": "America/Los_Angeles", "NH": "America/New_York",
  "NJ": "America/New_York", "NM": "America/Denver", "NY": "America/New_York",
  "NC": "America/New_York", "ND": "America/Chicago", "OH": "America/New_York",
  "OK": "America/Chicago", "OR": "America/Los_Angeles", "PA": "America/New_York",
  "RI": "America/New_York", "SC": "America/New_York", "SD": "America/Chicago",
  "TN": "America/Chicago", "TX": "America/Chicago", "UT": "America/Denver",
  "VT": "America/New_York", "VA": "America/New_York", "WA": "America/Los_Angeles",
  "WV": "America/New_York", "WI": "America/Chicago", "WY": "America/Denver",
}

_STATE_NAMES: Dict[str, str] = {
  "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
  "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
  "district of columbia": "DC", "florida": "FL", "georgia": "GA", "hawaii": "HI",
  "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
  "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
  "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
  "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
  "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
  "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
  "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
  "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
  "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
  "wisconsin": "WI", "wyoming": "WY",
}


def parse_iso_date(value: Any) -> Optional[date]:
  """YYYY-MM-DD only. Anything else is not a date the client sent."""
  text = str(value or "").strip()
  if len(text) < 10:
    return None
  try:
    return datetime.strptime(text[:10], "%Y-%m-%d").date()
  except ValueError:
    return None


def state_zone(address_state: Any) -> Optional[str]:
  raw = str(address_state or "").strip()
  if not raw:
    return None
  key = raw.upper() if len(raw) == 2 else _STATE_NAMES.get(raw.lower(), "")
  return US_STATE_TZ.get(key) if key else None


def today_in_state(address_state: Any, *, now: Optional[datetime] = None) -> Optional[date]:
  zone = state_zone(address_state)
  if not zone or ZoneInfo is None:
    return None
  try:
    tz = ZoneInfo(zone)
  except Exception:
    return None
  moment = now.astimezone(tz) if (now is not None and now.tzinfo is not None) else datetime.now(tz)
  return moment.date()


def server_local_today() -> date:
  """The app server's LOCAL date - the last resort. Never utcnow()."""
  return datetime.now().date()


def client_date_of(stamp: Any, address_state: Any) -> Optional[date]:
  """The client's calendar date for a stored timestamp. MySQL stamps
  created_at with NOW() in the DB server's own zone (session tz = SYSTEM,
  Eastern here, UTC on PythonAnywhere) and hands it back NAIVE, so the
  writing phase read `created_at.date()` and dated the plan's projection
  window by whatever clock the server happened to keep. Attach the server's
  local zone, convert to the business's state zone, take the date. A stamp
  that is already aware converts directly."""
  if stamp is None:
    return None
  if isinstance(stamp, date) and not isinstance(stamp, datetime):
    return stamp
  dt: Optional[datetime] = None
  if isinstance(stamp, datetime):
    dt = stamp
  else:
    text = str(stamp).strip()
    try:
      dt = datetime.fromisoformat(text[:26]) if len(text) > 10 else None
    except ValueError:
      dt = None
    if dt is None:
      return parse_iso_date(text)
  if dt.tzinfo is None:
    dt = dt.astimezone()  # the server's local zone, which is what NOW() used
  zone = state_zone(address_state)
  if zone and ZoneInfo is not None:
    try:
      return dt.astimezone(ZoneInfo(zone)).date()
    except Exception:
      pass
  return dt.astimezone().date()


def resolve_client_today(
  payload: Optional[Dict[str, Any]],
  business_facts: Optional[Dict[str, Any]],
  *,
  now: Optional[datetime] = None,
) -> date:
  """The client's today for THIS request: their browser's date if it sent
  one, else today in their business's state, else the server's local day."""
  p = payload if isinstance(payload, dict) else {}
  for key in CLIENT_TODAY_KEYS:
    d = parse_iso_date(p.get(key))
    if d is not None:
      return d
  # a test seam, kept for scripted runs that drive the handler without a
  # request body of their own; a browser never sets it
  d = parse_iso_date(os.environ.get("INTAKE_CURRENT_DATE"))
  if d is not None:
    return d
  facts = business_facts if isinstance(business_facts, dict) else {}
  d = today_in_state(facts.get("address_state"), now=now)
  if d is not None:
    return d
  return (now.astimezone().date() if (now is not None and now.tzinfo is not None)
          else server_local_today())


def today_for(business_facts: Optional[Dict[str, Any]], *, now: Optional[datetime] = None) -> date:
  """The client's today for post-intake and writing-phase code, which holds
  only the draft's flat facts: a persisted intake date when the draft
  carries one, else today in the business's state, else the server's local
  day. Never utcnow()."""
  facts = business_facts if isinstance(business_facts, dict) else {}
  for key in ("current_date", "intake_date", "client_today"):
    d = parse_iso_date(facts.get(key))
    if d is not None:
      return d
  d = today_in_state(facts.get("address_state"), now=now)
  if d is not None:
    return d
  return (now.astimezone().date() if (now is not None and now.tzinfo is not None)
          else server_local_today())
