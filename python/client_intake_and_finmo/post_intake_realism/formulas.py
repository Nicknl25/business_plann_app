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
  if quarter_index is None:
    return None
  current_assets = _finmo_quarter_field(finmo_json, quarter_index, "current_assets")
  current_liabilities = _finmo_quarter_field(finmo_json, quarter_index, "current_liabilities")
  return _ratio(current_assets, current_liabilities)


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
  "total_debt_div_total_equity": _formula_total_debt_div_total_equity,
  "total_debt_div_total_assets": _formula_total_debt_div_total_assets,
  # Cash flow ratios.
  "operating_cash_flow_div_revenue": _formula_operating_cash_flow_div_revenue,
  "capex_div_revenue_year_one": _formula_capex_div_revenue_year_one,
  "distributions_div_net_income_year_one": _formula_distributions_div_net_income_year_one,
}


class RealismFormulaNotRegistered(LookupError):
  """Raised when a realism check row references a formula key not in the registry."""


def evaluate_realism_formula(
  formula_key: str,
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  quarter_index: Optional[int] = None,
) -> Optional[float]:
  key = str(formula_key or "").strip()
  fn = _FORMULA_REGISTRY.get(key)
  if fn is None:
    raise RealismFormulaNotRegistered(
      f"post_intake_realism_formula_not_registered: formula_key={key}"
    )
  return fn(
    model_input_json=model_input_json or {},
    finmo_json=finmo_json or {},
    quarter_index=quarter_index,
  )


def registered_realism_formula_keys() -> List[str]:
  return sorted(_FORMULA_REGISTRY.keys())
