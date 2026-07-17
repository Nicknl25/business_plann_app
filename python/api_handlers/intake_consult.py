import copy
import hashlib
import json
import math
import os
import re
import sys
import time
import calendar
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from flask import jsonify

logger = logging.getLogger(__name__)
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(_REPO_ROOT))
import requests
from client_intake_and_finmo.intake_consult_draft import (
  append_messages,
  begin_planning_run,
  clear_planning_run_action,
  current_app_timestamp_iso,
  current_app_timestamp_str,
  current_app_timezone_name,
  get_draft,
  get_latest_planning_run_checkpoint,
  get_planning_run,
  persist_post_intake_execution_state,
  request_planning_run_action,
)
from client_intake_and_finmo.openai_http import post_openai_with_retries  # type: ignore
try:
  from api_handlers.shared_context import build_shared_context  # type: ignore
except Exception:
  build_shared_context = None  # type: ignore
from client_intake_and_finmo.fact_templates import sanitize_fact_template  # type: ignore
from client_intake_and_finmo.realism_memo import generate_realism_memo_payload_safe  # type: ignore
# Phase 4 / Issue 1: explicit module imports replace wildcards. Each runner
# module is imported by name; cross-runner helpers are pulled via the
# runner's __all__ list at dependency-dict-build time. No wildcard imports;
# no globals() round-trip; the dependency contract is the runner's __all__.
from client_intake_and_finmo.post_intake_cash import runner as _post_intake_cash_runner  # type: ignore
# Phase 8: post_intake_issues legacy machinery deleted. The replacement
# is post_intake_resolution_state, which provides the small set of
# realism-gate-backed helpers the convergence runner / cash / contracts
# / runtime / state runner consume + legacy-name compat shims for the
# bound underscore-prefixed helpers callers used to receive via the
# legacy runner's __all__.
from client_intake_and_finmo import post_intake_resolution_state as _post_intake_resolution_state  # type: ignore
from client_intake_and_finmo.post_intake_contracts import runner as _post_intake_contracts_runner  # type: ignore
from client_intake_and_finmo.post_intake_state import runner as _post_intake_state_runner  # type: ignore
# post_intake_convergence/runner.py was deleted in Phase 3 step 7 (the
# GPT-loop runner was dead code since Phase 2.5 — target_seeking_orchestrator
# is the live convergence path). post_intake_convergence/runtime.py survives
# only as a deterministic-helper module.
from client_intake_and_finmo.post_intake_convergence import runtime as _post_intake_convergence_runtime  # type: ignore
from client_intake_and_finmo.post_intake_initial_grid import prepare_initial_grid_for_draft  # type: ignore
from client_intake_and_finmo.post_intake_sequence import run_targeted_process_step  # type: ignore

# Bind-runtime-dependencies callables exposed under their handler-side names.
bind_cash_runtime_dependencies = _post_intake_cash_runner.bind_runtime_dependencies
# Phase 8: bind_issue_runtime_dependencies removed; legacy runner deleted.
bind_contract_runtime_dependencies = _post_intake_contracts_runner.bind_runtime_dependencies
bind_state_runtime_dependencies = _post_intake_state_runner.bind_runtime_dependencies
bind_convergence_runtime_dependencies = _post_intake_convergence_runtime.bind_runtime_dependencies
# bind_convergence_execution_runtime_dependencies removed in Phase 3 step 7
# (post_intake_convergence/runner.py deleted).

# Cross-runner helpers used directly within this module. The bind dict
# below carries the union of every runner's __all__, so these names are
# also reachable through that path; importing them here is for direct use
# by intake_consult.py code paths.
_assert_r_and_d_applicability_policy_applied = _post_intake_contracts_runner._assert_r_and_d_applicability_policy_applied
_derive_maintenance_capex_percent_from_naics = _post_intake_contracts_runner._derive_maintenance_capex_percent_from_naics
_estimate_balance_sheet_contextual_seed_with_gpt = _post_intake_contracts_runner._estimate_balance_sheet_contextual_seed_with_gpt
_estimate_r_and_d_applicability_with_gpt = _post_intake_contracts_runner._estimate_r_and_d_applicability_with_gpt
_estimate_stage_ramp_contract_with_gpt = _post_intake_contracts_runner._estimate_stage_ramp_contract_with_gpt
# iter 19 Stage 5 — Python-first stage ramp builder + handler-on-failure.
# Replaces the GPT-only authoring path. The dependency-injection name
# stays `estimate_stage_ramp_contract_with_gpt` so the initial-grid
# runner's signature does not need to change; behind it, the new
# function tries the Python builder first and engages the stage ramp
# handler only when the validator rejects the deterministic output
# (doctrine.md §3 Pattern 2).
from client_intake_and_finmo.post_intake_contracts.runner import (  # type: ignore  # noqa: E402
  build_python_stage_ramp_contract as _build_python_stage_ramp_contract,
  _validate_stage_ramp_contract_payload as _validate_stage_ramp_contract_payload_for_handler,
)
from client_intake_and_finmo.post_intake_stage_ramp_handler import (  # type: ignore  # noqa: E402
  engage_stage_ramp_handler_on_validator_failure as _engage_stage_ramp_handler,
)


def _stage_ramp_contract_python_first_with_handler(
  *,
  business_facts,
  ops_json,
  financials_json,
  financials_year1_json,
  people_json=None,
  planning_mode,
  planning_mode_reason,
  model_input_json,
  finmo_json,
  r_and_d_applicability=None,
):
  """iter 19 Stage 5 dependency-injection wrapper. Returns the same
  contract shape the legacy GPT-only path returned. On Python-and-
  handler exhaustion the wrapper RE-RAISES a prefixed RuntimeError
  (stage_ramp_handler_exhausted: ...). The orchestrator records the
  failure rather than shipping a bad ramp; no legacy-GPT fallback is
  taken (doctrine §1 hard-fail with diagnostic). P3.21 Part 2
  housekeeping: pre-housekeeping docstring referenced a 'falls back
  to legacy GPT call' behavior that the code never implemented."""
  try:
    return _engage_stage_ramp_handler(
      build_python_contract=_build_python_stage_ramp_contract,
      validator=_validate_stage_ramp_contract_payload_for_handler,
      business_facts=business_facts,
      ops_json=ops_json,
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
      people_json=people_json,
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      model_input_json=model_input_json,
      finmo_json=finmo_json,
      r_and_d_applicability=r_and_d_applicability,
    )
  except RuntimeError as exc:
    # Stage ramp handler exhausted. Per doctrine §1 hard-fail, surface
    # the diagnostic with the legacy GPT path as documentation of
    # what the alternative path used to do — but DO raise so the
    # orchestrator records a real failure rather than shipping a
    # bad ramp.
    raise RuntimeError(
      "stage_ramp_handler_exhausted: " + str(exc)
    ) from exc
_extract_numeric_solver_feedback_for_persistence = _post_intake_contracts_runner._extract_numeric_solver_feedback_for_persistence
_first_contract_product_missing_periods = _post_intake_contracts_runner._first_contract_product_missing_periods
_r_and_d_policy_from_model_input = _post_intake_contracts_runner._r_and_d_policy_from_model_input
_build_planning_run_payload = _post_intake_state_runner._build_planning_run_payload
_maybe_interrupt_planning_run = _post_intake_state_runner._maybe_interrupt_planning_run
_persist_failed_system_run_snapshot = _post_intake_state_runner._persist_failed_system_run_snapshot
_build_planning_context_summary_payload = _post_intake_convergence_runtime._build_planning_context_summary_payload

# Convergence package surface re-exported under aliases used elsewhere.
from client_intake_and_finmo.post_intake_convergence import (  # type: ignore  # noqa: E402
  build_retry_scope_payload as convergence_build_retry_scope_payload,
  build_unified_convergence_contract_policy,
  evaluate_retry_improvement as convergence_evaluate_retry_improvement,
  full_horizon_quarters as convergence_full_horizon_quarters,
  full_horizon_retry_scope_mode as convergence_full_horizon_retry_scope_mode,
  retry_scope_lever_ids as convergence_retry_scope_lever_ids,
  retry_scope_quarters as convergence_retry_scope_quarters,
  subset_numeric_solver_contract as convergence_subset_numeric_solver_contract,
  unified_convergence_contract_constraints,
  validate_unified_convergence_contract_horizon,
)

OPS_CONFIRM_QUESTION = "Does this look right before we move on to Target Market?"
OPS_MILESTONE_QUESTION = (
  "Looking ahead, what is one concrete goal you want to hit in about the next 12 months "
  "(for example: a target number of weekly units/orders, a customer count, or a rough monthly revenue level)?"
)

class PlanningRunLifecycleInterrupt(RuntimeError):
  def __init__(self, *, action: str, planning_run_id: str, detail: str):
    super().__init__(detail)
    self.action = str(action or "").strip().lower()
    self.planning_run_id = str(planning_run_id or "").strip()
    self.detail = str(detail or "").strip()


class StructuredSystemRunFailure(RuntimeError):
  def __init__(self, *, detail: str, diagnostics: Optional[Dict[str, Any]] = None):
    super().__init__(detail)
    self.detail = str(detail or "").strip()
    self.diagnostics = (
      copy.deepcopy(diagnostics)
      if isinstance(diagnostics, dict)
      else {}
    )


_POST_INTAKE_RUNTIME_DEPENDENCY_PROVIDER_MODULES = (
  _post_intake_cash_runner,
  # Phase 8: post_intake_resolution_state replaces _post_intake_issues_runner
  # as the source of bound helpers (realism-gate-backed + legacy-name shims).
  _post_intake_resolution_state,
  _post_intake_contracts_runner,
  _post_intake_state_runner,
  _post_intake_convergence_runtime,
)

# Helpers and aliases defined inside intake_consult.py (or imported into
# its module scope) that runners need at runtime via the bind injection.
# Listed explicitly — replacing the legacy globals()-as-source pattern
# with an enumerated allow-list. Source-truth: derived from an AST audit
# of every runner's referenced-but-not-locally-defined names, intersected
# with intake_consult.py's module attributes, minus names already
# provided by any runner's __all__.
_INTAKE_CONSULT_OWN_RUNTIME_DEPENDENCY_NAMES = (
  "PlanningRunLifecycleInterrupt",
  "StructuredSystemRunFailure",
  # intake_consult-private helpers consumed by runners.
  "_format_currency",
  "_is_missing_number_value",
  "_openai_call_telemetry_snapshot",
  "_openai_key",
  "_openai_model",
  "_parse_json_dict",
  "_parse_milestones",
  "_parse_responses_text",
  "_parse_responses_json_dict",
  "_post_openai",
  "_safe_float",
  "_safe_int",
  "_series_changed_count",
  "_set_active_openai_deadline",
  "_structured_system_run_failure_detail",
  "post_openai_with_retries",
  "build_shared_context",
  "logger",
  # Convergence package re-exports under intake_consult-side aliases.
  "build_unified_convergence_contract_policy",
  "convergence_build_retry_scope_payload",
  "convergence_evaluate_retry_improvement",
  "convergence_full_horizon_quarters",
  "convergence_full_horizon_retry_scope_mode",
  "convergence_retry_scope_lever_ids",
  "convergence_retry_scope_quarters",
  "convergence_subset_numeric_solver_contract",
  "unified_convergence_contract_constraints",
  "validate_unified_convergence_contract_horizon",
  # intake_consult_draft helpers consumed via injection.
  "append_messages",
  "begin_planning_run",
  "clear_planning_run_action",
  "current_app_timestamp_iso",
  "current_app_timestamp_str",
  "current_app_timezone_name",
  "get_draft",
  "get_latest_planning_run_checkpoint",
  "get_planning_run",
  "persist_post_intake_execution_state",
  "request_planning_run_action",
)


def _post_intake_runtime_dependency_dict() -> Dict[str, Any]:
  """Phase 4 / Issue 1: build the cross-runner dependency dict explicitly.

  Source of truth for cross-runner helpers is each provider module's
  __all__; intake_consult.py-owned helpers come from a named allow-list
  above. No reliance on `globals()` as a symbol bridge; no wildcard
  imports anywhere. Each helper is sourced from a named module.
  """
  dependencies: Dict[str, Any] = {}
  for module in _POST_INTAKE_RUNTIME_DEPENDENCY_PROVIDER_MODULES:
    for name in getattr(module, "__all__", ()) or ():
      if name in dependencies:
        continue
      attr = getattr(module, name, None)
      if attr is None:
        continue
      dependencies[name] = attr
  module_globals = globals()
  for name in _INTAKE_CONSULT_OWN_RUNTIME_DEPENDENCY_NAMES:
    if name not in dependencies and name in module_globals:
      dependencies[name] = module_globals[name]
  return dependencies


def _bind_post_intake_runtime_dependencies() -> None:
  dependencies = _post_intake_runtime_dependency_dict()
  bind_cash_runtime_dependencies(dependencies)
  # Phase 8: bind_issue_runtime_dependencies removed; legacy runner deleted.
  bind_contract_runtime_dependencies(dependencies)
  bind_state_runtime_dependencies(dependencies)
  # P3.33 Phase 3 step 7: bind_convergence_execution_runtime_dependencies
  # removed (post_intake_convergence/runner.py deleted).
  bind_convergence_runtime_dependencies(dependencies)


def _dispatch_post_intake_failure_alert(
  *,
  app,
  conn,
  draft_id: str,
  active_run: Optional[Dict[str, Any]],
  exception: BaseException,
  failure_detail: str,
  failure_details_payload: Optional[Dict[str, Any]],
  failure_diagnostics_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  """Phase 9 P3.10 Commit 5 Part B — failure-side outreach.

  Called from both ``except RuntimeError`` and the catch-all
  ``except Exception`` blocks of the system-run handler. Performs
  three side-effects (each logged-and-continued; never raises):

    1. Best-effort INSERT of a ``post_intake_run_diagnostics`` row
       with ``acceptance_score="FAILED"`` so the failure is visible
       to the same SQL telemetry the success path uses.
    2. Best-effort fetch of the draft's business name + planning
       run id for the email subject + body.
    3. Best-effort dispatch of the failure-alert email via
       ``workbook_email.send_failure_alert``. SMTP failure is logged
       at ERROR; the run is already failing, the email outcome
       cannot make it worse.

  Returns the email outcome dict so the API's HTTP 500 response can
  surface ``sent``, ``reason``, ``recipient``, ``subject`` to the
  caller. The returned dict is always present, even when no email
  could be attempted.
  """
  draft_id_s = str(draft_id or "").strip()
  business_name = ""
  planning_run_id = ""
  if isinstance(active_run, dict):
    planning_run_id = str(active_run.get("planning_run_id") or "").strip()
  workbook_path: Optional[str] = None
  if isinstance(active_run, dict):
    workbook_candidate = active_run.get("client_workbook_path")
    if isinstance(workbook_candidate, str) and workbook_candidate.strip():
      workbook_path = workbook_candidate.strip()
  try:
    cur = conn.cursor(dictionary=True)
    try:
      cur.execute(
        "SELECT business_name FROM intake_consult_drafts WHERE draft_id = %s",
        (draft_id_s,),
      )
      row = cur.fetchone()
      if isinstance(row, dict):
        business_name = str(row.get("business_name") or "").strip()
    finally:
      try:
        cur.close()
      except Exception:
        pass
  except Exception as exc:
    app.logger.error(
      "Failure-alert business_name lookup failed for draft %s: %s: %s",
      draft_id_s, type(exc).__name__, str(exc)[:200],
    )

  failure_diagnostic: Dict[str, Any] = {}
  to_dict = getattr(exception, "to_dict", None)
  if callable(to_dict):
    try:
      structured = to_dict()
      if isinstance(structured, dict):
        failure_diagnostic = structured
    except Exception:
      failure_diagnostic = {}
  if not failure_diagnostic and isinstance(failure_details_payload, dict):
    failure_diagnostic = dict(failure_details_payload)

  failed_diag_payload = {
    "draft_id": draft_id_s,
    "planning_run_id": planning_run_id or None,
    "business_name": business_name or None,
    "acceptance_passed": False,
    "acceptance_score": None,            # numeric contract field (no score on failure)
    "acceptance_score_label": "FAILED",  # display form
    "handler_fired": False,
    "failure_exception_class": type(exception).__name__,
    "failure_detail": str(failure_detail or "")[:4000],
    "failure_diagnostic": failure_diagnostic,
    "failure_diagnostics_payload": failure_diagnostics_payload or {},
    "captured_at": datetime.utcnow().isoformat() + "Z",
  }
  try:
    from client_intake_and_finmo.post_intake_run_diagnostics import (  # type: ignore
      persist_run_diagnostics,
    )
    persist_run_diagnostics(conn, payload=failed_diag_payload)
  except Exception as exc:
    app.logger.error(
      "Failed-run diagnostic persistence failed for draft %s: %s: %s",
      draft_id_s, type(exc).__name__, str(exc)[:300],
    )

  try:
    from client_intake_and_finmo.workbook_email import (  # type: ignore
      send_failure_alert,
    )
    return send_failure_alert(
      business_name=business_name or "(unknown business)",
      exception_class=type(exception).__name__,
      exception_message=str(exception),
      failure_diagnostic=failure_diagnostic,
      draft_id=draft_id_s or None,
      planning_run_id=planning_run_id or None,
      attachment_paths=[workbook_path] if workbook_path else None,
    )
  except Exception as exc:
    app.logger.error(
      "Failure-alert dispatch raised unexpectedly for draft %s: %s: %s",
      draft_id_s, type(exc).__name__, str(exc)[:300],
    )
    return {
      "sent": False,
      "reason": "dispatch_exception",
      "error": f"{type(exc).__name__}: {str(exc)[:200]}",
    }


def _structured_system_run_failure_detail(
  *,
  diagnostics: Optional[Dict[str, Any]],
  fallback: str,
) -> str:
  diag = diagnostics if isinstance(diagnostics, dict) else {}
  stage = str(diag.get("failure_stage") or "").strip()
  reason = str(diag.get("failure_reason") or "").strip()
  lever = str(diag.get("lever") or "").strip()
  validation_context = (
    diag.get("validation_context")
    if isinstance(diag.get("validation_context"), dict)
    else {}
  )
  pre_solver_validation = (
    validation_context.get("pre_solver_validation")
    if isinstance(validation_context.get("pre_solver_validation"), dict)
    else diag.get("pre_solver_validation")
    if isinstance(diag.get("pre_solver_validation"), dict)
    else {}
  )
  first_error = next(
    (
      item for item in (pre_solver_validation.get("errors") or [])
      if isinstance(item, dict)
    ),
    {},
  )
  error_code = str(first_error.get("error") or "").strip()
  error_reason = str(first_error.get("reason") or "").strip()
  parts = [
    part
    for part in [
      stage,
      reason,
      error_code if error_code and error_code != reason else "",
      lever or str(first_error.get("lever_id") or "").strip(),
      error_reason,
    ]
    if part
  ]
  return ": ".join(parts) if parts else (str(fallback or "").strip() or "system_run_failed")










MARKET_CONFIRM_QUESTION = "Does this look right before we move on to Human Resources?"
PEOPLE_CONFIRM_QUESTION = "Does this look right before we move on to Financials?"
COMPETITIVE_ADVANTAGE_PREFIX = "Proposed competitive advantage:"
COMPETITIVE_ADVANTAGE_QUESTION = "Does this accurately reflect what truly sets the business apart?"
_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
_ACTIVE_OPENAI_DEADLINE_MONOTONIC: Optional[float] = None
_ACTIVE_OPENAI_DEADLINE_RETURN_GUARD_SECONDS = 8.0
_INTAKE_CONSULT_RUNTIME_PROBE_VERSION = "2026-04-23-post-intake-numeric-contract-v32"
_OPENAI_CALL_TELEMETRY: Dict[str, Any] = {
  "logical_call_count": 0,
  "by_model": {},
  "events": [],
}


























def _reset_openai_call_telemetry() -> None:
  _OPENAI_CALL_TELEMETRY["logical_call_count"] = 0
  _OPENAI_CALL_TELEMETRY["by_model"] = {}
  _OPENAI_CALL_TELEMETRY["events"] = []


def _openai_call_telemetry_snapshot() -> Dict[str, Any]:
  return {
    "logical_call_count": int(_safe_float(_OPENAI_CALL_TELEMETRY.get("logical_call_count")) or 0),
    "by_model": copy.deepcopy(
      _OPENAI_CALL_TELEMETRY.get("by_model")
      if isinstance(_OPENAI_CALL_TELEMETRY.get("by_model"), dict)
      else {}
    ),
    "events": copy.deepcopy(
      _OPENAI_CALL_TELEMETRY.get("events")
      if isinstance(_OPENAI_CALL_TELEMETRY.get("events"), list)
      else []
    ),
  }


def _parse_json_dict(raw: Any) -> Dict[str, Any]:
  if raw is None:
    return {}
  if isinstance(raw, dict):
    return raw
  try:
    parsed = json.loads(str(raw))
  except Exception:
    return {}
  return parsed if isinstance(parsed, dict) else {}


def _parse_messages(raw: Any) -> List[Dict[str, str]]:
  if raw is None:
    return []
  if isinstance(raw, list):
    return [m for m in raw if isinstance(m, dict)]
  try:
    parsed = json.loads(str(raw))
  except Exception:
    return []
  return [m for m in parsed if isinstance(m, dict)] if isinstance(parsed, list) else []


def _parse_pending_bool(raw: Any) -> bool:
  # Treat any non-null-ish, truthy value as pending.
  if raw is None:
    return False
  if raw is False:
    return False
  if raw == 0:
    return False
  if isinstance(raw, str):
    val = raw.strip().lower()
    if not val or val in ("0", "false", "null", "none", "[]", "{}"):
      return False
    return True
  if isinstance(raw, (list, dict)):
    return bool(raw)
  return bool(raw)


def _is_missing_number_value(value: Any) -> bool:
  if value is None:
    return True
  if isinstance(value, bool):
    return True
  try:
    return float(value) <= 0
  except Exception:
    return True


def _normalize_ops_capacity_compat(ops_obj: Any) -> Any:
  """
  Capacity compatibility: keep ops capacity coherent without re-asking the user.

  Rules (minimal, non-destructive):
  - If unit_cadence is weekly and week capacity is set, fill missing period capacity from it.
  - If unit_cadence is monthly/contract and period capacity is set, fill missing week capacity from it.
  - If unit_cadence is weekly/monthly and operating_periods_per_year is missing, fill it with 52/12.
  - Never overwrite an existing non-missing capacity number.
  - For multi-product ops (lob_models with >1 product), only normalize per-product fields;
    keep top-level unit fields null by design.
  """
  if not isinstance(ops_obj, dict):
    return ops_obj

  def _normalize_unit_dict(d: Dict[str, Any]) -> None:
    cadence = str(d.get("unit_cadence") or "").strip().lower()
    week = d.get("units_per_week_capacity")
    period = d.get("units_per_period_capacity")
    periods_per_year = d.get("operating_periods_per_year")

    if cadence == "weekly":
      if _is_missing_number_value(period) and not _is_missing_number_value(week):
        d["units_per_period_capacity"] = week
      if _is_missing_number_value(periods_per_year):
        d["operating_periods_per_year"] = 52
      return

    if cadence in ("monthly", "contract"):
      if _is_missing_number_value(week) and not _is_missing_number_value(period):
        d["units_per_week_capacity"] = period
      elif _is_missing_number_value(period) and not _is_missing_number_value(week):
        d["units_per_period_capacity"] = week
      if cadence == "monthly" and _is_missing_number_value(periods_per_year):
        d["operating_periods_per_year"] = 12
      return

    # Unknown cadence: best-effort fill the missing side only.
    if _is_missing_number_value(week) and not _is_missing_number_value(period):
      d["units_per_week_capacity"] = period
    elif _is_missing_number_value(period) and not _is_missing_number_value(week):
      d["units_per_period_capacity"] = week

  lob_models = ops_obj.get("lob_models")
  product_count = 0
  if isinstance(lob_models, list):
    for lob in lob_models:
      if not isinstance(lob, dict):
        continue
      prods = lob.get("products")
      if not isinstance(prods, list):
        continue
      for p in prods:
        if isinstance(p, dict):
          product_count += 1
          _normalize_unit_dict(p)

  # Only normalize top-level unit fields if this is not a multi-product model.
  if product_count <= 1:
    _normalize_unit_dict(ops_obj)

  return ops_obj


def _count_ops_products(ops_obj: Any) -> int:
  if not isinstance(ops_obj, dict):
    return 0
  total = 0
  lob_models = ops_obj.get("lob_models")
  if not isinstance(lob_models, list):
    return 0
  for lob in lob_models:
    if not isinstance(lob, dict):
      continue
    products = lob.get("products")
    if not isinstance(products, list):
      continue
    total += sum(1 for product in products if isinstance(product, dict))
  return total


def _extract_single_compact_number(text: Any) -> Optional[float]:
  blob = str(text or "").strip()
  if not blob:
    return None
  tokens = re.findall(r"\$?\d[\d,]*(?:\.\d+)?\s*[kKmM]?", blob)
  values: List[float] = []
  for tok in tokens:
    cleaned = str(tok or "").strip().replace("$", "").replace(",", "")
    match = re.match(r"^(\d+(?:\.\d+)?)\s*([kKmM]?)$", cleaned)
    if not match:
      continue
    try:
      value = float(match.group(1))
    except Exception:
      continue
    suffix = str(match.group(2) or "").strip().lower()
    if suffix == "k":
      value *= 1000.0
    elif suffix == "m":
      value *= 1000000.0
    values.append(value)
  if len(values) != 1:
    return None
  value = float(values[0])
  return value if value > 0 else None


def _extract_single_compact_number_allow_zero(text: Any) -> Optional[float]:
  blob = str(text or "").strip()
  if not blob:
    return None
  tokens = re.findall(r"\$?\d[\d,]*(?:\.\d+)?\s*[kKmM]?", blob)
  values: List[float] = []
  for tok in tokens:
    cleaned = str(tok or "").strip().replace("$", "").replace(",", "")
    match = re.match(r"^(\d+(?:\.\d+)?)\s*([kKmM]?)$", cleaned)
    if not match:
      continue
    try:
      value = float(match.group(1))
    except Exception:
      continue
    suffix = str(match.group(2) or "").strip().lower()
    if suffix == "k":
      value *= 1000.0
    elif suffix == "m":
      value *= 1000000.0
    values.append(value)
  if not values:
    return None
  unique_values: List[float] = []
  for value in values:
    if not any(abs(value - existing) < 1e-9 for existing in unique_values):
      unique_values.append(value)
  if len(unique_values) != 1:
    return None
  value = float(unique_values[0])
  return value if value >= 0 else None


def _extract_compact_numbers(text: Any) -> List[float]:
  blob = str(text or "").strip()
  if not blob:
    return []
  tokens = re.findall(r"\$?\d[\d,]*(?:\.\d+)?\s*[kKmM]?", blob)
  values: List[float] = []
  for tok in tokens:
    cleaned = str(tok or "").strip().replace("$", "").replace(",", "")
    match = re.match(r"^(\d+(?:\.\d+)?)\s*([kKmM]?)$", cleaned)
    if not match:
      continue
    try:
      value = float(match.group(1))
    except Exception:
      continue
    suffix = str(match.group(2) or "").strip().lower()
    if suffix == "k":
      value *= 1000.0
    elif suffix == "m":
      value *= 1000000.0
    values.append(value)
  return values


def _looks_like_capacity_prompt(text: Any) -> bool:
  prompt = str(text or "").strip().lower()
  if not prompt:
    return False
  if "how many" not in prompt and "capacity" not in prompt:
    return False
  if "can you handle" in prompt and ("fully booked" in prompt or "busy month" in prompt or "busy week" in prompt):
    return True
  if "to make planning realistic" in prompt and ("fully busy" in prompt or "fully booked" in prompt):
    return True
  if "operationally stretched" in prompt or "over-crowded" in prompt:
    return True
  return False


def _capacity_field_for_cadence(cadence: Any) -> Tuple[str, str]:
  cadence_norm = str(cadence or "").strip().lower()
  if cadence_norm == "weekly":
    return "units_per_week_capacity", "week"
  if cadence_norm in {"monthly", "contract"}:
    return "units_per_period_capacity", "month"
  return "units_per_period_capacity", "period"


def _find_missing_capacity_target(
  snapshot_obj: Any,
  *,
  fallback_ops: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
  if not isinstance(snapshot_obj, dict):
    return None
  fallback = fallback_ops if isinstance(fallback_ops, dict) else {}
  lob_models = snapshot_obj.get("lob_models")
  if isinstance(lob_models, list):
    for lob_index, lob in enumerate(lob_models):
      if not isinstance(lob, dict):
        continue
      products = lob.get("products")
      if not isinstance(products, list):
        continue
      for product_index, product in enumerate(products):
        if not isinstance(product, dict):
          continue
        if not _is_missing_number_value(product.get("units_per_period_capacity")) or not _is_missing_number_value(
          product.get("units_per_week_capacity")
        ):
          continue
        cadence = (
          product.get("unit_cadence")
          or snapshot_obj.get("unit_cadence")
          or fallback.get("unit_cadence")
        )
        field, period_label = _capacity_field_for_cadence(cadence)
        label = str(
          product.get("product_name")
          or product.get("unit_name")
          or snapshot_obj.get("unit_name")
          or fallback.get("unit_name")
          or "this offering"
        ).strip()
        return {
          "kind": "product",
          "lob_index": lob_index,
          "product_index": product_index,
          "field": field,
          "period_label": period_label,
          "label": label,
        }
  if _is_missing_number_value(snapshot_obj.get("units_per_period_capacity")) and _is_missing_number_value(
    snapshot_obj.get("units_per_week_capacity")
  ):
    cadence = snapshot_obj.get("unit_cadence") or fallback.get("unit_cadence")
    field, period_label = _capacity_field_for_cadence(cadence)
    label = str(snapshot_obj.get("unit_name") or fallback.get("unit_name") or "units").strip() or "units"
    return {
      "kind": "top_level",
      "field": field,
      "period_label": period_label,
      "label": label,
    }
  return None


def _build_capacity_target_question(target: Dict[str, Any]) -> str:
  period_label = str(target.get("period_label") or "period").strip() or "period"
  label = str(target.get("label") or "units").strip() or "units"
  if str(target.get("kind") or "").strip() == "product":
    return (
      f"To make planning realistic for {label}, in a fully busy {period_label}, "
      f"about how many {label} can you handle?"
    ).strip()
  return (
    f"To make planning realistic, in a fully busy {period_label}, "
    f"about how many {label} can you handle?"
  ).strip()


def _apply_capacity_target_value(snapshot_obj: Any, target: Dict[str, Any], value: float) -> Dict[str, Any]:
  next_snapshot = json.loads(json.dumps(snapshot_obj if isinstance(snapshot_obj, dict) else {}))
  field = str(target.get("field") or "").strip()
  if not field:
    return _normalize_ops_capacity_compat(next_snapshot)
  if str(target.get("kind") or "").strip() == "product":
    try:
      lob_index = int(target.get("lob_index"))
      product_index = int(target.get("product_index"))
      next_snapshot["lob_models"][lob_index]["products"][product_index][field] = float(value)
    except Exception:
      return _normalize_ops_capacity_compat(next_snapshot)
  else:
    next_snapshot[field] = float(value)
  return _normalize_ops_capacity_compat(next_snapshot)


def _apply_capacity_snapshot_to_ops_json(
  ops_json: Dict[str, Any],
  snapshot_obj: Dict[str, Any],
  target: Dict[str, Any],
) -> Dict[str, Any]:
  patch_obj: Dict[str, Any] = {}
  if isinstance(snapshot_obj.get("lob_models"), list):
    patch_obj["lob_models"] = snapshot_obj.get("lob_models")
  field = str(target.get("field") or "").strip()
  if field and field in snapshot_obj:
    patch_obj[field] = snapshot_obj.get(field)
  return _apply_model_ops_patch(dict(ops_json or {}), patch_obj)


def _infer_capacity_field_from_prompt(*, last_assistant: str, ops_json: Dict[str, Any]) -> Optional[str]:
  prompt = str(last_assistant or "").strip().lower()
  cadence = str((ops_json or {}).get("unit_cadence") or "").strip().lower()
  if "fully booked week" in prompt:
    return "units_per_week_capacity"
  if "fully booked month" in prompt or "fully booked period" in prompt:
    return "units_per_period_capacity"
  if cadence == "weekly":
    return "units_per_week_capacity"
  if cadence in {"monthly", "contract"}:
    return "units_per_period_capacity"
  return None


def _capacity_confirm_prompt_patch(
  *,
  last_assistant: str,
  user_message: str,
  ops_json: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  prompt = str(last_assistant or "").strip().lower()
  if "just to confirm your capacity:" not in prompt or "fully booked" not in prompt:
    return None
  if _count_ops_products(ops_json) > 1:
    return None
  value = _extract_single_compact_number(user_message)
  if value is None:
    return None
  field = _infer_capacity_field_from_prompt(last_assistant=last_assistant, ops_json=ops_json or {})
  if not field:
    return None
  return {field: float(value)}


def _apply_model_ops_patch(ops_json: Any, patch_obj: Any) -> Any:
  """
  Merge model-produced incremental Ops facts into the working Ops JSON.

  This mirrors the existing edit_patch persistence style, but stays scoped to Ops
  and ignores nulls so partial snapshots do not wipe prior answers.
  """
  if not isinstance(ops_json, dict) or not isinstance(patch_obj, dict):
    return ops_json

  allowed_keys = {
    "consumer_type",
    "business_type",
    "unit_name",
    "unit_description",
    "unit_cadence",
    "units_per_week_capacity",
    "units_per_period_capacity",
    "operating_periods_per_year",
    "utilization_rate",
    "unit_price",
    "shipping_method",
    "sales_modality",
    "geographic_scope",
    "geographic_coverage",
    "countries",
    "capacity_driver",
    "primary_growth_lever",
    "legal_entity",
    "lob_models",
  }
  for k, v in patch_obj.items():
    key = str(k or "").strip()
    if key not in allowed_keys or v is None:
      continue
    ops_json[key] = v

  # Keep single-product top-level convenience fields aligned with the product row.
  lob_models = ops_json.get("lob_models")
  if isinstance(lob_models, list) and len(lob_models) == 1:
    products = lob_models[0].get("products") if isinstance(lob_models[0], dict) else None
    if isinstance(products, list) and len(products) == 1 and isinstance(products[0], dict):
      product = products[0]

      def _maybe_copy_text(field: str) -> None:
        if not str(ops_json.get(field) or "").strip() and product.get(field) is not None:
          ops_json[field] = product.get(field)

      def _maybe_copy_number(field: str) -> None:
        if _is_missing_number_value(ops_json.get(field)) and product.get(field) is not None:
          ops_json[field] = product.get(field)

      _maybe_copy_text("unit_name")
      _maybe_copy_text("unit_description")
      _maybe_copy_text("unit_cadence")
      _maybe_copy_number("unit_price")
      _maybe_copy_number("units_per_week_capacity")
      _maybe_copy_number("units_per_period_capacity")
      _maybe_copy_number("operating_periods_per_year")
      _maybe_copy_number("utilization_rate")

  return _normalize_ops_capacity_compat(ops_json)




def _last_assistant_message(messages: List[Dict[str, str]]) -> str:
  for msg in reversed(messages or []):
    if str(msg.get("role") or "").strip().lower() != "assistant":
      continue
    text = str(msg.get("content") or "").strip()
    if text:
      return text
  return ""


def _sync_pending_revenue_adjustment_state(
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  revenue_adjudication: Any,
) -> Dict[str, Any]:
  next_financials = dict(financials_json or {})
  try:
    from financials_year1 import build_revenue_driver_signature as _build_signature  # type: ignore
  except Exception:
    from client_intake_and_finmo.financials_year1 import (  # type: ignore
      build_revenue_driver_signature as _build_signature,
    )
  current_signature = str(_build_signature(financials_year1_json or {}) or "").strip()
  locked_signature = str(next_financials.get("_revenue_adjustment_locked_signature") or "").strip()

  if locked_signature and current_signature and locked_signature == current_signature:
    next_financials.pop("_pending_revenue_adjustment_signature", None)
    next_financials.pop("_pending_revenue_adjustment_options", None)
    return next_financials

  if not isinstance(revenue_adjudication, dict):
    next_financials.pop("_pending_revenue_adjustment_signature", None)
    next_financials.pop("_pending_revenue_adjustment_options", None)
    return next_financials

  requires_adjustment = bool(revenue_adjudication.get("requires_adjustment"))
  options = revenue_adjudication.get("options")
  options = [option for option in (options or []) if isinstance(option, dict)]
  if requires_adjustment and current_signature and options:
    next_financials["_pending_revenue_adjustment_signature"] = current_signature
    next_financials["_pending_revenue_adjustment_options"] = options
  else:
    next_financials.pop("_pending_revenue_adjustment_signature", None)
    next_financials.pop("_pending_revenue_adjustment_options", None)
  return next_financials


def _build_cogs_baseline_signature(
  financials_year1_json: Dict[str, Any],
  ops_json: Dict[str, Any],
) -> str:
  try:
    from financials_year1 import build_revenue_driver_signature as _build_signature  # type: ignore
  except Exception:
    from client_intake_and_finmo.financials_year1 import (  # type: ignore
      build_revenue_driver_signature as _build_signature,
    )
  revenue_signature = str(_build_signature(financials_year1_json or {}) or "").strip()
  naics = str((ops_json or {}).get("business_naics_6") or "").strip()
  return f"{naics}::{revenue_signature}" if revenue_signature or naics else ""


def _build_cogs_estimate_context(
  *,
  ops_json: Dict[str, Any],
  shared_context: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Dict[str, Any]:
  people_ctx = dict((shared_context or {}).get("people_capability") or {})
  market_ctx = dict((shared_context or {}).get("target_market") or {})
  return {
    "business_type": str((ops_json or {}).get("business_type") or "").strip(),
    "business_naics_6": str((ops_json or {}).get("business_naics_6") or "").strip(),
    "unit_name": str((ops_json or {}).get("unit_name") or "").strip(),
    "unit_description": str((ops_json or {}).get("unit_description") or "").strip(),
    "unit_cadence": str((ops_json or {}).get("unit_cadence") or "").strip(),
    "unit_price": (ops_json or {}).get("unit_price"),
    "units_per_period_capacity": (ops_json or {}).get("units_per_period_capacity"),
    "units_per_week_capacity": (ops_json or {}).get("units_per_week_capacity"),
    "operating_periods_per_year": (ops_json or {}).get("operating_periods_per_year"),
    "utilization_rate": (ops_json or {}).get("utilization_rate"),
    "shipping_method": str((ops_json or {}).get("shipping_method") or "").strip(),
    "sales_modality": str((ops_json or {}).get("sales_modality") or "").strip(),
    "geographic_scope": str((ops_json or {}).get("geographic_scope") or "").strip(),
    "capacity_driver": str((ops_json or {}).get("capacity_driver") or "").strip(),
    "competitive_advantage": str((ops_json or {}).get("competitive_advantage") or "").strip(),
    "market_summary": str((market_ctx or {}).get("target_market_summary") or "").strip(),
    "key_people_summary": str((people_ctx or {}).get("key_people_summary") or "").strip(),
    "people": people_ctx.get("people") or [],
    "inferred_roles": people_ctx.get("inferred_roles") or [],
    "financials_year1_json": financials_year1_json or {},
  }


def _resolve_cogs_baseline_or_raise(
  *,
  conn,
  ops_json: Dict[str, Any],
  shared_context: Dict[str, Any],
  estimate_cogs_percent_from_context,
  financials_year1_json: Dict[str, Any],
) -> Dict[str, Any]:
  baseline = _compute_cogs_baseline(
    conn=conn,
    ops_json=ops_json,
    shared_context=shared_context,
    estimate_cogs_percent_from_context=estimate_cogs_percent_from_context,
    financials_year1_json=financials_year1_json,
  )
  if isinstance(baseline, dict):
    return baseline
  raise RuntimeError(
    "Unable to resolve a Year-1 COGS baseline from exact industry data or GPT estimation."
  )


def _compute_cogs_baseline(
  *,
  conn,
  ops_json: Dict[str, Any],
  shared_context: Dict[str, Any],
  estimate_cogs_percent_from_context,
  financials_year1_json: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  revenue_year1 = float((financials_year1_json or {}).get("company_revenue_total_year1") or 0.0)
  naics_6 = str((ops_json or {}).get("business_naics_6") or "").strip()
  if revenue_year1 <= 0 or not naics_6:
    return None

  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      """
      SELECT fiscalDateEnding, quarter, industry_cogs_percent
      FROM industry_growth_table
      WHERE naics_code = %s
        AND industry_cogs_percent IS NOT NULL
      ORDER BY fiscalDateEnding DESC, quarter DESC
      LIMIT 8
      """,
      (naics_6,),
    )
    rows = cur.fetchall() or []
  finally:
    cur.close()

  percents: List[float] = []
  years_used: List[str] = []
  seen_years = set()
  for row in rows:
    year = str(row.get("fiscalDateEnding") or "")[:4].strip()
    if year and year not in seen_years and len(seen_years) >= 2:
      continue
    value = row.get("industry_cogs_percent")
    if value is None:
      continue
    try:
      percents.append(float(value))
    except Exception:
      continue
    year = str(row.get("fiscalDateEnding") or "")[:4].strip()
    if year and year not in seen_years:
      seen_years.add(year)
      years_used.append(year)

  if percents:
    baseline_cogs_percent = float(sum(percents) / len(percents))
    baseline_cogs = float(revenue_year1 * baseline_cogs_percent)
    return {
      "baseline_cogs_percent": baseline_cogs_percent,
      "baseline_cogs": baseline_cogs,
      "cogs_adjustment": 0.0,
      "cogs_total_year1": baseline_cogs,
      "cogs_basis_naics": naics_6,
      "cogs_basis_years_used": years_used[:2],
      "revenue_year1": revenue_year1,
    }

  estimated = estimate_cogs_percent_from_context(
    cogs_estimate_context=_build_cogs_estimate_context(
      ops_json=ops_json,
      shared_context=shared_context,
      financials_year1_json=financials_year1_json,
    ),
  )
  if not estimated:
    return None
  baseline_cogs_percent = float(estimated.get("estimated_cogs_percent") or 0.0)
  baseline_cogs = float(revenue_year1 * baseline_cogs_percent)
  return {
    "baseline_cogs_percent": baseline_cogs_percent,
    "baseline_cogs": baseline_cogs,
    "cogs_adjustment": 0.0,
    "cogs_total_year1": baseline_cogs,
    "cogs_basis_naics": naics_6,
    "cogs_basis_years_used": [],
    "revenue_year1": revenue_year1,
    "cogs_basis_rationale": str(estimated.get("brief_rationale") or "").strip(),
  }


def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "" or isinstance(value, bool):
    return None
  try:
    return float(value)
  except Exception:
    return None


def _extract_first_number_from_text(value: Any) -> Optional[float]:
  text = str(value or "").replace(",", "").strip()
  if not text:
    return None
  match = re.search(r"-?\d+(?:\.\d+)?", text)
  if not match:
    return None
  try:
    return float(match.group(0))
  except Exception:
    return None


def _normalize_ratio_like(value: Any) -> Optional[float]:
  numeric = _safe_float(value)
  if numeric is None:
    return None
  if numeric > 1.0:
    return float(numeric) / 100.0
  return float(numeric)


def _safe_int(value: Any) -> Optional[int]:
  if value is None or value == "" or isinstance(value, bool):
    return None
  try:
    return int(float(value))
  except Exception:
    return None


def _format_currency(value: Any) -> str:
  amount = _safe_float(value)
  if amount is None:
    return "$0"
  return f"${amount:,.0f}"


def _format_percent(value: Any) -> str:
  ratio = _safe_float(value)
  if ratio is None:
    return "0%"
  return f"{ratio * 100:.0f}%"


def _summarize_income_intent(market_json: Dict[str, Any]) -> str:
  market = market_json if isinstance(market_json, dict) else {}
  values = market.get("income_intent")
  if not isinstance(values, list):
    return ""
  parts: List[str] = []
  for item in values:
    if not isinstance(item, dict):
      continue
    income_min = _safe_float(item.get("income_min"))
    income_max = _safe_float(item.get("income_max"))
    if income_min is None and income_max is None:
      continue
    if income_min is not None and income_max is not None:
      parts.append(f"{_format_currency(income_min)}-{_format_currency(income_max)}")
    elif income_min is not None:
      parts.append(f"{_format_currency(income_min)}+")
    else:
      parts.append(f"up to {_format_currency(income_max)}")
  return ", ".join(parts[:3])


def _summarize_gender_age_intent(market_json: Dict[str, Any]) -> str:
  market = market_json if isinstance(market_json, dict) else {}
  values = market.get("gender_age_intent")
  if not isinstance(values, list):
    return ""
  parts: List[str] = []
  for item in values:
    if not isinstance(item, dict):
      continue
    gender = str(item.get("gender") or "").strip()
    age_min = _safe_int(item.get("age_min"))
    age_max = _safe_int(item.get("age_max"))
    age_part = ""
    if age_min is not None and age_max is not None:
      age_part = f"{age_min}-{age_max}"
    elif age_min is not None:
      age_part = f"{age_min}+"
    elif age_max is not None:
      age_part = f"up to {age_max}"
    piece = ", ".join(part for part in [gender, age_part] if part)
    if piece:
      parts.append(piece)
  return "; ".join(parts[:3])


def _summarize_market_selections(market_json: Dict[str, Any]) -> List[str]:
  market = market_json if isinstance(market_json, dict) else {}
  selections = market.get("selections")
  if not isinstance(selections, list):
    return []
  labels: List[str] = []
  seen = set()
  for item in selections:
    if isinstance(item, dict):
      label = str(
        item.get("segment_name")
        or item.get("label")
        or item.get("selection_name")
        or item.get("name")
        or ""
      ).strip()
    else:
      label = str(item or "").strip()
    if not label or label in seen:
      continue
    seen.add(label)
    labels.append(label)
  return labels[:8]


def _milestone_cadence_hint(text: Any) -> str:
  lowered = str(text or "").strip().lower()
  if not lowered:
    return ""
  if "per week" in lowered or "weekly" in lowered or "a week" in lowered:
    return "weekly"
  if "per month" in lowered or "monthly" in lowered or "a month" in lowered:
    return "monthly"
  if "per year" in lowered or "annual" in lowered or "annually" in lowered or "yearly" in lowered:
    return "annual"
  return ""


def _period_capacity_for_cadence(product: Dict[str, Any], cadence: str) -> Optional[float]:
  cadence_norm = str(cadence or "").strip().lower()
  if cadence_norm == "weekly":
    return _safe_float(product.get("units_per_week_capacity"))
  if cadence_norm == "monthly":
    units = _safe_float(product.get("units_per_period_capacity"))
    return units
  if cadence_norm == "annual":
    units = _safe_float(product.get("units_per_period_capacity"))
    periods = _safe_float(product.get("operating_periods_per_year"))
    if units is not None and periods is not None:
      return units * periods
    annual_units = _safe_float(product.get("annual_units_year1"))
    return annual_units
  return None


def _replace_compact_number_in_text(text: Any, *, target_value: float, replacement_value: float) -> str:
  raw = str(text or "")
  if not raw:
    return raw

  def _normalize_number(value: float) -> str:
    rounded = round(float(value), 6)
    if abs(rounded - round(rounded)) < 1e-6:
      return str(int(round(rounded)))
    return f"{rounded:g}"

  pattern = re.compile(r"\b\d[\d,]*(?:\.\d+)?[kKmM]?\b")
  replaced = False

  def _repl(match: re.Match[str]) -> str:
    nonlocal replaced
    token = str(match.group(0) or "").strip()
    if not token:
      return token
    numeric = _extract_single_compact_number(token)
    if numeric is None:
      return token
    if replaced:
      return token
    if abs(float(numeric) - float(target_value)) > 1e-6:
      return token
    replaced = True
    return _normalize_number(replacement_value)

  updated = pattern.sub(_repl, raw, count=0)
  if replaced:
    return updated
  return pattern.sub(_normalize_number(replacement_value), raw, count=1)


def _refresh_shared_forecast_context(
  shared_context: Optional[Dict[str, Any]],
  bundle: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  del bundle
  return dict(shared_context or {})






























































































































































































































































































































































































































































































































































































































































































































def _series_changed_count(before: Any, after: Any, *, tolerance: float = 1.0) -> int:
  before_list = before if isinstance(before, list) else []
  after_list = after if isinstance(after, list) else []
  changed = 0
  for before_value, after_value in zip(before_list, after_list):
    if abs(float(_safe_float(before_value) or 0.0) - float(_safe_float(after_value) or 0.0)) > float(tolerance):
      changed += 1
  return changed




def _build_intake_complete_planning_run_payload() -> Dict[str, Any]:
  return _build_planning_run_payload(
    stage="intake_complete",
    status="pending",
    gpt_narrative="Intake complete. Ready for backend planning.",
  )


def _build_financials_completion_turn(*, acknowledgement: str = "") -> Dict[str, Any]:
  message = "Thanks. I have everything I need for financials, and the intake is complete."
  if str(acknowledgement or "").strip():
    message = f"{str(acknowledgement).strip()}\n\n{message}".strip()
  return {
    "assistant_message": message,
    "finalize_ready": False,
    "transition_to_done": True,
  }


def _persist_and_reload_financials_progress(
  *,
  conn,
  draft_id: str,
  business_facts: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
  append_messages(
    conn,
    draft_id=str(draft_id).strip(),
    new_messages=[],
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    marketing_model_json=marketing_model_json,
    active_focus="financials",
    business_facts=business_facts,
  )
  persisted = get_draft(conn, draft_id=str(draft_id).strip())
  return (
    _parse_json_dict(persisted.get("financials_json")),
    _parse_json_dict(persisted.get("financials_year1_json")),
    _parse_json_dict(persisted.get("marketing_model_json")),
  )


def _advance_persisted_financials_stage(
  *,
  conn,
  draft_id: str,
  business_facts: Dict[str, Any],
  intake_context: Dict[str, Any],
  conversation_messages: List[Dict[str, str]],
  shared_context: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]] = None,
  acknowledgement: str = "",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
  persisted_financials, persisted_year1, persisted_marketing = _persist_and_reload_financials_progress(
    conn=conn,
    draft_id=draft_id,
    business_facts=business_facts,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    marketing_model_json=marketing_model_json or {},
  )
  next_stage = _next_financials_stage(persisted_financials)
  if next_stage:
    next_context = dict(intake_context or {})
    next_context["financials_json"] = persisted_financials
    next_shared = dict(shared_context or {})
    next_shared["financials"] = persisted_financials
    if isinstance(persisted_marketing, dict) and persisted_marketing:
      next_shared["marketing"] = persisted_marketing
    next_context["shared_context"] = next_shared
    next_context["financials_active_stage"] = next_stage
    next_turn = {
      "assistant_message": _build_financials_stage_message(
        stage_name=next_stage,
        intake_context=next_context,
        shared_context=next_shared,
        financials_json=persisted_financials,
        financials_year1_json=persisted_year1,
        business_facts=business_facts,
        conn=conn,
      ),
      "finalize_ready": False,
    }
    if str(acknowledgement or "").strip():
      next_text = str(next_turn.get("assistant_message") or "").strip()
      next_turn["assistant_message"] = (
        f"{str(acknowledgement).strip()}\n\n{next_text}".strip()
        if next_text
        else str(acknowledgement).strip()
      )
    next_financials = _sync_pending_revenue_adjustment_state(
      persisted_financials,
      persisted_year1,
      next_turn.get("revenue_adjudication") if isinstance(next_turn, dict) else None,
    )
    return next_turn, next_financials, persisted_marketing

  completion_turn = _build_financials_completion_turn(acknowledgement=acknowledgement)
  next_financials = _sync_pending_revenue_adjustment_state(
    persisted_financials,
    persisted_year1,
    completion_turn.get("revenue_adjudication") if isinstance(completion_turn, dict) else None,
  )
  return completion_turn, next_financials, persisted_marketing


def _build_financials_revenue_intro_message(
  *,
  intake_context: Dict[str, Any],
  shared_context: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> str:
  revenue_math_line = str((intake_context or {}).get("revenue_math_line") or "").strip()
  operating_model = dict((shared_context or {}).get("operating_model") or {})
  price = _format_currency(operating_model.get("unit_price"))
  utilization = _format_percent(operating_model.get("utilization_rate"))
  weekly_capacity = _safe_float(operating_model.get("units_per_week_capacity"))
  periods = _safe_float(operating_model.get("operating_periods_per_year"))
  annual_revenue = _format_currency((financials_year1_json or {}).get("company_revenue_total_year1"))
  capacity_text = f"{weekly_capacity:g} sessions per week" if weekly_capacity is not None else "the modeled weekly capacity"
  periods_text = f"{periods:g} operating periods" if periods is not None else "the modeled operating periods"
  lead = "Year 1 revenue:"
  if revenue_math_line:
    lead = f"{lead}\n\n{revenue_math_line}"
  summary = (
    f"This planning baseline assumes you run at about {utilization} utilization of {capacity_text}, "
    f"at an average price of {price}, across {periods_text}, which produces about {annual_revenue} in Year-1 revenue."
  )
  return (
    f"{lead}\n\n"
    f"{summary} "
    "We will use this as the baseline for the rest of financial planning."
  ).strip()


def _financials_baseline_estimators() -> Tuple[Any, Any]:
  try:
    from financials_consultant import (  # type: ignore
      estimate_cogs_percent_from_context as _estimate_cogs_percent_from_context,
      estimate_marketing_baseline_from_context as _estimate_marketing_baseline_from_context,
    )
  except Exception:
    from client_intake_and_finmo.financials_consultant import (  # type: ignore
      estimate_cogs_percent_from_context as _estimate_cogs_percent_from_context,
      estimate_marketing_baseline_from_context as _estimate_marketing_baseline_from_context,
    )
  return _estimate_cogs_percent_from_context, _estimate_marketing_baseline_from_context


def _build_financials_stage_message(
  *,
  stage_name: str,
  intake_context: Dict[str, Any],
  shared_context: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  business_facts: Dict[str, Any],
  conn,
) -> str:
  stage = str(stage_name or "").strip()
  estimate_cogs_percent_from_context, estimate_marketing_baseline_from_context = _financials_baseline_estimators()
  if stage == "revenue_intro":
    return _build_financials_revenue_intro_message(
      intake_context=intake_context,
      shared_context=shared_context,
      financials_year1_json=financials_year1_json,
    )
  if stage == "cogs":
    baseline = _resolve_cogs_baseline_or_raise(
      conn=conn,
      ops_json=dict((shared_context or {}).get("operating_model") or {}),
      shared_context=shared_context,
      estimate_cogs_percent_from_context=estimate_cogs_percent_from_context,
      financials_year1_json=financials_year1_json,
    )
    return _build_cogs_baseline_message(baseline)
  if stage == "current_payroll":
    return _build_payroll_baseline_message(_compute_payroll_baseline(shared_context=shared_context))
  if stage == "marketing":
    marketing_model = _resolve_marketing_model_or_raise(
      conn=conn,
      ops_json=dict((shared_context or {}).get("operating_model") or {}),
      market_json=dict((shared_context or {}).get("target_market") or {}),
      people_json=dict((shared_context or {}).get("people_capability") or {}),
      financials_year1_json=financials_year1_json,
      business_facts=business_facts,
      existing_marketing_model_json=dict((shared_context or {}).get("marketing") or {}),
      estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
    )
    return _build_marketing_baseline_message(marketing_model)
  if stage == "monthly_rent_expense":
    return _build_monthly_rent_message(shared_context=shared_context)
  if stage == "future_rent_expected":
    return _build_future_rent_message(
      shared_context=shared_context,
      monthly_rent_expense=(financials_json or {}).get("monthly_rent_expense"),
    )
  if stage == "owner_compensation":
    return (
      "As of last month, how much did you pay yourself from the business in wages, draws, or other owner compensation? "
      "A dollar amount is fine."
    )
  if stage == "other_operating_expense":
    return (
      "As of last month, about how much did you spend on other regular business bills besides payroll, marketing, and rent, "
      "like utilities, software, insurance, accounting, phone, internet, and general overhead?"
    )
  if stage == "current_num_employees":
    return (
      "As of last month, how many people were on payroll for the business, not counting outside contractors? "
      "A whole number is fine."
    )
  if stage == "current_capex":
    return (
      "As of last month, did you make any larger one-time purchases for the business, like equipment, devices, furniture, build-out, or vehicles? "
      "If yes, what was the rough total?"
    )
  if stage == "initial_assets":
    return (
      "As of last month, what is your best rough estimate of the total value of the main equipment, devices, furniture, and fixtures already in the business?"
    )
  if stage == "initial_lease":
    return _build_initial_lease_message()
  if stage == "initial_equity":
    return (
      "As of last month, what is your best rough estimate of the total money or value put into the business so far by you or any investors?"
    )
  if stage == "total_debt_outstanding":
    return (
      "As of last month, what was the total amount the business still owed on loans, lines of credit, or business credit cards?"
    )
  if stage == "other_monthly_debt_payments":
    return (
      "As of last month, besides regular rent and credit card minimums already baked into other expenses, what other loan or debt payments did the business make each month?"
    )
  if stage == "annual_interest_payment":
    return (
      "Of your debt payments, what is your best estimate of the annual interest cost, meaning the finance charge rather than principal paydown?"
    )
  if stage == "annual_principal_payment":
    return (
      "What is your best estimate of the annual principal you expect to repay on the business debt, separate from interest?"
    )
  if stage == "cash_on_hand":
    return "As of last month, about how much cash did the business have on hand in its bank accounts and any cash on site?"
  if stage == "ar_balance":
    return (
      "As of last month, about how much money did customers still owe you for completed work, like unpaid invoices or payment plans?"
    )
  if stage == "ap_balance":
    return (
      "As of last month, about how much did the business still owe in regular operating bills, like unpaid supplier invoices, utilities, or business credit card balances related to operations?"
    )
  if stage == "inventory_balance":
    return (
      "As of last month, about how much inventory did you have on hand, like products or supplies kept in stock to use or sell?"
    )
  if stage == "cash_strategy":
    return _build_cash_strategy_message()
  return "What number should I record for this financial item?"


def _financials_stage_default_patch(
  *,
  stage_name: str,
  shared_context: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  business_facts: Dict[str, Any],
  conn,
) -> Optional[Dict[str, Any]]:
  stage = str(stage_name or "").strip()
  estimate_cogs_percent_from_context, estimate_marketing_baseline_from_context = _financials_baseline_estimators()
  if stage == "revenue_intro":
    baseline_revenue = _safe_float((financials_year1_json or {}).get("company_revenue_total_year1"))
    if baseline_revenue is None:
      return None
    return {
      "current_revenue": float(baseline_revenue),
    }
  if stage == "cogs":
    baseline = _resolve_cogs_baseline_or_raise(
      conn=conn,
      ops_json=dict((shared_context or {}).get("operating_model") or {}),
      shared_context=shared_context,
      estimate_cogs_percent_from_context=estimate_cogs_percent_from_context,
      financials_year1_json=financials_year1_json,
    )
    revenue_year1 = _safe_float((financials_year1_json or {}).get("company_revenue_total_year1")) or 0.0
    total = float(baseline.get("baseline_cogs") or 0.0)
    return {
      "current_cogs": total,
      "cogs_total_year1": total,
      "cogs_percent_of_revenue": (total / revenue_year1) if revenue_year1 > 0 else float(baseline.get("baseline_cogs_percent") or 0.0),
      "baseline_cogs": total,
      "baseline_cogs_percent": float(baseline.get("baseline_cogs_percent") or 0.0),
      "cogs_adjustment": 0.0,
      "cogs_basis_naics": baseline.get("cogs_basis_naics"),
      "cogs_basis_years_used": baseline.get("cogs_basis_years_used") or [],
      "cogs_basis_rationale": str(baseline.get("cogs_basis_rationale") or "").strip(),
    }
  if stage == "current_payroll":
    baseline = _compute_payroll_baseline(shared_context=shared_context)
    total = float(baseline.get("baseline_payroll_year1") or 0.0)
    return {
      "current_payroll": total,
      "payroll_total_year1": total,
      "baseline_payroll_year1": total,
      "payroll_adjustment": 0.0,
      "payroll_basis_people_roles": baseline.get("payroll_basis_people_roles") or [],
    }
  if stage == "marketing":
    marketing_model = _resolve_marketing_model_or_raise(
      conn=conn,
      ops_json=dict((shared_context or {}).get("operating_model") or {}),
      market_json=dict((shared_context or {}).get("target_market") or {}),
      people_json=dict((shared_context or {}).get("people_capability") or {}),
      financials_year1_json=financials_year1_json,
      business_facts=business_facts,
      existing_marketing_model_json=dict((shared_context or {}).get("marketing") or {}),
      estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
    )
    total = float(marketing_model.get("baseline_marketing") or 0.0)
    percent = float(marketing_model.get("baseline_marketing_percent") or 0.0)
    return {
      "marketing_total_year1": total,
      "marketing_percent_of_revenue": percent,
      "baseline_marketing": total,
      "baseline_marketing_percent": percent,
      "marketing_adjustment": 0.0,
    }
  return None


def _build_financials_stage_acknowledgement(
  *,
  stage_name: str,
  financials_json: Dict[str, Any],
) -> str:
  stage = str(stage_name or "").strip()
  if stage == "cogs":
    total = _format_currency((financials_json or {}).get("cogs_total_year1"))
    percent = _format_percent((financials_json or {}).get("cogs_percent_of_revenue"))
    return f"Got it. IÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¾ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ll use Year-1 direct costs of {total} ({percent} of revenue)."
  if stage == "current_payroll":
    return f"Got it. IÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¾ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ll use Year-1 payroll of {_format_currency((financials_json or {}).get('payroll_total_year1'))}."
  if stage == "marketing":
    total = _format_currency((financials_json or {}).get("marketing_total_year1"))
    percent = _format_percent((financials_json or {}).get("marketing_percent_of_revenue"))
    return f"Got it. IÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¾ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ll use a Year-1 marketing budget of {total} ({percent} of revenue)."
  if stage == "revenue_intro":
    return "Understood. WeÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¾ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ll use the current Year-1 revenue model as the baseline and move into the rest of financials."
  if stage == "cash_strategy":
    return _build_cash_strategy_acknowledgement((financials_json or {}).get("cash_strategy"))
  if stage == "current_num_employees":
    return f"Got it. IÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¾ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ll use {int(round(float((financials_json or {}).get('current_num_employees') or 0)))} for current employee count."
  scalar_field = stage if stage in _GENERIC_FINANCIALS_FIELD_LABELS else ""
  if scalar_field:
    value = (financials_json or {}).get(stage)
    if stage == "future_rent_expected":
      return "Got it. IÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¾ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ll treat future dedicated space as part of the model." if bool(value) else "Got it. IÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¾ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ll treat future dedicated space as not expected for now."
    return _build_financials_scalar_stage_acknowledgement(stage, float(value or 0.0))
  return "Got it."


def _build_financials_live_turn(
  *,
  conn,
  intake_context: Dict[str, Any],
  conversation_messages: List[Dict[str, str]],
  shared_context: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  guardrail_triggered: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
  del guardrail_triggered
  next_financials = _ensure_financials_stage_defaults(dict(financials_json or {}))
  next_stage = _next_financials_stage(next_financials)
  if not next_stage:
    return _build_financials_completion_turn(), next_financials

  next_context = dict(intake_context or {})
  next_context["financials_json"] = next_financials
  next_shared = dict(shared_context or {})
  next_shared["financials"] = next_financials
  next_shared["financials_controller"] = _build_financials_controller_context(next_stage)
  next_context["shared_context"] = next_shared
  if next_stage:
    next_context["financials_active_stage"] = next_stage
  else:
    next_context.pop("financials_active_stage", None)

  turn = {
    "assistant_message": _build_financials_stage_message(
      stage_name=next_stage,
      intake_context=next_context,
      shared_context=next_shared,
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
      business_facts=dict((shared_context or {}).get("business_facts") or {}),
      conn=conn,
    ),
    "finalize_ready": False,
  }
  return turn, next_financials


def _build_cogs_baseline_message(cogs_baseline: Dict[str, Any]) -> str:
  return (
    f"A reasonable Year-1 COGS baseline is about "
    f"{_format_percent(cogs_baseline.get('baseline_cogs_percent'))} of revenue, which puts your projected Year-1 direct costs around "
    f"{_format_currency(cogs_baseline.get('baseline_cogs'))}.\n\n"
    "Does that broadly match how your business works, or should we adjust it because your direct costs are materially different?"
  )


def _build_payroll_baseline_signature(shared_context: Dict[str, Any]) -> str:
  people_context = dict((shared_context or {}).get("people_capability") or {})
  people_rows: List[Dict[str, Any]] = []
  for person in people_context.get("people") or []:
    if not isinstance(person, dict):
      continue
    people_rows.append(
      {
        "source": "person",
        "full_name": str(person.get("full_name") or "").strip(),
        "role_title": str(person.get("role_title") or "").strip(),
        "annual_wage": person.get("annual_wage"),
      }
    )
  role_rows: List[Dict[str, Any]] = []
  for role in people_context.get("inferred_roles") or []:
    if not isinstance(role, dict):
      continue
    role_rows.append(
      {
        "source": "inferred_role",
        "role_title": str(role.get("role_title") or "").strip(),
        "annual_wage": role.get("annual_wage"),
        "months_until_hire": role.get("months_until_hire"),
      }
    )
  try:
    return json.dumps({"people": people_rows, "roles": role_rows}, sort_keys=True, ensure_ascii=False)
  except Exception:
    return ""


def _compute_payroll_baseline(
  *,
  shared_context: Dict[str, Any],
) -> Dict[str, Any]:
  people_context = dict((shared_context or {}).get("people_capability") or {})
  operating_model = dict((shared_context or {}).get("operating_model") or {})
  basis_roles: List[Dict[str, Any]] = []
  baseline_total = 0.0

  for person in people_context.get("people") or []:
    if not isinstance(person, dict):
      continue
    try:
      annual_wage = float(person.get("annual_wage") or 0.0)
    except Exception:
      annual_wage = 0.0
    annual_wage = max(0.0, annual_wage)
    baseline_total += annual_wage
    basis_roles.append(
      {
        "source": "person",
        "full_name": str(person.get("full_name") or "").strip(),
        "role_title": str(person.get("role_title") or "").strip(),
        "annual_wage": annual_wage,
        "months_counted_year1": 12,
        "year1_payroll_amount": annual_wage,
      }
    )

  for role in people_context.get("inferred_roles") or []:
    if not isinstance(role, dict):
      continue
    try:
      annual_wage = float(role.get("annual_wage") or 0.0)
    except Exception:
      annual_wage = 0.0
    annual_wage = max(0.0, annual_wage)
    raw_months = role.get("months_until_hire")
    try:
      months_until_hire = int(float(raw_months))
    except Exception:
      months_until_hire = 0
    months_until_hire = max(0, min(12, months_until_hire))
    months_counted = max(0, 12 - months_until_hire)
    year1_amount = float(annual_wage * (months_counted / 12.0))
    baseline_total += year1_amount
    basis_roles.append(
      {
        "source": "inferred_role",
        "role_title": str(role.get("role_title") or "").strip(),
        "annual_wage": annual_wage,
        "months_until_hire": months_until_hire,
        "months_counted_year1": months_counted,
        "year1_payroll_amount": year1_amount,
      }
    )

  return {
    "baseline_payroll_year1": float(baseline_total),
    "payroll_adjustment": 0.0,
    "payroll_total_year1": float(baseline_total),
    "payroll_basis_people_roles": basis_roles,
    "business_stage": str(operating_model.get("business_stage") or "").strip().lower(),
  }


def _build_payroll_baseline_message(payroll_baseline: Dict[str, Any]) -> str:
  roles = payroll_baseline.get("payroll_basis_people_roles") or []
  role_count = len(roles)
  role_phrase = "role" if role_count == 1 else "roles"
  existing_count = 0
  inferred_count = 0
  for role in roles:
    if not isinstance(role, dict):
      continue
    source = str(role.get("source") or "").strip().lower()
    if source == "person":
      existing_count += 1
    elif source == "inferred_role":
      inferred_count += 1
  stage = str(payroll_baseline.get("business_stage") or "").strip().lower()
  clarification = (
    "This payroll estimate reflects the staffing plan already captured, including current team members and any additional roles discussed earlier where applicable."
  )
  if stage == "pre-revenue":
    clarification = (
      "This payroll estimate reflects the team needed to launch and operate in Year 1, including any planned hires from the staffing plan."
    )
  elif stage == "early-stage":
    clarification = (
      "This payroll estimate reflects the current staffing plan plus near-term additions as the business ramps and workload increases."
    )
  elif stage == "operating":
    clarification = (
      "This payroll estimate reflects the existing team plus any incremental additions from the staffing plan; it is not replacing the team already in place."
    )
  composition = ""
  if existing_count and inferred_count:
    composition = (
      f" That includes {existing_count} current team {'role' if existing_count == 1 else 'roles'} "
      f"and {inferred_count} additional planned {'role' if inferred_count == 1 else 'roles'}."
    )
  elif existing_count:
    composition = f" That includes {existing_count} current team {'role' if existing_count == 1 else 'roles'}."
  elif inferred_count:
    composition = (
      f" That includes {inferred_count} planned {'role' if inferred_count == 1 else 'roles'} from the staffing plan."
    )
  return (
    f"Based on the people plan already defined, a reasonable Year-1 payroll baseline is about "
    f"{_format_currency(payroll_baseline.get('baseline_payroll_year1'))} across {role_count} {role_phrase} in the plan.\n\n"
    f"{clarification}{composition}\n\n"
    "Does that broadly match your Year-1 payroll expectation, or should we adjust it because your actual payroll setup is materially different?"
  )


def _extract_zip_codes(text: Any) -> List[str]:
  import re

  raw = str(text or "").strip()
  if not raw:
    return []
  seen = set()
  out: List[str] = []
  for match in re.findall(r"\b(\d{5})(?:-\d{4})?\b", raw):
    code = str(match).strip()
    if code and code not in seen:
      seen.add(code)
      out.append(code)
  return out


def _is_us_country(value: Any) -> bool:
  raw = " ".join(str(value or "").strip().lower().split())
  if not raw:
    return True
  return raw in {"us", "u.s.", "usa", "u.s.a.", "united states", "united states of america"}


def _marketing_dependency_signature(
  *,
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  business_facts: Dict[str, Any],
) -> str:
  signature_payload = {
    "business": {
      "address_zip": str((business_facts or {}).get("address_zip") or "").strip(),
      "address_state": str((business_facts or {}).get("address_state") or "").strip(),
      "address_country": str((business_facts or {}).get("address_country") or "").strip(),
    },
    "ops": {
      "consumer_type": str((ops_json or {}).get("consumer_type") or "").strip(),
      "business_type": str((ops_json or {}).get("business_type") or "").strip(),
      "business_naics_6": str((ops_json or {}).get("business_naics_6") or "").strip(),
      "unit_name": str((ops_json or {}).get("unit_name") or "").strip(),
      "unit_description": str((ops_json or {}).get("unit_description") or "").strip(),
      "unit_cadence": str((ops_json or {}).get("unit_cadence") or "").strip(),
      "unit_price": (ops_json or {}).get("unit_price"),
      "units_per_week_capacity": (ops_json or {}).get("units_per_week_capacity"),
      "units_per_period_capacity": (ops_json or {}).get("units_per_period_capacity"),
      "operating_periods_per_year": (ops_json or {}).get("operating_periods_per_year"),
      "utilization_rate": (ops_json or {}).get("utilization_rate"),
      "shipping_method": str((ops_json or {}).get("shipping_method") or "").strip(),
      "sales_modality": str((ops_json or {}).get("sales_modality") or "").strip(),
      "geographic_scope": str((ops_json or {}).get("geographic_scope") or "").strip(),
      "geographic_coverage": str((ops_json or {}).get("geographic_coverage") or "").strip(),
      "countries": (ops_json or {}).get("countries") or [],
      "competitive_advantage": str((ops_json or {}).get("competitive_advantage") or "").strip(),
      "capacity_driver": str((ops_json or {}).get("capacity_driver") or "").strip(),
      "primary_growth_lever": str((ops_json or {}).get("primary_growth_lever") or "").strip(),
    },
    "market": {
      "consumer_type": str((market_json or {}).get("consumer_type") or "").strip(),
      "selections": (market_json or {}).get("selections") or [],
      "b2b_naics_6": (market_json or {}).get("b2b_naics_6") or [],
      "b2b_size_bands": (market_json or {}).get("b2b_size_bands") or [],
      "b2b_age_bands": (market_json or {}).get("b2b_age_bands") or [],
      "marketing_plan_summary": str((market_json or {}).get("marketing_plan_summary") or "").strip(),
      "target_market_summary": str((market_json or {}).get("target_market_summary") or "").strip(),
    },
    "year1": {
      "company_revenue_total_year1": (financials_year1_json or {}).get("company_revenue_total_year1"),
      "lobs": (financials_year1_json or {}).get("lobs") or [],
    },
  }
  return json.dumps(signature_payload, sort_keys=True, ensure_ascii=False)


def _marketing_explicit_zips(
  *,
  ops_json: Dict[str, Any],
  business_facts: Dict[str, Any],
) -> List[str]:
  coverage = str((ops_json or {}).get("geographic_coverage") or "").strip()
  zips = _extract_zip_codes(coverage)
  address_zip = str((business_facts or {}).get("address_zip") or "").strip()
  if address_zip and address_zip not in zips:
    zips.append(address_zip)
  return zips


def _fetch_crosswalk_rows_for_zips(conn, zips: List[str]) -> List[Dict[str, Any]]:
  if not zips:
    return []
  placeholders = ",".join(["%s"] * len(zips))
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      f"""
      SELECT zcta, state_fips, county_fips, geoid, zpop_pct, zhu_pct
      FROM zip_county_crosswalk
      WHERE zcta IN ({placeholders})
      """,
      tuple(zips),
    )
    return cur.fetchall() or []
  finally:
    cur.close()


def _fetch_crosswalk_rows_for_counties(conn, county_geoids: List[str]) -> List[Dict[str, Any]]:
  if not county_geoids:
    return []
  placeholders = ",".join(["%s"] * len(county_geoids))
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      f"""
      SELECT zcta, state_fips, county_fips, geoid, zpop_pct, zhu_pct
      FROM zip_county_crosswalk
      WHERE geoid IN ({placeholders})
      """,
      tuple(county_geoids),
    )
    return cur.fetchall() or []
  finally:
    cur.close()


def _acs_zip_column_sets(conn) -> Tuple[set[str], set[str]]:
  cache = getattr(_acs_zip_column_sets, "_cache", None)
  if isinstance(cache, tuple) and len(cache) == 2:
    return cache  # type: ignore[return-value]
  cur = conn.cursor()
  try:
    cur.execute("SHOW COLUMNS FROM acs_zip_2022_part1")
    part1 = {str(row[0]) for row in (cur.fetchall() or [])}
    cur.execute("SHOW COLUMNS FROM acs_zip_2022_part2")
    part2 = {str(row[0]) for row in (cur.fetchall() or [])}
  finally:
    cur.close()
  result = (part1, part2)
  setattr(_acs_zip_column_sets, "_cache", result)
  return result


def _weighted_acs_total_for_code(
  *,
  conn,
  table_name: str,
  acs_code: str,
  zips: List[str],
  county_geoids: List[str],
  state_fips: List[str],
  weight_field: Optional[str],
) -> float:
  code = str(acs_code or "").strip()
  if not code:
    return 0.0
  cur = conn.cursor()
  try:
    if county_geoids:
      placeholders = ",".join(["%s"] * len(county_geoids))
      if weight_field:
        cur.execute(
          f"""
          SELECT COALESCE(SUM(COALESCE(a.`{code}`, 0) * COALESCE(x.`{weight_field}`, 0) / 100.0), 0)
          FROM {table_name} a
          JOIN zip_county_crosswalk x
            ON x.zcta = a.zcta
          WHERE x.geoid IN ({placeholders})
          """,
          tuple(county_geoids),
        )
      else:
        cur.execute(
          f"""
          SELECT COALESCE(SUM(COALESCE(a.`{code}`, 0)), 0)
          FROM {table_name} a
          JOIN zip_county_crosswalk x
            ON x.zcta = a.zcta
          WHERE x.geoid IN ({placeholders})
          """,
          tuple(county_geoids),
        )
    elif state_fips:
      placeholders = ",".join(["%s"] * len(state_fips))
      if weight_field:
        cur.execute(
          f"""
          SELECT COALESCE(SUM(COALESCE(a.`{code}`, 0) * COALESCE(x.`{weight_field}`, 0) / 100.0), 0)
          FROM {table_name} a
          JOIN zip_county_crosswalk x
            ON x.zcta = a.zcta
          WHERE x.state_fips IN ({placeholders})
          """,
          tuple(state_fips),
        )
      else:
        cur.execute(
          f"""
          SELECT COALESCE(SUM(COALESCE(a.`{code}`, 0)), 0)
          FROM {table_name} a
          JOIN zip_county_crosswalk x
            ON x.zcta = a.zcta
          WHERE x.state_fips IN ({placeholders})
          """,
          tuple(state_fips),
        )
    elif zips:
      placeholders = ",".join(["%s"] * len(zips))
      if weight_field:
        cur.execute(
          f"""
          SELECT COALESCE(SUM(COALESCE(a.`{code}`, 0) * COALESCE(x.`{weight_field}`, 0) / 100.0), 0)
          FROM {table_name} a
          JOIN zip_county_crosswalk x
            ON x.zcta = a.zcta
          WHERE a.zcta IN ({placeholders})
          """,
          tuple(zips),
        )
      else:
        cur.execute(
          f"""
          SELECT COALESCE(SUM(COALESCE(a.`{code}`, 0)), 0)
          FROM {table_name} a
          WHERE a.zcta IN ({placeholders})
          """,
          tuple(zips),
        )
    else:
      cur.execute(
        f"""
        SELECT COALESCE(SUM(COALESCE(a.`{code}`, 0)), 0)
        FROM {table_name} a
        """
      )
    row = cur.fetchone()
  finally:
    cur.close()
  try:
    return float((row or [0])[0] or 0.0)
  except Exception:
    return 0.0


def _marketing_segment_weight_field(segment: str) -> Optional[str]:
  seg = str(segment or "").strip()
  if seg in {"Income", "Household Structure", "Housing Economics"}:
    return "zhu_pct"
  if seg:
    return "zpop_pct"
  return None


def _all_cbp_state_fips(conn) -> List[str]:
  cur = conn.cursor()
  try:
    cur.execute("SELECT DISTINCT state_fips FROM cbp_2022_raw ORDER BY state_fips ASC")
    return [str(row[0]).strip() for row in (cur.fetchall() or []) if str(row[0]).strip()]
  finally:
    cur.close()


def _state_fips_from_text(conn, text: str) -> List[str]:
  clean_text = str(text or "").strip().lower()
  if not clean_text:
    return []
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute("SELECT DISTINCT state_fips, state_name FROM cbp_2022_raw")
    rows = cur.fetchall() or []
  finally:
    cur.close()
  resolved: List[str] = []
  seen = set()
  for row in rows:
    state_name = str((row or {}).get("state_name") or "").strip().lower()
    state_fips = str((row or {}).get("state_fips") or "").strip()
    if not state_name or not state_fips:
      continue
    pattern = re.compile(rf"(?<![a-z]){re.escape(state_name)}(?![a-z])")
    if pattern.search(clean_text) and state_fips not in seen:
      seen.add(state_fips)
      resolved.append(state_fips)
  return sorted(resolved)


def _marketing_normalized_geography(
  *,
  conn,
  ops_json: Dict[str, Any],
  business_facts: Dict[str, Any],
) -> Dict[str, Any]:
  scope = str((ops_json or {}).get("geographic_scope") or "").strip().lower() or "local"
  coverage = str((ops_json or {}).get("geographic_coverage") or "").strip()
  address_zip = str((business_facts or {}).get("address_zip") or "").strip()
  address_state = str((business_facts or {}).get("address_state") or "").strip()

  explicit_zips = _extract_zip_codes(coverage)
  anchor_zip = address_zip if len(address_zip) == 5 and address_zip.isdigit() else ""
  crosswalk_seed_zips: List[str] = list(explicit_zips)
  if anchor_zip and anchor_zip not in crosswalk_seed_zips:
    crosswalk_seed_zips.append(anchor_zip)
  crosswalk_rows = _fetch_crosswalk_rows_for_zips(conn, crosswalk_seed_zips) if crosswalk_seed_zips else []

  county_geoids = sorted(
    {
      str(row.get("geoid") or "").strip()
      for row in crosswalk_rows
      if isinstance(row, dict) and str(row.get("geoid") or "").strip()
    }
  )
  state_fips = sorted(
    {
      str(row.get("state_fips") or "").strip()
      for row in crosswalk_rows
      if isinstance(row, dict) and str(row.get("state_fips") or "").strip()
    }
  )

  if scope == "national":
    state_fips = _all_cbp_state_fips(conn)
    county_geoids = []
  else:
    text_states = _state_fips_from_text(conn, coverage)
    if scope == "regional":
      for state in text_states:
        if state not in state_fips:
          state_fips.append(state)
      state_fips = sorted(set(state_fips))
    if scope == "local":
      # Local market sizing should anchor to county even if the client only confirmed
      # a city/metro phrase. Address ZIP gives us the county aggregation basis.
      if not county_geoids and anchor_zip:
        anchor_rows = _fetch_crosswalk_rows_for_zips(conn, [anchor_zip])
        county_geoids = sorted(
          {
            str(row.get("geoid") or "").strip()
            for row in anchor_rows
            if isinstance(row, dict) and str(row.get("geoid") or "").strip()
          }
        )
        for row in anchor_rows:
          state = str(row.get("state_fips") or "").strip()
          if state and state not in state_fips:
            state_fips.append(state)
        state_fips = sorted(set(state_fips))

  if not state_fips and address_state:
    cur = conn.cursor()
    try:
      cur.execute(
        """
        SELECT DISTINCT state_fips
        FROM cbp_2022_raw
        WHERE LOWER(state_name) = LOWER(%s)
        ORDER BY state_fips ASC
        """,
        (address_state,),
      )
      state_fips = [str(row[0]).strip() for row in (cur.fetchall() or []) if str(row[0]).strip()]
    finally:
      cur.close()

  return {
    "scope": scope,
    "coverage_summary": coverage,
    "anchor_zip": anchor_zip,
    "explicit_zip_basis": explicit_zips,
    "county_geoids": county_geoids,
    "state_fips": state_fips,
  }


def _build_b2c_marketing_basis(
  *,
  conn,
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  business_facts: Dict[str, Any],
  normalized_geography: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  selections = market_json.get("selections")
  if not isinstance(selections, list) or not selections:
    return None

  geo = dict(normalized_geography or {})
  zips = list(geo.get("explicit_zip_basis") or [])
  county_geoids = list(geo.get("county_geoids") or [])
  state_fips = list(geo.get("state_fips") or [])
  part1_cols, part2_cols = _acs_zip_column_sets(conn)
  segment_basis: List[Dict[str, Any]] = []

  for selection in selections:
    if not isinstance(selection, dict):
      continue
    segment = str(selection.get("segment") or "").strip()
    codes = selection.get("acs_codes")
    if not segment or not isinstance(codes, list):
      continue
    clean_codes: List[str] = []
    seen_codes = set()
    for code in codes:
      acs_code = str(code or "").strip()
      if not acs_code or acs_code in seen_codes:
        continue
      if acs_code not in part1_cols and acs_code not in part2_cols:
        continue
      seen_codes.add(acs_code)
      clean_codes.append(acs_code)
    if not clean_codes:
      continue
    weight_field = _marketing_segment_weight_field(segment)
    total = 0.0
    for acs_code in clean_codes:
      table_name = "acs_zip_2022_part1" if acs_code in part1_cols else "acs_zip_2022_part2"
      total += _weighted_acs_total_for_code(
        conn=conn,
        table_name=table_name,
        acs_code=acs_code,
        zips=zips,
        county_geoids=county_geoids,
        state_fips=state_fips,
        weight_field=weight_field if (zips or county_geoids or state_fips) else None,
      )
    segment_basis.append(
      {
        "segment": segment,
        "acs_codes": clean_codes,
        "basis_count": float(max(0.0, total)),
        "weight_basis": "housing" if weight_field == "zhu_pct" else "population",
      }
    )

  if not segment_basis:
    return None

  return {
    "basis_type": "b2c",
    "scope": str((geo.get("scope") or (ops_json or {}).get("geographic_scope") or "").strip().lower() or "local"),
    "anchor_zip": str(geo.get("anchor_zip") or "").strip(),
    "zip_basis": zips,
    "county_geoids": county_geoids,
    "state_fips": state_fips,
    "coverage_summary": str(geo.get("coverage_summary") or "").strip(),
    "segment_basis_counts": segment_basis,
  }


def _state_fips_from_basis(
  *,
  conn,
  ops_json: Dict[str, Any],
  business_facts: Dict[str, Any],
) -> List[str]:
  normalized = _marketing_normalized_geography(conn=conn, ops_json=ops_json, business_facts=business_facts)
  return list(normalized.get("state_fips") or [])


_BDS_SIZE_BUCKET_MAP = {
  "1-4": "a) 1 to 4",
  "5-9": "b) 5 to 9",
  "10-19": "c) 10 to 19",
  "20-99": "d) 20 to 99",
  "100-499": "e) 100 to 499",
  "500-999": "f) 500 to 999",
  "1000-2499": "g) 1000 to 2499",
  "2500-4999": "h) 2500 to 4999",
  "5000-9999": "i) 5000 to 9999",
  "10000+": "j) 10000+",
}

_BDS_AGE_BUCKET_MAP = {
  "0": "a) 0",
  "1": "b) 1",
  "2": "c) 2",
  "3": "d) 3",
  "4": "e) 4",
  "5": "f) 5",
  "6-10": "g) 6 to 10",
  "11-15": "h) 11 to 15",
  "16-20": "i) 16 to 20",
  "21-25": "j) 21 to 25",
  "26+": "k) 26+",
}


def _cbp_exact_hits_for_codes(
  *,
  conn,
  naics_codes: List[str],
  state_fips: List[str],
) -> List[Dict[str, Any]]:
  if not naics_codes or not state_fips:
    return []
  code_placeholders = ",".join(["%s"] * len(naics_codes))
  state_placeholders = ",".join(["%s"] * len(state_fips))
  params: List[Any] = [*naics_codes, *state_fips]
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      f"""
      SELECT naics, SUM(estab) AS estab_total, SUM(emp) AS emp_total
      FROM cbp_2022_raw
      WHERE naics IN ({code_placeholders})
        AND state_fips IN ({state_placeholders})
      GROUP BY naics
      """,
      tuple(params),
    )
    return cur.fetchall() or []
  finally:
    cur.close()


def _cbp_parent_hit(
  *,
  conn,
  prefix: str,
  state_fips: List[str],
) -> Optional[Dict[str, Any]]:
  if not prefix or not state_fips:
    return None
  state_placeholders = ",".join(["%s"] * len(state_fips))
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      f"""
      SELECT naics, SUM(estab) AS estab_total, SUM(emp) AS emp_total
      FROM cbp_2022_raw
      WHERE naics = %s
        AND state_fips IN ({state_placeholders})
      GROUP BY naics
      """,
      tuple([prefix, *state_fips]),
    )
    row = cur.fetchone()
  finally:
    cur.close()
  return row if isinstance(row, dict) else None


def _latest_bds_year(conn, *, table_name: str) -> Optional[int]:
  cur = conn.cursor()
  try:
    cur.execute(f"SELECT MAX(year) FROM {table_name}")
    row = cur.fetchone()
  finally:
    cur.close()
  try:
    return int((row or [None])[0])
  except Exception:
    return None


def _aggregate_bds_signal(
  *,
  conn,
  table_name: str,
  bucket_column: str,
  selected_bucket_labels: List[str],
  naics4_prefixes: List[int],
  exclude_bucket: Optional[str] = None,
) -> Dict[str, Any]:
  if not naics4_prefixes:
    return {
      "latest_year": None,
      "selected_buckets": [],
      "selected_firms": 0.0,
      "total_firms": 0.0,
      "selected_share": 0.0,
    }
  latest_year = _latest_bds_year(conn, table_name=table_name)
  if latest_year is None:
    return {
      "latest_year": None,
      "selected_buckets": [],
      "selected_firms": 0.0,
      "total_firms": 0.0,
      "selected_share": 0.0,
    }
  placeholders = ",".join(["%s"] * len(naics4_prefixes))
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      f"""
      SELECT `{bucket_column}` AS bucket_label, SUM(firms) AS firms_total
      FROM {table_name}
      WHERE year = %s
        AND vcnaics4 IN ({placeholders})
      GROUP BY `{bucket_column}`
      """,
      tuple([latest_year, *naics4_prefixes]),
    )
    rows = cur.fetchall() or []
  finally:
    cur.close()
  total = 0.0
  selected = 0.0
  cleaned_selected = {str(label).strip() for label in selected_bucket_labels if str(label).strip()}
  for row in rows:
    label = str(row.get("bucket_label") or "").strip()
    try:
      firms_total = float(row.get("firms_total") or 0.0)
    except Exception:
      firms_total = 0.0
    if exclude_bucket and label == exclude_bucket:
      continue
    total += firms_total
    if label in cleaned_selected:
      selected += firms_total
  share = (selected / total) if total > 0 else 0.0
  return {
    "latest_year": latest_year,
    "selected_buckets": sorted(cleaned_selected),
    "selected_firms": float(max(0.0, selected)),
    "total_firms": float(max(0.0, total)),
    "selected_share": float(max(0.0, share)),
  }


def _build_b2b_marketing_basis(
  *,
  conn,
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  business_facts: Dict[str, Any],
  normalized_geography: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  selected_codes = []
  seen_codes = set()
  for value in market_json.get("b2b_naics_6") or []:
    code = str(value or "").strip()
    if len(code) == 6 and code.isdigit() and code not in seen_codes:
      seen_codes.add(code)
      selected_codes.append(code)
  if not selected_codes:
    return None

  state_fips = list((normalized_geography or {}).get("state_fips") or [])
  if not state_fips:
    return None

  cbp_match_level = 6
  cbp_source_codes: List[str] = []
  cbp_establishments_total = 0.0
  cbp_employee_total = 0.0

  exact_hits = _cbp_exact_hits_for_codes(conn=conn, naics_codes=selected_codes, state_fips=state_fips)
  if exact_hits:
    cbp_source_codes = [str(row.get("naics") or "").strip() for row in exact_hits if str(row.get("naics") or "").strip()]
    for row in exact_hits:
      try:
        cbp_establishments_total += float(row.get("estab_total") or 0.0)
      except Exception:
        pass
      try:
        cbp_employee_total += float(row.get("emp_total") or 0.0)
      except Exception:
        pass
  else:
    for level in (5, 4, 3, 2):
      prefixes = {code[:level] for code in selected_codes if len(code) >= level}
      if len(prefixes) != 1:
        continue
      prefix = next(iter(prefixes))
      parent_hit = _cbp_parent_hit(conn=conn, prefix=prefix, state_fips=state_fips)
      if not parent_hit:
        continue
      cbp_match_level = level
      cbp_source_codes = [prefix]
      try:
        cbp_establishments_total = float(parent_hit.get("estab_total") or 0.0)
      except Exception:
        cbp_establishments_total = 0.0
      try:
        cbp_employee_total = float(parent_hit.get("emp_total") or 0.0)
      except Exception:
        cbp_employee_total = 0.0
      break

  naics4_prefixes = sorted({int(code[:4]) for code in selected_codes})
  selected_size_labels = [_BDS_SIZE_BUCKET_MAP.get(str(band).strip()) for band in (market_json.get("b2b_size_bands") or [])]
  selected_size_labels = [label for label in selected_size_labels if label]
  selected_age_labels = [_BDS_AGE_BUCKET_MAP.get(str(band).strip()) for band in (market_json.get("b2b_age_bands") or [])]
  selected_age_labels = [label for label in selected_age_labels if label]

  size_signal = _aggregate_bds_signal(
    conn=conn,
    table_name="bds_firm_size",
    bucket_column="firm_size_bucket",
    selected_bucket_labels=selected_size_labels,
    naics4_prefixes=naics4_prefixes,
  )
  age_signal = _aggregate_bds_signal(
    conn=conn,
    table_name="bds_firm_age",
    bucket_column="firm_age_bucket",
    selected_bucket_labels=selected_age_labels,
    naics4_prefixes=naics4_prefixes,
    exclude_bucket="l) Left Censored",
  )

  return {
    "basis_type": "b2b",
    "scope": str(((normalized_geography or {}).get("scope") or (ops_json or {}).get("geographic_scope") or "").strip().lower() or "local"),
    "anchor_zip": str((normalized_geography or {}).get("anchor_zip") or "").strip(),
    "county_geoids": (normalized_geography or {}).get("county_geoids") or [],
    "state_fips": state_fips,
    "coverage_summary": str((normalized_geography or {}).get("coverage_summary") or "").strip(),
    "cbp_basis": {
      "match_level": cbp_match_level,
      "source_codes": cbp_source_codes,
      "establishments_total": float(max(0.0, cbp_establishments_total)),
      "employees_total": float(max(0.0, cbp_employee_total)),
    },
    "size_signal": size_signal,
    "age_signal": age_signal,
    "selected_naics_6": selected_codes,
    "selected_naics_4": [str(value) for value in naics4_prefixes],
  }


def _required_units_year1(financials_year1_json: Dict[str, Any]) -> float:
  total_units = 0.0
  lobs = (financials_year1_json or {}).get("lobs")
  if not isinstance(lobs, list):
    return 0.0
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    products = lob.get("products")
    if not isinstance(products, list):
      continue
    for product in products:
      if not isinstance(product, dict):
        continue
      try:
        avg_units = float(product.get("avg_units_per_period_year1") or product.get("avg_units_per_week_year1") or 0.0)
      except Exception:
        avg_units = 0.0
      try:
        periods = float(product.get("operating_periods_per_year") or product.get("operating_weeks_per_year") or 0.0)
      except Exception:
        periods = 0.0
      total_units += max(0.0, avg_units) * max(0.0, periods)
  return float(max(0.0, total_units))


def _build_marketing_estimate_context(
  *,
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  business_facts: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
) -> Dict[str, Any]:
  marketing_basis = dict(marketing_model_json or {})
  b2b_basis = dict(marketing_basis.get("b2b_basis_counts") or {})
  cbp_basis = dict(b2b_basis.get("cbp_basis") or {})
  market_basis_type = str(marketing_basis.get("market_basis_type") or "").strip().lower()
  normalized_geography = marketing_basis.get("geography_basis") or {}
  scope = str((normalized_geography or {}).get("scope") or "").strip().lower()
  return {
    "business": {
      "name": business_facts.get("name"),
      "address_zip": business_facts.get("address_zip"),
      "address_state": business_facts.get("address_state"),
      "address_country": business_facts.get("address_country"),
    },
    "ops": {
      "consumer_type": ops_json.get("consumer_type"),
      "business_type": ops_json.get("business_type"),
      "business_naics_6": ops_json.get("business_naics_6"),
      "unit_name": ops_json.get("unit_name"),
      "unit_description": ops_json.get("unit_description"),
      "unit_cadence": ops_json.get("unit_cadence"),
      "unit_price": ops_json.get("unit_price"),
      "units_per_week_capacity": ops_json.get("units_per_week_capacity"),
      "units_per_period_capacity": ops_json.get("units_per_period_capacity"),
      "operating_periods_per_year": ops_json.get("operating_periods_per_year"),
      "utilization_rate": ops_json.get("utilization_rate"),
      "shipping_method": ops_json.get("shipping_method"),
      "sales_modality": ops_json.get("sales_modality"),
      "geographic_scope": ops_json.get("geographic_scope"),
      "geographic_coverage": ops_json.get("geographic_coverage"),
      "capacity_driver": ops_json.get("capacity_driver"),
      "primary_growth_lever": ops_json.get("primary_growth_lever"),
      "competitive_advantage": ops_json.get("competitive_advantage"),
    },
    "market": {
      "consumer_type": market_json.get("consumer_type"),
      "target_market_summary": market_json.get("target_market_summary"),
      "marketing_plan_summary": market_json.get("marketing_plan_summary"),
      "b2b_industry_terms": market_json.get("b2b_industry_terms") or [],
      "b2b_naics_6": market_json.get("b2b_naics_6") or [],
      "b2b_size_bands": market_json.get("b2b_size_bands") or [],
      "b2b_age_bands": market_json.get("b2b_age_bands") or [],
      "selections": market_json.get("selections") or [],
    },
    "people": {
      "key_people_summary": people_json.get("key_people_summary"),
      "people": people_json.get("people") or [],
      "inferred_roles": people_json.get("inferred_roles") or [],
    },
    "financials_year1_json": financials_year1_json or {},
    "normalized_geography": normalized_geography,
    "market_measurement_guidance": {
      "combined_reachable_market_reporting_only": True,
      "combined_reachable_market_note": (
        "reachable_market is a high-level planning/reporting field only. "
        "Do not treat it as a literal additive TAM count when B2C and B2B are both present."
      ),
      "b2c_measurement_unit": "people/customers",
      "b2b_measurement_unit": "firms",
      "mixed_case_note": (
        "In mixed models, keep B2C people reach and B2B firm reach conceptually separate. "
        "Do not use neat or symmetrical splits unless the observed data truly supports them."
      ) if market_basis_type == "mixed" else "",
      "scope_note": (
        "Regional and national B2B reach must stay grounded in the observed state-level CBP firm universe."
        if scope in {"regional", "national"} else
        "Local B2B reach must still stay grounded in the observed state-level CBP firm universe while respecting the tighter local footprint."
      ),
      "b2b_observed_establishments_total": cbp_basis.get("establishments_total"),
      "b2b_observed_employees_total": cbp_basis.get("employees_total"),
      "b2b_cbp_match_level": cbp_basis.get("match_level"),
    },
    "marketing_model_basis": {
      "version": marketing_basis.get("version"),
      "market_basis_type": marketing_basis.get("market_basis_type"),
      "geography_basis": normalized_geography,
      "b2c_basis_counts": marketing_basis.get("b2c_basis_counts") or [],
      "b2b_basis_counts": b2b_basis,
      "required_revenue_year1": marketing_basis.get("required_revenue_year1"),
      "required_units_year1": marketing_basis.get("required_units_year1"),
      "reachable_market": marketing_basis.get("reachable_market"),
      "reachable_market_b2c": marketing_basis.get("reachable_market_b2c"),
      "reachable_market_b2b": marketing_basis.get("reachable_market_b2b"),
    },
  }


def _marketing_intensity_from_percent(percent: float) -> str:
  value = float(max(0.0, percent))
  if value >= 0.12:
    return "very_high"
  if value >= 0.08:
    return "high"
  if value >= 0.04:
    return "medium"
  return "low"


def _fallback_marketing_estimate(
  *,
  base_model: Dict[str, Any],
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  business_facts: Dict[str, Any],
  fallback_reason: str,
) -> Optional[Dict[str, Any]]:
  revenue_year1 = float(base_model.get("required_revenue_year1") or 0.0)
  if revenue_year1 <= 0:
    return None

  market_basis_type = str(base_model.get("market_basis_type") or "").strip().lower() or "consumer"
  stage = str((ops_json or {}).get("business_stage") or "").strip().lower()
  scope = str(((base_model.get("geography_basis") or {}).get("scope") or (ops_json or {}).get("geographic_scope") or "")).strip().lower()
  sales_modality = str((ops_json or {}).get("sales_modality") or "").strip().lower()
  shipping_method = str((ops_json or {}).get("shipping_method") or "").strip().lower()
  capacity_driver = str((ops_json or {}).get("capacity_driver") or "").strip().lower()
  unit_cadence = str((ops_json or {}).get("unit_cadence") or "").strip().lower()
  unit_price = _safe_float((ops_json or {}).get("unit_price")) or 0.0
  required_units_year1 = float(base_model.get("required_units_year1") or 0.0)

  baseline_percent = 0.0

  if stage == "operating":
    baseline_percent += 0.035
  elif stage == "pre-revenue":
    baseline_percent += 0.06
  else:
    baseline_percent += 0.045

  if market_basis_type == "consumer":
    baseline_percent += 0.025
  elif market_basis_type == "mixed":
    baseline_percent += 0.02
  else:
    baseline_percent += 0.012

  if "online" in sales_modality or "ecommerce" in sales_modality:
    baseline_percent += 0.018
  elif "hybrid" in sales_modality:
    baseline_percent += 0.01
  elif "in-person" in shipping_method or "shop" in shipping_method or "facility" in shipping_method:
    baseline_percent += 0.004

  if scope == "regional":
    baseline_percent += 0.008
  elif scope == "national":
    baseline_percent += 0.015
  elif scope == "local":
    baseline_percent += 0.002

  if unit_price >= 1000:
    baseline_percent -= 0.012
  elif unit_price >= 500:
    baseline_percent -= 0.006
  elif unit_price <= 75:
    baseline_percent += 0.015
  elif unit_price <= 200:
    baseline_percent += 0.008

  if capacity_driver == "labor":
    baseline_percent -= 0.004

  marketing_plan_text = " ".join(
    [
      str((market_json or {}).get("marketing_plan_summary") or ""),
      str((market_json or {}).get("target_market_summary") or ""),
      str((ops_json or {}).get("primary_growth_lever") or ""),
      str((ops_json or {}).get("competitive_advantage") or ""),
    ]
  ).lower()
  channel_terms = (
    "google",
    "search",
    "maps",
    "instagram",
    "facebook",
    "linkedin",
    "referral",
    "partnership",
    "delivery",
    "ads",
    "seo",
  )
  baseline_percent += min(0.015, 0.003 * sum(1 for term in channel_terms if term in marketing_plan_text))
  baseline_percent = float(min(0.18, max(0.025, baseline_percent)))

  if unit_cadence == "weekly":
    repeat_units_per_entity = 10.0 if market_basis_type == "b2b" else 6.0
  elif unit_cadence == "monthly":
    repeat_units_per_entity = 6.0 if market_basis_type == "b2b" else 2.5
  elif unit_cadence == "annual":
    repeat_units_per_entity = 1.2
  else:
    repeat_units_per_entity = 3.0 if market_basis_type == "b2b" else 2.0

  expected_entities_year1 = max(1.0, required_units_year1 / max(1.0, repeat_units_per_entity)) if required_units_year1 > 0 else 1.0

  positive_b2c_counts = [
    float(item.get("basis_count") or 0.0)
    for item in (base_model.get("b2c_basis_counts") or [])
    if isinstance(item, dict) and float(item.get("basis_count") or 0.0) > 0
  ]
  b2c_anchor = max(positive_b2c_counts) if positive_b2c_counts else 0.0
  b2c_ratio = 0.001 if scope == "national" else 0.003 if scope == "regional" else 0.008
  reachable_market_b2c = 0.0
  if market_basis_type in {"consumer", "mixed"}:
    if b2c_anchor > 0:
      reachable_market_b2c = max(expected_entities_year1 * 4.0, b2c_anchor * b2c_ratio)
    else:
      reachable_market_b2c = expected_entities_year1 * 6.0

  cbp_basis = dict((base_model.get("b2b_basis_counts") or {}).get("cbp_basis") or {})
  observed_establishments = float(cbp_basis.get("establishments_total") or 0.0)
  b2b_ratio = 0.02 if scope == "national" else 0.01 if scope == "regional" else 0.004
  reachable_market_b2b = 0.0
  if market_basis_type in {"b2b", "mixed"}:
    if observed_establishments > 0:
      reachable_market_b2b = max(expected_entities_year1 * 1.5, observed_establishments * b2b_ratio)
      reachable_market_b2b = min(observed_establishments, reachable_market_b2b)
    else:
      reachable_market_b2b = expected_entities_year1 * 3.0

  if market_basis_type == "consumer":
    combined_reachable_market = max(reachable_market_b2c, expected_entities_year1 * 4.0)
  elif market_basis_type == "b2b":
    combined_reachable_market = max(reachable_market_b2b, expected_entities_year1 * 2.0)
  else:
    combined_reachable_market = max(reachable_market_b2c, reachable_market_b2b, expected_entities_year1 * 5.0)

  capture_rate_year1 = 0.0
  if combined_reachable_market > 0:
    capture_rate_year1 = min(1.0, max(0.0, expected_entities_year1 / combined_reachable_market))

  business_label = str((ops_json or {}).get("business_type") or business_facts.get("business_name") or "this business").strip() or "this business"
  rationale = (
    f"Deterministic fallback used because the GPT marketing estimator did not return an accepted result "
    f"({fallback_reason}). The baseline was anchored to the saved operating context for {business_label}, "
    f"including market type={market_basis_type}, scope={scope or 'unspecified'}, sales modality={sales_modality or shipping_method or 'unspecified'}, "
    f"unit price={_format_currency(unit_price)}, and Year-1 revenue={_format_currency(revenue_year1)}. "
    f"The result is a conservative planning baseline intended to keep intake moving without treating broad observed market ceilings as directly reachable demand."
  )

  return {
    "reachable_market": float(max(1.0, combined_reachable_market)),
    "reachable_market_b2c": float(max(0.0, reachable_market_b2c)),
    "reachable_market_b2b": float(max(0.0, reachable_market_b2b)),
    "capture_rate_year1": float(capture_rate_year1),
    "expected_customers_or_clients_year1": float(max(1.0, expected_entities_year1)),
    "expected_units_year1": float(max(0.0, required_units_year1)),
    "marketing_intensity": _marketing_intensity_from_percent(baseline_percent),
    "baseline_marketing_percent": float(baseline_percent),
    "brief_rationale": rationale,
    "estimation_method": "deterministic_fallback",
    "estimation_status": "fallback_used",
    "estimation_warning": f"GPT marketing baseline unavailable; fallback used ({fallback_reason}).",
  }


def _compute_marketing_model_json(
  *,
  conn,
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  business_facts: Dict[str, Any],
  existing_marketing_model_json: Dict[str, Any],
  estimate_marketing_baseline_from_context,
) -> Dict[str, Any]:
  signature = _marketing_dependency_signature(
    ops_json=ops_json,
    market_json=market_json,
    financials_year1_json=financials_year1_json,
    business_facts=business_facts,
  )
  base_model: Dict[str, Any] = {
    "version": 3,
    "signature": signature,
    "market_basis_type": str((market_json or {}).get("consumer_type") or (ops_json or {}).get("consumer_type") or "").strip().lower() or "consumer",
    "geography_basis": {},
    "b2c_basis_counts": [],
    "b2b_basis_counts": {},
    "required_revenue_year1": float((financials_year1_json or {}).get("company_revenue_total_year1") or 0.0),
    "required_units_year1": _required_units_year1(financials_year1_json or {}),
    "reachable_market_b2c": None,
    "reachable_market_b2b": None,
    "missing_dependencies": [],
    "ready": False,
    "estimation_method": "",
    "estimation_status": "",
    "estimation_warning": "",
  }
  normalized_geography = _marketing_normalized_geography(
    conn=conn,
    ops_json=ops_json,
    business_facts=business_facts,
  )
  base_model["geography_basis"] = normalized_geography

  if not _is_us_country((business_facts or {}).get("address_country")):
    base_model["missing_dependencies"] = ["us_only_quantified_market"]
    return base_model

  market_basis_type = str(base_model.get("market_basis_type") or "").strip().lower()
  b2c_basis = None
  b2b_basis = None
  if market_basis_type in {"consumer", "mixed"}:
    b2c_basis = _build_b2c_marketing_basis(
      conn=conn,
      ops_json=ops_json,
      market_json=market_json,
      business_facts=business_facts,
      normalized_geography=normalized_geography,
    )
    if isinstance(b2c_basis, dict):
      base_model["b2c_basis_counts"] = b2c_basis.get("segment_basis_counts") or []
      base_model["geography_basis"]["zip_basis"] = b2c_basis.get("zip_basis") or []
      base_model["geography_basis"]["county_geoids"] = b2c_basis.get("county_geoids") or []
      base_model["geography_basis"]["state_fips"] = b2c_basis.get("state_fips") or base_model["geography_basis"].get("state_fips") or []
      base_model["geography_basis"]["scope"] = b2c_basis.get("scope")
  if market_basis_type in {"b2b", "mixed"}:
    b2b_basis = _build_b2b_marketing_basis(
      conn=conn,
      ops_json=ops_json,
      market_json=market_json,
      business_facts=business_facts,
      normalized_geography=normalized_geography,
    )
    if isinstance(b2b_basis, dict):
      base_model["b2b_basis_counts"] = {
        "cbp_basis": b2b_basis.get("cbp_basis") or {},
        "size_signal": b2b_basis.get("size_signal") or {},
        "age_signal": b2b_basis.get("age_signal") or {},
        "state_fips": b2b_basis.get("state_fips") or [],
        "selected_naics_6": b2b_basis.get("selected_naics_6") or [],
        "selected_naics_4": b2b_basis.get("selected_naics_4") or [],
      }
      base_model["geography_basis"]["state_fips"] = b2b_basis.get("state_fips") or []
      base_model["geography_basis"]["scope"] = b2b_basis.get("scope")

  has_b2c = bool(base_model.get("b2c_basis_counts"))
  has_b2b = bool((base_model.get("b2b_basis_counts") or {}).get("cbp_basis") or (base_model.get("b2b_basis_counts") or {}).get("size_signal") or (base_model.get("b2b_basis_counts") or {}).get("age_signal"))
  if market_basis_type == "consumer" and not has_b2c:
    base_model["missing_dependencies"] = ["b2c_market_basis"]
    fallback = _fallback_marketing_estimate(
      base_model=base_model,
      ops_json=ops_json,
      market_json=market_json,
      business_facts=business_facts,
      fallback_reason="missing_b2c_market_basis",
    )
    if isinstance(fallback, dict):
      baseline_percent = float(fallback.get("baseline_marketing_percent") or 0.0)
      base_model.update(
        {
          **fallback,
          "baseline_marketing_percent": baseline_percent,
          "baseline_marketing": float(base_model["required_revenue_year1"] * baseline_percent),
          "marketing_basis_summary": str(fallback.get("brief_rationale") or "").strip(),
          "ready": True,
        }
      )
    return base_model
  if market_basis_type == "b2b" and not has_b2b:
    base_model["missing_dependencies"] = ["b2b_market_basis"]
    fallback = _fallback_marketing_estimate(
      base_model=base_model,
      ops_json=ops_json,
      market_json=market_json,
      business_facts=business_facts,
      fallback_reason="missing_b2b_market_basis",
    )
    if isinstance(fallback, dict):
      baseline_percent = float(fallback.get("baseline_marketing_percent") or 0.0)
      base_model.update(
        {
          **fallback,
          "baseline_marketing_percent": baseline_percent,
          "baseline_marketing": float(base_model["required_revenue_year1"] * baseline_percent),
          "marketing_basis_summary": str(fallback.get("brief_rationale") or "").strip(),
          "ready": True,
        }
      )
    return base_model
  if market_basis_type == "mixed" and not (has_b2c or has_b2b):
    base_model["missing_dependencies"] = ["market_basis"]
    fallback = _fallback_marketing_estimate(
      base_model=base_model,
      ops_json=ops_json,
      market_json=market_json,
      business_facts=business_facts,
      fallback_reason="missing_market_basis",
    )
    if isinstance(fallback, dict):
      baseline_percent = float(fallback.get("baseline_marketing_percent") or 0.0)
      base_model.update(
        {
          **fallback,
          "baseline_marketing_percent": baseline_percent,
          "baseline_marketing": float(base_model["required_revenue_year1"] * baseline_percent),
          "marketing_basis_summary": str(fallback.get("brief_rationale") or "").strip(),
          "ready": True,
        }
      )
    return base_model
  if base_model["required_revenue_year1"] <= 0:
    base_model["missing_dependencies"] = ["required_revenue_year1"]
    return base_model

  existing_model = dict(existing_marketing_model_json or {})
  if (
    int(existing_model.get("version") or 0) == int(base_model.get("version") or 0)
    and str(existing_model.get("signature") or "").strip() == signature
    and existing_model.get("ready") is True
    and existing_model.get("baseline_marketing_percent") is not None
  ):
    for key in (
      "reachable_market",
      "reachable_market_b2c",
      "reachable_market_b2b",
      "capture_rate_year1",
      "expected_customers_or_clients_year1",
      "expected_units_year1",
      "marketing_intensity",
      "baseline_marketing_percent",
      "baseline_marketing",
      "marketing_basis_summary",
      "demand_supports_required_units",
      "estimation_method",
      "estimation_status",
      "estimation_warning",
    ):
      if key in existing_model:
        base_model[key] = existing_model.get(key)
    base_model["ready"] = True
    return base_model

  estimated = estimate_marketing_baseline_from_context(
    marketing_estimate_context=_build_marketing_estimate_context(
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_year1_json=financials_year1_json,
      business_facts=business_facts,
      marketing_model_json=base_model,
    )
  )
  if not isinstance(estimated, dict):
    estimated = _fallback_marketing_estimate(
      base_model=base_model,
      ops_json=ops_json,
      market_json=market_json,
      business_facts=business_facts,
      fallback_reason="estimator_returned_no_accepted_result",
    )
  if not isinstance(estimated, dict):
    return base_model

  baseline_percent = float(estimated.get("baseline_marketing_percent") or 0.0)
  baseline_amount = float(base_model["required_revenue_year1"] * baseline_percent)
  expected_units_year1 = float(estimated.get("expected_units_year1") or 0.0)
  reachable_market = float(estimated.get("reachable_market") or 0.0)
  reachable_market_b2c = _safe_float(estimated.get("reachable_market_b2c"))
  reachable_market_b2b = _safe_float(estimated.get("reachable_market_b2b"))
  if market_basis_type == "consumer":
    reachable_market_b2c = reachable_market
    reachable_market_b2b = 0.0
  elif market_basis_type == "b2b":
    reachable_market_b2c = 0.0
    reachable_market_b2b = reachable_market
  else:
    if reachable_market_b2c is None:
      reachable_market_b2c = 0.0
    if reachable_market_b2b is None:
      reachable_market_b2b = 0.0
  base_model.update(
    {
      "reachable_market": reachable_market,
      "reachable_market_b2c": max(0.0, reachable_market_b2c),
      "reachable_market_b2b": max(0.0, reachable_market_b2b),
      "capture_rate_year1": float(estimated.get("capture_rate_year1") or 0.0),
      "expected_customers_or_clients_year1": float(estimated.get("expected_customers_or_clients_year1") or 0.0),
      "expected_units_year1": expected_units_year1,
      "marketing_intensity": str(estimated.get("marketing_intensity") or "").strip() or "medium",
      "baseline_marketing_percent": baseline_percent,
      "baseline_marketing": baseline_amount,
      "marketing_basis_summary": str(estimated.get("brief_rationale") or "").strip(),
      "demand_supports_required_units": expected_units_year1 >= float(base_model.get("required_units_year1") or 0.0),
      "estimation_method": str(estimated.get("estimation_method") or "gpt_estimate").strip() or "gpt_estimate",
      "estimation_status": str(estimated.get("estimation_status") or "gpt_estimate_ready").strip() or "gpt_estimate_ready",
      "estimation_warning": str(estimated.get("estimation_warning") or "").strip(),
      "ready": True,
    }
  )
  return base_model


def _resolve_marketing_model_or_raise(
  *,
  conn,
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  business_facts: Dict[str, Any],
  existing_marketing_model_json: Dict[str, Any],
  estimate_marketing_baseline_from_context,
) -> Dict[str, Any]:
  marketing_model = _compute_marketing_model_json(
    conn=conn,
    ops_json=ops_json,
    market_json=market_json,
    people_json=people_json,
    financials_year1_json=financials_year1_json,
    business_facts=business_facts,
    existing_marketing_model_json=existing_marketing_model_json,
    estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
  )
  if isinstance(marketing_model, dict) and marketing_model.get("ready") is True:
    return marketing_model
  raise RuntimeError("Unable to resolve a Year-1 marketing baseline from the current market and operating context.")


def _build_marketing_baseline_message(marketing_baseline: Dict[str, Any]) -> str:
  return (
    f"A reasonable Year-1 marketing baseline is about "
    f"{_format_percent(marketing_baseline.get('baseline_marketing_percent'))} of revenue, which puts your projected Year-1 marketing spend around "
    f"{_format_currency(marketing_baseline.get('baseline_marketing'))}.\n\n"
    "Does that broadly match what it will take to attract and convert customers in Year 1, or should we adjust it because your marketing spend will be materially different?"
  )


def _normalize_marketing_reply_to_fields(
  *,
  reply: Dict[str, Any],
  baseline: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  baseline_amount = float(baseline.get("baseline_marketing") or 0.0)
  revenue_year1 = float(baseline.get("required_revenue_year1") or 0.0)
  baseline_percent = float(baseline.get("baseline_marketing_percent") or 0.0)
  intent_type = str(reply.get("intent_type") or "").strip()

  if intent_type == "accept_baseline":
    total = baseline_amount
  elif intent_type == "set_total":
    try:
      total = float(reply.get("marketing_total_year1"))
    except Exception:
      return None
  elif intent_type == "set_percent":
    try:
      percent = float(reply.get("marketing_percent_of_revenue"))
    except Exception:
      return None
    total = float(revenue_year1 * percent)
  elif intent_type == "set_adjustment":
    try:
      adjustment = float(reply.get("marketing_adjustment"))
    except Exception:
      return None
    total = baseline_amount + adjustment
  else:
    return None

  total = max(0.0, float(total))
  adjustment = float(total - baseline_amount)
  percent_total = float(total / revenue_year1) if revenue_year1 > 0 else baseline_percent
  return {
    "baseline_marketing_percent": baseline_percent,
    "baseline_marketing": baseline_amount,
    "marketing_adjustment": adjustment,
    "marketing_total_year1": total,
    "marketing_percent_of_revenue": percent_total,
  }


def _sync_marketing_field_family(
  *,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
) -> Dict[str, Any]:
  next_financials = dict(financials_json or {})
  revenue = _safe_float((financials_year1_json or {}).get("company_revenue_total_year1"))
  baseline_percent = _safe_float(next_financials.get("baseline_marketing_percent"))
  baseline_amount = _safe_float(next_financials.get("baseline_marketing"))
  if baseline_percent is None:
    baseline_percent = _safe_float((marketing_model_json or {}).get("baseline_marketing_percent"))
  if baseline_amount is None:
    baseline_amount = _safe_float((marketing_model_json or {}).get("baseline_marketing"))
  if baseline_percent is None and baseline_amount is not None and revenue and revenue > 0:
    baseline_percent = baseline_amount / revenue
  if baseline_amount is None and baseline_percent is not None and revenue is not None:
    baseline_amount = revenue * baseline_percent

  total = _safe_float(next_financials.get("marketing_total_year1"))
  percent_total = _safe_float(next_financials.get("marketing_percent_of_revenue"))
  if total is None and percent_total is not None and revenue is not None:
    total = revenue * percent_total
  if percent_total is None and total is not None and revenue and revenue > 0:
    percent_total = total / revenue

  if total is None:
    return next_financials

  next_financials["marketing_total_year1"] = total
  if percent_total is not None:
    next_financials["marketing_percent_of_revenue"] = percent_total
  if baseline_percent is not None:
    next_financials["baseline_marketing_percent"] = baseline_percent
  if baseline_amount is not None:
    next_financials["baseline_marketing"] = baseline_amount
  if baseline_amount is not None:
    next_financials["marketing_adjustment"] = total - baseline_amount
  return next_financials

def _build_initial_lease_message() -> str:
  return (
    "Now let's capture any leased or rented equipment or space beyond your main rent. "
    "What monthly amount should we use for any leased equipment, vehicles, servers, or additional space you do not own? "
    "If there is none, use 0."
  )


def _financials_business_stage(shared_context: Dict[str, Any]) -> str:
  operating_model = (shared_context or {}).get("operating_model") or {}
  if not isinstance(operating_model, dict):
    return ""
  return str(operating_model.get("business_stage") or "").strip().lower()


def _build_monthly_rent_message(*, shared_context: Dict[str, Any]) -> str:
  stage = _financials_business_stage(shared_context)
  if stage == "operating":
    return (
      "What do you pay each month for the space you use to run the business, like an office, storefront, clinic, kitchen, warehouse, or similar dedicated space?"
    )
  return (
    "What do you pay each month for any dedicated business space, like an office, storefront, clinic, kitchen, warehouse, or similar facility? "
    "If you are not paying for separate space yet but already know what it will cost when you open, use that amount."
  )


def _build_future_rent_message(
  *,
  shared_context: Dict[str, Any],
  monthly_rent_expense: Any,
) -> str:
  try:
    current_rent = float(monthly_rent_expense)
  except Exception:
    current_rent = 0.0
  stage = _financials_business_stage(shared_context)
  if current_rent > 0:
    if stage == "operating":
      return "Looking ahead, do you expect paid dedicated business space to stay part of how this business operates?"
    return "Looking ahead, do you expect paid dedicated business space to stay part of this business once it is up and running?"
  if stage == "operating":
    return "Looking ahead, do you expect this business to need paid dedicated space later, or do you expect it to stay remote or space-light?"
  return "Looking ahead, do you expect this business to need paid dedicated space later, or do you expect it to stay without separate business space?"










def _financials_field_resolved(financials_json: Dict[str, Any], field: str) -> bool:
  if not isinstance(financials_json, dict):
    return False
  if field not in financials_json:
    return False
  if str(field or "").strip() == "cash_strategy":
    return _cash_strategy_option(financials_json.get(field)) is not None
  return financials_json.get(field) is not None


def _ensure_financials_stage_defaults(financials_json: Dict[str, Any]) -> Dict[str, Any]:
  next_financials = dict(financials_json or {})
  try:
    debt = float(next_financials.get("total_debt_outstanding"))
  except Exception:
    debt = None
  if debt is not None and debt <= 0:
    next_financials.setdefault("other_monthly_debt_payments", 0)
    next_financials.setdefault("annual_interest_payment", 0)
    next_financials.setdefault("annual_principal_payment", 0)
  return next_financials


_FINANCIALS_STAGE_ORDER: Tuple[str, ...] = (
  "revenue_intro",
  "cogs",
  "current_payroll",
  "marketing",
  "monthly_rent_expense",
  "future_rent_expected",
  "owner_compensation",
  "other_operating_expense",
  "current_num_employees",
  "current_capex",
  "initial_assets",
  "initial_lease",
  "initial_equity",
  "total_debt_outstanding",
  "other_monthly_debt_payments",
  "annual_interest_payment",
  "annual_principal_payment",
  "cash_on_hand",
  "ar_balance",
  "ap_balance",
  "inventory_balance",
  "cash_strategy",
)


_FINANCIALS_STAGE_SPECS: Dict[str, Dict[str, Any]] = {
  "revenue_intro": {
    "patch_targets": ("current_revenue",),
    "completion_fields": ("_financials_revenue_intro_done",),
    "confirmable_baseline": True,
    "clarifier": "What Year-1 revenue number should I use as the starting financial baseline instead?",
  },
  "cogs": {
    "patch_targets": ("current_cogs", "cogs_total_year1", "cogs_percent_of_revenue"),
    "completion_fields": ("current_cogs",),
    "confirmable_baseline": True,
    "clarifier": "What Year-1 direct-cost amount or percent should I use instead?",
  },
  "current_payroll": {
    "patch_targets": ("current_payroll", "payroll_total_year1"),
    "completion_fields": ("current_payroll",),
    "confirmable_baseline": True,
    "clarifier": "What Year-1 payroll should I use instead?",
  },
  "marketing": {
    "patch_targets": ("marketing_total_year1", "marketing_percent_of_revenue"),
    "completion_fields": ("marketing_total_year1",),
    "confirmable_baseline": True,
    "clarifier": "What Year-1 marketing budget or percent should I use instead?",
  },
  "monthly_rent_expense": {
    "patch_targets": ("monthly_rent_expense",),
    "completion_fields": ("monthly_rent_expense",),
    "confirmable_baseline": False,
    "clarifier": "What monthly rent amount should I record?",
  },
  "future_rent_expected": {
    "patch_targets": ("future_rent_expected",),
    "completion_fields": ("future_rent_expected",),
    "confirmable_baseline": False,
    "clarifier": "Should I record future dedicated business space as expected, yes or no?",
  },
  "owner_compensation": {
    "patch_targets": ("owner_compensation",),
    "completion_fields": ("owner_compensation",),
    "confirmable_baseline": False,
    "clarifier": "What annual owner compensation should I record?",
  },
  "other_operating_expense": {
    "patch_targets": ("other_operating_expense",),
    "completion_fields": ("other_operating_expense",),
    "confirmable_baseline": False,
    "clarifier": "What monthly other operating expense should I record?",
  },
  "current_num_employees": {
    "patch_targets": ("current_num_employees",),
    "completion_fields": ("current_num_employees",),
    "confirmable_baseline": False,
    "clarifier": "What whole-number employee count should I record?",
  },
  "current_capex": {
    "patch_targets": ("current_capex",),
    "completion_fields": ("current_capex",),
    "confirmable_baseline": False,
    "clarifier": "What current capital spending amount should I record?",
  },
  "initial_assets": {
    "patch_targets": ("initial_assets",),
    "completion_fields": ("initial_assets",),
    "confirmable_baseline": False,
    "clarifier": "What initial asset value should I record?",
  },
  "initial_lease": {
    "patch_targets": ("initial_lease",),
    "completion_fields": ("initial_lease",),
    "confirmable_baseline": False,
    "clarifier": "What monthly lease amount should I record for leased equipment or space beyond main rent?",
  },
  "initial_equity": {
    "patch_targets": ("initial_equity",),
    "completion_fields": ("initial_equity",),
    "confirmable_baseline": False,
    "clarifier": "What initial equity amount should I record?",
  },
  "total_debt_outstanding": {
    "patch_targets": ("total_debt_outstanding",),
    "completion_fields": ("total_debt_outstanding",),
    "confirmable_baseline": False,
    "clarifier": "What total debt outstanding amount should I record?",
  },
  "other_monthly_debt_payments": {
    "patch_targets": ("other_monthly_debt_payments",),
    "completion_fields": ("other_monthly_debt_payments",),
    "confirmable_baseline": False,
    "clarifier": "What other monthly debt-payment amount should I record?",
  },
  "annual_interest_payment": {
    "patch_targets": ("annual_interest_payment",),
    "completion_fields": ("annual_interest_payment",),
    "confirmable_baseline": False,
    "clarifier": "What annual interest amount should I record?",
  },
  "annual_principal_payment": {
    "patch_targets": ("annual_principal_payment",),
    "completion_fields": ("annual_principal_payment",),
    "confirmable_baseline": False,
    "clarifier": "What annual principal repayment amount should I record?",
  },
  "cash_on_hand": {
    "patch_targets": ("cash_on_hand",),
    "completion_fields": ("cash_on_hand",),
    "confirmable_baseline": False,
    "clarifier": "What cash-on-hand amount should I record?",
  },
  "ar_balance": {
    "patch_targets": ("ar_balance",),
    "completion_fields": ("ar_balance",),
    "confirmable_baseline": False,
    "clarifier": "What accounts receivable balance should I record?",
  },
  "ap_balance": {
    "patch_targets": ("ap_balance",),
    "completion_fields": ("ap_balance",),
    "confirmable_baseline": False,
    "clarifier": "What accounts payable balance should I record?",
  },
  "inventory_balance": {
    "patch_targets": ("inventory_balance",),
    "completion_fields": ("inventory_balance",),
    "confirmable_baseline": False,
    "clarifier": "What inventory balance should I record?",
  },
  "cash_strategy": {
    "patch_targets": ("cash_strategy",),
    "completion_fields": ("cash_strategy",),
    "confirmable_baseline": False,
    "clarifier": "Which cash approach should I record: Preserve cash, Shareholder return, or Balanced?",
  },
}

_CASH_STRATEGY_OPTIONS: Tuple[Dict[str, str], ...] = (
  {
    "value": "preserve_cash",
    "label": "Preserve cash",
    "description": "Keep a thicker cash cushion and stay more conservative about putting excess cash back to work.",
  },
  {
    "value": "shareholder_return",
    "label": "Shareholder return",
    "description": "Treat excess cash as something that can be taken out of the business rather than just left to build up.",
  },
  {
    "value": "balanced",
    "label": "Balanced",
    "description": "Balance the required cash cushion, debt discipline, and measured capital returns.",
  },
)

_CASH_STRATEGY_INITIAL_PROMPT_MARKER = "One last financial planning question before I wrap this section up:"
_CASH_STRATEGY_CLARIFY_PROMPT_MARKER = "Just to make sure I record this correctly,"
_CASH_STRATEGY_FORCED_CHOICE_PROMPT_MARKER = "To lock this in cleanly, please pick the one option below that fits best right now:"


def _cash_strategy_option(value: Any) -> Optional[Dict[str, str]]:
  normalized = str(value or "").strip().lower()
  if not normalized:
    return None
  for option in _CASH_STRATEGY_OPTIONS:
    if normalized == option["value"]:
      return dict(option)
  return None


def _cash_strategy_decision_mode(last_assistant: str) -> str:
  assistant_text = str(last_assistant or "").strip().lower()
  if not assistant_text:
    return "initial"
  if _CASH_STRATEGY_FORCED_CHOICE_PROMPT_MARKER.lower() in assistant_text:
    return "forced_choice"
  if _CASH_STRATEGY_CLARIFY_PROMPT_MARKER.lower() in assistant_text:
    return "clarify"
  return "initial"


def _format_cash_strategy_options(*, numbered: bool = False) -> str:
  option_lines = []
  for idx, option in enumerate(_CASH_STRATEGY_OPTIONS, start=1):
    prefix = f"{idx}. " if numbered else "- "
    option_lines.append(f"{prefix}{option['label']}: {option['description']}")
  return "\n".join(option_lines)


def _build_cash_strategy_clarify_message() -> str:
  return (
    f"{_CASH_STRATEGY_CLARIFY_PROMPT_MARKER} which direction is closer to what you want for extra cash?\n\n"
    + _format_cash_strategy_options()
    + "\n\nA short answer is fine."
  )


def _build_cash_strategy_forced_choice_message() -> str:
  return (
    f"{_CASH_STRATEGY_FORCED_CHOICE_PROMPT_MARKER}\n\n"
    + _format_cash_strategy_options(numbered=True)
    + "\n\nReply with one option name or number."
  )


def _infer_cash_strategy_last_resort(
  *,
  conversation_messages: List[Dict[str, str]],
  last_assistant: str,
  user_message: str,
) -> Optional[str]:
  key = _openai_key()
  if not key:
    return None
  system = (
    "You are selecting the best-fit cash strategy for a financial intake flow.\n"
    "Choose exactly one of these persisted values: preserve_cash, shareholder_return, balanced.\n"
    "Use the recent conversation as the source of truth.\n"
    "The user was already asked to choose explicitly but may still have answered indirectly.\n"
    "Pick the option that best matches the user's intent.\n"
    "Return only the persisted value."
  )
  recent = list(conversation_messages or [])[-12:]
  transcript_lines: List[str] = []
  for message in recent:
    role = str((message or {}).get("role") or "").strip().lower()
    content = str((message or {}).get("content") or "").strip()
    if role and content:
      transcript_lines.append(f"{role}: {content}")
  if str(last_assistant or "").strip():
    transcript_lines.append(f"latest_assistant: {str(last_assistant).strip()}")
  if str(user_message or "").strip():
    transcript_lines.append(f"latest_user: {str(user_message).strip()}")
  resp = _post_openai(
    url="https://api.openai.com/v1/responses",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    payload={
      "model": _openai_model(),
      "input": [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(transcript_lines)},
      ],
    },
  )
  if resp.status_code >= 400:
    return None
  option = _cash_strategy_option(_parse_responses_text(resp.json()))
  return str(option.get("value")) if option else None


def _financials_stage_spec(stage_name: Optional[str]) -> Dict[str, Any]:
  return dict(_FINANCIALS_STAGE_SPECS.get(str(stage_name or "").strip(), {}))


def _financials_stage_complete(stage_name: str, financials_json: Dict[str, Any]) -> bool:
  spec = _financials_stage_spec(stage_name)
  completion_fields = tuple(spec.get("completion_fields") or ())
  if not completion_fields:
    return False
  data = _ensure_financials_stage_defaults(financials_json)
  return all(_financials_field_resolved(data, field_name) for field_name in completion_fields)


def _build_financials_controller_context(stage_name: Optional[str], *, last_assistant: str = "") -> Dict[str, Any]:
  stage = str(stage_name or "").strip()
  spec = _financials_stage_spec(stage)
  current_stage = {
    "name": stage or None,
    "patch_targets": list(spec.get("patch_targets") or []),
    "completion_fields": list(spec.get("completion_fields") or []),
    "confirmable_baseline": bool(spec.get("confirmable_baseline")),
    "clarifier": str(spec.get("clarifier") or "").strip(),
  }
  if stage == "cash_strategy":
    current_stage["allowed_values"] = [option["value"] for option in _CASH_STRATEGY_OPTIONS]
    current_stage["options"] = [dict(option) for option in _CASH_STRATEGY_OPTIONS]
    current_stage["decision_mode"] = _cash_strategy_decision_mode(last_assistant)
  return {"current_stage": current_stage}


def _financials_stage_confirm_question(stage_name: Optional[str]) -> Optional[str]:
  spec = _financials_stage_spec(stage_name)
  if not bool(spec.get("confirmable_baseline")):
    return None
  stage = str(stage_name or "").strip()
  if stage == "revenue_intro":
    return "Should I use this Year-1 revenue baseline for financial planning?"
  if stage == "cogs":
    return "Should I use this Year-1 direct-cost baseline?"
  if stage == "current_payroll":
    return "Should I use this Year-1 payroll baseline?"
  if stage == "marketing":
    return "Should I use this Year-1 marketing baseline?"
  return None


def _build_financials_stage_clarifier(stage_name: Optional[str]) -> str:
  spec = _financials_stage_spec(stage_name)
  clarifier = str(spec.get("clarifier") or "").strip()
  if clarifier:
    return clarifier
  return "What should I record for this financial item?"


def _next_financials_stage(financials_json: Dict[str, Any]) -> Optional[str]:
  data = _ensure_financials_stage_defaults(financials_json)
  for stage_name in _FINANCIALS_STAGE_ORDER:
    if not _financials_stage_complete(stage_name, data):
      return stage_name
  return None


_GENERIC_FINANCIALS_SCALAR_FIELDS = {
  "owner_compensation",
  "other_operating_expense",
  "current_num_employees",
  "current_capex",
  "initial_assets",
  "initial_lease",
  "initial_equity",
  "total_debt_outstanding",
  "other_monthly_debt_payments",
  "annual_interest_payment",
  "annual_principal_payment",
  "cash_on_hand",
  "ar_balance",
  "ap_balance",
  "inventory_balance",
}

_GENERIC_FINANCIALS_FIELD_LABELS = {
  "owner_compensation": "owner compensation",
  "other_operating_expense": "other operating expense",
  "current_num_employees": "current employee count",
  "current_capex": "current capital spending",
  "initial_assets": "initial assets already in the business",
  "initial_lease": "monthly lease commitment beyond main rent",
  "initial_equity": "money invested so far",
  "total_debt_outstanding": "total debt outstanding",
  "other_monthly_debt_payments": "other monthly debt payments",
  "annual_interest_payment": "annual interest payment",
  "annual_principal_payment": "annual principal payment",
  "cash_on_hand": "cash on hand",
  "ar_balance": "accounts receivable",
  "ap_balance": "accounts payable",
  "inventory_balance": "inventory balance",
}


def _removed_cash_strategy_message_unused() -> str:
  option_lines = []
  for option in _CASH_STRATEGY_OPTIONS:
    option_lines.append(f"- {option['label']}: {option['description']}")
  return (
    "One last financial planning question before I wrap this section up: when this business starts building extra cash, "
    "what would you want to do with it?\n\n"
    + "\n".join(option_lines)
    + "\n\nYou can answer in plain language and IÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¾ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ll map it to the closest approach."
  )


def _build_cash_strategy_message() -> str:
  return (
    f"{_CASH_STRATEGY_INITIAL_PROMPT_MARKER} when this business starts building extra cash, "
    "what would you want to do with it?\n\n"
    + _format_cash_strategy_options()
    + "\n\nYou can answer in plain language and I'll map it to the closest approach."
  )


def _build_cash_strategy_acknowledgement(value: Any) -> str:
  option = _cash_strategy_option(value)
  if not option:
    return "Got it."
  return f"Got it. IÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¾ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ll treat {option['label'].lower()} as the preferred cash posture."


def _is_generic_financials_scalar_stage(stage_name: Optional[str]) -> bool:
  return str(stage_name or "").strip() in _GENERIC_FINANCIALS_SCALAR_FIELDS


def _build_financials_scalar_stage_acknowledgement(stage_name: str, value: float) -> str:
  label = _GENERIC_FINANCIALS_FIELD_LABELS.get(stage_name, stage_name.replace("_", " "))
  if stage_name == "current_num_employees":
    return f"Got it - I'll use {int(round(value))} for {label}."
  return f"Got it - I'll use {_format_currency(value)} for {label}."


def _build_financials_scalar_stage_clarifier(stage_name: str) -> str:
  label = _GENERIC_FINANCIALS_FIELD_LABELS.get(stage_name, stage_name.replace("_", " "))
  if stage_name == "current_num_employees":
    return f"What number should I record for {label}? A whole number is fine."
  return f"What amount should I record for {label}? A rough number is fine, and 0 is okay if that is correct."


def _financials_stage_fallback_patch(
  *,
  stage_name: Optional[str],
  user_message: str,
  financials_year1_json: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  stage = str(stage_name or "").strip()
  user_text = str(user_message or "").strip()
  user_lower = user_text.lower()
  if stage != "marketing":
    return None
  numeric = _extract_first_number_from_text(user_text)
  if numeric is None:
    return None
  if "per month" in user_lower or "monthly" in user_lower:
    total = float(numeric) * 12.0
  else:
    total = float(numeric)
  revenue_year1 = _safe_float((financials_year1_json or {}).get("company_revenue_total_year1")) or 0.0
  patch: Dict[str, Any] = {"marketing_total_year1": total}
  if revenue_year1 > 0:
    patch["marketing_percent_of_revenue"] = float(total / revenue_year1)
  return patch


def _normalize_financials_router_patch(
  *,
  patch: Dict[str, Any],
  active_stage: Optional[str],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  last_assistant: str,
  user_message: str = "",
) -> Optional[Dict[str, Any]]:
  if not isinstance(patch, dict) or not patch:
    return None
  stage_name = str(active_stage or "").strip()
  allowed_fields = set(_financials_stage_spec(stage_name).get("patch_targets") or ())
  if not allowed_fields:
    return None
  next_financials = _ensure_financials_stage_defaults(dict(financials_json or {}))
  touched: set[str] = set()
  assistant_lower = str(last_assistant or "").strip().lower()
  user_lower = str(user_message or "").strip().lower()
  for raw_key, raw_value in patch.items():
    field_name = str(raw_key or "").strip()
    if field_name.startswith("financials."):
      field_name = field_name.split(".", 1)[1].strip()
    if field_name not in allowed_fields:
      continue
    if raw_value is None:
      continue
    if field_name == "current_num_employees":
      numeric = _safe_float(raw_value)
      if numeric is None:
        continue
      next_financials[field_name] = int(round(numeric))
      touched.add(field_name)
      continue
    if field_name == "owner_compensation":
      numeric = _safe_float(raw_value)
      if numeric is None:
        continue
      asks_monthly = "owner compensation" in assistant_lower and ("per month" in assistant_lower or "last month" in assistant_lower)
      mentions_annual = any(token in user_lower for token in ("annual", "annually", "per year", "yearly", "/year", "a year"))
      if asks_monthly and not mentions_annual and numeric <= 50000.0:
        numeric *= 12.0
      next_financials[field_name] = float(numeric)
      touched.add(field_name)
      continue
    if field_name == "future_rent_expected":
      next_financials[field_name] = bool(raw_value)
      touched.add(field_name)
      continue
    if field_name == "initial_lease":
      numeric = _safe_float(raw_value)
      if numeric is None:
        continue
      next_financials[field_name] = float(numeric)
      touched.add(field_name)
      continue
    if field_name == "cash_strategy":
      option = _cash_strategy_option(raw_value)
      if option is None:
        continue
      next_financials[field_name] = option["value"]
      touched.add(field_name)
      continue
    if field_name in {"cogs_percent_of_revenue", "marketing_percent_of_revenue"}:
      numeric = _normalize_ratio_like(raw_value)
      if numeric is None:
        continue
      next_financials[field_name] = float(numeric)
      touched.add(field_name)
      continue
    numeric = _safe_float(raw_value)
    if numeric is None:
      continue
    if stage_name == "marketing" and field_name == "marketing_total_year1":
      if ("per month" in user_lower or "monthly" in user_lower) and numeric <= 20000.0:
        numeric *= 12.0
    next_financials[field_name] = float(numeric)
    touched.add(field_name)
  if not touched:
    return None
  if stage_name == "revenue_intro" and "current_revenue" in touched:
    next_financials["_financials_revenue_intro_done"] = True
  if "cogs_percent_of_revenue" in touched:
    revenue_year1 = _safe_float((financials_year1_json or {}).get("company_revenue_total_year1")) or 0.0
    percent = float(next_financials.get("cogs_percent_of_revenue") or 0.0)
    next_financials["current_cogs"] = percent * revenue_year1 if revenue_year1 > 0 else 0.0
    next_financials["cogs_total_year1"] = float(next_financials.get("current_cogs") or 0.0)
  if "current_cogs" in touched:
    next_financials["cogs_total_year1"] = float(next_financials.get("current_cogs") or 0.0)
    revenue_year1 = _safe_float((financials_year1_json or {}).get("company_revenue_total_year1"))
    if revenue_year1 and revenue_year1 > 0:
      next_financials["cogs_percent_of_revenue"] = float(next_financials["current_cogs"]) / revenue_year1
  if "cogs_total_year1" in touched:
    next_financials["current_cogs"] = float(next_financials.get("cogs_total_year1") or 0.0)
    revenue_year1 = _safe_float((financials_year1_json or {}).get("company_revenue_total_year1"))
    if revenue_year1 and revenue_year1 > 0:
      next_financials["cogs_percent_of_revenue"] = float(next_financials["current_cogs"]) / revenue_year1
  if "current_payroll" in touched:
    next_financials["payroll_total_year1"] = float(next_financials.get("current_payroll") or 0.0)
  if "payroll_total_year1" in touched:
    next_financials["current_payroll"] = float(next_financials.get("payroll_total_year1") or 0.0)
  if "marketing_total_year1" in touched or "marketing_percent_of_revenue" in touched:
    next_financials = _sync_marketing_field_family(
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
      marketing_model_json={},
    )
  return _ensure_financials_stage_defaults(next_financials)


def _rescale_financials_year1_to_current_revenue(
  *,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Dict[str, Any]:
  next_year1 = dict(financials_year1_json or {})
  target_total = _safe_float((financials_json or {}).get("current_revenue"))
  current_total = _safe_float(next_year1.get("company_revenue_total_year1"))
  if target_total is None or target_total <= 0 or current_total is None or current_total <= 0:
    return next_year1
  if abs(target_total - current_total) <= max(0.01, abs(target_total) * 1e-9):
    return next_year1

  factor = float(target_total / current_total)
  if factor <= 0:
    return next_year1

  lobs = next_year1.get("lobs")
  if not isinstance(lobs, list) or not lobs:
    return next_year1

  product_overrides: Dict[str, Dict[str, float]] = {}
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    lob_name = str(lob.get("lob_name") or "").strip() or "Line of business"
    products = lob.get("products")
    if not isinstance(products, list):
      continue
    for product in products:
      if not isinstance(product, dict):
        continue
      product_name = str(product.get("product_name") or "").strip() or "Product"
      cadence = str(product.get("unit_cadence") or "").strip().lower()
      scaled_fields: Dict[str, float] = {}

      for field_name in (
        "units_per_period_capacity",
        "avg_units_per_period_year1",
      ):
        value = _safe_float(product.get(field_name))
        if value is not None:
          scaled_fields[field_name] = float(value * factor)

      if cadence == "weekly":
        for field_name in ("units_per_week_capacity", "avg_units_per_week_year1"):
          value = _safe_float(product.get(field_name))
          if value is not None:
            scaled_fields[field_name] = float(value * factor)
      elif cadence == "monthly":
        for field_name in ("units_per_month_capacity", "avg_units_per_month_year1"):
          value = _safe_float(product.get(field_name))
          if value is not None:
            scaled_fields[field_name] = float(value * factor)
      else:
        for field_name in ("concurrent_capacity_units", "avg_active_units_year1"):
          value = _safe_float(product.get(field_name))
          if value is not None:
            scaled_fields[field_name] = float(value * factor)

      if scaled_fields:
        product_overrides[f"{lob_name}::{product_name}"] = scaled_fields

  if not product_overrides:
    return next_year1

  try:
    try:
      from financials_year1 import apply_revenue_driver_patch  # type: ignore
    except Exception:
      from client_intake_and_finmo.financials_year1 import apply_revenue_driver_patch  # type: ignore
    return apply_revenue_driver_patch(next_year1, {"product_overrides": product_overrides})
  except Exception:
    return next_year1


def _sync_financials_consult_persistence_state(
  *,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
  next_financials = _ensure_financials_stage_defaults(dict(financials_json or {}))
  next_year1 = _rescale_financials_year1_to_current_revenue(
    financials_json=next_financials,
    financials_year1_json=financials_year1_json,
  )

  revenue_year1 = _safe_float(next_year1.get("company_revenue_total_year1")) or 0.0
  if revenue_year1 > 0:
    next_financials["current_revenue"] = float(revenue_year1)

  cogs_percent = _safe_float(next_financials.get("cogs_percent_of_revenue"))
  cogs_total = _safe_float(next_financials.get("cogs_total_year1"))
  current_cogs = _safe_float(next_financials.get("current_cogs"))
  if cogs_percent is not None and revenue_year1 > 0:
    cogs_percent = max(0.0, min(float(cogs_percent), 1.0))
    synced_total = float(cogs_percent * revenue_year1)
    next_financials["cogs_percent_of_revenue"] = cogs_percent
    next_financials["current_cogs"] = synced_total
    next_financials["cogs_total_year1"] = synced_total
  elif cogs_total is not None:
    synced_total = max(0.0, float(cogs_total))
    next_financials["current_cogs"] = synced_total
    next_financials["cogs_total_year1"] = synced_total
    if revenue_year1 > 0:
      next_financials["cogs_percent_of_revenue"] = float(synced_total / revenue_year1)
  elif current_cogs is not None:
    synced_total = max(0.0, float(current_cogs))
    next_financials["current_cogs"] = synced_total
    next_financials["cogs_total_year1"] = synced_total
    if revenue_year1 > 0:
      next_financials["cogs_percent_of_revenue"] = float(synced_total / revenue_year1)

  current_payroll = _safe_float(next_financials.get("current_payroll"))
  payroll_total = _safe_float(next_financials.get("payroll_total_year1"))
  if payroll_total is not None:
    synced_total = max(0.0, float(payroll_total))
    next_financials["current_payroll"] = synced_total
    next_financials["payroll_total_year1"] = synced_total
  elif current_payroll is not None:
    synced_total = max(0.0, float(current_payroll))
    next_financials["current_payroll"] = synced_total
    next_financials["payroll_total_year1"] = synced_total

  next_financials = _sync_marketing_field_family(
    financials_json=next_financials,
    financials_year1_json=next_year1,
    marketing_model_json=marketing_model_json or {},
  )
  return _ensure_financials_stage_defaults(next_financials), next_year1


def _extract_ops_proposal_patch(
  *,
  last_assistant: str,
  route_intent,
  ops_json: Dict[str, Any],
  shared_context: Dict[str, Any],
  recent_messages: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
  text = str(last_assistant or "").strip()
  if not text:
    return None
  try:
    proposal_intent = route_intent(
      consult_type="ops",
      user_message=text,
      baseline_json=ops_json,
      shared_context=shared_context,
      recent_messages=recent_messages,
      active_focus="ops",
    )
  except Exception:
    return None
  if str(proposal_intent.get("action") or "").strip() != "edit_patch":
    return None
  patch = proposal_intent.get("patch")
  if not isinstance(patch, dict) or not patch:
    return None
  return patch


def _fallback_ops_followup_question(ops_json: Dict[str, Any]) -> str:
  ops = ops_json if isinstance(ops_json, dict) else {}

  def _missing_text(field: str) -> bool:
    return not str(ops.get(field) or "").strip()

  if _missing_text("capacity_driver"):
    return (
      "What most limits how much you can grow right now: your available labor/time, "
      "your systems/processes, or having enough customer demand?"
    )
  if _missing_text("primary_growth_lever"):
    return (
      "What do you see as the main lever you'll push first to grow this business: "
      "winning more demand, improving systems/processes, or adding more people/capacity?"
    )
  if _missing_text("legal_entity"):
    return "Which legal structure are you using right now: Sole proprietor, LLC, Partnership, S-corp, or C-corp?"
  return ""


def _run_financials_turn_and_sync(
  *,
  route_intent,
  conn,
  intake_context: Dict[str, Any],
  conversation_messages: List[Dict[str, str]],
  business_facts: Dict[str, Any],
  shared_context: Dict[str, Any],
  last_assistant: str,
  user_message: str,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
  next_financials = _ensure_financials_stage_defaults(dict(financials_json or {}))
  active_stage = _next_financials_stage(next_financials)

  def _stage_context(
    stage_name: Optional[str],
    fin_json: Dict[str, Any],
    extra_shared: Optional[Dict[str, Any]] = None,
    prior_assistant: str = "",
  ) -> Dict[str, Any]:
    ctx = dict(intake_context or {})
    ctx["financials_json"] = fin_json
    next_shared = dict(extra_shared if isinstance(extra_shared, dict) else (shared_context or {}))
    next_shared["financials"] = fin_json
    next_shared["financials_controller"] = _build_financials_controller_context(
      stage_name,
      last_assistant=prior_assistant,
    )
    ctx["shared_context"] = next_shared
    if stage_name:
      ctx["financials_active_stage"] = stage_name
    else:
      ctx.pop("financials_active_stage", None)
    return ctx

  if not active_stage:
    return _build_financials_completion_turn(), next_financials

  stage_context = _stage_context(active_stage, next_financials, prior_assistant=last_assistant)
  stage_shared_context = dict(stage_context.get("shared_context") or {})
  confirm_question = _financials_stage_confirm_question(active_stage)
  if not str(user_message or "").strip():
    return {
      "assistant_message": _build_financials_stage_message(
        stage_name=active_stage,
        intake_context=stage_context,
        shared_context=stage_shared_context,
        financials_json=next_financials,
        financials_year1_json=financials_year1_json,
        business_facts=business_facts,
        conn=conn,
      ),
      "finalize_ready": False,
    }, next_financials

  routed = route_intent(
    consult_type="financials",
    user_message=str(user_message).strip(),
    baseline_json=next_financials,
    shared_context=stage_shared_context,
    recent_messages=conversation_messages[-30:] if conversation_messages else [],
    confirm_question_override=confirm_question,
    active_focus="financials",
  )
  action = str(routed.get("action") or "").strip()
  assistant_message = sanitize_fact_template(str(routed.get("assistant_message") or "").strip())
  patch = routed.get("patch") if isinstance(routed.get("patch"), dict) else None
  cash_strategy_mode = _cash_strategy_decision_mode(last_assistant) if active_stage == "cash_strategy" else ""

  if action == "confirm_proceed":
    default_patch = _financials_stage_default_patch(
      stage_name=active_stage,
      shared_context=stage_shared_context,
      financials_year1_json=financials_year1_json,
      business_facts=business_facts,
      conn=conn,
    )
    if isinstance(default_patch, dict) and default_patch:
      patch = {f"financials.{k}": v for k, v in default_patch.items()}
      action = "edit_patch"

  if action == "edit_patch" and patch:
    normalized_patch = _normalize_financials_router_patch(
      patch=patch,
      active_stage=active_stage,
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
      last_assistant=last_assistant,
      user_message=user_message,
    )
    if isinstance(normalized_patch, dict) and normalized_patch:
      acknowledgement = assistant_message or _build_financials_stage_acknowledgement(
        stage_name=active_stage,
        financials_json=normalized_patch,
      )
      next_context = _stage_context(active_stage, normalized_patch)
      next_turn, updated_financials, _ = _advance_persisted_financials_stage(
        conn=conn,
        draft_id=str((intake_context or {}).get("draft_id") or "").strip(),
        business_facts=business_facts,
        intake_context=next_context,
        conversation_messages=conversation_messages,
        shared_context=stage_shared_context,
        financials_json=normalized_patch,
        financials_year1_json=financials_year1_json,
        marketing_model_json=dict((stage_shared_context or {}).get("marketing") or {}),
        acknowledgement=acknowledgement,
      )
      return next_turn, updated_financials

  if active_stage == "cash_strategy":
    if cash_strategy_mode == "forced_choice":
      inferred_value = _infer_cash_strategy_last_resort(
        conversation_messages=conversation_messages,
        last_assistant=last_assistant,
        user_message=user_message,
      )
      if inferred_value:
        normalized_patch = _normalize_financials_router_patch(
          patch={"financials.cash_strategy": inferred_value},
          active_stage=active_stage,
          financials_json=next_financials,
          financials_year1_json=financials_year1_json,
          last_assistant=last_assistant,
          user_message=user_message,
        )
        if isinstance(normalized_patch, dict) and normalized_patch:
          acknowledgement = assistant_message or _build_financials_stage_acknowledgement(
            stage_name=active_stage,
            financials_json=normalized_patch,
          )
          next_context = _stage_context(active_stage, normalized_patch)
          next_turn, updated_financials, _ = _advance_persisted_financials_stage(
            conn=conn,
            draft_id=str((intake_context or {}).get("draft_id") or "").strip(),
            business_facts=business_facts,
            intake_context=next_context,
            conversation_messages=conversation_messages,
            shared_context=stage_shared_context,
            financials_json=normalized_patch,
            financials_year1_json=financials_year1_json,
            marketing_model_json=dict((stage_shared_context or {}).get("marketing") or {}),
            acknowledgement=acknowledgement,
          )
          return next_turn, updated_financials
    if action != "answer_readonly":
      if cash_strategy_mode == "initial":
        return {"assistant_message": _build_cash_strategy_clarify_message(), "finalize_ready": False}, next_financials
      if cash_strategy_mode == "clarify":
        return {"assistant_message": _build_cash_strategy_forced_choice_message(), "finalize_ready": False}, next_financials

  fallback_patch = _financials_stage_fallback_patch(
    stage_name=active_stage,
    user_message=user_message,
    financials_year1_json=financials_year1_json,
  )
  if isinstance(fallback_patch, dict) and fallback_patch:
    normalized_patch = _normalize_financials_router_patch(
      patch=fallback_patch,
      active_stage=active_stage,
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
      last_assistant=last_assistant,
      user_message=user_message,
    )
    if isinstance(normalized_patch, dict) and normalized_patch:
      acknowledgement = assistant_message or _build_financials_stage_acknowledgement(
        stage_name=active_stage,
        financials_json=normalized_patch,
      )
      next_context = _stage_context(active_stage, normalized_patch)
      next_turn, updated_financials, _ = _advance_persisted_financials_stage(
        conn=conn,
        draft_id=str((intake_context or {}).get("draft_id") or "").strip(),
        business_facts=business_facts,
        intake_context=next_context,
        conversation_messages=conversation_messages,
        shared_context=stage_shared_context,
        financials_json=normalized_patch,
        financials_year1_json=financials_year1_json,
        marketing_model_json=dict((stage_shared_context or {}).get("marketing") or {}),
        acknowledgement=acknowledgement,
      )
      return next_turn, updated_financials

  if action == "answer_readonly" and assistant_message:
    return {"assistant_message": assistant_message, "finalize_ready": False}, next_financials

  if action == "confirm_clarify" and assistant_message:
    return {"assistant_message": assistant_message, "finalize_ready": False}, next_financials

  return {
    "assistant_message": _build_financials_stage_clarifier(active_stage),
    "finalize_ready": False,
  }, next_financials


def _ops_ready_for_wrap_from_gate_obj(obj: Any) -> bool:
  if not isinstance(obj, dict):
    return False

  def _has_text(field: str) -> bool:
    return bool(str(obj.get(field) or "").strip())

  def _product_complete(product: Dict[str, Any]) -> bool:
    if not isinstance(product, dict):
      return False
    if not str(product.get("unit_name") or "").strip():
      return False
    cadence = str(product.get("unit_cadence") or "").strip().lower()
    if not cadence:
      return False
    if _is_missing_number_value(product.get("unit_price")):
      return False
    if _is_missing_number_value(product.get("units_per_period_capacity")) and _is_missing_number_value(
      product.get("units_per_week_capacity")
    ):
      return False
    if _is_missing_number_value(product.get("utilization_rate")):
      return False
    if cadence == "contract" and _is_missing_number_value(product.get("operating_periods_per_year")):
      return False
    return True

  lob_models = obj.get("lob_models")
  products: List[Dict[str, Any]] = []
  if isinstance(lob_models, list):
    for lob in lob_models:
      if not isinstance(lob, dict):
        continue
      lob_products = lob.get("products")
      if not isinstance(lob_products, list):
        continue
      for product in lob_products:
        if isinstance(product, dict):
          products.append(product)

  business_wide_fields = [
    "shipping_method",
    "sales_modality",
    "geographic_scope",
    "legal_entity",
    "capacity_driver",
    "primary_growth_lever",
  ]
  if not all(_has_text(field) for field in business_wide_fields):
    return False

  if products:
    return all(_product_complete(product) for product in products)

  if not _has_text("unit_name") or not _has_text("unit_cadence"):
    return False
  if _is_missing_number_value(obj.get("unit_price")):
    return False
  if _is_missing_number_value(obj.get("units_per_period_capacity")) and _is_missing_number_value(
    obj.get("units_per_week_capacity")
  ):
    return False
  if _is_missing_number_value(obj.get("utilization_rate")):
    return False
  if str(obj.get("unit_cadence") or "").strip().lower() == "contract" and _is_missing_number_value(
    obj.get("operating_periods_per_year")
  ):
    return False
  return True


def _is_guardrail_acknowledgement(message: str) -> bool:
  text = str(message or "").strip().lower()
  if not text:
    return False
  try:
    import re

    patterns = [
      r"\bok\b",
      r"\bokay\b",
      r"\byes\b",
      r"\bsounds good\b",
      r"\blooks good\b",
      r"\bworks for me\b",
      r"\bgo ahead\b",
      r"\bproceed\b",
      r"\bkeep (it|this) (as is|the same)\b",
      r"\bkeep as is\b",
      r"\bleave it\b",
      r"\bno changes\b",
      r"\bno change\b",
      r"\bi understand\b",
      r"\bunderstood\b",
      r"\baccept\b",
      r"\bi'?m ok\b",
      r"\bi am ok\b",
      r"\bfine\b",
      r"\ball good\b",
    ]
    return any(re.search(pat, text) for pat in patterns)
  except Exception:
    return False


def _is_restatement_acceptance(message: str) -> bool:
  """
  Semantic acceptance for restatement confirmations.
  Default to accept unless the user expresses disagreement, correction, or uncertainty.
  """
  text = str(message or "").strip().lower()
  if not text:
    return False
  try:
    import re

    reject_patterns = [
      r"\bno\b",
      r"\bnope\b",
      r"\bnot\b",
      r"\bincorrect\b",
      r"\bwrong\b",
      r"\bnot really\b",
      r"\bnot exactly\b",
      r"\bdoesn'?t\b",
      r"\bdoes not\b",
      r"\bthat'?s not\b",
      r"\bnot (quite|really)\b",
      r"\bexcept\b",
      r"\bbut\b",
      r"\bhowever\b",
      r"\binstead\b",
      r"\bactually\b",
      r"\bwe (don'?t|do not)\b",
      r"\bi (don'?t|do not)\b",
      r"\bnot sure\b",
      r"\bunsure\b",
      r"\bkind of\b",
      r"\bsort of\b",
      r"\bmaybe\b",
      r"\bdepends\b",
      r"\bpartly\b",
      r"\bpartially\b",
      r"\bnot fully\b",
      r"\bnot (completely|entirely)\b",
      r"\bquestion\b",
      r"\bconfused\b",
      r"\bchange\b",
      r"\bcorrect\b",
      r"\bclarify\b",
      r"\bupdate\b",
      r"\brevise\b",
    ]
    if any(re.search(pat, text) for pat in reject_patterns):
      return False
  except Exception:
    return False

  return True


def _classify_restatement_response(*, restatement: str, user_reply: str) -> Optional[str]:
  """
  Use GPT to classify the user's reply to a restatement as ACCEPT, REJECT, or CLARIFY.
  Returns one of those strings, or None if classification fails.
  """
  key = _openai_key()
  if not key:
    return None
  system = (
    "You are classifying a user's reply to a proposed restatement.\n"
    "Return exactly one of: ACCEPT, REJECT, CLARIFY.\n"
    "If the assistant text is not a restatement asking for confirmation, return CLARIFY.\n"
    "- ACCEPT: the user generally agrees that the restatement is accurate, even if they add extra nuance,\n"
    "  caveats, future plans, or additional details (e.g., \"yes, but...\", \"mostly yes...\", \"although...\").\n"
    "  Treat these as ACCEPT unless they clearly contradict the restatement.\n"
    "- REJECT: the user disagrees with a material part of the restatement or explicitly corrects/contradicts it.\n"
    "- CLARIFY: user is unsure, ambiguous, or asks for clarification.\n"
    "Return only the label."
  )
  payload = {
    "model": _openai_model(),
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": f"Restatement:\n{restatement}"},
      {"role": "user", "content": f"User reply:\n{user_reply}"},
    ],
  }
  resp = _post_openai(
    url="https://api.openai.com/v1/responses",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    payload=payload,
  )
  if resp.status_code >= 400:
    return None
  raw = _parse_responses_text(resp.json())
  label = str(raw or "").strip().upper()
  return label if label in ("ACCEPT", "REJECT", "CLARIFY") else None


def _detect_confirm_question(last_assistant: str) -> Optional[str]:
  text = str(last_assistant or "").strip().lower()
  if not text:
    return None
  for question in (
    OPS_CONFIRM_QUESTION,
    MARKET_CONFIRM_QUESTION,
    PEOPLE_CONFIRM_QUESTION,
  ):
    if question and question.lower() in text:
      return question
  return None


def _extract_competitive_advantage_prompt(last_assistant: str) -> Optional[str]:
  text = str(last_assistant or "").strip()
  if not text:
    return None
  for line in text.splitlines():
    line_stripped = line.strip()
    if not line_stripped:
      continue
    if line_stripped.lower().startswith(COMPETITIVE_ADVANTAGE_PREFIX.lower()):
      _, _, rest = line_stripped.partition(":")
      value = rest.strip()
      return value or None
  return None


def _extract_confirmed_restatement(messages: List[Dict[str, str]]) -> Optional[str]:
  for idx in range(len(messages) - 2, -1, -1):
    assistant_msg = messages[idx]
    user_msg = messages[idx + 1]
    if str(assistant_msg.get("role") or "") != "assistant":
      continue
    if str(user_msg.get("role") or "") != "user":
      continue
    assistant_text = str(assistant_msg.get("content") or "").strip()
    user_text = str(user_msg.get("content") or "").strip()
    if not assistant_text or not user_text:
      continue
    if not _is_guardrail_acknowledgement(user_text):
      continue
    if not assistant_text.endswith("?"):
      continue
    sentence_marks = sum(1 for ch in assistant_text if ch in ".!?")
    if sentence_marks < 2:
      continue
    return assistant_text
  return None


def _finalize_flag_field(focus: str, value: bool) -> Optional[Dict[str, Any]]:
  focus_norm = str(focus or "").strip().lower()
  mapping = {
    "ops": "ops_finalize_proposed",
    "market": "market_finalize_proposed",
    "people": "people_finalize_proposed",
  }
  key = mapping.get(focus_norm)
  if not key:
    return None
  return {key: bool(value)}


def _year1_driver_map(year1_json: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
  out: Dict[str, Dict[str, Any]] = {}
  if not isinstance(year1_json, dict):
    return out
  lobs = year1_json.get("lobs")
  if not isinstance(lobs, list):
    return out
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    lob_name = str(lob.get("lob_name") or "").strip().lower()
    products = lob.get("products")
    if not isinstance(products, list):
      continue
    for product in products:
      if not isinstance(product, dict):
        continue
      product_name = str(product.get("product_name") or "").strip().lower()
      if not product_name:
        continue
      key = f"{lob_name}::{product_name}"
      out[key] = {
        "unit_cadence": str(product.get("unit_cadence") or "").strip().lower(),
        "unit_price": product.get("unit_price"),
        "units_per_period_capacity": product.get("units_per_period_capacity"),
        "operating_periods_per_year": product.get("operating_periods_per_year"),
        "utilization_rate": product.get("utilization_rate"),
      }
  return out


def _year1_drivers_conflict(existing_year1: Optional[Dict[str, Any]], base_year1: Dict[str, Any]) -> bool:
  if not isinstance(existing_year1, dict) or not existing_year1:
    return False
  existing_map = _year1_driver_map(existing_year1)
  base_map = _year1_driver_map(base_year1)
  if not existing_map or not base_map:
    return False

  def _num(value: Any) -> Optional[float]:
    try:
      return float(value)
    except Exception:
      return None

  for key, base_driver in base_map.items():
    existing_driver = existing_map.get(key)
    if not existing_driver:
      continue
    base_cadence = str(base_driver.get("unit_cadence") or "").strip().lower()
    existing_cadence = str(existing_driver.get("unit_cadence") or "").strip().lower()
    if base_cadence and existing_cadence and base_cadence != existing_cadence:
      return True
    base_price = _num(base_driver.get("unit_price"))
    existing_price = _num(existing_driver.get("unit_price"))
    if base_price is not None and existing_price is not None and abs(base_price - existing_price) > 0.01:
      return True
    base_capacity = _num(base_driver.get("units_per_period_capacity"))
    existing_capacity = _num(existing_driver.get("units_per_period_capacity"))
    if base_capacity is not None and existing_capacity is not None and abs(base_capacity - existing_capacity) > 0.01:
      return True
    base_periods = _num(base_driver.get("operating_periods_per_year"))
    existing_periods = _num(existing_driver.get("operating_periods_per_year"))
    if base_periods is not None and existing_periods is not None and abs(base_periods - existing_periods) > 0.01:
      return True
    base_util = _num(base_driver.get("utilization_rate"))
    existing_util = _num(existing_driver.get("utilization_rate"))
    if base_util is not None and existing_util is not None and abs(base_util - existing_util) > 0.0001:
      return True
  return False


def _normalize_unscoped_patch(patch: Dict[str, Any], *, focus: str) -> Dict[str, Any]:
  focus_norm = str(focus or "").strip().lower()
  if not isinstance(patch, dict) or not patch:
    return patch
  field_sets = {
    "ops": {
      "consumer_type",
      "business_type",
      "business_stage",
      "business_naics_6",
      "unit_name",
      "unit_description",
      "unit_cadence",
      "units_per_week_capacity",
      "units_per_period_capacity",
      "operating_periods_per_year",
      "utilization_rate",
      "unit_price",
      "shipping_method",
      "sales_modality",
      "geographic_scope",
      "geographic_coverage",
      "countries",
      "milestones",
      "competitive_advantage",
      "capacity_driver",
      "primary_growth_lever",
      "legal_entity",
      "lob_models",
      "confidence",
    },
    "market": {
      "consumer_type",
      "gender_age_intent",
      "income_intent",
      "selections",
      "b2b_industry_terms",
      "b2b_naics_6",
      "b2b_size_bands",
      "b2b_age_bands",
      "marketing_plan_summary",
      "confidence",
    },
    "people": {
      "people",
      "inferred_roles",
      "inferred_roles_summary",
      "business_naics_6",
      "confidence",
    },
    "financials": {
      "current_revenue",
      "current_cogs",
      "baseline_marketing_percent",
      "baseline_marketing",
      "marketing_adjustment",
      "marketing_total_year1",
      "marketing_percent_of_revenue",
      "other_operating_expense",
      "monthly_rent_expense",
      "future_rent_expected",
      "other_monthly_debt_payments",
      "current_payroll",
      "current_num_employees",
      "current_capex",
      "ar_balance",
      "ap_balance",
      "inventory_balance",
      "initial_assets",
      "initial_lease",
      "initial_equity",
      "total_debt_outstanding",
      "annual_interest_payment",
      "annual_principal_payment",
      "owner_compensation",
      "cash_on_hand",
      "confidence",
    },
    "fulfillment": {
      "time",
      "personnel",
    },
  }
  allowed = field_sets.get(focus_norm, set())
  if not allowed:
    return patch
  normalized: Dict[str, Any] = {}
  for raw_key, value in patch.items():
    key = str(raw_key or "").strip()
    if not key:
      continue
    if "." in key:
      normalized[key] = value
      continue
    if key in allowed:
      normalized[f"{focus_norm}.{key}"] = value
    else:
      normalized[key] = value
  return normalized

def _constraints_snippet_already_sent(messages: List[Dict[str, str]]) -> bool:
  for msg in messages or []:
    if str(msg.get("role") or "").strip().lower() != "assistant":
      continue
    content = str(msg.get("content") or "")
    if "operational constraints:" in content.lower():
      return True
  return False


def _append_constraints_snippet(
  assistant_text: str,
  snippet: str,
  messages: List[Dict[str, str]],
  *,
  force: bool = False,
) -> str:
  # Financials no longer shows the deterministic "Operational constraints" block
  # in the client-facing chat output.
  return assistant_text



def _strip_acs_codes(text: str) -> str:
  """
  Never expose raw ACS codes in the UI conversation.
  """
  try:
    import re

    return re.sub(r"\b[A-Z]\d{5}_\d{3}E\b", "[ACS code redacted]", text)
  except Exception:
    return text


def _parse_date(value: Any) -> Optional[date]:
  if value is None:
    return None
  if isinstance(value, datetime):
    return value.date()
  if isinstance(value, date):
    return value
  raw = str(value).strip()
  if not raw:
    return None
  try:
    return datetime.fromisoformat(raw).date()
  except ValueError:
    pass
  for fmt in ("%m/%d/%Y", "%m-%d-%Y"):
    try:
      return datetime.strptime(raw, fmt).date()
    except ValueError:
      continue
  return None


def _infer_business_stage(start_date_raw: Any, current_date: Optional[date] = None) -> Optional[str]:
  start_date = _parse_date(start_date_raw)
  if start_date is None:
    return None
  today = current_date or datetime.utcnow().date()
  if start_date > today:
    return "pre-revenue"
  delta_days = (today - start_date).days
  if delta_days <= 365:
    return "early-stage"
  return "operating"


def _whole_months_between(start_date: date, end_date: date) -> int:
  months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
  if end_date.day < start_date.day:
    months -= 1
  return int(months)


def _openai_key() -> Optional[str]:
  key = (os.getenv("OPENAI_API_KEY") or "").strip()
  return key or None


def _openai_model() -> str:
  return (os.getenv("OPENAI_MODEL") or "gpt-5.1").strip() or "gpt-5.1"


def _set_active_openai_deadline(deadline_monotonic: Optional[float]) -> Optional[float]:
  global _ACTIVE_OPENAI_DEADLINE_MONOTONIC
  previous = _ACTIVE_OPENAI_DEADLINE_MONOTONIC
  _ACTIVE_OPENAI_DEADLINE_MONOTONIC = (
    float(deadline_monotonic)
    if isinstance(deadline_monotonic, (int, float)) and float(deadline_monotonic) > 0
    else None
  )
  return previous


def _active_openai_deadline_remaining_seconds() -> Optional[float]:
  deadline = _ACTIVE_OPENAI_DEADLINE_MONOTONIC
  if not isinstance(deadline, (int, float)) or float(deadline) <= 0:
    return None
  return float(deadline) - time.perf_counter()


def _openai_timeout_seconds() -> Optional[int]:
  raw = (os.getenv("OPENAI_TIMEOUT_SECONDS") or "").strip()
  if raw:
    try:
      return max(30, int(raw))
    except Exception:
      pass
  return 120


def _post_openai(*, url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> requests.Response:
  model_name = str((payload or {}).get("model") or "").strip() or "unknown"
  caller_frame = None
  try:
    caller_frame = __import__("sys")._getframe(1)
  except Exception:
    caller_frame = None
  caller_name = str(getattr(getattr(caller_frame, "f_code", None), "co_name", "") or "unknown")
  caller_line = int(getattr(caller_frame, "f_lineno", 0) or 0)
  _OPENAI_CALL_TELEMETRY["logical_call_count"] = int(_safe_float(_OPENAI_CALL_TELEMETRY.get("logical_call_count")) or 0) + 1
  by_model = _OPENAI_CALL_TELEMETRY.get("by_model") if isinstance(_OPENAI_CALL_TELEMETRY.get("by_model"), dict) else {}
  by_model[model_name] = int(_safe_float(by_model.get(model_name)) or 0) + 1
  _OPENAI_CALL_TELEMETRY["by_model"] = by_model
  events = _OPENAI_CALL_TELEMETRY.get("events") if isinstance(_OPENAI_CALL_TELEMETRY.get("events"), list) else []
  events.append(
    {
      "sequence": int(_safe_float(_OPENAI_CALL_TELEMETRY.get("logical_call_count")) or 0),
      "model": model_name,
      "input_item_count": len((payload or {}).get("input") or []),
      "caller": caller_name,
      "caller_line": caller_line,
    }
  )
  _OPENAI_CALL_TELEMETRY["events"] = events[-200:]
  timeout = _openai_timeout_seconds()
  remaining = _active_openai_deadline_remaining_seconds()
  max_attempts = 3
  if remaining is not None:
    guard_seconds = min(
      float(_ACTIVE_OPENAI_DEADLINE_RETURN_GUARD_SECONDS),
      max(2.0, float(remaining) * 0.10),
    )
    request_budget = float(remaining) - guard_seconds
    if request_budget <= 1.0:
      raise TimeoutError(
        "active OpenAI deadline has insufficient guarded budget before request could start: "
        f"remaining_seconds={round(float(remaining), 3)} guard_seconds={round(guard_seconds, 3)}"
      )
    strict_format = ((payload or {}).get("text") or {}).get("format") if isinstance((payload or {}).get("text"), dict) else {}
    is_strict_structured_output = (
      isinstance(strict_format, dict)
      and str(strict_format.get("type") or "").strip().lower() == "json_schema"
    )
    # Bounded strict structured-output calls need one full attempt more than two
    # partial attempts. Splitting the active deadline can strand the model while
    # still consuming the whole cycle budget.
    max_attempts = 1 if is_strict_structured_output else (2 if request_budget >= 100.0 else 1)
    per_attempt_budget = max(1.0, (request_budget - (0.75 if max_attempts > 1 else 0.0)) / max_attempts)
    timeout = max(1, int(math.floor(per_attempt_budget)))
  try:
    return post_openai_with_retries(
      url=url,
      headers=headers,
      payload=payload,
      timeout_seconds=timeout,
      retryable_status=_RETRYABLE_STATUS,
      max_attempts=max_attempts,
    )
  except Exception as exc:
    remaining_after = _active_openai_deadline_remaining_seconds()
    raise RuntimeError(
      "openai_request_failed: "
      f"caller={caller_name}:{caller_line}; model={model_name}; "
      f"timeout_seconds={timeout}; active_deadline_remaining_seconds="
      f"{round(float(remaining_after), 3) if remaining_after is not None else None}; "
      f"error={exc}"
    ) from exc


def _parse_responses_text(data: Dict[str, Any]) -> str:
  output = data.get("output") or []
  chunks: List[str] = []
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_text" and part.get("text"):
        chunks.append(str(part["text"]))
  if not chunks:
    raise RuntimeError("OpenAI response contained no output_text.")
  return "\n".join(chunks).strip()


def _months_until(target: date, reference_date: Optional[date]) -> int:
  ref = reference_date or datetime.utcnow().date()
  months = (target.year - ref.year) * 12 + (target.month - ref.month)
  if target.day > ref.day:
    months += 1
  if months < 0:
    return 0
  return months


def _timing_months_max_deterministic(timing_text: str, reference_date: Optional[date]) -> Optional[int]:
  text = str(timing_text or "").strip().lower()
  if not text:
    return None
  try:
    import re

    months_match = re.search(r"\b(\d+)\s*(months?|mos?)\b", text)
    if months_match:
      return int(months_match.group(1))
    years_match = re.search(r"\b(\d+)\s*(years?|yrs?)\b", text)
    if years_match:
      return int(years_match.group(1)) * 12

    quarter_match = re.search(r"\bq([1-4])\s*([12]\d{3})\b", text)
    if quarter_match:
      q = int(quarter_match.group(1))
      year = int(quarter_match.group(2))
      month = q * 3
      last_day = calendar.monthrange(year, month)[1]
      return _months_until(date(year, month, last_day), reference_date)
    quarter_match = re.search(r"\b([12]\d{3})\s*q([1-4])\b", text)
    if quarter_match:
      year = int(quarter_match.group(1))
      q = int(quarter_match.group(2))
      month = q * 3
      last_day = calendar.monthrange(year, month)[1]
      return _months_until(date(year, month, last_day), reference_date)

    month_map = {
      "jan": 1,
      "january": 1,
      "feb": 2,
      "february": 2,
      "mar": 3,
      "march": 3,
      "apr": 4,
      "april": 4,
      "may": 5,
      "jun": 6,
      "june": 6,
      "jul": 7,
      "july": 7,
      "aug": 8,
      "august": 8,
      "sep": 9,
      "sept": 9,
      "september": 9,
      "oct": 10,
      "october": 10,
      "nov": 11,
      "november": 11,
      "dec": 12,
      "december": 12,
    }
    month_regex = r"\b(" + "|".join(month_map.keys()) + r")\b"
    month_match = re.search(month_regex + r".*?\b([12]\d{3})\b", text)
    if month_match:
      month_name = month_match.group(1)
      year = int(month_match.group(2))
      month = month_map.get(month_name)
      if month:
        last_day = calendar.monthrange(year, month)[1]
        return _months_until(date(year, month, last_day), reference_date)

    year_end_match = re.search(r"(end of|by end of)\s*([12]\d{3})\b", text)
    if year_end_match:
      year = int(year_end_match.group(2))
      return _months_until(date(year, 12, 31), reference_date)
  except Exception:
    return None
  return None


def _timing_months_max_via_openai(timing_text: str, reference_date: Optional[date]) -> Optional[int]:
  key = _openai_key()
  if not key:
    return None
  timing = str(timing_text or "").strip()
  if timing:
    timing = timing.replace("\u2013", "-").replace("\u2014", "-")
  if not timing:
    return None
  ref_date = reference_date.isoformat() if isinstance(reference_date, date) else None
  system = (
    "You convert milestone timing text into a single integer: the MAX number of months. "
    "If the text contains a range, return the upper bound in months. "
    "If the text references quarters or years, convert to months. "
    "If you cannot determine a number of months, return null. "
    "Return ONLY valid JSON: {\"months_max\": <integer or null>}."
  )
  payload = {
    "model": _openai_model(),
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": json.dumps({"timing": timing, "reference_date": ref_date})},
    ],
  }
  resp = _post_openai(
    url="https://api.openai.com/v1/responses",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    payload=payload,
  )
  if resp.status_code >= 400:
    return None
  data = resp.json()
  raw = _parse_responses_text(data)
  try:
    parsed = json.loads(raw)
  except Exception:
    parsed = None
  if isinstance(parsed, dict):
    value = parsed.get("months_max")
  else:
    value = raw.strip()
  if value is None:
    return None
  if isinstance(value, (int, float)):
    return int(round(float(value)))
  try:
    return int(round(float(str(value).strip())))
  except Exception:
    return None


def _enrich_milestones_timing(ops_json: Dict[str, Any], reference_date: Optional[date]) -> None:
  milestones = ops_json.get("milestones")
  if isinstance(milestones, str):
    try:
      milestones = json.loads(milestones)
    except Exception:
      milestones = None
  if not isinstance(milestones, list):
    return
  def _coerce_positive_int(value: Any) -> Optional[int]:
    if value is None:
      return None
    if isinstance(value, bool):
      return None
    if isinstance(value, (int, float)):
      if float(value) <= 0:
        return None
      return int(round(float(value)))
    try:
      parsed = int(round(float(str(value).strip())))
    except Exception:
      return None
    return parsed if parsed > 0 else None

  for milestone in milestones:
    if not isinstance(milestone, dict):
      continue
    existing = _coerce_positive_int(milestone.get("timing_months_max"))
    if existing is not None:
      milestone["timing_months_max"] = existing
      continue
    months = _timing_months_max_deterministic(str(milestone.get("timing") or "").strip(), reference_date)
    if months is None:
      months = _timing_months_max_via_openai(str(milestone.get("timing") or "").strip(), reference_date)
    if months is None:
      continue
    milestone["timing_months_max"] = months


def _parse_milestones(raw: Any) -> List[Dict[str, Any]]:
  if raw is None:
    return []
  if isinstance(raw, str):
    try:
      parsed = json.loads(raw)
    except Exception:
      return []
    raw = parsed
  if not isinstance(raw, list):
    return []
  return [m for m in raw if isinstance(m, dict)]


































def _has_confirmed_milestone(ops_json: Dict[str, Any]) -> bool:
  for milestone in _parse_milestones((ops_json or {}).get("milestones")):
    desc = str(milestone.get("description") or "").strip()
    timing = str(milestone.get("timing") or "").strip()
    if desc and timing:
      return True
  return False


def _ensure_ops_business_naics(conn, ops_json: Dict[str, Any]) -> None:
  if not isinstance(ops_json, dict):
    return
  if not ops_json.get("business_type"):
    return
  if ops_json.get("business_naics_6"):
    return
  try:
    try:
      from business_type_naics import get_naics_from_business_type  # type: ignore
    except Exception:
      from client_intake_and_finmo.business_type_naics import (  # type: ignore
        get_naics_from_business_type,
      )
    ops_json["business_naics_6"] = get_naics_from_business_type(
      conn, ops_json.get("business_type")
    )
  except Exception:
    ops_json.setdefault("business_naics_6", None)


def _extract_ops_pending_milestone(
  *,
  text: str,
  route_intent,
  ops_json: Dict[str, Any],
  shared_context: Dict[str, Any],
) -> Optional[List[Dict[str, Any]]]:
  try:
    milestone_intent = route_intent(
      consult_type="ops",
      user_message=str(text or "").strip(),
      baseline_json=ops_json,
      shared_context=shared_context,
      recent_messages=[],
      active_focus="ops",
    )
  except Exception:
    return None
  if str(milestone_intent.get("action") or "").strip() != "edit_patch":
    return None
  patch = milestone_intent.get("patch")
  if not isinstance(patch, dict) or not patch:
    return None
  milestones_val = patch.get("milestones")
  if not milestones_val:
    return None
  if isinstance(milestones_val, str):
    try:
      milestones_val = json.loads(milestones_val)
    except Exception:
      return None
  if not isinstance(milestones_val, list):
    return None
  return [m for m in milestones_val if isinstance(m, dict)]


def _fallback_ops_pending_milestone_from_text(text: str) -> Optional[Dict[str, str]]:
  raw = str(text or "").strip()
  if not raw:
    return None

  normalized = (
    raw.replace("\u2018", "'")
    .replace("\u2019", "'")
    .replace("\u201c", '"')
    .replace("\u201d", '"')
  )
  quoted_match = re.search(r"(?<!\w)['\"]([^'\"]{6,})['\"](?!\w)", normalized)
  if quoted_match:
    description = quoted_match.group(1).strip()
  else:
    description = re.sub(
      r"^(let's record|lets record|we(?:'ve| have) already established(?: the milestone as)?|record)\s*",
      "",
      normalized,
      flags=re.IGNORECASE,
    ).strip()
    description = re.sub(
      r"^(that|this)\s+(?:milestone|goal)\s+(?:is|would be)\s*",
      "",
      description,
      flags=re.IGNORECASE,
    ).strip()
  description = description.strip(" .")
  if len(description) < 6:
    return None

  lower_description = description.lower()
  timing = "Within the next 12 months"
  timing_patterns = [
    r"\b(?:within|over|in)\s+the\s+next\s+\d+\s+(?:months?|mos?|years?|yrs?)\b",
    r"\bwithin\s+\d+\s+(?:months?|mos?|years?|yrs?)\b",
    r"\bby\s+q[1-4]\s*[12]\d{3}\b",
    r"\bq[1-4]\s*[12]\d{3}\b",
    r"\b[12]\d{3}\s*q[1-4]\b",
    r"\bby\s+end\s+of\s+[12]\d{3}\b",
    r"\bend\s+of\s+[12]\d{3}\b",
    r"\byear\s*1\b",
    r"\bfirst\s+year\b",
  ]
  for pattern in timing_patterns:
    timing_match = re.search(pattern, lower_description, re.IGNORECASE)
    if timing_match:
      timing = description[timing_match.start():timing_match.end()].strip().rstrip(".,")
      break
  else:
    if re.search(r"\bq[1-4]\b", lower_description):
      timing = "By the referenced quarter"

  return {
    "description": description,
    "timing": timing,
  }


def _extract_ops_pending_milestone_via_openai(
  *,
  text: str,
  ops_json: Dict[str, Any],
  business_facts: Dict[str, Any],
) -> Dict[str, Any]:
  key = _openai_key()
  user_text = str(text or "").strip()
  if not key or not user_text:
    return {"captured": False, "milestone": None, "clarification_question": ""}

  schema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "captured": {"type": "boolean"},
      "milestone": {
        "type": ["object", "null"],
        "additionalProperties": False,
        "properties": {
          "description": {"type": "string"},
          "timing": {"type": "string"},
        },
        "required": ["description", "timing"],
      },
      "clarification_question": {"type": "string"},
    },
    "required": ["captured", "milestone", "clarification_question"],
  }

  system = (
    "You are extracting a single 12-month business milestone from the user's answer.\n"
    "The user is answering the question: what is one concrete goal they want to hit in about the next 12 months?\n\n"
    "Return ONLY JSON matching the schema.\n"
    "- If the user's answer clearly states one concrete goal, set captured=true and return one milestone object.\n"
    "- milestone.description should be a concise plain-English business goal.\n"
    "- milestone.timing should preserve the user's timeframe in plain English when available (for example: "
    "\"Within the next 12 months\" or \"By Q4 2026\").\n"
    "- If the answer is unclear or does not contain a concrete goal, set captured=false and ask one short clarification question.\n"
    "- Do not ask for permission to continue.\n"
    "- Do not return more than one milestone.\n"
  )
  context = {
    "business_name": str(business_facts.get("name") or "").strip(),
    "business_type": str((ops_json or {}).get("business_type") or "").strip(),
    "unit_name": str((ops_json or {}).get("unit_name") or "").strip(),
    "unit_cadence": str((ops_json or {}).get("unit_cadence") or "").strip(),
    "user_answer": user_text,
  }
  payload = {
    "model": _openai_model(),
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": "ops_pending_milestone_extract",
        "schema": schema,
        "strict": True,
      }
    },
  }
  resp = _post_openai(
    url="https://api.openai.com/v1/responses",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    payload=payload,
  )
  if resp.status_code >= 400:
    return {"captured": False, "milestone": None, "clarification_question": ""}

  data = resp.json()
  output = data.get("output") or []
  parsed: Optional[Dict[str, Any]] = None
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_json" and isinstance(part.get("json"), dict):
        parsed = part["json"]
        break
    if parsed:
      break
  if parsed is None:
    try:
      parsed = json.loads(_parse_responses_text(data))
    except Exception:
      parsed = None
  if not isinstance(parsed, dict):
    return {"captured": False, "milestone": None, "clarification_question": ""}
  return {
    "captured": bool(parsed.get("captured", False)),
    "milestone": parsed.get("milestone") if isinstance(parsed.get("milestone"), dict) else None,
    "clarification_question": str(parsed.get("clarification_question") or "").strip(),
  }


def _detect_people_done_adding_via_openai(
  *,
  last_assistant: str,
  user_message: str,
) -> bool:
  key = _openai_key()
  assistant_text = str(last_assistant or "").strip()
  user_text = str(user_message or "").strip()
  if not key or not assistant_text or not user_text:
    return False

  schema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "done_adding_people": {"type": "boolean"},
    },
    "required": ["done_adding_people"],
  }
  system = (
    "You are classifying a People/HR intake reply.\n"
    "Decide whether the client is saying they are done adding key people and wants to move to the full review.\n"
    "Return ONLY JSON matching the schema.\n"
    "Set done_adding_people=true only when the user's reply clearly means there are no more people to add right now.\n"
    "Do not rely on exact keywords; use the assistant question and the user's reply together."
  )
  payload = {
    "model": _openai_model(),
    "input": [
      {"role": "system", "content": system},
      {
        "role": "user",
        "content": json.dumps(
          {
            "assistant_message": assistant_text,
            "user_message": user_text,
          },
          ensure_ascii=False,
        ),
      },
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": "people_done_adding_detect",
        "schema": schema,
        "strict": True,
      }
    },
  }
  resp = _post_openai(
    url="https://api.openai.com/v1/responses",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    payload=payload,
  )
  if resp.status_code >= 400:
    return False
  data = resp.json()
  output = data.get("output") or []
  parsed: Optional[Dict[str, Any]] = None
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_json" and isinstance(part.get("json"), dict):
        parsed = part["json"]
        break
    if parsed:
      break
  if parsed is None:
    try:
      parsed = json.loads(_parse_responses_text(data))
    except Exception:
      parsed = None
  if not isinstance(parsed, dict):
    return False
  return bool(parsed.get("done_adding_people"))


def _build_people_review_payload(
  *,
  conn,
  final_obj: Dict[str, Any],
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  business_facts: Dict[str, Any],
) -> Tuple[Dict[str, Any], str]:
  people_json = dict(final_obj or {})
  try:
    from people_roles import (  # type: ignore
      apply_oews_wages,
      apply_oews_wages_to_people,
      format_roles_summary,
    )

    roles = people_json.get("inferred_roles") if isinstance(people_json, dict) else None
    roles = roles if isinstance(roles, list) else []
    people_list = people_json.get("people") if isinstance(people_json, dict) else None
    people_list = people_list if isinstance(people_list, list) else []
    enriched_people = apply_oews_wages_to_people(
      conn,
      people=people_list,
      business_type=ops_json.get("business_type"),
      business_stage=ops_json.get("business_stage"),
      address_state=business_facts.get("address_state"),
      address=business_facts.get("address"),
      business_naics_6=ops_json.get("business_naics_6"),
    )
    enriched_roles = apply_oews_wages(
      conn,
      roles=roles,
      business_type=ops_json.get("business_type"),
      business_stage=ops_json.get("business_stage"),
      address_state=business_facts.get("address_state"),
      address=business_facts.get("address"),
      business_naics_6=ops_json.get("business_naics_6"),
    )
    people_json["business_naics_6"] = ops_json.get("business_naics_6")
    people_json["people"] = enriched_people
    people_json["inferred_roles"] = enriched_roles
    people_json["inferred_roles_summary"] = format_roles_summary(enriched_roles)
  except Exception:
    if "inferred_roles" not in people_json:
      people_json["inferred_roles"] = []
    if "inferred_roles_summary" not in people_json:
      people_json["inferred_roles_summary"] = ""
    if "business_naics_6" not in people_json:
      people_json["business_naics_6"] = None

  if isinstance(people_json, dict):
    people_json.pop("key_people_summary", None)

  try:
    try:
      from fact_templates import render_fact_template  # type: ignore
    except Exception:
      from client_intake_and_finmo.fact_templates import render_fact_template  # type: ignore

    if isinstance(people_json, dict):
      business_facts_for_render = {
        "name": str(business_facts.get("name") or "").strip(),
        "address": str(business_facts.get("address") or "").strip(),
        "start_date": str(business_facts.get("start_date") or "").strip(),
      }
      shared_ctx_for_render = {
        "operating_model": ops_json,
        "target_market": market_json,
        "people_capability": people_json,
        "financials": financials_json,
      }
      ppl = people_json.get("people")
      if isinstance(ppl, list):
        for p in ppl:
          if not isinstance(p, dict):
            continue
          for fk, fv in list(p.items()):
            if isinstance(fv, str) and "{{fact:" in fv:
              p[fk] = render_fact_template(
                fv, shared_context=shared_ctx_for_render, business_facts=business_facts_for_render
              ).strip()
      roles = people_json.get("inferred_roles")
      if isinstance(roles, list):
        for r in roles:
          if not isinstance(r, dict):
            continue
          for fk, fv in list(r.items()):
            if isinstance(fv, str) and "{{fact:" in fv:
              r[fk] = render_fact_template(
                fv, shared_context=shared_ctx_for_render, business_facts=business_facts_for_render
              ).strip()
  except Exception:
    pass

  key_people_blocks: List[str] = []
  try:
    people_list = people_json.get("people") if isinstance(people_json, dict) else None
    people_list = people_list if isinstance(people_list, list) else []
    for p in people_list:
      if not isinstance(p, dict):
        continue
      para = p.get("paragraph")
      if isinstance(para, str) and para.strip():
        block = para.strip()
        wage_raw = p.get("annual_wage")
        try:
          wage_val = float(wage_raw)
        except Exception:
          wage_val = None
        if wage_val is not None and wage_val > 0:
          wage_fmt = f"${int(round(wage_val)):,.0f}"
          block = f"{block.rstrip()} Estimated annual wage: {wage_fmt}/year."
        key_people_blocks.append(block)
  except Exception:
    key_people_blocks = []

  inferred_roles_summary = str((people_json or {}).get("inferred_roles_summary") or "").strip()
  parts: List[str] = []
  has_people = bool(key_people_blocks)
  has_roles = bool(inferred_roles_summary)
  if has_people and has_roles:
    parts.append(
      "Review this draft (key people narrative + suggested year-1 roles with wages and timing) and tell me any changes."
    )
  elif has_people:
    parts.append("Review this draft (key people narrative) and tell me any changes.")
  elif has_roles:
    parts.append("Review these suggested year-1 roles (with wages and timing) and tell me any changes.")

  if has_people:
    parts.append("\n\n".join(key_people_blocks))
  if has_roles:
    parts.append(inferred_roles_summary)
  assistant_final = "\n\n".join([p for p in parts if p.strip()]).strip()
  if assistant_final:
    assistant_final = f"{assistant_final}\n\n{PEOPLE_CONFIRM_QUESTION}".strip()
  else:
    assistant_final = PEOPLE_CONFIRM_QUESTION

  return people_json, assistant_final

def _propose_ops_competitive_advantage(
  *,
  ops_json: Dict[str, Any],
  business_facts: Dict[str, Any],
  shared_context: Dict[str, Any],
  confirmed_restatement: Optional[str],
) -> str:
  key = _openai_key()
  if not key:
    raise RuntimeError("OPENAI_API_KEY is not configured.")
  system = (
    "You are a senior business consultant defining a companyÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¾ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢s competitive advantage.\n\n"
    "This is NOT marketing language.\n"
    "This is an execution-based advantage grounded in how the business actually operates.\n\n"
    "Context:\n"
    "You are given the full operating model, including:\n"
    "- business type and stage\n"
    "- unit definition and pricing\n"
    "- capacity driver (labor / system / demand)\n"
    "- fulfillment and delivery model\n"
    "- geographic scope and coverage\n"
    "- target customer type (consumer / B2B / mixed)\n\n"
    "Your task:\n"
    "Propose ONE concise competitive advantage that clearly explains:\n"
    "1) What this business does meaningfully differently from typical competitors\n"
    "2) Why that difference exists operationally (process, structure, constraints, choices)\n"
    "3) Why it matters economically or experientially to the customer\n"
    "4) Why it is not trivial for competitors to replicate\n\n"
    "Hard rules:\n"
    "- Do NOT use generic phrases (e.g., ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œhigh quality,ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œgreat service,ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œcustomer-focused,ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œfast,ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œpersonalizedÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â) unless you explain *how* they are structurally enabled.\n"
    "- Do NOT describe multiple advantages ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â pick the single most defensible one.\n"
    "- Do NOT restate the business description.\n"
    "- Tie the advantage to at least ONE concrete operational choice (e.g., menu design, staffing model, throughput discipline, geographic focus, fulfillment cadence).\n"
    "- Keep it to 2ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã¢â‚¬Å“3 sentences total.\n\n"
    "After proposing the advantage, ask ONE confirmation question:\n"
    "ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œDoes this accurately reflect what truly sets the business apart?ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â\n\n"
    "If the client disagrees:\n"
    "- Ask ONE targeted clarification question.\n"
    "- Revise the advantage once and ask for confirmation again."
  )
  ops_payload = dict(ops_json or {})
  ops_payload["business_type"] = (ops_json or {}).get("business_type")
  ops_payload["business_naics_6"] = (ops_json or {}).get("business_naics_6")
  context_payload = {
    "confirmed_restatement": confirmed_restatement,
    "ops": ops_payload,
  }
  payload = {
    "model": _openai_model(),
    "input": [
      {"role": "system", "content": system},
      {"role": "user", "content": json.dumps(context_payload)},
    ],
  }
  resp = _post_openai(
    url="https://api.openai.com/v1/responses",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    payload=payload,
  )
  if resp.status_code >= 400:
    raise RuntimeError(_format_openai_error(resp))
  data = resp.json()
  raw = _parse_responses_text(data)
  cleaned = " ".join(str(raw or "").split()).strip().strip('"')
  if not cleaned:
    raise RuntimeError("Failed to generate competitive advantage.")
  question = COMPETITIVE_ADVANTAGE_QUESTION
  lower = cleaned.lower()
  q_lower = question.lower()
  if q_lower in lower:
    idx = lower.rfind(q_lower)
    cleaned = cleaned[:idx].strip()
  if not cleaned:
    raise RuntimeError("Failed to generate competitive advantage.")
  return cleaned


def _build_business_type_candidates(
  *,
  conn,
  messages: List[Dict[str, str]],
  restatement_text: Optional[str] = None,
) -> List[str]:
  """
  Select a single best-matching business_type token from naics_master.business_types,
  using the latest confirmed restatement as the primary signal.
  """
  try:
    cur = conn.cursor()
    try:
      cur.execute("SELECT business_types FROM naics_master WHERE business_types IS NOT NULL")
      rows = cur.fetchall() or []
      values: List[str] = []
      for (bt,) in rows:
        if bt is None:
          continue
        for part in str(bt).split(","):
          part_str = str(part).strip()
          if part_str:
            values.append(part_str)
      all_business_types = sorted(set(values), key=lambda x: x.lower())
    finally:
      try:
        cur.close()
      except Exception:
        pass

    if restatement_text is None:
      restatement_text = _extract_confirmed_restatement(messages)
    if not restatement_text or not all_business_types:
      return []

    def _fallback_ranked_business_types(restatement: str, options: List[str], limit: int = 3) -> List[str]:
      raw = str(restatement or "").strip().lower()
      if not raw:
        return []
      try:
        import re
        from difflib import SequenceMatcher

        tokens = {
          token
          for token in re.findall(r"[a-z0-9]+", raw)
          if token and token not in {
            "the", "and", "for", "with", "that", "this", "from", "into", "your", "their",
            "business", "company", "service", "services", "product", "products", "model",
          }
        }
        scored: List[Tuple[float, str]] = []
        for option in options:
          candidate = str(option or "").strip()
          if not candidate:
            continue
          candidate_lower = candidate.lower()
          candidate_tokens = set(re.findall(r"[a-z0-9]+", candidate_lower))
          overlap = len(tokens & candidate_tokens)
          containment_bonus = 2 if candidate_lower in raw or raw in candidate_lower else 0
          ratio = SequenceMatcher(None, raw, candidate_lower).ratio()
          score = float(overlap * 5 + containment_bonus + ratio)
          scored.append((score, candidate))
        ranked = [candidate for _score, candidate in sorted(scored, key=lambda item: (-item[0], item[1].lower())) if candidate]
        deduped: List[str] = []
        seen: set[str] = set()
        for candidate in ranked:
          lowered = candidate.lower()
          if lowered in seen:
            continue
          seen.add(lowered)
          deduped.append(candidate)
          if len(deduped) >= max(1, int(limit or 1)):
            break
        return deduped
      except Exception:
        return []

    def _pick_index(restatement: str, options: List[str]) -> Optional[int]:
      key = _openai_key()
      if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
      system = (
        "You are selecting the single best-matching business type from a fixed list.\n"
        "Return EXACTLY ONE integer index from the provided list. Do not add any text.\n"
        "If multiple are close, pick the closest operationally.\n"
        "Return only the index and nothing else."
      )
      numbered = [f"{idx}. {val}" for idx, val in enumerate(options, start=1)]
      payload = {
        "model": _openai_model(),
        "input": [
          {"role": "system", "content": system},
          {"role": "user", "content": f"Restatement:\n{restatement}"},
          {"role": "user", "content": "Business types:\n" + "\n".join(numbered)},
        ],
      }
      resp = _post_openai(
        url="https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        payload=payload,
      )
      if resp.status_code >= 400:
        raise RuntimeError(_format_openai_error(resp))
      raw = _parse_responses_text(resp.json())
      raw_text = str(raw or "").strip().strip('"')
      try:
        idx = int(raw_text)
      except Exception:
        return None
      return idx if 1 <= idx <= len(options) else None

    def _pick_ranked_indices(
      restatement: str,
      options: List[str],
      k_expected: int,
    ) -> Optional[List[int]]:
      key = _openai_key()
      if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
      system = (
        "You are selecting the best-matching business types from a fixed list.\n"
        f"Return EXACTLY {k_expected} integer indices, ranked best-to-worst.\n"
        "Return a comma-separated list of integers and nothing else."
      )
      numbered = [f"{idx}. {val}" for idx, val in enumerate(options, start=1)]
      payload = {
        "model": _openai_model(),
        "input": [
          {"role": "system", "content": system},
          {"role": "user", "content": f"Restatement:\n{restatement}"},
          {"role": "user", "content": "Business types:\n" + "\n".join(numbered)},
        ],
      }
      resp = _post_openai(
        url="https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        payload=payload,
      )
      if resp.status_code >= 400:
        raise RuntimeError(_format_openai_error(resp))
      raw = _parse_responses_text(resp.json())
      raw_text = str(raw or "").strip().strip('"')
      try:
        import re

        parts = [int(x) for x in re.findall(r"\d+", raw_text)]
      except Exception:
        return None
      if len(parts) != k_expected:
        return None
      if len(set(parts)) != len(parts):
        return None
      if any(p < 1 or p > len(options) for p in parts):
        return None
      return parts

    batch_size = 300
    k = 3
    winners: List[str] = []
    for i in range(0, len(all_business_types), batch_size):
      batch = all_business_types[i : i + batch_size]
      if not batch:
        continue
      k_expected = min(k, len(batch))
      picks = _pick_ranked_indices(restatement_text, batch, k_expected)
      if picks is None:
        picks = _pick_ranked_indices(restatement_text, batch, k_expected)
      if picks is None:
        logger.warning(
          "business_type_ranked_pick_failed restatement=%r batch_index=%d",
          restatement_text,
          i // batch_size,
        )
        fallback = _fallback_ranked_business_types(restatement_text, all_business_types, 3)
        if fallback:
          logger.warning("business_type_selection_fallback=%s", fallback)
          return fallback
        raise RuntimeError("Failed to select ranked business_type indices.")
      for idx in picks:
        winners.append(batch[idx - 1])

    if not winners:
      fallback = _fallback_ranked_business_types(restatement_text, all_business_types, 3)
      if fallback:
        logger.warning("business_type_selection_fallback=%s", fallback)
        return fallback
      raise RuntimeError("No business_type candidates selected.")

    # Deduplicate while preserving order.
    reduced: List[str] = []
    seen = set()
    for bt in winners:
      if bt in seen:
        continue
      seen.add(bt)
      reduced.append(bt)

    if len(reduced) == 1:
      logger.warning("business_type_reduced_candidates=%s", reduced)
      return [reduced[0]]

    final_idx = _pick_index(restatement_text, reduced)
    if final_idx is None:
      final_idx = _pick_index(restatement_text, reduced)
    if final_idx is None:
      logger.warning(
        "business_type_final_pick_failed restatement=%r total=%d",
        restatement_text,
        len(reduced),
      )
      fallback = _fallback_ranked_business_types(restatement_text, reduced or all_business_types, 1)
      if fallback:
        logger.warning("business_type_selection_fallback=%s", fallback)
        return fallback
      raise RuntimeError("Failed to select final business_type index.")

    logger.warning("business_type_reduced_candidates=%s", reduced)
    logger.warning(
      "business_type_final_pick index=%d value=%r",
      final_idx,
      reduced[final_idx - 1],
    )
    return [reduced[final_idx - 1]]
  except RuntimeError:
    raise
  except Exception:
    return []


def _normalize_business_type_from_candidates(
  raw_value: Any, candidates: List[str]
) -> Any:
  """
  Normalize a business_type value to the closest candidate label (case-insensitive).
  Falls back to the raw value if no candidates are available.
  """
  raw = str(raw_value or "").strip()
  if not raw or not candidates:
    return raw_value
  raw_lower = raw.lower()
  for candidate in candidates:
    if str(candidate or "").strip().lower() == raw_lower:
      return candidate
  try:
    from difflib import SequenceMatcher

    best = None
    best_score = 0.0
    for candidate in candidates:
      cand = str(candidate or "").strip()
      if not cand:
        continue
      score = SequenceMatcher(None, raw_lower, cand.lower()).ratio()
      if score > best_score:
        best_score = score
        best = cand
    return best if best else raw_value
  except Exception:
    return raw_value


def _compute_focus_and_confirm_question(
  *,
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  ops_confirmed: bool,
  market_confirmed: bool,
  people_confirmed: bool,
  financials_confirmed: bool,
) -> Tuple[str, Optional[str]]:
  del ops_json, market_json, people_json, financials_json
  # No realtime missing-fields gating; progression follows confirmations in order.
  if not ops_confirmed:
    return ("ops", None)
  if not market_confirmed:
    return ("market", None)
  if not people_confirmed:
    return ("people", None)
  if not financials_confirmed:
    return ("financials", None)
  return ("done", None)


def _next_focus(current: str) -> str:
  order = ["ops", "market", "people", "financials", "done"]
  cur = str(current or "").strip().lower()
  if cur not in order:
    return "ops"
  idx = order.index(cur)
  return order[min(idx + 1, len(order) - 1)]


def _start_instruction_for_focus(focus: str) -> str:
  focus_norm = str(focus or "").strip().lower()
  if focus_norm == "ops":
    return "Start the operational intake. Ask your first question."
  if focus_norm == "market":
    return "Start the target market intake. Ask exactly ONE question for the client to answer (do not bundle multiple questions)."
  if focus_norm == "people":
    return "Start the People & Capability intake. Ask your first question."
  if focus_norm == "financials":
    return "Start the financials intake. Ask your first question."
  return "Continue."


def _apply_scoped_patch(
  patch: Dict[str, Any],
  *,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  fulfillment_json: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
  """
  Apply patch keys scoped as "<group>.<field>" into the canonical section objects.
  """
  next_business = dict(business_facts)
  next_ops = dict(ops_json)
  next_market = dict(market_json)
  next_people = dict(people_json)
  next_financials = dict(financials_json)
  next_fulfillment = dict(fulfillment_json)

  for raw_key, value in (patch or {}).items():
    key = str(raw_key or "").strip()
    if key.count(".") != 1:
      continue
    group, field = key.split(".", 1)
    group = group.strip().lower()
    field = field.strip()
    if not group or not field:
      continue

    if group == "business":
      next_business[field] = value
      if field == "address":
        # If the canonical address string changes via chat-driven patch, we do not
        # have reliable structured parts (street/city/state/zip/country). Clear
        # parts so the UI can prompt the client to re-select a full address from
        # suggestions before final submit.
        for part_key in (
          "address_street",
          "address_city",
          "address_state",
          "address_zip",
          "address_country",
        ):
          next_business[part_key] = None
    elif group == "ops":
      next_ops[field] = value
    elif group == "market":
      next_market[field] = value
    elif group == "people":
      next_people[field] = value
    elif group == "financials":
      next_financials[field] = value
    elif group == "fulfillment":
      next_fulfillment[field] = value

  return next_business, next_ops, next_market, next_people, next_financials, next_fulfillment


def _fetch_target_market_mapping_rows(conn) -> List[Dict[str, Any]]:
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      "SELECT acs_code, description, segment, min_value, max_value FROM target_market_mapping"
    )
    rows = cur.fetchall() or []
  finally:
    try:
      cur.close()
    except Exception:
      pass

  def _parse_nullable_float(value: Any) -> Any:
    if value is None or value == "":
      return None
    try:
      return float(value)
    except Exception:
      return None

  mapping_rows: List[Dict[str, Any]] = []
  for r in rows:
    if not isinstance(r, dict):
      continue
    mapping_rows.append(
      {
        "acs_code": str(r.get("acs_code") or "").strip(),
        "description": str(r.get("description") or "").strip(),
        "segment": str(r.get("segment") or "").strip(),
        "min_value": _parse_nullable_float(r.get("min_value")),
        "max_value": _parse_nullable_float(r.get("max_value")),
      }
    )

  allowed_segments = {
    "Gender & Age",
    "Income",
    "Education",
    "Household Structure",
    "Housing Economics",
    "Employment",
  }

  cleaned: List[Dict[str, Any]] = []
  for r in mapping_rows:
    if not r["acs_code"] or not r["segment"]:
      continue
    if r["segment"] not in allowed_segments:
      continue
    # Ignore "Total households" rows for household structure selection.
    if r["segment"] == "Household Structure":
      desc_norm = " ".join(str(r["description"]).split()).strip().lower()
      if desc_norm == "total households":
        continue
    cleaned.append(r)
  if not cleaned:
    raise RuntimeError(
      "target_market_mapping table is empty; load it before running the target market consult."
    )
  return cleaned


def post_intake_consult_session_handler(*, app, request):
  """
  Create a new durable unified intake draft and return {draft_id, client_id}.
  """
  if request.method == "OPTIONS":
    return ("", 204)

  try:
    from intake_submission import generate_client_id, get_mysql_connection  # type: ignore
    from client_intake_and_finmo.intake_consult_draft import create_draft  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import intake consult draft helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  client_id = generate_client_id()
  conn = get_mysql_connection()
  try:
    draft = create_draft(conn, client_id=client_id)
    return jsonify(
      {
        "status": "ok",
        "draft_id": draft.get("draft_id"),
        "client_id": draft.get("client_id"),
      }
    )
  finally:
    try:
      conn.close()
    except Exception:
      pass


_bind_post_intake_runtime_dependencies()
def get_intake_consult_draft_handler(*, app, request):
  if request.method == "OPTIONS":
    return ("", 204)

  draft_id = request.args.get("draft_id")
  if not draft_id or not str(draft_id).strip():
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
      400,
    )

  try:
    from intake_submission import get_mysql_connection  # type: ignore
    from client_intake_and_finmo.intake_consult_draft import get_draft  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import MySQL helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  conn = get_mysql_connection()
  try:
    try:
      draft = get_draft(conn, draft_id=str(draft_id).strip())
    except Exception as exc:
      return (jsonify({"error": "not_found", "detail": str(exc)}), 404)

    return jsonify(
      {
        "status": "ok",
        "draft_id": draft.get("draft_id"),
        "client_id": draft.get("client_id"),
        "draft_status": draft.get("status"),
        "active_focus": draft.get("active_focus"),
        "ops_confirmed": bool(draft.get("ops_confirmed")),
        "market_confirmed": bool(draft.get("market_confirmed")),
        "people_confirmed": bool(draft.get("people_confirmed")),
        "financials_confirmed": bool(draft.get("financials_confirmed")),
        "business_name": draft.get("business_name"),
        "business_address": draft.get("business_address"),
        "address_street": draft.get("address_street"),
        "address_city": draft.get("address_city"),
        "address_state": draft.get("address_state"),
        "address_zip": draft.get("address_zip"),
        "address_country": draft.get("address_country"),
        "business_start_date": draft.get("business_start_date"),
        "messages_json": draft.get("messages_json"),
        "operating_model_json": draft.get("operating_model_json"),
        "target_market_json": draft.get("target_market_json"),
        "people_json": draft.get("people_json"),
        "financials_json": draft.get("financials_json"),
        "financials_year1_json": draft.get("financials_year1_json"),
        "fulfillment_json": draft.get("fulfillment_json"),
        "model_input_json": draft.get("model_input_json"),
        "finmo_json": draft.get("finmo_json"),
        "planning_context_summary_json": draft.get("planning_context_summary_json"),
        "planning_run_json": draft.get("planning_run_json"),
        "planning_runtime_json": draft.get("planning_runtime_json"),
        "numeric_solver_feedback_json": draft.get("numeric_solver_feedback_json"),
        "planning_run_id": draft.get("planning_run_id"),
        "planning_run_status": draft.get("planning_run_status"),
        "planning_stage": draft.get("planning_stage"),
        "planning_status": draft.get("planning_status"),
        "planning_last_review_iteration": draft.get("planning_last_review_iteration"),
        "planning_current_retry_count": draft.get("planning_current_retry_count"),
        "planning_current_cycle": draft.get("planning_current_cycle"),
        "planning_detected_issue_count": draft.get("planning_detected_issue_count"),
        "planning_remaining_issue_count": draft.get("planning_remaining_issue_count"),
        "planning_resolved_issue_count": draft.get("planning_resolved_issue_count"),
        "planning_tolerated_issue_count": draft.get("planning_tolerated_issue_count"),
        "planning_iteration_pending_issue_count": draft.get("planning_iteration_pending_issue_count"),
        "planning_latest_checkpoint_id": draft.get("planning_latest_checkpoint_id"),
        "planning_resume_from_checkpoint_id": draft.get("planning_resume_from_checkpoint_id"),
        "planning_requested_action": draft.get("planning_requested_action"),
        "planning_requested_action_at": draft.get("planning_requested_action_at"),
        "planning_requested_action_reason": draft.get("planning_requested_action_reason"),
        "planning_latest_controller_status": draft.get("planning_latest_controller_status"),
        "planning_failure_reason": draft.get("planning_failure_reason"),
        "planning_resume_count": draft.get("planning_resume_count"),
        "planning_source_run_id": draft.get("planning_source_run_id"),
        "planning_superseded_by_run_id": draft.get("planning_superseded_by_run_id"),
        "planning_run_started_at": draft.get("planning_run_started_at"),
        "planning_last_heartbeat_at": draft.get("planning_last_heartbeat_at"),
        "planning_paused_at": draft.get("planning_paused_at"),
        "planning_stopped_at": draft.get("planning_stopped_at"),
        "planning_run_completed_at": draft.get("planning_run_completed_at"),
      }
    )
  finally:
    try:
      conn.close()
    except Exception:
      pass
def _run_unified_post_grid_system_run(
  *,
  conn,
  draft_id: str,
  planning_run_id: str,
  business_facts: Dict[str, Any],
  planning_context_summary_json: Dict[str, Any],
  ops_json: Dict[str, Any],
  target_market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  fulfillment_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  planning_mode: str,
  planning_mode_reason: str,
  planning_result: Dict[str, Any],
  grid_application_summary: Dict[str, Any],
  catalog_source_model_input_json: Dict[str, Any],
  applied_model_input_json: Dict[str, Any],
  applied_finmo_json: Dict[str, Any],
  stage_ramp_contract: Optional[Dict[str, Any]] = None,
  payroll_headcount: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  _bind_post_intake_runtime_dependencies()
  # Phase 2.5: the target-seeking orchestrator is the authoritative top-
  # level convergence path. The existing scipy/issue-code solver in
  # numeric_solver.py and post_intake_convergence/runtime.py is repositioned
  # as an inner tool the outer loop calls when single-driver bisection
  # cannot close a numeric gap. The orchestrator's signature mirrors
  # run_unified_post_grid_system_run so this swap is a drop-in.
  from client_intake_and_finmo.post_intake_solver import (  # type: ignore
    run_target_seeking_orchestrated_system_run,
  )
  result = run_target_seeking_orchestrated_system_run(
    conn=conn,
    draft_id=draft_id,
    planning_run_id=planning_run_id,
    business_facts=business_facts,
    planning_context_summary_json=planning_context_summary_json,
    ops_json=ops_json,
    target_market_json=target_market_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    fulfillment_json=fulfillment_json,
    marketing_model_json=marketing_model_json,
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    planning_result=planning_result,
    grid_application_summary=grid_application_summary,
    catalog_source_model_input_json=catalog_source_model_input_json,
    applied_model_input_json=applied_model_input_json,
    applied_finmo_json=applied_finmo_json,
    stage_ramp_contract=stage_ramp_contract,
    payroll_headcount=copy.deepcopy(payroll_headcount or {}),
  )
  # Phase 3.8: persist plan_confidence and cascade diagnostics to the run
  # report. UPDATE planning_runs row, and emit one
  # `adaptation_cascade_completed` event per cascade-firing run (Tier 0
  # high_no_adaptation skips the event INSERT).
  try:
    from client_intake_and_finmo.intake_consult_draft import (  # type: ignore
      persist_adaptation_cascade_outcome,
    )
    persist_adaptation_cascade_outcome(
      conn,
      draft_id=str(draft_id or "").strip(),
      planning_run_id=str(planning_run_id or "").strip(),
      plan_confidence=(result.get("plan_confidence") if isinstance(result, dict) else None),
      cascade_diagnostics=(
        result.get("adaptation_cascade_diagnostics") if isinstance(result, dict) else None
      ),
    )
  except Exception as exc:
    logger.warning("persist_adaptation_cascade_outcome_failed: %s", exc)
  return result
def _run_planning_system_for_draft_unified(
  *,
  conn,
  draft_id: str,
  lifecycle_mode: str = "start",
  planning_run_id: Optional[str] = None,
) -> Dict[str, Any]:
  _bind_post_intake_runtime_dependencies()

  # Phase 9 P3.32 K11 L-4 — open the handler trace run at the TRUE entry,
  # BEFORE the initial-grid build (which runs payroll Handler C). draft_id
  # keys the run; the planning_run_id is created inside the grid build and
  # stamped immediately after via set_planning_run_id. This is the correct
  # placement: the orchestrator runs only after the grid is built, so a
  # begin there would miss Handler C entirely (and clear its buffer).
  try:
    from client_intake_and_finmo.post_intake_handler_traces import (  # type: ignore
      begin_trace_run as _begin_trace_run,
    )
    _begin_trace_run(str(draft_id).strip(), planning_run_id or "")
  except Exception:
    pass

  initial_grid_state = prepare_initial_grid_for_draft(
    conn=conn,
    draft_id=str(draft_id).strip(),
    lifecycle_mode=lifecycle_mode,
    planning_run_id=planning_run_id,
    build_shared_context=build_shared_context,
    get_draft=get_draft,
    begin_planning_run=begin_planning_run,
    persist_post_intake_execution_state=persist_post_intake_execution_state,
    maybe_interrupt_planning_run=_maybe_interrupt_planning_run,
    parse_json_dict=_parse_json_dict,
    reset_openai_call_telemetry=_reset_openai_call_telemetry,
    build_planning_run_payload=_build_planning_run_payload,
    extract_numeric_solver_feedback_for_persistence=_extract_numeric_solver_feedback_for_persistence,
    build_planning_context_summary_payload=_build_planning_context_summary_payload,
    year1_drivers_conflict=_year1_drivers_conflict,
    compute_marketing_model_json=_compute_marketing_model_json,
    # Module 5 Task 5.1 — GPT call DELETED. The deterministic NAICS-cascade
    # function replaces it. The dependency-injection key keeps the
    # legacy name so post_intake_initial_grid/runner.py does not need a
    # signature change in this commit.
    estimate_maintenance_capex_percent_with_gpt=_derive_maintenance_capex_percent_from_naics,
    safe_float=_safe_float,
    estimate_r_and_d_applicability_with_gpt=_estimate_r_and_d_applicability_with_gpt,
    r_and_d_policy_from_model_input=_r_and_d_policy_from_model_input,
    assert_r_and_d_applicability_policy_applied=_assert_r_and_d_applicability_policy_applied,
    estimate_balance_sheet_contextual_seed_with_gpt=_estimate_balance_sheet_contextual_seed_with_gpt,
    estimate_stage_ramp_contract_with_gpt=_stage_ramp_contract_python_first_with_handler,
  )

  # Phase 9 P3.32 K11 L-4 — stamp the real planning_run_id now that the
  # grid build created it, so post-grid traces (orchestrator, H2) carry
  # it. Early Handler C traces stay keyed by draft_id (the run identifier).
  try:
    from client_intake_and_finmo.post_intake_handler_traces import (  # type: ignore
      set_planning_run_id as _set_planning_run_id,
    )
    _set_planning_run_id(str(initial_grid_state.get("planning_run_id") or "").strip())
  except Exception:
    pass

  return _run_unified_post_grid_system_run(
    conn=conn,
    draft_id=str(draft_id).strip(),
    planning_run_id=str(initial_grid_state.get("planning_run_id") or "").strip(),
    business_facts=copy.deepcopy(initial_grid_state.get("business_facts") or {}),
    planning_context_summary_json=copy.deepcopy(initial_grid_state.get("planning_context_summary_json") or {}),
    ops_json=copy.deepcopy(initial_grid_state.get("ops_json") or {}),
    target_market_json=copy.deepcopy(initial_grid_state.get("target_market_json") or {}),
    people_json=copy.deepcopy(initial_grid_state.get("people_json") or {}),
    financials_json=copy.deepcopy(initial_grid_state.get("financials_json") or {}),
    financials_year1_json=copy.deepcopy(initial_grid_state.get("financials_year1_json") or {}),
    fulfillment_json=copy.deepcopy(initial_grid_state.get("fulfillment_json") or {}),
    marketing_model_json=copy.deepcopy(initial_grid_state.get("marketing_model_json") or {}),
    planning_mode=str(initial_grid_state.get("planning_mode") or "").strip(),
    planning_mode_reason=str(initial_grid_state.get("planning_mode_reason") or "").strip(),
    planning_result=copy.deepcopy(initial_grid_state.get("planning_result") or {}),
    grid_application_summary=copy.deepcopy(initial_grid_state.get("grid_application_summary") or {}),
    catalog_source_model_input_json=copy.deepcopy(initial_grid_state.get("catalog_source_model_input_json") or {}),
    applied_model_input_json=copy.deepcopy(initial_grid_state.get("applied_model_input_json") or {}),
    applied_finmo_json=copy.deepcopy(initial_grid_state.get("applied_finmo_json") or {}),
    stage_ramp_contract=copy.deepcopy(initial_grid_state.get("stage_ramp_contract") or {}),
    payroll_headcount=copy.deepcopy(initial_grid_state.get("payroll_headcount") or {}),
  )
def _run_planning_system_for_draft(
  *,
  conn,
  draft_id: str,
  lifecycle_mode: str = "start",
  planning_run_id: Optional[str] = None,
) -> Dict[str, Any]:
  return _run_planning_system_for_draft_unified(
    conn=conn,
    draft_id=draft_id,
    lifecycle_mode=lifecycle_mode,
    planning_run_id=planning_run_id,
  )


def _targeted_process_runtime_context_from_rows(
  *,
  draft: Dict[str, Any],
  planning_run: Optional[Dict[str, Any]] = None,
  checkpoint: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  draft_row = draft if isinstance(draft, dict) else {}
  run_row = planning_run if isinstance(planning_run, dict) else {}
  checkpoint_row = checkpoint if isinstance(checkpoint, dict) else {}

  def _json_payload(name: str) -> Dict[str, Any]:
    for row in (checkpoint_row, run_row, draft_row):
      value = _parse_json_dict(row.get(name)) if isinstance(row, dict) else {}
      if value:
        return copy.deepcopy(value)
    return {}

  ops_json = _json_payload("operating_model_json")
  target_market_json = _json_payload("target_market_json")
  people_json = _json_payload("people_json")
  financials_json = _json_payload("financials_json")
  financials_year1_json = _json_payload("financials_year1_json")
  fulfillment_json = _json_payload("fulfillment_json")
  marketing_model_json = _json_payload("marketing_model_json")
  planning_context_summary_json = _json_payload("planning_context_summary_json")
  planning_run_json = _json_payload("planning_run_json")
  model_input_json = _json_payload("model_input_json")
  finmo_json = _json_payload("finmo_json")
  payroll_headcount = _json_payload("payroll_headcount")
  debt_schedule = _json_payload("debt_schedule")
  business_facts = {
    "draft_id": str(draft_row.get("draft_id") or run_row.get("draft_id") or "").strip(),
    "client_id": str(draft_row.get("client_id") or run_row.get("client_id") or "").strip(),
    "business_name": draft_row.get("business_name"),
    "name": draft_row.get("business_name"),
    "business_address": draft_row.get("business_address"),
    "business_start_date": draft_row.get("business_start_date"),
    "address_street": draft_row.get("address_street"),
    "address_city": draft_row.get("address_city"),
    "address_state": draft_row.get("address_state"),
    "address_zip": draft_row.get("address_zip"),
    "address_country": draft_row.get("address_country"),
  }
  context: Dict[str, Any] = {
    "business_facts": business_facts,
    "business_type": str((ops_json or {}).get("business_type") or "").strip(),
    "business_naics": str(
      (people_json or {}).get("business_naics_6")
      or (ops_json or {}).get("naics_code")
      or (ops_json or {}).get("business_naics")
      or ""
    ).strip(),
    "operating_model_json": ops_json,
    "ops_json": ops_json,
    "ops_context": ops_json,
    "target_market_json": target_market_json,
    "market_json": target_market_json,
    "market_context": target_market_json,
    "people_json": people_json,
    "people_context": people_json,
    "financials_json": financials_json,
    "financials_context": financials_json,
    "financials_year1_json": financials_year1_json,
    "financials_year1_context": financials_year1_json,
    "fulfillment_json": fulfillment_json,
    "marketing_model_json": marketing_model_json,
    "marketing_context": marketing_model_json,
    "planning_context_summary_json": planning_context_summary_json,
    "planning_run_json": planning_run_json,
    "model_input_json": model_input_json,
    "finmo_json": finmo_json,
    "payroll_headcount": payroll_headcount,
    "debt_schedule": debt_schedule,
  }
  for key in [
    "stage_ramp_contract",
    "planning_mode",
    "planning_mode_reason",
    "grid_application_summary",
    "controller_resolution_state",
    "issue_repair_scope",
    "unified_convergence_context",
    "unified_convergence_decision",
    "unified_convergence_result",
    "cash_strategy_review_context",
    "cash_strategy_review_decision",
    "cash_strategy_second_pass_plan",
    "cash_strategy_second_pass_result",
    "cash_strategy_effect_summary",
    "final_hard_gate_assessment",
  ]:
    value = planning_run_json.get(key) if isinstance(planning_run_json, dict) else None
    if value is not None:
      context[key] = copy.deepcopy(value)
  if not context.get("stage_ramp_contract"):
    context["stage_ramp_contract"] = _json_payload("stage_ramp_contract")
  return context










def post_intake_consult_system_run_handler(*, app, request):
  if request.method == "OPTIONS":
    return ("", 204)

  # The OpenAI deadline is a per-run/cycle guard. Clear any stale value from a
  # prior failed request before this run starts so one failure cannot poison the
  # next system run.
  _set_active_openai_deadline(None)

  payload = request.get_json(silent=True) or {}
  draft_id = str(payload.get("draft_id") or "").strip()
  lifecycle_mode = str(payload.get("lifecycle_mode") or "start").strip().lower() or "start"
  planning_run_id = str(payload.get("planning_run_id") or "").strip()
  if not draft_id:
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
      400,
    )

  try:
    from intake_submission import get_mysql_connection  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import MySQL helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  conn = get_mysql_connection()
  try:
    try:
      result = _run_planning_system_for_draft(
        conn=conn,
        draft_id=draft_id,
        lifecycle_mode=lifecycle_mode,
        planning_run_id=planning_run_id or None,
      )
      # P3.40 Contract 4 Commit 3 -- consumer-side boundary gate.
      # FIRST consumer access of `result`. Validates the 20-field
      # solver-output dict before any acceptance-gate processing or
      # workbook-export trigger. Placed INSIDE this try block so a
      # ContractViolation raised by the gate lands in the existing
      # `except Exception as exc:` branch below (ContractViolation
      # is Exception subclass, not RuntimeError -- skips the
      # RuntimeError branch). Surfaces as a structured 500 with
      # detail=str(exc) carrying SOLVER_OUTPUT_STAGE_LABEL + field
      # path per trace Div-6.
      from client_intake_and_finmo.post_intake_contracts.enforcement import (  # type: ignore  # noqa: E501
        SIDE_CONSUMER as _SO_SIDE_CONSUMER,
        validate_solver_output_at_boundary,
      )
      validate_solver_output_at_boundary(
        result, side=_SO_SIDE_CONSUMER,
      )
    except PlanningRunLifecycleInterrupt as exc:
      run_row = get_planning_run(conn, planning_run_id=exc.planning_run_id)
      checkpoint = get_latest_planning_run_checkpoint(conn, planning_run_id=exc.planning_run_id)
      return jsonify(
        {
          "status": "ok",
          "draft_id": draft_id,
          "planning_run_id": exc.planning_run_id,
          "action": f"system_run_{exc.action}d",
          "assistant_message": f"System run {exc.action}d.",
          "detail": exc.detail,
          "planning_run": _serialize_debug_draft_row(run_row or {}),
          "latest_checkpoint": _serialize_debug_draft_row(checkpoint or {}),
        }
      )
    except RuntimeError as exc:
      detail = str(exc).strip() or "system_run_failed"
      if detail == "draft_not_complete":
        return (jsonify({"error": "conflict", "detail": detail}), 409)
      if detail.startswith("planning_run_already_active:"):
        return (
          jsonify(
            {
              "error": "conflict",
              "detail": "planning_run_already_active",
              "planning_run_id": detail.split(":", 1)[1],
            }
          ),
          409,
        )
      if detail == "planning_run_resume_target_not_found":
        return (jsonify({"error": "not_found", "detail": detail}), 404)
      active_run = get_planning_run(
        conn,
        planning_run_id=planning_run_id or None,
        draft_id=draft_id,
        active_only=True,
      )
      if isinstance(active_run, dict):
        clear_planning_run_action(
          conn,
          planning_run_id=str(active_run.get("planning_run_id") or "").strip(),
          run_status="failed",
          failure_reason=detail,
        )
      failure_diagnostics_payload = (
        copy.deepcopy(getattr(exc, "diagnostics", {}))
        if isinstance(getattr(exc, "diagnostics", {}), dict)
        else None
      )
      # FailFastError carries `details` (per-violation diagnostics) on
      # attribute named `details`; preserve those so the API caller and
      # the persisted planning_run_json both see them without needing to
      # re-run the system with ad-hoc instrumentation.
      failure_details_payload = (
        copy.deepcopy(getattr(exc, "details", {}))
        if isinstance(getattr(exc, "details", {}), dict)
        else None
      )
      _persist_failed_system_run_snapshot(
        conn=conn,
        draft_id=draft_id,
        detail=detail,
        active_run=active_run if isinstance(active_run, dict) else None,
        failure_diagnostics=failure_diagnostics_payload,
        failure_details=failure_details_payload,
      )
      app.logger.exception(
        "System run failed for draft %s: %s | details=%s",
        draft_id, detail, failure_details_payload,
      )
      # Phase 9 P3.10 Commit 5 Part B — email-on-failure + FAILED
      # diagnostic SQL row. The email helper is never-raises by
      # contract; if SMTP fails, we log the failure and continue with
      # the HTTP 500 response so the caller still receives the
      # diagnostic body.
      email_outcome = _dispatch_post_intake_failure_alert(
        app=app,
        conn=conn,
        draft_id=draft_id,
        active_run=active_run if isinstance(active_run, dict) else None,
        exception=exc,
        failure_detail=detail,
        failure_details_payload=failure_details_payload,
        failure_diagnostics_payload=failure_diagnostics_payload,
      )
      return (
        jsonify({
          "error": "system_run_failed",
          "detail": detail,
          "diagnostics": failure_diagnostics_payload or {},
          "details": failure_details_payload or {},
          "failure_email": email_outcome,
        }),
        500,
      )
    except Exception as exc:
      active_run = get_planning_run(
        conn,
        planning_run_id=planning_run_id or None,
        draft_id=draft_id,
        active_only=True,
      )
      if isinstance(active_run, dict):
        clear_planning_run_action(
          conn,
          planning_run_id=str(active_run.get("planning_run_id") or "").strip(),
          run_status="failed",
          failure_reason=str(exc),
        )
      _persist_failed_system_run_snapshot(
        conn=conn,
        draft_id=draft_id,
        detail=str(exc),
        active_run=active_run if isinstance(active_run, dict) else None,
      )
      app.logger.exception("System run failed for draft %s", draft_id)
      email_outcome = _dispatch_post_intake_failure_alert(
        app=app,
        conn=conn,
        draft_id=draft_id,
        active_run=active_run if isinstance(active_run, dict) else None,
        exception=exc,
        failure_detail=str(exc),
        failure_details_payload=None,
        failure_diagnostics_payload=None,
      )
      return (
        jsonify({
          "error": "system_run_failed",
          "detail": str(exc),
          "failure_email": email_outcome,
        }),
        500,
      )

    planning_run_json = (
      result.get("planning_run_json")
      if isinstance(result.get("planning_run_json"), dict)
      else {}
    )
    numeric_solver_feedback_json = (
      result.get("numeric_solver_feedback_json")
      if isinstance(result.get("numeric_solver_feedback_json"), dict)
      else {}
    )
    planning_runtime_json = (
      result.get("planning_runtime_json")
      if isinstance(result.get("planning_runtime_json"), dict)
      else {}
    )
    planning_context_summary_json = (
      result.get("planning_context_summary_json")
      if isinstance(result.get("planning_context_summary_json"), dict)
      else {}
    )
    result_draft_id = str(result.get("draft_id") or draft_id).strip()

    # Phase 8 acceptance gate. Exit code 0 from the orchestrator no
    # longer means "passed." The gate verifies new-architecture criteria
    # (stage reached finalize, cascade tier landed, realism gate
    # provenance, solver_target_assertion clean, workbook integrity)
    # and is the only authority on whether this run actually succeeded.
    # A failed verdict short-circuits the workbook export and returns
    # HTTP 500 with the structured diagnostic so the caller sees exactly
    # which checks failed and the offending values.
    try:
      from client_intake_and_finmo.post_intake_acceptance import verify_run_acceptance  # type: ignore
      acceptance_planning_run_id = (
        str(planning_run_json.get("planning_run_id") or "").strip()
        if isinstance(planning_run_json, dict)
        else ""
      ) or planning_run_id
      acceptance_verdict = verify_run_acceptance(
        conn,
        draft_id=result_draft_id,
        planning_run_id=acceptance_planning_run_id or None,
      )
    except Exception as exc:
      app.logger.exception(
        "Acceptance gate raised for draft %s: %s", result_draft_id, exc
      )
      return (
        jsonify(
          {
            "error": "acceptance_gate_internal_error",
            "detail": str(exc),
            "draft_id": result_draft_id,
          }
        ),
        500,
      )
    # ═══ THE RESTRUCTURE STAGE (additive; fires ONLY on NON-VIABLE) ═══
    # The full existing process ran unchanged above. A VIABLE verdict
    # never enters this block — nothing changes for viable businesses.
    # On NON-VIABLE, the EXECUTIVE redesigns the whole business (design
    # seat: headcount, space, mix, pricing, phasing — bounded ONLY by
    # the four reality constraints) and the SOLVER (this entire
    # pipeline, re-run with the design as the authoritative maturation
    # targets) crunches it and reports the gap. They loop until viable
    # or the executive concludes no REAL redesign reaches viability.
    # Either outcome is final and honest; the restructured forecast, when
    # viable, simply IS the forecast.
    _rs_attempt_workbook_path: str = ""
    try:
      _rs_iterations: List[Dict[str, Any]] = []
      _rs_search: Optional[Dict[str, Any]] = None
      if not bool(acceptance_verdict.get("passed")):
        from client_intake_and_finmo.post_intake_restructure import (  # type: ignore
          build_solver_gap_report,
        )
        from client_intake_and_finmo.post_intake_restructure.designer import (  # type: ignore
          stated_owner_annual_wage as _rs_owner_wage,
        )
        from client_intake_and_finmo.post_intake_restructure.constraint_author import (  # type: ignore
          gpt_author_restructure_bounds_once,
          validate_restructure_bounds,
        )
        from client_intake_and_finmo.post_intake_restructure.searcher import (  # type: ignore
          candidate_to_directive,
        )
        from client_intake_and_finmo.post_intake_restructure.joint_solver import (  # type: ignore
          run_restructure_joint_solve,
        )
        from client_intake_and_finmo.post_intake_restructure.solution_review import (  # type: ignore
          apply_review_tightening,
          gpt_review_solution_once,
        )
        from client_intake_and_finmo.post_intake_amalgamated.mirror import (  # type: ignore
          build_operating_model_digest as _rs_digest,
        )
        from client_intake_and_finmo.post_intake_restructure.registry import (  # type: ignore
          set_active_directive as _rs_set_active,
          clear_active_directive as _rs_clear_active,
        )

        def _rs_draft_json(column: str) -> Dict[str, Any]:
          _cur = conn.cursor(dictionary=True)
          try:
            _cur.execute(
              f"SELECT {column} FROM intake_consult_drafts WHERE draft_id=%s",
              (result_draft_id,),
            )
            _row = _cur.fetchone() or {}
            _raw = _row.get(column)
            return json.loads(_raw) if isinstance(_raw, str) and _raw.strip() else (
              _raw if isinstance(_raw, dict) else {}
            )
          finally:
            _cur.close()

        def _rs_persist_guidance(payload_json: Dict[str, Any]) -> None:
          _cur = conn.cursor()
          try:
            _cur.execute(
              "UPDATE intake_consult_drafts SET repair_guidance_json=%s WHERE draft_id=%s",
              (json.dumps(payload_json, ensure_ascii=False), result_draft_id),
            )
            conn.commit()
          finally:
            _cur.close()

        _rs_ops = _rs_draft_json("operating_model_json")
        _rs_people = _rs_draft_json("people_json")
        _rs_market = _rs_draft_json("target_market_json")
        _rs_marketing = _rs_draft_json("marketing_model_json")
        _rs_fin = _rs_draft_json("financials_json")
        _rs_compact = _rs_digest(_rs_ops, _rs_people, _rs_market, _rs_marketing)
        _rs_stated = {
          k: _rs_fin.get(k)
          for k in (
            "current_revenue", "current_cogs", "payroll_total_year1",
            "current_num_employees", "total_debt_outstanding",
            "cash_on_hand", "initial_equity", "initial_assets",
          )
          if _rs_fin.get(k) is not None
        }
        _rs_owner = _rs_owner_wage(_rs_people)

        def _rs_current_structure() -> Dict[str, Any]:
          _fj = _rs_draft_json("finmo_json")
          _mi = _rs_draft_json("model_input_json")
          _rows = {
            int(float(r.get("quarter_index") or 0)): r
            for r in (_fj.get("quarter_rows") or [])
            if isinstance(r, dict)
          }
          _q1 = _rows.get(1) or {}
          _prices = {}
          _line_drivers: Dict[str, Dict[str, float]] = {}
          for _r in ((_mi.get("sections") or {}).get("revenue") or []):
            if not isinstance(_r, dict):
              continue
            _drv = str(_r.get("driver") or "").strip()
            _vals = _r.get("values") or []
            _key = f"{_r.get('lob')}/{_r.get('product')}"
            if _drv == "Unit Price" and len(_vals) > 1 and _vals[1]:
              _prices[_key] = _vals[1]
            if _drv in ("Unit Price", "Capacity", "Utilization"):
              for _qi, _lbl in ((1, "q1"), (11, "q11")):
                try:
                  _line_drivers.setdefault(_key, {})[f"{_lbl}_{_drv}"] = float(_vals[_qi])
                except (TypeError, ValueError, IndexError):
                  pass
          # Per-line revenue (price x capacity x utilization) at Q1 and
          # the currently-planned Q11 — the mix picture the executive
          # reallocates (revenue_mix identifies lines by these names).
          _line_revenues: Dict[str, Dict[str, float]] = {}
          for _key, _dv in _line_drivers.items():
            _line_revenues[_key] = {
              _lbl: round(
                (_dv.get(f"{_lbl}_Unit Price") or 0.0)
                * (_dv.get(f"{_lbl}_Capacity") or 0.0)
                * (_dv.get(f"{_lbl}_Utilization") or 0.0),
                2,
              )
              for _lbl in ("q1", "q11")
            }
          return {
            "q1_revenue": _q1.get("revenue"),
            "q1_payroll": _q1.get("payroll"),
            "q1_rent": _q1.get("lease_rent"),
            "q1_unit_prices": _prices,
            "revenue_lines_quarterly": _line_revenues,
          }

        # ═══ RESTRUCTURE v2: bounds → whole-P&L search → review → real run ═══
        # 1. The EXECUTIVE authors the four reality constraints as BOUNDS.
        # 2. The SOLVER searches every configuration inside them (fast
        #    evaluator = the pipeline's own math + the gate's own checks).
        # 3. The EXECUTIVE reviews the found design (real business? may
        #    tighten caps once — the solver re-searches inside them).
        # 4. The REAL pipeline runs the design; the REAL acceptance gate
        #    issues the verdict. Two real runs max; the second folds the
        #    first's landed state back into the search.
        _rs_gap = build_solver_gap_report(
          acceptance_verdict=acceptance_verdict,
          finmo_json=_rs_draft_json("finmo_json"),
        )
        _rs_ops_json = _rs_ops
        _rs_naics = (
          "".join(ch for ch in str((_rs_ops_json or {}).get("business_naics_6") or "") if ch.isdigit())
          or None
        )
        _rs_planning_mode = str(
          (_rs_draft_json("planning_runtime_json") or {}).get("planning_mode") or ""
        ).strip() or None
        _rs_bounds_raw = gpt_author_restructure_bounds_once(
          compact=_rs_compact,
          stated_facts=_rs_stated,
          current_structure=_rs_current_structure(),
          failure_summary=_rs_gap,
        )
        _rs_design_prev: Optional[Dict[str, Any]] = None
        _rs_bounds: Optional[Dict[str, Any]] = None
        if not _rs_bounds_raw.get("ok"):
          _rs_iterations.append({"stage": "bounds", "error": _rs_bounds_raw.get("error")})
        else:
          _rs_bounds = validate_restructure_bounds(
            bounds=_rs_bounds_raw["bounds"], stated_owner_annual_wage=_rs_owner,
          )
          _rs_iterations.append({
            "stage": "bounds",
            "feasible_region_exists": _rs_bounds.get("feasible_region_exists"),
            "bounds": _rs_bounds,
            "gap_report_in": _rs_gap,
          })
        # THE JOINT SOLVE — GPT authored the bounds and target OUTSIDE
        # the loop; numeric_solver.solve_review_plan (the existing SciPy
        # joint optimizer) drives ALL levers simultaneously to the
        # viability target inside them. GPT reviews the solved result
        # OUTSIDE the loop; each rejection tightens bounds for a
        # re-solve (the solve is seconds). Exactly ONE real pipeline
        # run, only after approval.
        _rs_max_rounds = 4
        for _rs_i in range(1, _rs_max_rounds + 1):
          if not (_rs_bounds and _rs_bounds.get("feasible_region_exists")):
            # The executive concluded no REAL region exists — the
            # honest terminal answer (or the bounds call failed; the
            # pre-restructure verdict then stands untouched).
            break
          _rs_base_mi = _rs_draft_json("model_input_json")
          _rs_search = run_restructure_joint_solve(
            base_model_input=_rs_base_mi,
            bounds=_rs_bounds,
            business_naics_6=_rs_naics,
            ops_json=_rs_ops_json,
            financials_json=_rs_fin,
            planning_mode=_rs_planning_mode,
          )
          _rs_iterations.append({
            "stage": f"search_{_rs_i}",
            "found": _rs_search.get("found"),
            "evals": _rs_search.get("evals"),
            "trace": _rs_search.get("trace"),
            "candidate": _rs_search.get("candidate"),
            "landed": (_rs_search.get("score") or {}).get("landed"),
            # The LEAN-END solution (viability first reached, before the
            # refine-back walked toward as-stated) — audit signal for how
            # far minimal-change and lean-end diverge.
            "candidate_first_viable": _rs_search.get("candidate_first_viable"),
            "landed_first_viable": _rs_search.get("landed_first_viable"),
            "payroll_burden_factor": _rs_search.get("payroll_burden_factor"),
            "line_margins": _rs_search.get("line_margins"),
          })
          if not _rs_search.get("found"):
            # Honest exhaustion: no configuration inside the executive's
            # reality bounds is viable.
            break
          _rs_design = candidate_to_directive(
            _rs_search["candidate"], _rs_bounds, _rs_search["base_levels"],
            overall_rationale=str(_rs_bounds.get("overall_rationale") or ""),
            base_model_input=_rs_base_mi,
            line_margins=_rs_search.get("line_margins") or None,
            payroll_burden_factor=float(_rs_search.get("payroll_burden_factor") or 1.0),
          )
          _rs_review_raw = gpt_review_solution_once(
            compact=_rs_compact,
            stated_facts=_rs_stated,
            bounds_rationale={
              "overall_rationale": _rs_bounds.get("overall_rationale"),
              "reality_constraints": _rs_bounds.get("reality_constraints"),
            },
            design_directive=_rs_design,
            landed_projection=(_rs_search.get("score") or {}).get("landed") or {},
          )
          _rs_review = _rs_review_raw.get("review") if _rs_review_raw.get("ok") else None
          _rs_iterations.append({
            "stage": f"review_{_rs_i}",
            "review": _rs_review,
            "error": _rs_review_raw.get("error"),
          })
          if _rs_review is not None and not bool(_rs_review.get("approved")):
            if bool(_rs_review.get("no_realistic_design_exists")):
              # The reviewer's honest terminal: no tightening helps.
              break
            _rs_tightened = apply_review_tightening(_rs_bounds, _rs_review)
            if bool(_rs_review.get("revenue_story_required")):
              # "Cost compression alone is not a credible story" as a
              # BOUND: the team floor rises to stated wages, so the
              # re-solve must close the gap on the revenue side.
              try:
                _rs_stated_wages = float(_rs_fin.get("payroll_total_year1") or 0.0)
              except (TypeError, ValueError):
                _rs_stated_wages = 0.0
              _rs_team_b = _rs_tightened.get("team") or {}
              if _rs_stated_wages > float(_rs_team_b.get("min_annual_payroll") or 0.0):
                _rs_team_b["min_annual_payroll"] = _rs_stated_wages
                _rs_tightened["team"] = _rs_team_b
            if _rs_i < _rs_max_rounds and _rs_tightened != _rs_bounds:
              # The rejection BINDS the re-solve: tighter bounds.
              _rs_bounds = _rs_tightened
              continue
            # The rejection carried nothing new to bind, or rounds are
            # spent — the honest terminal.
            break
          _rs_design_prev = _rs_design
          # The ACTIVE directive rides the in-process registry (the
          # pipeline's stage persists rewrite repair_guidance_json and
          # would wipe a row-persisted directive before the grid loader
          # reads it); the row write below is the audit record.
          _rs_set_active(result_draft_id, _rs_design)
          _rs_persist_guidance({
            "restructure": {
              "active_directive": _rs_design,
              "iteration": _rs_i,
              "history": _rs_iterations,
            }
          })
          app.logger.info(
            "restructure_stage: v2 round %s re-running solver for draft %s",
            _rs_i, result_draft_id,
          )
          result = _run_planning_system_for_draft(
            conn=conn,
            draft_id=result_draft_id,
            lifecycle_mode=lifecycle_mode,
            planning_run_id=None,
          )
          planning_run_json = (
            result.get("planning_run_json")
            if isinstance(result.get("planning_run_json"), dict) else {}
          )
          numeric_solver_feedback_json = (
            result.get("numeric_solver_feedback_json")
            if isinstance(result.get("numeric_solver_feedback_json"), dict) else {}
          )
          planning_runtime_json = (
            result.get("planning_runtime_json")
            if isinstance(result.get("planning_runtime_json"), dict) else {}
          )
          planning_context_summary_json = (
            result.get("planning_context_summary_json")
            if isinstance(result.get("planning_context_summary_json"), dict) else {}
          )
          acceptance_planning_run_id = (
            str(planning_run_json.get("planning_run_id") or "").strip()
            or acceptance_planning_run_id
          )
          # The re-run creates a second planning-run row whose id becomes
          # authoritative in planning_run_json, while the unified-run tail
          # stamps plan_confidence / cascade tier onto the GRID-BUILD's
          # run id — the resolved row then reads NULLs and three purely
          # clerical checks fail. Re-stamp the RESOLVED row with the
          # run's own values before the verdict.
          try:
            from client_intake_and_finmo.intake_consult_draft import (  # type: ignore
              persist_adaptation_cascade_outcome as _rs_persist_cascade,
            )
            # The DRAFT ROW's planning_run_json carries the id the gate
            # will resolve (the run switches ids mid-flight; the result
            # payload can carry the superseded one).
            _rs_stamp_run_id = str(
              (_rs_draft_json("planning_run_json") or {}).get("planning_run_id") or ""
            ).strip() or (acceptance_planning_run_id or "")
            _rs_stamp_out = _rs_persist_cascade(
              conn,
              draft_id=result_draft_id,
              planning_run_id=_rs_stamp_run_id,
              plan_confidence=(
                result.get("plan_confidence") if isinstance(result, dict) else None
              ) or "restructured_viable_candidate",
              cascade_diagnostics=(
                result.get("adaptation_cascade_diagnostics")
                if isinstance(result, dict) else None
              ) or {"tier_landed": 0, "source": "restructure_rerun_restamp"},
            )
            acceptance_planning_run_id = _rs_stamp_run_id or acceptance_planning_run_id
            try:
              with open("C:/dev/business_plann_app/_rs_loader_trace.log", "a", encoding="utf-8") as _rs_fh:
                _rs_fh.write(f"draft={result_draft_id} restamp={_rs_stamp_out}\n")
            except Exception:
              pass
          except Exception as _rs_stamp_exc:  # noqa: BLE001
            app.logger.warning(
              "restructure_rerun_restamp_failed: %s", _rs_stamp_exc
            )
            try:
              import traceback as _rs_tb
              with open("C:/dev/business_plann_app/_rs_loader_trace.log", "a", encoding="utf-8") as _rs_fh:
                _rs_fh.write(
                  f"draft={result_draft_id} restamp_FAILED: {_rs_tb.format_exc()[-600:]}\n"
                )
            except Exception:
              pass
          acceptance_verdict = verify_run_acceptance(
            conn,
            draft_id=result_draft_id,
            planning_run_id=acceptance_planning_run_id or None,
          )
          _rs_iterations[-1]["verdict_after"] = {
            "passed": bool(acceptance_verdict.get("passed")),
            "failed_checks": list(acceptance_verdict.get("failed_checks") or []),
          }
          # ONE real run per approved design: the real gate's verdict IS
          # the verdict (re-searching the already-restructured state
          # would compound multipliers past the executive's caps).
          break
        _rs_clear_active(result_draft_id)
        # THE ATTEMPT IS AN ARTIFACT, pass OR fail. A failed restructure
        # reverts the DRAFT to the original business (nothing ships
        # unshipped designs) — but the ATTEMPTED design the solver
        # evaluated is materialized through the real FINMO math and
        # exported through the real workbook exporter, every time.
        # Silent revert-and-lose-the-attempt is not allowed; the failed
        # attempt IS the "what a viable version would need" record.
        try:
          if isinstance(_rs_search, dict) and (_rs_search.get("candidate") or {}):
            from client_intake_and_finmo.post_intake_restructure.searcher import (  # type: ignore  # noqa: E501
              apply_candidate as _rs_apply_candidate,
            )
            from client_intake_and_finmo.post_intake_restructure.fast_evaluator import (  # type: ignore  # noqa: E501
              build_fast_finmo as _rs_build_finmo,
            )
            from client_statements_output_excel.export_client_workbook import (  # type: ignore  # noqa: E501
              export_workbook_for_row as _rs_export_row,
            )
            _rs_attempt_mi = _rs_apply_candidate(
              _rs_base_mi, _rs_search["candidate"],
              line_margins=(_rs_search.get("line_margins") or None),
            )
            _rs_attempt_fm = _rs_build_finmo(_rs_attempt_mi)
            _rs_row_cur = conn.cursor(dictionary=True)
            try:
              _rs_row_cur.execute(
                "SELECT * FROM intake_consult_drafts WHERE draft_id=%s",
                (result_draft_id,),
              )
              _rs_full_row = dict(_rs_row_cur.fetchone() or {})
            finally:
              _rs_row_cur.close()
            _rs_full_row["model_input_json"] = json.dumps(
              _rs_attempt_mi, ensure_ascii=False, default=str
            )
            _rs_full_row["finmo_json"] = json.dumps(
              _rs_attempt_fm, ensure_ascii=False, default=str
            )
            _rs_outcome_tag = (
              "RESTRUCTURE ATTEMPT - viable candidate"
              if _rs_search.get("found")
              else "RESTRUCTURE ATTEMPT - no viable config found"
            )
            _rs_full_row["business_name"] = (
              f"{str(_rs_full_row.get('business_name') or 'Business')} ({_rs_outcome_tag})"
            )
            _rs_attempt_workbook_path = str(
              _rs_export_row(_rs_full_row, run_diagnostics=None)
            )
            try:
              with open("C:/dev/business_plann_app/_rs_loader_trace.log", "a", encoding="utf-8") as _rs_fh:
                _rs_fh.write(
                  f"draft={result_draft_id} attempt_workbook={_rs_attempt_workbook_path}\n"
                )
            except Exception:
              pass
        except Exception as _rs_wb_exc:  # noqa: BLE001 — artifact export must not kill the run
          app.logger.warning(
            "restructure_attempt_workbook_failed for draft %s: %s",
            result_draft_id, _rs_wb_exc,
          )
        if _rs_iterations:
          _rs_persist_guidance({
            "restructure": {
              "active_directive": _rs_design_prev,
              "final_passed": bool(acceptance_verdict.get("passed")),
              "attempt_workbook_path": _rs_attempt_workbook_path or None,
              "history": _rs_iterations,
            }
          })
    except Exception as _rs_exc:  # noqa: BLE001 — the pre-restructure verdict stands
      app.logger.exception(
        "restructure_stage failed for draft %s: %s", result_draft_id, _rs_exc
      )
      try:
        from client_intake_and_finmo.post_intake_restructure.registry import (  # type: ignore
          clear_active_directive as _rs_clear_active_fallback,
        )
        _rs_clear_active_fallback(result_draft_id)
      except Exception:
        pass

    # Phase 9 P3.9 -- diagnostic persistence, workbook export, and
    # auto-email run for EVERY planning run (success or failure).
    # Trace each step into a file so failures surface visibly rather
    # than getting swallowed by Flask's logger configuration.
    def _p3_9_trace(msg: str) -> None:
      try:
        from pathlib import Path as _Path
        from datetime import datetime as _dt
        _Path("/tmp/p3_9_handler_trace.log").parent.mkdir(parents=True, exist_ok=True)
        with open("/tmp/p3_9_handler_trace.log", "a", encoding="utf-8") as _fh:
          _fh.write(f"[{_dt.utcnow().isoformat()}Z] [{result_draft_id}] {msg}\n")
      except Exception:
        pass

    _p3_9_trace("entered_post_acceptance_block")
    diagnostic_payload: Dict[str, Any] = {}
    diagnostic_persisted: bool = False
    client_workbook_path: str = ""
    workbook_export_error: Optional[str] = None
    email_outcome: Dict[str, Any] = {"sent": False, "reason": "not_attempted"}
    try:
      from client_intake_and_finmo.post_intake_run_diagnostics import (  # type: ignore
        build_run_diagnostics_payload,
        persist_run_diagnostics,
      )
      from client_intake_and_finmo.workbook_email import (  # type: ignore
        send_workbook_alert,
        build_run_email_body,
      )

      # Pull the draft row's relevant JSON blobs and ops/financials for
      # the diagnostic builder. Tolerate missing fields -- the builder
      # is defensive.
      try:
        draft_row_for_diag = _select_consult_row_by_draft_id(  # type: ignore[name-defined]
          conn, result_draft_id,
        ) if "_select_consult_row_by_draft_id" in globals() else None
      except Exception:
        draft_row_for_diag = None
      if draft_row_for_diag is None:
        try:
          cur_diag = conn.cursor(dictionary=True)
          cur_diag.execute(
            "SELECT draft_id, business_name, business_start_date, "
            "planning_run_id, planning_run_json, realism_memo_json, "
            "model_input_json, operating_model_json, financials_json "
            "FROM intake_consult_drafts WHERE draft_id = %s LIMIT 1",
            (result_draft_id,),
          )
          draft_row_for_diag = cur_diag.fetchone() or {}
          try:
            cur_diag.close()
          except Exception:
            pass
        except Exception:
          draft_row_for_diag = {}

      import json as _json_for_diag
      def _parse_blob(raw: Any) -> Dict[str, Any]:
        if isinstance(raw, dict):
          return raw
        if not raw:
          return {}
        try:
          parsed = _json_for_diag.loads(str(raw))
        except Exception:
          return {}
        return parsed if isinstance(parsed, dict) else {}

      realism_memo_for_diag = _parse_blob(
        (draft_row_for_diag or {}).get("realism_memo_json")
      )
      ops_for_diag = _parse_blob(
        (draft_row_for_diag or {}).get("operating_model_json")
      )
      financials_for_diag = _parse_blob(
        (draft_row_for_diag or {}).get("financials_json")
      )

      _p3_9_trace(f"draft_row_for_diag_keys={sorted(list((draft_row_for_diag or {}).keys()))[:20]}")
      # Phase 9 P3.9 fix -- prefer the DB-persisted planning_run_json
      # (full nested state) over the orchestrator's in-memory return
      # value, which is sometimes a truncated subset missing
      # planning_mode / post_cascade_completion. The fields we read
      # (planning_mode, cash_pass.cash_strategy_mode, etc.) all live
      # in the freshly-persisted blob.
      persisted_planning_run_json = _parse_blob(
        (draft_row_for_diag or {}).get("planning_run_json")
      ) or (
        planning_run_json if isinstance(planning_run_json, dict) else {}
      )
      # Planning Run ID is also a TOP-LEVEL column on intake_consult_drafts;
      # prefer that, then the persisted JSON's planning_run_id, then the
      # in-memory value, then the request param.
      resolved_planning_run_id = str(
        (draft_row_for_diag or {}).get("planning_run_id")
        or (persisted_planning_run_json or {}).get("planning_run_id")
        or (planning_run_json or {}).get("planning_run_id")
        or planning_run_id
        or ""
      ).strip()
      _p3_9_trace(
        f"persisted_pr_keys_have_planning_mode="
        f"{('planning_mode' in (persisted_planning_run_json or {}))} "
        f"persisted_pr_keys_have_post_cascade="
        f"{('post_cascade_completion' in (persisted_planning_run_json or {}))} "
        f"resolved_planning_run_id={resolved_planning_run_id!r}"
      )
      diagnostic_payload = build_run_diagnostics_payload(
        draft_row=draft_row_for_diag or {},
        planning_run_json=persisted_planning_run_json,
        realism_memo_json=realism_memo_for_diag,
        ops_json=ops_for_diag,
        financials_json=financials_for_diag,
        acceptance_verdict=acceptance_verdict,
        draft_id=result_draft_id,
        planning_run_id=resolved_planning_run_id,
      )
      # Path-miss diagnostics -- surface any None field that should
      # have come from a known location so future schema drift fails
      # visibly rather than silently.
      _missing_fields = [
        f for f in (
          "business_name", "business_naics_6", "business_stage",
          "business_start_date", "planning_mode", "cash_strategy_name",
          "planning_run_id",
        ) if not diagnostic_payload.get(f)
      ]
      if _missing_fields:
        _p3_9_trace(
          f"diagnostic_payload_missing_fields={_missing_fields}"
        )
        app.logger.warning(
          "Run diagnostics has missing fields for draft %s: %s",
          result_draft_id, _missing_fields,
        )
      _p3_9_trace(
        "diagnostic_payload built: "
        f"name={diagnostic_payload.get('business_name')!r} "
        f"naics={diagnostic_payload.get('business_naics_6')!r} "
        f"mode={diagnostic_payload.get('planning_mode')!r} "
        f"cash={diagnostic_payload.get('cash_strategy_name')!r} "
        f"run_id={diagnostic_payload.get('planning_run_id')!r} "
        f"checks={len(diagnostic_payload.get('realism_checks') or [])}"
      )
      try:
        diagnostic_persisted = persist_run_diagnostics(
          conn, payload=diagnostic_payload,
        )
        _p3_9_trace(f"persist_run_diagnostics returned={diagnostic_persisted}")
      except Exception as diag_exc:
        app.logger.warning(
          "Run diagnostics persist failed for draft %s: %s: %s",
          result_draft_id, type(diag_exc).__name__, str(diag_exc)[:200],
        )
        _p3_9_trace(
          f"persist_run_diagnostics raised "
          f"{type(diag_exc).__name__}: {str(diag_exc)[:200]}"
        )
        diagnostic_persisted = False
    except Exception as setup_exc:
      app.logger.warning(
        "Run diagnostics setup failed for draft %s: %s: %s",
        result_draft_id, type(setup_exc).__name__, str(setup_exc)[:200],
      )
      _p3_9_trace(
        f"diagnostic setup raised {type(setup_exc).__name__}: {str(setup_exc)[:500]}"
      )

    # Generate the workbook regardless of acceptance verdict. The
    # Diagnostics sheet renders from the just-persisted diagnostic row.
    try:
      from client_statements_output_excel.export_client_workbook import export_workbook_for_draft_id  # type: ignore

      client_workbook_path = str(
        export_workbook_for_draft_id(
          draft_id=result_draft_id,
          conn=conn,
          run_diagnostics=(diagnostic_payload or None),
        )
      )
    except Exception as exc:
      workbook_export_error = str(exc).strip() or "client_workbook_export_failed"
      app.logger.exception(
        "Client workbook export failed for draft %s: %s",
        result_draft_id, workbook_export_error,
      )

    # Phase 9 P3.20 Part 1 + Part 1b Concern 2 — post-run workbook
    # Model Status fail-fast. Differentiates environment failure (log
    # and continue) from genuine status failure (always re-raise, in
    # both test and production modes).
    #
    # Environment failures (no pywin32, no Excel COM, module import
    # broken) → log warning, run continues. These are infrastructure
    # problems that shouldn't kill business runs.
    #
    # Status read successfully and != "OK" → always raise. A
    # customer-visible workbook with Model Status=FAIL is a genuine
    # invariant violation; the run must NOT complete silently. The
    # fail-fast's diagnostic explicitly directs the operator to
    # verify APP state via existing post-intake fail-fasts before
    # patching workbook formulas.
    #
    # The check runs BEFORE the auto-email below so a broken workbook
    # never reaches the customer's inbox.
    if client_workbook_path:
      try:
        from client_intake_and_finmo.post_intake_runtime_validation.workbook_model_status import (  # type: ignore
          assert_workbook_model_status_ok,
        )
      except Exception as import_exc:
        # The check module itself failed to import. Treat as env
        # failure (log and continue) -- this is infrastructure, not
        # a business-logic violation.
        app.logger.warning(
          "workbook_model_status_check_module_unavailable for draft %s: %s: %s",
          result_draft_id, type(import_exc).__name__, str(import_exc)[:300],
        )
      else:
        # assert_workbook_model_status_ok handles its own env
        # failures (Excel COM unavailable) by returning silently.
        # If it raises here, the status was successfully read and
        # was NOT "OK" -- a genuine business-logic invariant
        # violation. Propagate to the API boundary so the run
        # surfaces as a 500 rather than shipping a bad workbook.
        assert_workbook_model_status_ok(client_workbook_path)

    # Deliver a copy of the generated finmo model workbook to a configured
    # folder (e.g. a OneDrive-synced Client Plans directory) IN ADDITION to the
    # auto-email. Env-configured via FINMO_MODEL_DELIVERY_DIR so no machine-
    # specific path is hardcoded in app code; unset -> skip. Best-effort: a copy
    # failure never blocks the run (log a warning only).
    if client_workbook_path:
      try:
        import os as _delivery_os
        import shutil as _delivery_shutil
        _delivery_dir = (_delivery_os.getenv("FINMO_MODEL_DELIVERY_DIR") or "").strip()
        if _delivery_dir and _delivery_os.path.isfile(client_workbook_path):
          _delivery_os.makedirs(_delivery_dir, exist_ok=True)
          _delivery_dest = _delivery_os.path.join(
            _delivery_dir, _delivery_os.path.basename(client_workbook_path)
          )
          _delivery_shutil.copy2(client_workbook_path, _delivery_dest)
          app.logger.info(
            "finmo model workbook delivered to %s for draft %s",
            _delivery_dest, result_draft_id,
          )
      except Exception as _delivery_exc:
        app.logger.warning(
          "finmo model workbook delivery to FINMO_MODEL_DELIVERY_DIR failed "
          "for draft %s: %s: %s",
          result_draft_id, type(_delivery_exc).__name__, str(_delivery_exc)[:300],
        )

    # Auto-email the workbook (if export succeeded). Never block the
    # response on email outcome -- log warnings only.
    if client_workbook_path:
      try:
        from client_intake_and_finmo.workbook_email import (  # type: ignore
          send_workbook_alert, build_run_email_body,
        )
        biz_name = (diagnostic_payload or {}).get("business_name") or result_draft_id
        score = (
          (diagnostic_payload or {}).get("acceptance_score_label")
          or (diagnostic_payload or {}).get("acceptance_score")
          or "?/?"
        )
        passed = (diagnostic_payload or {}).get("acceptance_passed")
        verdict_label = (
          "PASSED" if passed is True
          else "FAILED" if passed is False
          else "UNKNOWN"
        )
        subject = (
          f"[Planning Run] {biz_name} -- {verdict_label} ({score})"
        )
        body = build_run_email_body(diagnostic_payload or {})
        email_outcome = send_workbook_alert(
          subject=subject,
          body=body,
          # The restructure ATTEMPT workbook (pass or fail) rides the
          # same delivery as the client workbook — no silent reverts.
          attachment_paths=[
            p for p in (client_workbook_path, _rs_attempt_workbook_path) if p
          ],
        )
      except Exception as mail_exc:
        app.logger.warning(
          "Workbook auto-email failed for draft %s: %s: %s",
          result_draft_id, type(mail_exc).__name__, str(mail_exc)[:200],
        )
        email_outcome = {
          "sent": False,
          "reason": "send_exception",
          "error": f"{type(mail_exc).__name__}: {str(mail_exc)[:200]}",
        }

    # ROOT-DISEASE FIX (non-viable is an adjustable FORECAST, not a crash
    # endpoint): a non-passing acceptance verdict no longer 500s the run. The
    # verdict is the OUTPUT -- the run COMPLETES and RENDERS it (viable or
    # non-viable/tight), so the forecast flows to the client/cascade to keep
    # adjusting rather than killing the run. Only a genuine internal failure
    # (e.g. workbook export below) returns an error status. The caller inspects
    # acceptance_verdict.passed for viability. Universal.
    if not bool(acceptance_verdict.get("passed")):
      app.logger.warning(
        "Acceptance verdict non-viable for draft %s (rendered as forecast, not a crash): %s",
        result_draft_id,
        acceptance_verdict.get("failed_checks"),
      )

    # ROOT-DISEASE FIX (the run RENDERS its forecast; only viability gates --
    # a downstream ARTIFACT failure must not kill the run): a client-workbook
    # export error is SURFACED in the response but no longer 500s. The plan +
    # verdict are complete; the workbook is a rendering that can be regenerated.
    # (The former common cause -- run_diagnostics.acceptance_score a string like
    # "13/16" where the FINMO_BUILD->WORKBOOK contract expects a number -- is
    # fixed at the source: acceptance_score is now numeric and the "ok/total"
    # form lives in acceptance_score_label.) Universal.
    if workbook_export_error:
      app.logger.warning(
        "Client workbook export failed for draft %s (run still completes, surfaced not crashed): %s",
        result_draft_id, workbook_export_error,
      )

    return jsonify(
      {
        "status": "ok",
        "draft_id": result_draft_id,
        "action": "system_run_complete",
        "assistant_message": "System run complete.",
        "client_workbook_path": client_workbook_path,
        "workbook_export_error": workbook_export_error,
        "planning_context_summary_json": planning_context_summary_json,
        "planning_run_json": planning_run_json,
        "planning_runtime_json": planning_runtime_json,
        "numeric_solver_feedback_json": numeric_solver_feedback_json,
        "acceptance_verdict": acceptance_verdict,
        "run_diagnostics": diagnostic_payload,
        "run_diagnostics_persisted": diagnostic_persisted,
        "auto_email": email_outcome,
      }
    )
  finally:
    _set_active_openai_deadline(None)
    try:
      conn.close()
    except Exception:
      pass


def post_intake_consult_system_run_control_handler(*, app, request):
  if request.method == "OPTIONS":
    return ("", 204)

  payload = request.get_json(silent=True) or {}
  draft_id = str(payload.get("draft_id") or "").strip()
  planning_run_id = str(payload.get("planning_run_id") or "").strip()
  action = str(payload.get("action") or "").strip().lower()
  reason = str(payload.get("reason") or "").strip()
  step_key = str(payload.get("step_key") or payload.get("process_step_key") or "").strip()
  if not draft_id and not planning_run_id:
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id or planning_run_id is required"}),
      400,
    )
  if action not in {"pause", "stop", "run_process_step", "run_step", "run_targeted_process"}:
    return (
      jsonify({"error": "invalid_request", "detail": "action must be pause, stop, or run_process_step"}),
      400,
    )
  if action in {"run_process_step", "run_step", "run_targeted_process"} and not step_key:
    return (
      jsonify({"error": "invalid_request", "detail": "step_key is required for targeted process execution"}),
      400,
    )

  try:
    from intake_submission import get_mysql_connection  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import MySQL helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  conn = get_mysql_connection()
  try:
    if action in {"run_process_step", "run_step", "run_targeted_process"}:
      run_row = get_planning_run(conn, planning_run_id=planning_run_id) if planning_run_id else {}
      resolved_draft_id = draft_id or str((run_row or {}).get("draft_id") or "").strip()
      if not resolved_draft_id:
        return (
          jsonify({"error": "invalid_request", "detail": "draft_id is required when planning_run_id has no draft_id"}),
          400,
        )
      draft_row = get_draft(conn, draft_id=resolved_draft_id)
      checkpoint = (
        get_latest_planning_run_checkpoint(
          conn,
          planning_run_id=planning_run_id or str((run_row or {}).get("planning_run_id") or "").strip(),
        )
        if (planning_run_id or str((run_row or {}).get("planning_run_id") or "").strip())
        else {}
      )
      targeted_result = run_targeted_process_step(
        step_key,
        runtime_context=_targeted_process_runtime_context_from_rows(
          draft=draft_row or {},
          planning_run=run_row or {},
          checkpoint=checkpoint or {},
        ),
      )
      return jsonify(
        {
          "status": "ok",
          "action": "targeted_process_step_completed",
          "draft_id": resolved_draft_id,
          "planning_run_id": planning_run_id or str((run_row or {}).get("planning_run_id") or "").strip(),
          "step_key": step_key,
          "targeted_process": targeted_result,
        }
      )
    try:
      run_row = request_planning_run_action(
        conn,
        draft_id=draft_id or None,
        planning_run_id=planning_run_id or None,
        action=action,
        reason=reason,
      )
    except RuntimeError as exc:
      detail = str(exc).strip() or "planning_run_control_failed"
      if detail == "planning_run_not_found_for_action":
        return (jsonify({"error": "not_found", "detail": detail}), 404)
      if detail == "unsupported_planning_run_action":
        return (jsonify({"error": "invalid_request", "detail": detail}), 400)
      raise
    checkpoint = get_latest_planning_run_checkpoint(
      conn,
      planning_run_id=str((run_row or {}).get("planning_run_id") or "").strip(),
    )
    return jsonify(
      {
        "status": "ok",
        "action": f"run_{action}_requested",
        "planning_run": _serialize_debug_draft_row(run_row or {}),
        "latest_checkpoint": _serialize_debug_draft_row(checkpoint or {}),
      }
    )
  finally:
    try:
      conn.close()
    except Exception:
      pass


def get_intake_consult_system_run_status_handler(*, app, request):
  if request.method == "OPTIONS":
    return ("", 204)

  draft_id = str(request.args.get("draft_id") or "").strip()
  planning_run_id = str(request.args.get("planning_run_id") or "").strip()
  if not draft_id and not planning_run_id:
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id or planning_run_id is required"}),
      400,
    )

  try:
    from intake_submission import get_mysql_connection  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import MySQL helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  conn = get_mysql_connection()
  try:
    run_row = get_planning_run(
      conn,
      planning_run_id=planning_run_id or None,
      draft_id=draft_id or None,
      active_only=not bool(planning_run_id),
    )
    if not isinstance(run_row, dict) and draft_id and not planning_run_id:
      run_row = get_planning_run(
        conn,
        draft_id=draft_id,
        active_only=False,
      )
    if not isinstance(run_row, dict):
      return (jsonify({"error": "not_found", "detail": "planning_run_not_found"}), 404)
    checkpoint = get_latest_planning_run_checkpoint(
      conn,
      planning_run_id=str(run_row.get("planning_run_id") or "").strip(),
    )
    return jsonify(
      {
        "status": "ok",
        "planning_run": _serialize_debug_draft_row(run_row or {}),
        "latest_checkpoint": _serialize_debug_draft_row(checkpoint or {}),
      }
    )
  finally:
    try:
      conn.close()
    except Exception:
      pass


def _parse_json_value(raw: Any) -> Any:
  if raw is None:
    return None
  if isinstance(raw, (dict, list)):
    return raw
  try:
    return json.loads(str(raw))
  except Exception:
    return raw

def _serialize_debug_draft_row(row: Dict[str, Any]) -> Dict[str, Any]:
  if not isinstance(row, dict):
    return {}
  json_columns = {
    "messages_json",
    "operating_model_json",
    "target_market_json",
    "people_json",
    "financials_json",
    "marketing_model_json",
    "financials_year1_json",
    "realism_memo_json",
    "model_input_json",
    "finmo_json",
    "planning_run_json",
    "numeric_solver_feedback_json",
    "pending_ops_milestone_json",
    "fulfillment_json",
  }
  serialized: Dict[str, Any] = {}
  for key, value in row.items():
    if key in json_columns:
      serialized[key] = _parse_json_value(value)
    elif isinstance(value, (datetime, date)):
      serialized[key] = value.isoformat(sep=" ")
    else:
      serialized[key] = value
  return serialized


def get_intake_consult_debug_state_handler(*, app, request, draft_id: str):
  if request.method == "OPTIONS":
    return ("", 204)

  if not draft_id or not str(draft_id).strip():
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
      400,
    )

  try:
    from intake_submission import get_mysql_connection  # type: ignore
    from client_intake_and_finmo.intake_consult_draft import get_draft  # type: ignore
  except Exception as exc:
    app.logger.exception("Failed to import MySQL helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  conn = get_mysql_connection()
  try:
    try:
      draft = get_draft(conn, draft_id=str(draft_id).strip())
    except Exception as exc:
      return (jsonify({"error": "not_found", "detail": str(exc)}), 404)

    return jsonify(
      {
        "status": "ok",
        "table": "intake_consult_drafts",
        "draft_id": str(draft_id).strip(),
        "controller_resolution_state": (
          _parse_json_dict(draft.get("planning_run_json")).get("controller_resolution_state")
          if isinstance(_parse_json_dict(draft.get("planning_run_json")).get("controller_resolution_state"), dict)
          else {}
        ),
        "row": _serialize_debug_draft_row(draft),
      }
    )
  finally:
    try:
      conn.close()
    except Exception:
      pass


def post_intake_consult_handler(*, app, request):
  """
  Unified intake consult controller (single chat, single draft model).
  """

  if request.method == "OPTIONS":
    return ("", 204)

  payload = request.get_json(silent=True) or {}
  draft_id = payload.get("draft_id")
  if not draft_id or not str(draft_id).strip():
    return (
      jsonify({"error": "invalid_request", "detail": "draft_id is required"}),
      400,
    )

  raw_message = payload.get("message")
  message = str(raw_message or "").strip()
  starting = raw_message is None or not message

  try:
    from intake_submission import get_mysql_connection  # type: ignore
    from client_intake_and_finmo.intake_consult_draft import append_messages, get_draft  # type: ignore
    from api_handlers.shared_context import build_shared_context  # type: ignore
    from fact_templates import sanitize_fact_template  # type: ignore
    from intent_router import route_intent  # type: ignore

    from intake_consultant import consultant_chat_turn, consultant_finalize  # type: ignore
    from target_market_consultant import target_market_chat_turn, target_market_finalize  # type: ignore
    from people_capability_consultant import (  # type: ignore
      extract_people_collection_progress,
      people_capability_chat_turn,
      people_capability_finalize,
    )
    from financials_year1 import (  # type: ignore
      assemble_financials_year1,
      build_revenue_driver_signature,
      build_revenue_guardrail_signals,
      build_revenue_constraints_snippet,
      build_revenue_math_line,
    )
    from api_handlers.fact_propagation import propagate_shared_facts
    from api_handlers.revenue_guardrail_state import acknowledge_signature, get_acknowledged_signature
  except Exception as exc:
    app.logger.exception("Failed to import unified intake helpers: %s", exc)
    return (jsonify({"error": "server_error"}), 500)

  conn = get_mysql_connection()
  try:
    consult = get_draft(conn, draft_id=str(draft_id).strip())
    client_id = str(consult.get("client_id") or "").strip()
    draft_status = str(consult.get("status") or "").strip().lower()
    if draft_status == "submitted":
      return (
        jsonify({"error": "duplicate_submit", "detail": "This draft was already submitted."}),
        409,
      )

    messages = _parse_messages(consult.get("messages_json"))

    ops_json = _parse_json_dict(consult.get("operating_model_json"))
    market_json = _parse_json_dict(consult.get("target_market_json"))
    people_json = _parse_json_dict(consult.get("people_json"))
    financials_json = _parse_json_dict(consult.get("financials_json"))
    marketing_model_json = _parse_json_dict(consult.get("marketing_model_json"))
    financials_year1_json = _parse_json_dict(consult.get("financials_year1_json"))
    fulfillment_json = _parse_json_dict(consult.get("fulfillment_json"))
    pending_ops_milestone = _parse_pending_bool(consult.get("pending_ops_milestone_json"))

    _ensure_ops_business_naics(conn, ops_json)
    restatement_locked_prior = bool(ops_json.get("business_type_candidates_locked"))

    ops_confirmed = bool(consult.get("ops_confirmed"))
    market_confirmed = bool(consult.get("market_confirmed"))
    people_confirmed = bool(consult.get("people_confirmed"))
    financials_confirmed = bool(consult.get("financials_confirmed"))
    ops_finalize_proposed = bool(consult.get("ops_finalize_proposed"))
    market_finalize_proposed = bool(consult.get("market_finalize_proposed"))
    people_finalize_proposed = bool(consult.get("people_finalize_proposed"))

    business_facts: Dict[str, Any] = {
      "name": consult.get("business_name"),
      "address": consult.get("business_address"),
      "start_date": consult.get("business_start_date"),
      "address_street": consult.get("address_street"),
      "address_city": consult.get("address_city"),
      "address_state": consult.get("address_state"),
      "address_zip": consult.get("address_zip"),
      "address_country": consult.get("address_country"),
    }

    # Allow explicit client-detail updates from the UI (no intent inference).
    if payload.get("business_name") is not None:
      name_raw = str(payload.get("business_name") or "").strip()
      if name_raw:
        business_facts["name"] = name_raw
    address_keys = ("address_street", "address_city", "address_state", "address_zip", "address_country")
    payload_parts: Dict[str, str] = {}
    for key in address_keys:
      if payload.get(key) is None:
        payload_parts[key] = ""
        continue
      payload_parts[key] = str(payload.get(key) or "").strip()
    has_all_parts = all(payload_parts.values())
    if payload.get("address") is not None:
      addr_raw = str(payload.get("address") or "").strip()
      if addr_raw and has_all_parts:
        business_facts["address"] = addr_raw
    start_date_raw = payload.get("business_start_date")
    if start_date_raw is None:
      start_date_raw = payload.get("businessStartDate") or payload.get("business_startDate")
    if start_date_raw is not None:
      sd_raw = str(start_date_raw or "").strip()
      if sd_raw:
        business_facts["start_date"] = sd_raw

    if has_all_parts:
      for key, val in payload_parts.items():
        if val:
          business_facts[key] = val

    current_date = datetime.utcnow().date()
    current_date_iso = current_date.isoformat()
    business_stage_hint = _infer_business_stage(business_facts.get("start_date"), current_date)

    focus, confirm_question = _compute_focus_and_confirm_question(
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      ops_confirmed=ops_confirmed,
      market_confirmed=market_confirmed,
      people_confirmed=people_confirmed,
      financials_confirmed=financials_confirmed,
    )

    shared_context = build_shared_context(conn, draft_id=str(draft_id).strip())
    shared_context = dict(shared_context or {})
    shared_context["operating_model"] = ops_json
    shared_context["target_market"] = market_json
    shared_context["people_capability"] = people_json
    shared_context["financials"] = financials_json
    base_year1 = assemble_financials_year1(shared_context, None)
    if _year1_drivers_conflict(financials_year1_json, base_year1):
      financials_year1_json = base_year1
    else:
      financials_year1_json = assemble_financials_year1(shared_context, financials_year1_json)
    financials_json, financials_year1_json = _sync_financials_consult_persistence_state(
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
      marketing_model_json=marketing_model_json,
    )
    shared_context["financials"] = financials_json
    if isinstance(financials_year1_json, dict) and financials_year1_json:
      shared_context["financials_year1_json"] = financials_year1_json

    def _refresh_marketing_model() -> Dict[str, Any]:
      nonlocal marketing_model_json, shared_context
      try:
        marketing_model_json = _compute_marketing_model_json(
          conn=conn,
          ops_json=ops_json,
          market_json=market_json,
          people_json=people_json,
          financials_year1_json=financials_year1_json,
          business_facts=business_facts,
          existing_marketing_model_json=marketing_model_json,
          estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
        )
      except Exception:
        marketing_model_json = dict(marketing_model_json or {})
      shared_context["marketing"] = marketing_model_json
      return marketing_model_json

    def _persist_intake_completion(
      *,
      new_messages: List[Dict[str, str]],
      ops_value: Dict[str, Any],
      market_value: Dict[str, Any],
      people_value: Dict[str, Any],
      financials_value: Dict[str, Any],
      financials_year1_value: Dict[str, Any],
      marketing_value: Dict[str, Any],
      confirmations_value: Optional[Dict[str, bool]] = None,
      flat_fields_value: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
      planning_run_json = _build_intake_complete_planning_run_payload()
      realism_memo_json = generate_realism_memo_payload_safe(
        ops_json=ops_value,
        financials_json=financials_value,
      )
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=new_messages,
        operating_model_json=ops_value,
        target_market_json=market_value,
        people_json=people_value,
        financials_json=financials_value,
        financials_year1_json=financials_year1_value,
        marketing_model_json=marketing_value,
        realism_memo_json=realism_memo_json,
        planning_run_json=planning_run_json,
        active_focus="done",
        confirmations=confirmations_value,
        business_facts=business_facts,
        status="completed",
        completed=True,
        flat_fields=flat_fields_value,
      )
      return planning_run_json

    _refresh_marketing_model()
    revenue_math_line = build_revenue_math_line(
      financials_year1_json,
      unit_name=str((ops_json or {}).get("unit_name") or "").strip() or None,
    )
    revenue_constraints_snippet = build_revenue_constraints_snippet(
      shared_context,
      financials_year1_json,
      business_start_date=str(business_facts.get("start_date") or "").strip() or None,
    )
    guardrail_signals = build_revenue_guardrail_signals(
      shared_context,
      financials_year1_json,
      business_start_date=str(business_facts.get("start_date") or "").strip() or None,
      fulfillment_context=fulfillment_json,
    )
    driver_signature = build_revenue_driver_signature(financials_year1_json)
    guardrail_acknowledged = (
      get_acknowledged_signature(str(draft_id).strip()) == driver_signature
    )
    guardrail_triggered = bool(guardrail_signals.get("triggered")) and not guardrail_acknowledged

    if starting:
      start_instruction = _start_instruction_for_focus(focus)
      turn_messages = [*messages, {"role": "user", "content": start_instruction}]
      intake_context: Dict[str, Any] = {
        "client_id": client_id,
        "draft_id": str(draft_id).strip(),
        "business_name": business_facts.get("name"),
        "business_start_date": business_facts.get("start_date"),
        "address": business_facts.get("address"),
        "current_date": current_date_iso,
        "business_stage_hint": business_stage_hint,
        "shared_context": shared_context,
        "fulfillment_json": fulfillment_json,
      }
      if focus == "market":
        consumer_type = str((ops_json or {}).get("consumer_type") or "consumer").strip().lower()
        if consumer_type not in ("consumer", "b2b", "mixed"):
          consumer_type = "consumer"
        intake_context["consumer_type"] = consumer_type
      intake_context["financials_year1_json"] = financials_year1_json
      intake_context["revenue_math_line"] = revenue_math_line
      intake_context["revenue_constraints_snippet"] = revenue_constraints_snippet
      intake_context["revenue_driver_patch"] = None
      intake_context["revenue_guardrail_triggered"] = guardrail_triggered
      intake_context["revenue_guardrail_context_signals"] = guardrail_signals.get("context_signals") or []
      intake_context["revenue_guardrail_product_signals"] = guardrail_signals.get("product_signals") or []

      # Target Market is model-interpreted every turn and returns a structured patch,
      # allowing us to persist the Target Market JSON incrementally (no controller parsing).
      turn: Dict[str, Any] = {}
      closeout: Optional[Dict[str, Any]] = None
      if focus == "ops":
        turn = consultant_chat_turn(intake_context=intake_context, conversation_messages=turn_messages) or {}
        ops_json = _apply_model_ops_patch(ops_json, turn.get("patch") if isinstance(turn, dict) else None)
        try:
          shared_context["operating_model"] = ops_json
        except Exception:
          pass
      elif focus == "market":
        turn = target_market_chat_turn(intake_context=intake_context, conversation_messages=turn_messages) or {}
        try:
          if isinstance(market_json, dict):
            patch_obj = turn.get("patch") if isinstance(turn, dict) else None
            if isinstance(patch_obj, dict):
              allowed_keys = {
                "consumer_type",
                "gender_age_intent",
                "income_intent",
                "b2b_industry_terms",
                "b2b_size_bands",
                "b2b_age_bands",
              }
              for k, v in patch_obj.items():
                key = str(k or "").strip()
                if not key:
                  continue
                if key.startswith("market."):
                  key = key.split(".", 1)[1].strip()
                if key in allowed_keys:
                  # In strict json_schema, the model must always output every patch key.
                  # We treat null values as "no change" to avoid wiping prior answers.
                  if v is None:
                    continue
                  market_json[key] = v
        except Exception:
          pass
      elif focus == "people":
        turn = people_capability_chat_turn(intake_context=intake_context, conversation_messages=turn_messages) or {}
      elif focus == "financials":
        turn, financials_json = _build_financials_live_turn(
          conn=conn,
          intake_context=intake_context,
          conversation_messages=turn_messages,
          shared_context=shared_context,
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          guardrail_triggered=False,
        )
      else:
        turn = {"assistant_message": "Continue."}

      assistant_text = str(turn.get("assistant_message") or "").strip() or "Continue."

      assistant_text = sanitize_fact_template(str(assistant_text or "").strip())
      if focus == "market":
        assistant_text = _strip_acs_codes(assistant_text)
      if focus == "financials":
        assistant_text = _append_constraints_snippet(
          assistant_text,
          revenue_constraints_snippet,
          messages,
          force=True,
        )

      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[{"role": "assistant", "content": assistant_text}],
        operating_model_json=ops_json if focus == "done" else None,
        target_market_json=market_json if focus in {"market", "done"} else None,
        people_json=people_json if focus == "done" else None,
        financials_json=financials_json if focus in {"financials", "done"} else None,
        financials_year1_json=financials_year1_json if focus == "done" else None,
        marketing_model_json=marketing_model_json if focus == "done" else _refresh_marketing_model(),
        active_focus=focus,
        business_facts=business_facts,
        status="completed" if focus == "done" else None,
        completed=bool(focus == "done"),
      )

      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": focus,
          "awaiting_confirmation": bool(confirm_question),
          "done": bool(focus == "done"),
          "action": "continue",
          "assistant_message": assistant_text,
          "planning_mode": (
            str((closeout or {}).get("planning_mode") or "").strip()
            if isinstance(closeout, dict)
            else None
          ) or None,
          "planning_mode_reason": (
            str((closeout or {}).get("planning_mode_reason") or "").strip()
            if isinstance(closeout, dict)
            else None
          ) or None,
          "prompt_file": (
            str((closeout or {}).get("prompt_file") or "").strip()
            if isinstance(closeout, dict)
            else None
          ) or None,
        }
      )

    user_msg = {"role": "user", "content": message}
    recent_messages = messages[-12:] if len(messages) > 12 else list(messages)
    last_assistant = _last_assistant_message(messages)
    restatement_confirmed_this_turn = False
    persist_ops_from_restatement = False
    ops_restatement_meta_touched = False
    ops_restatement_pending = bool((ops_json or {}).get("_ops_restatement_pending"))
    ops_restatement_text = str((ops_json or {}).get("_ops_restatement_text") or "").strip()
    if (
      str(focus).strip().lower() == "ops"
      and last_assistant
    ):
      # Only run restatement confirmation inference when the controller explicitly
      # marked the prior assistant turn as the restatement confirmation prompt.
      # This avoids early persistence from classifier misfires on non-restatement turns.
      if ops_restatement_pending:
        try:
          classification = _classify_restatement_response(
            restatement=ops_restatement_text or last_assistant,
            user_reply=message,
          )
        finally:
          # Pending applies to exactly one client reply turn. Clear it regardless of
          # ACCEPT/REJECT/CLARIFY so we don't keep classifying subsequent answers.
          if isinstance(ops_json, dict):
            ops_json.pop("_ops_restatement_pending", None)
          ops_restatement_meta_touched = True
        if classification == "ACCEPT":
          restatement_confirmed_this_turn = True

    if restatement_confirmed_this_turn:
      already_locked = bool(ops_json.get("business_type_candidates_locked"))
      existing_candidates = ops_json.get("business_type_candidates")
      has_candidates = isinstance(existing_candidates, list) and bool(existing_candidates)
      if not already_locked and not has_candidates:
        try:
          bt_candidates = _build_business_type_candidates(
            conn=conn,
            messages=[*messages, user_msg],
            restatement_text=ops_restatement_text or last_assistant,
          )
        except Exception as exc:
          logger.exception("business_type_selection_failed: %s", exc)
          return (jsonify({"error": "business_type_selection_failed"}), 500)
        if not bt_candidates:
          logger.warning("business_type_selection_empty restatement=%r", last_assistant)
          return (jsonify({"error": "business_type_selection_failed"}), 500)
        ops_json["business_type_candidates"] = bt_candidates
        ops_json["business_type_candidates_locked"] = True
        ops_json["business_type"] = bt_candidates[0]
        try:
          try:
            from business_type_naics import get_naics_from_business_type  # type: ignore
          except Exception:
            from client_intake_and_finmo.business_type_naics import (  # type: ignore
              get_naics_from_business_type,
            )
          if ops_json.get("business_type"):
            ops_json["business_naics_6"] = get_naics_from_business_type(
              conn, ops_json.get("business_type")
            )
          else:
            ops_json["business_naics_6"] = None
        except Exception:
          ops_json["business_naics_6"] = None
        lines = []
        for idx, bt in enumerate(bt_candidates[:80], start=1):
          lines.append(f"{idx}. {bt}")
        if lines:
          logger.warning(
            "BUSINESS TYPE CANDIDATES (ranked):\n%s",
            "\n".join(lines),
          )
        logger.warning(
          "business_type_persisted business_type=%r business_naics_6=%r",
          ops_json.get("business_type"),
          ops_json.get("business_naics_6"),
        )
        persist_ops_from_restatement = True
    revenue_driver_patch = None
    pending_competitive_advantage = _extract_competitive_advantage_prompt(last_assistant)
    competitive_intent_override: Optional[Dict[str, Any]] = None
    if (
      pending_competitive_advantage
      and str(focus).strip().lower() == "ops"
      and not restatement_locked_prior
    ):
      pending_competitive_advantage = None

    if (
      pending_competitive_advantage
      and str(focus).strip().lower() == "ops"
      and not str((ops_json or {}).get("competitive_advantage") or "").strip()
    ):
      competitive_intent = route_intent(
        consult_type="ops",
        user_message=message,
        baseline_json=ops_json,
        shared_context=shared_context,
        recent_messages=recent_messages,
        confirm_question_override=COMPETITIVE_ADVANTAGE_QUESTION,
        active_focus="ops",
      )
      comp_action = str(competitive_intent.get("action") or "").strip()
      comp_router_msg = sanitize_fact_template(
        str(competitive_intent.get("assistant_message") or "").strip()
      )
      comp_patch = competitive_intent.get("patch") if isinstance(competitive_intent.get("patch"), dict) else None
      if comp_action == "confirm_clarify":
        assistant_text = comp_router_msg
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
          marketing_model_json=_refresh_marketing_model(),
          active_focus=focus,
          business_facts=business_facts,
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": focus,
            "awaiting_confirmation": True,
            "done": False,
            "action": "confirm_clarify",
            "assistant_message": assistant_text,
          }
        )
      if comp_action == "confirm_proceed":
        # Commit the confirmed competitive advantage immediately so subsequent Ops logic
        # in this turn cannot re-trigger the proposal injection.
        confirmed_advantage = sanitize_fact_template(
          str(pending_competitive_advantage or "").strip()
        )
        ops_json["competitive_advantage"] = confirmed_advantage
        try:
          shared_context["operating_model"] = ops_json
        except Exception:
          pass
        comp_action = "edit_patch"
        comp_patch = {
          "ops.competitive_advantage": confirmed_advantage
        }
      if comp_action != "edit_patch":
        raise RuntimeError("Unexpected intent action for competitive advantage.")
      competitive_intent_override = {
        "action": comp_action,
        "router_msg": comp_router_msg,
        "patch": comp_patch,
      }

    if not starting:
      # Revenue adjudication / option-battle flow has been removed from the live
      # Financials consult. Financials now stays on the controller/router path.
      pass

    if (
      guardrail_triggered
      and not revenue_driver_patch
      and not starting
      and _is_guardrail_acknowledgement(message)
    ):
      acknowledge_signature(str(draft_id).strip(), driver_signature)
      guardrail_triggered = False

    revenue_math_line = build_revenue_math_line(
      financials_year1_json,
      unit_name=str((ops_json or {}).get("unit_name") or "").strip() or None,
    )

    focus, confirm_question = _compute_focus_and_confirm_question(
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      ops_confirmed=ops_confirmed,
      market_confirmed=market_confirmed,
      people_confirmed=people_confirmed,
      financials_confirmed=financials_confirmed,
    )

    baseline_json = {
      "business": business_facts,
      "ops": ops_json,
      "market": market_json,
      "people": people_json,
      "financials": financials_json,
      "financials_year1": financials_year1_json,
      "marketing": dict((shared_context or {}).get("marketing") or {}),
      "fulfillment": fulfillment_json,
    }
    current_financials_stage = (
      _next_financials_stage(financials_json)
      if str(focus).strip().lower() == "financials"
      else None
    )
    shared_context_for_router = shared_context
    try:
      router_candidates = ops_json.get("business_type_candidates")
      if isinstance(router_candidates, list) and router_candidates:
        shared_context_for_router = dict(shared_context or {})
        shared_context_for_router["business_type_candidates"] = router_candidates
    except Exception:
      shared_context_for_router = shared_context
    # Route the user's message through the GPT-only intent router first.
    confirm_override = str(confirm_question or _detect_confirm_question(last_assistant) or "").strip()
    # NOTE: Target Market replies are interpreted directly by the Target Market consultant
    # (structured patch). We intentionally do not maintain controller-owned "pending income"
    # confirmation state to avoid brittle loops.
    milestone_intent_override: Optional[Dict[str, Any]] = None
    if (
      str(focus).strip().lower() == "ops"
      and pending_ops_milestone
      and not _has_confirmed_milestone(ops_json)
    ):
      try:
        extracted_milestone = _extract_ops_pending_milestone_via_openai(
          text=message,
          ops_json=ops_json,
          business_facts=business_facts,
        )
        milestone_obj = extracted_milestone.get("milestone")
        clarification_question = sanitize_fact_template(
          str(extracted_milestone.get("clarification_question") or "").strip()
        )
        if bool(extracted_milestone.get("captured")) and isinstance(milestone_obj, dict):
          milestone_intent_override = {
            "action": "edit_patch",
            "router_msg": "Got it.",
            "patch": {"milestones": [milestone_obj]},
          }
        else:
          fallback_milestone = _fallback_ops_pending_milestone_from_text(message)
          if isinstance(fallback_milestone, dict):
            milestone_intent_override = {
              "action": "edit_patch",
              "router_msg": "Got it.",
              "patch": {"milestones": [fallback_milestone]},
            }
          elif clarification_question:
            milestone_intent_override = {
              "action": "confirm_clarify",
              "router_msg": clarification_question,
              "patch": None,
            }
          else:
            milestone_intent = route_intent(
              consult_type="ops",
              user_message=message,
              baseline_json=ops_json,
              shared_context=shared_context_for_router,
              recent_messages=recent_messages,
              active_focus="ops",
            )
            m_action = str(milestone_intent.get("action") or "").strip()
            m_router_msg = sanitize_fact_template(str(milestone_intent.get("assistant_message") or "").strip())
            m_patch = (
              milestone_intent.get("patch") if isinstance(milestone_intent.get("patch"), dict) else None
            )
            # Only override routing when the router actually produced a milestones patch.
            if m_action == "edit_patch" and isinstance(m_patch, dict) and (
              "milestones" in m_patch or "ops.milestones" in m_patch
            ):
              milestone_intent_override = {
                "action": m_action,
                "router_msg": m_router_msg,
                "patch": m_patch,
              }
            elif m_action == "confirm_clarify" and m_router_msg:
              milestone_intent_override = {
                "action": m_action,
                "router_msg": m_router_msg,
                "patch": None,
              }
      except Exception:
        milestone_intent_override = None

    if (
      str(focus).strip().lower() == "people"
      and str(confirm_override or "").strip() != PEOPLE_CONFIRM_QUESTION
      and _detect_people_done_adding_via_openai(
        last_assistant=last_assistant,
        user_message=message,
      )
    ):
      intake_context_people = {
        "client_id": client_id,
        "draft_id": str(draft_id).strip(),
        "business_name": business_facts.get("name"),
        "business_start_date": business_facts.get("start_date"),
        "address": business_facts.get("address"),
        "current_date": current_date_iso,
        "business_stage_hint": business_stage_hint,
        "shared_context": shared_context,
        "operating_model_json": ops_json,
        "target_market_json": market_json,
        "people_json": people_json,
        "financials_json": financials_json,
        "fulfillment_json": fulfillment_json,
      }
      final_obj = people_capability_finalize(
        intake_context=intake_context_people,
        conversation_messages=[*messages, user_msg],
      )
      people_json, assistant_final = _build_people_review_payload(
        conn=conn,
        final_obj=final_obj,
        ops_json=ops_json,
        market_json=market_json,
        financials_json=financials_json,
        business_facts=business_facts,
      )
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_final}],
        people_json=people_json,
        marketing_model_json=_refresh_marketing_model(),
        active_focus="people",
        business_facts=business_facts,
        flat_fields=_finalize_flag_field("people", True),
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": "people",
          "awaiting_confirmation": True,
          "done": False,
          "action": "continue",
          "assistant_message": assistant_final,
        }
      )

    if str(focus).strip().lower() == "financials":
      intake_context_financials = {
        "client_id": client_id,
        "draft_id": str(draft_id).strip(),
        "business_name": business_facts.get("name"),
        "business_start_date": business_facts.get("start_date"),
        "address": business_facts.get("address"),
        "current_date": current_date_iso,
        "business_stage_hint": business_stage_hint,
        "shared_context": shared_context,
        "operating_model_json": ops_json,
        "target_market_json": market_json,
        "people_json": people_json,
        "financials_json": financials_json,
        "financials_year1_json": financials_year1_json,
        "fulfillment_json": fulfillment_json,
        "revenue_math_line": revenue_math_line,
        "revenue_constraints_snippet": revenue_constraints_snippet,
        "revenue_driver_patch": revenue_driver_patch,
        "revenue_guardrail_triggered": guardrail_triggered,
        "revenue_guardrail_context_signals": guardrail_signals.get("context_signals") or [],
        "revenue_guardrail_product_signals": guardrail_signals.get("product_signals") or [],
      }
      financials_turn, financials_json = _run_financials_turn_and_sync(
        route_intent=route_intent,
        conn=conn,
        intake_context=intake_context_financials,
        conversation_messages=[*messages, user_msg],
        business_facts=business_facts,
        shared_context=shared_context,
        last_assistant=last_assistant,
        user_message=message,
        financials_json=financials_json,
        financials_year1_json=financials_year1_json,
      )
      shared_context["financials"] = financials_json
      shared_context["financials_year1"] = financials_year1_json
      assistant_text = sanitize_fact_template(
        str((financials_turn or {}).get("assistant_message") or "").strip()
      )
      assistant_text = _append_constraints_snippet(
        assistant_text,
        revenue_constraints_snippet,
        messages,
        force=True,
      )

      if bool((financials_turn or {}).get("transition_to_done")):
        assistant_final = str((financials_turn or {}).get("assistant_message") or "").strip()
        _persist_intake_completion(
          new_messages=[user_msg, {"role": "assistant", "content": assistant_final}],
          ops_value=ops_json,
          market_value=market_json,
          people_value=people_json,
          financials_value=financials_json,
          financials_year1_value=financials_year1_json,
          marketing_value=_refresh_marketing_model(),
          confirmations_value={"financials": True},
          flat_fields_value=_finalize_flag_field("financials", True),
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": "done",
            "awaiting_confirmation": False,
            "done": True,
            "action": "intake_complete",
            "assistant_message": assistant_final,
          }
        )

      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        financials_json=financials_json,
        marketing_model_json=_refresh_marketing_model(),
        active_focus="financials",
        business_facts=business_facts,
        flat_fields=_finalize_flag_field("financials", False),
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": "financials",
          "awaiting_confirmation": False,
          "done": False,
          "action": "continue",
          "assistant_message": assistant_text,
        }
      )

    if competitive_intent_override:
      action = str(competitive_intent_override.get("action") or "").strip()
      router_msg = sanitize_fact_template(str(competitive_intent_override.get("router_msg") or "").strip())
      patch = (
        competitive_intent_override.get("patch")
        if isinstance(competitive_intent_override.get("patch"), dict)
        else None
      )
    elif milestone_intent_override:
      action = str(milestone_intent_override.get("action") or "").strip()
      router_msg = sanitize_fact_template(str(milestone_intent_override.get("router_msg") or "").strip())
      patch = (
        milestone_intent_override.get("patch")
        if isinstance(milestone_intent_override.get("patch"), dict)
        else None
      )
    elif str(focus).strip().lower() == "ops" and not restatement_locked_prior:
      action = "continue_chat"
      router_msg = ""
      patch = None
    elif str(focus).strip().lower() == "market" and not market_finalize_proposed:
      # Target Market is model-interpreted every turn (structured patch), not router-parsed.
      action = "continue_chat"
      router_msg = ""
      patch = None
    else:
      intent = route_intent(
        consult_type="unified",
        user_message=message,
        baseline_json=baseline_json,
        shared_context=shared_context_for_router,
        recent_messages=recent_messages,
        confirm_question_override=confirm_override,
        active_focus=focus,
      )

      action = str(intent.get("action") or "").strip()
      router_msg = sanitize_fact_template(str(intent.get("assistant_message") or "").strip())
      patch = intent.get("patch") if isinstance(intent.get("patch"), dict) else None

    if (
      str(focus).strip().lower() == "ops"
      and action == "confirm_proceed"
      and not ops_finalize_proposed
      and not pending_ops_milestone
      and not competitive_intent_override
      and not milestone_intent_override
    ):
      inferred_ops_patch = _extract_ops_proposal_patch(
        last_assistant=last_assistant,
        route_intent=route_intent,
        ops_json=ops_json,
        shared_context=shared_context,
        recent_messages=recent_messages,
      )
      if isinstance(inferred_ops_patch, dict) and inferred_ops_patch:
        action = "edit_patch"
        patch = inferred_ops_patch

    if str(focus).strip().lower() == "financials" and action == "confirm_proceed":
      try:
        active_stage = str(current_financials_stage or "").strip()
        stage_spec = _financials_stage_spec(active_stage)
        if active_stage and bool(stage_spec.get("confirmable_baseline")):
          default_patch = _financials_stage_default_patch(
            stage_name=active_stage,
            shared_context=shared_context,
            financials_year1_json=financials_year1_json,
            business_facts=business_facts,
            conn=conn,
          )
          if isinstance(default_patch, dict) and default_patch:
            action = "edit_patch"
            patch = {f"financials.{k}": v for k, v in default_patch.items()}
      except Exception:
        pass

    if (
      str(focus).strip().lower() == "ops"
      and pending_ops_milestone
      and not _has_confirmed_milestone(ops_json)
      and not milestone_intent_override
      and action != "edit_patch"
    ):
      action = "confirm_clarify"
      router_msg = (
        "What is one concrete goal you want to hit in about the next 12 months, and by when?"
      )
      patch = None

    milestone_patch_from_user: Optional[List[Dict[str, Any]]] = None
    if action == "edit_patch" and isinstance(patch, dict):
      patch = _normalize_unscoped_patch(patch, focus=focus)
      if str(focus or "").strip().lower() == "financials":
        normalized_financials_patch = _normalize_financials_router_patch(
          patch=patch,
          active_stage=current_financials_stage,
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          last_assistant=last_assistant,
          user_message=user_text,
        )
        if isinstance(normalized_financials_patch, dict) and normalized_financials_patch:
          patch = {f"financials.{k}": v for k, v in normalized_financials_patch.items()}
      candidate = patch.get("milestones")
      if candidate is None:
        candidate = patch.get("ops.milestones")
      if isinstance(candidate, str):
        try:
          candidate = json.loads(candidate)
        except Exception:
          candidate = None
      if isinstance(candidate, list):
        milestone_patch_from_user = [m for m in candidate if isinstance(m, dict)]

    if milestone_patch_from_user:
      existing_milestones = _parse_milestones((ops_json or {}).get("milestones"))
      if existing_milestones:
        milestone_patch_from_user = None

    # Only accept milestone patches when we are explicitly in the milestone-capture step.
    # This keeps Ops sequencing stable (competitive advantage second-to-last, milestone last)
    # and prevents earlier turns from accidentally persisting a milestone out of order.
    if (
      str(focus).strip().lower() == "ops"
      and pending_ops_milestone
      and not _has_confirmed_milestone(ops_json)
    ):
      if milestone_patch_from_user:
        ops_json["milestones"] = milestone_patch_from_user
        _enrich_milestones_timing(ops_json, reference_date=current_date)
        shared_context["operating_model"] = ops_json
        pending_ops_milestone = False

    # Sections can only advance after the explicit final confirmation has been proposed.
    finalize_flags = {
      "ops": ops_finalize_proposed,
      "market": market_finalize_proposed,
      "people": people_finalize_proposed,
    }
    if action == "confirm_proceed" and focus in finalize_flags and not finalize_flags.get(focus):
      action = "continue_chat"

    # If the intake is fully complete, "continue" should guide the user to submission.
    if focus == "done" and action == "continue_chat":
      assistant_text = 'Final review is complete and the facts line up well enough to proceed.\n\nClick "Submit intake" to finish.'
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        marketing_model_json=_refresh_marketing_model(),
        active_focus="done",
        business_facts=business_facts,
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": "done",
          "awaiting_confirmation": False,
          "done": True,
          "action": "ready_to_submit",
          "assistant_message": assistant_text,
        }
      )

    if action == "edit_patch" and patch:
      patch = _normalize_unscoped_patch(patch, focus=focus)

      # Target Market: after we generate a marketing_plan_summary, we present it for
      # confirmation. If the client counters with edits, keep them in this proposal
      # step and re-show the updated marketing_plan_summary (do not restart the
      # full Target Market consult).
      if (
        str(focus or "").strip().lower() == "market"
        and market_finalize_proposed
        and isinstance(patch, dict)
        and ("market.marketing_plan_summary" in patch)
      ):
        business_facts, ops_json, market_json, people_json, financials_json, fulfillment_json = _apply_scoped_patch(
          patch,
          business_facts=business_facts,
          ops_json=ops_json,
          market_json=market_json,
          people_json=people_json,
          financials_json=financials_json,
          fulfillment_json=fulfillment_json,
        )
        assistant_text = sanitize_fact_template(
          str((market_json or {}).get("marketing_plan_summary") or "").strip()
        )
        assistant_text = _strip_acs_codes(assistant_text)
        assistant_text = f"{assistant_text}\n\n{MARKET_CONFIRM_QUESTION}".strip()
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
          target_market_json=market_json,
          marketing_model_json=_refresh_marketing_model(),
          active_focus="market",
          business_facts=business_facts,
          flat_fields=_finalize_flag_field("market", True),
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": "market",
            "awaiting_confirmation": True,
            "done": False,
            "action": "continue",
            "assistant_message": assistant_text,
          }
        )

      people_patch_applied = bool(
        str(focus or "").strip().lower() == "people"
        or any(str(k).strip().lower().startswith("people.") for k in patch.keys())
      )
      baseline_people_json = json.loads(json.dumps(people_json)) if people_json else {}
      business_facts, ops_json, market_json, people_json, financials_json, fulfillment_json = _apply_scoped_patch(
        patch,
        business_facts=business_facts,
        ops_json=ops_json,
        market_json=market_json,
        people_json=people_json,
        financials_json=financials_json,
        fulfillment_json=fulfillment_json,
      )
      marketing_patch_touched = any(
        str(key or "").strip() in {
          "marketing_total_year1",
          "marketing_percent_of_revenue",
          "financials.marketing_total_year1",
          "financials.marketing_percent_of_revenue",
        }
        for key in patch.keys()
      )
      if marketing_patch_touched:
        financials_json = _sync_marketing_field_family(
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          marketing_model_json=marketing_model_json,
        )
      # Keep capacity compatibility coherent (especially monthly/contract cadence).
      ops_json = _normalize_ops_capacity_compat(ops_json)
      try:
        shared_context = dict(shared_context or {})
        shared_context["operating_model"] = ops_json
        shared_context["target_market"] = market_json
        shared_context["people_capability"] = people_json
        shared_context["financials"] = financials_json

        # Persist ops.business_description_summary rendered (no {{fact:...}} placeholders),
        # even when ops is updated via edit patches after finalization.
        try:
          try:
            from fact_templates import render_fact_template  # type: ignore
          except Exception:
            from client_intake_and_finmo.fact_templates import render_fact_template  # type: ignore

          if isinstance(ops_json, dict) and str(ops_json.get("business_description_summary") or "").strip():
            business_facts_for_render = {
              "name": str(business_facts.get("name") or "").strip(),
              "address": str(business_facts.get("address") or "").strip(),
              "start_date": str(business_facts.get("start_date") or "").strip(),
            }
            shared_ctx_for_render = {
              "operating_model": ops_json,
              "target_market": market_json,
              "people_capability": people_json,
              "financials": financials_json,
            }
            ops_json["business_description_summary"] = render_fact_template(
              str(ops_json.get("business_description_summary") or ""),
              shared_context=shared_ctx_for_render,
              business_facts=business_facts_for_render,
            ).strip()
            shared_context["operating_model"] = ops_json
        except Exception:
          pass

        base_year1 = assemble_financials_year1(shared_context, None)
        if _year1_drivers_conflict(financials_year1_json, base_year1):
          financials_year1_json = base_year1
        else:
          financials_year1_json = assemble_financials_year1(shared_context, financials_year1_json)
        financials_json, financials_year1_json = _sync_financials_consult_persistence_state(
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          marketing_model_json=marketing_model_json,
        )
        shared_context["financials"] = financials_json
        if isinstance(financials_year1_json, dict) and financials_year1_json:
          shared_context["financials_year1_json"] = financials_year1_json
        revenue_math_line = build_revenue_math_line(
          financials_year1_json,
          unit_name=str((ops_json or {}).get("unit_name") or "").strip() or None,
        )
        revenue_constraints_snippet = build_revenue_constraints_snippet(
          shared_context,
          financials_year1_json,
          business_start_date=str(business_facts.get("start_date") or "").strip() or None,
        )
        guardrail_signals = build_revenue_guardrail_signals(
          shared_context,
          financials_year1_json,
          business_start_date=str(business_facts.get("start_date") or "").strip() or None,
          fulfillment_context=fulfillment_json,
        )
        driver_signature = build_revenue_driver_signature(financials_year1_json)
        guardrail_acknowledged = (
          get_acknowledged_signature(str(draft_id).strip()) == driver_signature
        )
        guardrail_triggered = bool(guardrail_signals.get("triggered")) and not guardrail_acknowledged
      except Exception:
        pass
      def _coerce_wage(value: Any) -> Optional[float]:
        try:
          return float(value)
        except Exception:
          return None

      def _people_key(item: Dict[str, Any]) -> str:
        name = str(item.get("full_name") or "").strip().lower()
        title = str(item.get("role_title") or "").strip().lower()
        if name or title:
          return f"{name}::{title}".strip(":")
        return ""

      def _role_key(item: Dict[str, Any]) -> str:
        return str(item.get("role_title") or "").strip().lower()

      def _build_wage_map(items: List[Dict[str, Any]], key_fn) -> Dict[str, Optional[float]]:
        mapping: Dict[str, Optional[float]] = {}
        for it in items:
          if not isinstance(it, dict):
            continue
          key = key_fn(it)
          if not key:
            continue
          mapping[key] = _coerce_wage(it.get("annual_wage"))
        return mapping

      def _mark_client_overrides(
        updated_items: List[Dict[str, Any]],
        baseline_map: Dict[str, Optional[float]],
        key_fn,
      ) -> None:
        for it in updated_items:
          if not isinstance(it, dict):
            continue
          key = key_fn(it)
          if not key:
            continue
          new_wage = _coerce_wage(it.get("annual_wage"))
          if new_wage is None:
            continue
          old_wage = baseline_map.get(key)
          if old_wage is None or abs(new_wage - old_wage) > 0.01:
            it["wage_source"] = "client_override"

      try:
        baseline_people_list = (
          baseline_people_json.get("people") if isinstance(baseline_people_json, dict) else []
        )
        baseline_roles_list = (
          baseline_people_json.get("inferred_roles") if isinstance(baseline_people_json, dict) else []
        )
        if isinstance(people_json, dict):
          updated_people_list = people_json.get("people")
          updated_roles_list = people_json.get("inferred_roles")
          if isinstance(updated_people_list, list) and isinstance(baseline_people_list, list):
            _mark_client_overrides(
              updated_people_list, _build_wage_map(baseline_people_list, _people_key), _people_key
            )
          if isinstance(updated_roles_list, list) and isinstance(baseline_roles_list, list):
            _mark_client_overrides(
              updated_roles_list, _build_wage_map(baseline_roles_list, _role_key), _role_key
            )
      except Exception:
        pass

      # People/HR confirm stage: if the client counters/edits the People review, we apply
      # the patch, acknowledge briefly, and advance to Financials WITHOUT re-showing
      # roles/people again (noise). This keeps behavior scoped to People only.
      if (
        str(focus or "").strip().lower() == "people"
        and bool(people_finalize_proposed)
        and isinstance(patch, dict)
        and any(str(k).strip().lower().startswith("people.") for k in patch.keys())
      ):
        # Refresh derived People fields after edits (keeps SQL internally consistent).
        try:
          from people_roles import format_roles_summary  # type: ignore

          if isinstance(people_json, dict):
            roles_now = people_json.get("inferred_roles")
            roles_now = roles_now if isinstance(roles_now, list) else []
            people_json["inferred_roles_summary"] = format_roles_summary(roles_now)
        except Exception:
          pass

        # Render People fact templates (no {{fact:...}} placeholders) for persisted JSON.
        try:
          try:
            from fact_templates import render_fact_template  # type: ignore
          except Exception:
            from client_intake_and_finmo.fact_templates import render_fact_template  # type: ignore

          if isinstance(people_json, dict):
            business_facts_for_render = {
              "name": str(business_facts.get("name") or "").strip(),
              "address": str(business_facts.get("address") or "").strip(),
              "start_date": str(business_facts.get("start_date") or "").strip(),
            }
            shared_ctx_for_render = {
              "operating_model": ops_json,
              "target_market": market_json,
              "people_capability": people_json,
              "financials": financials_json,
            }
            ppl = people_json.get("people")
            if isinstance(ppl, list):
              for p in ppl:
                if not isinstance(p, dict):
                  continue
                for fk, fv in list(p.items()):
                  if isinstance(fv, str) and "{{fact:" in fv:
                    p[fk] = render_fact_template(
                      fv, shared_context=shared_ctx_for_render, business_facts=business_facts_for_render
                    ).strip()
            roles = people_json.get("inferred_roles")
            if isinstance(roles, list):
              for r in roles:
                if not isinstance(r, dict):
                  continue
                for fk, fv in list(r.items()):
                  if isinstance(fv, str) and "{{fact:" in fv:
                    r[fk] = render_fact_template(
                      fv, shared_context=shared_ctx_for_render, business_facts=business_facts_for_render
                    ).strip()
            shared_context["people_capability"] = people_json
        except Exception:
          pass

        next_focus = "financials"
        start_instruction = _start_instruction_for_focus(next_focus)
        turn_messages = [*messages, user_msg, {"role": "user", "content": start_instruction}]
        intake_context_next: Dict[str, Any] = {
          "client_id": client_id,
          "draft_id": str(draft_id).strip(),
          "business_name": business_facts.get("name"),
          "business_start_date": business_facts.get("start_date"),
          "address": business_facts.get("address"),
          "current_date": current_date_iso,
          "business_stage_hint": business_stage_hint,
          "shared_context": shared_context,
          "operating_model_json": ops_json,
          "target_market_json": market_json,
          "people_json": people_json,
          "financials_json": financials_json,
          "fulfillment_json": fulfillment_json,
        }
        intake_context_next["financials_year1_json"] = financials_year1_json
        intake_context_next["revenue_math_line"] = revenue_math_line
        intake_context_next["revenue_constraints_snippet"] = revenue_constraints_snippet
        intake_context_next["revenue_driver_patch"] = revenue_driver_patch
        intake_context_next["revenue_guardrail_triggered"] = guardrail_triggered
        intake_context_next["revenue_guardrail_context_signals"] = guardrail_signals.get("context_signals") or []
        intake_context_next["revenue_guardrail_product_signals"] = guardrail_signals.get("product_signals") or []

        financials_turn, financials_json = _build_financials_live_turn(
          conn=conn,
          intake_context=intake_context_next,
          conversation_messages=turn_messages,
          shared_context=shared_context,
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          guardrail_triggered=guardrail_triggered,
        )
        next_assistant = str(financials_turn.get("assistant_message") or "").strip()
        assistant_text = f"Got it - updated.\n\nGreat, let's move on to Financials.\n\n{next_assistant}".strip()
        assistant_text = sanitize_fact_template(str(assistant_text or "").strip())
        assistant_text = _append_constraints_snippet(
          assistant_text,
          revenue_constraints_snippet,
          messages,
          force=True,
        )

        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
          confirmations={"people": True},
          marketing_model_json=_refresh_marketing_model(),
          active_focus=next_focus,
          business_facts=business_facts,
          people_json=people_json,
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          flat_fields=_finalize_flag_field("people", False),
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": next_focus,
            "awaiting_confirmation": False,
            "done": False,
            "action": "confirm_proceed",
            "assistant_message": assistant_text,
          }
        )
      business_type_touched = False
      if isinstance(patch, dict):
        business_type_touched = "ops.business_type" in patch
      try:
        try:
          from business_type_naics import get_naics_from_business_type  # type: ignore
        except Exception:
          from client_intake_and_finmo.business_type_naics import (  # type: ignore
            get_naics_from_business_type,
          )
        if business_type_touched:
          bt_candidates = ops_json.get("business_type_candidates")
          if not isinstance(bt_candidates, list):
            bt_candidates = []
          ops_json["business_type"] = _normalize_business_type_from_candidates(
            ops_json.get("business_type"),
            bt_candidates,
          )
        if business_type_touched:
          if ops_json.get("business_type"):
            ops_json["business_naics_6"] = get_naics_from_business_type(
              conn, ops_json.get("business_type")
            )
          else:
            ops_json["business_naics_6"] = None
          logger.warning(
            "business_type_persisted business_type=%r business_naics_6=%r",
            ops_json.get("business_type"),
            ops_json.get("business_naics_6"),
          )
        elif ops_json.get("business_type") and not ops_json.get("business_naics_6"):
          bt_candidates = ops_json.get("business_type_candidates")
          if not isinstance(bt_candidates, list):
            bt_candidates = []
          ops_json["business_type"] = _normalize_business_type_from_candidates(
            ops_json.get("business_type"),
            bt_candidates,
          )
          ops_json["business_naics_6"] = get_naics_from_business_type(
            conn, ops_json.get("business_type")
          )
      except Exception:
        if business_type_touched and "business_naics_6" not in ops_json:
          ops_json["business_naics_6"] = None
      try:
        _enrich_milestones_timing(ops_json, reference_date=current_date)
      except Exception:
        pass
      try:
        from people_roles import (  # type: ignore
          apply_oews_wages,
          apply_oews_wages_to_people,
          format_roles_summary,
        )

        people_list = people_json.get("people") if isinstance(people_json, dict) else None
        people_list = people_list if isinstance(people_list, list) else []
        if people_list:
          enriched_people = apply_oews_wages_to_people(
            conn,
            people=people_list,
            business_type=ops_json.get("business_type"),
            business_stage=ops_json.get("business_stage"),
            address_state=business_facts.get("address_state"),
            address=business_facts.get("address"),
            business_naics_6=ops_json.get("business_naics_6"),
          )
          people_json["people"] = enriched_people

        roles = people_json.get("inferred_roles") if isinstance(people_json, dict) else None
        roles = roles if isinstance(roles, list) else []
        if roles:
          enriched_roles = apply_oews_wages(
            conn,
            roles=roles,
            business_type=ops_json.get("business_type"),
            business_stage=ops_json.get("business_stage"),
            address_state=business_facts.get("address_state"),
            address=business_facts.get("address"),
            business_naics_6=ops_json.get("business_naics_6"),
          )
          people_json["inferred_roles"] = enriched_roles
          people_json["inferred_roles_summary"] = format_roles_summary(enriched_roles)
      except Exception:
        pass
      active_focus_out = focus
      status_out: str | None = None
      completed_out = False
      confirm_question_live = _detect_confirm_question(last_assistant)

      # People/HR: if we're on the People section-final confirmation step and the client
      # counters with edits, acknowledge the change and advance (do not re-show the full
      # People recap/wage proposal again).
      if (
        str(focus).strip().lower() == "people"
        and active_focus_out == focus
        and confirm_question_live == PEOPLE_CONFIRM_QUESTION
      ):
        next_focus = "financials"
        start_instruction = _start_instruction_for_focus(next_focus)
        turn_messages = [*messages, user_msg, {"role": "user", "content": start_instruction}]
        intake_context_next: Dict[str, Any] = {
          "client_id": client_id,
          "draft_id": str(draft_id).strip(),
          "business_name": business_facts.get("name"),
          "business_start_date": business_facts.get("start_date"),
          "address": business_facts.get("address"),
          "current_date": current_date_iso,
          "business_stage_hint": business_stage_hint,
          "shared_context": shared_context,
          "operating_model_json": ops_json,
          "target_market_json": market_json,
          "people_json": people_json,
          "financials_json": financials_json,
          "fulfillment_json": fulfillment_json,
        }
        intake_context_next["financials_year1_json"] = financials_year1_json
        intake_context_next["revenue_math_line"] = revenue_math_line
        intake_context_next["revenue_constraints_snippet"] = revenue_constraints_snippet
        intake_context_next["revenue_driver_patch"] = revenue_driver_patch
        intake_context_next["revenue_guardrail_triggered"] = guardrail_triggered
        intake_context_next["revenue_guardrail_context_signals"] = guardrail_signals.get("context_signals") or []
        intake_context_next["revenue_guardrail_product_signals"] = guardrail_signals.get("product_signals") or []

        financials_turn, financials_json = _build_financials_live_turn(
          conn=conn,
          intake_context=intake_context_next,
          conversation_messages=turn_messages,
          shared_context=shared_context,
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          guardrail_triggered=guardrail_triggered,
        )
        next_assistant = str(financials_turn.get("assistant_message") or "").strip()
        next_assistant = sanitize_fact_template(str(next_assistant or "").strip())
        next_assistant = _append_constraints_snippet(
          next_assistant,
          revenue_constraints_snippet,
          messages,
          force=True,
        )
        assistant_text = f"Got it, updated.\n\nGreat, let's move on to Financials.\n\n{next_assistant}".strip()

        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
          people_json=people_json,
          financials_json=financials_json,
          marketing_model_json=_refresh_marketing_model(),
          active_focus=next_focus,
          confirmations={"people": True},
          business_facts=business_facts,
          flat_fields=_finalize_flag_field("people", True),
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": next_focus,
            "awaiting_confirmation": False,
            "done": False,
            "action": "confirm_proceed",
            "assistant_message": assistant_text,
          }
        )

      # If the draft was already marked complete, edits must reopen the affected
      # section so the persisted SQL state stays authoritative again.
      if str(draft_status).strip().lower() == "completed" or focus == "done":
        status_out = "in_progress"
        patch_focus = next(
          (
            str(key).split(".", 1)[0].strip().lower()
            for key in (patch or {}).keys()
            if str(key).count(".") == 1
            and str(key).split(".", 1)[0].strip().lower() in {"ops", "market", "people", "financials"}
          ),
          "",
        )
        active_focus_out = patch_focus or ("financials" if focus == "done" else focus)

      # For edit patches, the intent router is used only to interpret intent and
      # produce the deterministic patch. The domain consultant generates the next
      # conversational turn. Showing both messages causes duplicated acknowledgements
      # and repeated questions.
      #
      # Exception: if the edit re-opens a completed intake into final review, keep the
      # router acknowledgement so the user clearly sees the update before the audit.
      assistant_text = router_msg if (confirm_question_live or active_focus_out != focus) else ""
      # If we're awaiting a section-final confirmation, re-ask the confirm question
      if confirm_question_live:
        assistant_text = f"{assistant_text}\n\n{confirm_question_live}".strip()
      else:
        # Otherwise, keep the intake moving: acknowledge the edit and then continue
        # with the next question for the current focus (no standstills).
        shared_context_live = dict(shared_context or {})
        shared_context_live["operating_model"] = ops_json
        shared_context_live["target_market"] = market_json
        shared_context_live["people_capability"] = people_json
        shared_context_live["financials"] = financials_json

        intake_context_followup = {
          "client_id": client_id,
          "draft_id": str(draft_id).strip(),
          "business_name": business_facts.get("name"),
          "business_start_date": business_facts.get("start_date"),
          "address": business_facts.get("address"),
          "address_street": payload.get("address_street"),
          "address_city": payload.get("address_city"),
          "address_state": payload.get("address_state"),
          "address_zip": payload.get("address_zip"),
          "address_country": payload.get("address_country"),
          "current_date": current_date_iso,
          "business_stage_hint": business_stage_hint,
          "shared_context": shared_context_live,
          "operating_model_json": ops_json,
          "target_market_json": market_json,
          "people_json": people_json,
          "financials_json": financials_json,
          "fulfillment_json": fulfillment_json,
        }
        intake_context_followup["financials_year1_json"] = financials_year1_json
        intake_context_followup["revenue_math_line"] = revenue_math_line
        intake_context_followup["revenue_constraints_snippet"] = revenue_constraints_snippet
        intake_context_followup["revenue_driver_patch"] = revenue_driver_patch
        intake_context_followup["revenue_guardrail_triggered"] = guardrail_triggered
        intake_context_followup["revenue_guardrail_context_signals"] = guardrail_signals.get("context_signals") or []
        intake_context_followup["revenue_guardrail_product_signals"] = guardrail_signals.get("product_signals") or []

        followup_focus = active_focus_out if active_focus_out != "done" else focus
        if followup_focus == "market":
          consumer_type = str((ops_json or {}).get("consumer_type") or "consumer").strip().lower()
          if consumer_type not in ("consumer", "b2b", "mixed"):
            consumer_type = "consumer"
          intake_context_followup["consumer_type"] = consumer_type

        if followup_focus == "ops":
          followup_turn = consultant_chat_turn(
            intake_context=intake_context_followup, conversation_messages=[*messages, user_msg]
          )
        elif followup_focus == "market":
          followup_turn = target_market_chat_turn(
            intake_context=intake_context_followup, conversation_messages=[*messages, user_msg]
          )
        elif followup_focus == "people":
          followup_turn = people_capability_chat_turn(
            intake_context=intake_context_followup, conversation_messages=[*messages, user_msg]
          )
        elif followup_focus == "financials":
          followup_turn, financials_json = _build_financials_live_turn(
            conn=conn,
            intake_context=intake_context_followup,
            conversation_messages=[*messages, user_msg],
            shared_context=shared_context,
            financials_json=financials_json,
            financials_year1_json=financials_year1_json,
            guardrail_triggered=guardrail_triggered,
          )
          if bool((followup_turn or {}).get("transition_to_done")):
            assistant_final = str((followup_turn or {}).get("assistant_message") or "").strip()
            _persist_intake_completion(
              new_messages=[user_msg, {"role": "assistant", "content": assistant_final}],
              ops_value=ops_json,
              market_value=market_json,
              people_value=people_json,
              financials_value=financials_json,
              financials_year1_value=financials_year1_json,
              marketing_value=_refresh_marketing_model(),
              confirmations_value={"financials": True},
              flat_fields_value=_finalize_flag_field("financials", True),
            )
            return jsonify(
              {
                "status": "ok",
                "draft_id": str(draft_id).strip(),
                "client_id": client_id,
                "active_focus": "done",
                "awaiting_confirmation": False,
                "done": True,
                "action": "intake_complete",
                "assistant_message": assistant_final,
              }
            )
        else:
          followup_turn = {"assistant_message": ""}

        if followup_focus == "ops":
          ops_json = _apply_model_ops_patch(
            ops_json, followup_turn.get("patch") if isinstance(followup_turn, dict) else None
          )
          try:
            shared_context["operating_model"] = ops_json
          except Exception:
            pass

        followup_text = sanitize_fact_template(str(followup_turn.get("assistant_message") or "").strip())
        if focus == "market":
          followup_text = _strip_acs_codes(followup_text)
        if followup_focus == "financials":
          followup_text = _append_constraints_snippet(
            followup_text,
            revenue_constraints_snippet,
            messages,
            force=True,
          )
        if followup_focus == "ops" and not followup_text:
          followup_text = _fallback_ops_followup_question(ops_json)
        if followup_focus == "ops":
          followup_finalize_ready = bool(followup_turn.get("finalize_ready", False))
          followup_attempts_finalize = (
            followup_finalize_ready
            or (OPS_CONFIRM_QUESTION.lower() in str(followup_text or "").lower())
          )
          if followup_attempts_finalize:
            if not str((ops_json or {}).get("competitive_advantage") or "").strip():
              confirmed_restatement = _extract_confirmed_restatement(messages)
              proposed_advantage = _propose_ops_competitive_advantage(
                ops_json=ops_json,
                business_facts=business_facts,
                shared_context=shared_context,
                confirmed_restatement=confirmed_restatement,
              )
              proposed_advantage = sanitize_fact_template(str(proposed_advantage or "").strip())
              assistant_text = (
                f"{COMPETITIVE_ADVANTAGE_PREFIX} {proposed_advantage}\n\n"
                f"{COMPETITIVE_ADVANTAGE_QUESTION}"
              ).strip()
              append_messages(
                conn,
                draft_id=str(draft_id).strip(),
                new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
                operating_model_json=ops_json,
                marketing_model_json=_refresh_marketing_model(),
                active_focus="ops",
                business_facts=business_facts,
                pending_ops_milestone_json=pending_ops_milestone,
                flat_fields=_finalize_flag_field("ops", False),
              )
              return jsonify(
                {
                  "status": "ok",
                  "draft_id": str(draft_id).strip(),
                  "client_id": client_id,
                  "active_focus": "ops",
                  "awaiting_confirmation": True,
                  "done": False,
                  "action": "continue",
                  "assistant_message": assistant_text,
                }
              )

            if (
              str((ops_json or {}).get("competitive_advantage") or "").strip()
              and not _has_confirmed_milestone(ops_json)
              and not pending_ops_milestone
            ):
              assistant_text = OPS_MILESTONE_QUESTION
              pending_ops_milestone = True
              append_messages(
                conn,
                draft_id=str(draft_id).strip(),
                new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
                operating_model_json=ops_json,
                marketing_model_json=_refresh_marketing_model(),
                active_focus="ops",
                business_facts=business_facts,
                pending_ops_milestone_json=True,
                flat_fields=_finalize_flag_field("ops", False),
              )
              return jsonify(
                {
                  "status": "ok",
                  "draft_id": str(draft_id).strip(),
                  "client_id": client_id,
                  "active_focus": "ops",
                  "awaiting_confirmation": False,
                  "done": False,
                  "action": "continue",
                  "assistant_message": assistant_text,
                }
              )

            business_type_candidates = ops_json.get("business_type_candidates")
            if not isinstance(business_type_candidates, list):
              business_type_candidates = []
            intake_context_followup["business_type_candidates"] = business_type_candidates
            final_messages = [*messages, user_msg, {"role": "assistant", "content": followup_text}]
            final_obj = consultant_finalize(
              intake_context=intake_context_followup, conversation_messages=final_messages
            )
            for k, v in list(final_obj.items() if isinstance(final_obj, dict) else []):
              if isinstance(v, str):
                final_obj[k] = sanitize_fact_template(v)
            existing_advantage = str((ops_json or {}).get("competitive_advantage") or "").strip()
            if (
              existing_advantage
              and isinstance(final_obj, dict)
              and not str(final_obj.get("competitive_advantage") or "").strip()
            ):
              final_obj["competitive_advantage"] = existing_advantage
            try:
              try:
                from business_type_naics import get_naics_from_business_type  # type: ignore
              except Exception:
                from client_intake_and_finmo.business_type_naics import (  # type: ignore
                  get_naics_from_business_type,
                )
              if final_obj.get("business_type"):
                final_obj["business_naics_6"] = get_naics_from_business_type(
                  conn, final_obj.get("business_type")
                )
            except Exception:
              if "business_naics_6" not in final_obj:
                final_obj["business_naics_6"] = None
            try:
              _enrich_milestones_timing(final_obj, reference_date=current_date)
            except Exception:
              pass

            ops_json = final_obj
            try:
              shared_context = dict(shared_context or {})
              shared_context["operating_model"] = ops_json
              shared_context["target_market"] = market_json
              shared_context["people_capability"] = people_json
              shared_context["financials"] = financials_json
            except Exception:
              pass

            next_focus = "market"
            start_instruction = _start_instruction_for_focus(next_focus)
            turn_messages = [*messages, user_msg, {"role": "user", "content": start_instruction}]
            intake_context_next: Dict[str, Any] = {
              "client_id": client_id,
              "draft_id": str(draft_id).strip(),
              "business_name": business_facts.get("name"),
              "business_start_date": business_facts.get("start_date"),
              "address": business_facts.get("address"),
              "current_date": current_date_iso,
              "business_stage_hint": business_stage_hint,
              "shared_context": shared_context,
              "operating_model_json": ops_json,
              "target_market_json": market_json,
              "people_json": people_json,
              "financials_json": financials_json,
              "fulfillment_json": fulfillment_json,
            }
            consumer_type = str((ops_json or {}).get("consumer_type") or "consumer").strip().lower()
            if consumer_type not in ("consumer", "b2b", "mixed"):
              consumer_type = "consumer"
            intake_context_next["consumer_type"] = consumer_type
            market_turn = target_market_chat_turn(
              intake_context=intake_context_next, conversation_messages=turn_messages
            )
            next_assistant = str((market_turn or {}).get("assistant_message") or "").strip()
            assistant_text = f"Great, let's move on to Target Market.\n\n{next_assistant}".strip()
            assistant_text = _strip_acs_codes(sanitize_fact_template(str(assistant_text or "").strip()))

            append_messages(
              conn,
              draft_id=str(draft_id).strip(),
              new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
              operating_model_json=ops_json,
              target_market_json=market_json,
              marketing_model_json=_refresh_marketing_model(),
              active_focus=next_focus,
              confirmations={"ops": True},
              business_facts=business_facts,
              flat_fields=_finalize_flag_field("ops", True),
            )
            return jsonify(
              {
                "status": "ok",
                "draft_id": str(draft_id).strip(),
                "client_id": client_id,
                "active_focus": next_focus,
                "awaiting_confirmation": False,
                "done": False,
                "action": "confirm_proceed",
                "assistant_message": assistant_text,
              }
            )
        if followup_text:
          if assistant_text:
            assistant_text = f"{assistant_text}\n\n{followup_text}".strip()
          else:
            assistant_text = followup_text
      assistant_text = sanitize_fact_template(str(assistant_text or "").strip())
      if focus == "market":
        assistant_text = _strip_acs_codes(assistant_text)
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        operating_model_json=ops_json,
        target_market_json=market_json,
        people_json=people_json if people_patch_applied else None,
        financials_json=financials_json,
        financials_year1_json=financials_year1_json,
        fulfillment_json=fulfillment_json,
        marketing_model_json=_refresh_marketing_model(),
        active_focus=active_focus_out,
        business_facts=business_facts,
        status=status_out,
        completed=completed_out,
        pending_ops_milestone_json=pending_ops_milestone
        if str(active_focus_out).strip().lower() == "ops"
        else None,
        flat_fields=_finalize_flag_field(focus, False),
      )

      action_out = "edit_patch"
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": active_focus_out,
          "awaiting_confirmation": bool(confirm_question_live),
          "done": bool(active_focus_out == "done"),
          "action": action_out,
          "assistant_message": assistant_text,
        }
      )

    if action == "confirm_proceed":
      confirmations: Dict[str, bool] = {focus: True}
      next_focus = _next_focus(focus)

      # Generate the first question for the next focus immediately.
      start_instruction = _start_instruction_for_focus(next_focus)
      turn_messages = [*messages, user_msg, {"role": "user", "content": start_instruction}]
      intake_context_next: Dict[str, Any] = {
        "client_id": client_id,
        "draft_id": str(draft_id).strip(),
        "business_name": business_facts.get("name"),
        "business_start_date": business_facts.get("start_date"),
        "address": business_facts.get("address"),
        "consumer_type": (ops_json or {}).get("consumer_type"),
        "current_date": current_date_iso,
        "business_stage_hint": business_stage_hint,
        "shared_context": shared_context,
      }
      intake_context_next["financials_year1_json"] = financials_year1_json
      intake_context_next["revenue_math_line"] = revenue_math_line
      intake_context_next["revenue_constraints_snippet"] = revenue_constraints_snippet
      intake_context_next["revenue_driver_patch"] = revenue_driver_patch
      intake_context_next["revenue_guardrail_triggered"] = guardrail_triggered
      intake_context_next["revenue_guardrail_context_signals"] = guardrail_signals.get("context_signals") or []
      intake_context_next["revenue_guardrail_product_signals"] = guardrail_signals.get("product_signals") or []

      if next_focus == "ops":
        next_assistant = consultant_chat_turn(
          intake_context=intake_context_next, conversation_messages=turn_messages
        )["assistant_message"]
      elif next_focus == "market":
        market_turn = target_market_chat_turn(
          intake_context=intake_context_next, conversation_messages=turn_messages
        )
        next_assistant = str((market_turn or {}).get("assistant_message") or "").strip()
      elif next_focus == "people":
        next_assistant = people_capability_chat_turn(
          intake_context=intake_context_next, conversation_messages=turn_messages
        )["assistant_message"]
      elif next_focus == "financials":
        financials_turn, financials_json = _build_financials_live_turn(
          conn=conn,
          intake_context=intake_context_next,
          conversation_messages=turn_messages,
          shared_context=shared_context,
          financials_json=financials_json,
          financials_year1_json=financials_year1_json,
          guardrail_triggered=guardrail_triggered,
        )
        next_assistant = str(financials_turn.get("assistant_message") or "").strip()
      else:
        next_assistant = "Continue."

      transition = ""
      if next_focus == "market":
        transition = "Great, let's move on to Target Market."
      elif next_focus == "people":
        transition = "Great, let's move on to Human Resources."
      elif next_focus == "financials":
        transition = "Great, let's move on to Financials."
      elif next_focus == "done":
        transition = ""
      if transition:
        next_assistant = f"{transition}\n\n{next_assistant}".strip() if next_assistant else transition

      next_assistant = sanitize_fact_template(str(next_assistant or "").strip())
      if next_focus == "market":
        next_assistant = _strip_acs_codes(next_assistant)
      if next_focus == "financials":
        next_assistant = _append_constraints_snippet(
          next_assistant,
          revenue_constraints_snippet,
          messages,
          force=True,
        )

      if next_focus == "done":
        next_assistant = str(next_assistant or "").strip() or "Intake complete."
        _persist_intake_completion(
          new_messages=[user_msg, {"role": "assistant", "content": next_assistant}],
          ops_value=ops_json,
          market_value=market_json,
          people_value=people_json,
          financials_value=financials_json,
          financials_year1_value=financials_year1_json,
          marketing_value=_refresh_marketing_model(),
          confirmations_value=confirmations,
          flat_fields_value=_finalize_flag_field(focus, False),
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": "done",
            "awaiting_confirmation": False,
            "done": True,
            "action": "intake_complete",
            "assistant_message": next_assistant,
          }
        )

      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": next_assistant}],
        confirmations=confirmations,
        operating_model_json=ops_json if next_focus == "done" else None,
        marketing_model_json=marketing_model_json if next_focus == "done" else _refresh_marketing_model(),
        active_focus=next_focus,
        business_facts=business_facts,
        target_market_json=market_json if next_focus in {"market", "done"} else None,
        people_json=people_json if next_focus == "done" else None,
        financials_json=financials_json if next_focus in {"financials", "done"} else None,
        financials_year1_json=financials_year1_json if next_focus == "done" else None,
        flat_fields=_finalize_flag_field(focus, False),
        status="completed" if next_focus == "done" else None,
        completed=bool(next_focus == "done"),
      )

      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": next_focus,
          "awaiting_confirmation": False,
          "done": bool(next_focus == "done"),
          "action": "confirm_proceed",
          "assistant_message": next_assistant,
        }
      )

    if action == "confirm_clarify":
      assistant_text = sanitize_fact_template(router_msg)
      if focus == "market":
        assistant_text = _strip_acs_codes(assistant_text)
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        target_market_json=market_json if focus == "market" else None,
        marketing_model_json=_refresh_marketing_model(),
        active_focus=focus,
        business_facts=business_facts,
        pending_ops_milestone_json=pending_ops_milestone if focus == "ops" else None,
        flat_fields=_finalize_flag_field(focus, False),
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": focus,
          "awaiting_confirmation": bool(confirm_question),
          "done": False,
          "action": "confirm_clarify",
          "assistant_message": assistant_text,
        }
      )

    if action == "answer_readonly":
      assistant_text = sanitize_fact_template(router_msg)
      if focus == "market":
        assistant_text = _strip_acs_codes(assistant_text)
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        target_market_json=market_json if focus == "market" else None,
        marketing_model_json=_refresh_marketing_model(),
        active_focus=focus,
        business_facts=business_facts,
        pending_ops_milestone_json=pending_ops_milestone if focus == "ops" else None,
        flat_fields=_finalize_flag_field(focus, False),
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": focus,
          "awaiting_confirmation": bool(confirm_question),
          "done": False,
          "action": "answer_readonly",
          "assistant_message": assistant_text,
        }
      )

    # continue_chat: run the current focus consult normally.
    intake_context = {
      "client_id": client_id,
      "draft_id": str(draft_id).strip(),
      "business_name": business_facts.get("name"),
      "business_start_date": business_facts.get("start_date"),
      "address": business_facts.get("address"),
      "address_street": payload.get("address_street"),
      "address_city": payload.get("address_city"),
      "address_state": payload.get("address_state"),
      "address_zip": payload.get("address_zip"),
      "address_country": payload.get("address_country"),
      "current_date": current_date_iso,
      "business_stage_hint": business_stage_hint,
      "shared_context": shared_context,
      "operating_model_json": ops_json,
      "target_market_json": market_json,
      "people_json": people_json,
      "financials_json": financials_json,
      "fulfillment_json": fulfillment_json,
    }
    intake_context["financials_year1_json"] = financials_year1_json
    intake_context["revenue_math_line"] = revenue_math_line
    intake_context["revenue_constraints_snippet"] = revenue_constraints_snippet
    intake_context["revenue_driver_patch"] = revenue_driver_patch
    intake_context["revenue_guardrail_triggered"] = guardrail_triggered
    intake_context["revenue_guardrail_context_signals"] = guardrail_signals.get("context_signals") or []
    intake_context["revenue_guardrail_product_signals"] = guardrail_signals.get("product_signals") or []
    if focus == "market":
      consumer_type = str((ops_json or {}).get("consumer_type") or "consumer").strip().lower()
      if consumer_type not in ("consumer", "b2b", "mixed"):
        consumer_type = "consumer"
      intake_context["consumer_type"] = consumer_type
    if focus == "ops":
      turn = consultant_chat_turn(
        intake_context=intake_context, conversation_messages=[*messages, user_msg]
      )
    elif focus == "market":
      turn = target_market_chat_turn(
        intake_context=intake_context, conversation_messages=[*messages, user_msg]
      )
    elif focus == "people":
      turn = people_capability_chat_turn(
        intake_context=intake_context, conversation_messages=[*messages, user_msg]
      )
    elif focus == "financials":
      turn, financials_json = _build_financials_live_turn(
        conn=conn,
        intake_context=intake_context,
        conversation_messages=[*messages, user_msg],
        shared_context=shared_context,
        financials_json=financials_json,
        financials_year1_json=financials_year1_json,
        guardrail_triggered=guardrail_triggered,
      )
    else:
      turn = {"assistant_message": "Continue.", "finalize_ready": False}

    assistant_text = sanitize_fact_template(str(turn.get("assistant_message") or "").strip())
    if focus == "market":
      assistant_text = _strip_acs_codes(assistant_text)
    if focus == "financials":
      assistant_text = _append_constraints_snippet(
        assistant_text,
        revenue_constraints_snippet,
        messages,
        force=True,
      )

    # Ops: apply model-produced structured patch immediately (no controller parsing).
    if str(focus).strip().lower() == "ops" and isinstance(turn, dict):
      ops_json = _apply_model_ops_patch(ops_json, turn.get("patch"))
      try:
        shared_context["operating_model"] = ops_json
      except Exception:
        pass

    # Target Market: apply model-produced structured patch immediately (no controller parsing).
    if str(focus).strip().lower() == "market" and isinstance(turn, dict):
      patch_obj = turn.get("patch")
      if isinstance(patch_obj, dict) and isinstance(market_json, dict):
        allowed_keys = {
          "consumer_type",
          "gender_age_intent",
          "income_intent",
          "b2b_industry_terms",
          "b2b_size_bands",
          "b2b_age_bands",
        }
        for k, v in patch_obj.items():
          key = str(k or "").strip()
          if not key:
            continue
          if key.startswith("market."):
            key = key.split(".", 1)[1].strip()
          if key in allowed_keys:
            # In strict json_schema, the model must always output every patch key.
            # We treat null values as "no change" to avoid wiping prior answers.
            if v is None:
              continue
            market_json[key] = v
        try:
          shared_context["target_market"] = market_json
        except Exception:
          pass

    # People: persist raw structured person facts incrementally during collection.
    if str(focus).strip().lower() == "people":
      try:
        people_progress_context = dict(intake_context)
        people_progress_context["existing_people_capability_json"] = people_json
        extracted_people = extract_people_collection_progress(
          intake_context=people_progress_context,
          conversation_messages=[
            *messages,
            user_msg,
            {"role": "assistant", "content": assistant_text},
          ],
        )
        extracted_people_list = (
          extracted_people.get("people") if isinstance(extracted_people, dict) else None
        )
        if isinstance(extracted_people_list, list) and extracted_people_list:
          next_people_json = dict(people_json or {})
          next_people_json["people"] = extracted_people_list
          next_people_json["business_naics_6"] = ops_json.get("business_naics_6")
          people_json = next_people_json
          try:
            shared_context["people_capability"] = people_json
          except Exception:
            pass
      except Exception:
        pass

    finalize_ready = bool(turn.get("finalize_ready", False))
    review_ready = bool(turn.get("review_ready", False))
    # Controller-owned restatement-confirmation state: only classify acceptance on the
    # client reply to the explicit restatement confirmation prompt.
    if (
      str(focus).strip().lower() == "ops"
      and bool(turn.get("is_restatement_confirmation_prompt", False))
      and not bool((ops_json or {}).get("business_type_candidates_locked"))
    ):
      if isinstance(ops_json, dict):
        ops_json["_ops_restatement_pending"] = True
        ops_json["_ops_restatement_text"] = assistant_text
      ops_restatement_meta_touched = True
    if str(focus).strip().lower() == "people" and review_ready and not finalize_ready:
      finalize_ready = True
    if str(focus).strip().lower() == "financials":
      finalize_ready = False

    if str(focus).strip().lower() == "ops" and assistant_text:
      question_count = assistant_text.count("?")
      if question_count > 1:
        first_part = assistant_text.split("?", 1)[0].strip()
        if first_part:
          assistant_text = f"{first_part}?"
        finalize_ready = False
      # If the Ops consultant produced the section-final confirm question in normal chat,
      # treat it as a finalize attempt so we can enforce milestone-first and then auto-advance.
      if OPS_CONFIRM_QUESTION.lower() in assistant_text.lower():
        finalize_ready = True

    ops_ready_for_wrap = False
    # Ops hard gate: do not allow the ops "finalize-ready" path (which triggers competitive
    # advantage/milestone injection and summary auto-skip) unless capacity has been captured.
    #
    # We avoid brittle heuristic phrase-matching by taking a structured snapshot via
    # consultant_finalize() and checking the numeric capacity fields directly.
    if str(focus).strip().lower() == "ops" and (finalize_ready or not assistant_text):
      try:
        gate_messages = [*messages, user_msg, {"role": "assistant", "content": assistant_text}]
        business_type_candidates = (ops_json or {}).get("business_type_candidates")
        if not isinstance(business_type_candidates, list):
          business_type_candidates = []
        gate_context = dict(intake_context)
        gate_context["business_type_candidates"] = business_type_candidates
        gate_obj = consultant_finalize(intake_context=gate_context, conversation_messages=gate_messages)

        def _missing_number(value: Any) -> bool:
          if value is None:
            return True
          if isinstance(value, bool):
            return True
          try:
            return float(value) <= 0
          except Exception:
            return True

        def _final_obj_missing_capacity(obj: Any) -> bool:
          if not isinstance(obj, dict):
            return True
          lob_models = obj.get("lob_models")
          products: List[Dict[str, Any]] = []
          if isinstance(lob_models, list):
            for lob in lob_models:
              if not isinstance(lob, dict):
                continue
              prods = lob.get("products")
              if not isinstance(prods, list):
                continue
              for p in prods:
                if isinstance(p, dict):
                  products.append(p)
          if products:
            for p in products:
              if _missing_number(p.get("units_per_period_capacity")) and _missing_number(
                p.get("units_per_week_capacity")
              ):
                return True
            return False
          return _missing_number(obj.get("units_per_period_capacity")) and _missing_number(
            obj.get("units_per_week_capacity")
          )

        def _final_obj_missing_utilization(obj: Any) -> bool:
          if not isinstance(obj, dict):
            return True
          lob_models = obj.get("lob_models")
          products: List[Dict[str, Any]] = []
          if isinstance(lob_models, list):
            for lob in lob_models:
              if not isinstance(lob, dict):
                continue
              prods = lob.get("products")
              if not isinstance(prods, list):
                continue
              for p in prods:
                if isinstance(p, dict):
                  products.append(p)
          if products:
            for p in products:
              if _missing_number(p.get("utilization_rate")):
                return True
            return False
          return _missing_number(obj.get("utilization_rate"))

        if _final_obj_missing_capacity(gate_obj):
          capacity_target = _find_missing_capacity_target(gate_obj, fallback_ops=ops_json)
          captured_capacity = False
          numeric_capacity_value = _extract_single_compact_number(message)
          if (
            capacity_target
            and numeric_capacity_value is not None
            and _looks_like_capacity_prompt(last_assistant)
          ):
            updated_gate_obj = _apply_capacity_target_value(
              gate_obj,
              capacity_target,
              float(numeric_capacity_value),
            )
            ops_json = _apply_capacity_snapshot_to_ops_json(
              ops_json,
              updated_gate_obj,
              capacity_target,
            )
            shared_context = dict(shared_context or {})
            shared_context["operating_model"] = ops_json
            intake_context = dict(intake_context or {})
            intake_context["shared_context"] = shared_context
            intake_context["operating_model_json"] = ops_json
            gate_context = dict(gate_context or {})
            gate_context["shared_context"] = shared_context
            gate_context["operating_model_json"] = ops_json
            try:
              business_type_candidates = (ops_json or {}).get("business_type_candidates")
              if isinstance(business_type_candidates, list):
                intake_context["business_type_candidates"] = business_type_candidates
            except Exception:
              pass
            follow_up_turn = consultant_chat_turn(
              intake_context=intake_context,
              conversation_messages=[*messages, user_msg],
            ) or {}
            assistant_text = sanitize_fact_template(
              str((follow_up_turn or {}).get("assistant_message") or "").strip()
            )
            finalize_ready = bool(follow_up_turn.get("finalize_ready"))
            captured_capacity = True
          if not captured_capacity:
            if capacity_target:
              assistant_text = _build_capacity_target_question(capacity_target)
            else:
              assistant_text = (
                "To make planning realistic, in a fully busy period, about how many units do you expect you can handle?"
              ).strip()
            finalize_ready = False
        elif _final_obj_missing_utilization(gate_obj):
          def _first_product_missing_utilization(obj: Any) -> Optional[Dict[str, Any]]:
            if not isinstance(obj, dict):
              return None
            lob_models = obj.get("lob_models")
            if isinstance(lob_models, list):
              for lob in lob_models:
                if not isinstance(lob, dict):
                  continue
                products = lob.get("products")
                if not isinstance(products, list):
                  continue
                for product in products:
                  if isinstance(product, dict) and _missing_number(product.get("utilization_rate")):
                    return product
            return obj if _missing_number(obj.get("utilization_rate")) else None

          missing_product = _first_product_missing_utilization(gate_obj) or {}
          util_label = str(
            missing_product.get("product_name")
            or missing_product.get("unit_name")
            or (ops_json or {}).get("unit_name")
            or "this offering"
          ).strip()
          assistant_text = (
            f"For Year 1 planning, what average utilization do you want to assume for {util_label} "
            "(for example, 70% of practical capacity)?"
          ).strip()
          finalize_ready = False
        else:
          missing_period_product = _first_contract_product_missing_periods(gate_obj)
          if missing_period_product:
            period_label = str(
              missing_period_product.get("product_name")
              or missing_period_product.get("unit_name")
              or (ops_json or {}).get("unit_name")
              or "this contract offering"
            ).strip()
            assistant_text = (
              f"For {period_label}, about how many times does one active slot typically turn over in a year? "
              "(For example, if one matter usually lasts about 3 months, that would be about 4 turns per year.)"
            ).strip()
            finalize_ready = False
          else:
            # Competitive advantage should be second-to-last and milestones last.
            # For multi-product ops, readiness must come from the product rows plus
            # the business-wide top-level fields, not placeholder top-level unit fields.
            if _ops_ready_for_wrap_from_gate_obj(gate_obj):
              ops_ready_for_wrap = True
              finalize_ready = True
            else:
              finalize_ready = False
      except Exception:
        # Best-effort: if gating fails, preserve existing behavior.
        pass

    if str(focus).strip().lower() == "ops" and not assistant_text and not finalize_ready:
      assistant_text = _fallback_ops_followup_question(ops_json)

    if (
      str(focus).strip().lower() == "ops"
      and finalize_ready
      and ops_ready_for_wrap
      and not str((ops_json or {}).get("competitive_advantage") or "").strip()
    ):
      confirmed_restatement = _extract_confirmed_restatement(messages)
      proposed_advantage = _propose_ops_competitive_advantage(
        ops_json=ops_json,
        business_facts=business_facts,
        shared_context=shared_context,
        confirmed_restatement=confirmed_restatement,
      )
      proposed_advantage = sanitize_fact_template(str(proposed_advantage or "").strip())
      if proposed_advantage:
        assistant_text = (
          f"{COMPETITIVE_ADVANTAGE_PREFIX} {proposed_advantage}\n\n"
          f"{COMPETITIVE_ADVANTAGE_QUESTION}"
        )
        finalize_ready = False

    if (
      str(focus).strip().lower() == "ops"
      and finalize_ready
      and ops_ready_for_wrap
      and str((ops_json or {}).get("competitive_advantage") or "").strip()
      and not _has_confirmed_milestone(ops_json)
      and not pending_ops_milestone
    ):
      # Ask for milestone once, after competitive advantage is set; use a pending flag so
      # the next user reply is interpreted as an ops.milestones patch.
      assistant_text = OPS_MILESTONE_QUESTION
      finalize_ready = False
      pending_ops_milestone = True

    # Safety: avoid dead-end assistant replies with no next question.
    # If GPT responded with an acknowledgement only (no question) and we're not finalizing,
    # immediately ask for the next single question so the user isn't forced to type "ok".
    if (not finalize_ready) and assistant_text and ("?" not in assistant_text):
      continue_instruction = (
        "Continue. Ask exactly ONE next question for the client to answer (do not bundle)."
      )
      followup_messages = [
        *messages,
        user_msg,
        {"role": "assistant", "content": assistant_text},
        {"role": "user", "content": continue_instruction},
      ]
      try:
        if focus == "ops":
          followup_turn = consultant_chat_turn(
            intake_context=intake_context, conversation_messages=followup_messages
          )
        elif focus == "market":
          followup_turn = target_market_chat_turn(
            intake_context=intake_context, conversation_messages=followup_messages
          )
        elif focus == "people":
          followup_turn = people_capability_chat_turn(
            intake_context=intake_context, conversation_messages=followup_messages
          )
        elif focus == "financials":
          followup_turn, financials_json = _build_financials_live_turn(
            conn=conn,
            intake_context=intake_context,
            conversation_messages=followup_messages,
            shared_context=shared_context,
            financials_json=financials_json,
            financials_year1_json=financials_year1_json,
            guardrail_triggered=guardrail_triggered,
          )
        else:
          followup_turn = {"assistant_message": ""}
        followup_text = sanitize_fact_template(str(followup_turn.get("assistant_message") or "").strip())
        if focus == "market":
          followup_text = _strip_acs_codes(followup_text)
        if focus == "financials":
          followup_text = _append_constraints_snippet(
            followup_text,
            revenue_constraints_snippet,
            messages,
            force=True,
          )
        if followup_text:
          # If the follow-up turn indicates the consult is complete, carry that
          # completion signal forward so we finalize immediately instead of
          # returning a dead-end statement that forces the user to type "ok".
          if bool(followup_turn.get("finalize_ready", False)):
            finalize_ready = True
            assistant_text = followup_text.strip()
          else:
            assistant_text = f"{assistant_text}\n\n{followup_text}".strip()
      except Exception:
        # Best-effort; if follow-up fails, keep the original reply.
        pass

    if str(focus).strip().lower() == "financials" and bool(turn.get("transition_to_done")):
      assistant_final = str(turn.get("assistant_message") or "").strip()
      _persist_intake_completion(
        new_messages=[user_msg, {"role": "assistant", "content": assistant_final}],
        ops_value=ops_json,
        market_value=market_json,
        people_value=people_json,
        financials_value=financials_json,
        financials_year1_value=financials_year1_json,
        marketing_value=_refresh_marketing_model(),
        confirmations_value={"financials": True},
        flat_fields_value=_finalize_flag_field("financials", True),
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": "done",
          "awaiting_confirmation": False,
          "done": True,
          "action": "intake_complete",
          "assistant_message": assistant_final,
        }
      )
    if not finalize_ready:
      review_people = None
      if str(focus).strip().lower() == "people" and review_ready:
        review_people = people_capability_finalize(
          intake_context=intake_context,
          conversation_messages=[*messages, user_msg, {"role": "assistant", "content": assistant_text}],
        )
        for k, v in list(review_people.items() if isinstance(review_people, dict) else []):
          if isinstance(v, str):
            review_people[k] = sanitize_fact_template(v)
        try:
          from people_roles import (  # type: ignore
            apply_oews_wages,
            apply_oews_wages_to_people,
            format_roles_summary,
          )

          roles = review_people.get("inferred_roles") if isinstance(review_people, dict) else None
          roles = roles if isinstance(roles, list) else []
          people = review_people.get("people") if isinstance(review_people, dict) else None
          people = people if isinstance(people, list) else []
          enriched_people = apply_oews_wages_to_people(
            conn,
            people=people,
            business_type=ops_json.get("business_type"),
            business_stage=ops_json.get("business_stage"),
            address_state=business_facts.get("address_state"),
            address=business_facts.get("address"),
            business_naics_6=ops_json.get("business_naics_6"),
          )
          enriched_roles = apply_oews_wages(
            conn,
            roles=roles,
            business_type=ops_json.get("business_type"),
            business_stage=ops_json.get("business_stage"),
            address_state=business_facts.get("address_state"),
            address=business_facts.get("address"),
            business_naics_6=ops_json.get("business_naics_6"),
          )
          review_people["business_naics_6"] = ops_json.get("business_naics_6")
          review_people["people"] = enriched_people
          review_people["inferred_roles"] = enriched_roles
          review_people["inferred_roles_summary"] = format_roles_summary(enriched_roles)
        except Exception:
          if isinstance(review_people, dict):
            if "inferred_roles" not in review_people:
              review_people["inferred_roles"] = []
            if "inferred_roles_summary" not in review_people:
              review_people["inferred_roles_summary"] = ""
            if "business_naics_6" not in review_people:
              review_people["business_naics_6"] = None
      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
        operating_model_json=ops_json if str(focus).strip().lower() == "ops" else None,
        target_market_json=market_json if str(focus).strip().lower() == "market" else None,
        financials_json=financials_json if focus == "financials" else None,
        marketing_model_json=_refresh_marketing_model(),
        active_focus=focus,
        business_facts=business_facts,
        financials_year1_json=financials_year1_json if focus == "financials" else None,
        pending_ops_milestone_json=pending_ops_milestone if focus == "ops" else None,
        flat_fields=_finalize_flag_field(focus, False),
        people_json=review_people if review_ready else (people_json if str(focus).strip().lower() == "people" else None),
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": focus,
          "awaiting_confirmation": False,
          "done": False,
          "action": "continue",
          "assistant_message": assistant_text,
        }
      )

    # Finalize the current focus into structured JSON, then ask for confirmation.
    final_messages = [*messages, user_msg, {"role": "assistant", "content": assistant_text}]

    if focus == "ops":
      business_type_candidates = ops_json.get("business_type_candidates")
      if not isinstance(business_type_candidates, list):
        business_type_candidates = []
      intake_context["business_type_candidates"] = business_type_candidates
      final_obj = consultant_finalize(intake_context=intake_context, conversation_messages=final_messages)
      for k, v in list(final_obj.items() if isinstance(final_obj, dict) else []):
        if isinstance(v, str):
          final_obj[k] = sanitize_fact_template(v)
      existing_advantage = str((ops_json or {}).get("competitive_advantage") or "").strip()
      if (
        existing_advantage
        and isinstance(final_obj, dict)
        and not str(final_obj.get("competitive_advantage") or "").strip()
      ):
        final_obj["competitive_advantage"] = existing_advantage
      if isinstance(final_obj, dict):
        lob_models = final_obj.get("lob_models")
        if isinstance(lob_models, list) and len(lob_models) == 1:
          products = lob_models[0].get("products") if isinstance(lob_models[0], dict) else None
          if isinstance(products, list) and len(products) == 1 and isinstance(products[0], dict):
            product = products[0]

            def _is_missing_number(value: Any) -> bool:
              if value is None:
                return True
              if isinstance(value, bool):
                return True
              try:
                return float(value) <= 0
              except Exception:
                return True

            def _maybe_set_text(field: str) -> None:
              if not final_obj.get(field) and product.get(field) is not None:
                final_obj[field] = product.get(field)

            def _maybe_set_number(field: str) -> None:
              if _is_missing_number(final_obj.get(field)) and product.get(field) is not None:
                final_obj[field] = product.get(field)

            _maybe_set_text("unit_name")
            _maybe_set_text("unit_description")
            _maybe_set_text("unit_cadence")
            _maybe_set_number("unit_price")
            _maybe_set_number("units_per_week_capacity")
            _maybe_set_number("units_per_period_capacity")
            _maybe_set_number("operating_periods_per_year")
            _maybe_set_number("utilization_rate")
      # Capacity compatibility: fill missing week/period fields deterministically.
      final_obj = _normalize_ops_capacity_compat(final_obj)
      try:
        try:
          from business_type_naics import get_naics_from_business_type  # type: ignore
        except Exception:
          from client_intake_and_finmo.business_type_naics import (  # type: ignore
            get_naics_from_business_type,
          )

        if final_obj.get("business_type"):
          final_obj["business_naics_6"] = get_naics_from_business_type(
            conn, final_obj.get("business_type")
          )
      except Exception:
        if "business_naics_6" not in final_obj:
          final_obj["business_naics_6"] = None
      try:
        _enrich_milestones_timing(final_obj, reference_date=current_date)
      except Exception:
        pass

      # Persist a rendered business_description_summary (no {{fact:...}} placeholders).
      # Keep the change scoped to this single field only.
      try:
        try:
          from fact_templates import render_fact_template  # type: ignore
        except Exception:
          from client_intake_and_finmo.fact_templates import render_fact_template  # type: ignore

        if isinstance(final_obj, dict) and str(final_obj.get("business_description_summary") or "").strip():
          business_facts_for_render = {
            "name": str(business_facts.get("name") or "").strip(),
            "address": str(business_facts.get("address") or "").strip(),
            "start_date": str(business_facts.get("start_date") or "").strip(),
          }
          shared_ctx_for_render = {
            "operating_model": final_obj,
            "target_market": market_json,
            "people_capability": people_json,
            "financials": financials_json,
          }
          final_obj["business_description_summary"] = render_fact_template(
            str(final_obj.get("business_description_summary") or ""),
            shared_context=shared_ctx_for_render,
            business_facts=business_facts_for_render,
          ).strip()
      except Exception:
        pass
      # Do not show the Ops summary for confirmation. Assume affirmative and
      # advance directly to Target Market after persisting the finalized ops_json.
      if not str((ops_json or {}).get("competitive_advantage") or "").strip():
        confirmed_restatement = _extract_confirmed_restatement(messages)
        proposed_advantage = _propose_ops_competitive_advantage(
          ops_json=ops_json,
          business_facts=business_facts,
          shared_context=shared_context,
          confirmed_restatement=confirmed_restatement,
        )
        proposed_advantage = sanitize_fact_template(str(proposed_advantage or "").strip())
        assistant_text = (
          f"{COMPETITIVE_ADVANTAGE_PREFIX} {proposed_advantage}\n\n"
          f"{COMPETITIVE_ADVANTAGE_QUESTION}"
        ).strip()
        append_messages(
          conn,
          draft_id=str(draft_id).strip(),
          new_messages=[user_msg, {"role": "assistant", "content": assistant_text}],
          operating_model_json=ops_json,
          marketing_model_json=_refresh_marketing_model(),
          active_focus="ops",
          business_facts=business_facts,
          pending_ops_milestone_json=pending_ops_milestone,
          flat_fields=_finalize_flag_field("ops", False),
        )
        return jsonify(
          {
            "status": "ok",
            "draft_id": str(draft_id).strip(),
            "client_id": client_id,
            "active_focus": "ops",
            "awaiting_confirmation": True,
            "done": False,
            "action": "continue",
            "assistant_message": assistant_text,
          }
        )

      ops_json = final_obj
      try:
        shared_context = dict(shared_context or {})
        shared_context["operating_model"] = ops_json
        shared_context["target_market"] = market_json
        shared_context["people_capability"] = people_json
        shared_context["financials"] = financials_json
      except Exception:
        pass

      next_focus = "market"
      start_instruction = _start_instruction_for_focus(next_focus)
      turn_messages = [*messages, user_msg, {"role": "user", "content": start_instruction}]
      intake_context_next: Dict[str, Any] = {
        "client_id": client_id,
        "draft_id": str(draft_id).strip(),
        "business_name": business_facts.get("name"),
        "business_start_date": business_facts.get("start_date"),
        "address": business_facts.get("address"),
        "current_date": current_date_iso,
        "business_stage_hint": business_stage_hint,
        "shared_context": shared_context,
        "operating_model_json": ops_json,
        "target_market_json": market_json,
        "people_json": people_json,
        "financials_json": financials_json,
        "fulfillment_json": fulfillment_json,
      }
      consumer_type = str((ops_json or {}).get("consumer_type") or "consumer").strip().lower()
      if consumer_type not in ("consumer", "b2b", "mixed"):
        consumer_type = "consumer"
      intake_context_next["consumer_type"] = consumer_type
      market_turn = target_market_chat_turn(
        intake_context=intake_context_next, conversation_messages=turn_messages
      )
      next_assistant = str((market_turn or {}).get("assistant_message") or "").strip()
      assistant_final = f"Great, let's move on to Target Market.\n\n{next_assistant}".strip()
      assistant_final = _strip_acs_codes(sanitize_fact_template(str(assistant_final or "").strip()))

      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_final}],
        operating_model_json=ops_json,
        target_market_json=market_json,
        marketing_model_json=_refresh_marketing_model(),
        active_focus=next_focus,
        confirmations={"ops": True},
        business_facts=business_facts,
        flat_fields=_finalize_flag_field("ops", True),
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": next_focus,
          "awaiting_confirmation": False,
          "done": False,
          "action": "confirm_proceed",
          "assistant_message": assistant_final,
        }
      )
    elif focus == "market":
      consumer_type = str((ops_json or {}).get("consumer_type") or "consumer").strip().lower()
      mapping_rows: List[Dict[str, Any]] = []
      if consumer_type != "b2b":
        mapping_rows = _fetch_target_market_mapping_rows(conn)
      final_obj = target_market_finalize(
        intake_context={**intake_context, "consumer_type": consumer_type},
        conversation_messages=final_messages,
        mapping_rows=mapping_rows,
      )
      for k, v in list(final_obj.items() if isinstance(final_obj, dict) else []):
        if isinstance(v, str):
          final_obj[k] = sanitize_fact_template(v)
      if isinstance(final_obj, dict):
        final_obj.pop("target_market_summary", None)
        final_obj.pop("_pending_income_intent", None)
        final_obj.pop("_pending_capture_field", None)
        final_obj.pop("_pending_gender_focus", None)
        final_obj.pop("_pending_age_range", None)

      # Persist a rendered marketing_plan_summary (no {{fact:...}} placeholders).
      # Keep the change scoped to this single field only.
      try:
        try:
          from fact_templates import render_fact_template  # type: ignore
        except Exception:
          from client_intake_and_finmo.fact_templates import render_fact_template  # type: ignore

        if isinstance(final_obj, dict) and str(final_obj.get("marketing_plan_summary") or "").strip():
          business_facts_for_render = {
            "name": str(business_facts.get("name") or "").strip(),
            "address": str(business_facts.get("address") or "").strip(),
            "start_date": str(business_facts.get("start_date") or "").strip(),
          }
          shared_ctx_for_render = {
            "operating_model": ops_json,
            "target_market": final_obj,
            "people_capability": people_json,
            "financials": financials_json,
          }
          final_obj["marketing_plan_summary"] = render_fact_template(
            str(final_obj.get("marketing_plan_summary") or ""),
            shared_context=shared_ctx_for_render,
            business_facts=business_facts_for_render,
          ).strip()
      except Exception:
        pass
      market_json = final_obj

      # Show the finalized marketing_plan_summary to the client for confirmation/counter
      # before advancing. This replaces the older in-chat "promotion model" proposal.
      assistant_final = sanitize_fact_template(
        str((market_json or {}).get("marketing_plan_summary") or "").strip()
      )
      assistant_final = _strip_acs_codes(assistant_final)
      assistant_final = f"{assistant_final}\n\n{MARKET_CONFIRM_QUESTION}".strip()

      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_final}],
        target_market_json=market_json,
        marketing_model_json=_refresh_marketing_model(),
        active_focus="market",
        business_facts=business_facts,
        flat_fields=_finalize_flag_field("market", True),
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": "market",
          "awaiting_confirmation": True,
          "done": False,
          "action": "continue",
          "assistant_message": assistant_final,
        }
      )
    elif focus == "people":
      final_obj = people_capability_finalize(intake_context=intake_context, conversation_messages=final_messages)
      for k, v in list(final_obj.items() if isinstance(final_obj, dict) else []):
        if isinstance(v, str):
          final_obj[k] = sanitize_fact_template(v)
      try:
        from people_roles import (  # type: ignore
          apply_oews_wages,
          apply_oews_wages_to_people,
          format_roles_summary,
        )

        roles = final_obj.get("inferred_roles") if isinstance(final_obj, dict) else None
        roles = roles if isinstance(roles, list) else []
        people_list = final_obj.get("people") if isinstance(final_obj, dict) else None
        people_list = people_list if isinstance(people_list, list) else []
        enriched_people = apply_oews_wages_to_people(
          conn,
          people=people_list,
          business_type=ops_json.get("business_type"),
          business_stage=ops_json.get("business_stage"),
          address_state=business_facts.get("address_state"),
          address=business_facts.get("address"),
          business_naics_6=ops_json.get("business_naics_6"),
        )
        enriched_roles = apply_oews_wages(
          conn,
          roles=roles,
          business_type=ops_json.get("business_type"),
          business_stage=ops_json.get("business_stage"),
          address_state=business_facts.get("address_state"),
          address=business_facts.get("address"),
          business_naics_6=ops_json.get("business_naics_6"),
        )
        final_obj["business_naics_6"] = ops_json.get("business_naics_6")
        final_obj["people"] = enriched_people
        final_obj["inferred_roles"] = enriched_roles
        final_obj["inferred_roles_summary"] = format_roles_summary(enriched_roles)
      except Exception:
        if "inferred_roles" not in final_obj:
          final_obj["inferred_roles"] = []
        if "inferred_roles_summary" not in final_obj:
          final_obj["inferred_roles_summary"] = ""
        if "business_naics_6" not in final_obj:
          final_obj["business_naics_6"] = None

      # People/HR: show a one-time review (key people + inferred roles) and ask for
      # confirmation. If the client counters, we acknowledge and advance without
      # re-showing this review again.
      if isinstance(final_obj, dict):
        final_obj.pop("key_people_summary", None)
      people_json = final_obj

      # Render People fact templates (no {{fact:...}} placeholders) for display + persistence.
      try:
        try:
          from fact_templates import render_fact_template  # type: ignore
        except Exception:
          from client_intake_and_finmo.fact_templates import render_fact_template  # type: ignore

        if isinstance(people_json, dict):
          business_facts_for_render = {
            "name": str(business_facts.get("name") or "").strip(),
            "address": str(business_facts.get("address") or "").strip(),
            "start_date": str(business_facts.get("start_date") or "").strip(),
          }
          shared_ctx_for_render = {
            "operating_model": ops_json,
            "target_market": market_json,
            "people_capability": people_json,
            "financials": financials_json,
          }
          ppl = people_json.get("people")
          if isinstance(ppl, list):
            for p in ppl:
              if not isinstance(p, dict):
                continue
              for fk, fv in list(p.items()):
                if isinstance(fv, str) and "{{fact:" in fv:
                  p[fk] = render_fact_template(
                    fv, shared_context=shared_ctx_for_render, business_facts=business_facts_for_render
                  ).strip()
          roles = people_json.get("inferred_roles")
          if isinstance(roles, list):
            for r in roles:
              if not isinstance(r, dict):
                continue
              for fk, fv in list(r.items()):
                if isinstance(fv, str) and "{{fact:" in fv:
                  r[fk] = render_fact_template(
                    fv, shared_context=shared_ctx_for_render, business_facts=business_facts_for_render
                  ).strip()
      except Exception:
        pass

      key_people_blocks: List[str] = []
      try:
        people_list = people_json.get("people") if isinstance(people_json, dict) else None
        people_list = people_list if isinstance(people_list, list) else []
        for p in people_list:
          if not isinstance(p, dict):
            continue
          para = p.get("paragraph")
          if isinstance(para, str) and para.strip():
            block = para.strip()
            wage_raw = p.get("annual_wage")
            try:
              wage_val = float(wage_raw)
            except Exception:
              wage_val = None
            if wage_val is not None and wage_val > 0:
              wage_fmt = f"${int(round(wage_val)):,.0f}"
              # Keep wage visible to the client, but embedded in the narrative (no standalone line).
              block = f"{block.rstrip()} Estimated annual wage: {wage_fmt}/year."
            key_people_blocks.append(block)
      except Exception:
        key_people_blocks = []

      inferred_roles_summary = str((people_json or {}).get("inferred_roles_summary") or "").strip()
      parts: List[str] = []
      has_people = bool(key_people_blocks)
      has_roles = bool(inferred_roles_summary)
      if has_people and has_roles:
        parts.append(
          "Review this draft (key people narrative + suggested year-1 roles with wages and timing) and tell me any changes."
        )
      elif has_people:
        parts.append("Review this draft (key people narrative) and tell me any changes.")
      elif has_roles:
        parts.append("Review these suggested year-1 roles (with wages and timing) and tell me any changes.")

      if has_people:
        parts.append("\n\n".join(key_people_blocks))
      if has_roles:
        parts.append(inferred_roles_summary)
      assistant_final = "\n\n".join([p for p in parts if p.strip()]).strip()
      if assistant_final:
        assistant_final = f"{assistant_final}\n\n{PEOPLE_CONFIRM_QUESTION}".strip()
      else:
        assistant_final = PEOPLE_CONFIRM_QUESTION

      append_messages(
        conn,
        draft_id=str(draft_id).strip(),
        new_messages=[user_msg, {"role": "assistant", "content": assistant_final}],
        people_json=people_json,
        marketing_model_json=_refresh_marketing_model(),
        active_focus="people",
        business_facts=business_facts,
        flat_fields=_finalize_flag_field("people", True),
      )
      return jsonify(
        {
          "status": "ok",
          "draft_id": str(draft_id).strip(),
          "client_id": client_id,
          "active_focus": "people",
          "awaiting_confirmation": True,
          "done": False,
          "action": "continue",
          "assistant_message": assistant_final,
        }
      )
    else:
      assistant_final = assistant_text

    assistant_final = sanitize_fact_template(str(assistant_final or "").strip())

    assistant_payload: Dict[str, Any] = {"role": "assistant", "content": assistant_final}

    append_messages(
      conn,
      draft_id=str(draft_id).strip(),
      new_messages=[user_msg, assistant_payload],
      operating_model_json=ops_json if focus == "ops" else None,
      target_market_json=market_json if focus == "market" else None,
      people_json=people_json if focus == "people" else None,
      financials_json=financials_json if focus == "financials" else None,
      financials_year1_json=financials_year1_json if focus == "financials" else None,
      marketing_model_json=_refresh_marketing_model(),
      active_focus=focus,
      business_facts=business_facts,
      flat_fields=_finalize_flag_field(focus, True),
    )

    return jsonify(
      {
        "status": "ok",
        "draft_id": str(draft_id).strip(),
        "client_id": client_id,
        "active_focus": focus,
        "awaiting_confirmation": True,
        "done": False,
        "action": "await_confirmation",
        "assistant_message": assistant_final,
      }
    )
  except Exception as exc:
    app.logger.exception("Failed intake consult: %s", exc)
    return (jsonify({"error": "server_error", "detail": str(exc)}), 500)
  finally:
    try:
      conn.close()
    except Exception:
      pass
