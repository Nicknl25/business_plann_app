"""Golden Rule structural enforcement for post-intake.

The invariant is intentionally simple:
deterministic post-intake structure comes from lookup tables, not scattered
constants, prompt prose, or intake-handler globals.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Set

from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
  post_intake_cash_policy_errors,
  post_intake_contract_forecast_horizon_quarter_count,
  post_intake_driver_target_mapping_errors,
  post_intake_driver_target_lever_ids_for_issue,
  post_intake_gpt_context_errors,
  post_intake_gpt_contract_errors,
  post_intake_gpt_contract_rows,
  post_intake_gpt_context_rows,
  post_intake_golden_lookup_snapshot_errors,
  post_intake_issue_codes,
  post_intake_issue_codes_for_phase,
  post_intake_process_sequence_rows,
  post_intake_process_sequence_errors,
  post_intake_target_metric_names_for_issue,
)


_REPO_ROOT = Path(__file__).resolve().parents[3]
_INTAKE_HANDLER_PATH = _REPO_ROOT / "python" / "api_handlers" / "intake_consult.py"
_PROMPTS_ROOT = _REPO_ROOT / "python" / "client_intake_and_finmo" / "prompts"
_POST_INTAKE_ROOT = _REPO_ROOT / "python" / "client_intake_and_finmo"
_REQUIRED_CONTRACTS = {
  "maintenance_capex_percent",
  "r_and_d_applicability",
  "stage_ramp_contract",
  "payroll_headcount_schedule",
  "unified_convergence_decision",
  "cash_strategy_review",
  "unified_convergence_verification",
}
_REQUIRED_CONTEXT_CONTRACTS = {
  "stage_ramp_contract",
  "payroll_headcount_schedule",
  "unified_convergence_decision",
  "cash_strategy_review",
}
_FORBIDDEN_INTAKE_DEFINITIONS = (
  "_ISSUE_CODE_REGISTRY",
  "_CASH_PASS_OWNED_ISSUE_CODES",
  "_REMAINING_HORIZON_ISSUE_CODES",
  "_SOLVER_TARGET_METRIC_KEYS",
  "_REQUIRED_SOLVER_TARGET_METRIC_KEYS",
  "_UNIFIED_ALLOWED_TARGET_METRIC_KEYS",
  "_CASH_STRATEGY_DEBT_ISSUANCE_LEVER_ID",
  "_CASH_STRATEGY_ALLOWED_LEVER_IDS",
  "_CASH_STRATEGY_FUNDING_SOURCE_LEVER_IDS",
  "_CASH_STRATEGY_BUFFER_MONTHS",
  "_CASH_STRATEGY_PREFERRED_DEBT_RATIO",
  "_SHAPE_SENSITIVE_ALLOWED_SHAPE_TYPES",
)
_RETIRED_POST_INTAKE_ISSUE_CODE_LITERALS = (
  '"business_model_coherence"',
  '"capex_footprint_mismatch"',
  '"cash_distribution_violation"',
  '"cash_strategy_contract_failure"',
  '"cash_surplus_deployment_failure"',
  '"financial_solvency_mismatch"',
  '"pricing_positioning_mismatch"',
  '"profitability_cash_shape"',
  "'business_model_coherence'",
  "'capex_footprint_mismatch'",
  "'cash_distribution_violation'",
  "'cash_strategy_contract_failure'",
  "'cash_surplus_deployment_failure'",
  "'financial_solvency_mismatch'",
  "'pricing_positioning_mismatch'",
  "'profitability_cash_shape'",
)


def _headcount_policy_errors() -> List[str]:
  try:
    from client_intake_and_finmo.post_intake_headcount import post_intake_headcount_policy_errors  # type: ignore
  except Exception as exc:
    return [f"post_intake_headcount_policy_lookup_unavailable: {exc}"]
  return list(post_intake_headcount_policy_errors() or [])


def _issue_detector_alignment_errors() -> List[str]:
  errors: List[str] = []
  try:
    from client_intake_and_finmo.post_intake_issues.detection import (  # type: ignore
      post_intake_issue_detector_alignment_errors,
    )
  except Exception as exc:
    errors.append(f"post_intake_issue_detector_alignment_unavailable: {exc}")
  else:
    errors.extend(str(item) for item in (post_intake_issue_detector_alignment_errors() or []))
  try:
    from client_intake_and_finmo.post_intake_cash.runner import (  # type: ignore
      post_intake_cash_issue_alignment_errors,
    )
  except Exception as exc:
    errors.append(f"post_intake_cash_issue_alignment_unavailable: {exc}")
  else:
    errors.extend(str(item) for item in (post_intake_cash_issue_alignment_errors() or []))
  return errors


def _intake_boundary_errors() -> List[str]:
  if not _INTAKE_HANDLER_PATH.exists():
    return [f"intake_consult_boundary_missing_file: {_INTAKE_HANDLER_PATH}"]
  text = _INTAKE_HANDLER_PATH.read_text(encoding="utf-8")
  errors: List[str] = []
  for token in _FORBIDDEN_INTAKE_DEFINITIONS:
    for line_number, line in enumerate(text.splitlines(), start=1):
      stripped = line.strip()
      if stripped.startswith(f"{token} =") or stripped.startswith(f"{token}:"):
        errors.append(
          f"intake_consult_post_intake_authority_forbidden: {token} defined at line {line_number}"
        )
  return errors


def _prompt_table_reference_errors() -> List[str]:
  if not _PROMPTS_ROOT.exists():
    return []
  errors: List[str] = []
  for prompt_path in _PROMPTS_ROOT.rglob("*.md"):
    text = prompt_path.read_text(encoding="utf-8").lower()
    relative = prompt_path.relative_to(_REPO_ROOT).as_posix()
    if "post_intake" not in relative:
      # Existing prompt folders under client_intake_and_finmo are post-intake
      # prompts by usage, but this guard stays focused on table-backed prompts.
      pass
    if "sql.post_intak_mapping_lookup" not in text and "sql.post_intake_gpt_contract_lookup" not in text:
      errors.append(
        f"post_intake_prompt_missing_table_authority_reference: {relative}"
      )
  return errors


def _retired_issue_literal_errors() -> List[str]:
  errors: List[str] = []
  if not _POST_INTAKE_ROOT.exists():
    return errors
  for path in _POST_INTAKE_ROOT.rglob("*.py"):
    relative = path.relative_to(_REPO_ROOT).as_posix()
    if "__pycache__" in relative:
      continue
    if path == Path(__file__).resolve():
      continue
    text = path.read_text(encoding="utf-8")
    for literal in _RETIRED_POST_INTAKE_ISSUE_CODE_LITERALS:
      if literal in text:
        errors.append(
          f"retired_post_intake_issue_code_literal_forbidden: {literal} in {relative}"
        )
  return errors


def _contract_and_context_errors() -> List[str]:
  errors: List[str] = []
  for contract_name in sorted(_REQUIRED_CONTRACTS):
    rows = post_intake_gpt_contract_rows(contract_name=contract_name)
    if not rows:
      errors.append(f"post_intake_contract_missing_rows: {contract_name}")
  for contract_name in sorted(_REQUIRED_CONTEXT_CONTRACTS):
    rows = post_intake_gpt_context_rows(contract_name=contract_name, include_in_prompt=True)
    if not rows:
      errors.append(f"post_intake_context_missing_prompt_rows: {contract_name}")
  for contract_name in ("stage_ramp_contract", "payroll_headcount_schedule", "unified_convergence_decision"):
    horizon = int(post_intake_contract_forecast_horizon_quarter_count(contract_name=contract_name) or 0)
    if horizon != 20:
      errors.append(
        f"post_intake_contract_horizon_invalid: {contract_name} expected=20 actual={horizon}"
      )
  return errors


def _issue_mapping_errors() -> List[str]:
  errors: List[str] = []
  all_issue_codes: Set[str] = {
    str(code or "").strip().lower()
    for code in post_intake_issue_codes()
    if str(code or "").strip()
  }
  convergence_codes = {
    str(code or "").strip().lower()
    for code in post_intake_issue_codes_for_phase("convergence", targeting_allowed=True)
    if str(code or "").strip()
  }
  cash_codes = {
    str(code or "").strip().lower()
    for code in post_intake_issue_codes_for_phase("cash_pass")
    if str(code or "").strip()
  }
  if not convergence_codes:
    errors.append("post_intake_issue_mapping_missing_convergence_codes")
  if not cash_codes:
    errors.append("post_intake_issue_mapping_missing_cash_codes")
  for issue_code in sorted(all_issue_codes):
    phase = "cash_pass" if issue_code in cash_codes else "convergence"
    levers = post_intake_driver_target_lever_ids_for_issue(issue_code, phase=phase)
    targets = post_intake_target_metric_names_for_issue(issue_code, phase=phase)
    if issue_code not in {"accounting_integrity_failure", "structural_impossibility"}:
      if not levers:
        errors.append(f"post_intake_issue_mapping_missing_levers: {issue_code}/{phase}")
      if phase == "convergence" and not targets:
        errors.append(f"post_intake_issue_mapping_missing_targets: {issue_code}/{phase}")
  return errors


def _sequence_errors() -> List[str]:
  errors = list(post_intake_process_sequence_errors() or [])
  rows = post_intake_process_sequence_rows(active_only=True)
  if not rows:
    errors.append("post_intake_process_sequence_lookup_has_no_active_steps")
  for row in rows:
    step_key = str(row.get("step_key") or "").strip().lower()
    if not step_key:
      continue
    if not row.get("required_lookup_tables"):
      errors.append(f"post_intake_process_step_missing_required_lookup_tables: {step_key}")
    if not str(row.get("horizon_rule") or "").strip():
      errors.append(f"post_intake_process_step_missing_horizon_rule: {step_key}")
    if row.get("contract_name") and not post_intake_gpt_contract_rows(contract_name=row.get("contract_name")):
      errors.append(f"post_intake_process_step_contract_missing: {step_key}/{row.get('contract_name')}")
  return errors


def post_intake_golden_rule_errors() -> List[str]:
  errors: List[str] = []
  errors.extend(str(item) for item in (post_intake_driver_target_mapping_errors() or []))
  errors.extend(str(item) for item in (post_intake_cash_policy_errors() or []))
  errors.extend(str(item) for item in (post_intake_gpt_contract_errors() or []))
  errors.extend(str(item) for item in (post_intake_gpt_context_errors() or []))
  errors.extend(str(item) for item in (post_intake_golden_lookup_snapshot_errors() or []))
  errors.extend(str(item) for item in _headcount_policy_errors())
  errors.extend(_contract_and_context_errors())
  errors.extend(_issue_mapping_errors())
  errors.extend(_issue_detector_alignment_errors())
  errors.extend(_sequence_errors())
  errors.extend(_intake_boundary_errors())
  errors.extend(_retired_issue_literal_errors())
  errors.extend(_prompt_table_reference_errors())
  return errors


def post_intake_assert_golden_rule_integrity() -> Dict[str, Any]:
  errors = post_intake_golden_rule_errors()
  if errors:
    raise RuntimeError(
      "post_intake_golden_rule_violation: "
      + "; ".join(str(item) for item in errors[:50])
    )
  return {
    "golden_rule_enforced": True,
    "source_of_truth": "lookup_tables",
    "validated_tables": [
      "post_intak_mapping_lookup",
      "post_intake_cash_policy_lookup",
      "post_intake_gpt_contract_lookup",
      "post_intake_gpt_context_lookup",
      "post_intake_headcount_policy_lookup",
      "post_intake_process_sequence_lookup",
      "post_intake_lookup_table_snapshot",
    ],
  }
