from __future__ import annotations

import time
from typing import Any, Dict, List


def slugify_lob_key(name: str) -> str:
  raw = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(name or ""))
  raw = "_".join([p for p in raw.split("_") if p])
  if not raw:
    return "lob"
  if raw[0].isdigit():
    raw = f"lob_{raw}"
  return raw[:48]


def extract_lobs_from_text(text: str) -> List[Dict[str, str]]:
  raw = str(text or "")
  lowered = raw.lower()
  if "line of business" not in lowered and "lines of business" not in lowered and "lob" not in lowered:
    return []

  import re

  parts = re.split(r"\(\s*\d+\s*\)\s*", raw)
  parts = [p.strip(" .;\n\r\t") for p in parts if p and p.strip()]
  if len(parts) <= 1:
    return []

  out: List[Dict[str, str]] = []
  for p in parts[1:6]:
    name = re.split(r"[.;\n\r]", p, maxsplit=1)[0].strip()
    if not name:
      continue
    key = slugify_lob_key(name)
    existing = {x["lob_key"] for x in out if isinstance(x, dict) and "lob_key" in x}
    if key in existing:
      suffix = 2
      while f"{key}_{suffix}" in existing:
        suffix += 1
      key = f"{key}_{suffix}"
    out.append({"lob_key": key, "lob_name": name})
  return out


def ensure_lob_model_card(card: Dict[str, Any], lobs: List[Dict[str, str]]) -> Dict[str, Any]:
  if not lobs:
    return card
  now_ms = int(time.time() * 1000)
  existing_lobs = card.get("lobs") if isinstance(card, dict) else None
  if isinstance(existing_lobs, list) and existing_lobs:
    has_company_total = any(
      isinstance(l, dict) and str(l.get("lob_key") or "").strip() == "company_total" for l in existing_lobs
    )
    if has_company_total:
      return card
    return {
      **card,
      "lobs": [
        {"lob_key": "company_total", "lob_name": None, "drivers": {}, "derived": {}},
        *existing_lobs,
      ],
    }

  # Back-compat: preserve legacy {drivers, derived} root shape by mapping it into company_total.
  try:
    drivers_root = card.get("drivers") if isinstance(card.get("drivers"), dict) else {}
    derived_root = card.get("derived") if isinstance(card.get("derived"), dict) else {}
  except Exception:
    drivers_root = {}
    derived_root = {}

  deduped: List[Dict[str, str]] = []
  seen = set()
  for entry in [{"lob_key": "company_total", "lob_name": ""}, *list(lobs or [])]:
    key = str(entry.get("lob_key") or "").strip() or "company_total"
    if key in seen:
      continue
    seen.add(key)
    deduped.append(entry)

  base = dict(card or {}) if isinstance(card, dict) else {}
  base.pop("drivers", None)
  base.pop("derived", None)
  base_out = {
    **base,
    "version": int(base.get("version") or 1),
    "updated_at_ms": now_ms,
    "lobs": [
      {
        "lob_key": str(l.get("lob_key") or "company_total").strip() or "company_total",
        "lob_name": str(l.get("lob_name") or "").strip() or None,
        "drivers": (dict(drivers_root) if str(l.get("lob_key") or "").strip() == "company_total" else {}),
        "derived": (dict(derived_root) if str(l.get("lob_key") or "").strip() == "company_total" else {}),
      }
      for l in deduped
    ],
  }
  return base_out
