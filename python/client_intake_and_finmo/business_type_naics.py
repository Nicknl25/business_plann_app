from __future__ import annotations

from typing import Any


def _normalize_business_type(value: Any) -> str:
  cleaned = str(value or "").strip()
  for ch in ("â€“", "â€”", "â€‘", "âˆ’"):
    cleaned = cleaned.replace(ch, "-")
  cleaned = " ".join(cleaned.split())
  return cleaned.lower()


def get_naics_from_business_type(conn, business_type: Any) -> str:
  """
  Resolve client-selected business_type -> 6-digit NAICS.

  This is intentionally DB-only and free of workbook behavior.
  """
  bt_clean = _normalize_business_type(business_type)
  if not bt_clean:
    raise ValueError("business_type is required")

  cur = conn.cursor(dictionary=True)
  try:
    cur.execute("SELECT business_types, naics_6 FROM naics_master")
    rows = cur.fetchall() or []
  finally:
    try:
      cur.close()
    except Exception:
      pass

  for row in rows:
    bt_field = row.get("business_types") or ""
    tokens = [tok.strip() for tok in str(bt_field).split(",") if tok.strip()]
    for tok in tokens:
      if _normalize_business_type(tok) == bt_clean:
        return str(row.get("naics_6") or "").strip()

  raise ValueError(f"No NAICS mapping found for business_type: {business_type}")
