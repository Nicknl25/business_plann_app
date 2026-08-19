from __future__ import annotations

from openpyxl.styles import Font, PatternFill

from .calc_sheet import build_calc_sheet
from .checks_sheet import build_checks_sheet
from .cover_sheet import COVER_SHEET, build_cover_sheet
from .dashboard_sheet import build_dashboard_sheet
from . import design
from .data import DraftWorkbookData
from .diagnostics_sheet import build_diagnostics_sheet
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
  # P3.40 Contract 2 Commit 3 -- consumer-side boundary gate.
  # Replaces the legacy ``validate_draft_data(data)`` call (which only
  # checked field presence) with a typed contract validation. On
  # invalid input the gate raises ``ContractViolation``; the API
  # entry point at intake_consult.py:7655 catches it as a generic
  # Exception and logs str(exc), so the failure surfaces as a
  # structured boundary error rather than mid-build sheet-builder
  # crashes. The legacy ``validate_draft_data`` function is left in
  # ``data.py`` for now (spec §8 R9 follow-up deletes it).
  #
  # Lazy import so workbook_builder.py remains importable in
  # environments where the python/ contracts package isn't on
  # sys.path (the API export path adds it; some test paths do not).
  from client_intake_and_finmo.post_intake_contracts.enforcement import (
    SIDE_CONSUMER,
    validate_workbook_payload_at_boundary,
  )
  payload: dict = {
    "model_input_json": data.model_input_json,
    "finmo_json": data.finmo_json,
    "payroll_headcount": data.payroll_headcount,
    "debt_schedule": data.debt_schedule,
  }
  if data.planning_run_json:
    payload["planning_run_json"] = data.planning_run_json
  if data.run_diagnostics is not None:
    payload["run_diagnostics"] = data.run_diagnostics
  validate_workbook_payload_at_boundary(payload, side=SIDE_CONSUMER)

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
  # W2 (2026-08-18): Dashboard sits right after FINMO; wb.active stays FINMO.
  # The hidden Calc sheet is the dashboard's data engine, so it is built
  # first - the Dashboard only reads from it.
  build_calc_sheet(wb, data, ctx)
  build_dashboard_sheet(wb, data, ctx)
  build_source_audit_sheet(wb, data, ctx)
  build_checks_sheet(wb, ctx)

  # Phase 9 P3.9 -- Diagnostics sheet appended LAST. Additive; never
  # modifies or replaces any other sheet. Failures inside this builder
  # are caught so they don't take down the rest of the workbook.
  try:
    build_diagnostics_sheet(wb, data, ctx, data.run_diagnostics)
  except Exception:
    pass

  # X1 DESIGN SYSTEM (2026-08-18): the cover is built LAST (it links to the
  # sheets that exist) but READS first. Build order above is unchanged - the
  # dashboard still needs FINMO's row registry - and only the reading order
  # moves, per Nick's Q6 ruling.
  build_cover_sheet(wb, data)
  design.apply_sheet_order(wb)
  wb.active = wb.sheetnames.index(COVER_SHEET)
  set_tab_colors(wb)
  return wb

