from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from financial_model_engine.model_inputs import FinancialModelInputs, QUARTER_COUNT
from financial_model_engine.solver import LeverControl, OutputTarget, SolverOptions, solve_financial_model

_GRID_EXCLUDED_LEVER_IDS = {
  "balance_sheet::PPE $ (Excluding Capital Leases)",
  "balance_sheet::Accumulated Depreciation",
}


def float_or_none(value: Any) -> Optional[float]:
  if value in {None, ""}:
    return None
  try:
    return float(value)
  except Exception:
    return None


def has_material_values(values: Sequence[Any]) -> bool:
  for raw_value in values or []:
    number = float_or_none(raw_value)
    if number is not None and abs(number) > 1e-12:
      return True
  return False


def extract_solver_grid_rows(
  *,
  model_input_json: Dict[str, Any],
  baseline_outputs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  sections = model_input_json.get("sections") if isinstance(model_input_json.get("sections"), dict) else {}
  rows: List[Dict[str, Any]] = []

  for item in sections.get("revenue") or []:
    if not isinstance(item, dict):
      continue
    lever_id = str(item.get("lever_id") or "").strip()
    if not lever_id:
      continue
    values = list(item.get("values") or [])
    if len(values) == QUARTER_COUNT + 1:
      values = values[1:]
    if not has_material_values(values):
      continue
    rows.append(
      {
        "row_id": lever_id,
        "row_type": "lever",
        "section": "revenue",
        "label": str(item.get("label") or lever_id),
        "baseline_values": values[:QUARTER_COUNT],
      }
    )

  for section_name in ("expenses", "balance_sheet"):
    for item in sections.get(section_name) or []:
      if not isinstance(item, dict):
        continue
      if not bool(item.get("controller_write")):
        continue
      lever_id = str(item.get("lever_id") or "").strip()
      if not lever_id or lever_id in _GRID_EXCLUDED_LEVER_IDS:
        continue
      values = list(item.get("values") or [])
      if len(values) == QUARTER_COUNT + 1:
        values = values[1:]
      rows.append(
        {
          "row_id": lever_id,
          "row_type": "lever",
          "section": section_name,
          "label": str(item.get("label") or lever_id),
          "baseline_values": values[:QUARTER_COUNT],
        }
      )

  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  for item in schedules.get("rows") or []:
    if not isinstance(item, dict):
      continue
    if not bool(item.get("controller_write")):
      continue
    lever_id = str(item.get("lever_id") or "").strip()
    if not lever_id or lever_id in _GRID_EXCLUDED_LEVER_IDS:
      continue
    values = list(item.get("values") or [])
    if len(values) == QUARTER_COUNT + 1:
      values = values[1:]
    rows.append(
      {
        "row_id": lever_id,
        "row_type": "lever",
        "section": "schedules",
        "label": str(item.get("label") or lever_id),
        "baseline_values": values[:QUARTER_COUNT],
      }
    )

  for metric in ("Revenue", "EBITDA", "Cash"):
    metric_key = {"Revenue": "revenue", "EBITDA": "ebitda", "Cash": "ending_cash"}[metric]
    rows.append(
      {
        "row_id": metric,
        "row_type": "output",
        "section": "output",
        "label": metric,
        "baseline_values": [row.get(metric_key) for row in baseline_outputs[:QUARTER_COUNT]],
      }
    )

  return rows


def validate_solver_grid_response(
  *,
  requested_rows: List[Dict[str, Any]],
  response_json: Dict[str, Any],
) -> Dict[str, Any]:
  requested_ids = [str(item.get("row_id") or "") for item in requested_rows]
  requested_id_set = set(requested_ids)
  returned_rows = response_json.get("rows") if isinstance(response_json.get("rows"), list) else []
  returned_by_id: Dict[str, Dict[str, Any]] = {}
  duplicates: List[str] = []
  for item in returned_rows:
    if not isinstance(item, dict):
      continue
    row_id = str(item.get("row_id") or "").strip()
    if not row_id:
      continue
    if row_id in returned_by_id:
      duplicates.append(row_id)
    returned_by_id[row_id] = item

  missing_rows = [row_id for row_id in requested_ids if row_id not in returned_by_id]
  extra_rows = sorted(row_id for row_id in returned_by_id if row_id not in requested_id_set)

  malformed_rows: List[str] = []
  flat_rows: List[str] = []
  for row_id, item in returned_by_id.items():
    quarter_bands = item.get("quarter_bands") if isinstance(item.get("quarter_bands"), list) else []
    if len(quarter_bands) != QUARTER_COUNT:
      malformed_rows.append(f"{row_id}::quarter_count={len(quarter_bands)}")
      continue
    seen_quarters = []
    identical_pairs = []
    for band in quarter_bands:
      if not isinstance(band, dict):
        malformed_rows.append(f"{row_id}::non_object_band")
        break
      quarter_index = int(band.get("quarter_index") or 0)
      minimum = float_or_none(band.get("min_value"))
      maximum = float_or_none(band.get("max_value"))
      if quarter_index < 1 or quarter_index > QUARTER_COUNT:
        malformed_rows.append(f"{row_id}::quarter={quarter_index}")
        break
      if minimum is None or maximum is None or minimum > maximum:
        malformed_rows.append(f"{row_id}::invalid_band::Q{quarter_index}")
        break
      seen_quarters.append(quarter_index)
      identical_pairs.append((round(minimum, 6), round(maximum, 6)))
    if sorted(seen_quarters) != list(range(1, QUARTER_COUNT + 1)):
      malformed_rows.append(f"{row_id}::quarter_indexes_invalid")
      continue
    if len(set(identical_pairs)) == 1:
      flat_rows.append(row_id)

  return {
    "requested_row_count": len(requested_rows),
    "returned_row_count": len(returned_by_id),
    "missing_rows": missing_rows,
    "extra_rows": extra_rows,
    "duplicate_rows": duplicates,
    "malformed_rows": malformed_rows,
    "flat_rows": flat_rows,
  }


def controls_from_solver_grid(grid_json: Dict[str, Any]) -> List[LeverControl]:
  controls: List[LeverControl] = []
  for row in grid_json.get("rows") or []:
    if not isinstance(row, dict):
      continue
    if str(row.get("row_type") or "").strip().lower() != "lever":
      continue
    lever_id = str(row.get("row_id") or "").strip()
    if not lever_id:
      continue
    for band in row.get("quarter_bands") or []:
      if not isinstance(band, dict):
        continue
      quarter_index = int(band.get("quarter_index") or 0)
      if quarter_index < 1:
        continue
      controls.append(
        LeverControl(
          lever_id=lever_id,
          quarter_start=quarter_index,
          quarter_end=quarter_index,
          min_value=float_or_none(band.get("min_value")),
          max_value=float_or_none(band.get("max_value")),
        )
      )
  return controls


def targets_from_solver_grid(grid_json: Dict[str, Any]) -> List[OutputTarget]:
  targets: List[OutputTarget] = []
  for row in grid_json.get("rows") or []:
    if not isinstance(row, dict):
      continue
    if str(row.get("row_type") or "").strip().lower() != "output":
      continue
    metric = str(row.get("row_id") or "").strip()
    if not metric:
      continue
    for band in row.get("quarter_bands") or []:
      if not isinstance(band, dict):
        continue
      quarter_index = int(band.get("quarter_index") or 0)
      if quarter_index < 1:
        continue
      targets.append(
        OutputTarget(
          metric=metric,
          quarter_start=quarter_index,
          quarter_end=quarter_index,
          min_value=float_or_none(band.get("min_value")),
          max_value=float_or_none(band.get("max_value")),
        )
      )
  return targets


def solve_solver_grid_plan(
  *,
  baseline_model_input_json: Dict[str, Any],
  grid_json: Dict[str, Any],
  max_iterations: int = 300,
  movement_penalty_weight: float = 0.000001,
) -> Dict[str, Any]:
  try:
    from client_intake_and_finmo.finmo_bridge import build_python_finmo_json  # type: ignore
  except Exception:
    from finmo_bridge import build_python_finmo_json  # type: ignore

  baseline_inputs = FinancialModelInputs.from_model_input_json(
    baseline_model_input_json if isinstance(baseline_model_input_json, dict) else {}
  )
  controls = controls_from_solver_grid(grid_json if isinstance(grid_json, dict) else {})
  targets = targets_from_solver_grid(grid_json if isinstance(grid_json, dict) else {})
  result = solve_financial_model(
    baseline_inputs,
    controls=controls,
    targets=targets,
    options=SolverOptions(
      max_iterations=max(1, int(max_iterations)),
      movement_penalty_weight=float(movement_penalty_weight),
    ),
  )
  solved_model_input_json = result.solved_model_input_json if isinstance(result.solved_model_input_json, dict) else {}
  solved_finmo_json = build_python_finmo_json(model_input_json=solved_model_input_json)
  max_accounting_check = max(
    abs(float(row.get("accounting_equation_check") or 0.0))
    for row in (result.solved_outputs or [])
  ) if result.solved_outputs else 0.0
  solver_summary = {
    "success": bool(result.success),
    "objective_before": float(result.objective_before or 0.0),
    "objective_after": float(result.objective_after or 0.0),
    "iterations": len(result.iterations or []),
    "control_count": len(controls),
    "target_count": len(targets),
    "accounting_equation_check_max_abs": float(max_accounting_check),
    "movement_penalty_weight": float(movement_penalty_weight),
    "max_iterations": int(max_iterations),
  }
  return {
    "solver_result": result,
    "controls": controls,
    "targets": targets,
    "solved_model_input_json": solved_model_input_json,
    "solved_finmo_json": solved_finmo_json,
    "solver_summary": solver_summary,
  }
