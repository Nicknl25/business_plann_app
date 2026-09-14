"""TWO COPIES OF ONE FACT MUST AGREE - arithmetic on the store (Nick ruled 2026-09-14).

The one blocking group that needs no interpretation at all, and the one that had no
implementation. Cowork 1185 read it off the store: Green Meadow's ops row holds her 40
visits a week while financials_year1 holds 426.8986827126362 of the same fact; Alder &
Vine's ops row holds her 185 a week beside a units_per_period_capacity of 2 on a WEEKLY
row, and financials_year1 holds 187.35859728506782. Her figure was never lost - the copy
that got used was the wrong one.

This reads two stored numbers and the cadence rule the app itself derives by
(_derive_capacity_cells): a weekly row's period IS its week; any other row's week is
period x periods-per-year / 52. Nothing here reads her words, and nothing here decides
which copy is right - that is her question. It names every pair that disagrees.

One field per fact is the real fix (the corollary of one reader); this finds the
second copies until then.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# the app's own twin tolerance (_derive_capacity_cells: 0.0005 relative) - rounding of a
# stored derivation, not a judgement about how close is close enough
REL = 0.0005
ABS = 1e-6

# the same fact held on the ops product row and on its financials_year1 copy
ROW_FACTS = ("units_per_week_capacity", "units_per_period_capacity", "unit_price", "operating_periods_per_year")


def _f(v: Any) -> Optional[float]:
  try:
    if v is None or isinstance(v, bool):
      return None
    return float(v)
  except (TypeError, ValueError):
    return None


def _agree(a: float, b: float) -> bool:
  return abs(a - b) <= max(ABS, REL * max(abs(a), abs(b)))


def _rows(lob_list: Any, lob_key: str) -> Dict[tuple, Dict[str, Any]]:
  out: Dict[tuple, Dict[str, Any]] = {}
  for lm in lob_list or []:
    if not isinstance(lm, dict):
      continue
    for p in lm.get("products") or []:
      if isinstance(p, dict):
        out[(str(lm.get(lob_key) or "").strip(), str(p.get("product_name") or "").strip())] = p
  return out


def _week_period_pair(where: str, row: tuple, p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
  wk, per = _f(p.get("units_per_week_capacity")), _f(p.get("units_per_period_capacity"))
  if wk is None or per is None:
    return None
  cadence = str(p.get("unit_cadence") or "").strip().lower()
  periods = _f(p.get("operating_periods_per_year"))
  if cadence == "weekly":
    expected_week = per
    rule = "a weekly row's period is its week"
  elif periods and periods > 0:
    expected_week = per * periods / 52.0
    rule = "week = period x %g periods / 52" % periods
  else:
    return None
  if _agree(wk, expected_week):
    return None
  return {"where": where, "row": list(row), "fact": "capacity",
          "a": {"field": "units_per_week_capacity", "value": wk},
          "b": {"field": "units_per_period_capacity", "value": per, "as_week": round(expected_week, 6)},
          "rule": rule}


# A YEAR HAS ONLY SO MANY OF A CADENCE'S PERIODS (Cowork 1215, CW-070 draft 71d4e505): a
# monthly row stored operating_periods_per_year 52, and year-one wrote
# operating_months_per_year 52 - fifty-two months in a year. A bound, not a judgment: no
# words are read and nothing decides what the right number is.
_MAX_PERIODS = {"weekly": 53.0, "monthly": 12.0}
_PERIOD_FIELDS = ("operating_periods_per_year", "operating_months_per_year", "operating_weeks_per_year")


def _period_bound(where: str, row: tuple, p: Dict[str, Any]) -> List[Dict[str, Any]]:
  cadence = str(p.get("unit_cadence") or "").strip().lower()
  out = []
  for field in _PERIOD_FIELDS:
    v = _f(p.get(field))
    if v is None:
      continue
    limit = 12.0 if field == "operating_months_per_year" else 53.0 if field == "operating_weeks_per_year" else _MAX_PERIODS.get(cadence)
    if limit is not None and v > limit + ABS:
      out.append({"where": where, "row": list(row), "fact": "periods in a year",
                  "a": {"field": field, "value": v}, "b": {"field": "unit_cadence", "value": cadence or None, "max": limit},
                  "rule": "a year holds at most %g of this row's periods" % limit, "shape": "impossible"})
  return out


def twin_disagreements(operating_model_json: Any, financials_year1_json: Any) -> List[Dict[str, Any]]:
  """Every pair of stored fields holding one fact that do not agree, by arithmetic.
  (1) within a row, capacity per week against capacity per period, by the row's cadence;
  (2) the ops row against its financials_year1 copy, fact by fact."""
  ops = operating_model_json if isinstance(operating_model_json, dict) else {}
  y1 = financials_year1_json if isinstance(financials_year1_json, dict) else {}
  ops_rows = _rows(ops.get("lob_models"), "lob_name")
  y1_rows = _rows(y1.get("lobs"), "lob_name")
  out: List[Dict[str, Any]] = []
  for where, rows in (("operating_model_json", ops_rows), ("financials_year1_json", y1_rows)):
    for row, p in rows.items():
      d = _week_period_pair(where, row, p)
      if d:
        out.append(d)
      out.extend(_period_bound(where, row, p))
  for row, p in ops_rows.items():
    q = y1_rows.get(row)
    if q is None:
      continue
    for fact in ROW_FACTS:
      a, b = _f(p.get(fact)), _f(q.get(fact))
      if a is None or b is None or _agree(a, b):
        continue
      out.append({"where": "operating_model_json vs financials_year1_json", "row": list(row), "fact": fact,
                  "a": {"field": "operating_model_json." + fact, "value": a},
                  "b": {"field": "financials_year1_json." + fact, "value": b},
                  "rule": "one fact, two copies", "ratio": round(b / a, 6) if a else None,
                  # read on the store 2026-09-14 (Alderman & Fitch a88dae18, Thackeray & Nunes
                  # 53a7603f): the year-one build writes 0.0 where ops holds her figure or
                  # nothing - the plan then reads the 0. Still two copies disagreeing; named
                  # apart so a count says which shape it holds.
                  "shape": "zero_in_copy" if (a == 0) != (b == 0) else "disagree"})
  for d in out:
    d.setdefault("shape", "disagree")
  return out
