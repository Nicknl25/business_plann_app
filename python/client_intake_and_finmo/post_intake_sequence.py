"""Deterministic sequence controller for post-intake execution.

The SQL sequence/context tables define what may run, what inputs it requires,
what outputs it produces, and which executor function is responsible for the
step. Domain functions should be invoked through this controller when a caller
needs table-governed execution instead of ad hoc function chaining.
"""

from __future__ import annotations

import copy
import contextvars
import inspect
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
  post_intake_assert_required_process_sequence,
  post_intake_process_context_errors,
  post_intake_process_context_rows,
  post_intake_process_sequence_lookup,
  post_intake_process_step_context,
  post_intake_resolve_process_context,
)


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


def _normalized_key(value: Any) -> str:
  return _clean_text(value).lower()


_ACTIVE_SEQUENCE_CONTEXT: contextvars.ContextVar[Tuple[Dict[str, Any], ...]] = (
  contextvars.ContextVar("post_intake_active_sequence_context", default=())
)


def _registry_keys_for_row(row: Dict[str, Any]) -> List[str]:
  keys: List[str] = []
  for value in (
    row.get("executor_function"),
    row.get("handler_key"),
    row.get("step_key"),
  ):
    key = _clean_text(value)
    if key and key not in keys:
      keys.append(key)
  return keys


def _active_context_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
  return {
    "step_key": _normalized_key(row.get("step_key")),
    "phase": _normalized_key(row.get("phase")),
    "parent_step_key": _normalized_key(row.get("parent_step_key")),
    "step_kind": _normalized_key(row.get("step_kind")),
    "handler_key": _clean_text(row.get("handler_key")),
    "executor_function": _clean_text(row.get("executor_function") or row.get("handler_key")),
    "sequence_path": _clean_text(row.get("sequence_path")),
    "source_of_truth": row.get("source_of_truth") or "sql.post_intake_process_sequence_lookup",
  }


def active_post_intake_sequence_context() -> Dict[str, Any]:
  stack = _ACTIVE_SEQUENCE_CONTEXT.get(())
  if not stack:
    return {}
  return copy.deepcopy(stack[-1])


def assert_post_intake_sequence_controller_active(
  *,
  step_key: Any = None,
  allowed_step_keys: Optional[Iterable[Any]] = None,
  executor_function: Any = None,
  allowed_executor_functions: Optional[Iterable[Any]] = None,
) -> Dict[str, Any]:
  """Fail unless a post-intake process is running inside the sequence controller."""
  active_context = active_post_intake_sequence_context()
  if not active_context:
    raise RuntimeError(
      "post_intake_sequence_controller_required: "
      "post-intake process functions cannot run directly. "
      "Execute the declared step through PostIntakeSequenceController."
    )
  allowed_steps = {
    _normalized_key(item)
    for item in (allowed_step_keys or [])
    if _clean_text(item)
  }
  if step_key is not None:
    allowed_steps.add(_normalized_key(step_key))
  if allowed_steps and _normalized_key(active_context.get("step_key")) not in allowed_steps:
    raise RuntimeError(
      "post_intake_sequence_controller_wrong_step: "
      f"active_step={active_context.get('step_key') or 'missing'} "
      f"allowed_steps={sorted(allowed_steps)}"
    )
  allowed_executors = {
    _clean_text(item)
    for item in (allowed_executor_functions or [])
    if _clean_text(item)
  }
  if executor_function is not None:
    allowed_executors.add(_clean_text(executor_function))
  active_executor = _clean_text(active_context.get("executor_function") or active_context.get("handler_key"))
  if allowed_executors and active_executor not in allowed_executors:
    raise RuntimeError(
      "post_intake_sequence_controller_wrong_executor: "
      f"active_executor={active_executor or 'missing'} "
      f"allowed_executors={sorted(allowed_executors)}"
    )
  return active_context


def _push_active_sequence_context(row: Dict[str, Any]) -> contextvars.Token[Tuple[Dict[str, Any], ...]]:
  stack = _ACTIVE_SEQUENCE_CONTEXT.get(())
  return _ACTIVE_SEQUENCE_CONTEXT.set(stack + (_active_context_from_row(row),))


import contextlib  # noqa: E402  (deliberately scoped near the helper that uses it)


@contextlib.contextmanager
def post_intake_sequence_step_scope(
  *,
  step_key: str,
  phase: str = "post_intake_target_seeking",
  executor_function: str = "",
  parent_step_key: str = "",
  step_kind: str = "orchestration",
):
  """Context manager that pushes a synthetic sequence-controller scope for
  the duration of an orchestration-level operation.

  Some post-intake helpers (payroll capacity derivation, debt schedule
  rebuild, contract validators) gate themselves with
  `assert_post_intake_sequence_controller_active(...)` to prevent ad-hoc
  invocation outside the declared step graph. The Phase 2.5 / 3.7
  target-seeking orchestrator and Phase 3.7 adaptation cascade are
  legitimate orchestration-level callers that need to invoke those
  helpers (FINMO build, etc.) outside any specific table-declared step.
  This scope satisfies the controller-active guard with a context that
  honestly identifies itself as an orchestration step.

  Usage:
      with post_intake_sequence_step_scope(step_key="post_intake_target_seeking_pre_flight"):
          run_target_seeking_solver(...)
  """
  row = {
    "step_key": str(step_key or "post_intake_orchestration").strip(),
    "phase": str(phase or "post_intake_target_seeking").strip(),
    "executor_function": str(executor_function or "").strip(),
    "parent_step_key": str(parent_step_key or "").strip(),
    "step_kind": str(step_kind or "orchestration").strip(),
    "handler_key": str(executor_function or step_key or "post_intake_orchestration").strip(),
    "sequence_path": "post_intake_target_seeking_orchestration",
    "source_of_truth": "post_intake_solver.orchestrator_synthetic_scope",
  }
  token = _push_active_sequence_context(row)
  try:
    yield
  finally:
    _ACTIVE_SEQUENCE_CONTEXT.reset(token)


def _invoke_registered_handler(
  handler: Callable[..., Any],
  *,
  handler_kwargs: Optional[Dict[str, Any]] = None,
  process_context: Dict[str, Any],
  isolated: bool,
  allow_side_effects: bool,
) -> Any:
  base_kwargs = dict(handler_kwargs or {})
  metadata_kwargs = {
    "process_context": copy.deepcopy(process_context),
    "resolved_context": copy.deepcopy(
      (process_context.get("resolved_process_context") or {}).get("resolved_context") or {}
    ),
    "resolved_process_context": copy.deepcopy(process_context.get("resolved_process_context") or {}),
    "sequence_step": copy.deepcopy(process_context),
    "isolated": bool(isolated),
    "allow_side_effects": bool(allow_side_effects),
  }
  try:
    signature = inspect.signature(handler)
  except Exception:
    signature = None
  call_kwargs = dict(base_kwargs)
  if signature is not None:
    parameters = signature.parameters
    accepts_var_kwargs = any(
      parameter.kind == inspect.Parameter.VAR_KEYWORD
      for parameter in parameters.values()
    )
    for key, value in metadata_kwargs.items():
      if accepts_var_kwargs or key in parameters:
        call_kwargs.setdefault(key, value)
  return handler(**call_kwargs)


def _context_only_targeted_handler(
  *,
  process_context: Optional[Dict[str, Any]] = None,
  resolved_context: Optional[Dict[str, Any]] = None,
  resolved_process_context: Optional[Dict[str, Any]] = None,
  sequence_step: Optional[Dict[str, Any]] = None,
  isolated: bool = True,
  allow_side_effects: bool = False,
  **_: Any,
) -> Dict[str, Any]:
  step = process_context if isinstance(process_context, dict) else {}
  resolved = resolved_context if isinstance(resolved_context, dict) else {}
  resolved_payload = resolved_process_context if isinstance(resolved_process_context, dict) else {}
  sequence_row = sequence_step if isinstance(sequence_step, dict) else step
  return {
    "status": "targeted_process_context_resolved",
    "step_key": _normalized_key(sequence_row.get("step_key")),
    "phase": sequence_row.get("phase"),
    "handler_key": sequence_row.get("handler_key"),
    "executor_function": sequence_row.get("executor_function") or sequence_row.get("handler_key"),
    "isolated": bool(isolated),
    "side_effects_performed": False,
    "allow_side_effects": bool(allow_side_effects),
    "required_context_keys": copy.deepcopy(sequence_row.get("required_context_keys") or []),
    "resolved_context_keys": copy.deepcopy(resolved_payload.get("resolved_context_keys") or sorted(resolved.keys())),
    "resolved_context": copy.deepcopy(resolved),
    "produced_output_keys": copy.deepcopy(sequence_row.get("produced_output_keys") or []),
    "output_storage": copy.deepcopy(sequence_row.get("output_storage") or []),
    "output_finality": sequence_row.get("output_finality"),
    "targeted_execution_mode": "context_only_side_effect_free",
    "requires_domain_executor_for_output_materialization": True,
  }


setattr(_context_only_targeted_handler, "__post_intake_side_effect_free__", True)


class PostIntakeSequenceController:
  """Run post-intake steps from the SQL-backed process sequence.

  The controller is intentionally small: it does not own payroll, cash, or
  FINMO math. It owns table lookup, required context resolution, function
  dispatch, ordered trace capture, and protection for final stage outputs.
  """

  _BROAD_VERSIONED_OUTPUTS = {
    "model_input_json",
    "finmo_json",
    "planning_run_json",
    "controller_resolution_state",
    "resolution_summary",
  }

  def __init__(
    self,
    *,
    runtime_context: Optional[Dict[str, Any]] = None,
    phase: Any = None,
  ) -> None:
    self.runtime_context: Dict[str, Any] = copy.deepcopy(runtime_context or {})
    self.phase = _normalized_key(phase)
    self._lookup = post_intake_process_sequence_lookup()
    self._completed_step_keys: List[str] = []
    self._trace: List[Dict[str, Any]] = []
    self._final_outputs: Dict[str, Dict[str, Any]] = {}
    self._active_execution_stack: List[str] = []

  def ordered_steps(self) -> List[Dict[str, Any]]:
    return self._lookup.rows(phase=self.phase or None, active_only=True)

  def step_context(
    self,
    step_key: Any,
    *,
    runtime_context: Optional[Dict[str, Any]] = None,
    resolve_inputs: bool = True,
    expected_phase: Any = None,
    expected_handler_key: Any = None,
    required_contract_name: Any = None,
    required_context_contract_name: Any = None,
    required_context_include_phase: Any = None,
    required_lookup_tables: Optional[Iterable[Any]] = None,
    required_horizon_rule: Any = None,
  ) -> Dict[str, Any]:
    context = post_intake_process_step_context(
      step_key=step_key,
      expected_phase=expected_phase,
      expected_handler_key=expected_handler_key,
      required_contract_name=required_contract_name,
      required_context_contract_name=required_context_contract_name,
      required_context_include_phase=required_context_include_phase,
      required_lookup_tables=required_lookup_tables,
      required_horizon_rule=required_horizon_rule,
    )
    if resolve_inputs:
      merged_runtime_context = copy.deepcopy(self.runtime_context)
      if isinstance(runtime_context, dict):
        merged_runtime_context.update(copy.deepcopy(runtime_context))
      resolved_context = post_intake_resolve_process_context(
        step_key=step_key,
        runtime_context=merged_runtime_context,
      )
      context["resolved_process_context"] = copy.deepcopy(resolved_context)
      context["resolved_context_keys"] = copy.deepcopy(
        resolved_context.get("resolved_context_keys") or []
      )
    context["sequence_controller_loaded"] = True
    return context

  def execute_step(
    self,
    step_key: Any,
    handler: Callable[..., Any],
    *,
    runtime_context: Optional[Dict[str, Any]] = None,
    handler_kwargs: Optional[Dict[str, Any]] = None,
    resolve_inputs: bool = True,
    expected_phase: Any = None,
    expected_handler_key: Any = None,
    required_contract_name: Any = None,
    required_context_contract_name: Any = None,
    required_context_include_phase: Any = None,
    required_lookup_tables: Optional[Iterable[Any]] = None,
    required_horizon_rule: Any = None,
    _allow_direct_handler: bool = False,
  ) -> Any:
    if not bool(_allow_direct_handler):
      raise RuntimeError(
        "post_intake_sequence_controller_direct_handler_execution_disabled: "
        "register the declared SQL executor and call execute_registered_step()."
      )
    if not callable(handler):
      raise RuntimeError(
        f"post_intake_sequence_controller_handler_not_callable: step_key={_clean_text(step_key) or 'missing'}"
      )
    started_at = time.perf_counter()
    context = self.step_context(
      step_key,
      runtime_context=runtime_context,
      resolve_inputs=resolve_inputs,
      expected_phase=expected_phase,
      expected_handler_key=expected_handler_key,
      required_contract_name=required_contract_name,
      required_context_contract_name=required_context_contract_name,
      required_context_include_phase=required_context_include_phase,
      required_lookup_tables=required_lookup_tables,
      required_horizon_rule=required_horizon_rule,
    )
    self._active_execution_stack.append(_normalized_key(step_key))
    active_token = _push_active_sequence_context(context)
    try:
      result = handler(**dict(handler_kwargs or {}))
      self.complete_step(
        step_key,
        process_context=context,
        output_payload=result,
        elapsed_seconds=round(time.perf_counter() - started_at, 6),
      )
    finally:
      _ACTIVE_SEQUENCE_CONTEXT.reset(active_token)
      if self._active_execution_stack:
        self._active_execution_stack.pop()
    return result

  def targeted_step_manifest(
    self,
    step_key: Any,
    *,
    runtime_context: Optional[Dict[str, Any]] = None,
  ) -> Dict[str, Any]:
    context = self.step_context(
      step_key,
      runtime_context=runtime_context,
      resolve_inputs=True,
    )
    return {
      "status": "targeted_process_ready",
      "step_key": _normalized_key(context.get("step_key")),
      "phase": context.get("phase"),
      "handler_key": context.get("handler_key"),
      "executor_function": context.get("executor_function") or context.get("handler_key"),
      "required_context_keys": copy.deepcopy(context.get("required_context_keys") or []),
      "resolved_context_keys": copy.deepcopy(context.get("resolved_context_keys") or []),
      "produced_output_keys": copy.deepcopy(context.get("produced_output_keys") or []),
      "output_storage": copy.deepcopy(context.get("output_storage") or []),
      "output_finality": context.get("output_finality"),
      "context_source_of_truth": "sql.post_intake_process_context_lookup",
      "sequence_source_of_truth": "sql.post_intake_process_sequence_lookup",
      "targeted_execution_supported": True,
    }

  def _registered_handler(
    self,
    row: Dict[str, Any],
    handler_registry: Dict[str, Callable[..., Any]],
  ) -> Callable[..., Any]:
    registry = handler_registry if isinstance(handler_registry, dict) else {}
    for key in _registry_keys_for_row(row):
      handler = registry.get(key)
      if not callable(handler):
        handler = registry.get(key.lower())
      if callable(handler):
        return handler
    raise RuntimeError(
      "post_intake_sequence_controller_missing_registered_handler: "
      f"step_key={_normalized_key(row.get('step_key')) or 'missing'} "
      f"registered_keys={_registry_keys_for_row(row)}"
    )

  def execute_registered_step(
    self,
    step_key: Any,
    *,
    handler_registry: Dict[str, Callable[..., Any]],
    runtime_context: Optional[Dict[str, Any]] = None,
    handler_kwargs: Optional[Dict[str, Any]] = None,
    isolated: bool = False,
    allow_side_effects: bool = True,
  ) -> Any:
    row = self._lookup.step(step_key, required=True) or {}
    process_context = self.step_context(
      step_key,
      runtime_context=runtime_context,
      resolve_inputs=True,
      expected_phase=row.get("phase"),
      expected_handler_key=row.get("handler_key"),
      required_contract_name=row.get("contract_name") or None,
      required_context_contract_name=row.get("context_contract_name") or None,
      required_context_include_phase=row.get("context_include_phase") or None,
      required_lookup_tables=row.get("required_lookup_tables") or [],
      required_horizon_rule=row.get("horizon_rule") or None,
    )
    handler = self._registered_handler(process_context, handler_registry)
    side_effect_free = bool(getattr(handler, "__post_intake_side_effect_free__", False))
    if bool(isolated) and not bool(allow_side_effects) and not side_effect_free:
      raise RuntimeError(
        "post_intake_targeted_process_side_effect_free_handler_required: "
        f"step_key={_normalized_key(step_key)} executor_function="
        f"{process_context.get('executor_function') or process_context.get('handler_key')}. "
        "Targeted isolated execution cannot call a side-effecting domain handler."
      )

    def _registered_handler_wrapper() -> Any:
      return _invoke_registered_handler(
        handler,
        handler_kwargs=handler_kwargs,
        process_context=process_context,
        isolated=bool(isolated),
        allow_side_effects=bool(allow_side_effects),
      )

    setattr(
      _registered_handler_wrapper,
      "__name__",
      _clean_text(process_context.get("executor_function") or process_context.get("handler_key")) or "registered_post_intake_step",
    )
    return self.execute_step(
      step_key,
      _registered_handler_wrapper,
      runtime_context=runtime_context,
      expected_phase=process_context.get("phase"),
      expected_handler_key=process_context.get("handler_key"),
      required_contract_name=process_context.get("contract_name") or None,
      required_context_contract_name=process_context.get("context_contract_name") or None,
      required_context_include_phase=process_context.get("context_include_phase") or None,
      required_lookup_tables=process_context.get("required_lookup_tables") or [],
      required_horizon_rule=process_context.get("horizon_rule") or None,
      _allow_direct_handler=True,
    )

  def execute_all(
    self,
    *,
    handler_registry: Dict[str, Callable[..., Any]],
    runtime_context: Optional[Dict[str, Any]] = None,
    handler_kwargs_by_step: Optional[Dict[str, Dict[str, Any]]] = None,
  ) -> Dict[str, Any]:
    """Execute every active row for the configured phase in strict order."""
    results: Dict[str, Any] = {}
    registry = handler_registry if isinstance(handler_registry, dict) else {}
    kwargs_by_step = handler_kwargs_by_step if isinstance(handler_kwargs_by_step, dict) else {}
    for row in self.ordered_steps():
      step_key = _normalized_key(row.get("step_key"))
      results[step_key] = self.execute_registered_step(
        step_key,
        handler_registry=registry,
        runtime_context=runtime_context,
        handler_kwargs=kwargs_by_step.get(step_key) or {},
        isolated=False,
        allow_side_effects=True,
      )
      if isinstance(results[step_key], dict):
        self.runtime_context.update(copy.deepcopy(results[step_key]))
    return {
      "status": "completed",
      "phase": self.phase or None,
      "results": results,
      "trace": self.trace(),
    }

  def complete_step(
    self,
    step_key: Any,
    *,
    process_context: Dict[str, Any],
    output_payload: Any = None,
    elapsed_seconds: Optional[float] = None,
  ) -> Dict[str, Any]:
    step = _normalized_key(step_key)
    row = process_context if isinstance(process_context, dict) else {}
    self._assert_output_finality(step, row)
    if step not in self._completed_step_keys:
      self._completed_step_keys.append(step)
    trace_row = {
      "step_key": step,
      "phase": row.get("phase"),
      "parent_step_key": row.get("parent_step_key"),
      "step_kind": row.get("step_kind"),
      "sequence_path": row.get("sequence_path"),
      "executor_function": row.get("executor_function") or row.get("handler_key"),
      "required_context_keys": copy.deepcopy(row.get("required_context_keys") or []),
      "resolved_context_keys": copy.deepcopy(row.get("resolved_context_keys") or []),
      "produced_output_keys": copy.deepcopy(row.get("produced_output_keys") or []),
      "output_storage": copy.deepcopy(row.get("output_storage") or []),
      "output_finality": row.get("output_finality"),
      "elapsed_seconds": elapsed_seconds,
      "output_payload_type": type(output_payload).__name__ if output_payload is not None else "",
      "status": "completed",
    }
    self._trace.append(trace_row)
    return trace_row

  def trace(self) -> List[Dict[str, Any]]:
    return copy.deepcopy(self._trace)

  def _assert_output_finality(self, step_key: str, row: Dict[str, Any]) -> None:
    for storage in row.get("output_storage") or []:
      if not isinstance(storage, dict) or not bool(storage.get("final_for_stage")):
        continue
      output_key = _clean_text(storage.get("output_key"))
      normalized_output = output_key.lower()
      if not normalized_output or normalized_output in self._BROAD_VERSIONED_OUTPUTS:
        continue
      previous = self._final_outputs.get(normalized_output)
      if (
        previous
        and previous.get("step_key") != step_key
        and not self._same_sequence_family(previous.get("step_key"), step_key)
        and not bool(storage.get("preserves_upstream_output"))
        and not bool(storage.get("recompute_of_step_key"))
      ):
        raise RuntimeError(
          "post_intake_sequence_controller_final_output_mutation_blocked: "
          f"output_key={output_key} original_step={previous.get('step_key')} downstream_step={step_key}. "
          "Recompute the upstream process instead of mutating a final output directly."
        )
      self._final_outputs[normalized_output] = {
        "step_key": step_key,
        "storage": copy.deepcopy(storage),
      }

  def _same_sequence_family(self, left_step_key: Any, right_step_key: Any) -> bool:
    left = _normalized_key(left_step_key)
    right = _normalized_key(right_step_key)
    if not left or not right:
      return False
    if left == right:
      return True
    try:
      left_row = self._lookup.step(left, required=False) or {}
      right_row = self._lookup.step(right, required=False) or {}
    except Exception:
      return False
    left_parent = _normalized_key(left_row.get("parent_step_key"))
    right_parent = _normalized_key(right_row.get("parent_step_key"))
    return bool(
      left_parent == right
      or right_parent == left
      or (left_parent and left_parent == right_parent)
    )


def build_post_intake_sequence_controller(
  *,
  runtime_context: Optional[Dict[str, Any]] = None,
  phase: Any = None,
) -> PostIntakeSequenceController:
  return PostIntakeSequenceController(
    runtime_context=runtime_context,
    phase=phase,
  )


def assert_post_intake_sequence_controller_authoritative() -> Dict[str, Any]:
  required_process_sequence = post_intake_assert_required_process_sequence()
  context_errors = post_intake_process_context_errors()
  if context_errors:
    raise RuntimeError(
      "post_intake_process_context_lookup_invalid: "
      + "; ".join(str(item) for item in context_errors[:30])
    )
  return {
    "sequence_controller_authoritative": True,
    "direct_handler_execution_disabled": True,
    "source_of_truth": "sql.post_intake_process_sequence_lookup",
    "context_source_of_truth": "sql.post_intake_process_context_lookup",
    "active_step_count": int(required_process_sequence.get("active_step_count") or 0),
    "process_context_row_count": len(post_intake_process_context_rows(active_only=True)),
    "required_process_sequence": copy.deepcopy(required_process_sequence),
  }


def build_context_only_handler_registry(
  *,
  phase: Any = None,
) -> Dict[str, Callable[..., Any]]:
  registry: Dict[str, Callable[..., Any]] = {}
  lookup = post_intake_process_sequence_lookup()
  for row in lookup.rows(phase=phase, active_only=True):
    for key in _registry_keys_for_row(row):
      registry[key] = _context_only_targeted_handler
      registry[key.lower()] = _context_only_targeted_handler
  return registry


def build_single_step_handler_registry(
  step_key: Any,
  handler: Callable[..., Any],
  *,
  extra_keys: Optional[Iterable[Any]] = None,
) -> Dict[str, Callable[..., Any]]:
  if not callable(handler):
    raise RuntimeError(
      f"post_intake_sequence_controller_handler_not_callable: step_key={_clean_text(step_key) or 'missing'}"
    )
  lookup = post_intake_process_sequence_lookup()
  row = lookup.step(step_key, required=True) or {}
  registry: Dict[str, Callable[..., Any]] = {}
  for key in list(_registry_keys_for_row(row)) + [
    _clean_text(getattr(handler, "__name__", "")),
    *[_clean_text(item) for item in (extra_keys or [])],
  ]:
    if not key:
      continue
    registry[key] = handler
    registry[key.lower()] = handler
  return registry


def run_targeted_process_step(
  step_key: Any,
  *,
  runtime_context: Optional[Dict[str, Any]] = None,
  handler_registry: Optional[Dict[str, Callable[..., Any]]] = None,
  handler_kwargs: Optional[Dict[str, Any]] = None,
  allow_side_effects: bool = False,
) -> Dict[str, Any]:
  controller = build_post_intake_sequence_controller(runtime_context=runtime_context)
  registry = (
    handler_registry
    if isinstance(handler_registry, dict) and handler_registry
    else build_context_only_handler_registry()
  )
  result = controller.execute_registered_step(
    step_key,
    handler_registry=registry,
    runtime_context=runtime_context,
    handler_kwargs=handler_kwargs,
    isolated=True,
    allow_side_effects=bool(allow_side_effects),
  )
  return {
    "status": "completed",
    "step_key": _normalized_key(step_key),
    "targeted": True,
    "isolated": True,
    "allow_side_effects": bool(allow_side_effects),
    "result": copy.deepcopy(result),
    "manifest": controller.targeted_step_manifest(step_key, runtime_context=runtime_context),
    "trace": controller.trace(),
  }
