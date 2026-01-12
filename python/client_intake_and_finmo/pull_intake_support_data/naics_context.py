from __future__ import annotations

from typing import Dict, List


_BUSINESS_TYPES_CACHE: List[str] | None = None
_BUSINESS_TYPE_TO_NAICS_6_CACHE: Dict[str, str] | None = None


def _load_business_types(conn) -> List[str]:
  global _BUSINESS_TYPES_CACHE
  if _BUSINESS_TYPES_CACHE is not None:
    return list(_BUSINESS_TYPES_CACHE)

  cur = conn.cursor()
  try:
    cur.execute("SELECT business_types FROM naics_master WHERE business_types IS NOT NULL")
    rows = cur.fetchall() or []
  finally:
    try:
      cur.close()
    except Exception:
      pass

  values: List[str] = []
  for row in rows:
    if isinstance(row, dict):
      bt = row.get("business_types")
    else:
      bt = row[0] if row else None
    if bt is None:
      continue
    for part in str(bt).split(","):
      token = str(part).strip()
      if token:
        values.append(token)
  _BUSINESS_TYPES_CACHE = sorted(set(values), key=lambda x: x.lower())
  return list(_BUSINESS_TYPES_CACHE)


def _load_business_type_to_naics(conn) -> Dict[str, str]:
  global _BUSINESS_TYPE_TO_NAICS_6_CACHE
  if _BUSINESS_TYPE_TO_NAICS_6_CACHE is not None:
    return dict(_BUSINESS_TYPE_TO_NAICS_6_CACHE)

  cur = conn.cursor()
  try:
    cur.execute(
      "SELECT business_types, naics_6 FROM naics_master WHERE business_types IS NOT NULL AND naics_6 IS NOT NULL"
    )
    rows = cur.fetchall() or []
  finally:
    try:
      cur.close()
    except Exception:
      pass

  mapping: Dict[str, str] = {}
  for row in rows:
    if isinstance(row, dict):
      business_types_raw = row.get("business_types")
      naics_6 = row.get("naics_6")
    else:
      try:
        business_types_raw, naics_6 = row
      except Exception:
        continue
    if not business_types_raw or not naics_6:
      continue
    naics_6_str = str(naics_6).strip()
    if not naics_6_str:
      continue
    for part in str(business_types_raw).split(","):
      token = str(part).strip()
      if token and token not in mapping:
        mapping[token] = naics_6_str

  _BUSINESS_TYPE_TO_NAICS_6_CACHE = mapping
  return dict(mapping)


def build_business_type_candidates(*, conn, messages: List[Dict[str, str]], limit: int = 80) -> List[str]:
  """
  Build a small, relevant business_type candidate list by scoring known values against
  recent user messages. This keeps context compact while avoiding a massive list.
  """
  try:
    from difflib import SequenceMatcher

    all_business_types = _load_business_types(conn)
    if not all_business_types:
      return []

    user_texts: List[str] = []
    for msg in messages:
      if str(msg.get("role") or "") != "user":
        continue
      content = str(msg.get("content") or "").strip()
      if not content:
        continue
      user_texts.append(content)
      if len(user_texts) >= 6:
        break

    base = " ".join(user_texts).strip().lower()
    base = " ".join(base.split())
    tokens = {t for t in base.replace("/", " ").replace("-", " ").split() if len(t) >= 3}

    scored = []
    for bt in all_business_types:
      btl = bt.lower()
      token_score = sum(1 for t in tokens if t in btl) if tokens else 0
      ratio = SequenceMatcher(None, base, btl).ratio() if base else 0.0
      scored.append((token_score, ratio, bt))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [bt for _, _, bt in scored[:limit]] or all_business_types[:limit]
  except Exception:
    return []


def build_naics_context(*, conn, messages: List[Dict[str, str]], limit: int = 80) -> Dict[str, Dict[str, str] | List[str]]:
  candidates = build_business_type_candidates(conn=conn, messages=messages, limit=limit)
  mapping = _load_business_type_to_naics(conn)
  filtered_mapping = {bt: mapping.get(bt) for bt in candidates if mapping.get(bt)}
  return {
    "business_type_candidates": candidates,
    "business_type_to_naics_6": filtered_mapping,
  }
