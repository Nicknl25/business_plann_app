"""The 5 firm-side viability constructs (Fix #1 spec §2).

Operating-engine-only. Reads finmo_json.quarter_rows (live quarters,
quarter_index >= 1). Uses ONLY operating subsets — never the
funding-contaminated `current_assets` / `current_liabilities` totals
(which include cash and short-term debt, finmo_model.py:586,543).

Constructs:
  1. Operating-cash proxy = EBITDA - Delta(operating NWC)
     Reuses finmo's already-clean working-capital cash deltas:
       changes_in_current_assets        = -Delta(AR+inventory+prepaid)   (finmo_model.py:562, ex-cash)
       changes_in_current_liabilities   = +Delta(AP+deferred)            (finmo_model.py:571-572, ex-STD)
     so  EBITDA - Delta(NWC) = EBITDA + changes_in_current_assets + changes_in_current_liabilities
     (subtracting the NWC increase == adding finmo's signed WC cash deltas).
  2. Rule-of-40 = revenue-growth% (QoQ) + EBITDA-margin%.
  3. Working-capital intensity = operating-NWC / revenue (+ its trajectory).
       operating NWC = (AR + inventory + prepaid) - (AP + deferred).
  4. EBITDA ramp shape: breakeven quarter, EBITDA-margin slope, operating leverage.
  5. Cumulative EBITDA (running sum).

Firm-side only. Cohort percentiles (Unit 4) and scoring (Units 5/6) live
in sibling modules; these functions return raw per-quarter series + scalars.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


# Operating working-capital component fields (the clean subset).
_OP_CA_FIELDS = ("accounts_receivable", "inventory", "prepaid_expenses")
_OP_CL_FIELDS = ("accounts_payable", "deferred_revenue")


def _f(v: Any) -> Optional[float]:
  if v is None:
    return None
  try:
    return float(v)
  except (TypeError, ValueError):
    return None


def live_quarter_rows(finmo_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  """Live forecast quarters (quarter_index >= 1), sorted ascending.

  Excludes the opening stub (quarter_index 0). Mirrors the row filtering
  the payroll feasibility gate uses (schedule.py:3111-3114).
  """
  if not isinstance(finmo_json, dict):
    return []
  rows = finmo_json.get("quarter_rows")
  if not isinstance(rows, list):
    return []
  live = [r for r in rows if isinstance(r, dict) and int(_f(r.get("quarter_index")) or 0) >= 1]
  return sorted(live, key=lambda r: int(_f(r.get("quarter_index")) or 0))


def _ols_slope(xs: List[float], ys: List[float]) -> Optional[float]:
  """Ordinary-least-squares slope of ys on xs. None when undefined
  (< 2 points or zero x-variance)."""
  n = len(xs)
  if n < 2 or len(ys) != n:
    return None
  mean_x = sum(xs) / n
  mean_y = sum(ys) / n
  var_x = sum((x - mean_x) ** 2 for x in xs)
  if var_x == 0.0:
    return None
  cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
  return cov / var_x


def _operating_nwc(row: Dict[str, Any]) -> Optional[float]:
  ca = sum((_f(row.get(k)) or 0.0) for k in _OP_CA_FIELDS)
  cl = sum((_f(row.get(k)) or 0.0) for k in _OP_CL_FIELDS)
  # If every component is missing/None, treat as unknown rather than 0.
  if all(row.get(k) is None for k in _OP_CA_FIELDS + _OP_CL_FIELDS):
    return None
  return ca - cl


# ---------------------------------------------------------------------------
# Construct 1 — Operating-cash proxy = EBITDA - Delta(operating NWC).
# ---------------------------------------------------------------------------
def operating_cash_proxy_series(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
  out: List[Dict[str, Any]] = []
  for r in rows:
    q = int(_f(r.get("quarter_index")) or 0)
    ebitda = _f(r.get("ebitda"))
    d_ca = _f(r.get("changes_in_current_assets"))
    d_cl = _f(r.get("changes_in_current_liabilities"))
    rev = _f(r.get("revenue"))
    value = None
    if ebitda is not None and d_ca is not None and d_cl is not None:
      value = ebitda + d_ca + d_cl
    margin = (value / rev) if (value is not None and rev not in (None, 0.0)) else None
    out.append({"quarter_index": q, "value": value, "margin": margin})
  return out


# ---------------------------------------------------------------------------
# Construct 2 — Rule-of-40 = revenue-growth% (QoQ) + EBITDA-margin%.
# ---------------------------------------------------------------------------
def rule_of_40_series(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
  out: List[Dict[str, Any]] = []
  prev_rev: Optional[float] = None
  for r in rows:
    q = int(_f(r.get("quarter_index")) or 0)
    rev = _f(r.get("revenue"))
    ebitda = _f(r.get("ebitda"))
    growth = None
    if prev_rev is not None and prev_rev > 0.0 and rev is not None:
      growth = (rev - prev_rev) / prev_rev
    margin = (ebitda / rev) if (ebitda is not None and rev not in (None, 0.0)) else None
    rule = (growth + margin) if (growth is not None and margin is not None) else None
    out.append({"quarter_index": q, "revenue_growth": growth, "ebitda_margin": margin, "rule_of_40": rule})
    if rev is not None:
      prev_rev = rev
  return out


# ---------------------------------------------------------------------------
# Construct 3 — Working-capital intensity = operating-NWC / revenue.
# ---------------------------------------------------------------------------
def nwc_intensity_series(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
  out: List[Dict[str, Any]] = []
  for r in rows:
    q = int(_f(r.get("quarter_index")) or 0)
    rev = _f(r.get("revenue"))
    nwc = _operating_nwc(r)
    intensity = (nwc / rev) if (nwc is not None and rev not in (None, 0.0)) else None
    out.append({"quarter_index": q, "nwc": nwc, "nwc_to_revenue": intensity})
  return out


# ---------------------------------------------------------------------------
# Construct 4 — EBITDA ramp shape.
# ---------------------------------------------------------------------------
def ebitda_ramp(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
  margin_series: List[Dict[str, Any]] = []
  breakeven_quarter: Optional[int] = None
  q_idx: List[float] = []
  margins: List[float] = []
  log_rev: List[float] = []
  margins_for_leverage: List[float] = []
  for r in rows:
    q = int(_f(r.get("quarter_index")) or 0)
    rev = _f(r.get("revenue"))
    ebitda = _f(r.get("ebitda"))
    margin = (ebitda / rev) if (ebitda is not None and rev not in (None, 0.0)) else None
    margin_series.append({"quarter_index": q, "ebitda_margin": margin})
    if breakeven_quarter is None and ebitda is not None and ebitda >= 0.0:
      breakeven_quarter = q
    if margin is not None:
      q_idx.append(float(q))
      margins.append(margin)
      if rev is not None and rev > 0.0:
        log_rev.append(math.log(rev))
        margins_for_leverage.append(margin)
  return {
    "margin_per_quarter": margin_series,
    "breakeven_quarter": breakeven_quarter,
    # EBITDA-margin slope per quarter (OLS of margin vs quarter index).
    "margin_slope_per_quarter": _ols_slope(q_idx, margins),
    # Operating leverage: margin expansion as revenue scales (OLS of margin
    # vs ln(revenue)) — scale-robust "margin gain per e-fold revenue".
    "operating_leverage": _ols_slope(log_rev, margins_for_leverage),
  }


# ---------------------------------------------------------------------------
# Construct 5 — Cumulative EBITDA (running sum).
# ---------------------------------------------------------------------------
def cumulative_ebitda_series(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
  out: List[Dict[str, Any]] = []
  running = 0.0
  seen = False
  for r in rows:
    q = int(_f(r.get("quarter_index")) or 0)
    ebitda = _f(r.get("ebitda"))
    if ebitda is not None:
      running += ebitda
      seen = True
    out.append({"quarter_index": q, "cumulative_ebitda": (running if seen else None)})
  return out


# ---------------------------------------------------------------------------
# Top-level firm-side bundle.
# ---------------------------------------------------------------------------
def firm_constructs(finmo_json: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  """Compute all 5 firm-side constructs from a finmo_json. Pure / read-only."""
  rows = live_quarter_rows(finmo_json)
  cum = cumulative_ebitda_series(rows)
  final_cum = next((c["cumulative_ebitda"] for c in reversed(cum) if c["cumulative_ebitda"] is not None), None)
  final_q = cum[-1]["quarter_index"] if cum else None
  return {
    "quarters": [int(_f(r.get("quarter_index")) or 0) for r in rows],
    "operating_cash_proxy": operating_cash_proxy_series(rows),
    "rule_of_40": rule_of_40_series(rows),
    "nwc_intensity": nwc_intensity_series(rows),
    "ebitda_ramp": ebitda_ramp(rows),
    "cumulative_ebitda": {
      "per_quarter": cum,
      "final": final_cum,
      "final_quarter": final_q,
    },
  }
