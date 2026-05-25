from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional


if TYPE_CHECKING:  # pragma: no cover -- type-only import
  from client_intake_and_finmo.post_intake_contracts.workbook_payload_contract import (  # noqa: E501
    WorkbookPayloadContract,
  )


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
  # Phase 9 P3.9 -- optional run diagnostic payload. When set, the
  # workbook builder renders the trailing 'Diagnostics' sheet from
  # this dict. Source of truth lives in `post_intake_run_diagnostics`;
  # the workbook is a pure reflection.
  run_diagnostics: Optional[Dict[str, Any]] = None

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
    """Read the stage-ramp contract from the canonical location only.

    P3.40 bug 5 fix: collapsed a 4-path silent fallback (data.py:151-165
    before this change) to a single canonical read. The other three
    paths had no writers anywhere in the codebase (paths 1 and 4) or
    were intentional mirrors of path 2 written by the same orchestrator
    function (path 3); the silent fallback masked any failure to
    populate the canonical path.

    Canonical writer: orchestrator._build_minimal_convergence_context at
    [orchestrator.py:413](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L413)
    which stores the contract under
    ``planning_run_json["unified_convergence_context"]["business_world_contract"]["stage_ramp_contract"]``.

    Returns ``{}`` only when ``planning_run_json`` itself is absent or
    empty (workbook export ran before convergence). When
    ``planning_run_json`` is populated but the canonical path is missing
    or carries no ``quarter_ramp_grid``, raises ``RuntimeError`` so the
    operator sees the writer-side gap instead of getting silent
    zero-filled Stage Ramp Contract rows in the rendered Revenue
    Drivers sheet.
    """
    payload = self.planning_run_json if isinstance(self.planning_run_json, dict) else {}
    if not payload:
      return {}
    candidate = (
      ((payload.get("unified_convergence_context") or {}).get("business_world_contract") or {})
      .get("stage_ramp_contract")
    )
    if isinstance(candidate, dict):
      ramp_rows = candidate.get("quarter_ramp_grid")
      if isinstance(ramp_rows, list) and ramp_rows:
        return candidate
    raise RuntimeError(
      "stage_ramp_contract_missing_at_canonical_path: planning_run_json is "
      "populated but planning_run_json.unified_convergence_context."
      "business_world_contract.stage_ramp_contract has no quarter_ramp_grid. "
      "The orchestrator's _build_minimal_convergence_context "
      "(post_intake_solver/orchestrator.py:413) is the canonical writer; if "
      "this fires the upstream write was skipped or the persisted payload "
      "was overwritten."
    )

  def to_contract(self) -> "WorkbookPayloadContract":
    """P3.40 Contract 2 adapter (Commit 2). Build a
    ``WorkbookPayloadContract`` from this dataclass's 6 JSON dict
    fields.

    The dataclass's ``draft_row`` field carries the raw DB row used
    to derive ``draft_id`` / ``client_id`` / ``business_name`` for
    file naming and the cover sheet -- it is NOT part of the
    workbook payload contract (which describes what the workbook
    builder consumes to render sheets). ``draft_row`` is dropped
    here and reconstructed as ``{}`` in ``from_contract``.

    The 4 required JSON dicts (``model_input_json``, ``finmo_json``,
    ``payroll_headcount``, ``debt_schedule``) are passed through
    verbatim; the contract's ``model_validate`` performs the typed
    checks.

    ``planning_run_json`` is required on the dataclass but optional
    on the contract. An empty dict on the dataclass means
    "convergence did not run" -- the same semantic ``data.py:175-176``
    encodes with ``if not payload: return {}``. The adapter OMITS
    the field in that case so the contract's invariant 4.1
    chain-raise (which fires on present-but-empty
    planning_run_json) does not trip on an absence that is
    intentional rather than corrupt.
    """
    from client_intake_and_finmo.post_intake_contracts.workbook_payload_contract import (  # noqa: E501
      WorkbookPayloadContract,
    )
    payload: Dict[str, Any] = {
      "model_input_json": self.model_input_json,
      "finmo_json": self.finmo_json,
      "payroll_headcount": self.payroll_headcount,
      "debt_schedule": self.debt_schedule,
    }
    if self.planning_run_json:
      payload["planning_run_json"] = self.planning_run_json
    if self.run_diagnostics is not None:
      payload["run_diagnostics"] = self.run_diagnostics
    return WorkbookPayloadContract.model_validate(payload)

  @classmethod
  def from_contract(
    cls,
    contract: "WorkbookPayloadContract",
    *,
    draft_row: Optional[Dict[str, Any]] = None,
  ) -> "DraftWorkbookData":
    """P3.40 Contract 2 adapter (Commit 2). Build a
    ``DraftWorkbookData`` from a validated
    ``WorkbookPayloadContract``.

    ``draft_row`` is not stored on the contract (it is the raw DB
    row, not part of the workbook payload). Callers that have the
    DB row in scope -- the API export path -- pass it through;
    callers that don't (test fixtures, replay tooling) accept the
    default of ``{}`` and the derived ``draft_id`` / ``client_id``
    / ``business_name`` properties fall back to the values that
    live inside ``model_input_json`` / ``payroll_headcount``.

    Contract envelopes are serialised back to plain dicts via
    ``model_dump(mode="json")`` so the dataclass's existing
    consumer paths (which read dict keys) keep working unchanged.
    """
    dumped = contract.model_dump(mode="json")
    return cls(
      draft_row=dict(draft_row or {}),
      model_input_json=dumped["model_input_json"],
      finmo_json=dumped["finmo_json"],
      payroll_headcount=dumped["payroll_headcount"],
      debt_schedule=dumped["debt_schedule"],
      planning_run_json=dumped.get("planning_run_json") or {},
      run_diagnostics=dumped.get("run_diagnostics"),
    )


def draft_data_from_row(
  row: Dict[str, Any],
  *,
  run_diagnostics: Optional[Dict[str, Any]] = None,
) -> DraftWorkbookData:
  return DraftWorkbookData(
    draft_row=dict(row or {}),
    model_input_json=parse_json_object((row or {}).get("model_input_json")),
    finmo_json=parse_json_object((row or {}).get("finmo_json")),
    payroll_headcount=parse_json_object((row or {}).get("payroll_headcount")),
    debt_schedule=parse_json_object((row or {}).get("debt_schedule")),
    planning_run_json=parse_json_object((row or {}).get("planning_run_json")),
    run_diagnostics=run_diagnostics if isinstance(run_diagnostics, dict) else None,
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
