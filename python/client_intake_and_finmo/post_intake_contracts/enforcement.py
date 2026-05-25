"""Boundary-enforcement helpers for P3.40 Contract 1.

This module provides the producer-side and consumer-side validation
gates that wrap ``FinmoModelInputContract.model_validate`` and turn
``pydantic.ValidationError`` into a typed ``ContractViolation`` with
the stage/field/expected/actual extracted into structured attributes.

Producer-side gate (Commit 3): called at the end of
``prepare_initial_grid_for_draft`` just before the function returns
the ``applied_model_input_json`` that downstream code (the
target-seeking orchestrator + FINMO build) consumes.

Consumer-side gate (Commit 4): called at the entry of
``build_python_finmo_json`` to catch any mutation between the
producer's write and the consumer's read.

Both gates emit a diagnostic event on success
(``MODEL_INPUT_CONTRACT_VALIDATED``) and a FAILED-status emit on
failure (``MODEL_INPUT_CONTRACT_VIOLATION``) before raising. The
emit is best-effort: a missing or failing emitter does not block
the gate from raising / passing.

The floor's terminal trace path catches generic ``Exception``
(``driver_run_with_audit_wrapper`` at
``post_intake_amalgamated/protocol/session_factory.py:376+``), so
``ContractViolation`` propagates as a structured failure with its
stage tag intact for diagnostic surfacing.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple

from pydantic import ValidationError

from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (
  ContractViolation,
  FinmoModelInputContract,
)


#: Stage label for the producer/consumer gates around the
#: AMALGAMATED_SESSION → MODEL_INPUT boundary. Matches the boundary
#: name in the v2 inventory and the contract spec.
MODEL_INPUT_STAGE_LABEL = "AMALGAMATED_SESSION→MODEL_INPUT"

#: FailFastCode value emitted alongside the typed ``ContractViolation``
#: when a gate fires. Carries the standard ``post_intake_fail_fast::``
#: prefix in the audit row so existing upstream halt detectors (which
#: match on that prefix) see contract violations as structural failures
#: alongside other fail-fast points. The code itself is declared in
#: ``post_intake_diagnostics.fail_fast_codes.FailFastCode``:
#: ``FAIL_MODEL_INPUT_CONTRACT_VIOLATION = "fail_model_input_contract_violation"``.
_MODEL_INPUT_CONTRACT_FAIL_FAST_CODE_VALUE = "fail_model_input_contract_violation"

#: Sides of the boundary. Distinguished in diagnostic_data so a
#: failure at one side vs the other is queryable.
SIDE_PRODUCER = "producer"
SIDE_CONSUMER = "consumer"


def _truncate_repr(value: Any, *, limit: int = 200) -> str:
  """Compact representation of an arbitrary value, truncated to
  ``limit`` chars. Used for the ``actual`` field on
  ``ContractViolation`` so the boundary error message stays
  readable even when the source payload is large."""
  try:
    text = repr(value)
  except Exception:
    text = f"<unrepr {type(value).__name__}>"
  if len(text) > limit:
    text = text[: limit - 3] + "..."
  return text


def _extract_first_error(
  exc: ValidationError,
) -> Tuple[str, str, str]:
  """Pull the most-informative (field_path, expected, actual)
  triple out of a pydantic ``ValidationError`` for the
  ``ContractViolation`` payload.

  ``ValidationError.errors()`` returns a list of dicts. Each dict
  has ``loc`` (tuple of field path segments), ``msg`` (human
  description), ``type`` (pydantic error type), and ``input`` (the
  offending value). We take the first error as the "headline"
  failure and include the count in the message if there are more.
  """
  errors = exc.errors() if hasattr(exc, "errors") else []
  if not errors:
    return ("<unknown>", "valid payload", _truncate_repr(exc))
  first = errors[0]
  loc = first.get("loc") or ()
  field_path = ".".join(str(s) for s in loc) or "<root>"
  expected = str(first.get("msg") or first.get("type") or "valid value")
  actual = _truncate_repr(first.get("input"))
  if len(errors) > 1:
    expected = f"{expected} (and {len(errors) - 1} more error(s))"
  return (field_path, expected, actual)


def validate_model_input_at_boundary(
  payload: Dict[str, Any],
  *,
  side: str,
  stage: str = MODEL_INPUT_STAGE_LABEL,
  emit_diagnostic_fn: Optional[Callable[..., Any]] = None,
) -> FinmoModelInputContract:
  """Validate ``payload`` against ``FinmoModelInputContract`` and
  return the parsed contract on success.

  ``side`` distinguishes producer ("producer") vs consumer
  ("consumer") gates. The string lands in diagnostic_data so the
  event stream is queryable by which side fired.

  On success:
    - Returns the validated ``FinmoModelInputContract`` instance.
    - Emits ``MODEL_INPUT_CONTRACT_VALIDATED`` with
      ``status=COMPLETED`` if ``emit_diagnostic_fn`` is supplied.

  On failure:
    - Emits ``MODEL_INPUT_CONTRACT_VIOLATION`` with
      ``status=FAILED`` if ``emit_diagnostic_fn`` is supplied.
    - Raises ``ContractViolation`` with ``stage``, ``field``,
      ``expected``, ``actual`` extracted from the first
      ``ValidationError`` and ``source_payload=payload``.

  The emit is best-effort: if ``emit_diagnostic_fn`` raises, the
  exception is swallowed (observability must not break the
  pipeline).
  """
  try:
    contract = FinmoModelInputContract.model_validate(payload)
  except ValidationError as exc:
    field_path, expected, actual = _extract_first_error(exc)
    if emit_diagnostic_fn is not None:
      _safe_emit(
        emit_diagnostic_fn,
        event_code_name="MODEL_INPUT_CONTRACT_VIOLATION",
        status_name="FAILED",
        diagnostic_data={
          "side": side,
          "stage": stage,
          "field": field_path,
          "expected": expected[:300],
          "actual": actual[:300],
          "error_count": len(exc.errors()),
        },
      )
    raise ContractViolation(
      stage=stage,
      field=field_path,
      expected=expected,
      actual=actual,
      source_payload=payload,
    ) from exc

  if emit_diagnostic_fn is not None:
    _safe_emit(
      emit_diagnostic_fn,
      event_code_name="MODEL_INPUT_CONTRACT_VALIDATED",
      status_name="COMPLETED",
      diagnostic_data={
        "side": side,
        "stage": stage,
        "revenue_row_count": len(contract.sections.revenue),
        "expense_row_count": len(contract.sections.expenses),
        "balance_sheet_row_count": len(contract.sections.balance_sheet),
        "schedule_row_count": len(contract.sections.schedules.rows),
      },
    )
  return contract


def _safe_emit(
  emit_diagnostic_fn: Callable[..., Any],
  *,
  event_code_name: str,
  status_name: str,
  diagnostic_data: Dict[str, Any],
) -> None:
  """Best-effort emit. Resolves PhaseCode/EventCode/Status by name
  to avoid forcing the caller to know the enums; swallows all
  exceptions so observability never breaks the gate.

  Resolution is dynamic so this helper can run in environments
  where the diagnostics module hasn't been bound (tests with fake
  emitters, etc.).
  """
  try:
    from client_intake_and_finmo.post_intake_diagnostics.phase_codes import (  # type: ignore  # noqa: E501
      EventCode,
      PhaseCode,
      Status,
    )
    emit_diagnostic_fn(
      phase=PhaseCode.MODEL_INPUT_CONTRACT,
      event_code=getattr(EventCode, event_code_name),
      status=getattr(Status, status_name),
      diagnostic_data=diagnostic_data,
    )
  except Exception:
    return


def make_boundary_emitter(
  *,
  conn: Any,
  draft_id: str,
  planning_run_id: str,
) -> Callable[..., Any]:
  """Build an ``emit_diagnostic_fn`` closure that calls
  ``post_intake_diagnostics.emit_diagnostic`` with the supplied
  conn / draft_id / planning_run_id pre-bound.

  Convenience for call sites that have conn + ids in scope (the
  initial-grid runner, the orchestrator, etc.) but don't already
  carry an emit closure.
  """
  def emit(**kwargs: Any) -> Any:
    try:
      from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
        emit_diagnostic,
      )
      return emit_diagnostic(
        conn, draft_id=draft_id, planning_run_id=planning_run_id, **kwargs
      )
    except Exception:
      return None
  return emit


__all__ = [
  "MODEL_INPUT_STAGE_LABEL",
  "SIDE_PRODUCER",
  "SIDE_CONSUMER",
  "validate_model_input_at_boundary",
  "make_boundary_emitter",
]
