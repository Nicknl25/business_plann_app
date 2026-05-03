"""Initialize gate for production post-intake runtime validation."""

from __future__ import annotations

import copy
from typing import Any, Dict, List

from client_intake_and_finmo.post_intake_runtime_validation.balance_sheet_driver_validation import (  # type: ignore
  balance_sheet_driver_initialization_sample_errors,
  build_balance_sheet_driver_initialization_sample,
)
from client_intake_and_finmo.post_intake_foundation import (  # type: ignore
  post_intake_assert_runtime_table_integrity,
)
from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
  post_intake_assert_required_process_sequence,
  post_intake_cash_policy_errors,
  post_intake_contract_forecast_horizon_quarter_count,
  post_intake_driver_formula_contract_rows,
  post_intake_driver_target_mapping_errors,
  post_intake_gpt_context_errors,
  post_intake_gpt_contract_errors,
  post_intake_gpt_contract_openai_schema,
  post_intake_process_step_context,
  post_intake_process_sequence_errors,
)


def _raise_if_errors(errors: List[str]) -> None:
  if errors:
    raise RuntimeError(
      "post_intake_initialize_validation_failed: "
      + "; ".join(str(item) for item in errors[:80])
    )


def _assert_callable(name: str, fn: Any, errors: List[str]) -> None:
  if not callable(fn):
    errors.append(f"lookup_function_not_callable: {name}")


def run_initialize_post_intake_validation(
  *,
  draft_id: str = "",
  planning_run_id: str = "",
) -> Dict[str, Any]:
  """Validate that the table-backed post-intake machine can run.

  This is a production gate. It validates lookup tables, lookup functions,
  sequence rows, contract schemas, formula metadata, and required horizons
  before post-intake begins spending OpenAI/runtime cycles.
  """
  errors: List[str] = []
  _assert_callable("post_intake_assert_runtime_table_integrity", post_intake_assert_runtime_table_integrity, errors)
  _assert_callable("post_intake_assert_required_process_sequence", post_intake_assert_required_process_sequence, errors)
  _assert_callable("post_intake_driver_formula_contract_rows", post_intake_driver_formula_contract_rows, errors)
  _assert_callable("post_intake_gpt_contract_openai_schema", post_intake_gpt_contract_openai_schema, errors)

  runtime_table_integrity: Dict[str, Any] = {}
  required_process_sequence: Dict[str, Any] = {}
  process_step_contexts: Dict[str, Any] = {}
  schema_contracts: Dict[str, Any] = {}
  draft_row: Dict[str, Any] = {}
  balance_sheet_driver_sample: Dict[str, Any] = {}

  try:
    runtime_table_integrity = post_intake_assert_runtime_table_integrity()
  except Exception as exc:
    errors.append(f"runtime_table_integrity_unavailable: {exc}")
  if str(draft_id or "").strip():
    try:
      from client_intake_and_finmo.intake_submission import get_mysql_connection  # type: ignore

      conn = get_mysql_connection()
      try:
        cur = conn.cursor(dictionary=True)
        try:
          cur.execute(
            """
            SELECT draft_id, business_name, operating_model_json, financials_json, financials_year1_json
            FROM intake_consult_drafts
            WHERE draft_id = %s
            LIMIT 1
            """,
            (str(draft_id).strip(),),
          )
          draft_row = cur.fetchone() or {}
        finally:
          cur.close()
      finally:
        conn.close()
    except Exception as exc:
      errors.append(f"initialize_draft_sample_unavailable: {exc}")
  try:
    required_process_sequence = post_intake_assert_required_process_sequence()
  except Exception as exc:
    errors.append(f"process_sequence_unavailable: {exc}")

  for source_name, source_errors in [
    ("mapping", post_intake_driver_target_mapping_errors),
    ("cash_policy", post_intake_cash_policy_errors),
    ("gpt_contract", post_intake_gpt_contract_errors),
    ("gpt_context", post_intake_gpt_context_errors),
    ("process_sequence", post_intake_process_sequence_errors),
  ]:
    try:
      errors.extend(f"{source_name}: {item}" for item in (source_errors() or []))
    except Exception as exc:
      errors.append(f"{source_name}_validation_unavailable: {exc}")

  try:
    from client_intake_and_finmo.post_intake_headcount import post_intake_headcount_policy_errors  # type: ignore

    errors.extend(f"headcount_policy: {item}" for item in (post_intake_headcount_policy_errors() or []))
  except Exception as exc:
    errors.append(f"headcount_policy_validation_unavailable: {exc}")

  for step_key in [
    "post_intake_initialize_validation",
    "baseline_model_input",
    "maintenance_capex_percent",
    "r_and_d_applicability",
    "stage_ramp_contract",
    "quarter_grid_generation",
    "payroll_headcount_schedule",
    "issue_detection",
    "unified_convergence_decision",
    "cash_minimum_debt_schedule",
    "cash_strategy_review",
    "cash_pass_validation",
    "final_hard_gates",
    "post_intake_finalize_validation",
  ]:
    try:
      process_step_contexts[step_key] = post_intake_process_step_context(step_key=step_key)
    except Exception as exc:
      errors.append(f"process_step_context_unavailable: {step_key}: {exc}")

  for contract_name in [
    "maintenance_capex_percent",
    "r_and_d_applicability",
    "stage_ramp_contract",
    "payroll_headcount_schedule",
    "quarter_grid_probe",
    "unified_convergence_decision",
    "cash_strategy_review",
  ]:
    try:
      schema = post_intake_gpt_contract_openai_schema(contract_name=contract_name)
      if not isinstance(schema, dict) or schema.get("type") != "object":
        errors.append(f"contract_schema_invalid: {contract_name}")
      schema_contracts[contract_name] = {
        "schema_type": schema.get("type") if isinstance(schema, dict) else None,
        "property_count": len((schema.get("properties") or {}) if isinstance(schema, dict) else {}),
      }
    except Exception as exc:
      errors.append(f"contract_schema_unavailable: {contract_name}: {exc}")

  for contract_name in [
    "stage_ramp_contract",
    "payroll_headcount_schedule",
    "unified_convergence_decision",
    "cash_strategy_review",
  ]:
    try:
      horizon = int(post_intake_contract_forecast_horizon_quarter_count(contract_name=contract_name) or 0)
      if horizon != 20:
        errors.append(f"contract_horizon_invalid: {contract_name} expected=20 actual={horizon}")
    except Exception as exc:
      errors.append(f"contract_horizon_unavailable: {contract_name}: {exc}")

  formula_rows = []
  try:
    formula_rows = post_intake_driver_formula_contract_rows()
    if not formula_rows:
      errors.append("mapping_formula_contract_rows_missing")
    for row in formula_rows:
      if not row.get("seed_formula_key"):
        errors.append(f"{row.get('lever_id')} missing seed_formula_key")
      if not row.get("validation_formula_key"):
        errors.append(f"{row.get('lever_id')} missing validation_formula_key")
  except Exception as exc:
    errors.append(f"mapping_formula_contract_rows_unavailable: {exc}")

  try:
    balance_sheet_driver_sample = build_balance_sheet_driver_initialization_sample(
      draft_row=copy.deepcopy(draft_row),
    )
    if not balance_sheet_driver_sample.get("mapped_driver_count"):
      errors.append("balance_sheet_driver_initialization_sample_empty")
    errors.extend(
      f"balance_sheet_driver_initialization_sample_invalid: {item}"
      for item in balance_sheet_driver_initialization_sample_errors(balance_sheet_driver_sample)
    )
  except Exception as exc:
    errors.append(f"balance_sheet_driver_initialization_sample_unavailable: {exc}")

  _raise_if_errors(errors)
  return {
    "validation_gate": "post_intake_initialize_validation",
    "status": "completed",
    "draft_id": str(draft_id or "").strip(),
    "planning_run_id": str(planning_run_id or "").strip(),
    "runtime_table_integrity": copy.deepcopy(runtime_table_integrity),
    "required_process_sequence": copy.deepcopy(required_process_sequence),
    "process_step_contexts": copy.deepcopy(process_step_contexts),
    "schema_contracts": copy.deepcopy(schema_contracts),
    "balance_sheet_driver_initialization_sample": copy.deepcopy(balance_sheet_driver_sample),
    "mapping_formula_contract_count": len(formula_rows),
    "validated_tables": [
      "post_intak_mapping_lookup",
      "post_intake_cash_policy_lookup",
      "post_intake_gpt_contract_lookup",
      "post_intake_gpt_context_lookup",
      "post_intake_headcount_policy_lookup",
      "post_intake_process_sequence_lookup",
    ],
  }
