from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import date, datetime
from typing import Any, Dict, List

from .model_inputs import FinancialModelInputs, QUARTER_COUNT, _safe_float


def _parse_start_date(value: str) -> date:
  cleaned = str(value or "").strip()
  if not cleaned:
    raise ValueError("start_date is required for finmo_model")
  for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
    try:
      return datetime.strptime(cleaned, fmt).date()
    except Exception:
      continue
  raise ValueError(f"Unsupported start_date format: {value}")


def _quarter_end_for(start: date, step_index: int) -> date:
  month = start.month + (step_index * 3)
  year = start.year + ((month - 1) // 12)
  normalized_month = ((month - 1) % 12) + 1
  quarter_end_month = ((normalized_month - 1) // 3 + 1) * 3
  if quarter_end_month == 12:
    next_month = date(year + 1, 1, 1)
  else:
    next_month = date(year, quarter_end_month + 1, 1)
  return next_month.fromordinal(next_month.toordinal() - 1)


def _quarter_days(quarter_end: date) -> int:
  quarter_start_month = ((quarter_end.month - 1) // 3) * 3 + 1
  quarter_start = date(quarter_end.year, quarter_start_month, 1)
  if quarter_end.month == 12:
    next_month = date(quarter_end.year + 1, 1, 1)
  else:
    next_month = date(quarter_end.year, quarter_end.month + 1, 1)
  return (next_month - quarter_start).days


FORMULA_REGISTRY: Dict[str, str] = {
  "Accounting Equation Check": "Total Assets - Total Liabilities & Equity",
  "Revenue": "SUM(all product revenue) where product revenue = capacity_units * unit_price * utilization",
  "Cost of Goods Sold": "Revenue * expenses::Cost of Goods Sold",
  "Gross Profit": "Revenue - Cost of Goods Sold",
  "Marketing": "Revenue * expenses::Marketing",
  "Research & Development": "Revenue * expenses::Research & Development",
  "Lease/Rent": "expenses::Lease",
  "Payroll": "expenses::Payroll",
  "General & Administrative": "Revenue * expenses::General & Administrative",
  "EBITDA": "Gross Profit - SUM(Marketing, Research & Development, Lease/Rent, Payroll, General & Administrative)",
  "Interest": "Debt Schedule Interest Expense = AVERAGE(Debt Opening Balance, Debt Closing Balance) * expenses::Interest Rate",
  "Depreciation": "Revenue * expenses::Depreciation",
  "Taxes": "Revenue * expenses::Taxes",
  "Net Income": "EBITDA - SUM(Interest, Depreciation, Taxes)",
  "Cash": "Ending Cash",
  "Accounts Receivable": "(balance_sheet::Accounts Receivable Days / days_in_quarter) * Revenue",
  "Inventory": "(balance_sheet::Inventory Days / days_in_quarter) * Cost of Goods Sold",
  "Current Assets": "Cash + Accounts Receivable + Inventory",
  "PPE": "previous PPE + schedules::Capital Expenditures - Depreciation",
  "Accumulated Depreciation": "previous Accumulated Depreciation - Depreciation",
  "Total Assets": "Current Assets + PPE",
  "Accounts Payable": "(balance_sheet::Accounts Payable Days / days_in_quarter) * SUM(Marketing, Research & Development, Lease/Rent, Payroll, General & Administrative)",
  "Prepaid Expenses": "Revenue * balance_sheet::Prepaid Expenses",
  "Short Term Debt": "balance_sheet::Short Term Debt (% of LTD) * Long Term Debt",
  "Deferred Revenue": "balance_sheet::Deferred Revnue * Revenue",
  "Current Liabilities": "SUM(Accounts Payable, Prepaid Expenses, Short Term Debt, Deferred Revenue)",
  "Long Term Debt": "Debt Schedule Closing Balance",
  "Total Liabilities": "Current Liabilities + Long Term Debt + Capital Lease Closing Balance (Total)",
  "Owner's Capital": "balance_sheet::Owner's Capital",
  "Retained Earnings": "previous Retained Earnings + Net Income",
  "Other Equity": "balance_sheet::Other Equity",
  "Total Equity": "SUM(Owner's Capital, Retained Earnings, Other Equity)",
  "Total Liabilities & Equity": "Total Liabilities + Total Equity",
  "Beginning Cash": "previous Ending Cash",
  "Changes in Current Assets": "-((Accounts Receivable + Inventory)_t - (Accounts Receivable + Inventory)_(t-1))",
  "Changes in Current Liabilites": "Current Liabilities_t - Current Liabilities_(t-1)",
  "Operating Cash Flow": "Net Income + Depreciation + Changes in Current Assets + Changes in Current Liabilites",
  "Capital Expenditures": "schedules::Capital Expenditures",
  "Investing Cash Flow": "-Capital Expenditures",
  "Dept Receive(Repay)": "Long Term Debt_t - Long Term Debt_(t-1)",
  "Equity": "(Owner's Capital_t - Owner's Capital_(t-1)) + (Other Equity_t - Other Equity_(t-1))",
  "Financing Cash Flow": "Dept Receive(Repay) + Equity + Capital Lease Additions - Capital Lease Principal Repayments",
  "Net Cash Flow": "Operating Cash Flow + Investing Cash Flow + Financing Cash Flow",
  "Ending Cash": "Beginning Cash + Net Cash Flow",
  "Debt Schedule / Opening Balance": "previous Debt Schedule Closing Balance, seeded from schedules.debt_opening_balance_seed",
  "Debt Schedule / Plus: Additions (repayments), net": "schedules::Plus: Additions (repayments), net",
  "Debt Schedule / Closing Balance": "Debt Opening Balance + Plus: Additions (repayments), net",
  "Debt Schedule / Interest Expense": "AVERAGE(Debt Opening Balance, Debt Closing Balance) * expenses::Interest Rate",
  "Debt Schedule / Interest Rate": "expenses::Interest Rate",
  "Capital Leases Schedule / Opening Balance (Total)": "previous Capital Lease Closing Balance (Total), seeded from schedules.lease_opening_balance_seed",
  "Capital Leases Schedule / Less: Principal Repayments": "schedules::Less: Principal Repayments",
  "Capital Leases Schedule / Plus: Net Additions": "schedules::Plus: Net Additions",
  "Capital Leases Schedule / Closing Balance (Total)": "max(0, Capital Lease Opening Balance (Total) + Plus: Net Additions - Less: Principal Repayments)",
}


@dataclass(slots=True)
class FinmoQuarterResult:
  quarter_index: int
  year: int
  quarter: int
  date: str
  days_in_quarter: int
  accounting_equation_check: float
  revenue: float
  cost_of_goods_sold: float
  gross_profit: float
  marketing: float
  research_and_development: float
  lease_rent: float
  payroll: float
  general_and_administrative: float
  ebitda: float
  interest: float
  depreciation: float
  taxes: float
  net_income: float
  cash: float
  accounts_receivable: float
  inventory: float
  current_assets: float
  ppe: float
  accumulated_depreciation: float
  total_assets: float
  accounts_payable: float
  prepaid_expenses: float
  short_term_debt: float
  deferred_revenue: float
  current_liabilities: float
  long_term_debt: float
  total_liabilities: float
  owners_capital: float
  retained_earnings: float
  other_equity: float
  total_equity: float
  total_liabilities_and_equity: float
  beginning_cash: float
  changes_in_current_assets: float
  changes_in_current_liabilities: float
  operating_cash_flow: float
  capital_expenditures: float
  investing_cash_flow: float
  debt_receive_repay: float
  equity: float
  financing_cash_flow: float
  net_cash_flow: float
  ending_cash: float
  debt_opening_balance: float
  debt_additions_repayments_net: float
  debt_closing_balance: float
  debt_interest_expense: float
  debt_interest_rate: float
  lease_opening_balance_total: float
  lease_principal_repayments: float
  lease_net_additions: float
  lease_closing_balance_total: float

  def to_dict(self) -> Dict[str, Any]:
    return {
      field_def.name: (
        round(getattr(self, field_def.name), 6)
        if isinstance(getattr(self, field_def.name), float)
        else getattr(self, field_def.name)
      )
      for field_def in fields(self)
    }


@dataclass(slots=True)
class FinmoModelResult:
  quarter_results: List[FinmoQuarterResult] = field(default_factory=list)

  def quarter_rows(self, *, include_stub: bool = False) -> List[Dict[str, Any]]:
    rows = self.quarter_results if include_stub else self.quarter_results[1:]
    return [item.to_dict() for item in rows]

  def formula_registry(self) -> Dict[str, str]:
    return dict(FORMULA_REGISTRY)


def _row_value(book: FinancialModelInputs, section: str, label: str, quarter_index: int) -> float:
  target = {
    "expenses": book.expense_rows,
    "balance_sheet": book.balance_sheet_rows,
    "schedules": book.schedule_rows,
  }[section]
  row = target.get(label)
  if row is None:
    return 0.0
  return row.get_value(quarter_index)


def calculate_finmo_model(model_inputs: FinancialModelInputs) -> FinmoModelResult:
  start = _parse_start_date(model_inputs.start_date)
  quarter_results: List[FinmoQuarterResult] = [
    FinmoQuarterResult(
      quarter_index=0,
      year=start.year,
      quarter=0,
      date=start.isoformat(),
      days_in_quarter=0,
      accounting_equation_check=0.0,
      revenue=0.0,
      cost_of_goods_sold=0.0,
      gross_profit=0.0,
      marketing=0.0,
      research_and_development=0.0,
      lease_rent=0.0,
      payroll=0.0,
      general_and_administrative=0.0,
      ebitda=0.0,
      interest=0.0,
      depreciation=0.0,
      taxes=0.0,
      net_income=0.0,
      cash=model_inputs.cash_opening_balance_seed,
      accounts_receivable=model_inputs.accounts_receivable_opening_balance_seed,
      inventory=model_inputs.inventory_opening_balance_seed,
      current_assets=model_inputs.cash_opening_balance_seed + model_inputs.accounts_receivable_opening_balance_seed + model_inputs.inventory_opening_balance_seed,
      ppe=model_inputs.ppe_opening_balance_seed,
      accumulated_depreciation=model_inputs.accumulated_depreciation_opening_seed,
      total_assets=model_inputs.ppe_opening_balance_seed + model_inputs.accumulated_depreciation_opening_seed,
      accounts_payable=model_inputs.accounts_payable_opening_balance_seed,
      prepaid_expenses=0.0,
      short_term_debt=model_inputs.short_term_debt_opening_balance_seed,
      deferred_revenue=0.0,
      current_liabilities=model_inputs.accounts_payable_opening_balance_seed + model_inputs.short_term_debt_opening_balance_seed,
      long_term_debt=0.0,
      total_liabilities=model_inputs.debt_opening_balance_seed + model_inputs.lease_opening_balance_seed,
      owners_capital=max(
        0.0,
        (
          model_inputs.cash_opening_balance_seed
          + model_inputs.accounts_receivable_opening_balance_seed
          + model_inputs.inventory_opening_balance_seed
          + model_inputs.ppe_opening_balance_seed
          + model_inputs.accumulated_depreciation_opening_seed
        ) - (
          model_inputs.accounts_payable_opening_balance_seed
          + model_inputs.short_term_debt_opening_balance_seed
          + model_inputs.debt_opening_balance_seed
          + model_inputs.lease_opening_balance_seed
        ),
      ),
      retained_earnings=0.0,
      other_equity=0.0,
      total_equity=max(
        0.0,
        (
          model_inputs.cash_opening_balance_seed
          + model_inputs.accounts_receivable_opening_balance_seed
          + model_inputs.inventory_opening_balance_seed
          + model_inputs.ppe_opening_balance_seed
          + model_inputs.accumulated_depreciation_opening_seed
        ) - (
          model_inputs.accounts_payable_opening_balance_seed
          + model_inputs.short_term_debt_opening_balance_seed
          + model_inputs.debt_opening_balance_seed
          + model_inputs.lease_opening_balance_seed
        ),
      ),
      total_liabilities_and_equity=(
        model_inputs.accounts_payable_opening_balance_seed
        + model_inputs.short_term_debt_opening_balance_seed
        + model_inputs.debt_opening_balance_seed
        + model_inputs.lease_opening_balance_seed
        + max(
          0.0,
          (
            model_inputs.cash_opening_balance_seed
            + model_inputs.accounts_receivable_opening_balance_seed
            + model_inputs.inventory_opening_balance_seed
            + model_inputs.ppe_opening_balance_seed
            + model_inputs.accumulated_depreciation_opening_seed
          ) - (
            model_inputs.accounts_payable_opening_balance_seed
            + model_inputs.short_term_debt_opening_balance_seed
            + model_inputs.debt_opening_balance_seed
            + model_inputs.lease_opening_balance_seed
          ),
        )
      ),
      beginning_cash=model_inputs.cash_opening_balance_seed,
      changes_in_current_assets=0.0,
      changes_in_current_liabilities=0.0,
      operating_cash_flow=0.0,
      capital_expenditures=0.0,
      investing_cash_flow=0.0,
      debt_receive_repay=0.0,
      equity=0.0,
      financing_cash_flow=0.0,
      net_cash_flow=0.0,
      ending_cash=0.0,
      debt_opening_balance=model_inputs.debt_opening_balance_seed,
      debt_additions_repayments_net=0.0,
      debt_closing_balance=model_inputs.debt_opening_balance_seed,
      debt_interest_expense=0.0,
      debt_interest_rate=0.0,
      lease_opening_balance_total=model_inputs.lease_opening_balance_seed,
      lease_principal_repayments=0.0,
      lease_net_additions=0.0,
      lease_closing_balance_total=model_inputs.lease_opening_balance_seed,
    )
  ]

  previous_ending_cash = model_inputs.cash_opening_balance_seed
  previous_accounts_receivable = model_inputs.accounts_receivable_opening_balance_seed
  previous_inventory = model_inputs.inventory_opening_balance_seed
  previous_current_liabilities = model_inputs.accounts_payable_opening_balance_seed + model_inputs.short_term_debt_opening_balance_seed
  previous_ppe = model_inputs.ppe_opening_balance_seed
  previous_long_term_debt = model_inputs.debt_opening_balance_seed
  previous_owners_capital = max(
    0.0,
    (
      model_inputs.cash_opening_balance_seed
      + model_inputs.accounts_receivable_opening_balance_seed
      + model_inputs.inventory_opening_balance_seed
      + model_inputs.ppe_opening_balance_seed
      + model_inputs.accumulated_depreciation_opening_seed
    ) - (
      model_inputs.accounts_payable_opening_balance_seed
      + model_inputs.short_term_debt_opening_balance_seed
      + model_inputs.debt_opening_balance_seed
      + model_inputs.lease_opening_balance_seed
    ),
  )
  previous_other_equity = 0.0
  previous_retained_earnings = 0.0
  previous_accumulated_depreciation = model_inputs.accumulated_depreciation_opening_seed
  previous_debt_closing_balance = model_inputs.debt_opening_balance_seed
  previous_lease_closing_balance = model_inputs.lease_opening_balance_seed

  for quarter in model_inputs.quarters:
    quarter_end = _quarter_end_for(start, quarter.quarter_index)
    quarter_number = ((quarter_end.month - 1) // 3) + 1
    days_in_quarter = _quarter_days(quarter_end)

    revenue = quarter.revenue
    cogs = revenue * quarter.expenses.cogs_percent
    gross_profit = revenue - cogs
    marketing = revenue * quarter.expenses.marketing_percent
    r_and_d = revenue * quarter.expenses.r_and_d_percent
    lease_rent = quarter.expenses.lease_amount
    payroll = quarter.expenses.payroll_amount
    g_and_a = revenue * quarter.expenses.g_and_a_percent
    ebitda = gross_profit - (marketing + r_and_d + lease_rent + payroll + g_and_a)

    debt_opening = previous_debt_closing_balance
    debt_additions = _row_value(model_inputs, "schedules", "Plus: Additions (repayments), net", quarter.quarter_index)
    debt_closing = debt_opening + debt_additions
    interest_rate = quarter.expenses.interest_rate
    interest = ((debt_opening + debt_closing) / 2.0) * interest_rate

    depreciation = quarter.expenses.depreciation_percent * max(0.0, previous_ppe)
    taxes = revenue * quarter.expenses.tax_percent
    net_income = ebitda - (interest + depreciation + taxes)

    accounts_receivable = (_row_value(model_inputs, "balance_sheet", "Accounts Receivable Days", quarter.quarter_index) / max(1, days_in_quarter)) * revenue
    inventory = (_row_value(model_inputs, "balance_sheet", "Inventory Days", quarter.quarter_index) / max(1, days_in_quarter)) * cogs
    prepaid_expenses = revenue * _row_value(model_inputs, "balance_sheet", "Prepaid Expenses", quarter.quarter_index)
    deferred_revenue = revenue * _row_value(model_inputs, "balance_sheet", "Deferred Revnue", quarter.quarter_index)

    lease_opening = previous_lease_closing_balance
    lease_principal = _row_value(model_inputs, "schedules", "Less: Principal Repayments", quarter.quarter_index)
    lease_additions = _row_value(model_inputs, "schedules", "Plus: Net Additions", quarter.quarter_index)
    lease_closing = max(0.0, lease_opening + lease_additions - lease_principal)
    capex = _row_value(model_inputs, "schedules", "Capital Expenditures", quarter.quarter_index)
    depreciation = min(depreciation, max(0.0, previous_ppe))
    ppe = max(0.0, previous_ppe + capex - depreciation)
    accumulated_depreciation = previous_accumulated_depreciation - depreciation

    accounts_payable = (_row_value(model_inputs, "balance_sheet", "Accounts Payable Days", quarter.quarter_index) / max(1, days_in_quarter)) * (marketing + r_and_d + lease_rent + payroll + g_and_a)
    short_term_debt = _row_value(model_inputs, "balance_sheet", "Short Term Debt (% of LTD)", quarter.quarter_index) * debt_closing
    current_liabilities = accounts_payable + prepaid_expenses + short_term_debt + deferred_revenue
    long_term_debt = debt_closing
    total_liabilities = current_liabilities + long_term_debt + lease_closing

    owners_capital = _row_value(model_inputs, "balance_sheet", "Owner's Capital", quarter.quarter_index)
    other_equity = _row_value(model_inputs, "balance_sheet", "Other Equity", quarter.quarter_index)
    retained_earnings = previous_retained_earnings + net_income
    total_equity = owners_capital + retained_earnings + other_equity
    total_liabilities_and_equity = total_liabilities + total_equity

    beginning_cash = previous_ending_cash
    changes_in_current_assets = -((accounts_receivable + inventory) - (previous_accounts_receivable + previous_inventory))
    changes_in_current_liabilities = current_liabilities - previous_current_liabilities
    operating_cash_flow = net_income + depreciation + changes_in_current_assets + changes_in_current_liabilities
    capital_expenditures = capex
    investing_cash_flow = -capex
    debt_receive_repay = long_term_debt - previous_long_term_debt
    equity = (owners_capital - previous_owners_capital) + (other_equity - previous_other_equity)
    financing_cash_flow = debt_receive_repay + equity + lease_additions - lease_principal
    net_cash_flow = operating_cash_flow + investing_cash_flow + financing_cash_flow
    ending_cash = beginning_cash + net_cash_flow
    cash = ending_cash

    current_assets = cash + accounts_receivable + inventory
    total_assets = current_assets + ppe

    quarter_results.append(
      FinmoQuarterResult(
        quarter_index=quarter.quarter_index,
        year=quarter_end.year,
        quarter=quarter_number,
        date=quarter_end.isoformat(),
        days_in_quarter=days_in_quarter,
        accounting_equation_check=total_assets - total_liabilities_and_equity,
        revenue=revenue,
        cost_of_goods_sold=cogs,
        gross_profit=gross_profit,
        marketing=marketing,
        research_and_development=r_and_d,
        lease_rent=lease_rent,
        payroll=payroll,
        general_and_administrative=g_and_a,
        ebitda=ebitda,
        interest=interest,
        depreciation=depreciation,
        taxes=taxes,
        net_income=net_income,
        cash=ending_cash,
        accounts_receivable=accounts_receivable,
        inventory=inventory,
        current_assets=current_assets,
        ppe=ppe,
        accumulated_depreciation=accumulated_depreciation,
        total_assets=total_assets,
        accounts_payable=accounts_payable,
        prepaid_expenses=prepaid_expenses,
        short_term_debt=short_term_debt,
        deferred_revenue=deferred_revenue,
        current_liabilities=current_liabilities,
        long_term_debt=long_term_debt,
        total_liabilities=total_liabilities,
        owners_capital=owners_capital,
        retained_earnings=retained_earnings,
        other_equity=other_equity,
        total_equity=total_equity,
        total_liabilities_and_equity=total_liabilities_and_equity,
        beginning_cash=beginning_cash,
        changes_in_current_assets=changes_in_current_assets,
        changes_in_current_liabilities=changes_in_current_liabilities,
        operating_cash_flow=operating_cash_flow,
        capital_expenditures=capital_expenditures,
        investing_cash_flow=investing_cash_flow,
        debt_receive_repay=debt_receive_repay,
        equity=equity,
        financing_cash_flow=financing_cash_flow,
        net_cash_flow=net_cash_flow,
        ending_cash=ending_cash,
        debt_opening_balance=debt_opening,
        debt_additions_repayments_net=debt_additions,
        debt_closing_balance=debt_closing,
        debt_interest_expense=interest,
        debt_interest_rate=interest_rate,
        lease_opening_balance_total=lease_opening,
        lease_principal_repayments=lease_principal,
        lease_net_additions=lease_additions,
        lease_closing_balance_total=lease_closing,
      )
    )

    previous_ending_cash = ending_cash
    previous_accounts_receivable = accounts_receivable
    previous_inventory = inventory
    previous_current_liabilities = current_liabilities
    previous_ppe = ppe
    previous_long_term_debt = long_term_debt
    previous_owners_capital = owners_capital
    previous_other_equity = other_equity
    previous_retained_earnings = retained_earnings
    previous_accumulated_depreciation = accumulated_depreciation
    previous_debt_closing_balance = debt_closing
    previous_lease_closing_balance = lease_closing

  return FinmoModelResult(quarter_results=quarter_results)
