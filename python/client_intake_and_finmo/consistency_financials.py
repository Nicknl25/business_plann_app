from __future__ import annotations

from typing import Any, Dict, List, Optional


def _safe_float(value: Any) -> float:
  try:
    num = float(value)
  except Exception:
    return 0.0
  if num != num:  # NaN
    return 0.0
  return num


def _format_currency(value: Any) -> str:
  amount = _safe_float(value)
  return f"${amount:,.0f}" if abs(amount - round(amount)) < 1e-9 else f"${amount:,.2f}"


def _build_quarterly_ebitda_forecast_table(forecast_quarters: Any) -> str:
  quarters = [q for q in (forecast_quarters or []) if isinstance(q, dict)]
  if not quarters:
    return ""

  lines: List[str] = [
    "Quarterly EBITDA Forecast",
    "",
    "| Year | Q1 | Q2 | Q3 | Q4 |",
    "| --- | ---: | ---: | ---: | ---: |",
  ]

  for year_index in range(0, len(quarters), 4):
    chunk = quarters[year_index:year_index + 4]
    if not chunk:
      continue
    year_number = (year_index // 4) + 1
    values = [_format_currency((quarter or {}).get("ebitda")) for quarter in chunk]
    while len(values) < 4:
      values.append("--")
    lines.append(f"| Year {year_number} | {values[0]} | {values[1]} | {values[2]} | {values[3]} |")

  return "\n".join(lines)


def build_consistency_financial_summary(
  *,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Dict[str, Any]:
  financials = financials_json if isinstance(financials_json, dict) else {}
  year1 = financials_year1_json if isinstance(financials_year1_json, dict) else {}

  # This table is a Year-1 viability view. Use the Year-1 financial mapping only,
  # with narrow fallbacks to older persisted modeled fields where needed.
  revenue = _safe_float(year1.get("company_revenue_total_year1") or financials.get("current_revenue"))
  cogs = _safe_float(
    financials.get("cogs_total_year1")
    or year1.get("company_cogs_total_year1")
    or year1.get("cogs_total_year1")
  )
  if cogs <= 0:
    cogs = _safe_float(financials.get("current_cogs"))
  gross_profit = revenue - cogs
  # The controller-owned Year-1 payroll field is the most trustworthy value
  # when staffing assumptions and modeled payroll diverge.
  payroll = _safe_float(
    financials.get("current_payroll")
    or financials.get("payroll_total_year1")
    or year1.get("company_payroll_total_year1")
    or year1.get("payroll_total_year1")
  )
  marketing = _safe_float(
    financials.get("marketing_total_year1")
    or year1.get("company_marketing_total_year1")
    or year1.get("marketing_total_year1")
  )
  rent_annualized = _safe_float(financials.get("monthly_rent_expense")) * 12.0
  other_opex_non_rent = _safe_float(
    financials.get("other_operating_expense")
    or year1.get("other_operating_expense_total_year1")
    or year1.get("other_operating_expense")
  )
  other_opex = other_opex_non_rent + rent_annualized
  ebitda = gross_profit - payroll - marketing - other_opex
  interest = _safe_float(financials.get("annual_interest_payment"))
  taxes = 0.0
  net_income = ebitda - interest - taxes

  return {
    "revenue": revenue,
    "cogs": cogs,
    "gross_profit": gross_profit,
    "payroll": payroll,
    "marketing": marketing,
    "other_opex": other_opex,
    "other_opex_non_rent": other_opex_non_rent,
    "rent_annualized": rent_annualized,
    "ebitda": ebitda,
    "interest": interest,
    "taxes": taxes,
    "net_income": net_income,
    "taxes_assumed_zero": True,
  }


def build_consistency_financial_table(
  summary: Dict[str, Any],
  forecast_quarters: Optional[List[Dict[str, Any]]] = None,
) -> str:
  if not isinstance(summary, dict):
    return ""
  rows = [
    ("Revenue", summary.get("revenue")),
    ("COGS", summary.get("cogs")),
    ("Gross Profit", summary.get("gross_profit")),
    ("Payroll", summary.get("payroll")),
    ("Marketing", summary.get("marketing")),
    ("Other Opex", summary.get("other_opex")),
    ("EBITDA", summary.get("ebitda")),
    ("Interest", summary.get("interest")),
    ("Taxes", summary.get("taxes")),
    ("Net Income", summary.get("net_income")),
  ]
  lines = [
    "| Line Item | Year 1 |",
    "| --- | ---: |",
  ]
  for label, value in rows:
    lines.append(f"| {label} | {_format_currency(value)} |")
  forecast_table = _build_quarterly_ebitda_forecast_table(forecast_quarters)
  if forecast_table:
    lines.extend(["", forecast_table])
  return "\n".join(lines)
