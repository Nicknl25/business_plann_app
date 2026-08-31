"""THE VALUATION, PROMOTED (Nick's ruling, 2026-08-31).

Equity value and the exit multiple become catalogue facts a GROUNDED sentence
can carry. The workbook's Valuation sheet computes in Excel formulas only, so
this module MIRRORS that computation in Python, step for step against
valuation_sheet.py:

  cost of equity   rf + ERP + size premium + company-specific premium
  WACC             ke*we + kd*(1-tax)*wd, book weights from the Y1 balance
                   sheet, kd = Debt Schedule Q1 rate x 4, tax = model's rate
  UFCF per quarter NOPAT + depreciation - max(capex, revenue x maintenance
                   floor) + changes in working capital (signs as the cash
                   flow statement carries them)
  discounting      quarterly, 1/(1+WACC/4)^n
  terminal         UFCF_Y5 x (1+g) / (WACC-g), shown ONLY when the spread
                   clears the floor - below it the sheet prints an em dash
                   and this module returns ABSENT-equivalent None
  equity           PV(FCF) + PV(TV) - net debt TODAY (the stub column)

THE GUARD (scripts/writing_phase_valuation_guard.py + the env-gated test):
the fact and the recalculated workbook cell must agree on the same run. A
divergence FAILS - same numbers or no number.

Constants come from valuation_reference_constants with the sheet's own
resolution rule (longest NAICS prefix wins, ALL is the floor) and the sheet's
build-time fallbacks, so the two implementations cannot resolve differently.
"""
from __future__ import annotations

import json
import math
from typing import Any, Dict, Optional

QUARTERS = 20

# valuation_sheet.py's _FALLBACK, mirrored verbatim so an empty constants table
# resolves identically on both sides.
_FALLBACK = {
  "risk_free_rate": {"value": 0.0472, "citation": "FRED DGS10 (build-time fallback)", "as_of": "2026-08-17"},
  "equity_risk_premium": {"value": 0.0428, "citation": "Damodaran implied ERP (build-time fallback)", "as_of": "2026-08-01"},
  "size_premium_micro_cap": {"value": 0.112, "citation": "Kroll CRSP decile 10 (build-time fallback)", "as_of": "2026-01-01"},
  "company_specific_risk_premium": {"value": 0.03, "citation": "judgment (build-time fallback)", "as_of": ""},
  "terminal_growth_rate": {"value": 0.023, "citation": "FRED-derived (build-time fallback)", "as_of": "2026-08-18"},
  "exit_multiple_sde": {"value": 2.7, "citation": "BizBuySell Insight Report (build-time fallback)", "as_of": "2026-06-30"},
  "wacc_minus_growth_floor": {"value": 0.03, "citation": "structural guard (build-time fallback)", "as_of": ""},
  # 0.028 EXACTLY as valuation_sheet.py has it - the first guard run caught
  # this fallback written as 0.005 "from memory": a 20.7% equity divergence,
  # entirely in the capex floor. Mirrored means byte-for-byte.
  "maintenance_capex_percent_of_revenue": {"value": 0.028, "citation": "Maintenance capital expenditure floor (build-time fallback)", "as_of": ""},
}


def _f(v: Any) -> Optional[float]:
  try:
    x = float(v)
    return x if math.isfinite(x) else None
  except (TypeError, ValueError):
    return None


def _j(v: Any) -> Any:
  if isinstance(v, (dict, list)):
    return v
  try:
    return json.loads(v) if v else {}
  except Exception:
    return {}


def load_constants(cur, naics: str) -> Dict[str, Dict[str, Any]]:
  """The sheet's resolution rule: longest matching NAICS prefix wins, ALL is
  the floor; fallbacks fill anything the table lacks."""
  resolved: Dict[str, Dict[str, Any]] = {}
  digits = str(naics or "")
  try:
    cur.execute("SELECT constant_key, applies_to, value_default, data_source, "
                "source_citation, source_as_of FROM valuation_reference_constants "
                "WHERE active=1")
    for key, scope, value, source, citation, as_of in cur.fetchall():
      scope = str(scope or "ALL")
      if scope != "ALL" and not digits.startswith(scope):
        continue
      current = resolved.get(str(key))
      cur_scope = str(current.get("scope") or "") if current else None
      new_scope = "" if scope == "ALL" else scope
      if current is not None and len(cur_scope) >= len(new_scope):
        continue
      resolved[str(key)] = {
        "value": _f(value), "scope": new_scope, "source": str(source or ""),
        "citation": str(citation or ""), "as_of": str(as_of or ""),
      }
  except Exception:
    pass
  for key, fb in _FALLBACK.items():
    if key not in resolved or resolved[key]["value"] is None:
      resolved[key] = {"value": fb["value"], "scope": "", "source": "build_time_fallback",
                       "citation": fb["citation"], "as_of": fb.get("as_of", "")}
  return resolved


def compute_valuation(cur, draft: Dict[str, Any]) -> Dict[str, Any]:
  """The Python twin of the Valuation sheet. Returns {} when the model lacks
  what the sheet itself would refuse to price."""
  om = _j(draft.get("operating_model_json"))
  fin = _j(draft.get("financials_json"))
  fj = _j(draft.get("finmo_json"))
  mi = _j(draft.get("model_input_json"))
  # NOTE the explicit None check: `or -99` would swallow the STUB, whose
  # quarter_index is 0 and therefore falsy - that bug made the valuation
  # ABSENT on every draft and the guard vacuously green (caught 2026-08-31).
  qr = {}
  for r in (fj.get("quarter_rows") or []):
    if isinstance(r, dict):
      qi = _f(r.get("quarter_index"))
      if qi is not None:
        qr[int(qi)] = r
  if not all(i in qr for i in range(0, QUARTERS + 1)):
    return {}
  naics = str(om.get("business_naics_6") or "")
  const = load_constants(cur, naics)
  C = lambda k: float(const[k]["value"])

  # owner comp is stored MONTHLY; the sheet takes three per quarter
  owner_comp_q = (_f(fin.get("owner_compensation")) or 0.0) * 3.0

  # tax: the model's own effective rate (Model Inputs "Taxes", ratio, Q1)
  tax = 0.0
  for r in ((mi.get("sections") or {}).get("expenses") or []):
    if str(r.get("label")) == "Taxes":
      vals = r.get("values") or []
      tax = _f(vals[1] if len(vals) > 1 else None) or 0.0
      break
  # cost of debt: Debt Schedule Q1 rate x 4 == finmo debt_interest_rate Q1 x 4
  kd = (_f(qr[1].get("debt_interest_rate")) or 0.0) * 4.0

  ke = C("risk_free_rate") + C("equity_risk_premium") + C("size_premium_micro_cap") \
       + C("company_specific_risk_premium")
  eq_y1 = _f(qr[4].get("total_equity")) or 0.0
  debt_y1 = sum(_f(qr[4].get(k)) or 0.0 for k in
                ("short_term_debt", "long_term_debt", "capital_lease_obligation"))
  we = eq_y1 / (eq_y1 + debt_y1) if (eq_y1 + debt_y1) > 0 else 1.0
  wd = 1.0 - we
  wacc = ke * we + kd * (1.0 - tax) * wd
  g = C("terminal_growth_rate")
  spread = wacc - g

  pv_total = 0.0
  ufcf_by_q = []
  sde_y5 = 0.0
  tot = {"ebitda": 0.0, "nopat": 0.0, "dep": 0.0, "capex": 0.0, "nwc": 0.0}
  maint = C("maintenance_capex_percent_of_revenue")
  for i in range(1, QUARTERS + 1):
    row = qr[i]
    rev = _f(row.get("revenue")) or 0.0
    ebitda = _f(row.get("ebitda")) or 0.0
    dep = _f(row.get("depreciation")) or 0.0
    ebit = ebitda - dep
    nopat = ebit * (1.0 - tax)
    cf_capex = -(_f(row.get("capital_expenditures")) or 0.0)   # CF sign
    capex_term = -max(cf_capex, rev * maint)
    nwc = (_f(row.get("changes_in_current_assets")) or 0.0) \
        + (_f(row.get("changes_in_current_liabilities")) or 0.0)
    ufcf = nopat + dep + capex_term + nwc
    tot["ebitda"] += ebitda; tot["nopat"] += nopat; tot["dep"] += dep
    tot["capex"] += capex_term; tot["nwc"] += nwc
    ufcf_by_q.append(ufcf)
    df = 1.0 / (1.0 + wacc / 4.0) ** i
    pv_total += ufcf * df
    if i >= 17:
      sde_y5 += ebitda + owner_comp_q

  ufcf_y5 = sum(ufcf_by_q[16:20])
  floor = C("wacc_minus_growth_floor")
  # THE SHEET'S TERMINAL LAW (read off the built sheet, 2026-08-31): both
  # methods side by side and the value USED is their AVERAGE - perpetuity
  # growth and the exit multiple - with the perpetuity half shown only when
  # the spread clears the floor. Mirroring perpetuity-only diverged 27%.
  exit_tv = sde_y5 * float(const["exit_multiple_sde"]["value"]) if sde_y5 > 0 else None
  perp_tv = ufcf_y5 * (1.0 + g) / spread if (spread >= floor and spread > 0) else None
  tv_used = None
  if perp_tv is not None and exit_tv is not None:
    tv_used = (perp_tv + exit_tv) / 2.0
  elif exit_tv is not None:
    tv_used = exit_tv
  elif perp_tv is not None:
    tv_used = perp_tv
  tv_pv = tv_used * (1.0 / (1.0 + wacc / 4.0) ** QUARTERS) if tv_used is not None else None

  # net debt TODAY: the stub column (quarter_index 0)
  stub = qr[0]
  net_debt = sum(_f(stub.get(k)) or 0.0 for k in
                 ("short_term_debt", "long_term_debt", "capital_lease_obligation")) \
             - (_f(stub.get("cash")) or 0.0)

  out: Dict[str, Any] = {
    "component_totals": {k: round(v, 2) for k, v in tot.items()},
    "ufcf_total": sum(ufcf_by_q), "ufcf_y5": ufcf_y5,
    "perp_tv": perp_tv, "exit_tv": exit_tv, "tv_used": tv_used,
    "wacc": wacc, "cost_of_equity": ke, "spread": spread, "spread_ok": perp_tv is not None,
    "pv_explicit": pv_total, "tv_pv": tv_pv, "net_debt": net_debt,
    "sde_y5": sde_y5, "owner_comp_q": owner_comp_q,
    "exit_multiple": const["exit_multiple_sde"],
    "constants": {k: const[k] for k in ("risk_free_rate", "equity_risk_premium",
                                        "size_premium_micro_cap",
                                        "company_specific_risk_premium",
                                        "terminal_growth_rate")},
  }
  if tv_pv is not None:
    ev = pv_total + tv_pv
    out["enterprise_value"] = ev
    out["equity_value"] = ev - net_debt
  if sde_y5 > 0:
    out["value_at_exit_multiple"] = sde_y5 * float(const["exit_multiple_sde"]["value"])
  return out
