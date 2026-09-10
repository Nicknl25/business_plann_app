"""OWNER PAY, ONE DEFINITION (Nick, payroll directive item 7 / R4, 2026-09-09).

"Add back EVERY owner's pay. SDE is what a single owner-operator would take
out; mirroring whichever row is first is arbitrary and order-dependent,
which is worse than either answer. Nothing touching valuation should depend
on row order."

This module is the one home for two things every owner-pay reader shares:

  OWNER_TITLE_RE   the owner-title test. It is THE regex the recalc's
                   owner-row pass uses (api_handlers.intake_consult aliases
                   it as _OWNER_TITLE_RE) - the workbook builder and the
                   writing phase cannot import the API handler, so the
                   pattern lives here and the handler imports it. One
                   pattern, never a second copy.
  owner_pay_total  the SUM of every owner-titled person's annual pay, read
                   from the people rows, ORDER-INDEPENDENT by construction
                   (a sum). A roster with no owner-titled row carrying a
                   numeric wage falls back to the legacy financials mirror
                   (drafts captured before the people door existed carried
                   owner pay only there) - reported as such, never silently.

Owner pay is stored MONTHLY on financials.owner_compensation (the derived
mirror) and ANNUALLY on the people rows (annual_wage). The mirror is now
defined as owner_pay_total / 12 - the same set, the same sum - so the
post-intake readers of the mirror and the valuation readers of the rows
cannot disagree about which owners count.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

OWNER_TITLE_RE = re.compile(r"owner|principal|founder|managing|partner", re.I)

SOURCE_PEOPLE_ROWS = "people_rows"
SOURCE_LEGACY_MIRROR = "legacy_mirror"


def _num(value: Any) -> Optional[float]:
  try:
    x = float(value)
  except (TypeError, ValueError):
    return None
  return x if math.isfinite(x) else None


def owner_rows(people_json: Any) -> List[Dict[str, Any]]:
  """Every people row whose title passes the owner test, in stored order.
  Callers that need a figure must SUM over this list, never index it."""
  ppl = people_json if isinstance(people_json, dict) else {}
  rows = ppl.get("people")
  if not isinstance(rows, list):
    return []
  return [
    p for p in rows
    if isinstance(p, dict) and OWNER_TITLE_RE.search(str(p.get("role_title") or ""))
  ]


def owner_pay_total(people_json: Any, financials_json: Any = None) -> Dict[str, Any]:
  """The order-independent owner-pay figure.

  Returns {annual_total, owners, source}:
    annual_total  sum of annual_wage over every owner-titled row that carries
                  a numeric, non-negative wage (float), or None when nothing
                  supplies one;
    owners        how many owner-titled rows contributed;
    source        'people_rows', 'legacy_mirror' (no owner row supplied a
                  wage; financials.owner_compensation x 12 used instead), or
                  None when neither exists.
  """
  rows = owner_rows(people_json)
  wages = []
  for p in rows:
    w = _num(p.get("annual_wage"))
    if w is not None and w >= 0:
      wages.append(w)
  if wages:
    return {
      "annual_total": float(sum(wages)),
      "owners": len(wages),
      "source": SOURCE_PEOPLE_ROWS,
    }
  fin = financials_json if isinstance(financials_json, dict) else {}
  monthly = _num(fin.get("owner_compensation"))
  if monthly is not None and monthly >= 0:
    return {
      "annual_total": round(monthly * 12.0, 2),
      "owners": 1 if monthly > 0 else 0,
      "source": SOURCE_LEGACY_MIRROR,
    }
  return {"annual_total": None, "owners": 0, "source": None}


def owner_pay_quarterly(people_json: Any, financials_json: Any = None) -> Dict[str, Any]:
  """The valuation add-back per quarter: annual_total / 4 (0.0 when absent),
  with the owner count and source carried for the sheet's note."""
  total = owner_pay_total(people_json, financials_json)
  annual = total["annual_total"]
  return {
    "quarterly": (annual / 4.0) if annual is not None else 0.0,
    "annual_total": annual,
    "owners": total["owners"],
    "source": total["source"],
  }


def owner_compensation_mirror_monthly(people_json: Any) -> Optional[float]:
  """financials.owner_compensation as a stated function of the SET of owner
  rows: the sum of their annual pay / 12, rounded to cents. None when no
  owner-titled row carries a numeric wage (the legacy-field branch of the
  sync then governs)."""
  total = owner_pay_total(people_json, None)
  if total["source"] != SOURCE_PEOPLE_ROWS:
    return None
  return round(float(total["annual_total"]) / 12.0, 2)


def owner_rows_annual_sum(rows: Any) -> Optional[float]:
  """Sum of annual_wage over owner-titled rows in an arbitrary row list (the
  payroll basis rows, for the staleness check). None when no such row."""
  if not isinstance(rows, list):
    return None
  wages = [
    _num(r.get("annual_wage")) for r in rows
    if isinstance(r, dict) and OWNER_TITLE_RE.search(str(r.get("role_title") or ""))
  ]
  wages = [w for w in wages if w is not None]
  return float(sum(wages)) if wages else None
