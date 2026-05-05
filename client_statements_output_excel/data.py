from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


QUARTER_COUNT = 20
PERIOD_COUNT = 21


def text(value: Any) -> str:
  return str(value or "").strip()


def number(value: Any, default: float = 0.0) -> float:
  if value in {None, ""}:
    return default
  try:
    return float(value)
  except Exception:
    return default


def parse_json_object(raw: Any) -> Dict[str, Any]:
  if isinstance(raw, dict):
    return dict(raw)
  if raw is None:
    return {}
  try:
    parsed = json.loads(str(raw))
  except Exception:
    return {}
  return parsed if isinstance(parsed, dict) else {}


def values_21(values: Any) -> List[float]:
  items = [number(item) for item in (values or [])] if isinstance(values, list) else []
  if len(items) >= PERIOD_COUNT:
    return items[:PERIOD_COUNT]
  if len(items) == QUARTER_COUNT:
    return [0.0] + items
  return (items + [0.0 for _ in range(PERIOD_COUNT)])[:PERIOD_COUNT]


def live_values(values: Any) -> List[float]:
  return values_21(values)[1:]


def row_by_label(rows: Any) -> Dict[str, Dict[str, Any]]:
  result: Dict[str, Dict[str, Any]] = {}
  if not isinstance(rows, list):
    return result
  for row in rows:
    if not isinstance(row, dict):
      continue
    label = text(row.get("label"))
    if label:
      result[label] = row
  return result


@dataclass
class DraftWorkbookData:
  draft_row: Dict[str, Any]
  model_input_json: Dict[str, Any]
  finmo_json: Dict[str, Any]
  payroll_headcount: Dict[str, Any]
  debt_schedule: Dict[str, Any]
  planning_run_json: Dict[str, Any]

  @property
  def draft_id(self) -> str:
    return text(self.draft_row.get("draft_id") or self.model_input_json.get("draft_id"))

  @property
  def client_id(self) -> str:
    return text(self.draft_row.get("client_id") or self.payroll_headcount.get("client_id"))

  @property
  def business_name(self) -> str:
    return (
      text(self.draft_row.get("business_name"))
      or text(self.model_input_json.get("business_name"))
      or "Client"
    )

  @property
  def periods(self) -> List[Dict[str, Any]]:
    quarter_rows = self.finmo_json.get("quarter_rows")
    if isinstance(quarter_rows, list) and quarter_rows:
      periods: List[Dict[str, Any]] = []
      for idx, item in enumerate(quarter_rows[:PERIOD_COUNT]):
        row = item if isinstance(item, dict) else {}
        periods.append(
          {
            "slot_index": idx,
            "quarter": row.get("quarter") if idx else 0,
            "year": row.get("year"),
            "date": row.get("date"),
            "days_in_quarter": row.get("days_in_quarter"),
            "is_stub": idx == 0,
          }
        )
      if len(periods) >= PERIOD_COUNT:
        return periods
    periods = self.finmo_json.get("periods")
    if isinstance(periods, list) and periods:
      return [item if isinstance(item, dict) else {} for item in periods[:PERIOD_COUNT]]
    model_periods = self.model_input_json.get("periods")
    if isinstance(model_periods, list) and model_periods:
      return [item if isinstance(item, dict) else {} for item in model_periods[:PERIOD_COUNT]]
    return [{"slot_index": i, "quarter": i, "year": "", "date": ""} for i in range(PERIOD_COUNT)]

  @property
  def sections(self) -> Dict[str, Any]:
    sections = self.model_input_json.get("sections")
    return sections if isinstance(sections, dict) else {}

  @property
  def revenue_rows(self) -> List[Dict[str, Any]]:
    rows = self.sections.get("revenue")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

  @property
  def expense_rows(self) -> List[Dict[str, Any]]:
    rows = self.sections.get("expenses")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

  @property
  def balance_sheet_rows(self) -> List[Dict[str, Any]]:
    rows = self.sections.get("balance_sheet")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

  @property
  def schedules(self) -> Dict[str, Any]:
    schedules = self.sections.get("schedules")
    return schedules if isinstance(schedules, dict) else {}

  @property
  def schedule_rows(self) -> List[Dict[str, Any]]:
    rows = self.schedules.get("rows")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

  @property
  def stage_ramp_contract(self) -> Dict[str, Any]:
    payload = self.planning_run_json if isinstance(self.planning_run_json, dict) else {}
    candidates = [
      payload.get("stage_ramp_contract"),
      ((payload.get("unified_convergence_context") or {}).get("business_world_contract") or {}).get("stage_ramp_contract"),
      ((payload.get("unified_convergence_context") or {}).get("planning_context_summary") or {}).get("stage_ramp_contract"),
      ((payload.get("first_pass_handoff") or {}).get("business_world_contract") or {}).get("stage_ramp_contract"),
    ]
    for candidate in candidates:
      if not isinstance(candidate, dict):
        continue
      ramp_rows = candidate.get("quarter_ramp_grid")
      if isinstance(ramp_rows, list) and ramp_rows:
        return candidate
    return {}


def draft_data_from_row(row: Dict[str, Any]) -> DraftWorkbookData:
  return DraftWorkbookData(
    draft_row=dict(row or {}),
    model_input_json=parse_json_object((row or {}).get("model_input_json")),
    finmo_json=parse_json_object((row or {}).get("finmo_json")),
    payroll_headcount=parse_json_object((row or {}).get("payroll_headcount")),
    debt_schedule=parse_json_object((row or {}).get("debt_schedule")),
    planning_run_json=parse_json_object((row or {}).get("planning_run_json")),
  )


def validate_draft_data(data: DraftWorkbookData) -> None:
  missing: List[str] = []
  if not data.model_input_json:
    missing.append("model_input_json")
  if not data.finmo_json:
    missing.append("finmo_json")
  if not data.payroll_headcount:
    missing.append("payroll_headcount")
  if not data.debt_schedule:
    missing.append("debt_schedule")
  if missing:
    raise RuntimeError("Draft is missing workbook export inputs: " + ", ".join(missing))
