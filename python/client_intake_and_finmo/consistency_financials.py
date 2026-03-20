from __future__ import annotations

from typing import Any, Dict, Optional


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
  cogs = _safe_float(financials.get("cogs_total_year1"))
  if cogs <= 0:
    cogs = _safe_float(financials.get("current_cogs"))
  gross_profit = revenue - cogs
  payroll = _safe_float(financials.get("payroll_total_year1"))
  if payroll <= 0:
    payroll = _safe_float(financials.get("current_payroll"))
  marketing = _safe_float(financials.get("marketing_total_year1"))
  rent_annualized = _safe_float(financials.get("monthly_rent_expense")) * 12.0
  other_opex_non_rent = _safe_float(financials.get("other_operating_expense"))
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


def build_consistency_financial_table(summary: Dict[str, Any]) -> str:
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
  return "\n".join(lines)
