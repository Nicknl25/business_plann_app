from __future__ import annotations

from typing import Dict, List


def build_business_type_candidates(*, conn, messages: List[Dict[str, str]]) -> List[str]:
  """
  Build a small, relevant business_type candidate list by scoring known values against
  early user messages. This keeps finalization deterministic while avoiding a huge list.
  """
  try:
    from difflib import SequenceMatcher

    cur = conn.cursor()
    try:
      cur.execute("SELECT business_types FROM naics_master WHERE business_types IS NOT NULL")
      rows = cur.fetchall() or []
      values: List[str] = []
      for (bt,) in rows:
        if bt is None:
          continue
        for part in str(bt).split(","):
          part_str = str(part).strip()
          if part_str:
            values.append(part_str)
      all_business_types = sorted(set(values), key=lambda x: x.lower())
    finally:
      try:
        cur.close()
      except Exception:
        pass

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
    return [bt for _, _, bt in scored[:80]] or (all_business_types[:80] if all_business_types else [])
  except Exception:
    return []

