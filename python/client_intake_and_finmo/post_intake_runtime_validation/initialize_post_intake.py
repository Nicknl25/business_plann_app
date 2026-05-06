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
  post_intake_gpt_context_rows,
  post_intake_gpt_contract_errors,
  post_intake_gpt_contract_openai_schema,
  post_intake_gpt_contract_rows,
  post_intake_process_context_errors,
  post_intake_process_context_rows,
  post_intake_process_sequence_step,
  post_intake_process_sequence_errors,
)
from client_intake_and_finmo.post_intake_sequence import build_post_intake_sequence_controller  # type: ignore


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


def _raise_if_errors(errors: List[str]) -> None:
  if errors:
    raise RuntimeError(
      "post_intake_initialize_validation_failed: "
      + "; ".join(str(item) for item in errors[:80])
    )


def _assert_payroll_headcount_initialization_contract(errors: List[str]) -> None:
  try:
    contract_rows = post_intake_gpt_contract_rows(contract_name="payroll_headcount_schedule")
    field_paths = {
      _clean_text(row.get("field_path"))
      for row in contract_rows
      if isinstance(row, dict)
    }
    forbidden_paths = {
      "payroll_headcount_grid[].role_family",
      "payroll_headcount_grid[].role_category",
      "payroll_headcount_grid[].role_title",
      "payroll_headcount_grid[].avg_annual_wage",
      "payroll_headcount_grid[].annual_wage",
    }
    leaked_paths = sorted(field_paths.intersection(forbidden_paths))
    if leaked_paths:
      errors.append(f"payroll_headcount_initialization_legacy_contract_fields_present: {leaked_paths}")
    required_paths = {
      "payroll_headcount_grid[].oews_occ_title",
      "payroll_headcount_grid[].starting_fte",
      "payroll_headcount_grid[].hires",
      "payroll_headcount_grid[].ending_fte",
      "payroll_headcount_grid[].payroll_tax_benefits_pct",
      "capacity_units_per_supporting_fte",
      "target_payroll_percent_of_revenue",
    }
    missing_paths = sorted(required_paths.difference(field_paths))
    if missing_paths:
      errors.append(f"payroll_headcount_initialization_required_contract_fields_missing: {missing_paths}")
    title_rows = [
      row
      for row in contract_rows
      if isinstance(row, dict)
      and _clean_text(row.get("field_path")) == "payroll_headcount_grid[].oews_occ_title"
    ]
    if not title_rows:
      errors.append("payroll_headcount_initialization_oews_title_field_missing")
    elif _clean_text(title_rows[0].get("lookup_source")) != "oews_title_catalog":
      errors.append(
        "payroll_headcount_initialization_oews_title_lookup_invalid: "
        f"actual={_clean_text(title_rows[0].get('lookup_source')) or 'missing'}"
      )
  except Exception as exc:
    errors.append(f"payroll_headcount_initialization_contract_check_unavailable: {exc}")

  try:
    context_rows = post_intake_gpt_context_rows(
      contract_name="payroll_headcount_schedule",
      include_phase="pre_convergence",
    )
    context_keys = {
      _clean_text(row.get("context_key"))
      for row in context_rows
      if isinstance(row, dict)
    }
    if "oews_role_catalog" in context_keys:
      errors.append("payroll_headcount_initialization_legacy_oews_role_catalog_present")
    if "oews_title_catalog" not in context_keys:
      errors.append("payroll_headcount_initialization_oews_title_catalog_missing")
  except Exception as exc:
    errors.append(f"payroll_headcount_initialization_context_check_unavailable: {exc}")

  try:
    sequence_row = post_intake_process_sequence_step("payroll_headcount_schedule", required=True) or {}
    quarter_row = post_intake_process_sequence_step("quarter_grid_generation", required=True) or {}
    timing = _clean_text(sequence_row.get("python_timing"))
    notes = _clean_text(sequence_row.get("notes")).lower()
    action = _clean_text(sequence_row.get("python_action")).lower()
    payroll_order = float(sequence_row.get("step_order") or sequence_row.get("sequence_order") or sequence_row.get("order_index") or 0)
    quarter_order = float(quarter_row.get("step_order") or quarter_row.get("sequence_order") or quarter_row.get("order_index") or 0)
    if timing == "after_quarter_grid_before_convergence":
      errors.append("payroll_headcount_initialization_legacy_reverse_timing_present")
    if payroll_order and quarter_order and payroll_order > quarter_order:
      errors.append("payroll_headcount_initialization_legacy_reverse_order_present")
    if "after the quarter grid" in notes or "against the applied quarter grid" in action:
      errors.append("payroll_headcount_initialization_legacy_capacity_demand_sequence_present")
    if "derive" not in action or "capacity" not in action:
      errors.append("payroll_headcount_initialization_capacity_derivation_action_missing")
  except Exception as exc:
    errors.append(f"payroll_headcount_initialization_process_sequence_check_unavailable: {exc}")


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
  process_context_row_count = 0

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
    ("process_context", post_intake_process_context_errors),
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
  _assert_payroll_headcount_initialization_contract(errors)
  try:
    process_context_row_count = len(post_intake_process_context_rows(active_only=True))
  except Exception as exc:
    errors.append(f"process_context_rows_unavailable: {exc}")

  sequence_controller = build_post_intake_sequence_controller()
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
      process_step_contexts[step_key] = sequence_controller.step_context(
        step_key=step_key,
        resolve_inputs=False,
      )
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
    "process_context_row_count": process_context_row_count,
    "validated_tables": [
      "post_intak_mapping_lookup",
      "post_intake_cash_policy_lookup",
      "post_intake_gpt_contract_lookup",
      "post_intake_gpt_context_lookup",
      "post_intake_headcount_policy_lookup",
      "post_intake_process_sequence_lookup",
      "post_intake_process_context_lookup",
    ],
  }
