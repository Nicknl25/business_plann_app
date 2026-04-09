from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import minimize

from .finmo_model import calculate_finmo_model
from .model_inputs import FinancialModelInputs, QUARTER_COUNT, _safe_float


OUTPUT_METRIC_MAP: Dict[str, str] = {
  "revenue": "revenue",
  "ebitda": "ebitda",
  "cash": "ending_cash",
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
  target_center_weight: float = 1.0
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
  target_constraints_satisfied: bool
  max_target_violation: float
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


def _movement_objective_value(
  *,
  controls: List[LeverControl],
  baseline_values: Dict[str, float],
  variable_values: Dict[str, float],
  movement_penalty_weight: float,
) -> float:
  total_penalty = 0.0
  for control in controls:
    key = _variable_key(control)
    baseline = baseline_values[key]
    proposed = variable_values[key]
    scale = max(abs(control.upper_bound()), abs(control.lower_bound()), abs(baseline), 1.0)
    total_penalty += movement_penalty_weight * control.weight * (((proposed - baseline) / scale) ** 2)
  return total_penalty


def _target_center_objective_value(
  solved_rows: List[Dict[str, Any]],
  targets: List[OutputTarget],
  *,
  target_center_weight: float,
) -> float:
  total_penalty = 0.0
  if target_center_weight <= 0:
    return total_penalty
  for target in targets:
    metric = target.normalized_metric()
    q_start, q_end = target.normalized_quarters()
    for quarter_index in range(q_start, q_end + 1):
      row = solved_rows[quarter_index - 1]
      value = _safe_float(row.get(metric))
      minimum = _safe_float(target.min_value) if target.min_value is not None else None
      maximum = _safe_float(target.max_value) if target.max_value is not None else None
      if minimum is not None and maximum is not None:
        center = (minimum + maximum) / 2.0
        half_width = max(abs(maximum - minimum) / 2.0, 1.0)
        total_penalty += target_center_weight * target.weight * (((value - center) / half_width) ** 2)
      elif minimum is not None:
        scale = max(abs(minimum), 1.0)
        total_penalty += target_center_weight * target.weight * (((value - minimum) / scale) ** 2)
      elif maximum is not None:
        scale = max(abs(maximum), 1.0)
        total_penalty += target_center_weight * target.weight * (((value - maximum) / scale) ** 2)
  return total_penalty


def _target_constraint_residuals(
  solved_rows: List[Dict[str, Any]],
  targets: List[OutputTarget],
) -> List[float]:
  residuals: List[float] = []
  for target in targets:
    metric = target.normalized_metric()
    q_start, q_end = target.normalized_quarters()
    for quarter_index in range(q_start, q_end + 1):
      row = solved_rows[quarter_index - 1]
      value = _safe_float(row.get(metric))
      if target.min_value is not None:
        residuals.append(value - _safe_float(target.min_value))
      if target.max_value is not None:
        residuals.append(_safe_float(target.max_value) - value)
  return residuals


def _max_target_violation(residuals: List[float]) -> float:
  if not residuals:
    return 0.0
  return max(0.0, max(-float(item) for item in residuals))


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

  variable_keys = [_variable_key(control) for control in normalized_controls]
  evaluation_cache: Dict[Tuple[float, ...], Tuple[float, List[Dict[str, Any]]]] = {}

  def _values_cache_key(proposal_values: Dict[str, float]) -> Tuple[float, ...]:
    return tuple(round(float(proposal_values.get(key, 0.0)), 12) for key in variable_keys)

  def _evaluate_values(proposal_values: Dict[str, float]) -> Tuple[float, List[Dict[str, Any]]]:
    cache_key = _values_cache_key(proposal_values)
    cached = evaluation_cache.get(cache_key)
    if cached is not None:
      return cached
    proposal_book = _apply_control_values(baseline_book, normalized_controls, proposal_values)
    solved_rows = calculate_finmo_model(proposal_book).quarter_rows()
    objective_value = _movement_objective_value(
      controls=normalized_controls,
      baseline_values=baseline_values,
      variable_values=proposal_values,
      movement_penalty_weight=solve_options.movement_penalty_weight,
    )
    objective_value += _target_center_objective_value(
      solved_rows,
      normalized_targets,
      target_center_weight=solve_options.target_center_weight,
    )
    cached = (objective_value, solved_rows)
    evaluation_cache[cache_key] = cached
    return cached

  objective_before, baseline_outputs = _evaluate_values(variable_values)
  iterations = [SolverIteration(iteration_index=0, objective_value=objective_before, variable_values=dict(variable_values))]
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
    proposal_objective, _ = _evaluate_values(proposal_values)
    return proposal_objective

  def _callback(vector: List[float]) -> None:
    callback_iteration["count"] += 1
    proposal_values = _vector_to_values(vector)
    proposal_objective, _ = _evaluate_values(proposal_values)
    iterations.append(
      SolverIteration(
        iteration_index=callback_iteration["count"],
        objective_value=proposal_objective,
        variable_values=dict(proposal_values),
      )
    )

  constraints: List[Dict[str, Any]] = []
  if normalized_targets:
    def _constraint_fun(vector: List[float]) -> np.ndarray:
      proposal_values = _vector_to_values(vector)
      _, solved_rows = _evaluate_values(proposal_values)
      return np.asarray(_target_constraint_residuals(solved_rows, normalized_targets), dtype=float)

    constraints.append({"type": "ineq", "fun": _constraint_fun})

  if variable_keys:
    scipy_result = minimize(
      _objective,
      x0,
      method="SLSQP",
      bounds=bounds,
      constraints=constraints,
      options={
        "maxiter": solve_options.max_iterations,
        "ftol": solve_options.tolerance,
      },
      callback=_callback,
    )
    best_values = _vector_to_values(list(scipy_result.x))
    best_objective = float(scipy_result.fun if scipy_result.fun is not None else objective_before)
  else:
    class _NoopResult:
      success = True
      x: List[float] = []
      fun: float = objective_before

    scipy_result = _NoopResult()
    best_values = dict(variable_values)
    best_objective = objective_before

  if not iterations or iterations[-1].objective_value != best_objective:
    iterations.append(
      SolverIteration(
        iteration_index=callback_iteration["count"] + (1 if variable_keys else 0),
        objective_value=best_objective,
        variable_values=dict(best_values),
      )
    )

  solved_book = _apply_control_values(baseline_book, normalized_controls, best_values)
  objective_after, solved_outputs = _evaluate_values(best_values if best_values else variable_values)
  solved_residuals = _target_constraint_residuals(solved_outputs, normalized_targets)
  target_constraints_satisfied = _max_target_violation(solved_residuals) <= max(1e-8, float(solve_options.tolerance))
  return SolverResult(
    success=bool(target_constraints_satisfied),
    objective_before=objective_before,
    objective_after=objective_after,
    target_constraints_satisfied=bool(target_constraints_satisfied),
    max_target_violation=_max_target_violation(solved_residuals),
    solved_inputs=solved_book,
    solved_controller_seed=solved_book.to_controller_seed(),
    solved_model_input_json=solved_book.to_model_input_json(),
    baseline_outputs=baseline_outputs,
    solved_outputs=solved_outputs,
    iterations=iterations,
  )
