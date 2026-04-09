from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from scipy.optimize import minimize

from .finmo_model import calculate_finmo_model
from .model_inputs import FinancialModelInputs, QUARTER_COUNT, _safe_float


OUTPUT_METRIC_MAP: Dict[str, str] = {
  "revenue": "revenue",
  "ebitda": "ebitda",
  "cash": "cash",
  "net income": "net_income",
  "net_income": "net_income",
  "gross profit": "gross_profit",
  "gross_profit": "gross_profit",
  "operating cash flow": "operating_cash_flow",
  "operating_cash_flow": "operating_cash_flow",
}


def _normalize_output_metric(value: str) -> str:
  cleaned = str(value or "").strip().lower()
  return OUTPUT_METRIC_MAP.get(cleaned, cleaned.replace(" ", "_"))


def _quarter_bounds(start: int, end: int) -> Tuple[int, int]:
  quarter_start = min(max(int(start or 1), 1), QUARTER_COUNT)
  quarter_end = min(max(int(end or quarter_start), quarter_start), QUARTER_COUNT)
  return quarter_start, quarter_end


def _penalty_against_band(value: float, minimum: Optional[float], maximum: Optional[float]) -> float:
  if minimum is not None and value < minimum:
    return (minimum - value) ** 2
  if maximum is not None and value > maximum:
    return (value - maximum) ** 2
  return 0.0


@dataclass(slots=True)
class LeverControl:
  lever_id: str
  quarter_start: int
  quarter_end: int
  min_value: Optional[float] = None
  max_value: Optional[float] = None
  exact_value: Optional[float] = None
  weight: float = 1.0

  def normalized_quarters(self) -> Tuple[int, int]:
    return _quarter_bounds(self.quarter_start, self.quarter_end)

  def lower_bound(self) -> float:
    if self.exact_value is not None:
      return _safe_float(self.exact_value)
    if self.min_value is not None:
      return _safe_float(self.min_value)
    if self.max_value is not None:
      return _safe_float(self.max_value)
    return 0.0

  def upper_bound(self) -> float:
    if self.exact_value is not None:
      return _safe_float(self.exact_value)
    if self.max_value is not None:
      return _safe_float(self.max_value)
    if self.min_value is not None:
      return _safe_float(self.min_value)
    return self.lower_bound()

  def clamp(self, value: float) -> float:
    lower = min(self.lower_bound(), self.upper_bound())
    upper = max(self.lower_bound(), self.upper_bound())
    return min(max(_safe_float(value), lower), upper)


@dataclass(slots=True)
class OutputTarget:
  metric: str
  quarter_start: int
  quarter_end: int
  min_value: Optional[float] = None
  max_value: Optional[float] = None
  weight: float = 1.0

  def normalized_metric(self) -> str:
    return _normalize_output_metric(self.metric)

  def normalized_quarters(self) -> Tuple[int, int]:
    return _quarter_bounds(self.quarter_start, self.quarter_end)


@dataclass(slots=True)
class SolverOptions:
  max_iterations: int = 100
  movement_penalty_weight: float = 0.0001
  tolerance: float = 1e-6


@dataclass(slots=True)
class SolverIteration:
  iteration_index: int
  objective_value: float
  variable_values: Dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class SolverResult:
  success: bool
  objective_before: float
  objective_after: float
  solved_inputs: FinancialModelInputs
  solved_controller_seed: List[Dict[str, Any]]
  solved_model_input_json: Dict[str, Any]
  baseline_outputs: List[Dict[str, Any]]
  solved_outputs: List[Dict[str, Any]]
  iterations: List[SolverIteration] = field(default_factory=list)


def _variable_key(control: LeverControl) -> str:
  q_start, q_end = control.normalized_quarters()
  return f"{control.lever_id}::{q_start}-{q_end}"


def _revenue_driver_value(book: FinancialModelInputs, lever_id: str, quarter_index: int) -> float:
  parts = str(lever_id or "").split("::")
  if len(parts) < 4:
    raise ValueError(f"Unsupported revenue lever_id: {lever_id}")
  _, lob_name, product_name, driver_name = parts[:4]
  quarter = book.quarter(quarter_index)
  for group in quarter.revenue_groups:
    if group.lob_name != lob_name:
      continue
    for product in group.products:
      if product.product_name != product_name:
        continue
      if driver_name == "Capacity":
        return _safe_float(product.drivers.capacity_units)
      if driver_name == "Unit Price":
        return _safe_float(product.drivers.unit_price)
      if driver_name == "Utilization":
        return _safe_float(product.drivers.utilization)
  return 0.0


def _current_lever_value(book: FinancialModelInputs, control: LeverControl) -> float:
  q_start, _ = control.normalized_quarters()
  parts = str(control.lever_id or "").split("::")
  if not parts:
    raise ValueError("lever_id is required")
  if parts[0] == "revenue":
    return _revenue_driver_value(book, control.lever_id, q_start)
  if parts[0] == "expenses":
    row = book.expense_rows.get("::".join(parts[1:]))
    return row.get_value(q_start) if row is not None else 0.0
  if parts[0] == "balance_sheet":
    row = book.balance_sheet_rows.get("::".join(parts[1:]))
    return row.get_value(q_start) if row is not None else 0.0
  if parts[0] == "schedules":
    row = book.schedule_rows.get("::".join(parts[1:]))
    return row.get_value(q_start) if row is not None else 0.0
  raise ValueError(f"Unsupported lever section: {parts[0]}")


def _set_revenue_value(
  book: FinancialModelInputs,
  *,
  lever_id: str,
  quarter_index: int,
  value: float,
) -> None:
  parts = str(lever_id or "").split("::")
  if len(parts) < 4:
    raise ValueError(f"Unsupported revenue lever_id: {lever_id}")
  _, lob_name, product_name, driver_name = parts[:4]
  kwargs: Dict[str, Any] = {
    "quarter_index": quarter_index,
    "lob_name": lob_name,
    "product_name": product_name,
  }
  if driver_name == "Capacity":
    kwargs["capacity_units"] = value
  elif driver_name == "Unit Price":
    kwargs["unit_price"] = value
  elif driver_name == "Utilization":
    kwargs["utilization"] = value
  else:
    raise ValueError(f"Unsupported revenue driver: {driver_name}")
  book.set_revenue_drivers(**kwargs)


def _apply_lever_value(book: FinancialModelInputs, control: LeverControl, value: float) -> None:
  q_start, q_end = control.normalized_quarters()
  parts = str(control.lever_id or "").split("::")
  if not parts:
    raise ValueError("lever_id is required")
  for quarter_index in range(q_start, q_end + 1):
    if parts[0] == "revenue":
      _set_revenue_value(book, lever_id=control.lever_id, quarter_index=quarter_index, value=value)
    elif parts[0] == "expenses":
      book.set_simple_driver(
        section="expenses",
        label="::".join(parts[1:]),
        quarter_index=quarter_index,
        value=value,
        named_range="model_input_expenses",
        lever_id=control.lever_id,
      )
    elif parts[0] == "balance_sheet":
      book.set_simple_driver(
        section="balance_sheet",
        label="::".join(parts[1:]),
        quarter_index=quarter_index,
        value=value,
        named_range="model_input_balancehseet",
        lever_id=control.lever_id,
      )
    elif parts[0] == "schedules":
      book.set_simple_driver(
        section="schedules",
        label="::".join(parts[1:]),
        quarter_index=quarter_index,
        value=value,
        named_range="model_input_schedules",
        lever_id=control.lever_id,
      )
    else:
      raise ValueError(f"Unsupported lever section: {parts[0]}")


def _apply_control_values(
  base_inputs: FinancialModelInputs,
  controls: List[LeverControl],
  variable_values: Dict[str, float],
) -> FinancialModelInputs:
  next_book = deepcopy(base_inputs)
  for control in controls:
    key = _variable_key(control)
    value = variable_values.get(key, control.clamp(_current_lever_value(base_inputs, control)))
    _apply_lever_value(next_book, control, control.clamp(value))
  return next_book


def _objective_value(
  candidate_inputs: FinancialModelInputs,
  *,
  controls: List[LeverControl],
  baseline_values: Dict[str, float],
  variable_values: Dict[str, float],
  targets: List[OutputTarget],
  movement_penalty_weight: float,
) -> Tuple[float, List[Dict[str, Any]]]:
  solved_rows = calculate_finmo_model(candidate_inputs).quarter_rows()
  total_penalty = 0.0
  for target in targets:
    metric = target.normalized_metric()
    q_start, q_end = target.normalized_quarters()
    for quarter_index in range(q_start, q_end + 1):
      row = solved_rows[quarter_index - 1]
      total_penalty += target.weight * _penalty_against_band(
        _safe_float(row.get(metric)),
        target.min_value,
        target.max_value,
      )
  for control in controls:
    key = _variable_key(control)
    baseline = baseline_values[key]
    proposed = variable_values[key]
    scale = max(abs(control.upper_bound()), abs(control.lower_bound()), abs(baseline), 1.0)
    total_penalty += movement_penalty_weight * control.weight * (((proposed - baseline) / scale) ** 2)
  return total_penalty, solved_rows


def solve_financial_model(
  baseline_inputs: FinancialModelInputs,
  *,
  controls: List[LeverControl],
  targets: List[OutputTarget],
  options: Optional[SolverOptions] = None,
) -> SolverResult:
  solve_options = options or SolverOptions()
  baseline_book = deepcopy(baseline_inputs)
  normalized_controls = list(controls or [])
  normalized_targets = list(targets or [])

  baseline_values: Dict[str, float] = {}
  variable_values: Dict[str, float] = {}
  for control in normalized_controls:
    key = _variable_key(control)
    current = _current_lever_value(baseline_book, control)
    baseline_values[key] = control.clamp(current)
    variable_values[key] = control.clamp(
      control.exact_value if control.exact_value is not None else current
    )

  candidate_book = _apply_control_values(baseline_book, normalized_controls, variable_values)
  objective_before, baseline_outputs = _objective_value(
    candidate_book,
    controls=normalized_controls,
    baseline_values=baseline_values,
    variable_values=variable_values,
    targets=normalized_targets,
    movement_penalty_weight=solve_options.movement_penalty_weight,
  )
  best_objective = objective_before
  iterations = [SolverIteration(iteration_index=0, objective_value=objective_before, variable_values=dict(variable_values))]
  variable_keys = [_variable_key(control) for control in normalized_controls]
  x0 = [variable_values[key] for key in variable_keys]
  bounds = [(control.lower_bound(), control.upper_bound()) for control in normalized_controls]

  def _vector_to_values(vector: List[float]) -> Dict[str, float]:
    return {
      key: normalized_controls[index].clamp(vector[index])
      for index, key in enumerate(variable_keys)
    }

  callback_iteration = {"count": 0}

  def _objective(vector: List[float]) -> float:
    proposal_values = _vector_to_values(vector)
    proposal_book = _apply_control_values(baseline_book, normalized_controls, proposal_values)
    proposal_objective, _ = _objective_value(
      proposal_book,
      controls=normalized_controls,
      baseline_values=baseline_values,
      variable_values=proposal_values,
      targets=normalized_targets,
      movement_penalty_weight=solve_options.movement_penalty_weight,
    )
    return proposal_objective

  def _callback(vector: List[float]) -> None:
    callback_iteration["count"] += 1
    proposal_values = _vector_to_values(vector)
    proposal_book = _apply_control_values(baseline_book, normalized_controls, proposal_values)
    proposal_objective, _ = _objective_value(
      proposal_book,
      controls=normalized_controls,
      baseline_values=baseline_values,
      variable_values=proposal_values,
      targets=normalized_targets,
      movement_penalty_weight=solve_options.movement_penalty_weight,
    )
    iterations.append(
      SolverIteration(
        iteration_index=callback_iteration["count"],
        objective_value=proposal_objective,
        variable_values=dict(proposal_values),
      )
    )

  scipy_result = minimize(
    _objective,
    x0,
    method="L-BFGS-B",
    bounds=bounds,
    options={
      "maxiter": solve_options.max_iterations,
      "ftol": solve_options.tolerance,
    },
    callback=_callback if variable_keys else None,
  )

  best_values = _vector_to_values(list(scipy_result.x)) if variable_keys else {}
  best_objective = float(scipy_result.fun if scipy_result.fun is not None else objective_before)
  if not iterations or iterations[-1].objective_value != best_objective:
    iterations.append(
      SolverIteration(
        iteration_index=callback_iteration["count"] + (1 if variable_keys else 0),
        objective_value=best_objective,
        variable_values=dict(best_values),
      )
    )

  solved_book = _apply_control_values(baseline_book, normalized_controls, best_values)
  objective_after, solved_outputs = _objective_value(
    solved_book,
    controls=normalized_controls,
    baseline_values=baseline_values,
    variable_values=best_values if best_values else variable_values,
    targets=normalized_targets,
    movement_penalty_weight=solve_options.movement_penalty_weight,
  )
  return SolverResult(
    success=bool(scipy_result.success) or objective_after <= objective_before + 1e-12,
    objective_before=objective_before,
    objective_after=objective_after,
    solved_inputs=solved_book,
    solved_controller_seed=solved_book.to_controller_seed(),
    solved_model_input_json=solved_book.to_model_input_json(),
    baseline_outputs=baseline_outputs,
    solved_outputs=solved_outputs,
    iterations=iterations,
  )
