from __future__ import annotations

from openpyxl.styles import Font, PatternFill

from .checks_sheet import build_checks_sheet
from .data import DraftWorkbookData, validate_draft_data
from .excel_utils import (
  CASH_EQUITY_SHEET,
  CHECKS_SHEET,
  FINMO_SHEET,
  MODEL_INPUT_SHEET,
  WorkbookBuildContext,
  create_workbook,
  set_tab_colors,
)
from .finmo_sheet import build_finmo_sheet
from .model_inputs_sheet import build_model_inputs_sheet
from .schedule_sheets import (
  build_capex_depreciation_sheet,
  build_cash_equity_sheet,
  build_debt_schedule_sheet,
  build_payroll_schedule_sheet,
  build_revenue_drivers_sheet,
  build_working_capital_sheet,
)
from .source_audit_sheet import build_source_audit_sheet


def build_client_financial_model_workbook(data: DraftWorkbookData):
  validate_draft_data(data)
  wb = create_workbook()
  wb.properties.title = f"{data.business_name} Financial Model"
  wb.properties.subject = "Client financial model workbook"
  wb.properties.creator = "Business Plan Generator"
  ctx = WorkbookBuildContext()

  build_revenue_drivers_sheet(wb, data, ctx)
  build_payroll_schedule_sheet(wb, data, ctx)
  build_debt_schedule_sheet(wb, data, ctx)
  build_capex_depreciation_sheet(wb, data, ctx)
  build_working_capital_sheet(wb, data, ctx)
  build_cash_equity_sheet(wb, data, ctx)
  build_model_inputs_sheet(wb, data, ctx)
  build_finmo_sheet(wb, data, ctx)
  build_source_audit_sheet(wb, data, ctx)
  build_checks_sheet(wb, ctx)

  wb.active = wb.sheetnames.index(FINMO_SHEET)
  set_tab_colors(wb)
  return wb

