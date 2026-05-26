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
from client_intake_and_finmo.post_intake_contracts.workbook_payload_contract import (
  WORKBOOK_STAGE_LABEL,
  WorkbookPayloadContract,
)
from client_intake_and_finmo.post_intake_contracts.solver_input_contract import (
  SOLVER_STAGE_LABEL,
  SolverInputContract,
)
from client_intake_and_finmo.post_intake_contracts.solver_output_contract import (
  SOLVER_OUTPUT_STAGE_LABEL,
  SolverOutputContract,
)
from client_intake_and_finmo.post_intake_contracts.intake_draft_contract import (
  INTAKE_DRAFT_STAGE_LABEL,
  IntakeDraftContract,
)
from client_intake_and_finmo.post_intake_contracts.industry_baseline_resolved_contract import (
  INDUSTRY_BASELINE_STAGE_LABEL,
  CascadeResolverPayloadContract,
  CohortSqlRowContract,
  GetBandsViewContract,
  PopulationSummaryContract,
)
from client_intake_and_finmo.post_intake_contracts.amalgamated_session_contract import (
  AMALGAMATED_SESSION_STAGE_LABEL,
  MirrorContract,
  ValidationStateProjectionContract,
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
        phase_code_name="MODEL_INPUT_CONTRACT",
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
      phase_code_name="MODEL_INPUT_CONTRACT",
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
  phase_code_name: str,
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

  ``phase_code_name`` parameterized in P3.40 Contract 3 Commit 3
  so each per-boundary gate routes to its own PhaseCode rather
  than all gates landing under MODEL_INPUT_CONTRACT. Each caller
  passes the PhaseCode attribute name (e.g.
  "MODEL_INPUT_CONTRACT", "SOLVER_INPUT_CONTRACT"); if the
  attribute doesn't exist (e.g. an older boundary contract whose
  PhaseCode wasn't added), the AttributeError is swallowed and
  no event lands -- contract still raises ContractViolation.
  """
  try:
    from client_intake_and_finmo.post_intake_diagnostics.phase_codes import (  # type: ignore  # noqa: E501
      EventCode,
      PhaseCode,
      Status,
    )
    emit_diagnostic_fn(
      phase=getattr(PhaseCode, phase_code_name),
      event_code=getattr(EventCode, event_code_name),
      status=getattr(Status, status_name),
      diagnostic_data=diagnostic_data,
    )
  except Exception:
    return


def validate_workbook_payload_at_boundary(
  payload: Dict[str, Any],
  *,
  side: str,
  stage: str = WORKBOOK_STAGE_LABEL,
  emit_diagnostic_fn: Optional[Callable[..., Any]] = None,
) -> WorkbookPayloadContract:
  """P3.40 Contract 2 Commit 3 consumer-side gate. Validate
  ``payload`` against ``WorkbookPayloadContract`` and return the
  parsed contract on success.

  This is the boundary enforcement called at the entry of
  ``client_statements_output_excel/workbook_builder.py:
  build_client_financial_model_workbook`` -- the workbook builder
  is the SOLE consumer at this boundary, so this is the gate that
  matters today. The matching producer-side gates (one per writer
  of the 5 JSON dicts: model_input_json, finmo_json,
  payroll_headcount, debt_schedule, planning_run_json) are deferred
  to spec §8 R8.

  On failure, raises ``ContractViolation`` with the WORKBOOK stage
  label and the first ``ValidationError`` extracted into structured
  fields. The API entry point at
  ``python/api_handlers/intake_consult.py:7655`` already catches
  generic ``Exception`` and logs ``str(exc)``, so the violation
  propagates as a useful structured message in the server log
  (verified by Adjustment B tests in
  ``tests/test_p3_40_contract_2_workbook_payload.py``).

  Diagnostic emission is best-effort (same pattern as the
  model-input gate above): if ``emit_diagnostic_fn`` is supplied,
  the gate emits ``WORKBOOK_PAYLOAD_CONTRACT_VALIDATED`` on success
  and ``WORKBOOK_PAYLOAD_CONTRACT_VIOLATION`` on failure. Both
  emit-failures are swallowed so observability cannot break the
  workbook build.
  """
  try:
    contract = WorkbookPayloadContract.model_validate(payload)
  except ValidationError as exc:
    field_path, expected, actual = _extract_first_error(exc)
    if emit_diagnostic_fn is not None:
      _safe_emit(
        emit_diagnostic_fn,
        phase_code_name="WORKBOOK_PAYLOAD_CONTRACT",
        event_code_name="WORKBOOK_PAYLOAD_CONTRACT_VIOLATION",
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
      phase_code_name="WORKBOOK_PAYLOAD_CONTRACT",
      event_code_name="WORKBOOK_PAYLOAD_CONTRACT_VALIDATED",
      status_name="COMPLETED",
      diagnostic_data={
        "side": side,
        "stage": stage,
        "pl_row_count": len(contract.finmo_json.pl),
        "balance_sheet_row_count": len(contract.finmo_json.balance_sheet),
        "cash_flow_row_count": len(contract.finmo_json.cash_flow),
        "payroll_row_count": len(contract.payroll_headcount.rows),
        "debt_schedule_row_count": len(contract.debt_schedule.rows),
        "has_planning_run_json": contract.planning_run_json is not None,
        "has_run_diagnostics": contract.run_diagnostics is not None,
      },
    )
  return contract


def validate_solver_input_at_boundary(
  payload: Dict[str, Any],
  *,
  side: str,
  stage: str = SOLVER_STAGE_LABEL,
  emit_diagnostic_fn: Optional[Callable[..., Any]] = None,
) -> SolverInputContract:
  """P3.40 Contract 3 Commit 3 boundary gate. Validate ``payload``
  against ``SolverInputContract`` and return the parsed contract
  on success.

  Producer-side: called at the end of
  ``prepare_initial_grid_for_draft`` (runner.py:1830, just before
  the dict return; SECOND validate call after Contract 1's gate
  at runner.py:1809-1822, validating the disjoint set of solver
  bundle fields).

  Consumer-side: called as the FIRST executable line of
  ``run_target_seeking_orchestrated_system_run``
  (orchestrator.py:1028+).

  On failure raises ``ContractViolation`` with the SOLVER stage
  label and the first ``ValidationError`` extracted into
  structured fields. Per trace Div-8: the API handler at
  ``intake_consult.py:7377`` catches ``except Exception as exc:``
  and logs ``str(exc)`` -- the violation propagates as a useful
  structured message containing ``SOLVER_STAGE_LABEL`` + field
  path. Verified by Adjustment B tests in
  ``tests/test_p3_40_contract_3_consumer_gate.py``.

  Diagnostic emission is best-effort (same pattern as the
  model-input and workbook-payload gates): emits
  ``SOLVER_INPUT_CONTRACT_VALIDATED`` on success and
  ``SOLVER_INPUT_CONTRACT_VIOLATION`` on failure when
  ``emit_diagnostic_fn`` is supplied. Failures swallowed so
  observability cannot break the gate.
  """
  try:
    contract = SolverInputContract.model_validate(payload)
  except ValidationError as exc:
    field_path, expected, actual = _extract_first_error(exc)
    if emit_diagnostic_fn is not None:
      _safe_emit(
        emit_diagnostic_fn,
        phase_code_name="SOLVER_INPUT_CONTRACT",
        event_code_name="SOLVER_INPUT_CONTRACT_VIOLATION",
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
      phase_code_name="SOLVER_INPUT_CONTRACT",
      event_code_name="SOLVER_INPUT_CONTRACT_VALIDATED",
      status_name="COMPLETED",
      diagnostic_data={
        "side": side,
        "stage": stage,
        "planning_mode": contract.planning_mode,
        "has_stage_ramp_contract": contract.stage_ramp_contract is not None,
        "has_payroll_headcount": contract.payroll_headcount is not None,
        "has_planning_context_summary_json": (
          contract.planning_context_summary_json is not None
        ),
        "has_grid_application_summary": (
          contract.grid_application_summary is not None
        ),
      },
    )
  return contract


def validate_solver_output_at_boundary(
  payload: Dict[str, Any],
  *,
  side: str,
  stage: str = SOLVER_OUTPUT_STAGE_LABEL,
  emit_diagnostic_fn: Optional[Callable[..., Any]] = None,
) -> SolverOutputContract:
  """P3.40 Contract 4 Commit 3 boundary gate. Validate ``payload``
  against ``SolverOutputContract`` and return the parsed contract
  on success.

  Consumer-side: called at intake_consult.py:7276 (after
  ``_run_planning_system_for_draft`` returns, before
  ``verify_run_acceptance``). Producer-side is skipped per spec
  Flag 7 (14 stamp sites across 600 lines of orchestrator.py;
  the 4 composed sub-contract fields are upstream-gated via
  Contracts 1/2 producer-side gates).

  On failure raises ``ContractViolation`` with the SOLVER_OUTPUT
  stage label and the first ``ValidationError`` extracted into
  structured fields. Per trace Div-6 the API handler at
  intake_consult.py:7377 catches ``except Exception as exc:``
  (skips line-7298 RuntimeError because ContractViolation is
  Exception subclass, not RuntimeError). ContractViolation
  surfaces as a structured 500 with str(exc) carrying
  ``SOLVER_OUTPUT_STAGE_LABEL`` + field path. Verified by
  Adjustment B tests in
  ``tests/test_p3_40_contract_4_solver_output.py``.

  Diagnostic emission is best-effort (same pattern as the
  model-input / workbook-payload / solver-input gates): emits
  ``SOLVER_OUTPUT_CONTRACT_VALIDATED`` on success and
  ``SOLVER_OUTPUT_CONTRACT_VIOLATION`` on failure when
  ``emit_diagnostic_fn`` is supplied. Failures swallowed so
  observability cannot break the gate.
  """
  try:
    contract = SolverOutputContract.model_validate(payload)
  except ValidationError as exc:
    field_path, expected, actual = _extract_first_error(exc)
    if emit_diagnostic_fn is not None:
      _safe_emit(
        emit_diagnostic_fn,
        phase_code_name="SOLVER_OUTPUT_CONTRACT",
        event_code_name="SOLVER_OUTPUT_CONTRACT_VIOLATION",
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
      phase_code_name="SOLVER_OUTPUT_CONTRACT",
      event_code_name="SOLVER_OUTPUT_CONTRACT_VALIDATED",
      status_name="COMPLETED",
      diagnostic_data={
        "side": side,
        "stage": stage,
        "plan_confidence": contract.plan_confidence,
        "has_payroll_headcount": contract.payroll_headcount is not None,
        "has_debt_schedule": contract.debt_schedule is not None,
        "has_capital_lease_schedule": (
          contract.capital_lease_schedule is not None
        ),
        "cascade_fired": contract.adaptation_cascade_diagnostics is not None,
      },
    )
  return contract


def validate_intake_draft_at_boundary(
  payload: Dict[str, Any],
  *,
  side: str,
  stage: str = INTAKE_DRAFT_STAGE_LABEL,
  emit_diagnostic_fn: Optional[Callable[..., Any]] = None,
) -> IntakeDraftContract:
  """P3.40 Contract 5 Commit 3 boundary gate. Validate ``payload``
  against ``IntakeDraftContract`` and return the parsed contract
  on success.

  Consumer-side: called inside ``prepare_initial_grid_for_draft``
  immediately after the draft row is loaded and BEFORE the 8
  ``parse_json_dict(draft.get(<column>))`` reads at
  runner.py:190-197. Closes the FALLBACK_PATH silent-empty pattern
  per trace Div-3.

  Producer-side is SKIPPED per spec Flag 4 (20+ append_messages
  writer sites in intake_consult.py make a single producer-side
  gate infeasible -- Contract 2 R8 pattern). Per-consultant gates
  land as Contract 5b/c/etc. follow-ups once typed sub-contracts
  ship.

  On failure raises ``ContractViolation`` with the INTAKE_DRAFT
  stage label and the first ``ValidationError`` extracted into
  structured fields. Per trace Div-6: the API handler at
  intake_consult.py:7377 catches ``except Exception as exc:``
  (skips line-7298 RuntimeError because ContractViolation is
  Exception subclass, not RuntimeError). The violation surfaces
  as a structured 500 with str(exc) carrying
  ``INTAKE_DRAFT_STAGE_LABEL`` + field path. Verified by
  Adjustment B tests in
  ``tests/test_p3_40_contract_5_intake_draft.py``.

  Diagnostic emission is best-effort (same pattern as the
  model-input / workbook-payload / solver-input / solver-output
  gates): emits ``INTAKE_DRAFT_CONTRACT_VALIDATED`` on success
  and ``INTAKE_DRAFT_CONTRACT_VIOLATION`` on failure when
  ``emit_diagnostic_fn`` is supplied. Failures swallowed so
  observability cannot break the gate.
  """
  try:
    contract = IntakeDraftContract.model_validate(payload)
  except ValidationError as exc:
    field_path, expected, actual = _extract_first_error(exc)
    if emit_diagnostic_fn is not None:
      _safe_emit(
        emit_diagnostic_fn,
        phase_code_name="INTAKE_DRAFT_CONTRACT",
        event_code_name="INTAKE_DRAFT_CONTRACT_VIOLATION",
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
      phase_code_name="INTAKE_DRAFT_CONTRACT",
      event_code_name="INTAKE_DRAFT_CONTRACT_VALIDATED",
      status_name="COMPLETED",
      diagnostic_data={
        "side": side,
        "stage": stage,
        "has_fulfillment_json": contract.fulfillment_json is not None,
      },
    )
  return contract


def validate_industry_baseline_cascade_payload_at_boundary(
  payload: Dict[str, Any],
  *,
  side: str,
  stage: str = INDUSTRY_BASELINE_STAGE_LABEL,
  emit_diagnostic_fn: Optional[Callable[..., Any]] = None,
) -> CascadeResolverPayloadContract:
  """P3.40 Contract 6 Commit 3 -- Shape A consumer-side gate.
  Validates the cascade resolver payload (13 fields per metric)
  per F5-α (NO cohort_query). Single PhaseCode per F16;
  diagnostic_data['shape']='A' distinguishes from Shape B/C/D
  emissions.

  Consumer-side: called from _attach_seed_provenance at
  finmo_bridge.py:339 and from
  driver_movement_assembler._resolve_naics_band at
  driver_movement_assembler.py:97.
  """
  try:
    contract = CascadeResolverPayloadContract.model_validate(payload)
  except ValidationError as exc:
    field_path, expected, actual = _extract_first_error(exc)
    if emit_diagnostic_fn is not None:
      _safe_emit(
        emit_diagnostic_fn,
        phase_code_name="INDUSTRY_BASELINE_CONTRACT",
        event_code_name="INDUSTRY_BASELINE_CONTRACT_VIOLATION",
        status_name="FAILED",
        diagnostic_data={
          "side": side, "stage": stage, "shape": "A",
          "field": field_path,
          "expected": expected[:300], "actual": actual[:300],
          "error_count": len(exc.errors()),
        },
      )
    raise ContractViolation(
      stage=stage, field=field_path,
      expected=expected, actual=actual, source_payload=payload,
    ) from exc

  if emit_diagnostic_fn is not None:
    _safe_emit(
      emit_diagnostic_fn,
      phase_code_name="INDUSTRY_BASELINE_CONTRACT",
      event_code_name="INDUSTRY_BASELINE_CONTRACT_VALIDATED",
      status_name="COMPLETED",
      diagnostic_data={
        "side": side, "stage": stage, "shape": "A",
        "metric_key": contract.metric_key,
        "trust_flag": contract.trust_flag,
        "naics_level_used": contract.naics_level_used,
      },
    )
  return contract


def validate_industry_baseline_cohort_sql_row_at_boundary(
  payload: Dict[str, Any],
  *,
  side: str,
  stage: str = INDUSTRY_BASELINE_STAGE_LABEL,
  emit_diagnostic_fn: Optional[Callable[..., Any]] = None,
) -> CohortSqlRowContract:
  """P3.40 Contract 6 Commit 3 -- Shape B per-row gate. F12 (a)
  benchmark monotonicity invariant fires here when all 3
  benchmark values are non-None. Per F15: per-row validation
  SKIPPED at the production populator (no in-process consumer
  reads SQL rows directly; R13 covers defense-in-depth).
  This helper exists for test paths + future direct-SQL
  consumers."""
  try:
    contract = CohortSqlRowContract.model_validate(payload)
  except ValidationError as exc:
    field_path, expected, actual = _extract_first_error(exc)
    if emit_diagnostic_fn is not None:
      _safe_emit(
        emit_diagnostic_fn,
        phase_code_name="INDUSTRY_BASELINE_CONTRACT",
        event_code_name="INDUSTRY_BASELINE_CONTRACT_VIOLATION",
        status_name="FAILED",
        diagnostic_data={
          "side": side, "stage": stage, "shape": "B",
          "field": field_path,
          "expected": expected[:300], "actual": actual[:300],
          "error_count": len(exc.errors()),
        },
      )
    raise ContractViolation(
      stage=stage, field=field_path,
      expected=expected, actual=actual, source_payload=payload,
    ) from exc

  if emit_diagnostic_fn is not None:
    _safe_emit(
      emit_diagnostic_fn,
      phase_code_name="INDUSTRY_BASELINE_CONTRACT",
      event_code_name="INDUSTRY_BASELINE_CONTRACT_VALIDATED",
      status_name="COMPLETED",
      diagnostic_data={
        "side": side, "stage": stage, "shape": "B",
        "section": contract.section,
        "lever_id": contract.lever_id,
      },
    )
  return contract


def validate_industry_baseline_get_bands_view_at_boundary(
  payload: Dict[str, Any],
  *,
  side: str,
  stage: str = INDUSTRY_BASELINE_STAGE_LABEL,
  emit_diagnostic_fn: Optional[Callable[..., Any]] = None,
) -> GetBandsViewContract:
  """P3.40 Contract 6 Commit 3 -- Shape C consumer-side gate.
  Validates the in-memory get_bands view before handing to
  amalgamated tools / mirror.build_mirror /
  evaluate_plan._margin_distance_from_bands.

  Per F7: 12 fields per band (NOT 14); naics_prefix_used +
  data_source silently dropped at SQL -> in-memory translation.
  F12 (b) benchmark monotonicity invariant fires on each band
  when all 3 benchmark values are non-None.

  Consumer-side: called inside get_bands at
  cohort_bands_table.py:386 immediately before return.
  """
  try:
    contract = GetBandsViewContract.model_validate(payload)
  except ValidationError as exc:
    field_path, expected, actual = _extract_first_error(exc)
    if emit_diagnostic_fn is not None:
      _safe_emit(
        emit_diagnostic_fn,
        phase_code_name="INDUSTRY_BASELINE_CONTRACT",
        event_code_name="INDUSTRY_BASELINE_CONTRACT_VIOLATION",
        status_name="FAILED",
        diagnostic_data={
          "side": side, "stage": stage, "shape": "C",
          "field": field_path,
          "expected": expected[:300], "actual": actual[:300],
          "error_count": len(exc.errors()),
        },
      )
    raise ContractViolation(
      stage=stage, field=field_path,
      expected=expected, actual=actual, source_payload=payload,
    ) from exc

  if emit_diagnostic_fn is not None:
    _safe_emit(
      emit_diagnostic_fn,
      phase_code_name="INDUSTRY_BASELINE_CONTRACT",
      event_code_name="INDUSTRY_BASELINE_CONTRACT_VALIDATED",
      status_name="COMPLETED",
      diagnostic_data={
        "side": side, "stage": stage, "shape": "C",
        "section": contract.section,
        "count": contract.count,
      },
    )
  return contract


def validate_industry_baseline_population_summary_at_boundary(
  payload: Dict[str, Any],
  *,
  side: str,
  stage: str = INDUSTRY_BASELINE_STAGE_LABEL,
  emit_diagnostic_fn: Optional[Callable[..., Any]] = None,
) -> PopulationSummaryContract:
  """P3.40 Contract 6 Commit 3 -- Shape D producer-side gate
  per F14 (a). Includes F10 cross-field invariant (total
  resolved >= 1 across all 5 sections). Closes v1 §F-2
  FAIL_COHORT_BANDS_MISSING precondition that today is
  swallowed by the soft try/except at runner.py:556-583.

  Producer-side: called immediately after
  populate_cohort_bands_for_run returns at runner.py:580+.
  """
  try:
    contract = PopulationSummaryContract.model_validate(payload)
  except ValidationError as exc:
    field_path, expected, actual = _extract_first_error(exc)
    if emit_diagnostic_fn is not None:
      _safe_emit(
        emit_diagnostic_fn,
        phase_code_name="INDUSTRY_BASELINE_CONTRACT",
        event_code_name="INDUSTRY_BASELINE_CONTRACT_VIOLATION",
        status_name="FAILED",
        diagnostic_data={
          "side": side, "stage": stage, "shape": "D",
          "field": field_path,
          "expected": expected[:300], "actual": actual[:300],
          "error_count": len(exc.errors()),
        },
      )
    raise ContractViolation(
      stage=stage, field=field_path,
      expected=expected, actual=actual, source_payload=payload,
    ) from exc

  if emit_diagnostic_fn is not None:
    total_resolved = sum(
      section.resolved
      for section in (
        contract.drivers, contract.balance_sheet,
        contract.stage_ramp, contract.capex_rd, contract.payroll,
      )
      if section is not None
    )
    _safe_emit(
      emit_diagnostic_fn,
      phase_code_name="INDUSTRY_BASELINE_CONTRACT",
      event_code_name="INDUSTRY_BASELINE_CONTRACT_VALIDATED",
      status_name="COMPLETED",
      diagnostic_data={
        "side": side, "stage": stage, "shape": "D",
        "total_resolved": total_resolved,
      },
    )
  return contract


def validate_amalgamated_session_at_boundary(
  payload: Dict[str, Any],
  *,
  side: str,
  stage: str = AMALGAMATED_SESSION_STAGE_LABEL,
  emit_diagnostic_fn: Optional[Callable[..., Any]] = None,
) -> MirrorContract:
  """P3.40 Contract 7 Commit 3 -- Shape A gate. Validates the full
  Mirror payload (9 data fields per mirror.py:75-86) against
  ``MirrorContract``. Carries the F5 plan_state_alias_sync
  @model_validator (Bug 2 fix invariant) + composes Contract 6
  GetBandsViewContract for mirror.bands per F1.

  Producer-side: called at the end of build_mirror (mirror.py:329+)
  via ``dataclasses.asdict(mirror)`` per F14 -- recursive
  conversion handles the nested RecentDecision dataclass
  automatically.

  Consumer-side: called inside ``Mirror.to_dict()``
  (mirror.py:182-192); the method already builds the dict, the
  gate validates that dict before returning.

  Per F0 + F12: SINGLE PhaseCode AMALGAMATED_SESSION_CONTRACT
  covers both helpers; diagnostic_data['shape']='mirror'
  distinguishes from the validation_state slice gate.

  On failure raises ``ContractViolation`` with the
  AMALGAMATED_SESSION stage label and the first
  ``ValidationError`` extracted into structured fields. Per F11
  / trace Div-8: the API handler at intake_consult.py:7377
  catches ``except Exception as exc:`` (skips line-7298
  RuntimeError because ContractViolation is Exception subclass,
  not RuntimeError). The violation surfaces as a structured 500
  with str(exc) carrying ``AMALGAMATED_SESSION_STAGE_LABEL`` +
  field path. Verified by Adjustment B tests in
  ``tests/test_p3_40_contract_7_consumer_gate.py``.

  Diagnostic emission is best-effort (same pattern as Contracts
  1-6 helpers): emits ``AMALGAMATED_SESSION_CONTRACT_VALIDATED``
  on success and ``AMALGAMATED_SESSION_CONTRACT_VIOLATION`` on
  failure when ``emit_diagnostic_fn`` is supplied. Failures
  swallowed so observability cannot break the gate.
  """
  try:
    contract = MirrorContract.model_validate(payload)
  except ValidationError as exc:
    field_path, expected, actual = _extract_first_error(exc)
    if emit_diagnostic_fn is not None:
      _safe_emit(
        emit_diagnostic_fn,
        phase_code_name="AMALGAMATED_SESSION_CONTRACT",
        event_code_name="AMALGAMATED_SESSION_CONTRACT_VIOLATION",
        status_name="FAILED",
        diagnostic_data={
          "side": side, "stage": stage, "shape": "mirror",
          "field": field_path,
          "expected": expected[:300], "actual": actual[:300],
          "error_count": len(exc.errors()),
        },
      )
    raise ContractViolation(
      stage=stage, field=field_path,
      expected=expected, actual=actual, source_payload=payload,
    ) from exc

  if emit_diagnostic_fn is not None:
    _safe_emit(
      emit_diagnostic_fn,
      phase_code_name="AMALGAMATED_SESSION_CONTRACT",
      event_code_name="AMALGAMATED_SESSION_CONTRACT_VALIDATED",
      status_name="COMPLETED",
      diagnostic_data={
        "side": side, "stage": stage, "shape": "mirror",
        "plan_state_section_count": len(contract.plan_state),
        "bands_section_count": len(contract.bands),
        "has_validation_state": contract.validation_state is not None,
        "recent_decisions_count": (
          len(contract.recent_decisions)
          if contract.recent_decisions is not None else 0
        ),
      },
    )
  return contract


def validate_amalgamated_validation_state_at_boundary(
  payload: Dict[str, Any],
  *,
  side: str,
  stage: str = AMALGAMATED_SESSION_STAGE_LABEL,
  emit_diagnostic_fn: Optional[Callable[..., Any]] = None,
) -> ValidationStateProjectionContract:
  """P3.40 Contract 7 Commit 3 -- Shape D gate. Validates the
  Bug 3 bounded projection (11 fields per mirror.py:146-157)
  against ``ValidationStateProjectionContract``. Carries the F6
  (i)-(iv) cross-field invariants: cap on failing_check_names,
  cap on failing_lever_margins, truncation flag consistency,
  outside_band filter.

  Consumer-side: called inside ``responder.render_mirror_for_proposal``
  at responder.py:269+ where the validation_state slice is read
  for GPT rendering. Only validates when vs is non-empty
  (validation_state is {} pre-evaluate).

  Per F0 + F12: SINGLE PhaseCode AMALGAMATED_SESSION_CONTRACT
  covers both helpers; diagnostic_data['shape']='validation_state'
  distinguishes from the full Mirror gate.

  On failure raises ``ContractViolation`` with the
  AMALGAMATED_SESSION stage label and the first ``ValidationError``
  extracted into structured fields. Adjustment B propagation per
  the Shape A helper docstring above.

  Diagnostic emission best-effort (same pattern).
  """
  try:
    contract = ValidationStateProjectionContract.model_validate(payload)
  except ValidationError as exc:
    field_path, expected, actual = _extract_first_error(exc)
    if emit_diagnostic_fn is not None:
      _safe_emit(
        emit_diagnostic_fn,
        phase_code_name="AMALGAMATED_SESSION_CONTRACT",
        event_code_name="AMALGAMATED_SESSION_CONTRACT_VIOLATION",
        status_name="FAILED",
        diagnostic_data={
          "side": side, "stage": stage, "shape": "validation_state",
          "field": field_path,
          "expected": expected[:300], "actual": actual[:300],
          "error_count": len(exc.errors()),
        },
      )
    raise ContractViolation(
      stage=stage, field=field_path,
      expected=expected, actual=actual, source_payload=payload,
    ) from exc

  if emit_diagnostic_fn is not None:
    _safe_emit(
      emit_diagnostic_fn,
      phase_code_name="AMALGAMATED_SESSION_CONTRACT",
      event_code_name="AMALGAMATED_SESSION_CONTRACT_VALIDATED",
      status_name="COMPLETED",
      diagnostic_data={
        "side": side, "stage": stage, "shape": "validation_state",
        "all_pass": contract.all_pass,
        "round_number": contract.round_number,
        "failing_check_count": contract.failing_check_count,
        "failing_lever_margins_count": len(contract.failing_lever_margins),
      },
    )
  return contract


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
  "WORKBOOK_STAGE_LABEL",
  "SOLVER_STAGE_LABEL",
  "SOLVER_OUTPUT_STAGE_LABEL",
  "INTAKE_DRAFT_STAGE_LABEL",
  "INDUSTRY_BASELINE_STAGE_LABEL",
  "AMALGAMATED_SESSION_STAGE_LABEL",
  "SIDE_PRODUCER",
  "SIDE_CONSUMER",
  "validate_model_input_at_boundary",
  "validate_workbook_payload_at_boundary",
  "validate_solver_input_at_boundary",
  "validate_solver_output_at_boundary",
  "validate_intake_draft_at_boundary",
  "validate_industry_baseline_cascade_payload_at_boundary",
  "validate_industry_baseline_cohort_sql_row_at_boundary",
  "validate_industry_baseline_get_bands_view_at_boundary",
  "validate_industry_baseline_population_summary_at_boundary",
  "validate_amalgamated_session_at_boundary",
  "validate_amalgamated_validation_state_at_boundary",
  "make_boundary_emitter",
]
