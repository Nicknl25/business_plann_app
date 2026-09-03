"""THE BUILDERS - one per namespace, computed against a REAL draft (2026-08-30).

Python computes; GPT never does (rule 17). Everything here reads the stored
payloads and the warehouse, and puts Facts into a FactCatalog. Anything that
cannot be computed for this business is put as ABSENT with a reason, and the
catalogue drops it.

Geography is resolved from the business ZIP through zip_county_crosswalk
(state_fips, county_fips) rather than from address_state, which arrives as
"NC" on one draft and "Minnesota" on the next.

Every computation is guarded: a builder that raises records the failure as an
ABSENT reason on every key it owns and moves on. A missing fact is a shorter
section, never a crashed plan.
"""
from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .catalog import (ABSENT, FactCatalog, Provenance, prov_baseline, prov_intake, prov_model, prov_raw)
from .. import rules as RR
from . import valuation as V

# ---------------------------------------------------------------------------
# table-level vintages (raw tables carry no per-row provenance - ruling E)
# ---------------------------------------------------------------------------
V_ACS = "U.S. Census Bureau, American Community Survey 5-year, 2022, by ZCTA"
V_CBP = "U.S. Census Bureau, County Business Patterns 2022, state by NAICS"
V_BDS = "U.S. Census Bureau, Business Dynamics Statistics 1978-2023, national by NAICS-4"
V_SBA = "U.S. Small Business Administration, 7(a) loan data FY2020-FY2025"
V_OEWS = "U.S. Bureau of Labor Statistics, Occupational Employment and Wage Statistics"

FIPS_TO_ABBR = {
  "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE",
  "11": "DC", "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA",
  "20": "KS", "21": "KY", "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
  "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH", "34": "NJ", "35": "NM",
  "36": "NY", "37": "NC", "38": "ND", "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
  "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
  "54": "WV", "55": "WI", "56": "WY", "72": "PR",
}

# ACS B01001 age bands: sex-by-age columns 003..025 (male) and 027..049 (female)
_AGE_BANDS = [(0, 4), (5, 9), (10, 14), (15, 17), (18, 19), (20, 20), (21, 21), (22, 24), (25, 29),
              (30, 34), (35, 39), (40, 44), (45, 49), (50, 54), (55, 59), (60, 61), (62, 64),
              (65, 66), (67, 69), (70, 74), (75, 79), (80, 84), (85, 120)]
_AGE_COLS = [("B01001_%03dE" % (3 + i), "B01001_%03dE" % (27 + i)) for i in range(23)]
# ACS B19001 household income brackets 002..017 (upper edges, thousands)
_INC_EDGES = [10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 75, 100, 125, 150, 200, 10 ** 9]
_INC_COLS = ["B19001_%03dE" % (2 + i) for i in range(16)]


def _f(v: Any) -> Optional[float]:
  try:
    x = float(v)
    return x if math.isfinite(x) else None
  except (TypeError, ValueError):
    return None


def _j(v: Any) -> Any:
  if v is None:
    return {}
  if isinstance(v, (dict, list)):
    return v
  try:
    return json.loads(v)
  except Exception:
    return {}


def _median(xs: Sequence[float]) -> Optional[float]:
  s = sorted(x for x in xs if x is not None)
  if not s:
    return None
  n = len(s)
  return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _percentile_rank(xs: Sequence[float], v: float) -> Optional[float]:
  s = sorted(xs)
  if not s:
    return None
  below = sum(1 for x in s if x < v)
  return round(100.0 * below / len(s))


def _quarters(finmo: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
  out: Dict[int, Dict[str, Any]] = {}
  for r in finmo.get("quarter_rows") or []:
    qi = _f(r.get("quarter_index"))
    if qi is not None:
      out[int(qi)] = r
  return out


def _ysum(q: Dict[int, Dict[str, Any]], key: str, year: int) -> Optional[float]:
  vals = [_f(q.get(i, {}).get(key)) for i in range(4 * year - 3, 4 * year + 1)]
  if any(v is None for v in vals) or len(vals) != 4:
    return None
  return float(sum(vals))


def _yend(q: Dict[int, Dict[str, Any]], key: str, year: int) -> Optional[float]:
  return _f(q.get(4 * year, {}).get(key))


def _opcost_q(row: Dict[str, Any]) -> Optional[float]:
  parts = [_f(row.get(k)) for k in ("cogs", "marketing", "lease_rent", "payroll", "g_and_a")]
  if any(p is None for p in parts):
    return None
  return float(sum(parts))


# ---------------------------------------------------------------------------
# GEOGRAPHY
# ---------------------------------------------------------------------------
def resolve_geography(cur, zip5: str) -> Dict[str, Any]:
  cur.execute("SELECT state_fips, county_fips, zpop_pct FROM zip_county_crosswalk "
              "WHERE zcta=%s ORDER BY zpop_pct DESC LIMIT 1", (zip5,))
  r = cur.fetchone()
  if not r:
    return {}
  state_fips, county_fips = str(r[0]).zfill(2), str(r[1]).zfill(3)
  cur.execute("SELECT DISTINCT state_name FROM cbp_2022_raw WHERE state_fips=%s LIMIT 1", (state_fips,))
  s = cur.fetchone()
  cur.execute("SELECT cbsa, usps_zip_pref_city FROM hud_zip_cbsa_092025 WHERE zip=%s "
              "ORDER BY res_ratio DESC LIMIT 1", (zip5,))
  h = cur.fetchone()
  return {
    "zip": zip5, "state_fips": state_fips, "county_fips": county_fips,
    "state_abbr": FIPS_TO_ABBR.get(state_fips), "state_name": s[0] if s else None,
    "cbsa": str(int(float(h[0]))) if h and h[0] is not None else None,
    "pref_city": (str(h[1]).strip().title() if h and h[1] else None),
  }


# ---------------------------------------------------------------------------
# ENTITY
# ---------------------------------------------------------------------------
def build_entity(cat: FactCatalog, cur, draft: Dict[str, Any], geo: Dict[str, Any]) -> Dict[str, Any]:
  om, fin, tm = _j(draft.get("operating_model_json")), _j(draft.get("financials_json")), _j(draft.get("target_market_json"))
  finmo = _j(draft.get("finmo_json"))
  name = str(draft.get("business_name") or "").strip()
  cat.put("entity.business_name", name or ABSENT, "text", prov_intake("business name"), "Business name")
  naics6 = str(om.get("business_naics_6") or "").strip()
  ctx: Dict[str, Any] = {"naics6": naics6, "geo": geo}
  if naics6:
    cur.execute("SELECT naics_title FROM naics_master WHERE naics_code=%s LIMIT 1", (naics6,))
    r = cur.fetchone()
    cat.put("entity.naics_title", (r[0] if r else ABSENT), "text",
            prov_intake("industry classification NAICS %s" % naics6), "Industry title")
  else:
    cat.put("entity.naics_title", ABSENT, "text", prov_intake("x"), absent_reason="no NAICS on draft")
  cat.put("entity.state_name", geo.get("state_name") or ABSENT, "text",
          prov_intake("business address"), "State", absent_reason="ZIP not in crosswalk")
  # years operating
  sd = str(draft.get("business_start_date") or om.get("business_start_date") or "")
  yrs = ABSENT
  founded = ABSENT
  founded_my = ABSENT
  try:
    import datetime as _dt
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
      try:
        d0 = _dt.datetime.strptime(sd[:10], fmt)
        yrs = max(1, int((_dt.datetime.now() - d0).days // 365) + 1)
        founded = str(d0.year)
        founded_my = d0.strftime("%B %Y")
        break
      except ValueError:
        continue
  except Exception:
    pass
  cat.put("entity.years_operating", yrs, "ordinal", prov_intake("business start date"), "Years operating",
          absent_reason="no parseable start date")
  # founded year (Nick 2026-09-01): "open since 2016" is the one date a company
  # description should carry; without this fact the digits fail rule 17.
  cat.put("entity.founded_year", founded, "text", prov_intake("business start date"), "Founded",
          absent_reason="no parseable start date")
  cat.put("entity.founded_month_year", founded_my, "text", prov_intake("business start date"),
          "Founded (month and year)", absent_reason="no parseable start date")
  # digit-bearing identifiers the client stated (Nick 2026-09-01): a
  # certification a business holds is exactly the specificity that makes a
  # plan theirs, and rule 17 means its digits can only ride inside a token -
  # so stated identifiers become facts. Extraction is deliberately
  # conservative: 2-5 capitals + 3-5 digits (AS9100, ISO 9001), never a token
  # that is part of the business's own name.
  import re as _re
  # description + advantage ONLY: coverage text carries "NC 27615"-style
  # state+ZIP pairs that satisfy the letters+digits pattern and are not
  # certifications (caught red by the first test run).
  _prof = " ".join(str(om.get(k) or "") for k in
                   ("business_description_summary", "competitive_advantage"))
  _name_flat = _re.sub(r"[^A-Z0-9]", "", name.upper())
  certs = sorted({m.group(0) for m in _re.finditer(r"\b[A-Z]{2,5}[ -]?\d{3,5}\b", _prof)
                  if _re.sub(r"[^A-Z0-9]", "", m.group(0).upper()) not in _name_flat})
  cat.put("entity.stated_certifications", (certs if certs else ABSENT), "list",
          prov_intake("standards and certifications stated by the client"),
          "Stated certifications", absent_reason="no certification identifiers stated")
  _zips = _re.findall(r"\b\d{5}\b", str(om.get("geographic_coverage") or ""))
  cat.put("entity.coverage_zip", (_zips[0] if _zips else ABSENT), "text",
          prov_intake("stated service area"), "Coverage ZIP",
          absent_reason="no ZIP stated in coverage")
  # identity legs for The Business (Part 1, 2026-08-30)
  _legal = str(om.get("legal_entity") or "").strip()
  cat.put("entity.legal_entity", (_legal if _legal else ABSENT), "text",
          prov_intake("legal entity"), "Legal entity", absent_reason="no legal entity stated")
  cat.put("entity.stated_employees", _f(fin.get("current_num_employees")) or ABSENT, "count",
          prov_intake("current employee count"), "Stated employees", absent_reason="not stated")
  _city = geo.get("pref_city"); _st = geo.get("state_name")
  cat.put("entity.city_state", ("%s, %s" % (_city, _st) if _city and _st else ABSENT), "text",
          prov_intake("business address"), "City and state", absent_reason="ZIP did not resolve to a city")
  cat.put("entity.stated_current_revenue", _f(fin.get("current_revenue")) or ABSENT, "money",
          prov_intake("current annual revenue"), "Stated revenue", absent_reason="not stated")
  # THE DEPTH FACTS (Nick 2026-09-02): "ten facts in, four numbers out" - the
  # stated TODAY position a consultant would put in a company description.
  # Computed by Python from intake statements; rule 17 keeps GPT out of the
  # arithmetic.
  _rev, _emp = _f(fin.get("current_revenue")), _f(fin.get("current_num_employees"))
  cat.put("entity.stated_revenue_per_employee",
          (_rev / _emp if _rev and _emp and _emp >= 1 else ABSENT), "money",
          prov_intake("stated annual revenue over stated headcount"),
          "Revenue per person today", absent_reason="revenue or headcount not stated")
  _cash = _f(fin.get("cash_on_hand"))
  cat.put("entity.stated_cash_on_hand", (_cash if _cash and _cash > 0 else ABSENT), "money",
          prov_intake("stated cash on hand"), "Cash on hand today",
          absent_reason="no cash position stated")
  _debt = _f(fin.get("total_debt_outstanding"))
  cat.put("entity.stated_debt_outstanding", (_debt if _debt and _debt > 0 else ABSENT), "money",
          prov_intake("stated debt outstanding"), "Debt outstanding today",
          absent_reason="no debt stated (a debt-free position is words, not a figure)")
  # funding request = new borrowing in the projections' first year
  q = _quarters(finmo)
  ask = _ysum(q, "debt_issuance", 1)
  cat.put("entity.funding_request", (ask if ask and ask > 0 else ABSENT), "money",
          prov_model("new borrowing in Year 1"), "Funding request",
          absent_reason="no new borrowing in the projections")
  ctx["funding_request"] = ask if ask and ask > 0 else None
  # target-market intents (consumer)
  ii = (tm.get("income_intent") or [{}])[0] if isinstance(tm.get("income_intent"), list) else {}
  floor = _f((ii or {}).get("income_min"))
  cat.put("entity.target_income_floor", (floor if floor and floor > 0 else ABSENT), "money",
          prov_intake("target customer income"), "Target income floor",
          absent_reason="no consumer income target stated")
  ctx["income_floor"] = floor if floor and floor > 0 else None
  ga = (tm.get("gender_age_intent") or [{}])[0] if isinstance(tm.get("gender_age_intent"), list) else {}
  amin, amax = _f((ga or {}).get("age_min")), _f((ga or {}).get("age_max"))
  if amin is not None and amax is not None and amax >= amin:
    cat.put("entity.target_age_band", "%d to %d" % (amin, amax), "text",
            prov_intake("target customer age range"), "Target age band")
    ctx["age_band"] = (amin, amax)
  else:
    cat.put("entity.target_age_band", ABSENT, "text", prov_intake("x"), absent_reason="no consumer age target stated")
  ctx["b2b_naics"] = [str(x) for x in (tm.get("b2b_naics_6") or []) if x]
  return ctx


# ---------------------------------------------------------------------------
# ANNUAL (finmo) + QUARTERLY exceptions
# ---------------------------------------------------------------------------
def build_annual(cat: FactCatalog, draft: Dict[str, Any], ctx: Dict[str, Any]) -> None:
  finmo, mi, fin = _j(draft.get("finmo_json")), _j(draft.get("model_input_json")), _j(draft.get("financials_json"))
  ph = _j(draft.get("payroll_headcount"))
  q = _quarters(finmo)
  if len([i for i in q if 1 <= i <= 20]) < 20:
    for k in ("annual.revenue_y1",):
      cat.put(k, ABSENT, "money", prov_model("x"), absent_reason="finmo_json lacks 20 quarters")
    return
  P = prov_model
  rev = {y: _ysum(q, "revenue", y) for y in range(1, 6)}
  cogs = {y: _ysum(q, "cogs", y) for y in range(1, 6)}
  ni = {y: _ysum(q, "net_income", y) for y in range(1, 6)}
  ebitda = {y: _ysum(q, "ebitda", y) for y in range(1, 6)}
  dep = {y: _ysum(q, "depreciation", y) for y in range(1, 6)}
  intr = {y: _ysum(q, "interest", y) for y in range(1, 6)}
  pay = {y: _ysum(q, "payroll", y) for y in range(1, 6)}
  rent = {y: _ysum(q, "lease_rent", y) for y in range(1, 6)}
  capex = {y: _ysum(q, "capital_expenditures", y) for y in range(1, 6)}
  for y in range(1, 6):
    cat.put("annual.revenue_y%d" % y, rev[y] or ABSENT, "money", P("Year %d revenue" % y), "Revenue Y%d" % y)
    cat.put("annual.net_income_y%d" % y, (ni[y] if ni[y] is not None else ABSENT), "money", P("Year %d net income" % y), "Net income Y%d" % y)
    cat.put("annual.payroll_y%d" % y, pay[y] or ABSENT, "money", P("Year %d payroll" % y), "Payroll Y%d" % y)
    cat.put("annual.capex_y%d" % y, (capex[y] if capex[y] is not None else ABSENT), "money", P("Year %d capital expenditure" % y), "CapEx Y%d" % y)
    if rev[y] and rev[y] > 0:
      gm = (rev[y] - (cogs[y] or 0)) / rev[y]
      om = ((ebitda[y] or 0) - (dep[y] or 0)) / rev[y]
      nm = (ni[y] or 0) / rev[y]
      cat.put("annual.gross_margin_y%d" % y, gm, "percent", P("Year %d gross profit over revenue" % y), "Gross margin Y%d" % y)
      cat.put("annual.operating_margin_y%d" % y, om, "percent", P("Year %d EBITDA less depreciation, over revenue" % y), "Operating margin Y%d" % y)
      cat.put("annual.net_margin_y%d" % y, nm, "percent", P("Year %d net income over revenue" % y), "Net margin Y%d" % y)
      cat.put("annual.payroll_pct_revenue_y%d" % y, (pay[y] or 0) / rev[y], "percent", P("Year %d payroll over revenue" % y), "Payroll %% of revenue Y%d" % y)
      cat.put("annual.rent_pct_revenue_y%d" % y, (rent[y] or 0) / rev[y], "percent", P("Year %d rent over revenue" % y), "Rent %% of revenue Y%d" % y)
    # DSCR: cash available for debt service over debt service
    ds = sum(x or 0 for x in (_ysum(q, "debt_repayment", y), intr[y], _ysum(q, "lease_principal_repayments", y), _ysum(q, "lease_interest_expense", y)))
    cads = (ni[y] or 0) + (dep[y] or 0) + (intr[y] or 0) + (_ysum(q, "lease_interest_expense", y) or 0)
    cat.put("annual.dscr_y%d" % y, (cads / ds if ds > 0 else ABSENT), "multiple",
            P("Year %d net income plus depreciation and interest, over debt and lease service" % y),
            "DSCR Y%d" % y, absent_reason="no debt service in Year %d" % y)
  if rev[1] and rev[5] and rev[1] > 0 and rev[5] > 0:
    cat.put("annual.revenue_cagr_y1_y5", (rev[5] / rev[1]) ** 0.25 - 1.0, "percent", P("compound annual growth, Year 1 to Year 5"), "Revenue CAGR")
  cat.put("annual.capex_total_y1_y5", (sum(capex[y] or 0 for y in range(1, 6)) if any(capex[y] for y in range(1, 6)) else ABSENT),
          "money", P("capital expenditure summed over five years"), "Total CapEx", absent_reason="no capital expenditure in the plan")
  # gap vs stated
  stated = _f(fin.get("current_revenue"))
  if stated and stated > 0 and rev[1]:
    d = rev[1] / stated - 1.0
    cat.put("annual.revenue_y1_vs_stated", ("%s above" % _fmt_pct_word(d)) if d >= 0 else ("%s below" % _fmt_pct_word(-d)),
            "text", P("Year-1 revenue against the revenue stated at intake"), "Y1 vs stated")
  # first profitable year, debt retired year
  fp = next((y for y in range(1, 6) if ni[y] is not None and ni[y] > 0), None)
  cat.put("annual.first_profitable_year", fp or ABSENT, "year", P("first year with positive net income"), "First profitable year",
          absent_reason="no profitable year in the plan")
  ob = _f(q.get(1, {}).get("debt_opening_balance"))
  ret = next((y for y in range(1, 6) if (_yend(q, "debt_closing_balance", y) or 0) <= 0.5), None)
  cat.put("annual.debt_retired_year", (ret if (ob and ob > 0 and ret) else ABSENT), "year", P("first year-end with no debt outstanding"),
          "Debt retired", absent_reason="no opening debt, or not retired within the plan")
  # cash Y5 and months of costs
  cash5 = _yend(q, "ending_cash", 5)
  oc5 = _opcost_q(q.get(20, {}))
  cat.put("annual.cash_y5", (cash5 if cash5 is not None else ABSENT), "money", P("Year-5 ending cash"), "Cash Y5")
  cat.put("annual.cash_months_of_costs_y5", (cash5 / (oc5 / 3.0) if (cash5 is not None and oc5 and oc5 > 0) else ABSENT),
          "months", P("Year-5 ending cash over one month of Year-5 operating costs"), "Cash cover Y5",
          absent_reason="no operating costs in Q20")
  # owner's capital vs assets
  oc = _yend(q, "owners_capital", 1); ta = _yend(q, "total_assets", 1)
  cat.put("annual.owners_capital_y1", (oc if oc else ABSENT), "money", P("owner's capital at Year-1 end"), "Owner's capital Y1", absent_reason="no owner's capital")
  cat.put("annual.owners_capital_pct_assets_y1", (oc / ta if (oc and ta and ta > 0) else ABSENT), "percent", P("owner's capital over total assets, Year-1 end"), "Owner's capital % assets")
  # headcount
  qt = {int(_f(t.get("quarter_index")) or 0): t for t in (ph.get("quarter_totals") or []) if isinstance(t, dict)}
  for y in (1, 5):
    hc = _f(qt.get(4 * y, {}).get("ending_fte"))
    cat.put("annual.headcount_y%d" % y, (hc if hc is not None else ABSENT), "count", P("full-time-equivalent headcount at Year-%d end" % y), "Headcount Y%d" % y,
            absent_reason="no payroll schedule")
  hc1 = _f(qt.get(4, {}).get("ending_fte"))
  cat.put("annual.revenue_per_fte_y1", (rev[1] / hc1 if (rev[1] and hc1 and hc1 > 0) else ABSENT), "money", P("Year-1 revenue over Year-1 headcount"), "Revenue per FTE Y1",
          absent_reason="no headcount")
  # cash trough (quarterly exceptions)
  trough_q = min((i for i in range(1, 21) if _f(q[i].get("ending_cash")) is not None), key=lambda i: _f(q[i]["ending_cash"]), default=None)
  if trough_q is not None:
    tc = _f(q[trough_q]["ending_cash"]); oc_t = _opcost_q(q[trough_q])
    cat.put("quarterly.cash_trough", trough_q, "quarter_label", P("the quarter in which projected cash is lowest"), "Cash trough quarter")
    cat.put("quarterly.cash_trough_amount", tc, "money", P("projected cash at its lowest quarter"), "Cash trough amount")
    cat.put("annual.cash_trough_months_of_costs", (tc / (oc_t / 3.0) if (oc_t and oc_t > 0 and tc is not None) else ABSENT), "months",
            P("cash at the trough over one month of that quarter's operating costs"), "Months of cover at trough")
  # break-even
  be = (finmo.get("break_even") or {}).get("summary") or {}
  beq = _f(be.get("first_ebitda_positive_quarter"))
  cat.put("quarterly.break_even", (int(beq) if beq and 1 <= beq <= 20 else ABSENT), "quarter_label",
          P("the first quarter in which operating earnings cover fixed costs"), "Break-even quarter",
          absent_reason="no break-even quarter within the plan")
  # marketing economics from the marketing schedule (Part 1, 2026-08-30).
  # The schedule is engine output (fd3d1ed): spend, customers, CAC and the
  # retention assumption all live there; the retention basis is an expert
  # estimate and its provenance says so rather than dressing it as a source.
  ms = _j(draft.get("marketing_schedule_json"))
  per = {int(_f(p.get("period_index")) or -1): p for p in (ms.get("periods") or []) if isinstance(p, dict)}
  mk1 = sum(_f(per.get(i, {}).get("marketing_dollars")) or 0.0 for i in range(1, 5))
  new1 = sum(_f(per.get(i, {}).get("new_customers")) or 0.0 for i in range(1, 5))
  cust = {i: _f(per.get(i, {}).get("customers")) for i in range(1, 21)}
  ret_block = ((ms.get("assumptions") or {}).get("retention") or {})
  P_ = prov_model
  cat.put("annual.marketing_y1", (mk1 if mk1 > 0 else ABSENT), "money",
          P_("Year-1 marketing spend from the marketing schedule"), "Marketing Y1",
          absent_reason="no marketing spend in the schedule")
  cat.put("annual.marketing_pct_revenue_y1", (mk1 / rev[1] if (mk1 > 0 and rev[1]) else ABSENT), "percent",
          P_("Year-1 marketing spend over Year-1 revenue"), "Marketing % of revenue")
  cat.put("annual.new_customers_y1", (new1 if new1 > 0 else ABSENT), "count",
          P_("new customers won across Year 1, from the marketing schedule"), "New customers Y1",
          absent_reason="the schedule carries no customer counts for this business")
  cat.put("annual.cac_y1", (mk1 / new1 if (mk1 > 0 and new1 > 0) else ABSENT), "money",
          P_("Year-1 marketing spend over Year-1 new customers"), "CAC Y1",
          absent_reason="the schedule carries no customer counts for this business")
  cat.put("annual.customers_y1", (cust.get(4) if cust.get(4) else ABSENT), "count",
          P_("active customers at the end of Year 1"), "Customers Y1",
          absent_reason="the schedule carries no customer counts for this business")
  cat.put("annual.customers_y5", (cust.get(20) if cust.get(20) else ABSENT), "count",
          P_("active customers at the end of Year 5"), "Customers Y5",
          absent_reason="the schedule carries no customer counts for this business")
  _rr = _f(ret_block.get("retention_rate"))
  cat.put("annual.retention_rate", (_rr if _rr is not None and _rr > 0 else ABSENT), "percent",
          Provenance := prov_model("the retention assumption in the marketing schedule (an expert estimate, not a sourced figure)"),
          "Retention rate", absent_reason="no retention assumption in the schedule")
  ret1 = sum(_f(per.get(i, {}).get("retained_customers")) or 0.0 for i in range(1, 5))
  tot1 = sum(cust.get(i) or 0.0 for i in range(1, 5))
  cat.put("annual.repeat_share_y1", (ret1 / tot1 if (ret1 > 0 and tot1 > 0) else ABSENT), "percent",
          P_("retained customers over active customers across Year 1"), "Repeat share Y1",
          absent_reason="the schedule carries no customer counts for this business")

  # per-line contribution (from the revenue drivers, scaled per line's cadence)
  _build_lob_contribution(cat, mi, _j(draft.get("operating_model_json")), rev[1], cogs[1])
  # utilisation on the top line: filled inside _build_lob_contribution


def _fmt_pct_word(d: float) -> str:
  p = d * 100.0
  return ("%d%%" % round(p)) if abs(p - round(p)) < 0.05 else ("%.1f%%" % p)


def _build_lob_contribution(cat: FactCatalog, mi: Dict[str, Any], om: Dict[str, Any],
                            rev_y1: Optional[float], cogs_y1: Optional[float]) -> None:
  rows = ((mi.get("sections") or {}).get("revenue") or [])
  periods = {}
  for lm in om.get("lob_models") or []:
    for p in lm.get("products") or []:
      ppy = _f(p.get("operating_periods_per_year"))
      if ppy:
        periods[str(lm.get("lob_name"))] = ppy
  # Keyed by PRODUCT (the lever_id prefix "revenue::<lob>::<product>"), not by
  # lob: a line with two products carries two Capacity rows under one lob
  # label, and keying by lob silently kept only the last - which is exactly
  # what the 5% gate caught on Bluestem, Understory and Harrow Lane.
  by_prod: Dict[str, Dict[str, List[float]]] = {}
  prod_lob: Dict[str, str] = {}
  for r in rows:
    lob, drv = str(r.get("lob") or ""), str(r.get("driver") or "")
    lever = str(r.get("lever_id") or "")
    prod = lever.rsplit("::", 1)[0] if "::" in lever else lob
    vals = [(_f(v) or 0.0) for v in (r.get("values") or [])]
    if lob and drv:
      by_prod.setdefault(prod, {})[drv] = vals
      prod_lob[prod] = lob
  by_lob: Dict[str, Dict[str, List[float]]] = {}
  for prod, d in by_prod.items():
    lob = prod_lob[prod]
    cap, price, util, cg = d.get("Capacity"), d.get("Unit Price"), d.get("Utilization"), d.get("COGS %")
    if not (cap and price and util):
      continue
    n = min(len(cap), len(price), len(util))
    rev = [cap[i] * price[i] * util[i] for i in range(n)]
    gp = [rev[i] * (1.0 - (cg[i] if cg and i < len(cg) else 0.0)) for i in range(n)]
    acc = by_lob.setdefault(lob, {"_rev": [0.0] * n, "_gp": [0.0] * n, "_util_w": [0.0] * n})
    for i in range(min(n, len(acc["_rev"]))):
      acc["_rev"][i] += rev[i]; acc["_gp"][i] += gp[i]; acc["_util_w"][i] += util[i] * rev[i]
  if not by_lob or not rev_y1:
    cat.put("annual.top_lob_name", ABSENT, "text", prov_model("x"), absent_reason="no revenue drivers")
    return
  # Capacity in the revenue section is PER QUARTER already (measured: the
  # product sums reproduce finmo Q1 revenue to the cent on 7 of 10 drafts and
  # the other 3 were the keying bug above), so no cadence scaling is applied.
  lob_rev: Dict[str, float] = {}; lob_gp: Dict[str, float] = {}; lob_util: Dict[str, Tuple[float, float]] = {}
  for lob, acc in by_lob.items():
    q_rev, q_gp, uw = acc["_rev"], acc["_gp"], acc["_util_w"]
    lob_rev[lob] = sum(q_rev[1:5]); lob_gp[lob] = sum(q_gp[1:5])
    if len(q_rev) >= 21:
      r1, r5 = sum(q_rev[1:5]), sum(q_rev[17:21])
      if r1 > 0 and r5 > 0:
        lob_util[lob] = (sum(uw[1:5]) / r1, sum(uw[17:21]) / r5)   # revenue-weighted utilisation
  tot = sum(lob_rev.values()); tgp = sum(lob_gp.values())
  # honesty gate: the driver arithmetic must reproduce the model's Year-1 revenue
  if not tot or abs(tot - rev_y1) / rev_y1 > 0.05:
    cat.put("annual.top_lob_name", ABSENT, "text", prov_model("x"),
            absent_reason="driver arithmetic does not reproduce Year-1 revenue (%.0f vs %.0f)" % (tot or 0, rev_y1))
    return
  top = max(lob_rev, key=lob_rev.get)
  cat.put("annual.top_lob_name", top, "text", prov_model("the line with the largest Year-1 revenue"), "Top line")
  cat.put("annual.top_lob_revenue_share_y1", lob_rev[top] / tot, "percent", prov_model("that line's share of Year-1 revenue"), "Top line revenue share")
  cat.put("annual.top_lob_gross_profit_share_y1", (lob_gp[top] / tgp if tgp > 0 else ABSENT), "percent", prov_model("that line's share of Year-1 gross profit"), "Top line GP share")
  cat.put("annual.lob_count", len(lob_rev), "count", prov_model("number of revenue lines"), "Lines of business")
  if top in lob_util:
    cat.put("annual.top_lob_utilization_y1", lob_util[top][0], "percent", prov_model("Year-1 average utilisation on the top line"), "Top line util Y1")
    cat.put("annual.top_lob_utilization_y5", lob_util[top][1], "percent", prov_model("Year-5 average utilisation on the top line"), "Top line util Y5")
  # THE SERIES behind the revenue-by-LOB chart (Nick 2026-08-31): annual
  # revenue per line, only where the mix question exists (>=2 lines) and the
  # same honesty gate above has already passed.
  # THE REVENUE BUILD-UP (Nick 2026-09-01): a single line still has a
  # revenue story. Several lines -> by line; one line with several products
  # -> by product; one product -> one series. Never omitted for "no mix".
  def _annual(qrv):
    return [round(sum(qrv[4 * y - 3:4 * y + 1]), 2) for y in range(1, 6)]
  series, basis = [], None
  if len(lob_rev) >= 2:
    series = [{"lob": lob, "annual": _annual(acc["_rev"])}
              for lob, acc in sorted(by_lob.items(), key=lambda kv: -sum(kv[1]["_rev"][1:5])) if len(acc["_rev"]) >= 21]
    basis = "line of business"
  else:
    prods = []
    for prod, d in by_prod.items():
      cap, price, util = d.get("Capacity"), d.get("Unit Price"), d.get("Utilization")
      if cap and price and util:
        n_ = min(len(cap), len(price), len(util))
        if n_ >= 21:
          prods.append((prod.split("::")[-1] or prod, [cap[i] * price[i] * util[i] for i in range(n_)]))
    if len(prods) >= 2:
      series = [{"lob": name, "annual": _annual(q_)} for name, q_ in sorted(prods, key=lambda p: -sum(p[1][1:5]))]
      basis = "product"
    elif by_lob:
      lob, acc = next(iter(by_lob.items()))
      if len(acc["_rev"]) >= 21:
        series = [{"lob": lob, "annual": _annual(acc["_rev"])}]
        basis = "single line"
  if series:
    cat.put("annual.revenue_by_lob", series, "list",
            prov_model("annual revenue by %s from the model's revenue drivers" % basis), "Revenue build-up")
    cat.put("annual.revenue_by_lob_basis", basis, "text", prov_model("what the revenue build-up is split by"), "Build-up basis")


# ---------------------------------------------------------------------------
# INDUSTRY - baseline lookup (SOURCE), BDS, SBA
# ---------------------------------------------------------------------------
_BENCH = {
  "industry.marketing_pct_benchmark": ("marketing_percent_of_revenue", "percent"),
  "industry.gross_margin_benchmark": ("gross_margin_percent", "percent"),
  "industry.operating_margin_benchmark": ("operating_margin_percent", "percent"),
  "industry.net_margin_benchmark": ("net_income_margin", "percent"),
  "industry.revenue_per_fte_benchmark": ("revenue_per_fte", "money"),
  "industry.payroll_pct_benchmark": ("payroll_percent_of_revenue", "percent"),
  "industry.rent_pct_benchmark": ("rent_percent_of_revenue", "percent"),
  "industry.emp_per_establishment_national": ("employees_per_establishment", "count"),
}


def _baseline(cur, naics6: str, metric_key: str) -> Optional[Dict[str, Any]]:
  for code in (naics6, naics6[:5], naics6[:4], naics6[:3], naics6[:2]):
    cur.execute("SELECT benchmark_target, data_source, source_year, metric_label, naics_level, sample_size, confidence_tier "
                "FROM post_intake_industry_baseline_lookup WHERE active=1 AND naics_code=%s AND metric_key=%s "
                "ORDER BY FIELD(confidence_tier,'high','medium','low','generic_default') LIMIT 1", (code, metric_key))
    r = cur.fetchone()
    if r and r[0] is not None:
      return {"value": _f(r[0]), "source": r[1], "year": r[2], "label": r[3], "level": r[4], "n": r[5], "tier": r[6]}
  return None


def build_industry(cat: FactCatalog, cur, ctx: Dict[str, Any]) -> None:
  n6 = ctx.get("naics6") or ""
  if not n6:
    return
  # --- baseline lookup: the only SOURCE path
  for key, (mk, fmt) in _BENCH.items():
    b = _baseline(cur, n6, mk)
    if b and b["value"] is not None and str(b.get("tier")) != "generic_default":
      cat.put(key, b["value"], fmt, prov_baseline(str(b["source"]), b["year"], str(b["label"] or mk), b["level"], b["n"]), b["label"] or mk)
    else:
      cat.put(key, ABSENT, fmt, prov_model("x"), absent_reason="no non-generic benchmark for %s at any NAICS level" % mk)
  # --- gaps in points (client vs benchmark) for the margins present
  for m in ("gross", "operating", "net"):
    c = cat.get_quiet("annual.%s_margin_y1" % m); b = cat.get_quiet("industry.%s_margin_benchmark" % m)
    if c is not None and b is not None:
      gap = c.value - b.value
      cat.put("annual.%s_margin_gap_pts_y1" % m, abs(gap), "points", prov_model("Year-1 %s margin less the industry benchmark" % m), "%s margin gap" % m)
      cat.put("annual.%s_margin_gap_direction_y1" % m, "above" if gap >= 0 else "below", "text", prov_model("sign of that gap"), "gap direction")
  # --- payroll-per-establishment national (CBP US row). CBP and BDS both
  #     file under NAICS2017, so the concordance candidates apply here exactly
  #     as they do in the market block - without this, a 2022-only code
  #     (Northgate's 513210) recovers its market facts and keeps an empty
  #     industry block.
  cbp_code = None
  scopes = naics_scopes(cur, n6)
  for level, prefixes, lvl_label in scopes:
    clause, params = _like_clause("naics", level, prefixes)
    cur.execute("SELECT SUM(pay_ann), SUM(estab) FROM cbp_2022_raw WHERE LENGTH(naics)=6 AND " + clause, params)
    r = cur.fetchone()
    if r and r[0] and r[1]:
      cbp_code = prefixes[0]
      cat.put("industry.payroll_per_establishment_national", float(r[0]) * 1000.0 / float(r[1]), "money",
              prov_raw("County Business Patterns", "2022", "annual payroll over establishments, all states, %s" % lvl_label), "Payroll/estab national")
      break
  if cbp_code is None:
    cat.put("industry.payroll_per_establishment_national", ABSENT, "money", prov_model("x"), absent_reason="CBP has no rows for NAICS %s at any scope" % n6)
  # --- BDS latest year, widened 4 -> 3 -> sector (BDS files at NAICS-4 under
  #     NAICS 2017; the prefixes carry the translation). Rates aggregate
  #     estab-weighted across the codes a wider scope gathers.
  yr, bds_like, bds_scope = None, None, None
  for level, prefixes, lvl_label in scopes:
    if level == 6:
      continue
    pattern = prefixes[0][:level] + "%"
    cur.execute("SELECT MAX(year) FROM bds_firm_age WHERE vcnaics4 LIKE %s", (pattern,))
    y = cur.fetchone()[0]
    if y:
      # the widened label as naics_scopes phrases it ("the NAICS 3119 industry
      # group", "the ... sector") - the same standard the market labels carry,
      # so S11/S61 read as prose rather than as a bare code (Nick 2026-09-01)
      yr, bds_like, bds_scope = y, pattern, lvl_label
      break
  n4 = bds_scope or ("NAICS %s" % n6[:4])
  if yr:
    cat.put("industry.bds_scope_label", bds_scope, "text", prov_raw("Business Dynamics Statistics", str(yr), "the scope the dynamics are drawn at"), "BDS scope")
    cur.execute("SELECT firm_age_bucket, SUM(firms), SUM(estabs), SUM(emp), "
                "SUM(estabs_entry_rate*estabs)/NULLIF(SUM(estabs),0), SUM(estabs_exit_rate*estabs)/NULLIF(SUM(estabs),0), "
                "SUM(net_job_creation_rate*emp)/NULLIF(SUM(emp),0), SUM(firmdeath_firms) "
                "FROM bds_firm_age WHERE vcnaics4 LIKE %s AND year=%s GROUP BY firm_age_bucket", (bds_like, yr))
    rows = {str(x[0]): x for x in cur.fetchall()}
    tot_emp = sum(_f(x[3]) or 0 for x in rows.values())
    tot_est = sum(_f(x[2]) or 0 for x in rows.values())
    def wavg(idx):
      num = sum((_f(x[idx]) or 0) * (_f(x[2]) or 0) for x in rows.values()); return num / tot_est if tot_est else None
    entry, exit_, njc = wavg(4), wavg(5), None
    num = sum((_f(x[6]) or 0) * (_f(x[3]) or 0) for x in rows.values()); njc = num / tot_emp if tot_emp else None
    V = "%s, %d" % ("Business Dynamics Statistics", int(yr))
    cat.put("industry.bds_year", int(yr), "text", prov_raw("Business Dynamics Statistics", str(yr), "reference year"), "BDS year")
    cat.put("industry.establishment_entry_rate", (entry / 100.0 if entry is not None else ABSENT), "percent", prov_raw("Business Dynamics Statistics", str(yr), "establishment entry rate, %s" % n4), "Entry rate")
    cat.put("industry.establishment_exit_rate", (exit_ / 100.0 if exit_ is not None else ABSENT), "percent", prov_raw("Business Dynamics Statistics", str(yr), "establishment exit rate, %s" % n4), "Exit rate")
    cat.put("industry.net_job_creation_rate", (njc / 100.0 if njc is not None else ABSENT), "percent", prov_raw("Business Dynamics Statistics", str(yr), "net job creation rate, %s" % n4), "Net job creation")
    cat.put("industry.employment_direction", ("growing" if njc is not None and njc >= 0 else ("contracting" if njc is not None else ABSENT)), "text", prov_raw("Business Dynamics Statistics", str(yr), "sign of net job creation"), "Direction")
    y1 = rows.get("b) 1")
    cat.put("industry.first_year_exit_rate", (_f(y1[5]) / 100.0 if y1 and _f(y1[5]) is not None else ABSENT), "percent", prov_raw("Business Dynamics Statistics", str(yr), "exit rate of one-year-old establishments, %s" % n4), "First-year exit rate")
    young = sum(_f(rows[k][3]) or 0 for k in ("a) 0", "b) 1", "c) 2", "d) 3", "e) 4") if k in rows)
    cat.put("industry.young_firm_employment_share", (young / tot_emp if tot_emp else ABSENT), "percent", prov_raw("Business Dynamics Statistics", str(yr), "employment at firms under five years old over sector employment, %s" % n4), "Young-firm employment share")
    # five-year survival: firms aged 5 in year Y over firms aged 0 in year Y-5
    cur.execute("SELECT SUM(firms) FROM bds_firm_age WHERE vcnaics4 LIKE %s AND year=%s AND firm_age_bucket='a) 0'", (bds_like, int(yr) - 5))
    born = cur.fetchone(); five = rows.get("f) 5")
    if born and _f(born[0]) and five and _f(five[1]) is not None:
      cat.put("industry.five_year_survival_rate", _f(five[1]) / _f(born[0]), "percent", prov_raw("Business Dynamics Statistics", "%d-%d" % (int(yr) - 5, int(yr)), "firms aged five in %d over firms born in %d, NAICS %s" % (int(yr), int(yr) - 5, n4)), "Five-year survival")
    else:
      cat.put("industry.five_year_survival_rate", ABSENT, "percent", prov_model("x"), absent_reason="BDS cohort %d missing for NAICS %s" % (int(yr) - 5, n4))
  else:
    for k in ("industry.establishment_entry_rate", "industry.five_year_survival_rate", "industry.net_job_creation_rate"):
      cat.put(k, ABSENT, "percent", prov_model("x"), absent_reason="BDS has no rows for NAICS %s at any scope" % n6)
  # firm size share under 10 (national, BDS firm_size latest year)
  ys = None
  if bds_like:
    cur.execute("SELECT MAX(year) FROM bds_firm_size WHERE vcnaics4 LIKE %s", (bds_like,))
    ys = cur.fetchone()[0]
  if ys:
    cur.execute("SELECT firm_size_bucket, SUM(firms) FROM bds_firm_size WHERE vcnaics4 LIKE %s AND year=%s GROUP BY firm_size_bucket", (bds_like, ys))
    fs = {str(a): (_f(b) or 0) for a, b in cur.fetchall()}
    tot = sum(fs.values())
    under10 = fs.get("a) 1 to 4", 0) + fs.get("b) 5 to 9", 0)
    cat.put("industry.share_firms_under_10_employees", (under10 / tot if tot else ABSENT), "percent", prov_raw("Business Dynamics Statistics", str(ys), "firms with 1-9 employees over all firms, %s, national" % n4), "Share of firms under 10 employees")
  # --- SBA 7(a) comparables
  st = (ctx.get("geo") or {}).get("state_abbr")
  scope, rows = None, []
  for label, sql, params in (
    ("%s businesses in %s" % (n6, st), "NAICSCode=%s AND BorrState=%s", (n6, st)),
    ("%s businesses nationally" % n6, "NAICSCode=%s", (n6,)),
    ("NAICS-%s businesses nationally" % n6[:4], "LEFT(NAICSCode,4)=%s", (n6[:4],)),
    ("NAICS-%s businesses nationally" % n6[:3], "LEFT(NAICSCode,3)=%s", (n6[:3],)),
    ("NAICS-%s businesses nationally" % n6[:2], "LEFT(NAICSCode,2)=%s", (n6[:2],)),
  ):
    if params and any(p is None for p in params):
      continue
    cur.execute("SELECT GrossApproval, InitialInterestRate, TermInMonths, LoanStatus FROM sba_loan_7a_raw WHERE %s AND LoanStatus<>'CANCLD'" % sql, params)
    rows = cur.fetchall()
    if len(rows) >= 10:
      scope = label; break
  if scope and rows:
    amts = [_f(r[0]) for r in rows if _f(r[0])]
    rates = [_f(r[1]) for r in rows if _f(r[1]) and _f(r[1]) > 0]
    terms = [_f(r[2]) for r in rows if _f(r[2]) and _f(r[2]) > 0]
    cho = sum(1 for r in rows if str(r[3]) == "CHGOFF")
    B = lambda what: prov_raw("SBA 7(a) loan data", "FY2020-FY2025", what + " (%s)" % scope)
    cat.put("industry.sba_scope_label", scope.replace(n6 + " businesses", (cat.get_quiet("entity.naics_title").value if cat.get_quiet("entity.naics_title") else "comparable") + " businesses"), "text", B("comparable-loan scope"), "SBA scope")
    cat.put("industry.sba_loan_count", len(rows), "count", B("approved loans, cancellations excluded"), "SBA loan count")
    # even the window start is a fact, not a template literal (rule 17 at the template level)
    cat.put("industry.sba_window_start", "fiscal 2020", "text", B("first fiscal year in the loaded 7(a) data"), "SBA window start")
    cat.put("industry.sba_window_label", "fiscal 2020 through fiscal 2025", "text", B("the fiscal-year window of the loaded 7(a) data"), "SBA window")
    cat.put("industry.sba_median_amount", _median(amts) or ABSENT, "money", B("median gross approval"), "SBA median amount")
    # THE DISTRIBUTION behind the percentile strip (Nick 2026-08-31): deciles
    # of the same in-scope gross approvals the median came from.
    if len(amts) >= 10:
      xs = sorted(amts)
      dec = [{"pct": p, "amount": round(xs[min(len(xs) - 1, int(len(xs) * p / 100.0))], 2)}
             for p in (10, 25, 50, 75, 90)]
      cat.put("industry.sba_amount_distribution", dec, "list",
              B("decile spread of comparable gross approvals"), "SBA amount distribution")
    cat.put("industry.sba_median_rate", (_median(rates) / 100.0 if rates else ABSENT), "percent", B("median initial interest rate"), "SBA median rate")
    cat.put("industry.sba_median_term_months", (_median(terms) if terms else ABSENT), "months", B("median term"), "SBA median term")
    cat.put("industry.sba_chargeoff_rate", cho / len(rows), "percent", B("charged-off loans over approved loans"), "SBA charge-off rate")
    ask = ctx.get("funding_request")
    pr = _percentile_rank(amts, ask) if ask else None
    cat.put("industry.sba_ask_percentile", (_ordinal(pr) if pr is not None else ABSENT), "text", B("percentile of the request among comparable gross approvals"), "Ask percentile",
            absent_reason="no funding request in the projections")
  else:
    for k in ("industry.sba_loan_count", "industry.sba_median_amount", "industry.sba_chargeoff_rate", "industry.sba_ask_percentile"):
      cat.put(k, ABSENT, "count", prov_model("x"), absent_reason="fewer than 10 SBA loans at any scope for NAICS %s" % n6)


def _ordinal(n: float) -> str:
  n = int(n)
  return "%d%s" % (n, "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


# ---------------------------------------------------------------------------
# MARKET - CBP state, ACS trade area, OEWS
# ---------------------------------------------------------------------------
def _cbp_naics_candidates(cur, n6):
  """The client's code, then its NAICS-2017 translation(s) when the code does
  not exist in CBP at all. CBP 2022 files under NAICS2017: Northgate's 513210
  (a 2022 code) is 511210 there - same business, different number. The
  concordance table may not be loaded yet; candidates degrade gracefully."""
  out = [n6]
  try:
    cur.execute("SELECT DISTINCT naics_2017 FROM naics_2022_to_2017_concordance WHERE naics_2022=%s", (n6,))
    out.extend(str(r[0]) for r in cur.fetchall() if r[0] and str(r[0]) != n6)
  except Exception:
    pass
  return out


SECTOR_NAMES = {
  "11": "agriculture, forestry, fishing and hunting", "21": "mining, quarrying, and oil and gas extraction",
  "22": "utilities", "23": "construction", "31": "manufacturing", "32": "manufacturing", "33": "manufacturing",
  "42": "wholesale trade", "44": "retail trade", "45": "retail trade", "48": "transportation and warehousing",
  "49": "transportation and warehousing", "51": "information", "52": "finance and insurance",
  "53": "real estate and rental and leasing", "54": "professional, scientific and technical services",
  "55": "management of companies", "56": "administrative, support and waste management services",
  "61": "educational services", "62": "health care and social assistance",
  "71": "arts, entertainment and recreation", "72": "accommodation and food services",
  "81": "other services", "92": "public administration",
}


def naics_scopes(cur, n6: str, title: Optional[str] = None) -> List[Tuple[int, List[str], str]]:
  """THE WIDENING RULE (Nick, 2026-09-01): every builder that touches CBP, BDS
  or the baseline walks 6 -> 4 -> 3 -> sector until the data answers, and the
  SCOPE LABEL TRAVELS WITH THE FACT so the prose says what it is describing -
  the same law as county-vs-state geography. Returns (level, prefixes, label)
  in widening order; prefixes carry the 2022->2017 translations."""
  n6 = str(n6 or "")
  cands = _cbp_naics_candidates(cur, n6) if len(n6) >= 2 else [n6]
  sector = SECTOR_NAMES.get(n6[:2])

  # NEVER PRINT A NAICS CODE (Nick 2026-09-02): the scope label is the
  # industry named in WORDS at the level the data was actually drawn at -
  # naics_master carries titles at every level. The coded fallback survives
  # only for a code the master does not know.
  def _level_title(code: str) -> str:
    try:
      cur.execute("SELECT naics_title FROM naics_master WHERE naics_code=%s LIMIT 1", (code,))
      r = cur.fetchone()
      return str(r[0]).strip().lower() if r and r[0] else ""
    except Exception:
      return ""

  # Nick 2026-09-02, second ruling on this label: the NAICS-4 TITLE is a code
  # wearing words ("services to buildings and dwellings" - no consultant
  # writes it). The label anchors on the client's own recognizable trade and
  # says honestly that the data is drawn wider.
  base = str(title or "").strip().lower() or _level_title(n6)
  return [
    (6, list(cands), title or ("NAICS %s" % n6)),
    (4, sorted({c[:4] for c in cands}),
     ("the trade group that includes %s" % base) if base
     else "the NAICS %s industry group" % n6[:4]),
    (3, sorted({c[:3] for c in cands}),
     ("the broader trade group that includes %s" % base) if base
     else "the NAICS %s subsector" % n6[:3]),
    (2, sorted({c[:2] for c in cands}),
     ("the %s sector" % sector) if sector else "the NAICS %s sector" % n6[:2]),
  ]


def _like_clause(col: str, level: int, prefixes: List[str]) -> Tuple[str, List[str]]:
  if level == 6:
    return "(" + " OR ".join(["%s=%%s" % col] * len(prefixes)) + ")", list(prefixes)
  return "(" + " OR ".join(["%s LIKE %%s" % col] * len(prefixes)) + ")", [p + "%" for p in prefixes]


def build_market(cat: FactCatalog, cur, draft: Dict[str, Any], ctx: Dict[str, Any]) -> None:
  geo = ctx.get("geo") or {}; n6 = ctx.get("naics6") or ""
  sf, cf = geo.get("state_fips"), geo.get("county_fips")
  if not sf:
    return
  # --- state population & households (ACS summed over the state's ZCTAs)
  cur.execute("SELECT SUM(a.B01001_001E), SUM(a.B11001_001E), SUM(a.B19013_001E*a.B11001_001E)/NULLIF(SUM(a.B11001_001E),0) "
              "FROM acs_zip_2022_part1 a JOIN (SELECT DISTINCT zcta FROM zip_county_crosswalk WHERE state_fips=%s) x ON x.zcta=a.zcta", (sf,))
  sp, sh, s_inc = [(_f(v)) for v in cur.fetchone()]

  # --- trade area (county of the business ZIP), computed FIRST because the
  #     competition block needs the county denominators and the area label
  pop = hh = med = None
  rows = []
  rows2 = []
  def wsum(rs, col):
    return sum((_f(r.get(col)) or 0) * ((_f(r.get("zpop_pct")) or 0) / 100.0) for r in rs)
  if cf:
    cur.execute("SELECT a.*, x.zpop_pct FROM acs_zip_2022_part1 a JOIN zip_county_crosswalk x ON x.zcta=a.zcta WHERE x.state_fips=%s AND x.county_fips=%s", (sf, cf))
    cols = [d[0] for d in cur.description]; rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.execute("SELECT b.*, x.zpop_pct FROM acs_zip_2022_part2 b JOIN zip_county_crosswalk x ON x.zcta=b.zcta WHERE x.state_fips=%s AND x.county_fips=%s", (sf, cf))
    cols2 = [d[0] for d in cur.description]; rows2 = [dict(zip(cols2, r)) for r in cur.fetchall()]
    pop, hh = wsum(rows, "B01001_001E"), wsum(rows, "B11001_001E")
    inc_num = sum((_f(r.get("B19013_001E")) or 0) * (_f(r.get("B11001_001E")) or 0) * ((_f(r.get("zpop_pct")) or 0) / 100.0) for r in rows)
    med = inc_num / hh if hh else None
  area_label = ("the %s area" % geo["pref_city"]) if geo.get("pref_city") else None

  # --- COMPETITION BLOCK: county first, state fallback. THE GEOGRAPHY
  #     TRAVELS WITH THE FACT (Nick, 2026-08-30): every count below is scoped
  #     by market.competition_geo_label, put by THIS code path and no other,
  #     and the sentences that use these keys REQUIRE the label - a bare
  #     count with no idea what it counts cannot render.
  #     "Three coffee manufacturers operate in the Saint Paul area" and
  #     "Minnesota has 26" are different claims; a silent fallback would make
  #     the plan say something false about the trade area.
  hit = None  # (est, emp, pay, geo_label, scope_text, denom_pop, denom_hh, industry_label)
  # THE WIDENING RULE: NAICS-6 at the county, then the state; then the
  # industry group, subsector and sector the same way. Industry specificity
  # outranks geography; both labels travel with every count.
  nt = cat.get_quiet("entity.naics_title")
  for level, prefixes, lvl_label in naics_scopes(cur, n6, nt.value if nt else None):
    clause, params = _like_clause("naics", level, prefixes)
    if cf and area_label and pop:
      cur.execute("SELECT SUM(estab), SUM(emp), SUM(pay_ann) FROM cbp_2022_raw_county "
                  "WHERE state_fips=%s AND county_fips=%s AND LENGTH(naics)=6 AND " + clause, [sf, cf] + params)
      r = cur.fetchone()
      if r and _f(r[0]):
        hit = (_f(r[0]), _f(r[1]), _f(r[2]), area_label,
               "the county containing ZIP %s, %s" % (geo.get("zip"), lvl_label), pop, hh, lvl_label)
        break
    cur.execute("SELECT SUM(estab), SUM(emp), SUM(pay_ann) FROM cbp_2022_raw "
                "WHERE state_fips=%s AND LENGTH(naics)=6 AND " + clause, [sf] + params)
    r = cur.fetchone()
    if r and _f(r[0]):
      hit = (_f(r[0]), _f(r[1]), _f(r[2]), str(geo.get("state_name")),
             "%s statewide, %s" % (geo.get("state_name"), lvl_label), sp, sh, lvl_label)
      break
  if hit:
    est, emp, pay, label, scope, d_pop, d_hh, ind_label = hit
    C = lambda what: prov_raw("County Business Patterns", "2022", what + " (%s)" % scope)
    cat.put("market.competition_geo_label", label, "text", C("the geography every establishment count in this plan is scoped to"), "Competition geography")
    cat.put("market.industry_scope_label", ind_label, "text", C("the industry scope every establishment count in this plan is drawn at"), "Industry scope")
    cat.put("market.establishments", est, "count", C("establishments"), "Establishments")
    cat.put("market.residents_per_establishment", (d_pop / est if d_pop else ABSENT), "count", C("residents over establishments, same geography"), "Residents per establishment")
    cat.put("market.client_share_of_establishments", 1.0 / est, "percent", C("one establishment over the count"), "Client share")
    cat.put("market.emp_per_establishment", (emp / est if emp else ABSENT), "ratio", C("employment over establishments"), "Emp per estab")
    cat.put("market.payroll_per_establishment", (pay * 1000.0 / est if pay else ABSENT), "money", C("annual payroll over establishments"), "Payroll per estab")
    cat.put("market.households_per_establishment", (d_hh / est if d_hh else ABSENT), "count", C("households over establishments, same geography"), "Households per estab")
  else:
    for k in ("market.competition_geo_label", "market.industry_scope_label", "market.establishments",
              "market.residents_per_establishment", "market.client_share_of_establishments",
              "market.emp_per_establishment", "market.payroll_per_establishment", "market.households_per_establishment"):
      cat.put(k, ABSENT, "count", prov_model("x"), absent_reason="no CBP rows for NAICS %s at any scope, county or state" % n6)

  # --- B2B target establishments statewide (the sentence names the scope)
  b2b = ctx.get("b2b_naics") or []
  if b2b:
    cur.execute("SELECT SUM(estab) FROM cbp_2022_raw WHERE state_fips=%s AND naics IN (%s)" % ("%s", ",".join(["%s"] * len(b2b))), [sf] + b2b)
    v = _f(cur.fetchone()[0])
    cat.put("market.b2b_target_establishments_state", (v if v else ABSENT), "count", prov_raw("County Business Patterns", "2022", "establishments in the client's target industries, statewide"), "B2B target estabs",
            absent_reason="CBP has no rows for the target NAICS codes")
  else:
    cat.put("market.b2b_target_establishments_state", ABSENT, "count", prov_model("x"), absent_reason="not a B2B business")

  # --- trade-area facts (ACS)
  if cf and rows:
    A = lambda what: prov_raw("American Community Survey 5-year", "2022", what + " for the county containing ZIP %s, ZCTA population-weighted" % geo.get("zip"))
    cat.put("market.trade_area_name", area_label or ABSENT, "text", A("trade area label"), "Trade area")
    cat.put("market.trade_area_population", (pop if pop else ABSENT), "count", A("population"), "Trade-area population")
    cat.put("market.trade_area_households", (hh if hh else ABSENT), "count", A("households"), "Trade-area households")
    cat.put("market.trade_area_median_hh_income", (med if med else ABSENT), "money", A("household-weighted median household income"), "Trade-area median income")
    if med and s_inc:
      cat.put("market.trade_area_income_vs_state", "above" if med >= s_inc else "below", "text", A("trade-area median against the state median"), "Income vs state")
    adults = wsum(rows, "B15003_017E") + wsum(rows, "B15003_022E") + wsum(rows, "B15003_023E") + wsum(rows, "B15003_025E")
    bach = wsum(rows, "B15003_022E") + wsum(rows, "B15003_023E") + wsum(rows, "B15003_025E")
    cat.put("market.trade_area_bachelors_or_higher_share", (bach / adults if adults else ABSENT), "percent",
            A("bachelor's, master's and doctoral holders over the education attainment counts held"), "Bachelor's or higher")
    hv_num = sum((_f(r.get("B25077_001E")) or 0) * (_f(r.get("B25001_001E")) or 0) * ((_f(r.get("zpop_pct")) or 0) / 100.0) for r in rows)
    hu = wsum(rows, "B25001_001E")
    cat.put("market.trade_area_median_home_value", (hv_num / hu if hu else ABSENT), "money", A("housing-unit-weighted median home value"), "Median home value")
    floor = ctx.get("income_floor")
    if floor and hh:
      share = 0.0; lo = 0.0
      for col, edge in zip(_INC_COLS, _INC_EDGES):
        hi = edge * 1000.0; nn = wsum(rows, col)
        if hi <= floor:
          pass
        elif lo >= floor:
          share += nn
        else:
          share += nn * ((hi - floor) / (hi - lo)) if hi < 10 ** 11 else nn
        lo = hi
      cat.put("market.share_households_in_target_income_band", share / hh, "percent", A("households with income at or above the stated target floor, partial brackets prorated"), "Share in target income band")
    else:
      cat.put("market.share_households_in_target_income_band", ABSENT, "percent", prov_model("x"), absent_reason="no consumer income target stated")
    band = ctx.get("age_band")
    if band and pop and rows2:
      amin, amax = band; inb = 0.0
      for (lo_a, hi_a), (mc, fc) in zip(_AGE_BANDS, _AGE_COLS):
        nn = wsum(rows2, mc) + wsum(rows2, fc)
        ov = max(0.0, min(hi_a, amax) - max(lo_a, amin) + 1)
        width = hi_a - lo_a + 1
        inb += nn * min(1.0, ov / width) if ov > 0 else 0.0
      cat.put("market.share_population_in_target_age_band", inb / pop, "percent", A("population within the stated target age range, partial bands prorated"), "Share in target age band")
    else:
      cat.put("market.share_population_in_target_age_band", ABSENT, "percent", prov_model("x"), absent_reason="no consumer age target stated")

  # --- OEWS: metro by title match, else state cross-industry
  ph = _j(draft.get("payroll_headcount"))
  rows_q1 = [r for r in (ph.get("rows") or []) if isinstance(r, dict) and int(_f(r.get("quarter_index")) or 0) == 1]
  titles = []
  for r in rows_q1:
    t = str(r.get("oews_occ_title") or r.get("oews_matched_title") or "").strip()
    if t and _f(r.get("annual_wage")):
      titles.append((t, _f(r.get("annual_wage")), str(r.get("position_title") or t), _f(r.get("ending_fte")) or 0))
  if not titles:
    cat.put("market.wage_check_title", ABSENT, "text", prov_model("x"), absent_reason="no OEWS-titled roles on the payroll schedule")
    cat.put("market.top_occupation_title", ABSENT, "text", prov_model("x"), absent_reason="no OEWS-titled roles on the payroll schedule")
    return
  titles.sort(key=lambda x: -x[3])
  area_lbl, area_rows = None, {}
  city, st = geo.get("pref_city"), geo.get("state_abbr")
  if city and st:
    cur.execute("SELECT occ_title, a_median, loc_quotient, area_title FROM oews_state_wages WHERE area_type='4' AND i_group='cross-industry' "
                "AND area_title LIKE %s AND (area_title LIKE %s OR area_title LIKE %s)", ("%" + city + "%", "%, " + st + "%", "%-" + st + "%"))
    for t, m, lq, at in cur.fetchall():
      area_rows[str(t)] = (_f(m), _f(lq)); area_lbl = "%s metro" % str(at).split(",")[0].split("-")[0]
  if not area_rows and st:
    cur.execute("SELECT occ_title, a_median, loc_quotient FROM oews_state_wages WHERE area_type='2' AND prim_state=%s AND naics='000000' AND i_group='cross-industry'", (st,))
    for t, m, lq in cur.fetchall():
      area_rows[str(t)] = (_f(m), _f(lq))
    area_lbl = "%s statewide" % geo.get("state_name")
  if not area_rows:
    cat.put("market.wage_check_title", ABSENT, "text", prov_model("x"), absent_reason="no OEWS area rows for this geography")
    return
  O = lambda what: prov_raw("BLS Occupational Employment and Wage Statistics", "latest loaded release", what + " (%s)" % area_lbl)
  done = False
  for t, wage, pos, fte in titles:
    m, lq = area_rows.get(t, (None, None))
    if m and not done:
      cat.put("market.wage_check_title", pos, "text", O("role compared"), "Wage check role")
      cat.put("market.wage_check_client_wage", wage, "money", prov_model("the annual wage carried for that role"), "Client wage")
      cat.put("market.wage_check_area_median", m, "money", O("median annual wage for %s" % t), "Area median")
      cat.put("market.wage_check_direction", "above" if wage >= m else "below", "text", O("client wage against the area median"), "Direction")
      cat.put("market.wage_check_area_label", area_lbl, "text", O("area"), "Area label")
      done = True
    if lq and not cat.has("market.top_occupation_loc_quotient"):
      cat.put("market.top_occupation_title", t, "text", O("the largest occupation on the schedule"), "Top occupation")
      cat.put("market.top_occupation_loc_quotient", lq, "multiple", O("location quotient - local employment concentration relative to national, for %s" % t), "Location quotient")
  if not done:
    cat.put("market.wage_check_title", ABSENT, "text", prov_model("x"), absent_reason="no payroll title matched an OEWS row in %s" % area_lbl)
  if not cat.has("market.top_occupation_loc_quotient"):
    cat.put("market.top_occupation_loc_quotient", ABSENT, "multiple", prov_model("x"), absent_reason="no location quotient for any schedule title in %s" % area_lbl)


# ---------------------------------------------------------------------------
# SENSITIVITY (depth item 1): the quantified demand_response + the break-even
# variants. These are OUR OWN judged analysis - grounded to the model.
# ---------------------------------------------------------------------------
def build_sensitivity(cat: FactCatalog, draft: Dict[str, Any]) -> None:
  fin = _j(draft.get("financials_json"))
  coh = (fin.get("_coherence") or {})
  P_ = prov_model
  pr = (coh.get("demand_response") or {}).get("price_response") or {}
  band = pr.get("retained_fraction_band") or []
  if len(band) == 2 and _f(band[0]) is not None:
    cat.put("annual.price_retained_low", float(band[0]), "percent",
            P_("the demand judgment's retained-volume band under top-of-range pricing"), "Price band low")
    cat.put("annual.price_retained_high", float(band[1]), "percent",
            P_("the demand judgment's retained-volume band under top-of-range pricing"), "Price band high")
  else:
    for k in ("annual.price_retained_low", "annual.price_retained_high"):
      cat.put(k, ABSENT, "percent", P_("x"), absent_reason="no quantified price response in the coherence record")
  mr = (coh.get("demand_response") or {}).get("marketing_response") or {}
  mband = mr.get("demand_at_reduced_spend_band") or []
  if len(mband) == 2 and _f(mband[0]) is not None:
    cat.put("annual.marketing_demand_low", float(mband[0]), "percent",
            P_("the demand judgment's demand-at-reduced-spend band"), "Marketing band low")
    cat.put("annual.marketing_demand_high", float(mband[1]), "percent",
            P_("the demand judgment's demand-at-reduced-spend band"), "Marketing band high")
  else:
    why = ("demand judgment withheld - thin evidence" if (coh.get("demand_response") or {}).get("withheld")
           else ("no coherence record on this draft" if not coh
                 else "no quantified marketing response in the coherence record"))
    for k in ("annual.marketing_demand_low", "annual.marketing_demand_high"):
      cat.put(k, ABSENT, "percent", P_("x"), absent_reason=why)
  vh = _f(((coh.get("demand_response") or {}).get("volume_headroom") or {}).get("supported_units_max"))
  cat.put("annual.volume_headroom_units", (vh if vh else ABSENT), "count",
          P_("maximum units the modelled reachable market supports"), "Volume headroom",
          absent_reason="no volume headroom in the coherence record")
  be = ((_j(draft.get("finmo_json")) or {}).get("break_even") or {}).get("summary") or {}
  y1 = be.get("y1_annualized") or {}
  cat.put("annual.break_even_revenue_y1", _f(y1.get("be_revenue")) or ABSENT, "money",
          P_("annualised Year-1 break-even revenue, accounting basis"), "BE revenue Y1",
          absent_reason="no annualised break-even in the model")
  cbe = _f(y1.get("cash_be_revenue")) or (_f((be.get("q1") or {}).get("cash_be_revenue")) or None)
  if cbe:
    cbe = cbe * (4.0 if cbe and y1.get("be_revenue") and cbe < _f(y1.get("be_revenue")) / 2 else 1.0)
  cat.put("annual.cash_break_even_revenue_y1", (cbe if cbe else ABSENT), "money",
          P_("Year-1 break-even revenue on a cash basis"), "Cash BE Y1",
          absent_reason="no cash break-even in the model")
  mos = _f((be.get("q1") or {}).get("margin_of_safety"))
  cat.put("annual.margin_of_safety", (mos if mos is not None else ABSENT), "percent",
          P_("planned revenue over break-even revenue, less one"), "Margin of safety",
          absent_reason="no margin of safety in the model")


# ---------------------------------------------------------------------------
# ECONOMY (Nick's ruling 1): FRED macro + the sourced Treasury rate. FRED rows
# are a raw table -> INFERRED per ruling E; the Treasury constant carries a
# full citation and, like the promoted valuation, is GROUNDED with a SOURCE -
# the one deliberate widening of ruling E, made under ruling 2's authority.
# ---------------------------------------------------------------------------
def build_economy(cat: FactCatalog, cur) -> None:
  try:
    cur.execute("SELECT date, inflation_rate, gdp, consumer_spending FROM fred_macro_quarterly ORDER BY date DESC LIMIT 5")
    rows = cur.fetchall()
  except Exception:
    rows = []
  if rows:
    latest = rows[0]
    d = latest[0]
    label = "the %s quarter of %d" % (("first", "second", "third", "fourth")[(d.month - 1) // 3], d.year)
    F = lambda what: prov_raw("FRED macroeconomic series", "quarterly, through %s" % d.isoformat(), what)
    cat.put("economy.period_label", label, "text", F("latest quarter held"), "Data period")
    cat.put("economy.inflation_rate", (_f(latest[1]) or 0) / 100.0, "percent", F("CPI year-over-year inflation"), "Inflation")
    if len(rows) == 5 and _f(rows[4][2]):
      cat.put("economy.gdp_growth_yoy", float(latest[2]) / float(rows[4][2]) - 1.0, "percent",
              F("nominal GDP, year over year"), "GDP growth")
      cat.put("economy.consumer_spending_growth_yoy", float(latest[3]) / float(rows[4][3]) - 1.0, "percent",
              F("personal consumption, year over year"), "Consumer spending growth")
  else:
    cat.put("economy.period_label", ABSENT, "text", prov_model("x"), absent_reason="fred_macro_quarterly empty")
  try:
    cur.execute("SELECT value_default, source_citation, source_as_of FROM valuation_reference_constants "
                "WHERE constant_key='risk_free_rate' AND active=1 LIMIT 1")
    r = cur.fetchone()
  except Exception:
    r = None
  # THE RATE SERIES (fred_series_quarterly, loaded 2026-08-31). Nick's ruling
  # on the constant-vs-live pair: the PROSE cites the LIVE series - these
  # sentences describe today's market, and the loader keeps them current -
  # while the constants table stays the DCF's as-of-build assumption. The
  # treasury guard (scripts/writing_phase_treasury_guard.py) caps the gap so
  # the two can never materially disagree in one document.
  latest: Dict[str, tuple] = {}
  ppi_yoy = None
  try:
    cur.execute("SELECT series_id, date, value FROM fred_series_quarterly "
                "WHERE (series_id, date) IN (SELECT series_id, MAX(date) FROM "
                "fred_series_quarterly GROUP BY series_id)")
    for sid, d2, v in cur.fetchall():
      latest[str(sid)] = (d2, _f(v))
    if "PPIACO" in latest:
      cur.execute("SELECT value FROM fred_series_quarterly WHERE series_id='PPIACO' "
                  "AND date=DATE_SUB(%s, INTERVAL 1 YEAR)", (latest["PPIACO"][0],))
      p = cur.fetchone()
      prior = _f(p[0]) if p else None
      now = latest["PPIACO"][1]
      if prior and now:
        ppi_yoy = now / prior - 1.0
  except Exception:
    latest = {}

  def _rate(sid: str):
    d2, v = latest.get(sid, (None, None))
    return (d2, v / 100.0) if v is not None else (None, None)

  d10, ten_live = _rate("DGS10")
  if ten_live is not None:
    lbl = "the %s quarter of %d" % (("first", "second", "third", "fourth")[(d10.month - 1) // 3], d10.year)
    RP = lambda what: prov_raw("FRED rate series", "quarterly average, through %s" % d10.isoformat(), what)
    cat.put("economy.ten_year_treasury", ten_live, "percent", RP("ten-year Treasury constant maturity"), "Ten-year Treasury")
    cat.put("economy.treasury_as_of", lbl, "text", RP("latest quarter held"), "Treasury as-of")
    cat.put("economy.rates_period_label", lbl, "text", RP("latest quarter held"), "Rates period")
    _, two = _rate("DGS2")
    if two is not None:
      cat.put("economy.two_year_treasury", two, "percent", RP("two-year Treasury constant maturity"), "Two-year Treasury")
      spread = ten_live - two
      shape = "positively sloped" if spread > 0.001 else ("inverted" if spread < -0.001 else "essentially flat")
      cat.put("economy.yield_curve_shape", shape, "text", RP("ten-year minus two-year Treasury"), "Yield curve")
    _, ff = _rate("FEDFUNDS")
    if ff is not None:
      cat.put("economy.fed_funds_rate", ff, "percent", RP("effective federal funds rate"), "Policy rate")
    _, un = _rate("UNRATE")
    if un is not None:
      cat.put("economy.unemployment_rate", un, "percent", RP("civilian unemployment rate"), "Unemployment")
    if ppi_yoy is not None:
      cat.put("economy.ppi_change_yoy", ppi_yoy, "percent", RP("producer price index, all commodities, year over year"), "Producer prices")
  elif r and _f(r[0]) is not None:
    # series table empty: fall back to the DCF constant rather than silence
    prov = Provenance(RR.CLASS_GROUNDED, RR.NOTE_KIND_SOURCE,
                      "%s, as of %s." % (str(r[1] or "FRED DGS10"), str(r[2] or "")),
                      source_name=str(r[1] or "FRED DGS10")[:120], source_vintage=str(r[2] or "undated"))
    cat.put("economy.ten_year_treasury", float(r[0]), "percent", prov, "Ten-year Treasury")
    cat.put("economy.treasury_as_of", str(r[2] or ABSENT), "text", prov, "Treasury as-of")
  else:
    cat.put("economy.ten_year_treasury", ABSENT, "percent", prov_model("x"), absent_reason="no rate series and no risk-free constant loaded")


# ---------------------------------------------------------------------------
# VALUATION PROMOTED (Nick's ruling 2): the Python twin of the Valuation
# sheet. The divergence guard (scripts/writing_phase_valuation_guard.py) holds
# fact and workbook to the same number on the same run.
# ---------------------------------------------------------------------------
def build_valuation_facts(cat: FactCatalog, cur, draft: Dict[str, Any]) -> None:
  try:
    val = V.compute_valuation(cur, draft)
  except Exception as exc:  # noqa: BLE001
    cat.put("entity.equity_value_dcf", ABSENT, "money", prov_model("x"),
            absent_reason="valuation computation failed: %s" % str(exc)[:120])
    return
  eq = _f(val.get("equity_value"))
  if eq is not None and eq > 0:
    cat.put("entity.equity_value_dcf", eq, "money",
            prov_model("the discounted-cash-flow prepared in the accompanying financial model's Valuation sheet, same run, same assumptions"),
            "Equity value (DCF)")
  else:
    reason = ("terminal spread below the structural floor - the model itself declines to price the perpetuity"
              if val and not val.get("spread_ok") else "model lacks the quarters the valuation needs")
    cat.put("entity.equity_value_dcf", ABSENT, "money", prov_model("x"), absent_reason=reason)
  xm = val.get("exit_multiple") or {}
  if _f(xm.get("value")):
    prov = Provenance(RR.CLASS_GROUNDED, RR.NOTE_KIND_SOURCE,
                      "%s, as of %s%s." % (str(xm.get("citation") or xm.get("source") or "industry transaction data"),
                                           str(xm.get("as_of") or "undated"),
                                           (", NAICS %s" % xm["scope"]) if xm.get("scope") else ""),
                      source_name=str(xm.get("citation") or xm.get("source") or "industry transaction data")[:120],
                      source_vintage=str(xm.get("as_of") or "undated"))
    cat.put("entity.exit_multiple_sde", float(xm["value"]), "multiple", prov, "Exit multiple (SDE)")
    v_mult = _f(val.get("value_at_exit_multiple"))
    cat.put("entity.value_at_exit_multiple", (v_mult if v_mult and v_mult > 0 else ABSENT), "money",
            prov_model("mature-year seller's discretionary earnings at the industry exit multiple"),
            "Value at exit multiple", absent_reason="no positive mature-year SDE")
  else:
    cat.put("entity.exit_multiple_sde", ABSENT, "multiple", prov_model("x"), absent_reason="no exit multiple constant")


# ---------------------------------------------------------------------------
# THE BDS HISTORY (depth item 4): the 46-year series behind the new chart.
# ---------------------------------------------------------------------------
def build_industry_history(cat: FactCatalog, cur, ctx: Dict[str, Any]) -> None:
  n6 = str(ctx.get("naics6") or "")
  if len(n6) < 4:
    return
  # BDS files under NAICS 2017: Northgate's 513210 (a 2022 code) is 511210
  # there. Same translation the CBP path uses - caught 2026-09-01 when the
  # audit showed BDS "missing" for a software publisher with 552 rows.
  rows, scope_label = [], None
  for level, prefixes, lvl_label in naics_scopes(cur, n6):
    if level == 6:
      continue
    cur.execute("SELECT year, SUM(estabs) FROM bds_firm_age WHERE vcnaics4 LIKE %s GROUP BY year ORDER BY year",
                (prefixes[0][:level] + "%",))
    rows = [(int(a), float(b)) for a, b in cur.fetchall() if b is not None]
    if len(rows) >= 10:
      scope_label = ("NAICS %s" % prefixes[0][:4]) if level == 4 else lvl_label
      break
  n4 = n6[:4]
  if len(rows) >= 10:
    span = "%d through %d" % (rows[0][0], rows[-1][0])
    prov = prov_raw("Business Dynamics Statistics", span, "establishments per year, %s" % scope_label)
    cat.put("industry.establishments_history_span", span, "text", prov, "History span")
    cat.put("industry.establishments_history_scope", scope_label, "text", prov, "History scope")
    cat.put("industry.establishments_history", rows, "list", prov, "Establishments by year")
  else:
    for k in ("industry.establishments_history_span", "industry.establishments_history"):
      cat.put(k, ABSENT, "text", prov_model("x"),
              absent_reason="BDS has no year series for NAICS-4 %s (BDS excludes agriculture)" % n4
              if n4.startswith("11") else "BDS has no year series for NAICS-4 %s" % n4)


# ---------------------------------------------------------------------------
# THE CHART SERIES (Nick's ruling, 2026-08-31 evening). Same discipline as
# the scalar facts: a series that cannot be built is ABSENT with its reason,
# its chart is silently omitted, and the figures renumber. Every series
# carries provenance.
# ---------------------------------------------------------------------------
def build_chart_series(cat: FactCatalog, draft: Dict[str, Any]) -> None:
  finmo = _j(draft.get("finmo_json"))
  q = _quarters(finmo)
  P = prov_model
  if len([i for i in q if 1 <= i <= 20]) < 20:
    for k, u in (("annual.revenue_series", "list"), ("annual.net_income_series", "list"),
                 ("annual.margin_structure_series", "list"),
                 ("quarterly.cash_balance_series", "list"),
                 ("quarterly.revenue_series", "list"), ("quarterly.total_cost_series", "list")):
      cat.put(k, ABSENT, u, P("x"), absent_reason="finmo_json lacks 20 quarters")
  else:
    rev = [_ysum(q, "revenue", y) for y in range(1, 6)]
    ni = [_ysum(q, "net_income", y) for y in range(1, 6)]
    if all(v is not None for v in rev):
      cat.put("annual.revenue_series", [round(v, 2) for v in rev], "list",
              P("annual revenue, Years 1-5"), "Revenue series")
    if all(v is not None for v in ni):
      cat.put("annual.net_income_series", [round(v, 2) for v in ni], "list",
              P("annual net income, Years 1-5"), "Net income series")
    # margins mirror build_annual's arithmetic EXACTLY - gross profit over
    # revenue, EBITDA less depreciation over revenue, net income over revenue
    margins = []
    for y in range(1, 6):
      r, c, e, d, n = (_ysum(q, k, y) for k in ("revenue", "cogs", "ebitda", "depreciation", "net_income"))
      if r and r > 0:
        margins.append({"year": y, "gross": round((r - (c or 0)) / r, 4),
                        "operating": round(((e or 0) - (d or 0)) / r, 4),
                        "net": round((n or 0) / r, 4)})
    if len(margins) == 5:
      cat.put("annual.margin_structure_series", margins, "list",
              P("gross, operating and net margin per year"), "Margin structure")
    cash = [_f(q[i].get("cash")) for i in range(1, 21)]
    if all(v is not None for v in cash):
      cat.put("quarterly.cash_balance_series", [round(v, 2) for v in cash], "list",
              P("quarter-end cash balance, Q1-Q20"), "Cash balance series")
    else:
      cat.put("quarterly.cash_balance_series", ABSENT, "list", P("x"),
              absent_reason="cash missing on one or more quarters")
    qrev = [_f(q[i].get("revenue")) for i in range(1, 21)]
    qni = [_f(q[i].get("net_income")) for i in range(1, 21)]
    if all(v is not None for v in qrev) and all(v is not None for v in qni):
      cat.put("quarterly.revenue_series", [round(v, 2) for v in qrev], "list",
              P("quarterly revenue, Q1-Q20"), "Quarterly revenue")
      # total cost = revenue - net income: everything the model charges against
      # the quarter, so the CVP crossing IS the model's own break-even
      cat.put("quarterly.total_cost_series", [round(qrev[i] - qni[i], 2) for i in range(20)],
              "list", P("revenue less net income per quarter - the all-in cost line"),
              "Quarterly total cost")

  # headcount by role group for the stacked area: ending FTE at each year end,
  # grouped by position title when few enough to read, else by staffing class
  ph = _j(draft.get("payroll_headcount"))
  rows = [r for r in (ph.get("rows") or []) if isinstance(r, dict)]
  if not rows:
    cat.put("annual.headcount_by_role_group", ABSENT, "list", P("x"),
            absent_reason="no payroll schedule rows")
  else:
    titles = {str(r.get("position_title") or "").strip() for r in rows if r.get("position_title")}
    key = "position_title" if 0 < len(titles) <= 6 else "staffing_class"
    groups: Dict[str, List[float]] = {}
    for r in rows:
      qi = _f(r.get("quarter_index"))
      if qi is None or int(qi) not in (4, 8, 12, 16, 20):
        continue
      g = str(r.get(key) or "other").strip() or "other"
      arr = groups.setdefault(g, [0.0] * 5)
      arr[int(qi) // 4 - 1] += _f(r.get("ending_fte")) or 0.0
    series = [{"group": g, "annual": [round(v, 2) for v in arr]}
              for g, arr in sorted(groups.items(), key=lambda kv: -kv[1][-1])]
    if series and any(any(v > 0 for v in s["annual"]) for s in series):
      cat.put("annual.headcount_by_role_group", series, "list",
              P("ending FTE at each year end, grouped by %s" % ("role" if key == "position_title" else "staffing class")),
              "Headcount by role group")
    else:
      cat.put("annual.headcount_by_role_group", ABSENT, "list", P("x"),
              absent_reason="payroll rows carry no year-end FTE")


def build_revenue_buildup_fallback(cat: FactCatalog, draft: Dict[str, Any]) -> None:
  """When the driver arithmetic could not be trusted (the 5% gate) or there
  were no drivers, the revenue figure still appears - one series, the
  model's own annual revenue. The standard: a figure appears unless its
  section is absent, never because the data is thin."""
  if cat.has("annual.revenue_by_lob"):
    return
  s = cat.get_quiet("annual.revenue_series")
  if s is None:
    cat.put("annual.revenue_by_lob", ABSENT, "list", prov_model("x"), absent_reason="finmo_json lacks 20 quarters")
    return
  cat.put("annual.revenue_by_lob", [{"lob": "Revenue", "annual": list(s.value)}], "list",
          prov_model("annual revenue from the model - drivers unavailable or unreconciled"), "Revenue build-up")
  cat.put("annual.revenue_by_lob_basis", "total revenue", "text", prov_model("what the revenue build-up is split by"), "Build-up basis")


def build_market_composition(cat: FactCatalog, cur, ctx: Dict[str, Any]) -> None:
  """Sibling NAICS-6 lines in the client's COUNTY from CBP: fragmentation at
  a glance, the client's own line among its neighbours."""
  geo = ctx.get("geo") or {}
  n6 = str(ctx.get("naics6") or "")
  sf, cf = geo.get("state_fips"), geo.get("county_fips")
  if not (sf and cf and len(n6) == 6):
    cat.put("market.composition", ABSENT, "list", prov_model("x"),
            absent_reason="no county geography or no NAICS-6")
    return
  cands = _cbp_naics_candidates(cur, n6)
  # WIDEN until the composition has something to say: siblings under the
  # NAICS-4, then the NAICS-3, then the sector. A NAICS-4 with one child
  # (software publishers, 5112) has no siblings at all - the audit of
  # 2026-09-01 found three "missing" compositions that were only this.
  rows: List[Tuple[str, str, float]] = []
  used = None
  for geo_name, table, where, base in (("county", "cbp_2022_raw_county", "state_fips=%s AND county_fips=%s", [sf, cf]),
                                       ("state", "cbp_2022_raw", "state_fips=%s", [sf])):
    for level, prefixes, lvl_label in naics_scopes(cur, n6):
      if level == 6:
        continue
      clause, params = _like_clause("naics", level, prefixes)
      cur.execute("SELECT naics, naics_label, SUM(estab) FROM %s WHERE %s AND LENGTH(naics)=6 AND %s "
                  "GROUP BY naics, naics_label" % (table, where, clause), base + params)
      rows = [(str(a), str(b or a), float(v or 0)) for a, b, v in cur.fetchall()]
      rows = [r for r in rows if r[2] > 0]
      if len(rows) >= 2:
        used = (geo_name, lvl_label)
        break
    if used:
      break
  if not used:
    cat.put("market.composition", ABSENT, "list", prov_model("x"),
            absent_reason="fewer than two lines in CBP at any scope, county or state, for NAICS %s" % n6)
    return
  geo_txt = ("the county containing ZIP %s" % geo.get("zip")) if used[0] == "county" else "%s statewide" % geo.get("state_name")
  scope_label = "%s, %s" % (used[1], geo_txt)
  cat.put("market.composition_scope", scope_label, "text",
          prov_raw("County Business Patterns 2022", "2022", "the scope the composition was drawn at"),
          "Composition scope")
  own = set(cands)
  comp = [{"naics": a, "label": b, "establishments": v, "is_client_line": a in own}
          for a, b, v in sorted(rows, key=lambda r: -r[2])[:8]]
  cat.put("market.composition", comp,
          "list", prov_raw("County Business Patterns 2022", "2022",
                           "establishments by NAICS-6 line, %s" % scope_label),
          "Local market composition")


def build_wage_positioning(cat: FactCatalog, cur, draft: Dict[str, Any], ctx: Dict[str, Any]) -> None:
  """Each OEWS-matched role's planned wage as a dot on the occupation's state
  decile bar. The role-to-SOC mapping already exists upstream: the payroll
  author stamps oews_occ_code per row, so this builder joins rather than
  guesses. Client-override roles without an SOC are omitted from the chart -
  a wage nobody benchmarked is not drawn as if someone had."""
  ph = _j(draft.get("payroll_headcount"))
  rows = [r for r in (ph.get("rows") or [])
          if isinstance(r, dict) and int(_f(r.get("quarter_index")) or -1) == 1]
  if not rows:
    cat.put("entity.wage_positioning", ABSENT, "list", prov_model("x"),
            absent_reason="no payroll schedule rows")
    return
  geo = ctx.get("geo") or {}
  state = str(geo.get("state_name") or "").strip()
  seen: Dict[str, Dict[str, Any]] = {}
  for r in rows:
    occ = str(r.get("oews_occ_code") or "").strip()
    wage = _f(r.get("annual_wage"))
    title = str(r.get("position_title") or r.get("oews_occ_title") or occ)
    if not wage:
      continue
    if not occ:
      # the title catalogue's own exact match, applied at build time to roles
      # the payroll author left unstamped (client-override wages)
      for t in (r.get("oews_matched_title"), r.get("oews_occ_title"), r.get("position_title")):
        if not t:
          continue
        cur.execute("SELECT occ_code FROM oews_state_wages WHERE LOWER(occ_title)=%s AND naics='000000' "
                    "AND o_group='detailed' LIMIT 1", (str(t).strip().lower(),))
        m = cur.fetchone()
        if m and m[0]:
          occ = str(m[0]); break
    if not occ:
      continue
    negotiated = str(r.get("wage_source") or "").startswith("client")
    if occ not in seen or wage > seen[occ]["planned_wage"]:
      seen[occ] = {"role": title, "occ_code": occ, "planned_wage": wage,
                   "wage_source": str(r.get("wage_source") or ""), "negotiated": negotiated}
  if not seen:
    cat.put("entity.wage_positioning", ABSENT, "list", prov_model("x"),
            absent_reason="no OEWS-matched roles in the payroll schedule")
    return
  out = []
  for occ, item in seen.items():
    band = None
    for area in ((state,) if state else ()) + ("U.S.",):
      cur.execute("SELECT a_pct10, a_pct25, a_median, a_pct75, a_pct90 FROM oews_state_wages "
                  "WHERE area_title=%s AND occ_code=%s AND naics='000000' "
                  "AND a_median IS NOT NULL LIMIT 1", (area, occ))
      b = cur.fetchone()
      if b and b[2] is not None:
        band = {"scope": "state" if area == state else "national",
                "p10": _f(b[0]), "p25": _f(b[1]), "median": _f(b[2]),
                "p75": _f(b[3]), "p90": _f(b[4])}
        break
    if band:
      out.append({**item, **band})
  if out:
    scope = "state" if all(o["scope"] == "state" for o in out) else "state and national"
    cat.put("entity.wage_positioning", sorted(out, key=lambda o: -o["planned_wage"]), "list",
            prov_raw("OEWS state wages", "latest loaded OEWS cross-industry table",
                     "planned wage per role against the occupation's %s decile spread" % scope),
            "Wage positioning")
  else:
    cat.put("entity.wage_positioning", ABSENT, "list", prov_model("x"),
            absent_reason="no OEWS decile rows for the schedule's occupation codes")


def build_cvp_facts(cat: FactCatalog, draft: Dict[str, Any]) -> None:
  """The TRUE CVP (Nick 2026-09-01): volume on the axis. Fixed cost, the
  contribution-margin ratio and planned revenue come straight off the model's
  own Year-1 annualised break-even block, so the chart's crossing IS the
  model's break-even by construction. Units and a unit price are added only
  when the model has exactly one product line - a multi-product business is
  charted in sales dollars, the textbook form for a mixed volume."""
  P_ = prov_model
  be = ((_j(draft.get("finmo_json")) or {}).get("break_even") or {}).get("summary") or {}
  y1 = be.get("y1_annualized") or {}
  fc, cm, pl = _f(y1.get("fixed_costs")), _f(y1.get("cm_ratio")), _f(y1.get("planned_revenue"))
  if not (fc and cm and pl and 0 < cm < 1):
    for k in ("annual.cvp_fixed_costs_y1", "annual.cvp_cm_ratio_y1", "annual.cvp_planned_revenue_y1"):
      cat.put(k, ABSENT, "money", P_("x"), absent_reason="no annualised Year-1 break-even block in the model")
    return
  cat.put("annual.cvp_fixed_costs_y1", fc, "money", P_("Year-1 fixed costs from the model's break-even block"), "Fixed costs Y1")
  cat.put("annual.cvp_cm_ratio_y1", cm, "percent", P_("Year-1 contribution-margin ratio"), "Contribution margin ratio")
  cat.put("annual.cvp_planned_revenue_y1", pl, "money", P_("Year-1 planned revenue on the break-even basis"), "Planned revenue Y1")
  mi = _j(draft.get("model_input_json"))
  levers: Dict[str, Dict[str, List[float]]] = {}
  for r in ((mi.get("sections") or {}).get("revenue") or []):
    lever = str(r.get("lever_id") or "")
    if not lever.startswith("revenue::"):
      continue
    prod = "::".join(lever.split("::")[:3])
    drv = str(r.get("driver") or "")
    if drv in ("Capacity", "Utilization"):
      vals = [(_f(v) or 0.0) for v in (r.get("values") or [])]
      levers.setdefault(prod, {})[drv] = vals
  products = [p for p, d in levers.items() if "Capacity" in d]
  if len(products) == 1 and len(levers[products[0]]["Capacity"]) >= 5:
    cap = levers[products[0]]["Capacity"]
    util = levers[products[0]].get("Utilization") or [1.0] * len(cap)
    units = sum(cap[i] * (util[i] if i < len(util) else 1.0) for i in range(1, 5))
    if units > 0:
      cat.put("annual.cvp_units_y1", units, "count", P_("Year-1 planned unit volume from the revenue drivers"), "Units Y1")
      cat.put("annual.cvp_unit_price_y1", pl / units, "money_exact", P_("Year-1 revenue per unit"), "Unit price Y1")
      return
  for k in ("annual.cvp_units_y1", "annual.cvp_unit_price_y1"):
    cat.put(k, ABSENT, "count", P_("x"),
            absent_reason="%d product lines - the volume axis is sales dollars" % len(products))


# ---------------------------------------------------------------------------
# THE DOOR
# ---------------------------------------------------------------------------
def build_catalog(cur, draft: Dict[str, Any], *, miss_sink=None) -> FactCatalog:
  """One call. Every builder is isolated; a failure in one becomes ABSENT
  reasons, never a crash, and the failure text is kept so it can be read."""
  cat = FactCatalog(str(draft.get("draft_id") or ""), miss_sink=miss_sink)
  zip5 = str(draft.get("address_zip") or "").strip()[:5]
  geo = resolve_geography(cur, zip5) if zip5 else {}
  ctx: Dict[str, Any] = {"geo": geo, "naics6": ""}
  for name, fn in (("entity", lambda: build_entity(cat, cur, draft, geo)),
                   ("annual", lambda: build_annual(cat, draft, ctx)),
                   ("industry", lambda: build_industry(cat, cur, ctx)),
                   ("industry_history", lambda: build_industry_history(cat, cur, ctx)),
                   ("market", lambda: build_market(cat, cur, draft, ctx)),
                   ("sensitivity", lambda: build_sensitivity(cat, draft)),
                   ("chart_series", lambda: build_chart_series(cat, draft)),
                   ("cvp", lambda: build_cvp_facts(cat, draft)),
                   ("revenue_buildup", lambda: build_revenue_buildup_fallback(cat, draft)),
                   ("market_composition", lambda: build_market_composition(cat, cur, ctx)),
                   ("wage_positioning", lambda: build_wage_positioning(cat, cur, draft, ctx)),
                   ("economy", lambda: build_economy(cat, cur)),
                   ("valuation", lambda: build_valuation_facts(cat, cur, draft))):
    try:
      out = fn()
      if name == "entity" and isinstance(out, dict):
        ctx.update(out)
    except Exception as exc:  # noqa: BLE001
      cat.note_builder_failure(name, "%s: %s" % (type(exc).__name__, str(exc)[:160]))
  return cat
