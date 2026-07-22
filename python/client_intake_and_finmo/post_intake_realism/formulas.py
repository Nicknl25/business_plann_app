"""Module 3 Task 3.7 — derivation formula registry.

Each formula is a Python function that computes a single metric ratio from
FINMO output + model_input. The registry maps `derivation_formula_key`
(stored on each `post_intake_finalize_realism_check_lookup` row) to the
function that produces the actual ratio for the realism gate to compare
against the NAICS band.

Formula contract:
  - Input: model_input_json, finmo_json, quarter_index (1..20) when
    aggregation is per_quarter, or None when aggregation is
    year_one_aggregate / horizon_average.
  - Output: a float, or None when the formula is not computable for this
    quarter / aggregation (e.g., divide-by-zero, missing quarter row).
  - Formulas are pure-deterministic and never raise. If the inputs do not
    permit computation, return None and let the validator skip.

This pattern parallels the mapping-table formula registry — SQL selects
the key, Python executes the named function. Never invent a formula.

FINMO field-name authority: `python/financial_model_engine/finmo_model.py`
`FinmoQuarterResult` dataclass. Use the EXACT field names from that
class — `cost_of_goods_sold` (not `cogs`), `research_and_development` (not
`r_and_d`), `general_and_administrative` (not `g_and_a`),
`capital_expenditures` (not `capex`), `lease_rent` (covers rent + lease),
`debt_interest_expense` for the calc-side interest, `debt_interest_rate`
for the produced rate.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional


# ----------------------------------------------------------------------------
# FINMO row helpers.
# ----------------------------------------------------------------------------


def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  try:
    out = float(value)
  except Exception:
    return None
  if out != out:  # NaN guard
    return None
  return out


def _finmo_quarter_rows(finmo_json: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
  out: Dict[int, Dict[str, Any]] = {}
  for row in (finmo_json or {}).get("quarter_rows") or []:
    if not isinstance(row, dict):
      continue
    quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
    if quarter_index >= 1:
      out[quarter_index] = row
  return out


def _finmo_quarter_field(
  finmo_json: Dict[str, Any], quarter_index: int, field_name: str
) -> Optional[float]:
  rows = _finmo_quarter_rows(finmo_json)
  row = rows.get(int(quarter_index)) or {}
  return _safe_float(row.get(field_name))


def _finmo_year_one_sum(finmo_json: Dict[str, Any], field_name: str) -> Optional[float]:
  total = 0.0
  found = False
  for q in (1, 2, 3, 4):
    value = _finmo_quarter_field(finmo_json, q, field_name)
    if value is None:
      continue
    total += float(value)
    found = True
  return total if found else None


def _year_quarter_range(year_index: int) -> tuple:
  """Map year 1..5 to that year's 4 quarters. Y1 = Q1..Q4, Y5 = Q17..Q20."""
  y = int(year_index)
  start = (y - 1) * 4 + 1
  return tuple(range(start, start + 4))


def _finmo_year_n_sum(
  finmo_json: Dict[str, Any], year_index: int, field_name: str
) -> Optional[float]:
  """Sum a quarterly field across the four quarters of the given year."""
  total = 0.0
  found = False
  for q in _year_quarter_range(year_index):
    value = _finmo_quarter_field(finmo_json, q, field_name)
    if value is None:
      continue
    total += float(value)
    found = True
  return total if found else None


def _finmo_year_end_field(
  finmo_json: Dict[str, Any], year_index: int, field_name: str
) -> Optional[float]:
  """Return the year-end (last-quarter-of-year) value for a stock field."""
  y = int(year_index)
  q = y * 4
  return _finmo_quarter_field(finmo_json, q, field_name)


def _ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
  if numerator is None or denominator is None:
    return None
  if abs(float(denominator)) <= 1e-9:
    return None
  return float(numerator) / float(denominator)


# ----------------------------------------------------------------------------
# Formula implementations.
# ----------------------------------------------------------------------------


def _quarter_pretax_income(finmo_json: Dict[str, Any], quarter_index: int) -> Optional[float]:
  """FINMO does not expose `pretax_income` directly; derive it from EBITDA -
  interest - depreciation, matching `taxes` line semantics in the dataclass.
  """
  ebitda = _finmo_quarter_field(finmo_json, quarter_index, "ebitda")
  interest = _finmo_quarter_field(finmo_json, quarter_index, "interest") or 0.0
  depreciation = _finmo_quarter_field(finmo_json, quarter_index, "depreciation") or 0.0
  if ebitda is None:
    return None
  return float(ebitda) - float(interest) - float(depreciation)


def _quarter_operating_expense_base(finmo_json: Dict[str, Any], quarter_index: int) -> Optional[float]:
  """FINMO does not surface a single `operating_expense_total`; sum the
  expense lines that drive AP turnover (COGS + the four opex categories).
  """
  fields = (
    "cost_of_goods_sold",
    "marketing",
    "research_and_development",
    "lease_rent",
    "general_and_administrative",
  )
  total = 0.0
  found_any = False
  for f in fields:
    v = _finmo_quarter_field(finmo_json, quarter_index, f)
    if v is not None:
      total += float(v)
      found_any = True
  return total if found_any else None


def _formula_cogs_dollars_div_revenue_dollars(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  if quarter_index is None:
    return None
  cogs = _finmo_quarter_field(finmo_json, quarter_index, "cost_of_goods_sold")
  revenue = _finmo_quarter_field(finmo_json, quarter_index, "revenue")
  return _ratio(cogs, revenue)


def _formula_gross_margin_div_revenue(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  if quarter_index is None:
    return None
  # Prefer the FINMO-emitted gross_profit; fall back to revenue - COGS.
  gross_profit = _finmo_quarter_field(finmo_json, quarter_index, "gross_profit")
  revenue = _finmo_quarter_field(finmo_json, quarter_index, "revenue")
  if gross_profit is not None:
    return _ratio(gross_profit, revenue)
  cogs = _finmo_quarter_field(finmo_json, quarter_index, "cost_of_goods_sold")
  if revenue is None or cogs is None or abs(revenue) <= 1e-9:
    return None
  return (float(revenue) - float(cogs)) / float(revenue)


def _formula_marketing_dollars_div_revenue_dollars(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  if quarter_index is None:
    return None
  marketing = _finmo_quarter_field(finmo_json, quarter_index, "marketing")
  revenue = _finmo_quarter_field(finmo_json, quarter_index, "revenue")
  return _ratio(marketing, revenue)


def _formula_payroll_dollars_div_revenue_dollars(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  if quarter_index is None:
    return None
  payroll = _finmo_quarter_field(finmo_json, quarter_index, "payroll")
  revenue = _finmo_quarter_field(finmo_json, quarter_index, "revenue")
  return _ratio(payroll, revenue)


def _formula_taxes_div_pretax_income_year_one(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  taxes = _finmo_year_one_sum(finmo_json, "taxes")
  pretax_total = 0.0
  found = False
  for q in (1, 2, 3, 4):
    pretax_q = _quarter_pretax_income(finmo_json, q)
    if pretax_q is not None:
      pretax_total += float(pretax_q)
      found = True
  if not found:
    return None
  return _ratio(taxes, pretax_total)


def _formula_ebitda_div_revenue(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  if quarter_index is None:
    return None
  ebitda = _finmo_quarter_field(finmo_json, quarter_index, "ebitda")
  revenue = _finmo_quarter_field(finmo_json, quarter_index, "revenue")
  return _ratio(ebitda, revenue)


def _formula_net_income_div_revenue(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  if quarter_index is None:
    return None
  net_income = _finmo_quarter_field(finmo_json, quarter_index, "net_income")
  revenue = _finmo_quarter_field(finmo_json, quarter_index, "revenue")
  return _ratio(net_income, revenue)


def _formula_ar_days_from_balance_and_revenue(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  if quarter_index is None:
    return None
  ar = _finmo_quarter_field(finmo_json, quarter_index, "accounts_receivable")
  revenue = _finmo_quarter_field(finmo_json, quarter_index, "revenue")
  ratio = _ratio(ar, revenue)
  if ratio is None:
    return None
  return float(ratio) * 90.0


def _formula_ap_days_from_balance_and_expenses(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  if quarter_index is None:
    return None
  ap = _finmo_quarter_field(finmo_json, quarter_index, "accounts_payable")
  base = _quarter_operating_expense_base(finmo_json, quarter_index)
  ratio = _ratio(ap, base)
  if ratio is None:
    return None
  return float(ratio) * 90.0


def _formula_inventory_days_from_balance_and_cogs(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  if quarter_index is None:
    return None
  inventory = _finmo_quarter_field(finmo_json, quarter_index, "inventory")
  cogs = _finmo_quarter_field(finmo_json, quarter_index, "cost_of_goods_sold")
  ratio = _ratio(inventory, cogs)
  if ratio is None:
    return None
  return float(ratio) * 90.0


# --------------- Module 3 v3 expansion: 15 additional formulas ---------------


def _formula_advertising_dollars_div_revenue_dollars(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  # FINMO rolls advertising into "marketing"; the realism check for
  # advertising_percent_of_revenue is a no-op until FINMO splits the line,
  # so the formula returns None to skip the row gracefully.
  return None


def _formula_r_and_d_dollars_div_revenue_dollars(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  if quarter_index is None:
    return None
  r_and_d = _finmo_quarter_field(finmo_json, quarter_index, "research_and_development")
  revenue = _finmo_quarter_field(finmo_json, quarter_index, "revenue")
  return _ratio(r_and_d, revenue)


def _formula_lease_rent_dollars_div_revenue_dollars(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  if quarter_index is None:
    return None
  lease_rent = _finmo_quarter_field(finmo_json, quarter_index, "lease_rent")
  revenue = _finmo_quarter_field(finmo_json, quarter_index, "revenue")
  return _ratio(lease_rent, revenue)


def _formula_g_and_a_dollars_div_revenue_dollars(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  if quarter_index is None:
    return None
  g_and_a = _finmo_quarter_field(finmo_json, quarter_index, "general_and_administrative")
  revenue = _finmo_quarter_field(finmo_json, quarter_index, "revenue")
  return _ratio(g_and_a, revenue)


def _formula_sga_dollars_div_revenue_dollars(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  # SGA = marketing + general_and_administrative (FINMO does not surface a
  # combined sga line; sum the components).
  if quarter_index is None:
    return None
  marketing = _finmo_quarter_field(finmo_json, quarter_index, "marketing") or 0.0
  g_and_a = _finmo_quarter_field(finmo_json, quarter_index, "general_and_administrative") or 0.0
  revenue = _finmo_quarter_field(finmo_json, quarter_index, "revenue")
  if revenue is None or abs(revenue) <= 1e-9:
    return None
  if marketing == 0.0 and g_and_a == 0.0:
    return None
  return (float(marketing) + float(g_and_a)) / float(revenue)


def _formula_depreciation_dollars_div_revenue_dollars(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  if quarter_index is None:
    return None
  depreciation = _finmo_quarter_field(finmo_json, quarter_index, "depreciation")
  revenue = _finmo_quarter_field(finmo_json, quarter_index, "revenue")
  return _ratio(depreciation, revenue)


def _formula_operating_margin_div_revenue(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  # Operating margin = (EBITDA - depreciation) / revenue. FINMO does not
  # surface "operating_income" directly.
  if quarter_index is None:
    return None
  ebitda = _finmo_quarter_field(finmo_json, quarter_index, "ebitda")
  depreciation = _finmo_quarter_field(finmo_json, quarter_index, "depreciation") or 0.0
  revenue = _finmo_quarter_field(finmo_json, quarter_index, "revenue")
  if ebitda is None or revenue is None or abs(revenue) <= 1e-9:
    return None
  return (float(ebitda) - float(depreciation)) / float(revenue)


def _formula_prepaid_expenses_dollars_div_revenue_dollars(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  if quarter_index is None:
    return None
  prepaid = _finmo_quarter_field(finmo_json, quarter_index, "prepaid_expenses")
  revenue = _finmo_quarter_field(finmo_json, quarter_index, "revenue")
  return _ratio(prepaid, revenue)


def _formula_deferred_revenue_dollars_div_revenue_dollars(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  if quarter_index is None:
    return None
  deferred = _finmo_quarter_field(finmo_json, quarter_index, "deferred_revenue")
  revenue = _finmo_quarter_field(finmo_json, quarter_index, "revenue")
  return _ratio(deferred, revenue)


def _formula_ppe_dollars_div_revenue_dollars(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  if quarter_index is None:
    return None
  ppe = _finmo_quarter_field(finmo_json, quarter_index, "ppe")
  revenue = _finmo_quarter_field(finmo_json, quarter_index, "revenue")
  return _ratio(ppe, revenue)


def _formula_total_assets_div_revenue(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  if quarter_index is None:
    return None
  total_assets = _finmo_quarter_field(finmo_json, quarter_index, "total_assets")
  revenue = _finmo_quarter_field(finmo_json, quarter_index, "revenue")
  return _ratio(total_assets, revenue)


def _formula_owners_capital_div_total_assets(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  if quarter_index is None:
    return None
  owners_capital = _finmo_quarter_field(finmo_json, quarter_index, "owners_capital")
  total_assets = _finmo_quarter_field(finmo_json, quarter_index, "total_assets")
  return _ratio(owners_capital, total_assets)


def _formula_current_ratio(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  # Working-capital ratio: (current_assets - cash) / current_liabilities.
  # Cash is excluded so that smart_funding_policy's equity injection (a
  # legitimate doctrine pass that inflates cash to cover the loss window)
  # does not inflate this ratio out of band. AR + inventory + prepaid is
  # what we actually want to compare against current liabilities here;
  # cash position has its own dedicated checks (cash_legitimate_q1_q10,
  # cash_health_operational_not_debt_funded, balance_sheet_growth_plausible).
  if quarter_index is None:
    return None
  current_assets = _finmo_quarter_field(finmo_json, quarter_index, "current_assets")
  current_liabilities = _finmo_quarter_field(finmo_json, quarter_index, "current_liabilities")
  if current_assets is None or current_liabilities is None:
    return None
  cash = _finmo_quarter_field(finmo_json, quarter_index, "cash") or 0.0
  return _ratio(float(current_assets) - float(cash), current_liabilities)


def _formula_quick_ratio(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  # (Current assets - inventory) / current liabilities.
  if quarter_index is None:
    return None
  current_assets = _finmo_quarter_field(finmo_json, quarter_index, "current_assets")
  inventory = _finmo_quarter_field(finmo_json, quarter_index, "inventory") or 0.0
  current_liabilities = _finmo_quarter_field(finmo_json, quarter_index, "current_liabilities")
  if current_assets is None or current_liabilities is None:
    return None
  return _ratio(float(current_assets) - float(inventory), current_liabilities)


def _formula_current_assets_minus_cash_div_revenue(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  """Phase 9 P3 Target 3 — (AR + Inventory + Prepaid) / Revenue.

  Working capital tied up in operating assets, expressed as a ratio to
  the quarter's revenue so cohort comparison is scale-free. Cash is
  excluded; cash position is owned by the cash strategy. The numerator
  prefers the FINMO `current_assets` aggregate minus `cash` if both are
  present; falls back to summing AR + inventory + prepaid_expenses
  individually when current_assets is unavailable.
  """
  if quarter_index is None:
    return None
  revenue = _finmo_quarter_field(finmo_json, quarter_index, "revenue")
  if revenue is None or abs(revenue) <= 1e-9:
    return None
  current_assets = _finmo_quarter_field(finmo_json, quarter_index, "current_assets")
  cash = _finmo_quarter_field(finmo_json, quarter_index, "cash") or 0.0
  if current_assets is not None:
    numerator = float(current_assets) - float(cash)
  else:
    ar = _finmo_quarter_field(finmo_json, quarter_index, "accounts_receivable") or 0.0
    inv = _finmo_quarter_field(finmo_json, quarter_index, "inventory") or 0.0
    prepaid = _finmo_quarter_field(finmo_json, quarter_index, "prepaid_expenses") or 0.0
    numerator = float(ar) + float(inv) + float(prepaid)
  return float(numerator) / float(revenue)


def _formula_current_liabilities_div_revenue(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  """Phase 9 P3 Target 4 — current_liabilities / revenue.

  Total current liabilities (AP + short-term debt + accrued + deferred
  revenue) over the quarter's revenue. Prefers the FINMO
  `current_liabilities` aggregate when present; falls back to summing
  the components individually.
  """
  if quarter_index is None:
    return None
  revenue = _finmo_quarter_field(finmo_json, quarter_index, "revenue")
  if revenue is None or abs(revenue) <= 1e-9:
    return None
  current_liabilities = _finmo_quarter_field(
    finmo_json, quarter_index, "current_liabilities"
  )
  if current_liabilities is not None:
    return float(current_liabilities) / float(revenue)
  ap = _finmo_quarter_field(finmo_json, quarter_index, "accounts_payable") or 0.0
  std = _finmo_quarter_field(finmo_json, quarter_index, "short_term_debt") or 0.0
  accrued = _finmo_quarter_field(finmo_json, quarter_index, "accrued_expenses") or 0.0
  deferred = _finmo_quarter_field(finmo_json, quarter_index, "deferred_revenue") or 0.0
  return (float(ap) + float(std) + float(accrued) + float(deferred)) / float(revenue)


def _formula_total_debt_div_total_equity(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  if quarter_index is None:
    return None
  short_term = _finmo_quarter_field(finmo_json, quarter_index, "short_term_debt") or 0.0
  long_term = _finmo_quarter_field(finmo_json, quarter_index, "long_term_debt") or 0.0
  total_debt = float(short_term) + float(long_term)
  total_equity = _finmo_quarter_field(finmo_json, quarter_index, "total_equity")
  return _ratio(total_debt, total_equity)


def _formula_total_debt_div_total_assets(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  if quarter_index is None:
    return None
  short_term = _finmo_quarter_field(finmo_json, quarter_index, "short_term_debt") or 0.0
  long_term = _finmo_quarter_field(finmo_json, quarter_index, "long_term_debt") or 0.0
  total_debt = float(short_term) + float(long_term)
  total_assets = _finmo_quarter_field(finmo_json, quarter_index, "total_assets")
  return _ratio(total_debt, total_assets)


def _formula_operating_cash_flow_div_revenue(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  if quarter_index is None:
    return None
  ocf = _finmo_quarter_field(finmo_json, quarter_index, "operating_cash_flow")
  revenue = _finmo_quarter_field(finmo_json, quarter_index, "revenue")
  return _ratio(ocf, revenue)


def _formula_capex_div_revenue_year_one(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  capex = _finmo_year_one_sum(finmo_json, "capital_expenditures")
  revenue = _finmo_year_one_sum(finmo_json, "revenue")
  return _ratio(capex, revenue)


def _formula_distributions_div_net_income_year_one(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  distributions = _finmo_year_one_sum(finmo_json, "distributions")
  if distributions is None:
    distributions = _finmo_year_one_sum(finmo_json, "owner_distributions")
  net_income = _finmo_year_one_sum(finmo_json, "net_income")
  return _ratio(distributions, net_income)


# ----------------------------------------------------------------------------
# Phase 9 audit Bucket B — per-year aggregate formulas (Y1..Y5).
#
# Each takes a ``year_index`` (1..5) and returns the metric value for that
# year. Aggregation conventions:
#   - flow metrics (taxes, capex, distributions, revenue, net_income) — sum
#     across the four quarters of the year.
#   - stock metrics (total_assets, owners_capital) — read the year-end
#     (last-quarter-of-year) snapshot.
# ----------------------------------------------------------------------------


def _formula_taxes_div_pretax_income_per_year(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  year_index: Optional[int] = None,
) -> Optional[float]:
  _ = model_input_json
  if year_index is None:
    return None
  taxes = _finmo_year_n_sum(finmo_json, year_index, "taxes")
  pretax_total = 0.0
  found = False
  for q in _year_quarter_range(year_index):
    pretax_q = _quarter_pretax_income(finmo_json, q)
    if pretax_q is not None:
      pretax_total += float(pretax_q)
      found = True
  if not found:
    return None
  return _ratio(taxes, pretax_total)


def _formula_capex_div_revenue_per_year(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  year_index: Optional[int] = None,
) -> Optional[float]:
  _ = model_input_json
  if year_index is None:
    return None
  capex = _finmo_year_n_sum(finmo_json, year_index, "capital_expenditures")
  revenue = _finmo_year_n_sum(finmo_json, year_index, "revenue")
  return _ratio(capex, revenue)


def _formula_distributions_div_net_income_per_year(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  year_index: Optional[int] = None,
) -> Optional[float]:
  _ = model_input_json
  if year_index is None:
    return None
  distributions = _finmo_year_n_sum(finmo_json, year_index, "distributions")
  if distributions is None:
    distributions = _finmo_year_n_sum(finmo_json, year_index, "owner_distributions")
  net_income = _finmo_year_n_sum(finmo_json, year_index, "net_income")
  return _ratio(distributions, net_income)


def _formula_total_assets_div_revenue_per_year(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  year_index: Optional[int] = None,
) -> Optional[float]:
  _ = model_input_json
  if year_index is None:
    return None
  total_assets = _finmo_year_end_field(finmo_json, year_index, "total_assets")
  revenue = _finmo_year_n_sum(finmo_json, year_index, "revenue")
  return _ratio(total_assets, revenue)


def _formula_owners_capital_div_total_assets_per_year(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  year_index: Optional[int] = None,
) -> Optional[float]:
  _ = model_input_json
  if year_index is None:
    return None
  owners_capital = _finmo_year_end_field(finmo_json, year_index, "owners_capital")
  total_assets = _finmo_year_end_field(finmo_json, year_index, "total_assets")
  return _ratio(owners_capital, total_assets)


# ----------------------------------------------------------------------------
# Phase 9 Phase D — Universal viability timeline formulas.
#
# Each returns a float interpretation of a trajectory check. Positive
# values pass the universal viability rule for that check; non-positive
# values flag a violation the validator routes to the appropriate
# adaptation family.
# ----------------------------------------------------------------------------


def _quarter_ebitda_margin(finmo_json: Dict[str, Any], quarter_index: int) -> Optional[float]:
  ebitda = _finmo_quarter_field(finmo_json, quarter_index, "ebitda")
  revenue = _finmo_quarter_field(finmo_json, quarter_index, "revenue")
  return _ratio(ebitda, revenue)


def _quarter_gross_margin(finmo_json: Dict[str, Any], quarter_index: int) -> Optional[float]:
  cogs = _finmo_quarter_field(finmo_json, quarter_index, "cost_of_goods_sold")
  revenue = _finmo_quarter_field(finmo_json, quarter_index, "revenue")
  if cogs is None or revenue is None or revenue <= 0:
    return None
  return float(revenue - cogs) / float(revenue)


def _quarter_ending_cash(finmo_json: Dict[str, Any], quarter_index: int) -> Optional[float]:
  for field_name in ("ending_cash", "cash", "cash_balance"):
    value = _finmo_quarter_field(finmo_json, quarter_index, field_name)
    if value is not None:
      return value
  return None


def _formula_trajectory_capital_lease_amortizes(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  """Universal statement-coherence rule — a capital-lease obligation must
  actually AMORTIZE over the horizon, not sit frozen at opening balance.

  The frozen-balance failure class (caught on Big_Shipper): a lease seed
  with no principal schedule left a $960M liability at Q20 against a $0
  ROU asset — interest-only forever, cash overstated by the entire unpaid
  principal stream, and the balance sheet TIES by construction so nothing
  else catches it.

  Returns (0.95 x opening_seed - q20_closing) / opening_seed: >= 0 passes.
  A frozen balance (closing >= 95% of seed) fails; a stated or authored
  SLOWER-but-real schedule (e.g. a 10-year equipment lease ~50% paid by
  Q20) passes — the rule is "it amortizes", not "it must reach zero".
  No lease (seed <= 0) trivially passes.
  """
  _ = (model_input_json, quarter_index)
  rows = (finmo_json or {}).get("quarter_rows") or []
  def _f(q: int, key: str) -> float:
    try:
      return float((rows[q] or {}).get(key) or 0.0)
    except (TypeError, ValueError, IndexError):
      return 0.0
  if len(rows) < 2:
    return None
  seed = _f(1, "lease_opening_balance_total")
  if seed <= 0.0:
    return 0.0
  last_q = min(20, len(rows) - 1)
  closing = _f(last_q, "lease_closing_balance_total")
  return (0.95 * seed - closing) / seed


def _formula_trajectory_ebitda_positive_at_quarter(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  """Universal viability rule — Q11 EBITDA margin must be >= 0.

  Returns Q11 EBITDA margin. The validator compares against the floor
  encoded in the row's band (default 0.0). Values below the floor are
  routed to turnaround_recovery_q5_q11.
  """
  _ = (model_input_json, quarter_index)
  return _quarter_ebitda_margin(finmo_json, 11)


# A business already healthily profitable at Q5 has nothing to RECOVER --
# the recovery-trend check exists to prove a loss-making start genuinely
# climbs out, not to forbid a healthy operation from maturing its cost
# structure (Apex: 47% EBITDA at Q5 gliding to 45% at Q11 as admin staffing
# normalizes is lender-defensible; demanding it climb further is not).
# Same recalibration doctrine as the NI flat-healthy rule: healthy-flat
# passes; never-recovers still fails; a healthy start COLLAPSING (losing
# more than half its margin, or dropping below the healthy floor) still
# fails.
_EBITDA_HEALTHY_FLAT_FLOOR = 0.02
_EBITDA_HEALTHY_RETENTION_FRACTION = 0.5


def _formula_trajectory_ebitda_recovery_trend(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  """Q11 EBITDA margin minus Q5 EBITDA margin. Positive = real recovery.

  Healthy-flat exception: when Q5 is already at/above the healthy floor AND
  Q11 retains both the floor and at least half the Q5 margin, the business
  needed no recovery -- the value floors at 0.0 (pass). Every other shape
  returns the raw delta, so a loss-making start that never climbs, or a
  healthy start that collapses, still fails.

  BAND SUBORDINATION (fragility-class Wave 1): the exception's healthy
  floor is the JUDGED Q11 band low when the executive margin-band
  judgment is present — a thin-margin business whose healthy level is
  1.5% could never use a 2pp absolute exception. The 50% retention
  fraction stays (it is already relative). Judgment absent -> today's
  exact 2pp behavior (fallback kept)."""
  _ = quarter_index
  q5 = _quarter_ebitda_margin(finmo_json, 5)
  q11 = _quarter_ebitda_margin(finmo_json, 11)
  if q5 is None or q11 is None:
    return None
  raw = float(q11) - float(q5)
  healthy_floor = _EBITDA_HEALTHY_FLAT_FLOOR
  try:
    from client_intake_and_finmo.post_intake_headcount.gpt_margin_band_judgment import (  # noqa: E501
      margin_band_from_model_input,
    )
    _judgment = margin_band_from_model_input(model_input_json)
    _q11_low = ((_judgment or {}).get("q11") or {}).get("low")
    if _q11_low is not None:
      healthy_floor = float(_q11_low)
  except Exception:
    healthy_floor = _EBITDA_HEALTHY_FLAT_FLOOR
  if (
    float(q5) >= healthy_floor
    and float(q11) >= max(healthy_floor, float(q5) * _EBITDA_HEALTHY_RETENTION_FRACTION)
  ):
    return max(raw, 0.0)
  return raw


def _formula_trajectory_loss_window_funded(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  """Minimum ending cash across Q1..Q5. Positive = funded loss window."""
  _ = (model_input_json, quarter_index)
  values: List[float] = []
  for q in (1, 2, 3, 4, 5):
    v = _quarter_ending_cash(finmo_json, q)
    if v is not None:
      values.append(float(v))
  if not values:
    return None
  return float(min(values))


_EBITDA_Q20_HOLDS_OR_IMPROVES_TOLERANCE = 0.01

def _formula_trajectory_ebitda_q20_holds_or_improves_vs_q11(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  """Q20 EBITDA margin holds or improves relative to Q11.

  Phase 9 P3.8 — replaces the prior 'no_post_recovery_relapse_q11_q20'
  formula, which returned min(EBITDA margin Q11..Q20) and was paired
  with a `>= 0` band check (a positivity test, not a relapse test).
  Under that formula a trajectory peaking at Q11 (e.g. 5% EBITDA) and
  declining toward break-even by Q20 (e.g. 0.5%) passed unconditionally
  because every quarter stayed positive.

  Universal viability doctrine: a business that crosses into viability
  at Q11 should NOT regress back toward break-even (or toward an
  industry-average that is structurally loss-making, as some NAICS
  cohort medians show). The check enforces this by computing
  `EBITDA_margin[Q20] - EBITDA_margin[Q11]` and adding 0.01 so the
  validator's `>= 0` trajectory-check translates into the doctrinal
  `>= -0.01` (Q20 may be at most 1pp below Q11). The 0.01 is a math-
  noise / floating-point buffer, NOT a doctrinal allowance for
  decline.

  BAND SUBORDINATION (fragility-class Wave 1): the check was written
  before the executive margin-band judgment existed, to stop regression
  toward structurally loss-making cohort medians. With the judged band
  present, the executive's Q20 band IS the definition of mature health
  — a dip that still lands AT OR ABOVE the judged Q20 band low is not
  regression toward break-even (and the mature-quarter LEVEL check
  independently hard-fails anything below the band). A 1pp absolute
  buffer at any margin level fails healthy high-margin plans on
  relative noise; the judged band knows the business. Judgment absent
  -> today's exact 1pp behavior (fallback kept).
  """
  _ = quarter_index
  q11 = _quarter_ebitda_margin(finmo_json, 11)
  q20 = _quarter_ebitda_margin(finmo_json, 20)
  if q11 is None or q20 is None:
    return None
  raw = float(q20) - float(q11) + _EBITDA_Q20_HOLDS_OR_IMPROVES_TOLERANCE
  try:
    from client_intake_and_finmo.post_intake_headcount.gpt_margin_band_judgment import (  # noqa: E501
      margin_band_from_model_input,
    )
    _judgment = margin_band_from_model_input(model_input_json)
    _q20_low = ((_judgment or {}).get("q20") or {}).get("low")
    if _q20_low is not None and float(q20) >= float(_q20_low) - 1e-9:
      return max(raw, 0.0)
  except Exception:
    pass
  return raw


_GROSS_MARGIN_RECOVERY_FLOOR = 0.20

def _formula_trajectory_gross_margin_supports_recovery(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  """Q11 gross margin minus the recovery-supporting floor (0.20).

  The validator's universal trajectory test is `>= 0.0`, so we shift the
  doctrine threshold into the formula: returning `gm - 0.20` makes the
  validator's `>= 0.0` test mean "Q11 gross margin >= 20%". Phase E will
  replace 0.20 with the NAICS-keyed floor; until then the constant lives
  next to the formula.

  Audit fix #7 — pre-fix the formula returned the raw gross margin and
  the validator compared to 0.0, which let any positive Q11 GM pass.

  JUDGED FLOOR (universal-app fix): when the executive margin-band
  judgment authored gross_margin_floor_q11 for THIS business, that
  floor governs — a grocer is judged against grocer physics, a
  consultancy against consultancy physics. The 0.20 constant is the
  judgment-absent fallback only (same precedence pattern as the cash
  rail and working-capital judgments)."""
  _ = quarter_index
  gm = _quarter_gross_margin(finmo_json, 11)
  if gm is None:
    return None
  floor = _GROSS_MARGIN_RECOVERY_FLOOR
  try:
    from client_intake_and_finmo.post_intake_headcount.gpt_margin_band_judgment import (  # noqa: E501
      margin_band_from_model_input,
    )
    _judgment = margin_band_from_model_input(model_input_json)
    _judged_floor = (_judgment or {}).get("gross_margin_floor_q11")
    if _judged_floor is not None:
      floor = float(_judged_floor)
  except Exception:
    floor = _GROSS_MARGIN_RECOVERY_FLOOR
  return float(gm) - float(floor)


_FIXED_COST_BURDEN_INDUSTRY_MAX = 0.65

def _formula_trajectory_fixed_cost_burden_at_industry_floor(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  """(Revenue - Payroll - Lease - G&A) / Revenue at Q11, shifted by the
  doctrine slack so the validator's universal `>= 0.0` test means
  "fixed cost burden <= 65% of revenue at Q11".

  Returns ((revenue - fixed) / revenue) - 0.35. Positive = fixed cost
  burden at or below the 65% industry ceiling; negative = burden too
  high. Phase E will plug in the NAICS-keyed industry max.

  Audit fix #8 — pre-fix the formula returned the raw slack and the
  validator compared to 0.0, which only caught fixed > 100% of revenue.

  JUDGED CEILING (universal-app fix): when the executive margin-band
  judgment authored fixed_cost_burden_max_q11 for THIS business, that
  ceiling governs — expert-labor practices are judged against their
  real staffing physics, capital-light distributors against theirs.
  The 0.65 constant is the judgment-absent fallback only."""
  _ = quarter_index
  payroll = _finmo_quarter_field(finmo_json, 11, "payroll")
  rent = _finmo_quarter_field(finmo_json, 11, "lease_rent")
  ga = _finmo_quarter_field(finmo_json, 11, "general_and_administrative")
  revenue = _finmo_quarter_field(finmo_json, 11, "revenue")
  if revenue is None or revenue <= 0:
    return None
  burden_max = _FIXED_COST_BURDEN_INDUSTRY_MAX
  try:
    from client_intake_and_finmo.post_intake_headcount.gpt_margin_band_judgment import (  # noqa: E501
      margin_band_from_model_input,
    )
    _judgment = margin_band_from_model_input(model_input_json)
    _judged_max = (_judgment or {}).get("fixed_cost_burden_max_q11")
    if _judged_max is not None:
      burden_max = float(_judged_max)
  except Exception:
    burden_max = _FIXED_COST_BURDEN_INDUSTRY_MAX
  fixed = float(payroll or 0.0) + float(rent or 0.0) + float(ga or 0.0)
  slack = float(revenue - fixed) / float(revenue)
  result = slack - (1.0 - burden_max)
  if result < 0.0:
    # HEALTHY-PROFITABILITY EXCEPTION (same recalibration doctrine as the
    # recovery-trend and NI flat-healthy rules): the ceiling exists to catch
    # fixed-cost structures that CRUSH viability, not to fail a labor-heavy
    # service business that is healthily profitable (a dental practice at
    # 66% payroll+rent+G&A with Q11 EBITDA +11.6% and positive net income
    # is a normal expert-labor P&L, not a burden failure). When Q11 EBITDA
    # margin clears the healthy floor, the burden is by definition
    # supportable -- the value floors at 0 (pass). A high burden WITH weak
    # margins still fails on the raw slack.
    q11_ebitda = _quarter_ebitda_margin(finmo_json, 11)
    if q11_ebitda is not None and float(q11_ebitda) >= _EBITDA_HEALTHY_FLAT_FLOOR:
      return 0.0
  return result


# ----------------------------------------------------------------------------
# Registry.
# ----------------------------------------------------------------------------


_FORMULA_REGISTRY: Dict[str, Callable[..., Optional[float]]] = {
  # P&L line ratios.
  "cogs_dollars_div_revenue_dollars": _formula_cogs_dollars_div_revenue_dollars,
  "gross_margin_div_revenue": _formula_gross_margin_div_revenue,
  "marketing_dollars_div_revenue_dollars": _formula_marketing_dollars_div_revenue_dollars,
  "advertising_dollars_div_revenue_dollars": _formula_advertising_dollars_div_revenue_dollars,
  "r_and_d_dollars_div_revenue_dollars": _formula_r_and_d_dollars_div_revenue_dollars,
  "lease_rent_dollars_div_revenue_dollars": _formula_lease_rent_dollars_div_revenue_dollars,
  "g_and_a_dollars_div_revenue_dollars": _formula_g_and_a_dollars_div_revenue_dollars,
  "sga_dollars_div_revenue_dollars": _formula_sga_dollars_div_revenue_dollars,
  "payroll_dollars_div_revenue_dollars": _formula_payroll_dollars_div_revenue_dollars,
  "depreciation_dollars_div_revenue_dollars": _formula_depreciation_dollars_div_revenue_dollars,
  "taxes_div_pretax_income_year_one": _formula_taxes_div_pretax_income_year_one,
  "ebitda_div_revenue": _formula_ebitda_div_revenue,
  "operating_margin_div_revenue": _formula_operating_margin_div_revenue,
  "net_income_div_revenue": _formula_net_income_div_revenue,
  # Balance sheet ratios.
  "ar_days_from_balance_and_revenue": _formula_ar_days_from_balance_and_revenue,
  "ap_days_from_balance_and_expenses": _formula_ap_days_from_balance_and_expenses,
  "inventory_days_from_balance_and_cogs": _formula_inventory_days_from_balance_and_cogs,
  "prepaid_expenses_dollars_div_revenue_dollars": _formula_prepaid_expenses_dollars_div_revenue_dollars,
  "deferred_revenue_dollars_div_revenue_dollars": _formula_deferred_revenue_dollars_div_revenue_dollars,
  "ppe_dollars_div_revenue_dollars": _formula_ppe_dollars_div_revenue_dollars,
  "total_assets_div_revenue": _formula_total_assets_div_revenue,
  "owners_capital_div_total_assets": _formula_owners_capital_div_total_assets,
  "current_ratio": _formula_current_ratio,
  "quick_ratio": _formula_quick_ratio,
  # Phase 9 P3 — Target 3 & Target 4 working-capital structure metrics.
  "current_assets_minus_cash_div_revenue": _formula_current_assets_minus_cash_div_revenue,
  "current_liabilities_div_revenue": _formula_current_liabilities_div_revenue,
  "total_debt_div_total_equity": _formula_total_debt_div_total_equity,
  "total_debt_div_total_assets": _formula_total_debt_div_total_assets,
  # Cash flow ratios.
  "operating_cash_flow_div_revenue": _formula_operating_cash_flow_div_revenue,
  "capex_div_revenue_year_one": _formula_capex_div_revenue_year_one,
  "distributions_div_net_income_year_one": _formula_distributions_div_net_income_year_one,
  # Phase 9 audit Bucket B — per-year aggregate formulas (Y1..Y5).
  "taxes_div_pretax_income_per_year": _formula_taxes_div_pretax_income_per_year,
  "capex_div_revenue_per_year": _formula_capex_div_revenue_per_year,
  "distributions_div_net_income_per_year": _formula_distributions_div_net_income_per_year,
  "total_assets_div_revenue_per_year": _formula_total_assets_div_revenue_per_year,
  "owners_capital_div_total_assets_per_year": _formula_owners_capital_div_total_assets_per_year,
  # Phase 9 Phase D — universal viability timeline trajectory checks.
  "trajectory_capital_lease_amortizes": _formula_trajectory_capital_lease_amortizes,
  "trajectory_ebitda_positive_at_quarter": _formula_trajectory_ebitda_positive_at_quarter,
  "trajectory_ebitda_recovery_trend": _formula_trajectory_ebitda_recovery_trend,
  "trajectory_loss_window_funded": _formula_trajectory_loss_window_funded,
  "trajectory_ebitda_q20_holds_or_improves_vs_q11": _formula_trajectory_ebitda_q20_holds_or_improves_vs_q11,
  "trajectory_gross_margin_supports_recovery": _formula_trajectory_gross_margin_supports_recovery,
  "trajectory_fixed_cost_burden_at_industry_floor": _formula_trajectory_fixed_cost_burden_at_industry_floor,
}


class RealismFormulaNotRegistered(LookupError):
  """Raised when a realism check row references a formula key not in the registry."""


def evaluate_realism_formula(
  formula_key: str,
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
  year_index: Optional[int] = None,
) -> Optional[float]:
  """Dispatch to the named formula. Per-year formulas take ``year_index``;
  per-quarter and trajectory formulas ignore it."""
  key = str(formula_key or "").strip()
  fn = _FORMULA_REGISTRY.get(key)
  if fn is None:
    raise RealismFormulaNotRegistered(
      f"post_intake_realism_formula_not_registered: formula_key={key}"
    )
  # Per-year formulas take year_index instead of quarter_index. The
  # registry suffix `_per_year` is the dispatch hint; per-quarter
  # formulas keep their existing signature.
  if key.endswith("_per_year"):
    return fn(
      model_input_json=model_input_json or {},
      finmo_json=finmo_json or {},
      year_index=year_index,
    )
  return fn(
    model_input_json=model_input_json or {},
    finmo_json=finmo_json or {},
    quarter_index=quarter_index,
  )


def registered_realism_formula_keys() -> List[str]:
  return sorted(_FORMULA_REGISTRY.keys())
